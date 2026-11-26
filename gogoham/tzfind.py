"""Zeitzone aus dem Locator (ab 0.10.10) – ohne Internet.

Jedes Linux bringt die Liste der Zeitzonen mit Ortsangabe ihrer Hauptstadt mit
(/usr/share/zoneinfo/zone1970.tab, gemeinfrei). GoGoHam nimmt die nächstgelegene.

Gebraucht wird das auf dem Live-Stick: Windows-Rechner führen ihre eingebaute Uhr in Ortszeit.
Stimmt die Zeitzone des Sticks nicht mit dem Standort überein, geht die Uhr ohne Internet eine
oder mehrere Stunden falsch.

Geändert wird nur, wenn die Uhrzeit dadurch wirklich anders wäre: Steht der Stick auf
Europe/Berlin und der Locator liegt bei Prag oder Wien (gleiche Uhrzeit, Sommerzeit gleich),
bleibt Europe/Berlin.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from pathlib import Path

TAB = Path("/usr/share/zoneinfo/zone1970.tab")


def _coord(s: str, deg_digits: int) -> float:
    sign = -1.0 if s[0] == "-" else 1.0
    d = s[1:]
    deg = int(d[:deg_digits])
    mins = int(d[deg_digits:deg_digits + 2])
    secs = int(d[deg_digits + 2:deg_digits + 4] or 0)
    return sign * (deg + mins / 60 + secs / 3600)


def parse_coords(s: str) -> tuple[float, float]:
    """„+5230+01322“ → (52.5, 13.37); auch mit Sekunden („+404251-0740023“)."""
    i = max(s.find("+", 1), s.find("-", 1))
    lat, lon = s[:i], s[i:]
    return _coord(lat, 2), _coord(lon, 3)


def load(path: Path | None = None) -> list[tuple[float, float, str]]:
    out = []
    try:
        text = Path(path or TAB).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for ln in text.splitlines():
        if not ln.strip() or ln.startswith("#"):
            continue
        parts = ln.split("\t")
        if len(parts) < 3:
            continue
        try:
            lat, lon = parse_coords(parts[1])
        except (ValueError, IndexError):
            continue
        out.append((lat, lon, parts[2].strip()))
    return out


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return 6371.0 * math.acos(max(-1.0, min(1.0, c)))


def nearest(lat: float, lon: float, zones=None) -> str | None:
    zones = zones if zones is not None else load()
    if not zones:
        return None
    return min(zones, key=lambda z: _km(lat, lon, z[0], z[1]))[2]


def _offsets(zone: str, year: int) -> tuple | None:
    try:
        from zoneinfo import ZoneInfo
        z = ZoneInfo(zone)
    except Exception:  # noqa: BLE001 – unbekannte Zone
        return None
    return tuple(datetime(year, m, 15, 12, tzinfo=timezone.utc).astimezone(z).utcoffset()
                 for m in (1, 4, 7, 10))


def same_time(a: str, b: str, year: int | None = None) -> bool:
    """Zeigen beide Zonen übers Jahr dieselbe Uhrzeit (inkl. Sommerzeit)?"""
    if a == b:
        return True
    y = year or datetime.now().year
    oa, ob = _offsets(a, y), _offsets(b, y)
    return oa is not None and oa == ob


def current_zone(etc: str = "/etc") -> str:
    """Eingestellte Zeitzone des Systems ("" = unbekannt)."""
    try:
        t = Path(etc, "timezone").read_text().strip()
        if t:
            return t
    except OSError:
        pass
    try:
        link = os.readlink(Path(etc, "localtime"))
    except OSError:
        return ""
    return link.split("zoneinfo/", 1)[1] if "zoneinfo/" in link else ""


def suggest(grid: str, current: str, zones=None) -> str | None:
    """Zone, auf die umgestellt werden sollte – None = so lassen (oder nicht feststellbar)."""
    from .locator import is_grid, latlon
    if not grid or not is_grid(grid.strip()):
        return None
    lat, lon = latlon(grid.strip())
    z = nearest(lat, lon, zones)
    if not z or (current and same_time(z, current)):
        return None
    return z
