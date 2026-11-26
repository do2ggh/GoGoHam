"""0.8.15: Grayline-Karte – Sonnenstand, Kartenarten, Großkreis, Kartendaten und das Fenster
(offen = an, Häkchen beim Start, Weg zum Rufzeichen in der Eingabezeile)."""

import json
import math
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from gogoham import worldmap as wm
from gogoham.locator import latlon, paths

HERE = Path(__file__).parent
HOME = latlon("JN59ME")


def test_subsolar_point():
    lat, lon = wm.subsolar(datetime(2026, 6, 21, 12, tzinfo=timezone.utc))
    assert abs(lat - 23.44) < 0.1 and abs(lon) < 1.5           # Sommeranfang, Mittag UTC
    lat, _lon = wm.subsolar(datetime(2026, 3, 20, 14, 46, tzinfo=timezone.utc))
    assert abs(lat) < 0.1                                        # Tagundnachtgleiche
    lat, lon = wm.subsolar(datetime(2026, 11, 5, 12, tzinfo=timezone.utc))
    assert abs(lat + 15.8) < 0.2 and abs(lon + 4.1) < 0.3        # Zeitgleichung ~ +16 min


def test_day_night_and_twilight():
    sun = (0.0, 0.0)
    assert wm.sun_elevation(0, 0, sun) > 89
    assert wm.sun_elevation(0, 180, sun) < -89
    assert wm.night_alpha(10.0) == 0 and wm.night_alpha(-30.0) == 1
    assert 0.4 < float(wm.night_alpha(-6.0)) < 0.6               # mitten in der Dämmerung
    assert float(wm.night_alpha(-6.0, twilight=False)) == 1.0    # ohne Dämmerung: harte Grenze


def test_great_circle_matches_infobox_paths():
    boston = (42.36, -71.06)
    p = paths(*HOME, *boston)
    assert abs(wm.bearing(*HOME, *boston) - p["sp_deg"]) < 0.01
    sp = wm.great_circle(HOME, boston)
    lp = wm.great_circle(HOME, boston, long_path=True)
    for pts in (sp, lp):
        assert abs(pts[0][0] - HOME[0]) < 1e-6 and abs(pts[-1][0] - boston[0]) < 1e-6
        assert abs(pts[-1][1] - boston[1]) < 1e-6
    assert len(lp) > len(sp) * 4                                # LP ist viel länger
    # LP startet in Gegenrichtung
    first = wm.bearing(*HOME, *lp[1])
    assert abs((first - p["lp_deg"] + 180) % 360 - 180) < 1


def test_projections_round_trip():
    for kind in (wm.RECT, wm.AZI):
        for lat, lon in ((42.36, -71.06), (-33.87, 151.21), (64.1, -21.9), (0.0, 179.5)):
            x, y = wm.project(kind, lat, lon, HOME)
            back = wm.unproject(kind, x, y, HOME)
            assert abs(back[0] - lat) < 1e-6 and abs((back[1] - lon + 180) % 360 - 180) < 1e-6
    # Kreiskarte: Mitte = eigener Standort, Rand = Gegenpunkt, Norden oben
    assert wm.project(wm.AZI, *HOME, HOME) == (0.0, 0.0)
    x, y = wm.project(wm.AZI, -HOME[0], HOME[1] - 180, HOME)
    assert abs(math.hypot(x, y) - 1) < 1e-6
    x, y = wm.project(wm.AZI, 70.0, HOME[1], HOME)
    assert abs(x) < 1e-9 and y > 0
    # Bildraster: Mitte des Bildes = eigener Standort; außen nicht auf der Erde
    lat, lon, inside = wm.inverse_grid(wm.AZI, 101, 101, HOME)
    assert abs(lat[50, 50] - HOME[0]) < 1.5 and abs(lon[50, 50] - HOME[1]) < 2.5
    assert not inside[0, 0] and inside[50, 50]


def test_grid_square_and_line_split():
    assert wm.grid_square(*HOME) == "JN59me"
    assert wm.grid_square(-33.87, 151.21) == "QF56od"
    parts = wm.split_line([(0.9, 0), (0.99, 0), (-0.99, 0), (-0.9, 0)], 0.2)
    assert len(parts) == 2                                        # Datumsgrenze getrennt


def test_map_data_offline_public_domain():
    data = wm.load()
    assert "Natural Earth" in data["source"] and "1:10m" in data["source"]
    assert len(data["land"]) > 5000 and len(data["borders"]) > 1000
    assert len(data["lakes"]) > 1000 and len(data["rivers"]) > 1000
    for ring in data["land"][:500]:
        assert ring[:, 0].min() >= -180 and ring[:, 0].max() <= 180
        assert ring[:, 1].min() >= -90 and ring[:, 1].max() <= 90
    places = {p[0]: p for p in data["places"]}
    assert places["Munich"][5] == "München" and places["Nuremberg"][5] == "Nürnberg"
    assert places["Berlin"][4] == 1                               # Hauptstadt
    assert abs(places["Nuremberg"][1] - 49.45) < 0.05
    ranks = [p[3] for p in data["places"]]
    assert ranks == sorted(ranks) and ranks[0] == 0                # nach Rang sortiert
    assert wm.DATA.stat().st_size < 4_000_000


