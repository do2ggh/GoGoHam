"""0.10.11: Einstellungen → Operator; neue Logs daraus vorausfüllen; Reihenfolge der Bereiche."""
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from gogoham.gui.operator_page import age_from, age_on, parse_birthdate

ROOT = Path(__file__).resolve().parent.parent


def test_birthdate_and_age():
    assert parse_birthdate("24.12.1965") == date(1965, 12, 24)
    assert parse_birthdate("1965-12-24") == date(1965, 12, 24)
    assert parse_birthdate("") is None and parse_birthdate("31.02.1990") is None
    assert parse_birthdate("1.1.65") is None                       # zweistelliges Jahr: nein
    b = date(1965, 12, 24)
    assert age_on(b, date(2026, 12, 23)) == 60 and age_on(b, date(2026, 12, 24)) == 61
    assert age_from({"my_birthdate": "1965-12-24"}, date(2026, 11, 12)) == "60"
    assert age_from({}) == ""


SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import rigservice
rigservice.available = lambda run=None: False
from gogoham.gui import dialogs, main_window
from gogoham import config as cfgmod
cfg = cfgmod.load()
cfg["station_defaults"] = {"my_grid": "JN59me", "my_state": "XX"}
d = dialogs.SettingsDialog(cfg)
out = {"sections": [t for t, _k in d.sections]}
op = d.operator_page
op.call.setText("do2ggh"); op.grid.setText("jn59ME"); op.dok.setText("b36")
op.licclass.setCurrentText("e"); op.birth.setText("24.12.1965"); op.cq.setText("")
op.club.setText("BCC")
out["ok"] = op.apply()
out["sd"] = cfg["station_defaults"]
op.birth.setText("1965"); out["bad_birth"] = op.apply(); out["msg"] = op.bad.text()
op.birth.setText(""); op.cq.setText("55"); out["bad_cq"] = op.apply()
w = main_window.MainWindow.__new__(main_window.MainWindow)
w.cfg = cfg; w.meta = {"mycall": "DL0OLD", "name": "Alt", "my_grid": "JO40"}; w.cty = None
from gogoham.db import DEFAULT_META
out["meta"] = w._prefill_meta(dict(DEFAULT_META))
w._remember_station({"mycall": "DO2GGH/P", "my_grid": "JN58aa", "my_iota": "EU-005"})
out["after"] = cfg["station_defaults"]
print("OUT" + json.dumps(out))
'''


def test_operator_page_and_prefill(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XDG_CONFIG_HOME=str(tmp_path),
               XDG_DATA_HOME=str(tmp_path))
    r = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], capture_output=True, text=True,
                       env=env, timeout=60)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("OUT")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[0][3:])
    assert o["sections"] == ["Operator", "Funkgerät", "Rotor", "GPS", "Funktionstasten", "Daten & Updates",
                             "Ton & Ansagen", "Online-Dienste", "Zusatzprogramme", "Darstellung"]
    assert o["ok"] is True
    sd = o["sd"]
    assert sd["mycall"] == "DO2GGH" and sd["my_grid"] == "JN59me" and sd["my_dok"] == "B36"
    assert sd["my_licclass"] == "E" and sd["my_birthdate"] == "1965-12-24" and sd["club"] == "BCC"
    assert sd["my_state"] == "XX" and "my_zone" not in sd           # Rest bleibt, leer = weg
    assert o["bad_birth"] is False and "TT.MM.JJJJ" in o["msg"]
    assert o["bad_cq"] is False
    m = o["meta"]
    assert m["mycall"] == "DO2GGH" and m["my_grid"] == "JN59me" and m["my_dok"] == "B36"
    assert m["name"] == "Alt"                                        # nicht in Operator → letztes Log
    assert m["club"] == "BCC" and m["my_age"].isdigit() and m["my_state"] == "XX"
    a = o["after"]                                                   # /P-Log ändert Operator nicht
    assert a["mycall"] == "DO2GGH" and a["my_grid"] == "JN59me" and a["my_iota"] == "EU-005"
