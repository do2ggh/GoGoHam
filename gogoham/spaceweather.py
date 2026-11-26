"""Funkwetter (ab 0.8.13): Sonnenfluss (SFI), A-Index und K-Index vom US-Weltraumwetterdienst
NOAA SWPC (amtliche Quelle, gemeinfrei, ohne Anmeldung).

- SFI: 10,7-cm-Sonnenfluss aus Penticton, dreimal am Tag gemessen – der neueste Wert zählt.
- K:   planetarer K-Index, alle 3 Stunden.
- A:   planetarer A-Index des laufenden Tages (geschätzt, solange der Tag läuft).

Abgerufen wird alle 30 Minuten im Hintergrund. Ohne Internet bleibt die Anzeige grau –
GoGoHam hängt nie und meldet keinen Fehler.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from dataclasses import dataclass

from . import __version__

BASE = "https://services.swpc.noaa.gov/"
SFI_URL = BASE + "json/f107_cm_flux.json"
K_URL = BASE + "products/noaa-planetary-k-index.json"
A_URL = BASE + "text/daily-geomagnetic-indices.txt"
INTERVAL_S = 30 * 60

GOOD, FAIR, POOR, NEUTRAL = "good", "fair", "poor", "neutral"
# Bänder, auf denen der Sonnenfluss viel ausmacht: Grenze für grün / gelb
SFI_LIMITS = {"10": (150, 100), "12": (150, 100), "15": (150, 100),
              "17": (100, 80), "20": (100, 80)}


@dataclass
class SpaceWeather:
    sfi: int | None = None
    a: int | None = None
    k: int | None = None
    sfi_time: str = ""          # „2026-11-04 17:00“ UTC
    k_time: str = ""
    a_date: str = ""            # „2026-11-04“

    @property
    def empty(self) -> bool:
        return self.sfi is None and self.a is None and self.k is None


def _get(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": f"GoGoHam/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (feste Adresse)
        return r.read().decode("utf-8", "replace")


def _t(tag: str) -> str:
    return (tag or "").replace("T", " ")[:16]


def parse_sfi(text: str) -> tuple[int | None, str]:
    """Neuester gemessener Sonnenfluss aus json/f107_cm_flux.json."""
    rows = [r for r in json.loads(text) if isinstance(r, dict) and r.get("flux") is not None
            and r.get("time_tag")]
    if not rows:
        return None, ""
    r = max(rows, key=lambda r: r["time_tag"])
    return int(round(float(r["flux"]))), _t(r["time_tag"])


def parse_k(text: str) -> tuple[int | None, str]:
    """Letzter planetarer K-Index (3-Stunden-Wert) aus noaa-planetary-k-index.json.
    Ältere Fassungen der Datei waren eine Tabelle mit Kopfzeile – beides wird verstanden."""
    data = json.loads(text)
    rows = []
    for r in data:
        if isinstance(r, dict):
            rows.append((r.get("time_tag", ""), r.get("Kp")))
        elif isinstance(r, list) and len(r) >= 2 and r[0] != "time_tag":
            rows.append((r[0], r[1]))
    rows = [(t, k) for t, k in rows if t and k not in (None, "")]
    if not rows:
        return None, ""
    t, k = max(rows, key=lambda r: r[0])
    return int(round(float(k))), _t(t)


def parse_a(text: str) -> tuple[int | None, str]:
    """Planetarer A-Index des neuesten Tages aus daily-geomagnetic-indices.txt.
    Jede Datenzeile endet mit „A  Kp1 … Kp8“ (planetar); -1 = noch kein Wert."""
    best = (None, "")
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 12 or line.startswith((":", "#")) or not parts[0].isdigit():
            continue
        try:
            a = int(parts[-9])
        except ValueError:
            continue
        if a >= 0:
            best = (a, f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}")
    return best


def fetch(timeout: float = 8.0) -> SpaceWeather:
    """Alle drei Werte holen; was nicht klappt, bleibt leer (None)."""
    w = SpaceWeather()
    for url, parse, keys in ((SFI_URL, parse_sfi, ("sfi", "sfi_time")),
                             (K_URL, parse_k, ("k", "k_time")),
                             (A_URL, parse_a, ("a", "a_date"))):
        try:
            val, when = parse(_get(url, timeout))
        except Exception:  # noqa: BLE001 – Funkwetter darf GoGoHam nie stören
            continue
        setattr(w, keys[0], val)
        setattr(w, keys[1], when)
    return w


def sfi_level(sfi: int | None, band: str) -> str:
    """Bewertung des Sonnenflusses für das aktive Band; auf den tiefen Bändern und UKW
    sagt er kaum etwas – dort neutral."""
    if sfi is None or band not in SFI_LIMITS:
        return NEUTRAL
    good, fair = SFI_LIMITS[band]
    return GOOD if sfi >= good else FAIR if sfi >= fair else POOR


def k_level(k: int | None) -> str:
    if k is None:
        return NEUTRAL
    return GOOD if k <= 2 else FAIR if k <= 4 else POOR


def a_level(a: int | None) -> str:
    if a is None:
        return NEUTRAL
    return GOOD if a < 10 else FAIR if a < 30 else POOR


class Fetcher(threading.Thread):
    """fetch() im Hintergrund; Ergebnis danach in .result."""

    def __init__(self, timeout: float = 8.0):
        super().__init__(daemon=True, name="spaceweather")
        self.timeout = timeout
        self.result: SpaceWeather | None = None

    def run(self) -> None:  # noqa: D401 (Thread-Methode)
        try:
            self.result = fetch(self.timeout)
        except Exception:  # noqa: BLE001
            self.result = SpaceWeather()
