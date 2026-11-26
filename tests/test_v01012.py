"""0.10.12: Fenster passen auf den Bildschirm (mit Taskleiste), Willkommensfenster statt
Startfragen, WSJT-X Improved in der Systemsprache, Feld Lizenzklasse breit genug."""
import json
import os
import subprocess
import sys
from pathlib import Path

from gogoham import extapps

ROOT = str(Path(__file__).parent.parent)

GUI = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QDialog, QScrollArea
app = QApplication([])
from gogoham import config
from gogoham.gui import dialogs, fitscreen
from gogoham.gui.main_window import welcome_text
from gogoham.gui.operator_page import OperatorPage
out = {}
# 1) Neues Contest-Log: klein genug für 1366×768, Haken + Knöpfe außerhalb des Scrollbereichs
d = dialogs.LogSettingsDialog({"mycall": "DO2GGH"}, new_log=True)
out["log_min_h"] = d.minimumSizeHint().height()
p = d.cb_station.parent()
inside = False
while p is not None:
    inside = inside or isinstance(p, QScrollArea)
    p = p.parent()
out["cb_in_scroll"] = inside
# 2) Einstellungen: jede Seite scrollt
cfg = config.load()
s = dialogs.SettingsDialog(cfg, check_apps=False)
out["set_min_h"] = s.minimumSizeHint().height()
out["pages_scroll"] = all(isinstance(s.stack.widget(i), QScrollArea) or
                          s.stack.widget(i).__class__.__name__ == "QTabWidget"
                          for i in range(s.stack.count()))
# 3) fit(): auf die freie Fläche begrenzen, auch die Mindestbreite
w = QDialog(); w.setMinimumWidth(1280); w.resize(1300, 900)
fitscreen.fit(w, QRect(0, 0, 1024, 700))
out["fit"] = [w.width(), w.height(), w.minimumWidth()]
# 4) Lizenzklasse breit genug für den Hinweis
op = OperatorPage(cfg)
fm = op.licclass.fontMetrics()
out["lic_ok"] = op.licclass.sizeHint().width() >= fm.horizontalAdvance("z. B. A, E oder N")
out["welcome"] = welcome_text()
print("OUT" + json.dumps(out))
'''


def test_gui_fits_laptop(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XDG_CONFIG_HOME=str(tmp_path),
               XDG_DATA_HOME=str(tmp_path))
    r = subprocess.run([sys.executable, "-c", GUI, ROOT], capture_output=True, text=True,
                       env=env, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("OUT")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[0][3:])
    assert o["log_min_h"] < 500 and not o["cb_in_scroll"]
    assert o["set_min_h"] < 600 and o["pages_scroll"]
    fw, fh, fmin = o["fit"]
    assert fw <= 1024 - 16 and fh <= 700 - 48 and fmin <= 1024 - 16
    assert o["lic_ok"]
    t = o["welcome"]
    order = [t.find(x) for x in ("Internet", "Operator", "Funkgerät", "Alles herunterladen")]
    assert -1 not in order and order == sorted(order)


def test_startup_questions_gone():
    src = Path(ROOT, "gogoham/gui/main_window.py").read_text(encoding="utf-8")
    for gone in ("later.append((150, self._ask_station))", "later.append((400, self._ask_cty))",
                 "later.append((400, self._ask_scp))", "later.append((400, self._ask_flags))"):
        assert gone not in src
    assert "self._first_welcome" in src and '"welcome_done"' in src


def test_improved_language(tmp_path):
    st, _o = extapps.station_settings({}, None, {}, audio=lambda p, f: ("", "", ""),
                                      key="wsjtx_improved")
    st["ui_language"] = "de"
    st0, _o = extapps.station_settings({}, None, {}, audio=lambda p, f: ("", "", ""), key="wsjtx")
    assert "ui_language" not in st0                     # Original-WSJT-X: nimmt die Systemsprache
    ini = tmp_path / "WS.ini"
    ini.write_text("[Configuration]\nMyCall=DL1XX\n")
    diff = extapps.changes(ini, "127.0.0.1", 4532, "127.0.0.1", 2237, st)
    assert any("Sprache" in label for label, _old in diff)
    extapps.apply(ini, "127.0.0.1", 4532, "127.0.0.1", 2237, st, now=0)
    assert extapps.current(ini, "MultiSettings")["UILanguage"] == "de"
    assert extapps.changes(ini, "127.0.0.1", 4532, "127.0.0.1", 2237, st) == []
    # eigene Wahl im Menü „Language“ bleibt
    ini.write_text("[Configuration]\n[MultiSettings]\nUILanguage=en_GB\n")
    extapps.apply(ini, "127.0.0.1", 4532, "127.0.0.1", 2237, st, now=1)
    assert extapps.current(ini, "MultiSettings")["UILanguage"] == "en_GB"
    # Englisch: nichts eintragen
    st["ui_language"] = "en"
    ini2 = tmp_path / "b.ini"
    extapps.apply(ini2, "127.0.0.1", 4532, "127.0.0.1", 2237, st, now=2)
    assert "MultiSettings" not in ini2.read_text()
