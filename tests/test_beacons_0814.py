"""0.8.14: Bakenanzeige über das Reverse Beacon Network – Auswahl der Empfänger in der Nähe,
Farben nach Alter und Stärke, Fenster mit echtem Qt, Verhalten ohne Internet."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham import beacons as bc
from gogoham.dxcluster import parse_line

HERE = Path(__file__).parent
HOME = (49.19, 11.04)                        # JN59me
POS = {"DL9GTB": (51.0, 10.0), "OE6ADD": (47.3, 13.3), "MM0ZBH": (56.5, -4.2),
       "K1HTV": (38.0, -78.0), "EA8/DF4UE": (28.3, -15.6)}


def spot(skimmer, khz, call, db, mode="NCDXF B"):
    return parse_line(f"DX de {skimmer}-#: {khz:.2f}  {call}  CW {db} dB 22 WPM {mode} 2018Z")


def board():
    return bc.BeaconBoard(HOME, POS.get)


def test_beacon_spots_are_recognised():
    assert bc.contest_bands(["160", "80", "40", "20", "15", "10"]) == ["20", "15", "10"]
    assert bc.contest_bands(["160"]) == [] and bc.contest_bands(["2m", "70cm"]) == []
    assert bc.beacon_band("4U1UN", 14100000) == "20"
    assert bc.beacon_band("4U1UN", 18110000) is None          # 17 m (WARC) nicht gezeigt
    assert bc.beacon_band("DL1ABC", 14100000) is None
    assert bc.is_beacon_spot(spot("K1HTV", 21150.0, "4U1UN", 9))
    assert not bc.is_beacon_spot(spot("K1HTV", 10110.0, "S51DX", 30, "CQ"))
    assert bc.snr_db("CW     9 dB  19 WPM  NCDXF B") == 9 and bc.snr_db("") is None
    assert len(bc.BEACONS) == 18 and bc.BEACONS[0].call == "4U1UN"
    assert bc.bearing(HOME, bc.BY_CALL["4U1UN"]) in range(285, 300)   # New York: Nordwest
    assert bc.bearing(None, bc.BY_CALL["4U1UN"]) is None


def test_only_skimmers_nearby_count():
    b = board()
    assert b.add(spot("DL9GTB", 14100.0, "4U1UN", 23), now=1000)
    assert not b.add(spot("MM0ZBH", 14100.0, "4U1UN", 8), now=1000)   # Schottland: > 1000 km
    assert b.add(spot("OE6ADD", 14100.0, "4U1UN", 8), now=1000)
    assert not b.add(spot("K1HTV", 14100.0, "4U1UN", 30), now=1000)  # USA: zu weit weg
    assert not b.add(spot("EA8/DF4UE", 14100.0, "4U1UN", 30), now=1000)  # Kanaren: zu weit
    assert not b.add(spot("XX9XX", 14100.0, "4U1UN", 30), now=1000)  # Lage unbekannt
    assert b.received == 6
    c = b.cell("4U1UN", "20", now=1060)
    assert c.level == bc.GOOD and c.best_db == 23
    assert sorted(h.skimmer for h in c.heard) == ["DL9GTB", "OE6ADD"]


def test_levels_by_age_and_strength():
    b = board()
    b.add(spot("OE6ADD", 21150.0, "CS3B", 5), now=0)              # schwach
    assert b.cell("CS3B", "15", now=60).level == bc.FAIR
    b.add(spot("DL9GTB", 21150.0, "CS3B", 18), now=100)
    assert b.cell("CS3B", "15", now=200).level == bc.GOOD
    # 20 Minuten später: nicht mehr frisch -> gelb
    assert b.cell("CS3B", "15", now=100 + 20 * 60).level == bc.FAIR
    # nach 30 Minuten vergessen -> grau
    assert b.cell("CS3B", "15", now=100 + 31 * 60).level == bc.NONE
    b.expire(now=100 + 31 * 60)
    assert b.cell("CS3B", "15", now=100 + 31 * 60).heard == []
    assert b.cell("VK6RBP", "10", now=0).level == bc.NONE


SCRIPT = r'''
import json, queue, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod
cfg = cfgmod.load()
cfg.update(rig_enabled=False, wsjtx_enabled=False)
cfgmod.save(cfg)
from gogoham.db import DEFAULT_META, LogDB
from gogoham.dxcluster import parse_line
from gogoham.gui import main_window
main_window.MainWindow._welcome = lambda self: None
main_window.MainWindow._ask_scp = lambda self, *a, **k: None
main_window.MainWindow._start_daily_update = lambda self, wait=10.0: None

class FakeRBN:
    def __init__(self, ok=True):
        self.spots = queue.Queue()
        self.connected, self.ever_connected = ok, ok
        self.error = "" if ok else "Knoten nicht gefunden – keine Internetverbindung?"
        self.host, self.started, self.stopped = "rbn", False, False
    def start(self): self.started = True
    def stop(self): self.stopped = True

made = []
def make(self, call, ok=[True]):
    r = FakeRBN(ok[0]); r.call = call; made.append(r); return r
main_window.MainWindow._make_rbn = make
w = main_window.MainWindow()
def wait(n=3):
    for _ in range(n):
        app.processEvents()
def open_log(contest, name):
    p = Path(sys.argv[2]) / name
    db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest=contest, mycall="DO2GGH",
                                    my_grid="JN59ME")); db.close()
    w.open_log(str(p)); wait()
out = {}
# ohne Log: geht nicht
w.toggle_beacons(True)
out["no_log"] = [w.rbn is None, w.act_beacons.isChecked(), w.sb.currentMessage()]
# CQ 160: keine Bakenbänder
open_log("cq160-cw", "a.ggh")
w.toggle_beacons(True)
out["cq160"] = [w.rbn is None, w.act_beacons.isChecked(), w.sb.currentMessage()]
# CQ WW: an, Spots kommen
open_log("cqww-ssb", "b.ggh")
w.show(); wait()
w.toggle_beacons(True); wait()
r = w.rbn
out["on"] = [r is not None and r.started, r.call, w.act_beacons.isChecked(),
             w.bc_dock.isVisible(), (not w.bc_dock.isHidden()), w._beacon_bands()]
for line in ("DX de DL9GTB-#: 14100.00  4U1UN  CW 23 dB 22 WPM NCDXF B 2018Z",
             "DX de OE6ADD-#: 21150.00  CS3B  CW 4 dB 22 WPM NCDXF B 2018Z",
             "DX de K1HTV-4-#: 28200.00  OA4B  CW 30 dB 22 WPM NCDXF B 2018Z"):
    r.spots.put(parse_line(line))
w._bc_next = 0; w._beacon_tick(); wait()
t = w.beacon_view.tbl
head = [t.horizontalHeaderItem(c).text() for c in range(t.columnCount())]
def cell(call, band):
    row = [b.call for b in __import__("gogoham.beacons", fromlist=["x"]).BEACONS].index(call)
    it = t.item(row, head.index(band))
    return [it.text(), it.background().color().name(), it.toolTip()]
out["head"] = head
out["4u1un"] = cell("4U1UN", "20 m")
out["cs3b"] = cell("CS3B", "15 m")
out["oa4b"] = cell("OA4B", "10 m")           # nur in den USA gehört -> grau
out["dir"] = t.item(0, 2).text()
out["status"] = w.beacon_view.status.text()
out["assisted"] = ["NON-ASSISTED" in out["status"], "NON-ASSISTED" in w.sb.currentMessage(),
                   "e08a00" in w.beacon_view.status.styleSheet()]
w.meta["cat_assisted"] = "ASSISTED"; w._bc_next = 0; w._beacon_tick()
out["assisted"].append("NON-ASSISTED" in w.beacon_view.status.text())
# Fenster mit dem X schließen: Verbindung zu, Einstellung aus
w.bc_dock.close(); wait()
out["closed"] = [r.stopped, w.rbn is None, w.act_beacons.isChecked(), (not w.bc_dock.isHidden())]
# Ohne Internet: Einschalten nicht möglich, klare Meldung
make.__defaults__[0][0] = False
w.toggle_beacons(True); w._beacon_tick(); wait()
out["offline"] = [w.rbn is None, w.act_beacons.isChecked(), (not w.bc_dock.isHidden()),
                  w.sb.currentMessage(), "c62828" in w.sb.hint.styleSheet()]
# Einstellung bleibt beim nächsten Log erhalten (wieder mit Internet)
make.__defaults__[0][0] = True
w.toggle_beacons(True); wait()
open_log("wpx-ssb", "c.ggh"); wait()
out["reopen"] = [w.rbn is not None, w.act_beacons.isChecked()]
open_log("cq160-ssb", "d.ggh"); wait()
out["unsuitable"] = [w.rbn is None, w.bc_dock.isVisible(), (not w.bc_dock.isHidden())]
w.close()
print("RESULT " + json.dumps(out))
'''


def test_beacon_window(tmp_path):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    (cfg / "gogoham").mkdir(parents=True)
    (data / "gogoham").mkdir(parents=True)
    logs.mkdir()
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(logs), str(HERE / "cty_sample.dat")],
                       capture_output=True, text=True, env=env, timeout=90)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["no_log"][:2] == [True, False] and "Log" in o["no_log"][2]
    assert o["cq160"][:2] == [True, False] and "20, 15 oder 10 m" in o["cq160"][2]
    assert o["on"] == [True, "DO2GGH", True, True, True, ["20", "15", "10"]]
    assert o["head"] == ["Bake", "Standort", "Richtung", "20 m", "15 m", "10 m"]
    text, color, tip = o["4u1un"]
    assert text == "23 dB" and color == "#1b8a3a" and "DL9GTB" in tip and "km" in tip
    text, color, _tip = o["cs3b"]
    assert text == "4 dB" and color == "#f2c200"
    text, _color, tip = o["oa4b"]
    assert text == "–" and "keinem Empfänger" in tip
    assert o["dir"].endswith("°")
    assert "RBN verbunden" in o["status"] and "1000 km" in o["status"]
    assert o["assisted"] == [True, True, True, False]    # warnt wie beim DX-Cluster
    assert o["closed"] == [True, True, False, False]
    gone, checked, enabled, msg, red = o["offline"]
    assert gone and not checked and not enabled and red
    assert "keine Internetverbindung" in msg
    assert o["reopen"] == [True, True]
    assert o["unsuitable"] == [True, False, False]     # 0.8.14.1: Fenster zu = aus
