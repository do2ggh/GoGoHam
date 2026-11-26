"""0.8.15: Kartenbilder (NASA Satellit Tag/Nacht, Natural Earth Relief) – herunterladen, in
Kacheln zerlegen, lesen, Monatswechsel. Läuft mit echtem Qt (offscreen) und kleinen Testbildern
von der Festplatte statt aus dem Internet."""

import json
import struct
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).parent

SCRIPT = r'''
import json, struct, sys, zipfile
from datetime import date
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
app = QApplication([])
from gogoham import mapimages as mi
work = Path(sys.argv[2])
out = {}

def jpg(path, w, h, color):
    a = np.zeros((h, w, 3), np.uint8); a[:] = color
    a[: h // 2, : w // 2] = (255, 0, 0)            # Nordwesten rot (zum Prüfen der Lage)
    QImage(a.data, w, h, w * 3, QImage.Format.Format_RGB888).save(str(path), "JPG", 95)

def tiff(path, w, h):
    a = np.zeros((h, w, 3), np.uint8); a[:] = (0, 128, 0); a[h // 2:, w // 2:] = (0, 0, 255)
    data = a.tobytes()
    ifd = [(256, 4, 1, w), (257, 4, 1, h), (258, 3, 1, 8), (259, 3, 1, 1), (262, 3, 1, 2),
           (273, 4, 1, 8), (277, 3, 1, 3), (278, 4, 1, h), (279, 4, 1, len(data))]
    with open(path, "wb") as f:
        f.write(b"II" + struct.pack("<HI", 42, 8 + len(data)))
        f.write(data)
        f.write(struct.pack("<H", len(ifd)))
        for tag, typ, cnt, val in ifd:
            f.write(struct.pack("<HHI", tag, typ, cnt) + (struct.pack("<HH", val, 0) if typ == 3 else struct.pack("<I", val)))
        f.write(struct.pack("<I", 0))

# kleine „Weltbilder“ (2:1) – Kacheln werden kleiner gestellt, damit es mehrere gibt
mi.TILE, mi.OVERVIEW = 100, (240, 120)
jpg(work / "day.jpg", 400, 200, (0, 0, 200))
jpg(work / "night.jpg", 300, 150, (10, 10, 10))
tiff(work / "relief.tif", 360, 180)
with zipfile.ZipFile(work / "relief.zip", "w") as z:
    z.write(work / "relief.tif", "NE1_50M_SR_W/NE1_50M_SR_W.tif")
mi.day_url = lambda m: (work / "day.jpg").as_uri()
mi.NIGHT_URL = (work / "night.jpg").as_uri()
mi.RELIEF_URL = (work / "relief.zip").as_uri()

out["before"] = [mi.available("nasa"), mi.available("relief"), mi.nasa_month(), mi.nasa_update_due()]
d = mi.MapDownloader("nasa", month=10); d.run()
out["nasa"] = [d.error, d.percent, mi.available("nasa"), mi.nasa_month(),
               sorted(p.name for p in (mi.maps_dir() / "nasa-day").iterdir())[:3],
               (mi.maps_dir() / "download").exists()]
out["due"] = [mi.nasa_update_due(date(2026, 10, 3)), mi.nasa_update_due(date(2026, 11, 1))]
d = mi.MapDownloader("nasa-month", month=11); d.run()
out["month"] = [d.error, mi.nasa_month(), mi.nasa_update_due(date(2026, 11, 20)),
                sorted(p.name for p in mi.maps_dir().iterdir())]
d = mi.MapDownloader("relief"); d.run()
out["relief"] = [d.error, mi.available("relief")]
# Lesen: Übersicht (ganz heraus) und Kacheln (nah) – Nordwesten rot, Südosten blau/grün
lay = mi.RasterLayer("nasa-day")
lat = np.array([[45.0, -45.0]]); lon = np.array([[-90.0, 90.0]])
far = lay.sample(lat, lon, 1.0)
near = lay.sample(np.array([[45.0, 44.0]]), np.array([[-90.0, -89.0]]), 0.01)
out["sample"] = [far[0, 0].round().tolist(), far[0, 1].round().tolist(), near[0, 0].round().tolist(),
                 len(lay._tiles)]
rel = mi.RasterLayer("relief")
out["relief_px"] = [rel.sample(np.array([[45.0]]), np.array([[-90.0]]), 1.0)[0, 0].round().tolist(),
                    rel.sample(np.array([[-45.0]]), np.array([[90.0]]), 0.01)[0, 0].round().tolist()]
# Fehler beim Download: nichts kaputt, Meldung
mi.day_url = lambda m: (work / "fehlt.jpg").as_uri()
d = mi.MapDownloader("nasa-month", month=12); d.run()
out["error"] = [bool(d.error), mi.nasa_month(), mi.available("nasa")]

# Karte mit NASA-Hintergrund: Tagseite = Tagbild, Nachtseite = Nachtbild
from datetime import datetime, timezone
from gogoham.gui.mapview import MapView
v = MapView({"map_kind": "rect", "map_background": "nasa"}); v.resize(800, 500)
v.show(); app.processEvents(); c = v.canvas; c._rebuild.stop()
c.now = datetime(2026, 6, 21, 12, tzinfo=timezone.utc)      # Sonne über Afrika
img = c.image(c.width(), c.height())
def px(lat, lon):
    import gogoham.worldmap as wm
    pt = c.to_px(*wm.project("rect", lat, lon, (0, 0)))
    col = img.pixelColor(int(pt.x()), int(pt.y()))
    return [col.red(), col.green(), col.blue()]
out["nasa_map"] = [c.raster() is not None, px(-30, 20), px(-30, 160)]
v.mapview_bg = v.bg.currentData()
v.set_background("relief")
out["relief_map"] = [c.background, c.raster() is not None]
print("RESULT " + json.dumps(out))
v.close()
'''


