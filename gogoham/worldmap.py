"""Grayline-Karte (ab 0.8.15): Rechnen ohne Qt.

- Kartendaten: Natural Earth 1:50m (gemeinfrei), `assets/world.json` (erzeugt mit
  tools/make_mapdata.py)
- Sonnenstand (Unterpunkt der Sonne) und Sonnenhöhe überall auf der Erde
- zwei Kartenarten: rechteckige Weltkarte (lon/lat gleichabständig) und Kreiskarte
  (mittabstandstreu azimutal um den eigenen Standort: gerade Linie von der Mitte = Beamrichtung)
- Großkreis: Short Path und Long Path als Punktfolgen

Koordinaten der Karten sind „Einheitskoordinaten“: Weltkarte x ∈ [-1, 1] (lon/180),
y ∈ [-0.5, 0.5] (lat/180, nach oben positiv); Kreiskarte x, y ∈ [-1, 1] (Rand = Gegenpunkt).
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np

DATA = Path(__file__).parent / "assets" / "world.json"

RECT = "rect"          # Weltkarte
AZI = "azimuthal"      # Kreiskarte um den eigenen Standort

TWILIGHT_DEG = 12.0    # Dämmerung: Sonne 0 … 12° unter dem Horizont (bis nautische Dämmerung)


# ------------------------------------------------------------------ Kartendaten
def _unpack(flat) -> np.ndarray:
    """[lon, lat, dlon, dlat, …] in 1/100 Grad → numpy-Feld (N, 2) mit (Länge, Breite) in Grad."""
    a = np.asarray(flat, dtype=np.int64).reshape(-1, 2)
    return np.cumsum(a, axis=0) / 100.0


@lru_cache(maxsize=1)
def load(path: str | None = None) -> dict:
    """Kartendaten: land/borders = Listen von (N, 2)-Feldern (Länge, Breite);
    lakes/rivers = Listen von (Rang, Feld); places = (Name englisch, Breite, Länge, Rang, Hauptstadt, Name deutsch oder "")."""
    raw = json.loads(Path(path or DATA).read_text(encoding="utf-8"))
    return {"land": [_unpack(r) for r in raw.get("land", [])],
            "borders": [_unpack(r) for r in raw.get("borders", [])],
            "lakes": [(r[0], _unpack(r[1:])) for r in raw.get("lakes", [])],
            "rivers": [(r[0], _unpack(r[1:])) for r in raw.get("rivers", [])],
            "places": [(n, la / 100.0, lo / 100.0, rk, cap, de)
                       for n, la, lo, rk, cap, de in raw.get("places", [])],
            "source": raw.get("source", "")}


# ------------------------------------------------------------------ Sonne
def subsolar(when: datetime | None = None) -> tuple[float, float]:
    """Punkt, an dem die Sonne senkrecht steht: (Breite, Länge) in Grad. Genau auf ~0.1°."""
    when = when or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    jd = when.timestamp() / 86400.0 + 2440587.5
    n = jd - 2451545.0
    L = math.radians((280.460 + 0.9856474 * n) % 360)
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = L + math.radians(1.915) * math.sin(g) + math.radians(0.020) * math.sin(2 * g)
    eps = math.radians(23.439 - 0.0000004 * n)
    dec = math.asin(math.sin(eps) * math.sin(lam))
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    gmst = (18.697374558 + 24.06570982441908 * n) % 24 * 15.0       # Grad
    lon = (math.degrees(ra) - gmst + 540.0) % 360.0 - 180.0
    return math.degrees(dec), lon


def sun_elevation(lat, lon, sun: tuple[float, float]):
    """Sonnenhöhe in Grad (Zahl oder numpy-Feld) für Breite/Länge in Grad."""
    sl, so = math.radians(sun[0]), math.radians(sun[1])
    la, lo = np.radians(lat), np.radians(lon)
    s = np.sin(la) * math.sin(sl) + np.cos(la) * math.cos(sl) * np.cos(lo - so)
    return np.degrees(np.arcsin(np.clip(s, -1.0, 1.0)))


def night_alpha(elev, twilight: bool = True):
    """0 = Tag … 1 = Nacht. Mit Dämmerung weicher Übergang über TWILIGHT_DEG Grad."""
    if not twilight:
        return (np.asarray(elev) < 0).astype(np.float32)
    return np.clip(-np.asarray(elev, dtype=np.float32) / TWILIGHT_DEG, 0.0, 1.0)


# ------------------------------------------------------------------ Großkreis
def destination(lat: float, lon: float, az_deg: float, dist_rad: float) -> tuple[float, float]:
    p1, l1, az = math.radians(lat), math.radians(lon), math.radians(az_deg)
    p2 = math.asin(max(-1.0, min(1.0, math.sin(p1) * math.cos(dist_rad)
                                 + math.cos(p1) * math.sin(dist_rad) * math.cos(az))))
    l2 = l1 + math.atan2(math.sin(az) * math.sin(dist_rad) * math.cos(p1),
                         math.cos(dist_rad) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540.0) % 360.0 - 180.0


def angular_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * math.asin(min(1.0, math.sqrt(a)))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def great_circle(home: tuple[float, float], target: tuple[float, float],
                 long_path: bool = False, step_deg: float = 1.0) -> list[tuple[float, float]]:
    """Punkte (Breite, Länge) von home nach target – Short Path oder Long Path."""
    d = angular_distance(home[0], home[1], target[0], target[1])
    az = bearing(home[0], home[1], target[0], target[1])
    if long_path:
        az, d = (az + 180.0) % 360.0, 2 * math.pi - d
    n = max(2, int(math.degrees(d) / step_deg) + 1)
    return [destination(home[0], home[1], az, d * i / (n - 1)) for i in range(n)]


# ------------------------------------------------------------------ Projektionen
def project(kind: str, lat: float, lon: float, home: tuple[float, float]) -> tuple[float, float]:
    """Grad → Einheitskoordinaten (siehe Kopf der Datei)."""
    if kind == RECT:
        return lon / 180.0, lat / 180.0
    c = angular_distance(home[0], home[1], lat, lon)
    az = math.radians(bearing(home[0], home[1], lat, lon))
    r = c / math.pi
    return r * math.sin(az), r * math.cos(az)


def inverse_units(kind: str, x, y, home: tuple[float, float]):
    """Einheitskoordinaten (numpy-Felder) → Breite, Länge (Grad) und Maske „liegt auf der Erde“."""
    x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    if kind == RECT:
        inside = (np.abs(x) <= 1.0) & (np.abs(y) <= 0.5)
        return np.clip(y, -0.5, 0.5) * 180.0, np.clip(x, -1.0, 1.0) * 180.0, inside
    r = np.hypot(x, y)
    inside = r <= 1.0
    c = np.minimum(r, 1.0) * math.pi
    az = np.arctan2(x, y)
    p1, l1 = math.radians(home[0]), math.radians(home[1])
    sp2 = np.sin(p1) * np.cos(c) + np.cos(p1) * np.sin(c) * np.cos(az)
    p2 = np.arcsin(np.clip(sp2, -1.0, 1.0))
    l2 = l1 + np.arctan2(np.sin(az) * np.sin(c) * np.cos(p1), np.cos(c) - np.sin(p1) * sp2)
    lon = (np.degrees(l2) + 540.0) % 360.0 - 180.0
    return np.degrees(p2), lon, inside


def inverse_grid(kind: str, w: int, h: int, home: tuple[float, float]):
    """Für ein Bild w×h (ganze Karte, nicht gezoomt): Breite, Länge je Bildpunkt und Maske.
    Weltkarte füllt das Bild, Kreiskarte ist ein Kreis mit Durchmesser min(w, h)."""
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
    if kind == RECT:
        return inverse_units(kind, (xs + 0.5) / w * 2 - 1, 0.5 - (ys + 0.5) / h, home)
    size = min(w, h)
    return inverse_units(kind, ((xs + 0.5) - w / 2.0) / (size / 2.0),
                         (h / 2.0 - (ys + 0.5)) / (size / 2.0), home)


def locator_digits(deg_per_px: float) -> int:
    """Wie viele Stellen Locator sinnvoll sind, je nach Maßstab (Grad Breite je Bildpunkt):
    0 = keiner (ganz herausgezoomt), 2 = Großfeld (10° hoch), 4 = Feld (1°), 6 = Kleinfeld (2,5')."""
    if deg_per_px <= (1 / 24) / 20:          # Kleinfeld mindestens 20 Bildpunkte hoch
        return 6
    if deg_per_px <= 1.0 / 50:               # Feld mindestens 50 Bildpunkte hoch
        return 4
    if deg_per_px <= 10.0 / 70:              # Großfeld mindestens 70 Bildpunkte hoch
        return 2
    return 0


def split_array(xy: np.ndarray, max_jump: float) -> list[np.ndarray]:
    """Wie split_line, aber für ein numpy-Feld (N, 2) – schnell für viele Punkte."""
    if len(xy) < 2:
        return []
    jumps = np.nonzero(np.hypot(*np.diff(xy, axis=0).T) > max_jump)[0] + 1
    return [p for p in np.split(xy, jumps) if len(p) > 1]


def split_line(points: list[tuple[float, float]], max_jump: float) -> list[list[tuple[float, float]]]:
    """Linie (Einheitskoordinaten) an Sprüngen auftrennen (Datumsgrenze, Gegenpunkt)."""
    out, cur = [], []
    for p in points:
        if cur and math.hypot(p[0] - cur[-1][0], p[1] - cur[-1][1]) > max_jump:
            if len(cur) > 1:
                out.append(cur)
            cur = []
        cur.append(p)
    if len(cur) > 1:
        out.append(cur)
    return out


def project_many(kind: str, lat, lon, home: tuple[float, float]):
    """Wie project(), aber für numpy-Felder (Grenzlinien, viele Punkte auf einmal)."""
    lat, lon = np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64)
    if kind == RECT:
        return lon / 180.0, lat / 180.0
    p1, l1 = math.radians(home[0]), math.radians(home[1])
    p2, dl = np.radians(lat), np.radians(lon) - l1
    cos_c = np.clip(math.sin(p1) * np.sin(p2) + math.cos(p1) * np.cos(p2) * np.cos(dl), -1, 1)
    c = np.arccos(cos_c)
    az = np.arctan2(np.sin(dl) * np.cos(p2),
                    math.cos(p1) * np.sin(p2) - math.sin(p1) * np.cos(p2) * np.cos(dl))
    r = c / math.pi
    return r * np.sin(az), r * np.cos(az)


def unproject(kind: str, x: float, y: float,
              home: tuple[float, float]) -> tuple[float, float] | None:
    """Einheitskoordinaten → (Breite, Länge) oder None außerhalb der Erde."""
    if kind == RECT:
        if abs(x) > 1 or abs(y) > 0.5:
            return None
        return y * 180.0, x * 180.0
    r = math.hypot(x, y)
    if r > 1.0:
        return None
    return destination(home[0], home[1], math.degrees(math.atan2(x, y)), r * math.pi)


def grid_square(lat: float, lon: float) -> str:
    """Maidenhead-Locator (6 Stellen) zu Breite/Länge."""
    lon = min(max(lon + 180.0, 0.0), 359.9999)
    lat = min(max(lat + 90.0, 0.0), 179.9999)
    a, b = int(lon // 20), int(lat // 10)
    c, d = int((lon % 20) // 2), int(lat % 10)
    e, f = int((lon % 2) * 12), int((lat % 1) * 24)
    return f"{chr(65 + a)}{chr(65 + b)}{c}{d}{chr(97 + e)}{chr(97 + f)}"
