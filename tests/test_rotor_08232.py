"""0.8.23.2: Beam-Keil bis zum Gegenpunkt, Öffnungswinkel einstellbar."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham import rotor as rt

HERE = Path(__file__).parent


def test_beamwidth_default_and_clamp():
    assert rt.profile({})["beamwidth"] == 30
    assert rt.profile({"rotor": {"beamwidth": 25}})["beamwidth"] == 25
    assert rt.profile({"rotor": {"beamwidth": 1}})["beamwidth"] == 5
    assert rt.profile({"rotor": {"beamwidth": 400}})["beamwidth"] == 180


SCRIPT = r'''
import json, sys, math
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import rigservice, worldmap as wm
rigservice.available = lambda run=None: True
from gogoham.gui.mapview import MapCanvas, KM_PER_RAD
from gogoham.gui.rotor_page import RotorPage
out = {}
c = MapCanvas(); c.resize(800, 400); c.home = (49.9, 10.9); c.kind = wm.AZI
ray = c._beam_ray(59.0)
end = wm.unproject(wm.AZI, *ray[-1], c.home)
out["ray_km"] = wm.angular_distance(*c.home, *end) * KM_PER_RAD
# Neuseeland liegt auf dem Strahl (Abstand < 300 km zu einem Punkt)
pts = [wm.unproject(wm.AZI, x, y, c.home) for x, y in ray]
out["zl_km"] = min(wm.angular_distance(-41.3, 174.8, *p) * KM_PER_RAD for p in pts if p)
cfg = {}
pg = RotorPage(cfg, test_fn=lambda p: None)
out["page_default"] = pg.beamwidth.value()
pg.beamwidth.setValue(25)
pg.apply()
out["saved"] = cfg["rotor"]["beamwidth"]
print("OUT" + json.dumps(out))
'''


def test_beam_reaches_antipode_and_width_saved(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HOME=str(tmp_path),
               XDG_CONFIG_HOME=str(tmp_path / "cfg"), XDG_DATA_HOME=str(tmp_path / "data"))
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent)],
                       capture_output=True, text=True, env=env, timeout=60)
    lines = [ln[3:] for ln in r.stdout.splitlines() if ln.startswith("OUT")]
    assert lines, r.stderr[-2000:]
    o = json.loads(lines[-1])
    assert o["ray_km"] > 19000                       # fast bis zum Gegenpunkt (~20 000 km)
    assert o["zl_km"] < 300
    assert o["page_default"] == 30 and o["saved"] == 25