def test_locator_digits():
    assert wm.locator_digits(0.4) == 0           # ganze Welt: kein Locator
    assert wm.locator_digits(0.1) == 2
    assert wm.locator_digits(0.01) == 4
    assert wm.locator_digits(0.001) == 6


SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from datetime import datetime, timezone
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui import main_window
from gogoham.gui.mapview import land_mask
M = main_window.MainWindow
M._welcome = lambda self: None
M._ask_scp = lambda self, *a, **k: None
M._start_daily_update = lambda self, wait=10.0: None
asked = []
M._ask_map_download = lambda self, bg, mb: asked.append((bg, mb)) or False   # „Nein“
p = Path(sys.argv[2]) / "wpx.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="wpx-ssb", mycall="DO2GGH",
                                my_grid="JN59ME")); db.close()
cfg = cfgmod.load()
cfg.update(rig_enabled=False, wsjtx_enabled=False, last_log=str(p), map_beacons=False, map_spots=False, **json.loads(sys.argv[4]))
cfgmod.save(cfg)
def wait(n=3):
    for _ in range(n):
        app.processEvents()
w = M(); wait()
mv, c = w.map_view, w.map_view.canvas
out = {"start": [not w.map_dock.isHidden(), mv.timer.isActive(), w.act_map.isChecked()]}
view = [a.menu() for a in w.menuBar().actions() if a.text() == "&Fenster"][0]
out["view"] = [x.text() for x in view.actions() if not x.isSeparator()]
w.show(); wait()
if not json.loads(sys.argv[4]):
    # Rechtsklick-Menü (toggleViewAction) öffnet: Timer läuft, Standort gesetzt
    w.map_dock.toggleViewAction().trigger(); wait()
    out["asked"] = [asked, mv.bg.currentData(), cfgmod.load().get("map_background")]
    out["open"] = [not w.map_dock.isHidden(), mv.timer.isActive(), w.act_map.isChecked(),
                   w.map_dock.isFloating(), c.home is not None, mv.kind.itemText(1)]
    # Rufzeichen eintippen → Weg zur Gegenstation
    w.ed_call.setText("W1AW"); w.update_check(); wait()
    out["target"] = [c.target is not None, c.target_label, c.path_texts()]
    w.ed_call.setText(""); w.update_check(); wait()
    out["cleared"] = c.target
    # Land/Meer: Mitte Atlantik Meer, Mitte Afrika Land
    m = land_mask()
    def is_land(lat, lon):
        return bool(m[int((90 - lat) / 180 * m.shape[0]), int((lon + 180) / 360 * m.shape[1])])
    out["land"] = [is_land(30, -40), is_land(5, 20), is_land(49.2, 11.0), is_land(-80, 0)]
    # Einstellungen der Karte werden sofort gespeichert
    mv.kind.setCurrentIndex(1); mv.chk_twilight.setChecked(False); mv.chk_path.setChecked(False)
    saved = cfgmod.load()
    out["saved"] = [saved.get("map_kind"), saved.get("map_twilight"), saved.get("map_path"),
                    saved.get("map_daynight")]
    mv.chk_night.setChecked(False); wait()
    out["twilight_disabled"] = not mv.chk_twilight.isEnabled()
    # Zeichnen in beiden Kartenarten ohne Fehler, mit Tooltip
    c.now = datetime(2026, 11, 5, 16, tzinfo=timezone.utc)
    mv.chk_night.setChecked(True); mv.chk_path.setChecked(True)
    w.ed_call.setText("VK2ABC"); w.update_check(); wait()
    sizes = []
    for k in (0, 1):
        mv.kind.setCurrentIndex(k); c._rebuild.stop(); wait()
        img = c.grab().toImage(); sizes.append([img.width() > 300, img.height() > 200])
        r = c.map_rect()
        out.setdefault("tip_center", []).append(c.tip_at(r.center().x(), r.center().y()))
    out["drawn"] = sizes
    # Zoomen (0.8.15, Nutzerwunsch): Locator im Tooltip erst, wenn er groß genug zu sehen ist
    mv.kind.setCurrentIndex(0); wait()
    import gogoham.worldmap as wm
    hp = c.to_px(*wm.project("rect", *c.home, c.home))
    tips = []
    for z in (1, 3, 30, 300):
        c.reset_view(); c.zoom_at(hp.x(), hp.y(), z); c._rebuild.stop()
        c.grab()                                            # zeichnen (feinere Landmaske)
        tips.append(c.tip_at(hp.x() + 2, hp.y() + 2))
    out["zoom_tips"] = tips
    # Gitter, Städte (deutsche Namen), Flüsse und Seen beim Hineinzoomen
    c.reset_view(); c.zoom_at(hp.x(), hp.y(), 30); c._rebuild.stop(); c.grab()
    ov = c._overlays(c._colors())
    out["grid30"] = [len(ov["grid"]) > 10, sorted({lab[1] for lab in ov["grid_labels"]} & {"JN59", "JN58"})]
    out["cities30"] = sorted({t for _p, t, _c, _r in ov["cities"]} & {"Nürnberg", "München", "Regensburg"})
    out["rivers30"] = len(ov["rivers"]) > 0
    c.reset_view(); c._rebuild.stop(); c.grab()
    ov = c._overlays(c._colors())
    out["grid1"] = [len(ov["grid"]), len(ov["grid_labels"])]
    out["cities1"] = [len(ov["cities"]) < 120, "Nürnberg" in {t for _p, t, _c, _r in ov["cities"]}]
    mv.checks["map_cities"].setChecked(False); mv.checks["map_grid"].setChecked(False)
    c.zoom_at(hp.x(), hp.y(), 30); c._rebuild.stop(); c.grab()
    ov = c._overlays(c._colors())
    out["off"] = [len(ov["grid"]), len(ov["cities"]), cfgmod.load().get("map_grid"),
                  cfgmod.load().get("map_cities")]
    lm = __import__("gogoham.gui.mapview", fromlist=["x"])
    out["lake"] = [bool(lm.is_land(43.5, -87.0)), bool(lm.is_land(47.6, 9.4)),
                   bool(lm.is_land(49.2, 11.0))]   # Michigansee, Bodensee (grob), Franken
    out["zoom_home_fixed"] = [round(c.to_px(*wm.project("rect", *c.home, c.home)).x() - hp.x(), 3)]
    c.mouseDoubleClickEvent(None)
    out["reset"] = [c.zoom, c.center]
    c.zoom_at(hp.x(), hp.y(), 10000)
    out["zoom_max"] = c.zoom
    mv.kind.setCurrentIndex(1); wait()
    out["kind_resets_zoom"] = c.zoom
    # X schließt = aus
    w.map_dock.close(); wait()
    out["closed"] = [w.map_dock.isHidden(), mv.timer.isActive(), w.act_map.isChecked()]
