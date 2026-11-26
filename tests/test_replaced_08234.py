"""0.8.23.4: Profil auf einem übernommenen Systemdienst-Port nicht still auf „nur solange
GoGoHam läuft“ lassen (sonst „Ein-/Ausgabefehler“ in anderen Programmen)."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).parent

SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
from gogoham import rigservice
rigservice.available = lambda run=None: True
from gogoham.gui import dialogs
answers, asked = [], []
def question(parent, title, text, *a, **k):
    asked.append(title)
    return answers.pop(0)
dialogs.QMessageBox.question = staticmethod(question)
from gogoham.gui.dialogs import RigDialog
def make(extra):
    cfg = dict({"rig_enabled": True, "rig_autostart": True, "rig_host": "127.0.0.1",
                "rig_port": 4532, "rig_model": 0, "rig_device": "", "rig_baud": 0,
                "rig_extra": "", "rig_profile": 0,
                "rig_profiles": [{"slot": 0, "name": "IC-7300", "model": 3073,
                                  "device": "/dev/ttyUSB0", "baud": 115200, "extra": "",
                                  "start": True, "service": False, "port": 4532}]}, **extra)
    return cfg, RigDialog(cfg)
out = {}
# alte Einstellung (nur Dienstname bekannt): fragt, Ja -> dauerhaft
cfg, d = make({"rig_replaced_services": ["rigctld.service"]})
answers[:] = [QMessageBox.StandardButton.Yes]
out["yes"] = [d.apply(), cfg["rig_profiles"][0]["service"], cfg["rig_profiles"][0]["start"],
              d.startmode.currentData(), len(asked)]
# Nein -> bleibt, wird gemerkt, fragt nicht wieder
asked.clear()
cfg, d = make({"rig_replaced_services": ["rigctld.service"]})
answers[:] = [QMessageBox.StandardButton.No]
d.apply()
d.apply()
out["no"] = [cfg["rig_profiles"][0]["service"], cfg.get("rig_selfmode_ok"), len(asked)]
# nichts übernommen -> keine Frage
asked.clear()
cfg, d = make({})
d.apply()
out["none"] = len(asked)
# anderer Port übernommen -> keine Frage
cfg, d = make({"rig_replaced_services": ["x.service"], "rig_replaced_ports": [4533]})
d.apply()
out["other_port"] = len(asked)
print("OUT" + json.dumps(out))
'''


def test_replaced_port_asks_for_service(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HOME=str(tmp_path),
               XDG_CONFIG_HOME=str(tmp_path / "cfg"), XDG_DATA_HOME=str(tmp_path / "data"))
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent)],
                       capture_output=True, text=True, env=env, timeout=60)
    lines = [ln[3:] for ln in r.stdout.splitlines() if ln.startswith("OUT")]
    assert lines, r.stderr[-2000:]
    o = json.loads(lines[-1])
    assert o["yes"] == [True, True, False, "service", 1]
    assert o["no"] == [False, [4532], 1]
    assert o["none"] == 0 and o["other_port"] == 0
