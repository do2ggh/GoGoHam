"""0.8.22.1: Neue Funkgerät-Profile richten rigctld dauerhaft ein (wo möglich)."""

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
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import rigservice
rigservice.available = lambda run=None: sys.argv[2] == "1"
from gogoham.gui.dialogs import RigDialog
cfg = {"rig_enabled": True, "rig_autostart": True, "rig_host": "127.0.0.1", "rig_port": 4532,
       "rig_model": 0, "rig_device": "", "rig_baud": 0, "rig_extra": "",
       "rig_profiles": [{"slot": 0, "name": "Alt", "model": 3073, "device": "/dev/ttyUSB0",
                         "baud": 115200, "extra": "", "start": True}], "rig_profile": 0}
d = RigDialog(cfg)
out = {"old": d.startmode.currentData(), "old_summary": d.adv_summary.text()}
d.profile.setCurrentIndex(1)                 # freier Platz 2 -> neues Profil
out["new"] = d.startmode.currentData()
out["summary"] = d.adv_summary.text()
print("OUT" + json.dumps(out))
'''


def _run(tmp_path, available):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HOME=str(tmp_path),
               XDG_CONFIG_HOME=str(tmp_path / "cfg"), XDG_DATA_HOME=str(tmp_path / "data"))
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        "1" if available else "0"], capture_output=True, text=True, env=env,
                       timeout=60)
    lines = [ln[3:] for ln in r.stdout.splitlines() if ln.startswith("OUT")]
    assert lines, r.stderr[-2000:]
    return json.loads(lines[-1])


def test_new_profile_defaults_to_service(tmp_path):
    o = _run(tmp_path, True)
    assert o["old"] == "self"                 # vorhandenes Profil wird nicht umgestellt
    assert o["new"] == "service"
    assert o["summary"].startswith("Erweitert: alles Standard")
    assert "rigctld nur mit GoGoHam" in o["old_summary"]


def test_without_systemd_falls_back(tmp_path):
    o = _run(tmp_path, False)
    assert o["new"] == "self"
    assert o["summary"].startswith("Erweitert: alles Standard")
    assert o["old_summary"].startswith("Erweitert: alles Standard")