w.close()
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def _run(tmp_path, flags):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    for d in (data / "gogoham", cfg / "gogoham", logs):
        d.mkdir(parents=True, exist_ok=True)
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(logs), str(HERE / "cty_sample.dat"), json.dumps(flags)],
                       capture_output=True, text=True, env=env, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    return json.loads(lines[-1][7:])


def test_map_window(tmp_path):
    o = _run(tmp_path, {})
    assert o["start"] == [False, False, False]                   # Standard: zu
    assert "Karte (Grayline)" in o["view"]
    assert o["asked"] == [[["nasa", 40]], "simple", "simple"]    # gefragt, „Nein“ → einfach
    assert o["open"] == [True, True, True, True, True, "Kreiskarte (um JN59ME)"]
    has, label, texts = o["target"]
    assert has and label.startswith("W1AW")
    assert texts[-2].startswith("SP ") and "durchgezogen" in texts[-2]
    assert texts[-1].startswith("LP ") and "gestrichelt" in texts[-1]
    assert o["cleared"] is None
    assert o["land"] == [False, True, True, True]
    assert o["saved"] == ["azimuthal", False, False, True]
    assert o["twilight_disabled"] is True
    assert o["drawn"] == [[True, True], [True, True]]
    tip = o["tip_center"][1]                                 # ganz heraus: kein Locator
    assert tip[0].isdigit() and tip.endswith(" 0 km")
    t1, t3, t30, t300 = o["zoom_tips"]
    assert t1[0].isdigit() and t3.startswith("JN · ") and t30.startswith("JN59 · ")
    assert t300.startswith("JN59me · ")
    assert o["zoom_home_fixed"] == [0.0]                     # Punkt unter der Maus bleibt
    assert o["reset"] == [1.0, [0.0, 0.0]]
    assert o["zoom_max"] == 600.0
    assert o["kind_resets_zoom"] == 1.0
    assert o["grid30"] == [True, ["JN58", "JN59"]]
    assert o["cities30"] == ["München", "Nürnberg", "Regensburg"]
    assert o["rivers30"] is True
    assert o["grid1"] == [0, 0]                                 # ganz heraus: kein Gitter
    assert o["cities1"] == [True, False]                        # nur große Städte
    assert o["off"] == [0, 0, False, False]
    assert o["lake"][0] is False and o["lake"][2] is True
    assert o["closed"] == [True, False, False]


def test_map_opens_at_start_when_ticked(tmp_path):
    o = _run(tmp_path, {"open_map": True})
    assert o["start"] == [True, True, True]
