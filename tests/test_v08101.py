"""0.8.10.1: Anzeige des gesendeten Texts (CW Buchstabe für Buchstabe, SSB-Sprachspeicher),
Design „Franken“ hell/dunkel."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gogoham.cwdisplay import LINGER, START_DELAY, CwTicker, char_units, timeline, unit

HERE = Path(__file__).parent
ROOT = HERE.parent


def test_paris_timing():
    # PARIS = 50 Einheiten inkl. Wortpause → bei 20 WpM genau 3 s
    t = timeline("PARIS", 20)
    assert abs(t[-1][1] + 7 * unit(20) - 3.0) < 1e-9
    assert char_units("E") == 1 and char_units("T") == 3 and char_units("0") == 19
    assert char_units("#") == 0                       # unbekanntes Zeichen: keine Zeit
    e = timeline("E E", 12)                           # Wortpause = 7 Einheiten
    assert abs(e[2][0] - e[0][1] - 7 * unit(12)) < 1e-9


def test_ticker_runs_letter_by_letter():
    t = CwTicker()
    t.add("cq  test", 30, now=0.0)
    assert t.state(0.0) == ("CQ TEST", 0, -1)          # noch nicht angefangen
    assert t.state(START_DELAY + 0.01) == ("CQ TEST", 0, 0)   # C läuft
    text, done, cur = t.state(START_DELAY + 1.0)
    assert 0 < done == cur
    end = t.end()
    assert t.state(end + 0.1) == ("CQ TEST", 7, -1)    # fertig, steht noch kurz da
    assert t.state(end + LINGER + 0.1) is None


def test_ticker_queues_and_stops():
    t = CwTicker()
    t.add("TU", 30, 0.0)
    t.add("DO2GGH", 30, 0.1)                           # Funkgerät reiht aneinander
    assert t.state(0.15)[0] == "TU DO2GGH"
    assert t.parts[1].start > t.parts[0].end
    _, done, cur = t.state(t.parts[1].start + 0.01)
    assert cur == 3 and done == 3                      # „TU “ fertig, D läuft
    t.stop(1.0)
    assert t.state(1.0) is None
    t.add("K", 30, 2.0)                                # nach Esc frisch
    assert t.state(2.0)[0] == "K"


def test_unknown_speed_only_shows():
    t = CwTicker()
    t.add("CQ", 0, 0.0)
    assert t.state(0.5) == ("CQ", -1, -1)


SCRIPT = r'''
import json, sys, threading, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham.db import DEFAULT_META, LogDB
from gogoham.rig import RigState
from gogoham.gui.main_window import MainWindow
MainWindow._welcome = lambda self: None
MainWindow._ask_scp = lambda self, *a, **k: None
w = MainWindow()
p = Path(sys.argv[2]) / "wpx.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="wpx-cw", mycall="DO2GGH")); db.close()
w.open_log(str(p))
class Rig:
    lock = threading.Lock()
    state = RigState(connected=True, wpm=40, mode="CW")
    def submit(self, *a): pass
    def snapshot(self): return RigState(**self.state.__dict__)
    def stop(self): pass
w.rig = Rig(); w._rig_connected = lambda: True; w.rig_caps = None
out = {}
w.cb_mode.setCurrentText("CW")
w.run_macro(4, manual=True)                      # F4 = Mein Call
time.sleep(0.4); w._update_sending()
out["cw"] = w.lbl_sending.text()
w.escape_pressed()
out["esc"] = w.lbl_sending.text()
w.cb_mode.setCurrentText("USB")
w.run_macro(1, manual=True)                      # F1 = Sprachspeicher 1 „CQ“
out["voice"] = w.lbl_sending.text()
from gogoham.gui import theme
w.set_theme("franken"); out["fr"] = app.styleSheet(); out["fr_dark"] = theme.is_dark()
w.set_theme("franken-dark"); out["frd_dark"] = theme.is_dark()
w.set_theme("light"); out["light"] = app.styleSheet()
print(json.dumps(out))
'''


def test_gui_sending_and_franken(tmp_path):
    pytest.importorskip("PySide6")
    data = tmp_path / "data" / "gogoham"
    data.mkdir(parents=True)
    shutil.copy(HERE / "cty_sample.dat", data / "cty.dat")
    env = {"QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path),
           "XDG_CONFIG_HOME": str(tmp_path / "cfg"), "XDG_DATA_HOME": str(tmp_path / "data"),
           "PATH": "/usr/bin:/bin"}
    (tmp_path / "cfg" / "gogoham").mkdir(parents=True)
    (tmp_path / "cfg" / "gogoham" / "config.json").write_text(json.dumps(
        {"rig_enabled": False, "wsjtx_enabled": False, "language": "de"}))
    r = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT), str(tmp_path)],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert "background:#1565c0" in out["cw"]           # aktueller Buchstabe markiert
    assert ">D<" in out["cw"] and "O2GGH" in out["cw"]
    assert out["esc"] == ""
    assert "Sprachspeicher 1 (CQ)" in out["voice"]
    assert "#C8102E" in out["fr"] and not out["fr_dark"] and out["frd_dark"]
    assert out["light"] == ""