def test_download_tiles_month_and_map(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(tmp_path / "cfg"), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent), str(work)],
                       capture_output=True, text=True, env=env, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["before"] == [False, False, None, False]
    err, pct, ok, month, files, leftover = o["nasa"]
    assert err == "" and pct == 100 and ok and month == 10
    assert files == ["meta.json", "overview.jpg", "t_0_0.jpg"] and leftover is False
    assert o["due"] == [False, True]                     # neuer Monat → neues Bild fällig
    assert o["month"][:3] == ["", 11, False]
    assert o["month"][3] == ["nasa-day", "nasa-night"]   # keine halben Ordner übrig
    assert o["relief"] == ["", True]
    far_nw, far_se, near_nw, tiles = o["sample"]
    assert far_nw[0] > 200 and far_nw[2] < 60            # Nordwesten rot
    assert far_se[2] > 150 and far_se[0] < 60            # sonst blau
    assert near_nw[0] > 200 and tiles >= 1               # nah: aus den Kacheln
    assert o["relief_px"][0][1] > 100                    # Relief: grün
    assert o["relief_px"][1][2] > 200                    # Südosten blau
    assert o["error"] == [True, 11, True]                # altes Bild bleibt, nichts kaputt
    has, day, night = o["nasa_map"]
    assert has and day[2] > 150                           # Tagseite: Tagbild (blau)
    assert max(night) < 60                                # Nachtseite: dunkles Nachtbild
    assert o["relief_map"] == ["relief", True]


def test_tiff_reader_rejects_compressed(tmp_path):
    from gogoham import mapimages as mi
    p = tmp_path / "x.tif"
    ifd = [(256, 4, 1, 4), (257, 4, 1, 2), (259, 3, 1, 5), (273, 4, 1, 8), (277, 3, 1, 3)]
    with open(p, "wb") as f:
        f.write(b"II" + struct.pack("<HI", 42, 8 + 24) + b"\0" * 24)
        f.write(struct.pack("<H", len(ifd)))
        for tag, typ, cnt, val in ifd:
            f.write(struct.pack("<HHI", tag, typ, cnt)
                    + (struct.pack("<HH", val, 0) if typ == 3 else struct.pack("<I", val)))
        f.write(struct.pack("<I", 0))
    try:
        mi.tiff_rows(p)
    except ValueError as e:
        assert "unkomprimiert" in str(e)
    else:
        raise AssertionError("komprimiertes TIFF hätte abgelehnt werden müssen")


def test_daily_update_asks_for_new_month(monkeypatch):
    from gogoham import dailyupdate as du
    from gogoham import mapimages as mi
    monkeypatch.setattr(du, "_online", lambda t: True)
    import gogoham.rulesupdate as ru
    monkeypatch.setattr(ru, "check_and_download", lambda timeout=8: type("R", (), {"offline": True})())
    monkeypatch.setattr(mi, "nasa_update_due", lambda today=None: True)
    monkeypatch.setattr(du, "remote_is_newer", lambda *a, **k: False)   # kein echtes Internet
    import gogoham.dok as dok
    monkeypatch.setattr(dok, "age_days", lambda: None)
    res = du.run(running=False, flags_due=False)
    assert res.map_month and "neuen Monats" in res.summary()
    res = du.run(running=True, flags_due=False)          # Contest läuft: nicht jetzt
    assert not res.map_month and "Kartenbild" in res.summary()
