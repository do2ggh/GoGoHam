"""Bandöffnungs-Vorschau (ab 0.8.27): grobe Schätzung, welches Band wohin offen ist.

Bewusst eine einfache Faustregel-Rechnung – offline, ohne Zusatzprogramm, gröber als große
Vorhersageprogramme. Sie kennt drei Dinge:

1. **Wie hoch die Bänder gehen (MUF):** aus dem Sonnenfluss (SFI → Sonnenfleckenzahl) und der
   Sonnenhöhe an den Umkehrpunkten des Wegs. Tagsüber ist die F2-Schicht dichter → höhere Bänder.
2. **Wie stark die tiefen Bänder geschluckt werden (LUF):** die D-Schicht entsteht nur bei
   Tageslicht; je mehr Tageslicht auf dem Weg und je mehr Sprünge, desto schlechter 160/80/40 m.
3. **Unruhe auf dem Magnetfeld (K-Wert):** drückt die MUF etwas, vor allem aber Wege über den
   hohen Norden (Polarlicht-Zone).

Ergebnis je Band: GOOD / FAIR / POOR / CLOSED. Nur Short Path, nur Kurzwelle (160–10 m).
Fehlt das Funkwetter, wird mit mittlerer Sonnenaktivität gerechnet (nur Tag/Nacht zählt dann).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .worldmap import angular_distance, bearing, destination, subsolar

EARTH_KM = 6371.0
CLOSED, POOR, FAIR, GOOD = 0, 1, 2, 3

# Mittenfrequenz je Kurzwellenband in MHz (UKW wird nicht geschätzt)
BAND_MHZ = {"160": 1.84, "80": 3.6, "60": 5.36, "40": 7.05, "30": 10.12, "20": 14.1,
            "17": 18.1, "15": 21.1, "12": 24.9, "10": 28.3}
DEFAULT_BANDS = ("160", "80", "40", "20", "15", "10")

# Bezugspunkte je Kontinent (Breite, Länge; Ost positiv) – Gegenden mit viel Funkbetrieb.
# Es zählt der beste Punkt: „irgendwo auf dem Kontinent offen“ (passt zum ✓). 0.8.27.1
CONTINENTS = ("EU", "NA", "SA", "AF", "AS", "OC")
REGIONS = {
    "EU": (("eu_c", 50.0, 10.0), ("eu_w", 40.0, -4.0), ("eu_n", 60.0, 15.0),
           ("eu_e", 55.7, 37.6), ("eu_s", 38.0, 23.0)),
    "NA": (("na_e", 41.0, -74.0), ("na_m", 41.0, -90.0), ("na_w", 37.0, -120.0),
           ("na_c", 18.0, -70.0)),
    "SA": (("sa_n", 8.0, -66.0), ("sa_b", -15.0, -47.0), ("sa_s", -34.0, -60.0)),
    "AF": (("af_nw", 28.0, -15.0), ("af_w", 8.0, -5.0), ("af_c", 0.0, 20.0),
           ("af_e", -1.0, 37.0), ("af_s", -28.0, 26.0)),
    "AS": (("as_me", 32.0, 40.0), ("as_r", 55.0, 75.0), ("as_in", 20.0, 78.0),
           ("as_cn", 33.0, 112.0), ("as_jp", 36.0, 138.0), ("as_se", 10.0, 105.0)),
    "OC": (("oc_ae", -33.0, 151.0), ("oc_aw", -32.0, 116.0), ("oc_nz", -41.0, 174.0),
           ("oc_id", -6.0, 107.0), ("oc_hi", 21.0, -157.0)),
}
TARGETS = {c: (r[0][1], r[0][2]) for c, r in REGIONS.items()}   # erster Punkt (für Tests)

MIN_KM = 800            # näher läuft eher über Bodenwelle – so nah rechnen wir nicht
NEAR_KM = 1000          # ✓ nur von Meldern bis hierhin (wie die Bakenanzeige)
GROUND_KM = 300         # ✓ nicht für Verbindungen darunter (Bodenwelle)
LAG_H = ((0, 1.0), (1, 0.85), (2, 0.65), (3, 0.45))   # Nachwirken der F2-Schicht
HOP_KM = 4000           # längster F2-Sprung
DEFAULT_SFI = 100       # ohne Funkwetter: mittlere Sonnenaktivität
GEOMAG_POLE = (80.8, -72.7)     # nördlicher geomagnetischer Pol (IGRF, 2025)


def sunspots(sfi: float) -> float:
    """Sonnenfleckenzahl aus dem Sonnenfluss: SFI = 63,7 + 0,728 R + 0,00089 R²."""
    s = max(64.0, float(sfi))
    a, b, c = 0.00089, 0.728, 63.7 - s
    return max(0.0, (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a))


def sun_elev(lat: float, lon: float, sun: tuple[float, float]) -> float:
    sl, so = math.radians(sun[0]), math.radians(sun[1])
    la, lo = math.radians(lat), math.radians(lon)
    s = math.sin(la) * math.sin(sl) + math.cos(la) * math.cos(sl) * math.cos(lo - so)
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def day_factor(elev: float) -> float:
    """0 = Nacht (Sonne > 6° unter dem Horizont) … 1 = Sonne ab 30° hoch."""
    return max(0.0, min(1.0, (elev + 6.0) / 36.0)) ** 0.7


def winterness(lat: float, sun: tuple[float, float]) -> float:
    """+1 = tiefer Winter am Ort, −1 = Hochsommer, 0 = Tropen oder Tagundnachtgleiche."""
    return -sun[0] / 23.44 * math.copysign(min(1.0, abs(lat) / 30.0), lat)


def fof2(elev, r: float, winter: float = 0.0) -> float:
    """Grenzfrequenz der F2-Schicht in MHz (grobe Mittelwerte mittlerer Breiten).

    elev: Sonnenhöhe jetzt – oder eine Liste [(Sonnenhöhe vor h Stunden, Gewicht)]: Die
    Schicht baut sich nach Sonnenuntergang nur langsam ab (über etwa 3 Stunden, 0.8.27.1).
    Winter-Effekt: im Winter ist die Schicht mittags dichter, im Sommer nachts."""
    noon = (6.0 + 0.06 * r) * (1.0 + 0.2 * winter * min(1.0, r / 100.0))
    night = (2.8 + 0.022 * r) * (1.0 - 0.15 * winter)
    if isinstance(elev, (int, float)):
        d = day_factor(elev)
    else:
        d = max(day_factor(e) * w for e, w in elev)
    return night + (noon - night) * d


def m_factor(hop_km: float) -> float:
    """Wie viel höher als foF2 ein Sprung dieser Länge reicht (M(3000) ≈ 3,4)."""
    return 1.0 + 2.4 * min(1.0, hop_km / 3000.0) ** 0.7


def geomag_lat(lat: float, lon: float) -> float:
    return 90.0 - math.degrees(angular_distance(lat, lon, *GEOMAG_POLE))


@dataclass
class Estimate:
    level: int
    muf: float                   # MHz
    luf: float                   # MHz
    km: int
    hops: int
    polar: bool = False          # Weg führt durch die Polarlicht-Zone
    k_penalty: int = 0           # um so viele Stufen wegen des K-Werts abgewertet
    region: str = ""             # bester Bezugspunkt (REGIONS), z. B. „na_e“


@dataclass
class Path:
    km: float
    hops: int
    muf: float
    luf: float
    max_gmlat: float
    notes: list = field(default_factory=list)


def path(home: tuple[float, float], target: tuple[float, float], when: datetime,
         sfi: float | None, k: float | None = None) -> Path:
    """MUF/LUF für den kurzen Weg home → target zur Zeit when (UTC)."""
    r = sunspots(DEFAULT_SFI if sfi is None else sfi)
    d = angular_distance(home[0], home[1], target[0], target[1])
    az = bearing(home[0], home[1], target[0], target[1]) if d > 1e-6 else 90.0
    km = max(MIN_KM, d * EARTH_KM)
    hops = max(1, math.ceil(km / HOP_KM))
    hop = km / hops
    sun = subsolar(when)
    suns = [(subsolar(when - timedelta(hours=h)), w) for h, w in LAG_H]
    at = lambda dist_km: destination(home[0], home[1], az, dist_km / EARTH_KM)  # noqa: E731
    # Umkehrpunkte: Mitte des Wegs, bei mehreren Sprüngen je einer am Anfang und am Ende
    if hops == 1:
        cps = [at(km / 2)]
    else:
        cps = [at(hop / 2), at(km - hop / 2)]
    muf = min(fof2([(sun_elev(*p, s), w) for s, w in suns], r, winterness(p[0], sun))
              for p in cps) * m_factor(hop)
    if k is not None and k > 3:
        muf *= 1.0 - 0.04 * (k - 3)               # Magnetsturm: F2-Schicht dünnt aus
    # Bodenpunkte der Sprünge (Start, Zwischenlandungen, Ziel): dort geht der Weg zweimal
    # durch die D-Schicht – Dämpfung nach Sonnenhöhe
    grounds = [at(km * i / hops) for i in range(hops + 1)]
    sunlit = sum(max(0.0, math.sin(math.radians(sun_elev(*p, sun)))) ** 0.5 for p in grounds)
    luf = max(1.0, 3.6 * math.sqrt(sunlit) * math.sqrt(1.0 + 0.01 * r))
    samples = [at(km * i / 20) for i in range(21)]
    gm = max(abs(geomag_lat(*p)) for p in samples)
    return Path(km, hops, muf, luf, gm)


def rate(p: Path, mhz: float, k: float | None = None) -> Estimate:
    ratio = mhz / p.muf
    if ratio <= 0.85:              # MUF ist ein Mittelwert – an vielen Tagen geht es höher
        hi = GOOD
    elif ratio <= 1.0:
        hi = FAIR
    elif ratio <= 1.25:
        hi = POOR
    else:
        hi = CLOSED
    lr = mhz / p.luf
    if lr >= 2.0:
        lo = GOOD
    elif lr >= 1.4:
        lo = FAIR
    elif lr >= 1.0:
        lo = POOR
    else:
        lo = CLOSED
    level = min(hi, lo)
    polar = p.max_gmlat >= 58.0
    pen = 0
    if k is not None:
        if polar and k >= 5:
            pen = 2
        elif polar and k >= 4:
            pen = 1
        elif k >= 6:
            pen = 1
    if pen and level > CLOSED:
        level = max(CLOSED, level - pen)
    return Estimate(level, p.muf, p.luf, int(round(p.km)), p.hops, polar, pen)


def hf_bands(bands) -> list[str]:
    """Kurzwellenbänder des Contests in Bandreihenfolge (tiefe zuerst)."""
    have = set(bands or ())
    return [b for b in BAND_MHZ if b in have]


def best(home, cont: str, bands, when: datetime, sfi, k) -> dict[str, Estimate]:
    """Band → beste Schätzung über alle Bezugspunkte des Kontinents."""
    out: dict[str, Estimate] = {}
    for key, lat, lon in REGIONS[cont]:
        p = path(home, (lat, lon), when, sfi, k)
        for b in bands:
            e = rate(p, BAND_MHZ[b], k)
            e.region = key
            old = out.get(b)
            # besser = höhere Stufe; bei Gleichstand der Punkt mit mehr Luft zur MUF
            if old is None or (e.level, -BAND_MHZ[b] / e.muf) > (old.level,
                                                                   -BAND_MHZ[b] / old.muf):
                out[b] = e
    return out


def grid_now(home, bands, when: datetime, sfi, k) -> dict[tuple[str, str], Estimate]:
    """(Band, Kontinent) → Schätzung für jetzt."""
    out = {}
    for c in CONTINENTS:
        for b, e in best(home, c, bands, when, sfi, k).items():
            out[(b, c)] = e
    return out


def hours(when: datetime, n: int = 12) -> list[datetime]:
    """Jetzt und die nächsten n Stunden (jeweils zur vollen Stunde + 30 min)."""
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    base = when.replace(minute=30, second=0, microsecond=0)
    if when.minute >= 30:
        base += timedelta(hours=1)
    return [when] + [base + timedelta(hours=i) for i in range(n)]


def grid_hours(home, bands, cont: str, times: list[datetime], sfi, k
               ) -> dict[tuple[str, int], Estimate]:
    """(Band, Spaltennummer) → Schätzung für den gewählten Kontinent."""
    out = {}
    for i, t in enumerate(times):
        for b, e in best(home, cont, bands, t, sfi, k).items():
            out[(b, i)] = e
    return out


# ------------------------------------------------------------------ tatsächlich gehört
HEARD_S = 30 * 60


def heard(spots, beacon_cells, cont_of, locate, home, now: float
          ) -> dict[tuple[str, str], int]:
    """(Band, Kontinent) → Anzahl Meldungen der letzten 30 Minuten.

    spots: Cluster-Spots (dxcluster.Spot); zählen nur, wenn der Melder in der Nähe sitzt
    (bis NEAR_KM) und die Gegenstation mindestens GROUND_KM von ihm weg ist – sonst sagt
    der Spot nichts über den Weg von hier (0.8.27.1).
    beacon_cells: [(Rufzeichen der Bake, Band, Anzahl)] – vom RBN in der Nähe gehört.
    cont_of(call) → Kontinent oder None; locate(call) → (Breite, Länge) oder None."""
    out: dict[tuple[str, str], int] = {}
    for sp in spots:
        band = sp.band
        if band not in BAND_MHZ or now - sp.received > HEARD_S:
            continue
        where = locate(sp.spotter_call)
        if home is None or where is None or \
                angular_distance(home[0], home[1], *where) * EARTH_KM > NEAR_KM:
            continue
        dx = locate(sp.call)
        if dx is None or angular_distance(where[0], where[1], *dx) * EARTH_KM < GROUND_KM:
            continue
        c = cont_of(sp.call)
        if c in TARGETS:
            out[(band, c)] = out.get((band, c), 0) + 1
    for call, band, n in beacon_cells:
        c = cont_of(call)
        if c in TARGETS and n:
            out[(band, c)] = out.get((band, c), 0) + n
    return out
