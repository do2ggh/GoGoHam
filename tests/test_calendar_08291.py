"""0.8.29.1: Contest-Kalender – Suche ab 2 Zeichen, einzelne/markierte Contests als ICS-Datei."""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def test_matches():
    from gogoham.gui.calendar_dialog import matches
    assert matches("D", "CQ WW DX CW", "cqww-cw")                  # 1 Zeichen: alles
    assert matches("darc", "DARC 10-m-Contest", "darc-10m")
    assert not matches("darc", "CQ WW DX CW", "cqww-cw")
    assert matches("cqww", "CQ WW DX SSB", "cqww-ssb")              # ohne Leerzeichen
    assert matches("cq ww", "CQ WW DX SSB", "cqww-ssb")
    assert matches("feld", "Fieldday", "x") is False
    assert matches("ukw-fd", "DARC UKW-Fieldday", "darc-ukw-fd-summer")
    assert matches("übung", "Uebung", "x")                         # Umlaute wie ausgeschrieben


SCRIPT = r'''
import json, sys
from datetime import datetime
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham.contests import CONTESTS
from gogoham.gui.calendar_dialog import CalendarDialog
out = {}
d = CalendarDialog(CONTESTS, {}, now=datetime(2026, 11, 14, 15))
out["all"] = d.tbl.rowCount()
d.search.setText("D")
out["one_char"] = d.tbl.rowCount()
d.search.setText("DARC")
names = [d.tbl.item(r, 3).text() for r in range(d.tbl.rowCount())]
out["darc"] = [len(names), all("DARC" in n.upper() for n in names)]
d.search.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
out["esc"] = [d.search.text(), d.tbl.rowCount()]
d.search.setText("cqww dx")
out["cqww"] = sorted(d.tbl.item(r, 3).text() for r in range(d.tbl.rowCount()))
# Rechtsklick: zwei markierte Contests in eine Datei
saved = {}
d._save_path = lambda start: (saved.setdefault("start", start), sys.argv[2] + "/x.ics")[1]
d._saved = lambda n, path: saved.setdefault("n", n)
menus = []
def fake_exec(menu, where):
    acts = menu.actions()
    menus.append(acts[0].text())
    acts[0].trigger()
d._exec_menu = fake_exec
d.tbl.selectRow(0)
from PySide6.QtCore import QItemSelectionModel
d.tbl.selectionModel().select(d.tbl.model().index(1, 0),
    QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
y = d.tbl.rowViewportPosition(1) + 2
d._context_menu(QPoint(5, y))
ics = Path(sys.argv[2] + "/x.ics").read_text()
out["multi"] = [menus[-1], saved.get("start", "").endswith("contests-auswahl.ics"),
                sorted({l[8:] for l in ics.splitlines() if l.startswith("SUMMARY:")})]
# Rechtsklick auf eine nicht markierte Zeile: nur dieser Contest, Dateiname nach dem Contest
d.search.setText("DARC")
d.tbl.selectRow(0)
saved.clear()
y = d.tbl.rowViewportPosition(1) + 2
d._context_menu(QPoint(5, y))
ics = Path(sys.argv[2] + "/x.ics").read_text()
out["single"] = [menus[-1], Path(saved["start"]).name,
                 sorted({l[8:] for l in ics.splitlines() if l.startswith("SUMMARY:")}),
                 d.tbl.item(1, 3).text()]
# Knopf „Als Kalenderdatei speichern“: mit Suche nur die gefundenen
saved.clear()
d.btn_ics.click()
ics = Path(sys.argv[2] + "/x.ics").read_text()
out["button"] = sorted({l[8:] for l in ics.splitlines() if l.startswith("SUMMARY:")})
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def test_search_and_ics_per_contest(tmp_path):
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
           "XDG_DATA_HOME": str(tmp_path / "data"), "HOME": str(tmp_path),
           "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", SCRIPT, str(HERE.parent), str(tmp_path)],
                       capture_output=True, text=True, env=env, timeout=60)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["one_char"] == o["all"] > 20
    assert o["darc"][0] >= 8 and o["darc"][1] and o["darc"][0] < o["all"]
    assert o["esc"] == ["", o["all"]]
    assert o["cqww"] == ["CQ WW DX CW", "CQ WW DX RTTY", "CQ WW DX SSB"]
    menu, auswahl, names = o["multi"]
    assert menu == "Ausgewählte (2) als ICS-Datei speichern …" and auswahl
    assert names == o["cqww"][:2]                     # die ersten beiden Zeilen gewählt
    menu, fname, names, row1 = o["single"]
    assert menu == "Als ICS-Datei speichern …" and names == [row1]
    assert fname.endswith(".ics") and fname != "contests-auswahl.ics" and " " not in fname
    assert o["button"] and all("DARC" in n.upper() for n in o["button"])
