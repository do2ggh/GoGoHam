"""0.8.9: Run/S&P mit „Enter sendet“ (ESM) – im echten Qt-Fenster (offscreen), Funkgerät als
Platzhalter, der nur mitschreibt, was gesendet würde."""

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).parent
SCRIPT = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui.main_window import MainWindow
MainWindow._welcome = lambda self: None
MainWindow._ask_scp = lambda self, *a, **k: None
w = MainWindow()
p = Path(sys.argv[2]) / "wpx.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="wpx-cw", mycall="DO2GGH")); db.close()
w.open_log(str(p))
sent = []
class Rig:
    def submit(self, *a): sent.append(list(a))
    def snapshot(self): return None
    def stop(self): pass
w.rig = Rig(); w._rig_connected = lambda: True; w.rig_caps = None
w.show(); app.processEvents()
out = []
def press(call=None, exch=None, focus="call"):
    if call is not None:
        w.ed_call.setText(call); w.update_check()
    if exch is not None:
        w.ed_exch.setText(exch); w.exch_auto = False
    (w.ed_call if focus == "call" else w.ed_exch).setFocus()
    sent.clear(); n = len(w.qsos); w.enter_pressed(); app.processEvents()
    out.append([list(sent), len(w.qsos) - n, w.ed_exch.hasFocus()])
def mode(m):
    w._updating = True; w.cb_mode.setCurrentText(m); w._updating = False
