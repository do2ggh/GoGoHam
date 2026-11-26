"""0.8.23: Rotorsteuerung über Hamlib rotctld."""

import json
import os
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

LIST = """ Rot #  Mfg                    Model                   Version         Status        Macro
     1  Hamlib                 Dummy                   20220531.0      Stable        ROT_MODEL_DUMMY
   404  DF9GR                  ERC                     20230328.2      Stable        ROT_MODEL_ERC
   603  Yaesu                  GS-232B                 20220109.0      Stable        ROT_MODEL_GS232B
  2501  FLIR                   PTU Serial              20240818.0      Beta          ROT_MODEL_FLIR
"""

CAPS = """Model name:\t\tGS-232B
Port type:\t\tRS-232
Serial speed:\t\t1200..9600 bauds, 8N1, ctrl=NONE
Min Azimuth:\t\t-180.00
Max Azimuth:\t\t450.00
Can Stop:\t\tY
"""


def test_parse_list_and_filter():
    rs = rt.parse_list(LIST)
    assert [(r.model, r.mfg, r.name, r.status) for r in rs] == [
        (1, "Hamlib", "Dummy", "Stable"), (404, "DF9GR", "ERC", "Stable"),
        (603, "Yaesu", "GS-232B", "Stable"), (2501, "FLIR", "PTU Serial", "Beta")]
    assert [r.model for r in rt.filter_rotors(rs, "gs232")] == [603]
    assert [r.model for r in rt.filter_rotors(rs, "erc")] == [404]


def test_parse_caps():
    c = rt.parse_caps(603, CAPS)
    assert c.serial and (c.speed_min, c.speed_max) == (1200, 9600)
    assert (c.min_az, c.max_az) == (-180.0, 450.0) and c.can_stop
    assert c.bauds() == [1200, 2400, 4800, 9600]


def test_normalize_az():
    n = rt.normalize_az
    assert n(300, 10, 0, 450) == 300                 # 660 liegt außerhalb
    assert n(30, 400, -180, 450) == 390              # Überlappung: kürzer von 400° aus
    assert n(30, 10, -180, 450) == 30
    assert n(200, None, -180, 180) == -160           # Rotor mit Südanschlag
    assert n(200, None, 0, 180) is None              # außerhalb
    assert n(360, None, 0, 360) == 0


def test_bearing_to():
    home = (49.9, 10.9)                              # JO50
    sp = rt.bearing_to(home, (36.4, 138.4))          # Japan
    assert 25 <= sp <= 45
    assert rt.bearing_to(home, (36.4, 138.4), long_path=True) == (sp + 180) % 360
    assert rt.bearing_to(None, (1, 2)) is None and rt.bearing_to(home, None) is None


def test_profile_defaults():
    p = rt.profile({})
    assert p["enabled"] is False and p["port"] == 4540 and p["mode"] == ""
    assert rt.profile({"rotor": {"model": "603", "port": "4541"}})["port"] == 4541


def test_sync_service(tmp_path):
    calls = []

    class R:
        returncode, stdout, stderr = 0, "", ""

    def run(cmd, timeout=30):
        calls.append(cmd)
        return R()
    rig_unit = tmp_path / "gogoham-rigctld-4532.service"
    rig_unit.write_text("x")
    prof = dict(rt.DEFAULTS, enabled=True, model=603, device="/dev/ttyUSB1", baud=9600,
                mode="service", name="GS-232B")
    assert rt.sync_service(prof, run=run, directory=str(tmp_path)) == []
    unit = (tmp_path / "gogoham-rotctld-4540.service").read_text()
    assert "-m 603 -r /dev/ttyUSB1 -s 9600 -t 4540" in unit
    assert ["systemctl", "--user", "enable", "gogoham-rotctld-4540.service"] in calls
    # aus: Dienst weg, Funkgerät-Dienst bleibt unberührt
    assert rt.sync_service(dict(prof, enabled=False), run=run, directory=str(tmp_path)) == []
    assert not (tmp_path / "gogoham-rotctld-4540.service").exists()
    assert rig_unit.exists()


