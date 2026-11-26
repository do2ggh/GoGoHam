"""0.8.27: Bandöffnungs-Vorschau – Faustregel-Rechnung (propagation.py) und Fenster."""

import json
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from gogoham import propagation as pr

HERE = Path(__file__).parent
HOME = (49.2, 11.0)                      # JN59


def at(month, hour):
    return datetime(2026, month, 15, hour, 30, tzinfo=timezone.utc)


def lv(band, cont, when, sfi, k=2):
    return pr.grid_now(HOME, [band], when, sfi, k)[(band, cont)].level


def test_sunspots_from_sfi():
    assert pr.sunspots(63) < 1
    assert 95 < pr.sunspots(150) < 110
    assert pr.sunspots(70) < 12


def test_low_bands_night_high_bands_day():
    # Winternacht: 80 m nach NA offen, 10 m zu; Mittag: 80 m zu
    assert lv("80", "NA", at(1, 3), 100) >= pr.FAIR
    assert lv("10", "NA", at(1, 3), 100) == pr.CLOSED
    assert lv("80", "NA", at(1, 12), 100) <= pr.POOR
    assert lv("160", "EU", at(1, 12), 100) == pr.CLOSED
    assert lv("160", "EU", at(1, 0), 100) >= pr.FAIR


def test_sunspots_open_high_bands():
    # Winternachmittag nach NA: 15 m bei hohem SFI gut, bei niedrigem zu
    assert lv("15", "NA", at(1, 15), 150) == pr.GOOD
    assert lv("15", "NA", at(1, 15), 68) <= pr.POOR
    assert lv("20", "NA", at(1, 12), 70) >= pr.POOR


def test_k_index_hurts_polar_paths_only():
    p = pr.path(HOME, pr.TARGETS["NA"], at(1, 15), 150, 6)
    assert p.max_gmlat >= 58
    quiet = lv("20", "NA", at(1, 15), 150, 1)
    storm = lv("20", "NA", at(1, 15), 150, 6)
    assert storm <= quiet - 1
    east = pr.rate(p, pr.BAND_MHZ["20"], 6)           # Weg zur Ostküste: über den Norden
    assert east.polar and east.k_penalty == 2
    best = pr.grid_now(HOME, ["20"], at(1, 15), 150, 6)[("20", "NA")]
    assert best.region == "na_c" and not best.polar    # Karibik: nicht über den Norden
    af = pr.grid_now(HOME, ["20"], at(1, 12), 150, 5)[("20", "AF")]
    assert not af.polar and af.k_penalty == 0


def test_without_weather_uses_default():
    a = pr.grid_now(HOME, ["20"], at(1, 12), None, None)
    b = pr.grid_now(HOME, ["20"], at(1, 12), pr.DEFAULT_SFI, None)
    assert a == b


def test_hf_bands_and_hours():
    assert pr.hf_bands(["2m", "70cm"]) == []
    assert pr.hf_bands(["10", "160", "40", "6"]) == ["160", "40", "10"]
    t = pr.hours(datetime(2026, 11, 7, 18, 45, tzinfo=timezone.utc), 12)
    assert len(t) == 13 and t[1].hour == 19 and t[1].minute == 30 and t[12].hour == 6
    g = pr.grid_hours(HOME, ["40", "20"], "AS", t, 120, 2)
    assert len(g) == 26


class Spot:
    def __init__(self, call, spotter, freq, received):
        self.call, self.spotter_call, self.freq, self.received = call, spotter, freq, received

    @property
    def band(self):
        from gogoham.bands import band_for_freq
        return band_for_freq(self.freq)


def test_heard_counts_only_nearby_spotters():
    cont = {"K1AR": "NA", "DL1A": "EU", "W3LPL": "NA", "JA1X": "AS", "4U1UN": "NA",
            "EA8X": "AF", "EA1X": "EU", "DL2B": "EU"}.get
    pos = {"K1AR": (42.0, -71.0), "DL1A": (50.0, 10.0), "W3LPL": (39.0, -77.0),
           "JA1X": (36.0, 139.0), "EA8X": (28.0, -15.0), "EA1X": (43.0, -8.0),
           "DL2B": (50.5, 10.5)}.get
    now = 10_000.0
    spots = [Spot("K1AR", "DL1A", 14_025_000, now - 60),      # zählt: Melder nah, NA auf 20 m
             Spot("JA1X", "W3LPL", 14_030_000, now - 60),     # Melder in NA → nicht von hier
             Spot("EA8X", "EA1X", 21_030_000, now - 60),      # Melder in Spanien → zu weit weg
             Spot("DL2B", "DL1A", 28_030_000, now - 60),      # 70 km: Bodenwelle → zählt nicht
             Spot("K1AR", "DL1A", 21_025_000, now - 3600),    # zu alt
             Spot("K1AR", "DL1A", 144_300_000, now - 60)]     # UKW
    h = pr.heard(spots, [("4U1UN", "15", 2), ("4U1UN", "10", 0)], cont, pos, HOME, now)
    assert h == {("20", "NA"): 1, ("15", "NA"): 2}