mode("CW")
press(""); press("DL1ABC"); press(exch="5", focus="exch")                 # Run CW
w.toggle_run_sp()
press(""); press("OE1XYZ"); press(exch="12", focus="exch")              # S&P CW
press("K1ABC"); press(exch="", focus="exch"); w.clear_entry()           # Austausch fehlt
mode("USB"); w.toggle_run_sp()
press(""); press("JA1AAA"); press(exch="7", focus="exch")               # Run SSB
w.toggle_run_sp()
press("VK2AB"); press(exch="9", focus="exch")                           # S&P SSB
w.set_esm(False)
press("DL2XX"); press(exch="4", focus="exch")                           # ESM aus
w.ed_call.setFocus(); before = w.cfg["esm_mode"]
QTest.keyClick(w.ed_call, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
out.append([before, w.cfg["esm_mode"], w.btn_runsp.text()])
print(json.dumps(out))
w.close()
'''


def test_esm_flow(tmp_path):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    (data / "gogoham").mkdir(parents=True)
    (cfg / "gogoham").mkdir(parents=True)
    logs.mkdir()
    shutil.copy(HERE / "cty_sample.dat", data / "gogoham" / "cty.dat")
    (cfg / "gogoham" / "config.json").write_text(json.dumps({
        "rig_enabled": False, "wsjtx_enabled": False, "livescore_enabled": False,
        "rules_auto_update": False, "last_log": "", "language": "de", "esm_enabled": True}))
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(logs)], capture_output=True, text=True, env=env, timeout=60)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("[")]
    assert lines, r.stderr[-2000:]
    o = json.loads(lines[-1])
    morse = lambda t: [["send_morse", t]]                                     # noqa: E731
    # Run CW: CQ → Rufzeichen+Austausch (Cursor in den Austausch) → TU + loggen
    assert o[0] == [morse("CQ TEST DO2GGH DO2GGH TEST"), 0, False]
    assert o[1] == [morse("DL1ABC 5NN 001"), 0, True]
    assert o[2] == [morse("TU DO2GGH"), 1, False]
    # S&P CW: leer → nichts; Mein Call → Austausch + TU in einem Rutsch + loggen
    assert o[3] == [[], 0, False]
    assert o[4] == [morse("DO2GGH"), 0, True]
    assert o[5] == [morse("OE1XYZ 5NN 002 TU DO2GGH"), 1, False]
    # Austausch fehlt: beim zweiten Enter wird nichts gesendet, nichts geloggt
    assert o[6][1] == 0 and o[7] == [[], 0, True]
    # SSB: nur feste Sprachspeicher (1 = CQ, 3 = TU, 4 = Mein Call)
    assert o[8] == [[["send_voice_mem", 1]], 0, False]
    assert o[9] == [[], 0, True]
    assert o[10] == [[["send_voice_mem", 3]], 1, False]
    assert o[11] == [[["send_voice_mem", 4]], 0, True]
    assert o[12] == [[["send_voice_mem", 3]], 1, False]
    # ESM aus: Enter sendet nie etwas
    assert o[13][0] == [] and o[14] == [[], 1, False]
    # Strg+Tab schaltet Run/S&P um
    assert o[15][0] != o[15][1] and o[15][2] in ("Run", "S&&P")
    saved = json.loads((cfg / "gogoham" / "config.json").read_text())
    assert saved["esm_enabled"] is False and saved["esm_mode"] == o[15][1]


def test_rejected_voice_memory_gives_notice():
    """Lehnt das Gerät einen Sprachspeicher ab (leer), sagt GoGoHam das verständlich."""
    from gogoham.rig import command_notice, command_notice_long
    t = command_notice("send_voice_mem", (3,), "rigctld meldet Fehler: RPRT -9")
    assert t == "Sprachspeicher 3 ist leer – am Funkgerät aufnehmen (IC-7300: VOICE)"
    t = command_notice_long("send_voice_mem", (3,))      # ausführlich: Statuszeile, Tooltip
    assert "Sprachspeicher 3 abgelehnt" in t and "aufgenommen" in t
    assert command_notice_long("set_freq", (1,)) == ""
    assert "CW" in command_notice("send_morse", ("TEST",), "x")
    assert command_notice("set_freq", (1,), "RPRT -1") == "RPRT -1"


def test_rig_notice_disappears(tmp_path):
    """Hinweis „Sprachspeicher abgelehnt“ verschwindet nach 10 s bzw. bei F-Taste/Enter."""
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    (data / "gogoham").mkdir(parents=True)
    (cfg / "gogoham").mkdir(parents=True)
    logs.mkdir()
    shutil.copy(HERE / "cty_sample.dat", data / "gogoham" / "cty.dat")
    (cfg / "gogoham" / "config.json").write_text(json.dumps({
        "rig_enabled": False, "wsjtx_enabled": False, "livescore_enabled": False,
        "rules_auto_update": False, "last_log": "", "language": "de"}))
    script = r'''
import faulthandler, json, sys, time
faulthandler.dump_traceback_later(50, exit=True)
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui.main_window import MainWindow
MainWindow._welcome = lambda self: None
MainWindow._ask_scp = lambda self, *a, **k: None
w = MainWindow()
p = Path(sys.argv[2]) / "t.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="wpx-ssb", mycall="DO2GGH")); db.close()
w.open_log(str(p))
N = "Hinweis"
def wait(s):
    e = time.time() + s
    while time.time() < e:
        app.processEvents(); time.sleep(0.05)
r = []
# ab 0.8.13 in der Hinweiszeile unten (w.sb), nicht mehr unter dem Rufzeichen
w._show_rig_notice(N); wait(0.2); r.append(w.sb.currentMessage() == N and w.lbl_status.text() == "")
w.run_macro(1, manual=True); wait(0.2); r.append(w.sb.currentMessage() != N)
w._show_rig_notice(N); wait(12.0); r.append(w.sb.currentMessage() != N)   # (tägliches Update darf melden)
w._show_rig_notice(N); w.enter_pressed(); wait(0.2); r.append(w.sb.currentMessage() != N)
print(json.dumps(r)); w.close()
'''
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    out = subprocess.run([sys.executable, "-c", script, str(HERE.parent), str(logs)],
                         capture_output=True, text=True, env=env, timeout=60)
    lines = [ln for ln in out.stdout.splitlines() if ln.startswith("[")]
    assert lines and json.loads(lines[-1]) == [True, True, True, True], (lines, out.stderr[-1500:])
