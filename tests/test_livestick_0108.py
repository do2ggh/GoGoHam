"""0.10.8: GoGoHam vom Live-Stick – Bereich „USB-Stick“, Sicherung in den Austausch-Ordner,
Platz- und Uhrzeit-Warnung. Auf einem normal installierten PC ändert sich nichts."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham import livestick as ls


def _marker(tmp_path, **extra):
    data, exch = tmp_path / "daten", tmp_path / "austausch"
    data.mkdir()
    exch.mkdir()
    m = tmp_path / "livestick.json"
    m.write_text(json.dumps(dict({"data": str(data), "exchange": str(exch)}, **extra)))
    return m, data, exch


def test_not_live_without_marker(tmp_path):
    assert ls.info(tmp_path / "fehlt.json") is None
    assert not ls.is_live(tmp_path / "fehlt.json")
    bad = tmp_path / "kaputt.json"
    bad.write_text("{kein json")
    assert not ls.is_live(bad)
    assert not ls.is_live()                        # Tests: nie auf dem Stick (conftest)


def test_marker_dirs_and_space(tmp_path):
    m, data, exch = _marker(tmp_path)
    assert ls.is_live(m)
    assert ls.data_dir(m) == data and ls.exchange_dir(m) == exch
    sp = ls.space(data)
    assert sp and sp[0] <= sp[1]
    assert "frei von" in ls.space_text(sp)
    assert ls.space(None) is None and ls.space_text(None) == "unbekannt"
    m2 = tmp_path / "m2.json"
    m2.write_text(json.dumps({"exchange": str(tmp_path / "weg")}))
    assert ls.exchange_dir(m2) is None             # Ordner fehlt → kein Austausch-Ordner


def test_low_space_rule():
    gb = 1024 ** 3
    assert ls.is_low(gb // 2, 100 * gb)            # unter 1 GB
    assert ls.is_low(3 * gb, 100 * gb)             # unter 5 %
    assert not ls.is_low(20 * gb, 100 * gb)
    assert ls.size_text(int(1.5 * gb)) == "1,5 GB" and ls.size_text(300 * 1024 ** 2) == "300 MB"


def test_commands(tmp_path):
    helper = tmp_path / "reset"
    helper.write_text("#!/bin/sh\n")
    m, *_ = _marker(tmp_path, reset=str(helper))
    have = lambda name: "/usr/bin/" + name
    assert ls.reset_command(m, which=have) == ["pkexec", str(helper)]
    assert ls.reset_command(m, which=lambda n: None) is None
    m2 = tmp_path / "m2.json"
    m2.write_text(json.dumps({"reset": str(tmp_path / "fehlt")}))
    assert ls.reset_command(m2, which=have) is None
    assert ls.poweroff_command(which=have) == ["systemctl", "poweroff"]
    # nur die Systemuhr (date -u), nie die eingebaute Uhr des fremden Rechners (kein hwclock)
    cmd = ls.set_time_command(1_790_000_000.7, which=have)
    assert cmd == ["pkexec", "date", "-u", "-s", "@1790000000"]
    assert ls.set_time_command(0, which=lambda n: None) is None


def test_clock_synced():
    class R:
        def __init__(self, out):
            self.stdout = out
    assert ls.clock_synced(run=lambda *a, **k: R("yes\n")) is True
    assert ls.clock_synced(run=lambda *a, **k: R("no\n")) is False
    assert ls.clock_synced(run=lambda *a, **k: R("")) is None

    def boom(*a, **k):
        raise FileNotFoundError
    assert ls.clock_synced(run=boom) is None


def test_backup_to_exchange(tmp_path):
    exch = tmp_path / "x"
    exch.mkdir()
    bk = tmp_path / "sicherung.ggh"
    bk.write_bytes(b"SQLite")
    d = ls.backup_to_exchange(exch, "/irgendwo/cqww.ggh", "<eoh>\n", bk)
    assert d == exch / ls.BACKUP_FOLDER
    assert (d / "cqww.adi").read_text() == "<eoh>\n" and (d / "cqww.ggh").read_bytes() == b"SQLite"
    ls.backup_to_exchange(exch, "/irgendwo/cqww.ggh", "neu", None)     # überschreibt, keine Reste
    assert (d / "cqww.adi").read_text() == "neu"
    assert sorted(p.name for p in d.iterdir()) == ["LIESMICH.txt", "cqww.adi", "cqww.ggh"]


# ------------------------------------------------------------ echtes Hauptfenster (offscreen)
GUI_SCRIPT = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import livestick
livestick.MARKER = Path(sys.argv[3])
livestick.persistent = lambda mounts=None: True       # Stick mit Datenteil (0.10.22)
from gogoham.contests.base import Qso
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui import dialogs
from gogoham.gui.main_window import MainWindow
MainWindow._welcome = lambda self: None
MainWindow._ask_scp = lambda self, *a, **k: None
MainWindow._stick_hint = lambda self: self.cfg.__setitem__("stick_hint_done", True)
out = {}
w = MainWindow()
p = Path(sys.argv[2]) / "cqww.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="cqww-cw", mycall="DO2GGH"))
db.add(Qso(time="2026-11-28 10:00:00", call="DL1ABC", band="20", mode="CW", freq=14_020_000,
           rst_s="599", exch_s="14", rst_r="599", exch_r="14"))
db.close()
w.open_log(str(p))
import time
end = time.monotonic() + 1.0                          # Rückfragen beim Start laufen per Timer
while time.monotonic() < end:
    app.processEvents(); time.sleep(0.02)
# Startfragen nacheinander (0.10.8): b startet erst, wenn a (modal) zu ist
from PySide6.QtCore import QEventLoop, QTimer
order = []
def pop_a():
    order.append("a+"); loop = QEventLoop(); QTimer.singleShot(300, loop.quit); loop.exec()
    order.append("a-")
class Fake: pass
fake = Fake(); fake._startup_popups = [(20, lambda: order.append("b")), (10, pop_a)]
MainWindow.run_startup_popups(fake)
end = time.monotonic() + 1.0
while time.monotonic() < end:
    app.processEvents(); time.sleep(0.02)
out["order"] = order
dlg = dialogs.SettingsDialog(w.cfg, w, actions={"stick_reset": w.stick_reset})
out["sections"] = [t for t, _k in dlg.sections]
dlg.select("stick")
page = dlg.stack.currentWidget().widget()          # 0.10.12: Seite im Scrollbereich
out["page"] = type(page).__name__
out["space"] = page.lbl_data.text()
out["open"] = page.btn_open.isEnabled()
out["reset"] = page.btn_reset.isEnabled()            # kein Hilfsprogramm → aus
page.chk_backup.setChecked(False); dlg.accept()
out["cfg_backup"] = w.cfg["stick_backup"]
w.cfg["stick_backup"] = True
w._backup_now(force=True)
exch = Path(json.loads(Path(sys.argv[3]).read_text())["exchange"]) / livestick.BACKUP_FOLDER
out["files"] = sorted(x.name for x in exch.iterdir()) if exch.is_dir() else []
out["adi_has_call"] = "DL1ABC" in (exch / "cqww.adi").read_text() if out["files"] else False
livestick.is_low = lambda free, total: True
w._stick_space_check()
out["low_msg"] = w.statusBar().currentMessage()
livestick.clock_synced = lambda: False
w.clock.asked = True                                  # keine Rückfrage (modal) im Test
w.clock._result(None)
out["clock_msg"] = w.statusBar().currentMessage()
livestick.clock_synced = lambda: True                 # Internet da → Hinweis weg (0.10.10)
w.clock._result(None)
out["clock_after"] = w.statusBar().currentMessage()
out["hint_done"] = w.cfg.get("stick_hint_done")
livestick.MARKER = Path(sys.argv[2]) / "fehlt.json"   # normaler PC: kein Bereich
dlg2 = dialogs.SettingsDialog(w.cfg, w)
out["sections_pc"] = [t for t, _k in dlg2.sections]
print("OUT" + json.dumps(out))
w.close()
'''


def test_main_window_on_stick(tmp_path):
    import shutil
    here = Path(__file__).parent
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    (data / "gogoham").mkdir(parents=True)
    (cfg / "gogoham").mkdir(parents=True)
    logs.mkdir()
    shutil.copy(here / "cty_sample.dat", data / "gogoham" / "cty.dat")
    (cfg / "gogoham" / "config.json").write_text(json.dumps({
        "rig_enabled": False, "wsjtx_enabled": False, "livescore_enabled": False,
        "rules_auto_update": False, "last_log": "", "language": "de", "daily_update": False}))
    m, *_ = _marker(tmp_path)
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin",
           "GOGOHAM_NO_DISCOVERY": "1"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(GUI_SCRIPT), str(here.parent),
                        str(logs), str(m)], capture_output=True, text=True, env=env, timeout=90)
    lines = [ln[3:] for ln in r.stdout.splitlines() if ln.startswith("OUT")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1])
    assert o["sections"][-2:] == ["Darstellung", "USB-Stick"]       # ganz unten (0.10.11)
    assert "USB-Stick" not in o["sections_pc"]
    assert o["page"] == "StickPage" and "frei von" in o["space"]
    assert o["open"] is True and o["reset"] is False
    assert o["cfg_backup"] is False
    assert o["files"] == ["LIESMICH.txt", "cqww.adi", "cqww.ggh"] and o["adi_has_call"]
    assert "fast voll" in o["low_msg"]
    assert "Uhrzeit vom Rechner übernommen" in o["clock_msg"]          # ruhig, ab 0.10.10
    assert "abgeglichen ✓" in o["clock_after"]
    assert o["hint_done"] is True
    assert o["order"] == ["a+", "a-", "b"]                     # nie zwei Startfragen übereinander