def test_evening_afterglow_and_best_region():
    # 7.11.2026, 17:48 UTC, SFI 128, K 3: bei uns dunkel, an der US-Ostküste Mittag –
    # 15 m nach NA und AF muss offen sein (vom Nutzer per Cluster bestätigt)
    t = datetime(2026, 11, 7, 17, 48, tzinfo=timezone.utc)
    g = pr.grid_now(HOME, ["20", "15", "10"], t, 128, 3)
    assert g[("15", "NA")].level >= pr.FAIR and g[("15", "AF")].level >= pr.FAIR
    assert g[("20", "EU")].level >= pr.FAIR and g[("10", "NA")].level >= pr.POOR
    assert g[("15", "NA")].region in ("na_e", "na_c")


SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui import main_window
from gogoham.spaceweather import SpaceWeather
M = main_window.MainWindow
M._welcome = lambda self: None
M._ask_scp = lambda self, *a, **k: None
M._start_daily_update = lambda self, wait=10.0: None
contest, flags = sys.argv[4], json.loads(sys.argv[5])
p = Path(sys.argv[2]) / (contest + ".ggh")
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest=contest, mycall="DO2GGH",
                                my_grid="JN59ME")); db.close()
cfg = cfgmod.load()
cfg.update(rig_enabled=False, wsjtx_enabled=False, last_log=str(p), **flags)
cfgmod.save(cfg)
def wait(n=3):
    for _ in range(n):
        app.processEvents()
w = M(); wait()
v, t = w.prop_view, w.prop_view.tbl
out = {"start": not w.prop_dock.isHidden(), "act": w.act_prop.isChecked()}
view = [a.menu() for a in w.menuBar().actions() if a.text() == "&Fenster"][0]
out["menu"] = "Bandöffnung (Vorschau)" in [x.text() for x in view.actions()]
w.show(); wait()
w._sw = SpaceWeather(sfi=140, k=2)
if w.prop_dock.isHidden():
    w.act_prop.trigger(); wait()
w._prop_tick(force=True)
out["open"] = [not w.prop_dock.isHidden(), w.act_prop.isChecked()]
out["status"] = v.status.text()
out["size"] = [t.rowCount(), t.columnCount()]
out["head"] = [t.horizontalHeaderItem(i).text() for i in range(t.columnCount())]
out["rows"] = [t.verticalHeaderItem(i).text() for i in range(t.rowCount())]
out["tip"] = t.item(0, 0).toolTip() if t.rowCount() else ""
if t.rowCount():
    import time
    from gogoham.dxcluster import Spot
    w._sw = SpaceWeather(sfi=140, k=2)
    w.spots.add(Spot("K1AR", 14_025_000, "DL1ABC", received=time.time()))
    w.cluster = object()
    w._prop_tick(force=True)
    w.cluster = None
    r20 = [t.verticalHeaderItem(i).text() for i in range(t.rowCount())].index("20 m")
    out["heard"] = [t.item(r20, 1).text(), t.item(r20, 1).toolTip().splitlines()[-1],
                    t.item(r20, 0).text()]
    w.spots.clear()
v.cb_view.setCurrentIndex(v.cb_view.findData("hours")); wait()
out["hours"] = [t.columnCount(), t.horizontalHeaderItem(0).text() if t.columnCount() else "",
                w.cfg.get("prop_view"), v.cb_cont.isHidden()]
w._sw = None; w._prop_tick(force=True)
out["offline"] = v.status.text()
w.prop_dock.close(); wait()
out["closed"] = w.act_prop.isChecked()
w.close()
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def _run(tmp_path, contest, flags=None):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    for d in (data / "gogoham", cfg / "gogoham", logs):
        d.mkdir(parents=True, exist_ok=True)
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(logs), str(HERE / "cty_sample.dat"), contest,
                        json.dumps(flags or {})],
                       capture_output=True, text=True, env=env, timeout=90)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    return json.loads(lines[-1][7:])


def test_window_both_views(tmp_path):
    o = _run(tmp_path, "cqww-ssb")
    assert o["start"] is False and o["act"] is False and o["menu"] is True
    assert o["open"] == [True, True]
    assert o["status"].startswith("Schätzung – keine Garantie") and "SFI 140" in o["status"]
    assert o["size"] == [6, 6]
    assert o["head"] == ["EU", "NA", "SA", "AF", "AS", "OC"]
    assert o["rows"][0] == "160 m" and o["rows"][-1] == "10 m"
    assert "geschätzt" in o["tip"] and "MHz" in o["tip"] and "Am besten:" in o["tip"]
    assert o["heard"][0].endswith("✓") and "Tatsächlich gehört: 1" in o["heard"][1]
    assert not o["heard"][2].endswith("✓")
    assert o["hours"] == [13, "jetzt", "hours", False]
    assert "ohne aktuelles Funkwetter" in o["offline"]
    assert o["closed"] is False


def test_ukw_contest_says_no_forecast(tmp_path):
    o = _run(tmp_path, "iaru-vhf", {"open_propagation": True})
    assert o["start"] is True and o["act"] is True
    assert o["size"] == [0, 0] and "UKW" in o["status"]
