"""Kartenbilder für die Grayline-Karte (ab 0.8.15): einmal herunterladen, in Kacheln zerlegen,
danach offline – wie die Flaggen.

- „nasa“:  NASA Blue Marble: Next Generation (Tag, Bild des aktuellen Monats, 21600×10800)
           + NASA Black Marble 2016 (Nacht mit Stadtlichtern, 13500×6750).
           „Image courtesy NASA Earth Observatory“ – frei nutzbar mit Quellenangabe.
- „relief“: Natural Earth I mit Relief und Gewässern, 1:50m (10800×5400), gemeinfrei.

Gespeichert unter ~/.local/share/gogoham/maps/<Ebene>/: overview.jpg (5400×2700, für die ganze
Welt), Kacheln t_<Zeile>_<Spalte>.jpg (1350×1350, für das Hineinzoomen) und meta.json.
Ebenen: nasa-day, nasa-night, relief. Große Bilder werden streifenweise gelesen (wenig Speicher).
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import threading
import urllib.request
import zipfile
from collections import OrderedDict
from datetime import date
from pathlib import Path

import numpy as np

from .i18n import tr

NASA = "https://assets.science.nasa.gov/content/dam/science/esd/eo/images"
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december")
NIGHT_URL = f"{NASA}/imagerecords/144000/144898/BlackMarble_2016_3km.jpg"
RELIEF_URL = "https://naciscdn.org/naturalearth/50m/raster/NE1_50M_SR_W.zip"
TILE = 1350
OVERVIEW = (5400, 2700)
CACHE_TILES = 24                    # höchstens so viele Kacheln im Speicher (je ~5,5 MB)

LAYERS = {"nasa": ("nasa-day", "nasa-night"), "relief": ("relief",), "simple": ()}
SIZE_MB = {"nasa": 40, "relief": 90}        # ungefähre Download-Größe


def day_url(month: int) -> str:
    name = MONTHS[month - 1]
    return (f"{NASA}/bmng/bmng-topography-bathymetry/{name}/"
            f"world.topo.bathy.2004{month:02d}.3x21600x10800.jpg")


def maps_dir() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "gogoham" / "maps"


def layer_meta(name: str) -> dict | None:
    p = maps_dir() / name / "meta.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def available(background: str) -> bool:
    """Sind alle Bilder für diesen Hintergrund vorhanden?"""
    layers = LAYERS.get(background, ())
    return bool(layers) and all(layer_meta(n) is not None for n in layers)


def nasa_month() -> int | None:
    m = layer_meta("nasa-day")
    return int(m["month"]) if m and m.get("month") else None


def nasa_update_due(today: date | None = None) -> bool:
    """Monatsbild veraltet? (nur, wenn die NASA-Bilder überhaupt schon geladen wurden)"""
    m = nasa_month()
    return m is not None and m != (today or date.today()).month


# ------------------------------------------------------------------ Bilder lesen
def _qimage_rgb(img) -> np.ndarray:
    """QImage → numpy (h, w, 3) uint8."""
    from PySide6.QtGui import QImage
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    arr = np.frombuffer(img.constBits(), dtype=np.uint8).reshape(h, bpl)[:, :w * 3]
    return arr.reshape(h, w, 3).copy()


def _save_jpg(arr: np.ndarray, path: Path, quality: int = 90) -> None:
    from PySide6.QtGui import QImage
    arr = np.ascontiguousarray(arr)
    h, w, _ = arr.shape
    img = QImage(arr.data, w, h, w * 3, QImage.Format.Format_RGB888)
    tmp = path.with_suffix(".tmp.jpg")
    if not img.save(str(tmp), "JPG", quality):
        raise OSError(tr("Bild konnte nicht gespeichert werden: {p}", p=path))
    tmp.replace(path)


def tiff_rows(path: Path) -> np.ndarray:
    """Unkomprimiertes RGB-TIFF (Natural Earth) als Speicherabbild (h, w, 3) – liest nur, was
    gebraucht wird. Andere TIFF-Arten: ValueError."""
    with open(path, "rb") as f:
        head = f.read(8)
        bo = {b"II": "<", b"MM": ">"}.get(head[:2])
        if bo is None or struct.unpack(bo + "H", head[2:4])[0] != 42:
            raise ValueError("kein TIFF")
        f.seek(struct.unpack(bo + "I", head[4:8])[0])
        n = struct.unpack(bo + "H", f.read(2))[0]
        tags = {}
        sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8}
        for _ in range(n):
            tag, typ, cnt, val = struct.unpack(bo + "HHI4s", f.read(12))
            size = sizes.get(typ, 1) * cnt
            fmt = {3: "H", 4: "I"}.get(typ)
            if fmt is None:
                continue
            if size <= 4:
                vals = struct.unpack(bo + fmt * cnt, val[:size])
            else:
                pos = f.tell()
                f.seek(struct.unpack(bo + "I", val)[0])
                vals = struct.unpack(bo + fmt * cnt, f.read(size))
                f.seek(pos)
            tags[tag] = vals
    w, h = tags[256][0], tags[257][0]
    if tags.get(259, (1,))[0] != 1 or tags.get(277, (1,))[0] != 3 or tags.get(258, (8,))[0] != 8:
        raise ValueError("nur unkomprimiertes RGB-TIFF")
    offsets = tags[273]
    rows = tags.get(278, (h,))[0]
    # Streifen müssen lückenlos hintereinander liegen (bei Natural Earth so)
    for i in range(1, len(offsets)):
        if offsets[i] != offsets[0] + i * rows * w * 3:
            raise ValueError("TIFF-Streifen nicht zusammenhängend")
    return np.memmap(path, dtype=np.uint8, mode="r", offset=offsets[0], shape=(h, w, 3))


class _JpegStrips:
    """Großes JPEG streifenweise lesen (Qt schneidet beim Entpacken aus – wenig Speicher)."""

    def __init__(self, path: Path):
        from PySide6.QtGui import QImageReader
        self.path = path
        r = QImageReader(str(path))
        s = r.size()
        if not s.isValid():
            raise ValueError(tr("Bild nicht lesbar: {p}", p=path.name))
        self.shape = (s.height(), s.width(), 3)

    def rows(self, y0: int, y1: int) -> np.ndarray:
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QImageReader
        r = QImageReader(str(self.path))
        r.setClipRect(QRect(0, y0, self.shape[1], y1 - y0))
        img = r.read()
        if img.isNull():
            raise ValueError(tr("Bild nicht lesbar: {p}", p=self.path.name))
        return _qimage_rgb(img)


def build_layer(src, out: Path, extra: dict | None = None, progress=None) -> None:
    """Bild (numpy-Abbild oder _JpegStrips) in Übersicht + Kacheln zerlegen; erst in einen
    Nebenordner, dann austauschen – ein halb fertiger Stand bleibt nie liegen."""
    h, w, _ = src.shape
    cols, rows = -(-w // TILE), -(-h // TILE)
    tmp = out.with_name(out.name + ".neu")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    ow, oh = OVERVIEW
    overview = np.zeros((oh, ow, 3), dtype=np.uint8)
    for r in range(rows):
        y0, y1 = r * TILE, min(h, (r + 1) * TILE)
        strip = src.rows(y0, y1) if hasattr(src, "rows") else np.asarray(src[y0:y1])
        for c in range(cols):
            x0, x1 = c * TILE, min(w, (c + 1) * TILE)
            _save_jpg(strip[:, x0:x1], tmp / f"t_{r}_{c}.jpg")
        # Übersicht: Streifen verkleinern (Mittelwert über ganze Blöcke, sonst nächster Punkt)
        oy0, oy1 = round(y0 * oh / h), round(y1 * oh / h)
        if oy1 > oy0:
            ys = np.clip(((np.arange(oy0, oy1) + 0.5) * h / oh - y0).astype(int), 0, y1 - y0 - 1)
            xs = np.clip(((np.arange(ow) + 0.5) * w / ow).astype(int), 0, w - 1)
            fy, fx = max(1, h // oh), max(1, w // ow)
            if fy > 1 or fx > 1:
                acc = np.zeros((len(ys), ow, 3), dtype=np.float32)
                for dy in range(fy):
                    for dx in range(fx):
                        acc += strip[np.clip(ys - fy // 2 + dy, 0, y1 - y0 - 1)][
                            :, np.clip(xs - fx // 2 + dx, 0, w - 1)]
                overview[oy0:oy1] = (acc / (fy * fx)).astype(np.uint8)
            else:
                overview[oy0:oy1] = strip[ys][:, xs]
        del strip
        if progress:
            progress((r + 1) / rows)
    _save_jpg(overview, tmp / "overview.jpg")
    meta = {"w": w, "h": h, "tile": TILE, "cols": cols, "rows": rows}
    meta.update(extra or {})
    (tmp / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    old = out.with_name(out.name + ".alt")
    shutil.rmtree(old, ignore_errors=True)
    if out.exists():
        out.rename(old)
    tmp.rename(out)
    shutil.rmtree(old, ignore_errors=True)


# ------------------------------------------------------------------ Herunterladen
class MapDownloader(threading.Thread):
    """Lädt die Bilder für „nasa“ (Tag + Nacht), „nasa-month“ (nur neues Monatsbild) oder
    „relief“ im Hintergrund und zerlegt sie in Kacheln. Fortschritt: .percent, .phase."""

    def __init__(self, what: str, month: int | None = None, timeout: float = 60.0):
        super().__init__(daemon=True, name="map-images")
        self.what = what
        self.month = month or date.today().month
        self.timeout = timeout
        self.percent = 0
        self.phase = ""
        self.error = ""
        self.background = "relief" if what == "relief" else "nasa"

    def _get(self, url: str, target: Path, share: tuple[float, float]) -> None:
        req = urllib.request.Request(url, headers={"User-Agent": "GoGoHam"})
        part = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(req, timeout=self.timeout) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    self.percent = int(share[0] + (share[1] - share[0]) * got / total)
        part.replace(target)

    def _build(self, src, name: str, share: tuple[float, float], extra=None) -> None:
        def prog(x):
            self.percent = int(share[0] + (share[1] - share[0]) * x)
        build_layer(src, maps_dir() / name, extra, prog)

    def run(self) -> None:  # noqa: D401 (Thread-Methode)
        work = maps_dir() / "download"
        try:
            work.mkdir(parents=True, exist_ok=True)
            if self.what in ("nasa", "nasa-month"):
                night_too = self.what == "nasa" or layer_meta("nasa-night") is None
                self.phase = tr("NASA-Bild des Monats wird geladen")
                f = work / "day.jpg"
                self._get(day_url(self.month), f, (0, 55 if night_too else 80))
                self.phase = tr("Kartenbild wird vorbereitet")
                self._build(_JpegStrips(f), "nasa-day", (55 if night_too else 80, 75 if night_too else 100),
                            {"month": self.month, "source": "NASA Blue Marble: Next Generation"})
                f.unlink(missing_ok=True)
                if night_too:
                    self.phase = tr("NASA-Nachtbild wird geladen")
                    f = work / "night.jpg"
                    self._get(NIGHT_URL, f, (75, 90))
                    self.phase = tr("Kartenbild wird vorbereitet")
                    self._build(_JpegStrips(f), "nasa-night", (90, 100),
                                {"source": "NASA Black Marble 2016"})
                    f.unlink(missing_ok=True)
            else:
                self.phase = tr("Reliefkarte wird geladen")
                z = work / "relief.zip"
                self._get(RELIEF_URL, z, (0, 70))
                self.phase = tr("Kartenbild wird vorbereitet")
                with zipfile.ZipFile(z) as zf:
                    name = next(n for n in zf.namelist() if n.lower().endswith(".tif"))
                    tif = work / "relief.tif"
                    with zf.open(name) as src, open(tif, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
                z.unlink(missing_ok=True)
                self._build(tiff_rows(tif), "relief", (75, 100),
                            {"source": "Natural Earth I, shaded relief, 1:50m"})
                tif.unlink(missing_ok=True)
            self.percent = 100
        except Exception as e:  # noqa: BLE001 – Download darf GoGoHam nie stören
            self.error = str(e) or e.__class__.__name__
        finally:
            shutil.rmtree(work, ignore_errors=True)


# ------------------------------------------------------------------ Lesen zur Laufzeit
class RasterLayer:
    """Eine Bildebene: Übersicht für die ganze Welt, Kacheln für nah. sample() liest weich
    (bilinear) je Bildpunkt; Kacheln werden nur bei Bedarf geladen (zuletzt benutzte bleiben)."""

    def __init__(self, name: str):
        self.dir = maps_dir() / name
        self.meta = layer_meta(name) or {}
        self._overview = None
        self._tiles: OrderedDict = OrderedDict()

    def ok(self) -> bool:
        return bool(self.meta)

    def overview(self) -> np.ndarray:
        if self._overview is None:
            from PySide6.QtGui import QImage
            self._overview = _qimage_rgb(QImage(str(self.dir / "overview.jpg")))
        return self._overview

    def _tile(self, r: int, c: int) -> np.ndarray:
        key = (r, c)
        if key in self._tiles:
            self._tiles.move_to_end(key)
            return self._tiles[key]
        from PySide6.QtGui import QImage
        img = QImage(str(self.dir / f"t_{r}_{c}.jpg"))
        arr = _qimage_rgb(img) if not img.isNull() else np.zeros((TILE, TILE, 3), np.uint8)
        self._tiles[key] = arr
        while len(self._tiles) > CACHE_TILES:
            self._tiles.popitem(last=False)
        return arr

    def sample(self, lat: np.ndarray, lon: np.ndarray, deg_per_px: float) -> np.ndarray:
        """Farben (h, w, 3) float32 für Breite/Länge (Grad)."""
        w, h = self.meta.get("w", 0), self.meta.get("h", 0)
        ov_dpp = 360.0 / OVERVIEW[0]
        if w and deg_per_px < ov_dpp * 0.8 and lat.size:
            lon0, lon1 = float(lon.min()), float(lon.max())
            lat0, lat1 = float(lat.min()), float(lat.max())
            if lon1 - lon0 < 90:                    # nah und nicht über die Datumsgrenze
                fx0 = int(max(0, (lon0 + 180) / 360 * w - 2))
                fx1 = int(min(w, (lon1 + 180) / 360 * w + 3))
                fy0 = int(max(0, (90 - lat1) / 180 * h - 2))
                fy1 = int(min(h, (90 - lat0) / 180 * h + 3))
                c0, c1 = fx0 // TILE, (fx1 - 1) // TILE
                r0, r1 = fy0 // TILE, (fy1 - 1) // TILE
                if (c1 - c0 + 1) * (r1 - r0 + 1) <= CACHE_TILES:
                    mosaic = np.vstack([np.hstack([self._tile(r, c) for c in range(c0, c1 + 1)])
                                        for r in range(r0, r1 + 1)])
                    box = (c0 * TILE / w * 360 - 180, (c0 * TILE + mosaic.shape[1]) / w * 360 - 180,
                           90 - (r0 * TILE + mosaic.shape[0]) / h * 180, 90 - r0 * TILE / h * 180)
                    return bilinear(mosaic, lat, lon, box)
        return bilinear(self.overview(), lat, lon, (-180.0, 180.0, -90.0, 90.0))


def bilinear(tex: np.ndarray, lat, lon, box) -> np.ndarray:
    """Weich aus einem gleichabständigen Bild lesen (box = lon0, lon1, lat0, lat1)."""
    th, tw, _ = tex.shape
    fx = np.clip((lon - box[0]) / (box[1] - box[0]) * tw - 0.5, 0, tw - 1.001)
    fy = np.clip((box[3] - lat) / (box[3] - box[2]) * th - 0.5, 0, th - 1.001)
    x0, y0 = fx.astype(np.int32), fy.astype(np.int32)
    ax, ay = (fx - x0)[..., None].astype(np.float32), (fy - y0)[..., None].astype(np.float32)
    a = tex[y0, x0].astype(np.float32) * (1 - ax) + tex[y0, x0 + 1].astype(np.float32) * ax
    b = tex[y0 + 1, x0].astype(np.float32) * (1 - ax) + tex[y0 + 1, x0 + 1].astype(np.float32) * ax
    return a * (1 - ay) + b * ay
