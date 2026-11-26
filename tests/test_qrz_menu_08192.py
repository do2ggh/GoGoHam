"""0.8.19.2: Rechtsklick im Log und in der Bandmap -> „Rufzeichen bei QRZ.com ansehen“."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham.weblookup import base_call, qrz_url

HERE = Path(__file__).parent


def test_base_call():
    assert base_call("dl1abc") == "DL1ABC"
    assert base_call("W1AW/P") == "W1AW"
    assert base_call("DL1ABC/MM") == "DL1ABC"
    assert base_call("EA8/DL1ABC") == "DL1ABC"
    assert base_call("DL/W1AW") == "W1AW"
    assert base_call("DL1ABC/VE3") == "DL1ABC"
    assert base_call("OH2BH/1") == "OH2BH"
    assert base_call("") == ""


def test_qrz_url():
    assert qrz_url("W1AW/P") == "https://www.qrz.com/db/W1AW"
    assert qrz_url(" dl1abc ") == "https://www.qrz.com/db/DL1ABC"
    assert qrz_url("") is None
    assert qrz_url("TEST") is None            # kein Rufzeichen (keine Ziffer)


SCRIPT = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QMenu
from PySide6.QtTest import QTest
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod
cfg = cfgmod.load(); cfg.update(rig_enabled=False, wsjtx_enabled=False); cfgmod.save(cfg)
from gogoham.db import DEFAULT_META, LogDB
from gogoham.dxcluster import Spot
from gogoham.contests import Qso
from gogoham.gui import main_window
main_window.MainWindow._welcome = lambda self: None
main_window.MainWindow._ask_scp = lambda self, *a, **k: None
main_window.MainWindow._start_daily_update = lambda self, wait=10.0: None

opened, menus = [], []
main_window.QDesktopServices.openUrl = staticmethod(lambda u: opened.append(u.toString()) or True)
class FakeMenu(QMenu):                    # zeigt nichts an, merkt sich die Einträge
    def exec(self, *a):
        menus.append([x.text() for x in self.actions() if not x.isSeparator()])
        for x in self.actions():
            if "QRZ" in x.text():
                x.trigger()
main_window.QMenu = FakeMenu

p = Path(sys.argv[2]) / "x.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="cqww-ssb", mycall="DO2GGH")); db.close()
w = main_window.MainWindow(); w.open_log(str(p)); w.show()
for _ in range(3): app.processEvents()
q = Qso(time="2026-11-07 12:00:00", call="EA8/DL1ABC", band="20", mode="PH", freq=14250000,
        rst_s="59", exch_s="14", rst_r="59", exch_r="14")
w.db.add(q) if hasattr(w.db, "add") else w.db.insert(q)
w.reload()
w.tbl.selectRow(0)
w._log_menu(QPoint(5, 5))

# Bandmap: Rechtsklick auf einen Spot -> Menü; Linksklick-Aktion darf nicht ausgelöst werden
picked = []
w.bandmap.on_pick = lambda s: picked.append(s.call)
now = time.time()
w.bandmap.show_rows([(Spot("W1AW/P", 14200000, "OK1AA-#", "", "1200", received=now), "new")],
                    14000000, "20", now)
w.bandmap.resize(400, 300); app.processEvents()
it = next(w.bandmap.item(i) for i in range(w.bandmap.count()) if "W1AW" in w.bandmap.item(i).text())
rect = w.bandmap.visualItemRect(it)
w.bandmap.customContextMenuRequested.emit(rect.center())
QTest.mouseClick(w.bandmap.viewport(), Qt.MouseButton.RightButton, pos=rect.center())
app.processEvents()
w.close()
print("RESULT " + json.dumps({"menus": menus, "opened": opened, "picked": picked}))
'''


def test_context_menus_offer_qrz(tmp_path):
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
    log_menu, bm_menu = o["menus"][0], o["menus"][1]
    assert log_menu[:2] == ["Bearbeiten …", "Löschen"]
    assert log_menu[2] == "DL1ABC bei QRZ.com ansehen"
    assert bm_menu == ["W1AW bei QRZ.com ansehen"]
    assert o["opened"][:2] == ["https://www.qrz.com/db/DL1ABC", "https://www.qrz.com/db/W1AW"]
    assert o["picked"] == []                  # Rechtsklick stellt das Funkgerät nicht um
