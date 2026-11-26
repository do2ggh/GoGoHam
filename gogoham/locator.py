"""Maidenhead-Locator: Prüfung, Mittelpunkt, Entfernung."""

from __future__ import annotations

from .i18n import tr

import math
import re

_GRID4 = re.compile(r"^[A-R]{2}[0-9]{2}$")
_GRID6 = re.compile(r"^[A-R]{2}[0-9]{2}[A-X]{2}$")


def is_grid4(g: str) -> bool:
    return bool(_GRID4.match((g or "").upper()))


def normalize(g: str) -> str:
    g = (g or "").strip().upper()
    if _GRID6.match(g):
        return g[:4]
    return g


def center4(g: str) -> tuple[float, float]:
    """Mittelpunkt eines 4-stelligen Locators -> (lat, lon)."""
    g = normalize(g)
    if not is_grid4(g):
        raise ValueError(tr("Ungültiger Locator: {g}", g=g))
    lon = (ord(g[0]) - 65) * 20 - 180 + int(g[2]) * 2 + 1.0
    lat = (ord(g[1]) - 65) * 10 - 90 + int(g[3]) + 0.5
    return lat, lon


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def is_grid6(g: str) -> bool:
    return bool(_GRID6.match((g or "").strip().upper()))


def center6(g: str) -> tuple[float, float]:
    """Mittelpunkt eines 6-stelligen Locators -> (lat, lon)."""
    g = (g or "").strip().upper()
    if not is_grid6(g):
        raise ValueError(tr("Ungültiger Locator: {g}", g=g))
    lon = (ord(g[0]) - 65) * 20 - 180 + int(g[2]) * 2 + (ord(g[4]) - 65) / 12 + 1 / 24
    lat = (ord(g[1]) - 65) * 10 - 90 + int(g[3]) + (ord(g[5]) - 65) / 24 + 1 / 48
    return lat, lon


def iaru_km(g1: str, g2: str) -> float:
    """Entfernung nach den IARU-Region-1-UKW-Regeln: Mittelpunkte der 6-stelligen Locator,
    Kugelformel, 1 Grad = 111,2 km (nicht gerundet)."""
    la1, lo1 = center6(g1)
    la2, lo2 = center6(g2)
    p1, p2 = math.radians(la1), math.radians(la2)
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(math.radians(lo2 - lo1))
    return 111.2 * math.degrees(math.acos(max(-1.0, min(1.0, c))))


def iaru_points(g1: str, g2: str) -> int:
    """QSO-Punkte im UKW-Contest: Kilometer abgeschnitten + 1 (gleicher Locator = 1)."""
    return int(iaru_km(g1, g2)) + 1


def grid_distance_km(g1: str, g2: str) -> float:
    a = center4(g1)
    b = center4(g2)
    return distance_km(a[0], a[1], b[0], b[1])


# ------------------------------------------------------------ 6-stellig, Richtung
_GRID46 = re.compile(r"^[A-R]{2}[0-9]{2}([A-X]{2})?$")
EARTH_CIRCUMFERENCE = 2 * math.pi * 6371.0


def is_grid(g: str) -> bool:
    """4- oder 6-stelliger Locator."""
    return bool(_GRID46.match((g or "").strip().upper()))


def latlon(g: str) -> tuple[float, float]:
    """Mittelpunkt eines 4- oder 6-stelligen Locators -> (lat, lon)."""
    g = (g or "").strip().upper()
    if not is_grid(g):
        raise ValueError(tr("Ungültiger Locator: {g}", g=g))
    lon = (ord(g[0]) - 65) * 20 - 180 + int(g[2]) * 2
    lat = (ord(g[1]) - 65) * 10 - 90 + int(g[3])
    if len(g) == 6:
        lon += (ord(g[4]) - 65) * (2 / 24) + (1 / 24)
        lat += (ord(g[5]) - 65) * (1 / 24) + (1 / 48)
    else:
        lon += 1.0
        lat += 0.5
    return lat, lon


def from_latlon(lat: float, lon: float, chars: int = 6) -> str:
    """Breite/Länge -> Locator (4, 6 oder 8 Stellen), z. B. für den GPS-Empfänger (0.10.25)."""
    lat = min(max(float(lat), -90.0), 89.999999) + 90.0
    lon = ((float(lon) + 180.0) % 360.0)
    g = chr(65 + int(lon // 20)) + chr(65 + int(lat // 10))
    lon, lat = lon % 20, lat % 10
    g += str(int(lon // 2)) + str(int(lat // 1))
    lon, lat = lon % 2, lat % 1
    if chars >= 6:
        g += chr(97 + int(lon * 12)) + chr(97 + int(lat * 24))
        lon, lat = lon % (1 / 12), lat % (1 / 24)
    if chars >= 8:
        g += str(int(lon * 120)) + str(int(lat * 240))
    return g


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def paths(lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    """Short Path und Long Path: Richtung (°) und Entfernung (km)."""
    sp_km = distance_km(lat1, lon1, lat2, lon2)
    sp = bearing_deg(lat1, lon1, lat2, lon2)
    return {"sp_deg": sp, "sp_km": sp_km,
            "lp_deg": (sp + 180) % 360, "lp_km": EARTH_CIRCUMFERENCE - sp_km}