# --- mit echtem Hamlib-Dummy-Rotor (dreht 6°/s) --------------------------------------
def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def dummy_rotctld():
    if not shutil.which("rotctld"):
        pytest.skip("rotctld fehlt")
    port = _free_port()
    proc = subprocess.Popen(["rotctld", "-m", "1", "-t", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        if rt.port_in_use("127.0.0.1", port):
            break
        time.sleep(0.1)
    yield port
    proc.terminate()
    proc.wait(3)


def _wait(cond, secs):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def test_worker_turns_arrives_and_stops(dummy_rotctld):
    w = rt.RotorWorker("127.0.0.1", dummy_rotctld, 0, 360)
    w.start()
    try:
        assert _wait(lambda: w.snapshot().connected and w.snapshot().az is not None, 5)
        w.turn(15)
        assert _wait(lambda: w.snapshot().target == 15, 2)
        assert _wait(lambda: w.snapshot().target is None, 10)          # angekommen
        assert abs(w.snapshot().az - 15) <= rt.REACHED_DEG
        w.turn(90)
        assert _wait(lambda: w.snapshot().target == 90, 2)
        time.sleep(1.0)
        w.halt_rotor()
        assert _wait(lambda: w.snapshot().target is None, 2)
        az = w.snapshot().az
        time.sleep(1.2)
        assert abs(w.snapshot().az - az) < 1.5 and az < 80              # steht wirklich
    finally:
        w.stop()
        w.join(3)


def test_worker_rejects_out_of_range(dummy_rotctld):
    w = rt.RotorWorker("127.0.0.1", dummy_rotctld, 0, 180)
    w.start()
    try:
        assert _wait(lambda: w.snapshot().connected, 5)
        w.turn(270)
        assert _wait(lambda: w.snapshot().notice_id == 1, 3)
        assert "außerhalb" in w.snapshot().notice and w.snapshot().target is None
    finally:
        w.stop()
        w.join(3)


def test_test_profile_reads_only(dummy_rotctld):
    prof = dict(rt.DEFAULTS, enabled=True, model=1, port=dummy_rotctld, mode="external")
    r = rt.test_profile(prof)
    assert r.ok and "steht auf 0°" in r.text
    r = rt.test_profile(dict(prof, port=_free_port()))
    assert not r.ok and "kein rotctld" in r.text


# --- Hauptfenster -------------------------------------------------------------------------
SCRIPT = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMenu
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod
cfg = cfgmod.load()
cfg.update(rig_enabled=False, wsjtx_enabled=False, rotor_auto=False,
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
out["label0"] = [w.lbl_sb_rotor.isVisible(), w.lbl_sb_rotor.text()]
# Alt+R ohne Rufzeichen -> Hinweis, kein Drehen
w.rotor_to_call(False)
out["no_call"] = [w.rotor.snapshot().target, w.statusBar()._msg]
# Rufzeichen eintippen, Alt+R = Short Path
w.ed_call.setText("JA1ABC"); w.update_check()          # wie getippt
pump(0.3)
w.rotor_to_call(False)
pump(1.0)
out["sp"] = [w.rotor.snapshot().target, w.lbl_sb_rotor.text()]
w.rotor_stop(); pump(1.0)
out["stopped"] = w.rotor.snapshot().target
w.rotor_to_call(True); pump(0.6)
out["lp"] = w.rotor.snapshot().target
w.rotor_stop(); pump(0.6)
# Bandmap-Rechtsklick: Rotor-Einträge vor QRZ
w._bandmap_menu(Spot("K3LR", 14025000, "DL1XX-#", "", "1200"), None)
out["menu"] = menus[-1]
# automatisch beim Tippen
w.cfg["rotor_auto"] = True
w.ed_call.setText("VK2ABC"); w.update_check()
pump(0.8)
out["auto_early"] = w.rotor.snapshot().target          # noch nicht (1,5 s Ruhe)
pump(1.5)
out["auto"] = w.rotor.snapshot().target
w.rotor_stop(); pump(0.4)
w.close()
print("RESULT " + json.dumps(out))
'''


def test_main_window_rotor(tmp_path, dummy_rotctld):
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
    home = (49.9, 10.9)
    assert o["label0"] == [True, "Rotor: 0°"]
    assert o["no_call"][0] is None and "Keine Richtung" in o["no_call"][1]
    ja_sp = o["sp"][0]
    assert 25 <= ja_sp <= 45 and "→" in o["sp"][1]
    assert o["stopped"] is None
    assert o["lp"] == (ja_sp + 180) % 360
    assert o["menu"][0].startswith("Rotor drehen: SP ") and o["menu"][1].startswith(
        "Rotor drehen: LP ") and o["menu"][2] == "K3LR bei QRZ.com ansehen"
    assert o["auto_early"] is None
    vk = rt.bearing_to(home, (-25.0, 135.0))
    assert o["auto"] is not None and abs(o["auto"] - vk) < 20


PAGE = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import rigservice
rigservice.available = lambda run=None: True
from gogoham.gui.rotor_page import RotorPage
cfg = {"rig_profiles": [{"slot": 0, "model": 3073, "port": 4532}]}
pg = RotorPage(cfg, test_fn=lambda p: type("R", (), {"ok": True, "text": "x"})())
out = {"mode": pg.mode.currentData(), "port": pg.port.value(), "enabled": pg.enabled.isChecked(),
       "summary": pg.summary.text()}
pg.enabled.setChecked(True)
out["no_model"] = pg.apply()
pg.search.setText("GS-232B"); pg._fill_models(0)
pg.model.setCurrentIndex(pg.model.findData(603))
pg.port.setValue(4532)
out["conflict"] = [pg.apply(), pg.test_result.text()]
pg.port.setValue(4540)
pg.auto.setChecked(True)
out["ok"] = pg.apply()
out["cfg"] = [cfg["rotor"]["model"], cfg["rotor"]["mode"], cfg["rotor"]["port"], cfg["rotor_auto"]]
out["bauds"] = [pg.baud.itemData(i) for i in range(pg.baud.count())]
print("OUT" + json.dumps(out))
'''


def test_rotor_page(tmp_path):
    if not shutil.which("rotctl"):
        pytest.skip("rotctl fehlt")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HOME=str(tmp_path),
               XDG_CONFIG_HOME=str(tmp_path / "cfg"), XDG_DATA_HOME=str(tmp_path / "data"))
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(PAGE), str(HERE.parent)],
                       capture_output=True, text=True, env=env, timeout=60)
    lines = [ln[3:] for ln in r.stdout.splitlines() if ln.startswith("OUT")]
    assert lines, r.stderr[-2000:]
    o = json.loads(lines[-1])
    assert o["mode"] == "service" and o["port"] == 4540 and o["enabled"] is False
    assert o["summary"].startswith("Erweitert: alles Standard")
    assert o["no_model"] is False
    assert o["conflict"][0] is False and "Funkgerät-Profil" in o["conflict"][1]
    assert o["ok"] is True and o["cfg"] == [603, "service", 4540, True]
    assert o["bauds"][:4] == [1200, 2400, 4800, 9600]   # ältere Hamlib-Fassungen melden mehr
