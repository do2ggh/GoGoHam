"""0.8.29.1: Abfrage-Intervall in „Funkgerät – erweiterte Einstellungen“ (0 = automatisch)."""

import json
import subprocess
import sys
from pathlib import Path

from gogoham import rigprofiles

HERE = Path(__file__).parent

SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import rigservice
rigservice.available = lambda run=None: False
from gogoham.gui.dialogs import RigDialog
cfg = {"rig_enabled": True, "rig_autostart": True, "rig_host": "127.0.0.1", "rig_port": 4532,
       "rig_model": 0, "rig_device": "", "rig_baud": 0, "rig_extra": "",
       "rig_profiles": [{"slot": 0, "name": "IC-7300", "model": 3073, "device": "/dev/ttyUSB0",
                         "baud": 115200, "extra": ""}], "rig_profile": 0}
d = RigDialog(cfg)
d.show(); app.processEvents()
out = {"text0": d.poll_ms.text(), "summary0": d.adv_summary.text(), "hint": d.poll_hint.text()}
d._store_slot()
out["auto"] = d.slots[0]["poll_ms"]
d.poll_ms.setValue(5)
d._store_slot()
out["five"] = [d.slots[0]["poll_ms"], d.poll_hint.text()]
d.poll_ms.setValue(50)
d._store_slot()
out["fifty"] = [d.slots[0]["poll_ms"], d.adv_summary.text()]
out["apply"] = d.apply()
out["cfg"] = cfg["rig_profiles"][0].get("poll_ms")
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def test_poll_setting_in_advanced_dialog(tmp_path):
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
           "XDG_DATA_HOME": str(tmp_path / "data"), "HOME": str(tmp_path),
           "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", SCRIPT, str(HERE.parent)],
                       capture_output=True, text=True, env=env, timeout=60)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["text0"] == "automatisch" and "Abfrage" not in o["summary0"]
    assert "höchstens 50-mal pro Sekunde" in o["hint"]
    assert o["auto"] == 0
    assert o["five"][0] == 20 and "nimmt 20 ms" in o["five"][1]
    assert o["fifty"][0] == 50 and "Abfrage alle 50 ms" in o["fifty"][1]
    assert o["apply"] and o["cfg"] == 50


def test_old_profiles_get_automatic_polling():
    cfg = {"rig_profiles": [{"name": "X", "model": 3073}]}
    assert rigprofiles.ensure_profiles(cfg)[0]["poll_ms"] == 0
