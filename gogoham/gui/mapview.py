"""Grayline-Karte (ab 0.8.15): Fenster mit Weltkarte oder Kreiskarte um den eigenen Standort,
Tag/Nacht, Dämmerung und Weg zur Gegenstation (Short Path durchgezogen, Long Path gestrichelt).

Ab 0.8.15.1 (je einzeln schaltbar): NCDXF-Baken als Dreiecke in den Farben der Bakenanzeige
und Cluster-Spots des aktiven Bandes als Punkte in den Farben der Bandmap (am Standort des
Landes). Klick auf einen Spot = wie in der Bandmap, Rechtsklick = Menü (QRZ.com).

Land, Meer und Nacht werden als Bild gerechnet (numpy, je Bildpunkt zurück auf Breite/Länge) –
so gibt es in keiner Kartenart Fehler an der Datumsgrenze oder am Gegenpunkt. Grenzen, Wege und
Beschriftung zeichnet QPainter darüber.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QImage, QPainter, QPainterPath, QPalette, QPen,
                           QPolygonF)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QSizePolicy, QToolTip, QVBoxLayout,
                               QWidget)

from .. import worldmap as wm
from ..i18n import num, tr

MASK_W, MASK_H = 2160, 1080          # Landmaske 1/6 Grad
KM_PER_RAD = 6371.0
PATH_COLOR = "#2ee65a"              # Weg zur Gegenstation: kräftiges Grün (Nutzerwunsch)
PATH_EDGE = QColor(0, 0, 0, 150)     # dunkler Rand – auch auf hellem/grünem Grund sichtbar
HIT_PX = 9                           # so nah muss die Maus an einem Baken-/Spot-Zeichen sein
BEAM_COLOR = "#ff8f00"               # Rotor-Beam (0.8.23.1)
BEAM_WIDTH = 30                      # Öffnungswinkel (Grad), einstellbar im Reiter Rotor
BEAM_STRIPS = 16                     # Streifen quer über den Keil (Verlauf Mitte → Rand)
BEAM_ALPHA = 150                     # Deckkraft in der Mitte (0–255)
BEAM_KM = 19900.0                    # bis kurz vor den Gegenpunkt (0.8.23.2: ganze Strecke)

LIGHT = {"sea": (198, 222, 240), "land": (236, 230, 205), "border": "#9a9080",
         "grid": "#a9c3d8", "loc": "#4a4a4a", "halo": QColor(255, 255, 255, 190), "river": "#6fa3cf", "city": "#3a3a3a", "night": (10, 20, 60), "night_a": 0.55, "text": "#202020",
         "box": QColor(255, 255, 255, 215)}
DARK = {"sea": (28, 44, 62), "land": (70, 78, 62), "border": "#8c8c7a",
        "grid": "#3e5870", "loc": "#c8c8c8", "halo": QColor(0, 0, 0, 170), "river": "#4f7fa8", "city": "#e0e0e0", "night": (0, 0, 12), "night_a": 0.6, "text": "#f0f0f0",
        "box": QColor(30, 30, 30, 215)}

_MASK = None
_SHAPES = {}                         # "land"/"lakes": (Felder, Umriss-Rechtecke)


def _shapes(name: str):
    if name not in _SHAPES:
        data = wm.load()[name]
        arrs = [a for a in data] if name == "land" else [a for _rank, a in data]
        boxes = np.array([(a[:, 0].min(), a[:, 0].max(), a[:, 1].min(), a[:, 1].max())
                          for a in arrs]) if arrs else np.zeros((0, 4))
        _SHAPES[name] = (arrs, boxes)
    return _SHAPES[name]


def _fill(p: QPainter, name: str, box, sx: float, sy: float, step: int, color: QColor) -> None:
    lon0, lon1, lat0, lat1 = box
    arrs, boxes = _shapes(name)
    if not arrs:
        return
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.OddEvenFill)        # Löcher (Inseln im See, Seen im Land)
    hit = ((boxes[:, 1] >= lon0) & (boxes[:, 0] <= lon1)
           & (boxes[:, 3] >= lat0) & (boxes[:, 2] <= lat1))
    # kleine Flächen weglassen, wenn sie im Bild kleiner als ein Bildpunkt wären
    big = ((boxes[:, 1] - boxes[:, 0]) * sx >= 0.7) | ((boxes[:, 3] - boxes[:, 2]) * sy >= 0.7)
    for i in np.nonzero(hit & big)[0]:
        a = arrs[i]
        if step > 1 and len(a) > 3 * step:
            a = a[::step]
        xs = ((a[:, 0] - lon0) * sx).tolist()
        ys = ((lat1 - a[:, 1]) * sy).tolist()
        path.addPolygon(QPolygonF([QPointF(x, y) for x, y in zip(xs, ys)]))
    p.fillPath(path, color)


def _rasterize(lon0: float, lon1: float, lat0: float, lat1: float, w: int, h: int) -> np.ndarray:
    """Landmaske (Land ohne Seen) für den Ausschnitt lon0…lon1 / lat0…lat1 als Bild w×h."""
    img = QImage(w, h, QImage.Format.Format_Grayscale8)
    img.fill(0)
    sx, sy = w / (lon1 - lon0), h / (lat1 - lat0)
    # Punkte der Kartendaten liegen ~0,02° auseinander: grob gerastert reicht jeder n-te
    step = max(1, int(1.0 / (0.02 * max(sx, sy)) / 2))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    _fill(p, "land", (lon0, lon1, lat0, lat1), sx, sy, step, QColor(255, 255, 255))
    _fill(p, "lakes", (lon0, lon1, lat0, lat1), sx, sy, step, QColor(0, 0, 0))
    p.end()
    arr = np.frombuffer(img.constBits(), dtype=np.uint8).reshape(h, img.bytesPerLine())
    return arr[:, :w] > 127


def land_mask() -> np.ndarray:
    """Landmaske der ganzen Welt (1/6 Grad) – einmal aus den Natural-Earth-Flächen."""
    global _MASK
    if _MASK is None:
        _MASK = _rasterize(-180.0, 180.0, -90.0, 90.0, MASK_W, MASK_H)
    return _MASK


def is_land(lat, lon, mask=None, box=(-180.0, 180.0, -90.0, 90.0)):
    """Nachschlagen in einer Landmaske (ganze Welt oder Ausschnitt box = lon0, lon1, lat0, lat1)."""
    mask = land_mask() if mask is None else mask
    h, w = mask.shape
    lon0, lon1, lat0, lat1 = box
    ix = np.clip(((np.asarray(lon) - lon0) / (lon1 - lon0) * w).astype(np.int32), 0, w - 1)
    iy = np.clip(((lat1 - np.asarray(lat)) / (lat1 - lat0) * h).astype(np.int32), 0, h - 1)
    return mask[iy, ix]


ZOOM_MAX = 600.0                     # reicht auch in der Kreiskarte bis zum 6-stelligen Locator
ZOOM_STEP = 1.25                     # je Raste am Mausrad


class MapCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 220)
        self.setMouseTracking(True)
        self.kind = wm.RECT
        self.home: tuple[float, float] | None = None
        self.home_label = ""
        self.target: tuple[float, float] | None = None
        self.target_label = ""
        self.show_night = True
        self.show_twilight = True
        self.show_path = True
        self.show_grid = True                   # Locator-Gitter (passend zur Zoomstufe)
        self.show_rivers = True
        self.show_cities = True
        self.show_beacons = True                # NCDXF-Baken (0.8.15.1)
        self.show_spots = True                  # Cluster-Spots des aktiven Bandes (0.8.15.1)
        # Zeichen von außen (Hauptfenster), je Eintrag ein dict:
        # Baken: lat, lon, call, color, tip · Spots: lat, lon, spots (Liste), color, label, tip
        self.beacon_marks: list[dict] = []
        self.spot_marks: list[dict] = []
        self.notes: list[str] = []              # zusätzliche Zeilen in der Legende
        self.show_beam = True                   # Rotor-Beam (0.8.23.1)
        self.beam_az: int | None = None         # aktuelle Rotor-Richtung (None = kein Rotor)
        self.beam_target: int | None = None     # Ziel, solange der Rotor dreht
        self.beam_width = BEAM_WIDTH            # Öffnungswinkel der Antenne (0.8.23.2)
        self.on_point_menu = None               # Rechtsklick ohne Spot: (art, Zeichen, (lat, lon), Pos.)
        self.on_spot_click = None               # (spots, globale Position)
        self.on_spot_menu = None                # (spots, globale Position)
        self._press = None
        self.background = "simple"              # simple / nasa / relief (mapimages)
        self.layers: dict = {}                  # Ebenenname → mapimages.RasterLayer
        self.status_line = ""                   # z. B. „Kartenbild wird geladen … 40 %“
        self.now: datetime | None = None        # für Tests feste Zeit
        self.zoom = 1.0                         # 1 = ganze Karte
        self.center = (0.0, 0.0)                # Bildmitte in Einheitskoordinaten
        self._grid_key = None
        self._grid = None                       # (lat, lon, inside, base_rgb)
        self._night_rgb = None                  # NASA-Nachtbild für die Ansicht
        self._img = None
        self._img_key = None
        self._img_view = None                   # Ansicht, für die _img gerechnet wurde
        self._units = {}                        # Grenzen/Flüsse in Einheitskoordinaten
        self._units_key = None
        self._ov = None                         # fertige Linien/Beschriftung für die Ansicht
        self._ov_key = None
        self._drag = None
        self._rebuild = QTimer(self)
        self._rebuild.setSingleShot(True)
        self._rebuild.setInterval(120)          # beim Ziehen/Zoomen nicht dauernd rechnen
        self._rebuild.timeout.connect(self.update)

    # ---------------------------------------------------------------- Geometrie
    def effective_kind(self) -> str:
        return self.kind if (self.kind == wm.RECT or self.home) else wm.RECT

    def map_rect(self) -> QRectF:
        """Rechteck der ganzen Karte bei Zoom 1 (Weltkarte 2:1, Kreiskarte quadratisch)."""
        w, h = self.width() - 8, self.height() - 8
        if self.effective_kind() == wm.RECT:
            mw = min(w, 2 * h)
            mh = mw / 2
        else:
            mw = mh = min(w, h)
        return QRectF((self.width() - mw) / 2, (self.height() - mh) / 2, mw, mh)

    def _scale(self) -> float:
        """Bildpunkte je Einheit bei Zoom 1."""
        return max(1.0, self.map_rect().width() / 2)

    def view(self) -> tuple[float, tuple[float, float], float, float, float]:
        return (self.zoom, self.center, self._scale(), self.width() / 2, self.height() / 2)

    @staticmethod
    def _to_px(v, x: float, y: float) -> tuple[float, float]:
        z, c, s, cx, cy = v
        return cx + (x - c[0]) * z * s, cy - (y - c[1]) * z * s

    def to_px(self, x: float, y: float, _r=None) -> QPointF:
        return QPointF(*self._to_px(self.view(), x, y))

    def from_px(self, px: float, py: float) -> tuple[float, float]:
        z, c, s, cx, cy = self.view()
        return c[0] + (px - cx) / (z * s), c[1] - (py - cy) / (z * s)

    def _home(self) -> tuple[float, float]:
        return self.home or (0.0, 0.0)

    def _limits(self) -> tuple[float, float]:
        return (1.0, 0.5) if self.effective_kind() == wm.RECT else (1.0, 1.0)

    def set_view(self, zoom: float, center: tuple[float, float]) -> None:
        zoom = min(max(zoom, 1.0), ZOOM_MAX)
        if zoom <= 1.0001:
            zoom, center = 1.0, (0.0, 0.0)
        lx, ly = self._limits()
        center = (min(max(center[0], -lx), lx), min(max(center[1], -ly), ly))
        if (zoom, center) != (self.zoom, self.center):
            self.zoom, self.center = zoom, center
            self._rebuild.start()
            self.update()

    def reset_view(self) -> None:
        self.set_view(1.0, (0.0, 0.0))

    # ---------------------------------------------------------------- Bild
    def _colors(self) -> dict:
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        return DARK if dark else LIGHT

    def _land(self, lat, lon, inside):
        """Land/Meer je Bildpunkt; gezoomt mit eigener, feinerer Maske für den Ausschnitt."""
        if self.zoom > 4 and inside.any():
            la, lo = lat[inside], lon[inside]
            lon0, lon1 = float(lo.min()), float(lo.max())
            lat0, lat1 = float(la.min()), float(la.max())
            if lon1 - lon0 < 170 and lat1 - lat0 < 120:   # nicht über die Datumsgrenze
                pad_x, pad_y = (lon1 - lon0) * 0.02 + 0.01, (lat1 - lat0) * 0.02 + 0.01
                box = (lon0 - pad_x, lon1 + pad_x, lat0 - pad_y, lat1 + pad_y)
                h, w = lat.shape
                mask = _rasterize(*box, min(4096, 2 * w), min(4096, 2 * h))
                return is_land(lat, lon, mask, box)
        return is_land(lat, lon)

    def raster(self) -> tuple | None:
        """Bildebenen des gewählten Hintergrunds (Tag, Nacht oder None) – None = einfache Karte."""
        if self.background == "nasa":
            day, night = self.layers.get("nasa-day"), self.layers.get("nasa-night")
            return (day, night) if day and night else None
        if self.background == "relief":
            day = self.layers.get("relief")
            return (day, None) if day else None
        return None

    def _base(self, w: int, h: int, colors: dict):
        raster = self.raster()
        key = (self.effective_kind(), w, h, self._home(), colors is DARK, self.view(),
               self.background, id(raster[0]) if raster else None)
        if key != self._grid_key:
            z, c, s, cx, cy = self.view()
            ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
            ux = c[0] + (xs + 0.5 - cx) / (z * s)
            uy = c[1] - (ys + 0.5 - cy) / (z * s)
            lat, lon, inside = wm.inverse_units(self.effective_kind(), ux, uy, self._home())
            night = None
            if raster:
                dpp = 180.0 / (z * s)                  # Grad je Bildpunkt (beide Kartenarten)
                rgb = raster[0].sample(lat, lon, dpp)
                if raster[1] is not None:              # NASA: Nachtseite mit Stadtlichtern
                    night = np.clip(raster[1].sample(lat, lon, dpp) * 1.25, 0, 255)
            else:
                land = self._land(lat, lon, inside)
                rgb = np.empty((h, w, 3), dtype=np.float32)
                rgb[:] = colors["sea"]
                rgb[land] = colors["land"]
            self._night_rgb = night
            self._grid = (lat, lon, inside, rgb)
            self._grid_key = key
            self._img_key = None
        return self._grid

    def image(self, w: int, h: int) -> QImage:
        colors = self._colors()
        lat, lon, inside, rgb = self._base(w, h, colors)
        when = self.now or datetime.now(timezone.utc)
        key = (self._grid_key, when.replace(second=0, microsecond=0), self.show_night,
               self.show_twilight)
        if key == self._img_key and self._img is not None:
            return self._img
        out = rgb
        if self.show_night:
            sun = wm.subsolar(when)
            a = wm.night_alpha(wm.sun_elevation(lat, lon, sun), self.show_twilight)
            if self._night_rgb is not None:            # NASA: Tagbild → Nachtbild
                a = a[..., None]
                out = rgb * (1 - a) + self._night_rgb * a
            else:
                a = (a * colors["night_a"])[..., None]
                out = rgb * (1 - a) + np.asarray(colors["night"], dtype=np.float32) * a
        argb = np.zeros((h, w, 4), dtype=np.uint8)
        argb[..., 0] = out[..., 2]            # QImage ARGB32 = B, G, R, A im Speicher
        argb[..., 1] = out[..., 1]
        argb[..., 2] = out[..., 0]
        argb[..., 3] = np.where(inside, 255, 0)
        # eigene Kopie: das Bild darf nicht am Speicher des numpy-Felds hängen (sonst kann
        # beim Aufräumen das eine vor dem anderen verschwinden)
        self._img = QImage(argb.data, w, h, w * 4, QImage.Format.Format_ARGB32).copy()
        self._img_key = key
        self._img_view = self.view()
        return self._img

    def _line_units(self, name: str) -> list[tuple[int, np.ndarray]]:
        """Grenzen („borders“) oder Flüsse („rivers“) in Einheitskoordinaten, an Sprüngen
        (Datumsgrenze, Gegenpunkt) getrennt – je Kartenart und Standort einmal gerechnet."""
        key = (self.effective_kind(), self._home())
        if key != self._units_key:
            self._units, self._units_key = {}, key
        if name not in self._units:
            data = wm.load()[name]
            items = [(0, a) for a in data] if name == "borders" else data
            out = []
            for rank, a in items:
                xs, ys = wm.project_many(self.effective_kind(), a[:, 1], a[:, 0], self._home())
                for part in wm.split_array(np.column_stack((xs, ys)), 0.2):
                    out.append((rank, part))
            self._units[name] = out
        return self._units[name]

    def _unit_box(self) -> tuple[float, float, float, float]:
        z, c, s, cx, cy = self.view()
        hx, hy = (self.width() / 2) / (z * s), (self.height() / 2) / (z * s)
        return c[0] - hx, c[0] + hx, c[1] - hy, c[1] + hy

    def _lines_px(self, name: str, max_rank: int) -> list[QPolygonF]:
        z, c, s, cx, cy = self.view()
        x0, x1, y0, y1 = self._unit_box()
        step = max(1, int(3 / z))                  # ganz heraus: jeder 3. Punkt reicht
        polys = []
        for rank, part in self._line_units(name):
            if rank > max_rank:
                continue
            if (part[:, 0].max() < x0 or part[:, 0].min() > x1
                    or part[:, 1].max() < y0 or part[:, 1].min() > y1):
                continue
            if step > 1 and len(part) > 2 * step:
                part = np.vstack((part[::step], part[-1:]))
            pxs = (cx + (part[:, 0] - c[0]) * z * s).tolist()
            pys = (cy - (part[:, 1] - c[1]) * z * s).tolist()
            polys.append(QPolygonF([QPointF(x, y) for x, y in zip(pxs, pys)]))
        return polys

    def _latlon_box(self) -> tuple[float, float, float, float]:
        """Sichtbarer Bereich in Grad (lon0, lon1, lat0, lat1) – aus dem Bildraster."""
        if self._grid is not None:
            lat, lon, inside, _rgb = self._grid
            if inside.any():
                la, lo = lat[inside], lon[inside]
                lon0, lon1 = float(lo.min()), float(lo.max())
                if lon1 - lon0 > 300:              # über die Datumsgrenze: alles nehmen
                    lon0, lon1 = -180.0, 180.0
                return lon0, lon1, float(la.min()), float(la.max())
        return -180.0, 180.0, -90.0, 90.0

    # Länge, Breite, Stellen, Mindesthöhe in Bildpunkten (Kleinfelder erst, wenn gut zu sehen)
    GRID_LEVELS = ((20.0, 10.0, 2, 40), (2.0, 1.0, 4, 25), (1 / 12, 1 / 24, 6, 24))

    def _grid_levels(self) -> list[tuple[float, float, int]]:
        """Welche Locator-Ebenen groß genug zu sehen sind (Großfeld, Feld, Kleinfeld)."""
        dpp = self.deg_per_px(self.width() / 2, self.height() / 2)
        return [(dlon, dlat, digits) for dlon, dlat, digits, min_px in self.GRID_LEVELS
                if dlat / dpp >= min_px]

    def _grid_overlay(self):
        """Locator-Gitter: Linien je Ebene (gröbere dicker) und Beschriftung der feinsten Ebene."""
        levels = self._grid_levels()
        if not levels:
            return [], []
        kind, home = self.effective_kind(), self._home()
        lon0, lon1, lat0, lat1 = self._latlon_box()
        lines, labels = [], []
        w, h = self.width(), self.height()
        for li, (dlon, dlat, digits) in enumerate(levels):
            lons = np.arange(math.floor(lon0 / dlon) * dlon, lon1 + dlon, dlon)
            lats = np.arange(math.floor((lat0 + 90) / dlat) * dlat - 90, lat1 + dlat, dlat)
            lons, lats = lons[(lons >= -180) & (lons <= 180)], lats[(lats >= -90) & (lats <= 90)]
            if len(lons) * len(lats) > 2500:
                continue
            width = 1.4 if li < len(levels) - 1 else 0.8
            la_s = np.linspace(max(lat0 - dlat, -90), min(lat1 + dlat, 90), 64)
            lo_s = np.linspace(max(lon0 - dlon, -180), min(lon1 + dlon, 180), 64)
            segs = [(np.full_like(la_s, lo), la_s) for lo in lons]
            segs += [(lo_s, np.full_like(lo_s, la)) for la in lats]
            for lo_a, la_a in segs:
                xs, ys = wm.project_many(kind, la_a, lo_a, home)
                for part in wm.split_array(np.column_stack((xs, ys)), 0.2):
                    lines.append((width, QPolygonF([self.to_px(x, y) for x, y in part])))
            if li == len(levels) - 1:              # Beschriftung nur für die feinste Ebene
                for lo in lons[:-1] if len(lons) > 1 else lons:
                    for la in lats[:-1] if len(lats) > 1 else lats:
                        clat, clon = la + dlat / 2, lo + dlon / 2
                        if not (-90 < clat < 90 and -180 < clon < 180):
                            continue
                        # Beschriftung in die linke obere Ecke (wie auf Locator-Karten) –
                        # die Mitte bleibt frei für Standort, Städte und Wege
                        top = min(la + dlat, 90.0)
                        pt = self.to_px(*wm.project(kind, top, lo, home))
                        if -20 <= pt.x() <= w and -10 <= pt.y() <= h:
                            right = self.to_px(*wm.project(kind, top, min(lo + dlon, 180.0), home))
                            low = self.to_px(*wm.project(kind, la, lo, home))
                            cw = math.hypot(right.x() - pt.x(), right.y() - pt.y())
                            ch = math.hypot(low.x() - pt.x(), low.y() - pt.y())
                            labels.append((pt, wm.grid_square(clat, clon)[:digits], cw, ch))
        return lines, labels

    def _city_overlay(self, fm) -> list[tuple[QPointF, str, bool, QRectF]]:
        """Orte nach Wichtigkeit, je nach Zoom mehr; Beschriftungen überlappen sich nie."""
        from ..i18n import language
        rmax = min(10, int(1 + 2.5 * self._detail()))
        kind, home = self.effective_kind(), self._home()
        lon0, lon1, lat0, lat1 = self._latlon_box()
        german = language() == "de"
        placed, taken = [], []
        w, h = self.width(), self.height()
        for name, lat, lon, rank, cap, de in wm.load()["places"]:
            if rank > rmax:
                break                               # nach Rang sortiert
            if not (lat0 - 1 <= lat <= lat1 + 1 and lon0 - 1 <= lon <= lon1 + 1):
                continue
            x, y = wm.project(kind, lat, lon, home)
            if math.hypot(x, y) > 1.0 and kind != wm.RECT:
                continue
            pt = self.to_px(x, y)
            if not (0 <= pt.x() <= w and 0 <= pt.y() <= h):
                continue
            text = de if (german and de) else name
            r = QRectF(pt.x() + 4, pt.y() - fm.height() / 2, fm.horizontalAdvance(text) + 2,
                       fm.height())
            if any(r.intersects(t) for t in taken):
                continue
            taken.append(r)
            placed.append((pt, text, bool(cap), r))
            if len(placed) >= 250:
                break
        return placed

    def _detail(self) -> float:
        """Wie weit hineingezoomt, gemessen am Maßstab (0 = ganze Weltkarte, +1 = doppelt so
        groß) – gleich für beide Kartenarten. Bestimmt, wie viele Städte und Flüsse erscheinen."""
        dpp = self.deg_per_px(self.width() / 2, self.height() / 2)
        world = 360.0 / max(1.0, self.map_rect().width()) if self.effective_kind() == wm.RECT \
            else 360.0 / max(1.0, 2 * self.map_rect().width())
        return max(0.0, math.log2(world / max(dpp, 1e-9)))

    def _overlays(self, colors: dict) -> dict:
        f = QFont(self.font())
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
        key = (self.view(), self.effective_kind(), self._home(), self.width(), self.height(),
               self.show_grid, self.show_rivers, self.show_cities, self._grid_key)
        if key != self._ov_key:
            from PySide6.QtGui import QFontMetricsF
            ov = {"font": f, "borders": self._lines_px("borders", 0)}
            ov["rivers"] = (self._lines_px("rivers", min(10, 3 + int(2 * self._detail())))
                            if self.show_rivers else [])
            ov["grid"], ov["grid_labels"] = self._grid_overlay() if self.show_grid else ([], [])
            ov["cities"] = self._city_overlay(QFontMetricsF(f)) if self.show_cities else []
            self._ov, self._ov_key = ov, key
        return self._ov

    # ---------------------------------------------------------------- Zeichnen
    def resizeEvent(self, e):  # noqa: N802
        self._rebuild.start()
        super().resizeEvent(e)

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colors = self._colors()
        busy = self._rebuild.isActive() and self._img is not None
        if busy:
            # beim Ziehen/Zoomen: altes Bild passend verschoben/gestreckt, Rest später
            old, new = self._img_view, self.view()
            z0, c0, s0, cx0, cy0 = old
            def moved(px, py):
                ux, uy = c0[0] + (px - cx0) / (z0 * s0), c0[1] - (py - cy0) / (z0 * s0)
                return self._to_px(new, ux, uy)
            x0, y0 = moved(0, 0)
            x1, y1 = moved(self._img.width(), self._img.height())
            p.drawImage(QRectF(x0, y0, x1 - x0, y1 - y0), self._img)
        else:
            p.drawImage(0, 0, self.image(max(1, self.width()), max(1, self.height())))
        self._draw_grid(p, colors)
        if not busy:
            ov = self._overlays(colors)
            p.setPen(QPen(QColor(colors["river"]), 0.9))
            for poly in ov["rivers"]:
                p.drawPolyline(poly)
            p.setPen(QPen(QColor(colors["border"]), 0.7))
            for poly in ov["borders"]:
                p.drawPolyline(poly)
            self._draw_locator_grid(p, ov, colors)
            self._draw_cities(p, ov, colors)
        if self.show_night:
            self._draw_sun(p)
        if self.show_path and self.home and self.target:
            self._draw_paths(p)
        if self.show_beam and self.home and self.beam_az is not None:
            self._draw_beam(p)
        if self.show_beacons or self.show_spots:
            self._draw_marks(p, colors)
        if self.home:
            self._dot(p, self.to_px(*wm.project(self.effective_kind(), *self.home, self.home)),
                      "#1565c0")
        self._draw_legend(p, colors)
        self._draw_credit(p, colors)
        p.end()

    def _draw_grid(self, p: QPainter, colors: dict) -> None:
        p.setPen(QPen(QColor(colors["grid"]), 0.6, Qt.PenStyle.DotLine))
        if self.effective_kind() == wm.RECT:
            top, bottom = self.to_px(0, 0.5).y(), self.to_px(0, -0.5).y()
            left, right = self.to_px(-1, 0).x(), self.to_px(1, 0).x()
            for lon in range(-150, 180, 30):
                x = self.to_px(lon / 180.0, 0).x()
                p.drawLine(QPointF(x, top), QPointF(x, bottom))
            for lat in range(-60, 90, 30):
                y = self.to_px(0, lat / 180.0).y()
                p.drawLine(QPointF(left, y), QPointF(right, y))
            return
        c, rad = self.to_px(0, 0), self.zoom * self._scale()
        for km in (5000, 10000, 15000):            # Entfernungsringe
            rr = km / (math.pi * KM_PER_RAD) * rad
            p.drawEllipse(c, rr, rr)
        p.setPen(QPen(QColor(colors["text"]), 1.0))
        p.drawEllipse(c, rad, rad)
        f = QFont(self.font())
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
        p.setFont(f)
        fm = p.fontMetrics()
        for deg in range(0, 360, 10):
            a = math.radians(deg)
            inner = rad - (8 if deg % 30 == 0 else 4)
            p.drawLine(QPointF(c.x() + inner * math.sin(a), c.y() - inner * math.cos(a)),
                       QPointF(c.x() + rad * math.sin(a), c.y() - rad * math.cos(a)))
            if deg % 30 == 0:
                txt = f"{deg}°"
                tr_ = rad - 10 - fm.height() * 0.6
                pt = QPointF(c.x() + tr_ * math.sin(a), c.y() - tr_ * math.cos(a))
                p.drawText(QPointF(pt.x() - fm.horizontalAdvance(txt) / 2,
                                   pt.y() + fm.ascent() / 2 - 1), txt)

    def _draw_locator_grid(self, p: QPainter, ov: dict, colors: dict) -> None:
        """Gitter grau mit hellem Rand (Nutzerwunsch: kontrastreich, auf jedem Hintergrund
        lesbar). Beschriftung nur, wenn sie ins Feld passt."""
        loc, halo = QColor(colors["loc"]), colors["halo"]
        for width, poly in ov["grid"]:
            p.setPen(QPen(halo, width + 1.6))
            p.drawPolyline(poly)
            p.setPen(QPen(loc, width))
            p.drawPolyline(poly)
        if ov["grid_labels"]:
            f = QFont(ov["font"])
            f.setBold(True)
            p.setFont(f)
            fm = p.fontMetrics()
            for pt, text, cw, ch in ov["grid_labels"]:
                if fm.horizontalAdvance(text) + 6 > cw or fm.height() + 2 > ch:
                    continue                    # passt nicht ins Feld: lieber weglassen
                base = QPointF(pt.x() + 3, pt.y() + fm.ascent() + 1)
                p.setPen(halo)
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (1, 1), (-1, -1)):
                    p.drawText(base + QPointF(dx, dy), text)
                p.setPen(loc)
                p.drawText(base, text)

    def _draw_cities(self, p: QPainter, ov: dict, colors: dict) -> None:
        if not ov["cities"]:
            return
        p.setFont(ov["font"])
        fm = p.fontMetrics()
        col = QColor(colors["city"])
        halo = QColor(colors["box"])
        for pt, text, cap, r in ov["cities"]:
            p.setPen(QPen(halo, 1))
            p.setBrush(col)
            size = 3.2 if cap else 2.4
            p.drawEllipse(pt, size, size)
            p.setBrush(Qt.BrushStyle.NoBrush)
            base = QPointF(r.left() + 1, pt.y() + fm.ascent() / 2 - 1)
            p.setPen(halo)                          # heller Rand für bessere Lesbarkeit
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                p.drawText(base + QPointF(dx, dy), text)
            p.setPen(col)
            p.drawText(base, text)

    def _draw_sun(self, p: QPainter) -> None:
        sun = wm.subsolar(self.now or datetime.now(timezone.utc))
        x, y = wm.project(self.effective_kind(), sun[0], sun[1], self._home())
        if math.hypot(x, y) > 1.001:
            return
        pt = self.to_px(x, y)
        p.setPen(QPen(QColor("#c77700"), 1.2))
        p.setBrush(QColor("#ffd600"))
        p.drawEllipse(pt, 6, 6)
        p.setBrush(Qt.BrushStyle.NoBrush)

    # ---------------------------------------------------------------- Rotor-Beam (0.8.23.1)
    def _beam_ray(self, az: float, steps: int = 90) -> list[tuple[float, float]]:
        """Großkreis vom Standort in Richtung ``az`` bis kurz vor den Gegenpunkt
        (Einheitskoordinaten der Karte)."""
        kind, home = self.effective_kind(), self.home
        dist = BEAM_KM / KM_PER_RAD
        return [wm.project(kind, *wm.destination(home[0], home[1], az, dist * i / steps), home)
                for i in range(steps + 1)]

    def _draw_beam(self, p: QPainter) -> None:
        """Keil mit dem Öffnungswinkel der Antenne. Die Fläche ist aus schmalen Streifen quer
        über die Breite gebaut (0.8.23.3): in der Mitte kräftig, zu den Rändern hin
        durchsichtig – dort liegt die Hauptenergie. Jeder Streifen besteht aus kleinen
        Vierecken entlang der Strecke; Vierecke, die über den Kartenrand (Datumsgrenze)
        springen, fallen weg, so bleibt der Keil auch dort gefüllt."""
        az = float(self.beam_az)
        half = max(1.0, min(90.0, float(self.beam_width) / 2))
        col = QColor(BEAM_COLOR)
        n = BEAM_STRIPS
        rays = [self._beam_ray(az - half + 2 * half * k / n) for k in range(n + 1)]
        # ohne Kantenglättung: sonst zeigen sich zwischen den Flächenstücken Haarlinien
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for k, (a, b) in enumerate(zip(rays, rays[1:])):
            off = abs((k + 0.5) / n * 2 - 1)                 # 0 = Mitte, 1 = Rand
            alpha = int(BEAM_ALPHA * max(0.0, 1.0 - off * off))
            if alpha < 3:
                continue
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.WindingFill)
            for i in range(len(a) - 1):
                quad = (a[i], a[i + 1], b[i + 1], b[i])
                xs = [q[0] for q in quad]
                ys = [q[1] for q in quad]
                if max(xs) - min(xs) > 0.25 or max(ys) - min(ys) > 0.25:
                    continue                                 # springt über den Kartenrand
                path.addPolygon(QPolygonF([self.to_px(x, y) for x, y in quad] +
                                          [self.to_px(*quad[0])]))
            fill = QColor(col)
            fill.setAlpha(alpha)
            p.fillPath(path, fill)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        edge = QColor(col)
        edge.setAlpha(150)                                   # Ränder dezent (Öffnungswinkel)
        for ray in (rays[0], rays[-1]):
            pen = QPen(edge, 1.0, Qt.PenStyle.DotLine)
            for part in wm.split_line(ray, 0.25):
                p.setPen(pen)
                p.drawPolyline(QPolygonF([self.to_px(x, y) for x, y in part]))
        center = QPen(col, 2.6)
        center.setCapStyle(Qt.PenCapStyle.RoundCap)
        for part in wm.split_line(self._beam_ray(az), 0.25):
            poly = QPolygonF([self.to_px(x, y) for x, y in part])
            p.setPen(QPen(PATH_EDGE, 4.2))
            p.drawPolyline(poly)
            p.setPen(center)
            p.drawPolyline(poly)
        if self.beam_target is not None:                 # Ziel gestrichelt, solange er dreht
            pen = QPen(col, 2.0, Qt.PenStyle.DashLine)
            for part in wm.split_line(self._beam_ray(float(self.beam_target)), 0.25):
                p.setPen(pen)
                p.drawPolyline(QPolygonF([self.to_px(x, y) for x, y in part]))

    # ---------------------------------------------------------------- Baken und Spots
    def mark_px(self, m: dict) -> QPointF | None:
        """Bildpunkt eines Zeichens, None wenn es nicht auf der Karte liegt."""
        x, y = wm.project(self.effective_kind(), m["lat"], m["lon"], self._home())
        if math.hypot(x, y) > 1.001 and self.effective_kind() != wm.RECT:
            return None
        pt = self.to_px(x, y)
        if not (-20 <= pt.x() <= self.width() + 20 and -20 <= pt.y() <= self.height() + 20):
            return None
        return pt

    def _label(self, p: QPainter, base: QPointF, text: str, col: QColor, halo: QColor) -> None:
        p.setPen(halo)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p.drawText(base + QPointF(dx, dy), text)
        p.setPen(col)
        p.drawText(base, text)

    def _draw_marks(self, p: QPainter, colors: dict) -> None:
        """Baken (Dreiecke) und Spots (Punkte); danach Beschriftung ohne Überdeckung –
        Spots haben Vorrang, Bakennamen weichen aus."""
        beacons = [(m, pt) for m in (self.beacon_marks if self.show_beacons else [])
                   if (pt := self.mark_px(m)) is not None]
        spots = [(m, pt) for m in (self.spot_marks if self.show_spots else [])
                 if (pt := self.mark_px(m)) is not None]
        edge = QColor(0, 0, 0, 180)
        for m, pt in beacons:
            tri = QPolygonF([QPointF(pt.x(), pt.y() - 6), QPointF(pt.x() + 5.5, pt.y() + 4),
                             QPointF(pt.x() - 5.5, pt.y() + 4)])
            p.setPen(QPen(edge, 1.2))
            p.setBrush(QColor(m["color"]))
            p.drawPolygon(tri)
        for m, pt in spots:
            p.setPen(QPen(edge, 1.3))
            p.setBrush(QColor(m["color"]))
            r = 5.0 if len(m["spots"]) == 1 else 6.5
            p.drawEllipse(pt, r, r)
        p.setBrush(Qt.BrushStyle.NoBrush)
        halo, text_col = colors["halo"], QColor(colors["text"])
        # Punkte selbst nicht überschreiben
        taken = [QRectF(pt.x() - 6, pt.y() - 6, 12, 12) for _m, pt in beacons + spots]
        if self.home:
            hp = self.to_px(*wm.project(self.effective_kind(), *self.home, self.home))
            taken.append(QRectF(hp.x() - 6, hp.y() - 6, 12, 12))
        f = QFont(self.font())
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        for m, pt in spots:
            text = m["label"]
            r = 5.0 if len(m["spots"]) == 1 else 6.5
            w = fm.horizontalAdvance(text) + 2
            for x in (pt.x() + r + 2, pt.x() - r - 2 - w):        # rechts, sonst links
                rect = QRectF(x, pt.y() - fm.height() / 2, w, fm.height())
                if not any(rect.intersects(t) for t in taken):
                    break
            else:
                continue
            taken.append(rect)
            col = QColor(m["color"])
            # Multi-Farben (grün/orange) behalten, sonst gut lesbare Textfarbe
            if col.saturation() < 60:
                col = text_col
            elif colors is LIGHT:
                col = col.darker(130)
            self._label(p, QPointF(rect.left() + 1, pt.y() + fm.ascent() / 2 - 1), text, col,
                        halo)
        f.setBold(False)
        f.setPointSizeF(max(6.5, f.pointSizeF() - 1))
        p.setFont(f)
        fm = p.fontMetrics()
        for m, pt in beacons:
            w = fm.horizontalAdvance(m["call"])
            rect = QRectF(pt.x() - w / 2, pt.y() + 6.5, w, fm.height())     # unter dem Dreieck
            if any(rect.intersects(t) for t in taken):
                continue
            taken.append(rect)
            self._label(p, QPointF(rect.left(), rect.top() + fm.ascent()), m["call"], text_col,
                        halo)

    def mark_at(self, px: float, py: float) -> tuple[str, dict] | None:
        """Nächstes Baken-/Spot-Zeichen unter der Maus: ("spot"|"beacon", Zeichen)."""
        best, best_d = None, HIT_PX
        groups = (("spot", self.spot_marks if self.show_spots else []),
                  ("beacon", self.beacon_marks if self.show_beacons else []))
        for kind, marks in groups:
            for m in marks:
                pt = self.mark_px(m)
                if pt is None:
                    continue
                d = math.hypot(pt.x() - px, pt.y() - py)
                if d < best_d:
                    best, best_d = (kind, m), d
        return best

    def _dot(self, p: QPainter, pt: QPointF, color: str) -> None:
        p.setPen(QPen(QColor("white"), 1.5))
        p.setBrush(QColor(color))
        p.drawEllipse(pt, 5, 5)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_paths(self, p: QPainter) -> None:
        kind = self.effective_kind()
        step = 1.0 if self.zoom < 8 else 0.1      # gezoomt: feinere Punkte, sonst eckig
        for long_path, style in ((True, Qt.PenStyle.DashLine), (False, Qt.PenStyle.SolidLine)):
            pts = [wm.project(kind, la, lo, self.home)
                   for la, lo in wm.great_circle(self.home, self.target, long_path, step)]
            width = 2.6 if not long_path else 2.2
            edge = QPen(PATH_EDGE, width + 2.0, style)
            pen = QPen(QColor(PATH_COLOR), width, style)
            for pn in (edge, pen):
                if long_path:
                    # Strichlänge in Bildpunkten für Rand und Linie gleich (Qt rechnet sonst in
                    # Linienbreiten – dann liefen Rand und Striche auseinander)
                    pn.setCapStyle(Qt.PenCapStyle.FlatCap)
                    pn.setDashPattern([9.0 / pn.widthF(), 6.0 / pn.widthF()])
                else:
                    pn.setCapStyle(Qt.PenCapStyle.RoundCap)
            for part in wm.split_line(pts, 0.25):
                poly = QPolygonF([self.to_px(x, y) for x, y in part])
                p.setPen(edge)
                p.drawPolyline(poly)
                p.setPen(pen)
                p.drawPolyline(poly)
        self._dot(p, self.to_px(*wm.project(kind, *self.target, self.home)), PATH_COLOR)

    def path_texts(self) -> list[str]:
        """Zeilen für die Beschriftung: Gegenstation, SP und LP (Grad, km)."""
        if not (self.home and self.target):
            return []
        d = wm.angular_distance(*self.home, *self.target) * KM_PER_RAD
        sp = wm.bearing(*self.home, *self.target)
        lines = [self.target_label] if self.target_label else []
        lines.append(tr("SP {deg}° · {km} km (durchgezogen)", deg=round(sp) % 360,
                        km=num(round(d))))
        lines.append(tr("LP {deg}° · {km} km (gestrichelt)", deg=round(sp + 180) % 360,
                        km=num(round(2 * math.pi * KM_PER_RAD - d))))
        return lines

    def _draw_credit(self, p: QPainter, colors: dict) -> None:
        """Quellenangabe unten rechts (NASA bittet darum; Natural Earth freiwillig)."""
        text = {"nasa": "NASA Earth Observatory", "relief": "Natural Earth"}.get(
            self.background if self.raster() else "", "Natural Earth")
        f = QFont(self.font())
        f.setPointSizeF(max(6.5, f.pointSizeF() - 2.5))
        p.setFont(f)
        fm = p.fontMetrics()
        x = self.width() - fm.horizontalAdvance(text) - 6
        y = self.height() - fm.descent() - 3
        p.setPen(colors["halo"])
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p.drawText(QPointF(x + dx, y + dy), text)
        p.setPen(QColor(colors["loc"]))
        p.drawText(QPointF(x, y), text)

    def _draw_legend(self, p: QPainter, colors: dict) -> None:
        lines = self.path_texts() if self.show_path else []
        lines += self.notes
        if not self.home:
            lines.append(tr("Kein eigener Standort – Locator im Log eintragen"))
        if self.status_line:
            lines.append(self.status_line)
        if not lines:
            return
        p.setFont(QFont(self.font()))
        fm = p.fontMetrics()
        bw = max(fm.horizontalAdvance(t) for t in lines) + 12
        bh = fm.height() * len(lines) + 8
        box = QRectF(6, 6, bw, bh)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colors["box"])
        p.drawRoundedRect(box, 4, 4)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QColor(colors["text"]))
        for i, t in enumerate(lines):
            p.drawText(QPointF(box.left() + 6, box.top() + 4 + fm.ascent() + i * fm.height()), t)

    # ---------------------------------------------------------------- Maus
    def deg_per_px(self, px: float, py: float) -> float:
        """Maßstab an dieser Stelle: Grad (Großkreis) je Bildpunkt."""
        kind, home = self.effective_kind(), self._home()
        a = wm.unproject(kind, *self.from_px(px, py), home)
        b = wm.unproject(kind, *self.from_px(px, py + 10), home)
        if a is None or b is None:
            return 1.0
        return math.degrees(wm.angular_distance(*a, *b)) / 10

    def tip_at(self, px: float, py: float) -> str:
        """Tooltip: Richtung und Entfernung; Locator erst, wenn er groß genug zu sehen ist.
        Über einer Bake oder einem Spot: deren Angaben."""
        hit = self.mark_at(px, py)
        if hit:
            return hit[1]["tip"]
        pos = wm.unproject(self.effective_kind(), *self.from_px(px, py), self._home())
        if pos is None:
            return ""
        parts = []
        digits = wm.locator_digits(self.deg_per_px(px, py))
        if digits:
            parts.append(wm.grid_square(*pos)[:digits])
        if self.home:
            d = wm.angular_distance(*self.home, *pos) * KM_PER_RAD
            parts.append(tr("{deg}° · {km} km", deg=round(wm.bearing(*self.home, *pos)) % 360,
                            km=num(round(d))))
        return " · ".join(parts)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.RightButton:
            hit = self.mark_at(e.position().x(), e.position().y())
            gpos = e.globalPosition().toPoint()
            if hit and hit[0] == "spot" and self.on_spot_menu:
                self.on_spot_menu(hit[1]["spots"], gpos)
            elif self.on_point_menu:                    # Bake oder freie Stelle (0.8.23.1)
                pos = wm.unproject(self.effective_kind(),
                                   *self.from_px(e.position().x(), e.position().y()), self._home())
                if hit or pos is not None:
                    self.on_point_menu(hit[0] if hit else "", hit[1] if hit else None,
                                       (hit[1]["lat"], hit[1]["lon"]) if hit else pos, gpos)
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position()
        if e.button() == Qt.MouseButton.LeftButton and self.zoom > 1:
            self._drag = (e.position(), self.center)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            QToolTip.hideText()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self._drag is not None:
            self._drag = None
            self.unsetCursor()
        press, self._press = self._press, None
        if press is None or e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position()
        if abs(pos.x() - press.x()) + abs(pos.y() - press.y()) > 4:
            return                          # gezogen, nicht geklickt
        hit = self.mark_at(pos.x(), pos.y())
        if hit and hit[0] == "spot" and self.on_spot_click:
            self.on_spot_click(hit[1]["spots"], e.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, _e):  # noqa: N802
        self.reset_view()                   # wieder die ganze Karte

    def mouseMoveEvent(self, e):  # noqa: N802
        pt = e.position()
        if self._drag is not None:
            start, c0 = self._drag
            k = self.zoom * self._scale()
            self.set_view(self.zoom, (c0[0] - (pt.x() - start.x()) / k,
                                      c0[1] + (pt.y() - start.y()) / k))
            return
        tip = self.tip_at(pt.x(), pt.y())
        if tip:
            QToolTip.showText(e.globalPosition().toPoint(), tip, self)
        else:
            QToolTip.hideText()

    def zoom_at(self, px: float, py: float, factor: float) -> None:
        """Zoomen; der Punkt unter der Maus bleibt, wo er ist."""
        ux, uy = self.from_px(px, py)
        z = min(max(self.zoom * factor, 1.0), ZOOM_MAX)
        k = z * self._scale()
        self.set_view(z, (ux - (px - self.width() / 2) / k, uy + (py - self.height() / 2) / k))

    def wheelEvent(self, e):  # noqa: N802
        steps = e.angleDelta().y() / 120.0
        if steps:
            pt = e.position()
            self.zoom_at(pt.x(), pt.y(), ZOOM_STEP ** steps)
            tip = self.tip_at(pt.x(), pt.y())
            if tip:
                QToolTip.showText(e.globalPosition().toPoint(), tip, self)
        e.accept()


class MapView(QWidget):
    """Fenster-Inhalt: Bedienzeilen + Karte. Einstellungen landen sofort in cfg (on_change)."""

    # cfg-Schlüssel, Eigenschaft der Karte, Zeile der Bedienleiste
    OPTIONS = (("map_daynight", "show_night", 0), ("map_twilight", "show_twilight", 0),
               ("map_path", "show_path", 0), ("map_grid", "show_grid", 1),
               ("map_rivers", "show_rivers", 1), ("map_cities", "show_cities", 1),
               ("map_beacons", "show_beacons", 1), ("map_spots", "show_spots", 1),
               ("map_beam", "show_beam", 1))

    @staticmethod
    def _texts() -> dict[str, tuple[str, str]]:
        """Beschriftung und Tooltip je Häkchen (hier, damit tr() die Sprache schon kennt)."""
        return {
            "map_daynight": (tr("Tag/Nacht"), ""),
            "map_twilight": (tr("Dämmerung (Grayline)"),
                             tr("Weicher Übergang, solange die Sonne bis zu 12° unter dem "
                                "Horizont steht – dort geht DX oft besonders gut")),
            "map_path": (tr("Weg zur Gegenstation"),
                         tr("Short Path durchgezogen, Long Path gestrichelt – zum Rufzeichen in "
                            "der Eingabezeile")),
            "map_grid": (tr("Locator-Gitter"),
                         tr("Beim Hineinzoomen: erst Großfelder (JN), dann Felder (JN59), ganz "
                            "nah Kleinfelder (JN59me)")),
            "map_rivers": (tr("Flüsse"), tr("Beim Hineinzoomen werden es mehr")),
            "map_cities": (tr("Städte"), tr("Erst die großen, beim Hineinzoomen immer mehr – "
                                            "Namen überdecken sich nie")),
            "map_beacons": (tr("Baken"),
                            tr("NCDXF/IARU-Baken in den Farben der Bakenanzeige (grün = gut "
                               "gehört, gelb = schwach, grau = nicht gehört). Verbindet sich "
                               "dafür selbst mit dem Reverse Beacon Network – das Fenster "
                               "Bakenanzeige muss nicht offen sein")),
            "map_spots": (tr("Cluster-Spots"),
                          tr("Spots des aktiven Bandes am Standort ihres Landes, Farben wie in "
                             "der Bandmap. Klick = Funkgerät einstellen wie in der Bandmap, "
                             "Rechtsklick = QRZ.com. Verbindet sich dafür selbst mit dem "
                             "DX-Cluster – die Bandmap muss nicht offen sein")),
            "map_beam": (tr("Beam"),
                         tr("Richtung des Rotors als Keil vom eigenen Standort, beim Drehen das "
                            "Ziel gestrichelt. Rechtsklick in die Karte: Rotor dorthin drehen. "
                            "Nur mit eingerichtetem Rotor")),
        }

    def __init__(self, cfg: dict, on_change=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.on_change = on_change
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        rows = [QHBoxLayout(), QHBoxLayout()]
        self.kind = QComboBox()
        self.kind.addItem(tr("Weltkarte"), wm.RECT)
        self.kind.addItem(tr("Kreiskarte (um den eigenen Standort)"), wm.AZI)
        self.kind.setToolTip(tr("Kreiskarte: Jede gerade Linie von der Mitte ist eine "
                                "Beamrichtung, der Rand ist der Gegenpunkt der Erde"))
        rows[0].addWidget(self.kind)
        self.bg = QComboBox()
        self.bg.addItem(tr("Satellit (NASA)"), "nasa")
        self.bg.addItem(tr("Relief (Natural Earth)"), "relief")
        self.bg.addItem(tr("Einfach (ohne Download)"), "simple")
        self.bg.setToolTip(tr("Kartenbild: wird beim ersten Mal heruntergeladen, danach offline. "
                              "Das NASA-Bild zeigt den aktuellen Monat, nachts die Stadtlichter."))
        rows[0].addWidget(self.bg)
        self.on_need_download = None            # Hauptfenster: fragt und lädt (Hintergrund)
        self.checks = {}
        texts = self._texts()
        for key, _attr, row in self.OPTIONS:
            text, tip = texts[key]
            chk = QCheckBox(text)
            if tip:
                chk.setToolTip(tip)
            rows[row].addWidget(chk)
            self.checks[key] = chk
        self.chk_night = self.checks["map_daynight"]
        self.chk_twilight = self.checks["map_twilight"]
        self.chk_path = self.checks["map_path"]
        rows[0].addStretch(1)
        rows[1].addStretch(1)
        hint = QLabel(tr("Mausrad: zoomen · Ziehen: verschieben · Doppelklick: ganze Karte"))
        hint.setStyleSheet("color:#888888;")
        # schmales Fenster: umbrechen statt abschneiden (Nutzerwunsch)
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        hint.setMinimumWidth(120)
        self.hint = hint
        rows[1].addWidget(hint, 1)
        for r in rows:
            lay.addLayout(r)
        self.canvas = MapCanvas(self)
        lay.addWidget(self.canvas, 1)
        self._load_cfg()
        self.kind.currentIndexChanged.connect(lambda _i: self._changed())
        self.bg.currentIndexChanged.connect(lambda _i: self._changed(ask=True))
        for chk in self.checks.values():
            chk.toggled.connect(lambda _v: self._changed())
        self.timer = QTimer(self)
        self.timer.setInterval(30_000)          # Tag/Nacht wandert ~1/4° pro Minute
        self.timer.timeout.connect(self.canvas.update)

    def _load_cfg(self) -> None:
        i = self.kind.findData(self.cfg.get("map_kind", wm.RECT))
        self.kind.setCurrentIndex(max(i, 0))
        i = self.bg.findData(self.cfg.get("map_background", "nasa"))
        self.bg.setCurrentIndex(max(i, 0))
        self.reload_layers()
        for key, chk in self.checks.items():
            chk.setChecked(bool(self.cfg.get(key, True)))
        self._apply()

    def _apply(self) -> None:
        c = self.canvas
        kind = self.kind.currentData() or wm.RECT
        if kind != c.kind:
            c.zoom, c.center = 1.0, (0.0, 0.0)  # andere Kartenart: wieder alles zeigen
        c.kind = kind
        c.background = self.bg.currentData() or "simple"
        for key, attr, _row in self.OPTIONS:
            setattr(c, attr, self.checks[key].isChecked())
        self.chk_twilight.setEnabled(c.show_night)
        c.update()

    def _changed(self, ask: bool = False) -> None:
        self._apply()
        if ask:
            self.check_download()
        self.cfg["map_background"] = self.canvas.background
        self.cfg["map_kind"] = self.canvas.kind
        for key, attr, _row in self.OPTIONS:
            self.cfg[key] = getattr(self.canvas, attr)
        if self.on_change:
            self.on_change()

    def reload_layers(self) -> None:
        """Vorhandene Kartenbilder (neu) einlesen – nach einem Download."""
        from .. import mapimages as mi
        layers = {}
        for bg in ("nasa", "relief"):
            if mi.available(bg):
                for name in mi.LAYERS[bg]:
                    layers[name] = mi.RasterLayer(name)
        self.canvas.layers = layers
        self.canvas._grid_key = None
        self.canvas.update()

    def set_background(self, bg: str) -> None:
        i = self.bg.findData(bg)
        if i >= 0 and i != self.bg.currentIndex():
            self.bg.blockSignals(True)
            self.bg.setCurrentIndex(i)
            self.bg.blockSignals(False)
            self._changed()

    def check_download(self) -> None:
        """Gewählter Hintergrund noch nicht da → Hauptfenster fragen/laden lassen."""
        from .. import mapimages as mi
        bg = self.canvas.background
        if bg != "simple" and not mi.available(bg) and self.on_need_download:
            self.on_need_download(bg)

    def set_active(self, on: bool) -> None:
        """Fenster offen = läuft (Regel: offen = an). Zu = kein Neuzeichnen im Hintergrund."""
        if on:
            self.timer.start()
            self.canvas.update()
            self.check_download()
        else:
            self.timer.stop()

    def set_home(self, home: tuple[float, float] | None, label: str = "") -> None:
        if home != self.canvas.home:
            self.canvas.home = home
            self.canvas.home_label = label
            self.canvas.update()
        idx = self.kind.findData(wm.AZI)
        self.kind.setItemText(idx, tr("Kreiskarte (um {grid})", grid=label) if label
                              else tr("Kreiskarte (um den eigenen Standort)"))

    def set_target(self, target: tuple[float, float] | None, label: str = "") -> None:
        if (target, label) != (self.canvas.target, self.canvas.target_label):
            self.canvas.target = target
            self.canvas.target_label = label
            self.canvas.update()
