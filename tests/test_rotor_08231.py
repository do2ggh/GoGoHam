"""0.8.23.1: Rotor auf der Karte (Beam, Rechtsklick) und Rotor-Fenster (Kompassrose)."""

import json
import shutil
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from gogoham import rotor as rt

HERE = Path(__file__).parent


@pytest.fixture
def dummy_rotctld():
    if not shutil.which("rotctld"):
        pytest.skip("rotctld fehlt")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen(["rotctld", "-m", "1", "-t", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        if rt.port_in_use("127.0.0.1", port):
            break
        time.sleep(0.1)
    yield port
    proc.terminate()
    proc.wait(3)


SCRIPT = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QMenu
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod
cfg = cfgmod.load()
cfg.update(rig_enabled=False, wsjtx_enabled=False, map_background="simple",
           map_spots=False, map_beacons=False,
           rotor={"enabled": True, "model": 1, "mode": "external", "host": "127.0.0.1",
                  "port": int(sys.argv[4])})
cfgmod.save(cfg)
from gogoham.db import DEFAULT_META, LogDB
from gogoham.dxcluster import Spot
from gogoham.gui import main_window
main_window.MainWindow._welcome = lambda self: None
main_window.MainWindow._ask_scp = lambda self, *a, **k: None
main_window.MainWindow._start_daily_update = lambda self, wait=10.0: None
menus = []
class FakeMenu(QMenu):
    def exec(self, *a):
        menus.append([x.text() for x in self.actions() if not x.isSeparator()])
        for x in self.actions():                     # ersten Rotor-Eintrag auslösen
            if x.text().startswith("Rotor drehen: SP"):
                x.trigger(); break
main_window.QMenu = FakeMenu
def pump(secs):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents(); time.sleep(0.05)

p = Path(sys.argv[2]) / "x.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="cqww-cw", mycall="DO2GGH",
                                my_grid="JO50")); db.close()
w = main_window.MainWindow(); w.open_log(str(p)); w.show()
out = {}
pump(1.5)
w.toggle_map(True); pump(0.5)
c = w.map_view.canvas
c.resize(900, 480); pump(0.3)
out["beam0"] = [c.beam_az, c.beam_target, c.show_beam]

def right_click(x, y):
    for typ in (QMouseEvent.Type.MouseButtonPress, QMouseEvent.Type.MouseButtonRelease):
        btn = Qt.MouseButton.RightButton
        ev = QMouseEvent(typ, QPointF(x, y), QPointF(c.mapToGlobal(QPointF(x, y).toPoint())), btn,
                         btn if typ == QMouseEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(c, ev)

# Rechtsklick auf eine freie Stelle östlich vom Standort -> Rotor dorthin (SP ~90°)
from gogoham import worldmap as wm
pt = c.to_px(*wm.project(c.effective_kind(), 50.0, 60.0, c.home))
right_click(pt.x(), pt.y())
pump(0.8)
out["menu_point"] = menus[-1]
out["beam_turning"] = [c.beam_target, c.beam_az]
w.rotor_stop(); pump(0.8)
out["beam_stopped"] = c.beam_target

# Spot-Menü in der Karte: Rotor + QRZ
w._map_spot_menu([Spot("JA1ABC", 14025000, "DL1XX-#", "", "1200")], None)
out["menu_spot"] = menus[-1]
w.rotor_stop(); pump(0.5)

# Rotor-Fenster: öffnen, Gradzahl eingeben, Klick in die Rose
w.act_rotor.setChecked(True); pump(0.6)
v = w.rotor_view
out["view_open"] = [not w.rot_dock.isHidden(), v.btn_go.isEnabled(), v.status.text()]
v.deg.setValue(200); v.btn_go.click(); pump(0.6)
out["view_turn"] = w.rotor.snapshot().target
v.btn_stop.click(); pump(0.6)
out["view_stop"] = w.rotor.snapshot().target
v.rose.resize(220, 220)
b = v.rose.bearing_at(110 + 60, 110)                  # rechts von der Mitte = Osten
out["rose_bearing"] = b
v.rose.on_click(b); pump(0.6)
out["rose_turn"] = w.rotor.snapshot().target
w.rotor_stop(); pump(0.4)
w.act_rotor.setChecked(False); pump(0.2)
out["view_closed"] = w.rot_dock.isHidden()
# Häkchen „Beam“ in der Karte
w.map_view.checks["map_beam"].setChecked(False)
out["beam_cfg"] = [c.show_beam, w.cfg.get("map_beam")]
w.close()
print("RESULT " + json.dumps(out))
'''


def test_map_and_window(tmp_path, dummy_rotctld):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    (cfg / "gogoham").mkdir(parents=True)
    (data / "gogoham").mkdir(parents=True)
    logs.mkdir()
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(logs), str(HERE / "cty_sample.dat"), str(dummy_rotctld)],
                       capture_output=True, text=True, env=env, timeout=90)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["beam0"] == [0, None, True]
    assert o["menu_point"][0].startswith("Rotor drehen: SP ") and len(o["menu_point"]) == 2
    sp = int(o["menu_point"][0].split()[-1].rstrip("°"))
    assert 60 <= sp <= 90
    assert o["beam_turning"][0] == sp
    assert o["beam_stopped"] is None
    assert o["menu_spot"][:2][0].startswith("Rotor drehen: SP") and \
        o["menu_spot"][-1] == "JA1ABC bei QRZ.com ansehen"
    assert o["view_open"][0] is True and o["view_open"][1] is True
    assert o["view_turn"] == 200 and o["view_stop"] is None
    assert o["rose_bearing"] == 90 and o["rose_turn"] == 90
    assert o["view_closed"] is True
    assert o["beam_cfg"] == [False, False]
