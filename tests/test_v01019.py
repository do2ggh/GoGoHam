"""0.10.19: Übung unübersehbar markiert, Karte in der Übung, Desktop-Verknüpfung, Handbuchsuche."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham import extapps

HERE = Path(__file__).parent
CALLS = ["DL1ABC", "DL2XYZ", "OE3ABC", "PA3AAA", "G4BBB", "UA3CCC", "JA1DDD", "K1EEE", "W3FFF",
         "VE3GGG", "PY2HHH", "VK2III", "HA5JJJ", "OK1KKK", "SP9LLL", "ON4MMM", "BY1NNN"]


# ------------------------------------------------------------------ Desktop-Verknüpfung
def test_desktop_link(tmp_path):
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "message_aggregator.desktop").write_text("[Desktop Entry]\nExec=message_aggregator\n")
    (apps / "hidden.desktop").write_text("[Desktop Entry]\nExec=ws\nNoDisplay=true\n")
    (apps / "wsjtx.desktop").write_text("[Desktop Entry]\nName=WS\nExec=ws --x %f\nIcon=ws\n")
    home = tmp_path / "home"
    src = extapps.desktop_file("wsjtx_improved", "/usr/bin/ws", str(home), (str(apps),))
    assert src == apps / "wsjtx.desktop"
    link = extapps.add_desktop_link("wsjtx_improved", "/usr/bin/ws", str(home), (str(apps),))
    assert link == home / "Desktop" / "gogoham-wsjtx_improved.desktop"
    assert "Exec=ws --x" in link.read_text() and link.stat().st_mode & 0o111
    extapps.remove_desktop_link("wsjtx_improved", str(home))
    assert not link.exists()
    extapps.remove_desktop_link("wsjtx_improved", str(home))       # schon weg: kein Fehler
    # Flatpak im Benutzerordner
    exp = home / ".local/share/flatpak/exports/share/applications"
    exp.mkdir(parents=True)
    (exp / "com.w1hkj.fldigi.desktop").write_text("[Desktop Entry]\nExec=flatpak run x\n")
    assert extapps.desktop_file("fldigi", "flatpak:com.w1hkj.fldigi", str(home)) \
        in (exp / "com.w1hkj.fldigi.desktop",
            Path("/var/lib/flatpak/exports/share/applications/com.w1hkj.fldigi.desktop"))
    assert extapps.add_desktop_link("fldigi", None, str(home)) is None
    assert extapps.desktop_file("fldigi", "/usr/bin/fldigi", str(home), (str(apps),)) is None


# ------------------------------------------------------------------ Handbuchsuche
SEARCH = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham.gui.help import HelpDialog, find_hits, search_pattern
d = HelpDialog()
doc = d.view.document()
out = {q: [(h.level, h.chapter) for h in find_hits(doc, q)[:2]]
       for q in ("Auto-CQ", "autocq", "AUTO CQ", "Übungsmodus")}
out["empty"] = find_hits(doc, " - ")
out["none"] = len(find_hits(doc, "xyzzyquux"))
d.search.setText("autocq"); d.find_next()
out["first"] = [d.view.textCursor().selectedText(), d.hits.text(), d.results.isHidden()]
d.find_next()
out["second"] = d.results.currentRow()
d.search.setText("xyzzyquux"); d.find_next()
out["nf"] = [d.hits.text(), d.results.isHidden()]
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def test_handbook_search(tmp_path):
    env = {"QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin",
           "XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SEARCH), str(HERE.parent)],
                       capture_output=True, text=True, env=env, timeout=60)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    for q in ("Auto-CQ", "autocq", "AUTO CQ"):
        assert o[q][0] == [2, "10. Auto-CQ"], (q, o[q])          # das Kapitel zuerst
    assert o["Übungsmodus"][0][0] == 2 and "Übungsmodus" in o["Übungsmodus"][0][1]
    assert o["empty"] == [] and o["none"] == 0
    assert o["first"][0] == "Auto-CQ" and "Treffer" in o["first"][1] and not o["first"][2]
    assert o["second"] == 1
    assert o["nf"] == ["nicht gefunden", True]


# ------------------------------------------------------------------ Übung im Hauptfenster
SCRIPT = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod
from gogoham import dxcluster as dxc
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui import main_window
from gogoham.gui import practice_mode as pmode
M = main_window.MainWindow
M._welcome = lambda self: None
M._ask_scp = lambda self, *a, **k: None
M._ask_flags = lambda self, *a, **k: None
M._start_daily_update = lambda self, wait=10.0: None
M._make_practice_stream = lambda self, mixer, dev: pmode.SilentStream(mixer)
M._show_practice_dialog = lambda self, dlg: True
M._show_practice_result = lambda self, dlg: None
M.start_beacons = lambda self: None            # kein Netz im Test
M.start_cluster = lambda self: None
p = Path(sys.argv[2]) / "cqww-cw.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="cqww-cw", mycall="DL9ZZZ",
                                my_grid="JN59ME")); db.close()
cfg = cfgmod.load()
cfg.update(rig_enabled=False, wsjtx_enabled=False, last_log=str(p))
cfg["practice"] = {"contest": "cqww-cw", "band": "20", "activity": 5, "minutes": 10}
cfgmod.save(cfg)
def wait(sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.01)
w = M(); w.show(); wait(0.3)
out = {"before": [w.windowTitle(), w.ed_call.styleSheet()]}
w.start_practice(); wait(0.2)
f = w.practice_frame
out["on"] = [w.windowTitle(), f.isVisible(), f.geometry() == w.rect(), w.ed_call.styleSheet(),
             w.practice_bar.styleSheet()]
w.resize(900, 600); wait(0.2)
out["follows"] = f.geometry() == w.rect()
# 0.10.19.1: Menüleiste und Statuszeile liegen innerhalb des Rands, nicht darunter
from gogoham.gui.practice_frame import WIDTH
mb, sb = w.menuBar().geometry(), w.statusBar().geometry()
out["inside"] = [mb.top() >= WIDTH, mb.left() >= WIDTH, sb.bottom() <= w.height() - 1 - WIDTH,
                 sb.right() <= w.width() - 1 - WIDTH]
# Karte: Run-Übung hat keine Spots; S&P-Übung zeigt die nachgebildeten
out["run_spots"] = w._map_spot_marks("20")
w.practice.listen = True
w.spots.add(dxc.Spot(call="JA1DDD", freq=14025000.0, spotter="DL1ABC", comment="", utc="1200"))
marks, note = w._map_spot_marks("20")
out["sp_spots"] = [[m["label"] for m in marks], note]
w.practice.listen = False
# Baken auch in der Übung (nur hören)
w.bc_dock.show(); wait(0.1)
out["beacons"] = w._beacons_wanted()
w.bc_dock.hide()
w.end_practice(); wait(0.2)
out["off"] = [w.windowTitle(), f.isVisible(), w.ed_call.styleSheet()]
m = w.contentsMargins(); out["margins_off"] = [m.left(), m.top(), m.right(), m.bottom()]
w.close()
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def test_practice_marked_and_map(tmp_path):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    for d in (data / "gogoham", cfg / "gogoham", logs):
        d.mkdir(parents=True, exist_ok=True)
    (data / "gogoham" / "MASTER.SCP").write_text("\n".join(CALLS) + "\n")
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(logs), str(HERE / "cty_sample.dat"), str(data)],
                       capture_output=True, text=True, env=env, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert "ÜBUNG" not in o["before"][0] and o["before"][1] == ""
    title, visible, geo, call_style, bar = o["on"]
    assert title.startswith("⚠ ÜBUNGSMODUS – es wird nichts gesendet – ")
    assert visible and geo and "#fff59d" in call_style and "#ffd600" in bar
    assert o["follows"]
    assert o["inside"] == [True, True, True, True], o["inside"]
    assert o["margins_off"] == [0, 0, 0, 0]
    assert o["run_spots"] == [[], "Spots: in der Run-Übung gibt es keine"]
    assert o["sp_spots"][0] == ["JA1DDD"] and "1 auf der Karte" in o["sp_spots"][1]
    assert o["beacons"] is True
    assert "ÜBUNG" not in o["off"][0] and not o["off"][1] and o["off"][2] == ""
