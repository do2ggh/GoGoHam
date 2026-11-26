"""NCDXF/IARU-Bakenanzeige (ab 0.8.14): welches Band ist gerade wohin offen?

Die 18 Baken des internationalen Bakenprojekts senden reihum je 10 Sekunden auf 14,100 /
18,110 / 21,150 / 24,930 / 28,200 MHz (Zyklus 3 Minuten). Das Reverse Beacon Network (RBN)
meldet, welcher Empfänger („Skimmer“) welche Bake wie stark gehört hat – als Typ „NCDXF B“.

GoGoHam zählt nur Empfänger in deiner Nähe (Umkreis RADIUS_KM, Lage aus der Länderdatei):
was sie hören, kommt sehr wahrscheinlich auch bei dir an. Das Funkgerät bleibt unberührt.

Das RBN meldet je Empfänger und Bake höchstens etwa alle 10–12 Minuten und liefert keine
Vorgeschichte – nach dem Einschalten füllt sich die Tabelle in 10–15 Minuten.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .locator import bearing_deg, distance_km

RBN_HOST, RBN_PORT = "telnet.reversebeacon.net", 7000
RADIUS_KM = 1000     # 0.8.14: RBN-Tagesdaten – bis 1000 km fast dasselbe Bild wie bis 500 km;
                     # darüber (GM, EI, ES, IT9) liegen Empfänger mit oft anderer Ausbreitung

# Bakenbänder, die GoGoHam zeigt (17 und 12 m sind WARC – im Contest nicht erlaubt)
BEACON_FREQ = {"20": 14100000, "15": 21150000, "10": 28200000}
FREQ_TOL = 1500                      # Hz

GOOD, FAIR, NONE = "good", "fair", "none"
FRESH_S = 15 * 60                    # bis hierhin „gerade gehört“
MAX_AGE_S = 30 * 60                  # danach vergessen
STRONG_DB = 10                       # ab hier „gut gehört“


@dataclass(frozen=True)
class Beacon:
    call: str
    place: str                       # deutsch; übersetzt wird in der Anzeige
    lat: float
    lon: float


# Reihenfolge = Sendefolge im 3-Minuten-Zyklus
BEACONS = (
    Beacon("4U1UN", "UNO New York, USA", 40.75, -73.97),
    Beacon("VE8AT", "Eureka, Kanada", 79.99, -85.93),
    Beacon("W6WX", "Mt. Umunhum, USA", 37.16, -121.90),
    Beacon("KH6RS", "Maui, Hawaii", 20.75, -156.43),
    Beacon("ZL6B", "Masterton, Neuseeland", -41.06, 175.60),
    Beacon("VK6RBP", "Rolystone, Australien", -32.11, 116.05),
    Beacon("JA2IGY", "Mt. Asama, Japan", 34.45, 136.78),
    Beacon("RR9O", "Nowosibirsk, Russland", 54.98, 82.90),
    Beacon("VR2B", "Hongkong", 22.27, 114.15),
    Beacon("4S7B", "Colombo, Sri Lanka", 6.90, 79.87),
    Beacon("ZS6DN", "Pretoria, Südafrika", -25.90, 28.28),
    Beacon("5Z4B", "Kikuyu, Kenia", -1.25, 36.66),
    Beacon("4X6TU", "Tel Aviv, Israel", 32.05, 34.78),
    Beacon("OH2B", "Lohja, Finnland", 60.32, 24.83),
    Beacon("CS3B", "Madeira, Portugal", 32.80, -17.25),
    Beacon("LU4AA", "Buenos Aires, Argentinien", -34.62, -58.36),
    Beacon("OA4B", "Lima, Peru", -12.07, -76.95),
    Beacon("YV5B", "Caracas, Venezuela", 9.10, -67.80),
)
BY_CALL = {b.call: b for b in BEACONS}

_DB = re.compile(r"(-?\d+)\s*dB", re.IGNORECASE)


def contest_bands(bands) -> list[str]:
    """Bakenbänder, die der Contest hat (in der Reihenfolge 20, 15, 10)."""
    have = set(bands or ())
    return [b for b in BEACON_FREQ if b in have]


def beacon_band(call: str, freq: int) -> str | None:
    """Band, wenn Rufzeichen eine NCDXF-Bake ist und die Frequenz zur Bakenfrequenz passt."""
    if call.upper().split("/")[0] not in BY_CALL:
        return None
    for band, f in BEACON_FREQ.items():
        if abs(int(freq) - f) <= FREQ_TOL:
            return band
    return None


def is_beacon_spot(spot) -> bool:
    """Für den Empfangs-Thread: nur Baken-Meldungen behalten (das RBN liefert ~4 Spots/s)."""
    return beacon_band(spot.call, spot.freq) is not None


def snr_db(comment: str) -> int | None:
    m = _DB.search(comment or "")
    return int(m.group(1)) if m else None


def bearing(home: tuple[float, float] | None, b: Beacon) -> int | None:
    if not home:
        return None
    return int(round(bearing_deg(home[0], home[1], b.lat, b.lon))) % 360


@dataclass
class Heard:
    skimmer: str
    km: int
    db: int | None
    when: float                      # time.time()


@dataclass
class Cell:
    level: str = NONE
    best_db: int | None = None
    heard: list[Heard] = field(default_factory=list)     # neueste zuerst


class BeaconBoard:
    """Sammelt Baken-Meldungen der Empfänger in der Nähe und bewertet sie je Bake und Band.

    locate(call) -> (lat, lon) oder None: Lage eines Empfängers (aus der Länderdatei)."""

    def __init__(self, home: tuple[float, float] | None, locate, radius_km: int = RADIUS_KM):
        self.home = home
        self.locate = locate
        self.radius = radius_km
        self._km: dict[str, int | None] = {}            # Empfänger -> Entfernung (Cache)
        self._data: dict[tuple[str, str], dict[str, Heard]] = {}
        self.version = 0
        self.received = 0                                # alle Baken-Meldungen (auch ferne)

    def skimmer_km(self, skimmer: str) -> int | None:
        if skimmer not in self._km:
            pos = self.locate(skimmer) if self.home else None
            self._km[skimmer] = (int(round(distance_km(self.home[0], self.home[1], *pos)))
                                 if pos else None)
        return self._km[skimmer]

    def add(self, spot, now: float | None = None) -> bool:
        """Meldung übernehmen, wenn sie von einem Empfänger in der Nähe stammt."""
        band = beacon_band(spot.call, spot.freq)
        if not band:
            return False
        self.received += 1
        skimmer = spot.spotter_call
        km = self.skimmer_km(skimmer)
        if km is None or km > self.radius:
            return False
        call = spot.call.upper().split("/")[0]
        now = time.time() if now is None else now
        self._data.setdefault((call, band), {})[skimmer] = Heard(skimmer, km, snr_db(spot.comment),
                                                                now)
        self.version += 1
        return True

    def expire(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        for key in list(self._data):
            d = self._data[key]
            for sk in [s for s, h in d.items() if now - h.when > MAX_AGE_S]:
                del d[sk]
                self.version += 1
            if not d:
                del self._data[key]

    def cell(self, call: str, band: str, now: float | None = None) -> Cell:
        now = time.time() if now is None else now
        heard = sorted((h for h in self._data.get((call, band), {}).values()
                        if now - h.when <= MAX_AGE_S), key=lambda h: -h.when)
        if not heard:
            return Cell()
        fresh = [h for h in heard if now - h.when <= FRESH_S]
        dbs = [h.db for h in (fresh or heard) if h.db is not None]
        best = max(dbs) if dbs else None
        if fresh and best is not None and best >= STRONG_DB:
            level = GOOD
        else:
            level = FAIR
        return Cell(level, best, heard)

    def clear(self) -> None:
        self._data.clear()
        self.version += 1
