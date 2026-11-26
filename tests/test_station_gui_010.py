"""0.10: Stationslog mit echtem Qt – zwei GoGoHam als getrennte Programme auf einem Rechner.
Der zweite findet den Hauptplatz von selbst, fragt „Mitmachen?“, prüft das Kennwort; danach
gehen QSOs in beide Richtungen, Nummern kommen vom Hauptplatz."""

import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
ROOT = HERE.parent

COMMON = r'''
import json, sys, time
import faulthandler
# hängt ein Testprogramm (z. B. auf GitHub), schreibt es nach 80 s auf, wo – statt stumm
# bis zur Zeitgrenze zu warten
faulthandler.dump_traceback_later(80, exit=True)
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog
app = QApplication([])
from gogoham import station as st
st.KDF_ROUNDS = 1000
st.UDP_PORT = int(sys.argv[3]); st.TCP_PORT = int(sys.argv[4])
st.beacon_targets = lambda: ["127.0.0.1", "255.255.255.255", st.MCAST_GROUP]
st.BEACON_EVERY = 0.3
# Netzwerk-Prüfung aus: hat der Testrechner einen Anschluss ohne Adresse (GitHub: „ens1“), fragt
# GoGoHam sonst „Am Kabel ist kein Router …“ – und niemand klickt
st.network_state = lambda run=None: []
from gogoham.contests import Qso
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui import main_window
main_window.MainWindow._welcome = lambda self: None
main_window.MainWindow._ask_scp = lambda self, *a, **k: None
main_window.MainWindow._ask_station = lambda self: None
main_window.MainWindow._start_daily_update = lambda self, wait=10.0: None
out = {}
def spin(sec, until=None):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.02)
        if until and until():
            return True
    return False
def calls(w):
    return sorted(q.call for q in w.qsos)
def log(w, call, exch="14"):
    w.ed_call.setText(call); w.ed_exch.setText(exch); w.log_qso(); app.processEvents()
'''

HOST = COMMON + r'''
w = main_window.MainWindow(); w.show()
p = Path(sys.argv[2]) / "station.ggh"
meta = dict(DEFAULT_META, contest="wpx-cw", mycall="DL0ABC", cat_operator="MULTI-OP",
            cat_transmitter="TWO")
meta = w.station.new_host_meta(meta, "geheim")
db = LogDB(p); db.set_meta(meta); db.close()
w.cfg["station_operator"] = "DL1AAA"; w.cfg["station_place_name"] = "Platz 1"
w.cfg["station_cable_asked"] = 9
w.open_log(str(p)); spin(0.3)
w.cb_mode.setCurrentText("CW")
out["role"] = w.station.role
log(w, "W1AW")
out["sent1"] = w.qsos[-1].exch_s
ok = spin(25, lambda: "JA1AAA" in calls(w))
out["got_ja"] = ok
out["places"] = len(w.station.host.places)
out["sb"] = w.station.label.text()
log(w, "VK2AA")
out["sent_vk"] = w.qsos[-1].exch_s
spin(4)
out["calls"] = calls(w)
out["ops"] = sorted({q.operator for q in w.qsos})
out["tx"] = sorted((q.call, q.tx) for q in w.qsos)
from gogoham.export import cabrillo
out["cab_tx"] = sorted(ln.split()[-1] for ln in cabrillo(w.contest, w.meta, w.qsos, w.scorer).splitlines() if ln.startswith("QSO:"))
spin(3)
w._dirty = False
print(json.dumps(out)); sys.stdout.flush()
w.close()
'''

PLACE = COMMON + r'''
w = main_window.MainWindow(); w.show()
w.cfg["station_operator"] = "DO2GGH"; w.cfg["station_place_name"] = "Platz 2"
w.cfg["station_cable_asked"] = 9
asked = []
QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2]), QMessageBox.StandardButton.Yes)[1])
pw = iter(["falsch", "geheim"])
QInputDialog.getText = staticmethod(lambda *a, **k: (next(pw), True))
ok = spin(15, lambda: w.station.active and w.station.connected())
out["joined"] = ok
out["asked"] = asked[:1]
out["file"] = Path(w.db.path).name if w.db else ""
out["role"] = w.station.role
ok = spin(10, lambda: "W1AW" in calls(w))
out["has_w1aw"] = ok
out["contest"] = w.meta.get("contest")
w.cb_mode.setCurrentText("CW")
spin(1.0)
out["serial_before"] = w._serial()
log(w, "JA1AAA")
out["sent_ja"] = w.qsos[-1].exch_s if w.qsos else ""
ok = spin(15, lambda: "VK2AA" in calls(w))
out["has_vk"] = ok
out["calls"] = calls(w)
out["sb"] = w.station.label.text()
w._dirty = False
print(json.dumps(out)); sys.stdout.flush()
w.close()
'''


def free_port(kind=socket.SOCK_STREAM):
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def env_for(base: Path):
    data = base / "data" / "gogoham"
    data.mkdir(parents=True)
    shutil.copy(HERE / "cty_sample.dat", data / "cty.dat")
    (base / "cfg" / "gogoham").mkdir(parents=True)
    (base / "cfg" / "gogoham" / "config.json").write_text(json.dumps(
        {"rig_enabled": False, "wsjtx_enabled": False, "language": "de"}))
    return {"QT_QPA_PLATFORM": "offscreen", "GOGOHAM_DISCOVERY": "1", "HOME": str(base),
            "XDG_CONFIG_HOME": str(base / "cfg"), "XDG_DATA_HOME": str(base / "data"),
            "PATH": "/usr/bin:/bin"}


def test_two_programs_join_and_sync(tmp_path):
    pytest.importorskip("PySide6")
    udp, tcp = free_port(socket.SOCK_DGRAM), free_port()
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    pa = subprocess.Popen([sys.executable, "-c", HOST, str(ROOT), str(a), str(udp), str(tcp)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          env=env_for(a))
    pb = subprocess.Popen([sys.executable, "-c", PLACE, str(ROOT), str(b), str(udp), str(tcp)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          env=env_for(b))
    oa, ea = pa.communicate(timeout=90)
    ob, eb = pb.communicate(timeout=90)
    assert pa.returncode == 0, ea[-3000:]
    assert pb.returncode == 0, eb[-3000:]
    A = json.loads(oa.strip().splitlines()[-1])
    B = json.loads(ob.strip().splitlines()[-1])
    assert A["role"] == "host" and A["sent1"] == "001"
    assert B["joined"] and B["role"] == "place", (B, eb[-2000:])
    assert "DL0ABC" in B["asked"][0] and "Mitmachen?" in B["asked"][0]
    assert B["file"].startswith("station-wpx-cw-") and B["contest"] == "wpx-cw"
    # die 2 hält der Hauptplatz für sein nächstes QSO reserviert -> der Platz bekommt die 3
    assert B["has_w1aw"] and B["serial_before"] == 3 and B["sent_ja"] == "003"
    assert A["sent_vk"] == "002"
    assert A["got_ja"] and A["places"] == 1
    assert "Hauptplatz · 2 Plätze · OP DL1AAA" in A["sb"]
    assert B["has_vk"] and B["calls"] == ["JA1AAA", "VK2AA", "W1AW"] == A["calls"]
    assert A["ops"] == ["DL1AAA", "DO2GGH"]
    assert "verbunden" in B["sb"]
    # Multi-Two (0.10.2): Hauptplatz = Sender 0, Platz = Sender 1 – auch im Cabrillo-Log
    assert A["tx"] == [["JA1AAA", "1"], ["VK2AA", "0"], ["W1AW", "0"]]
    assert A["cab_tx"] == ["0", "0", "1"]


OLD_PLACE = COMMON + r'''
import uuid
from gogoham.gui import station_ui
w = main_window.MainWindow(); w.show()
w.cfg["station_operator"] = "DO2GGH"; w.cfg["station_place_name"] = "Platz 2"
w.cfg["station_cable_asked"] = 9
old = uuid.uuid4().hex
w.cfg["station_keys"] = {old: "00" * 32}
p = Path(sys.argv[2]) / "alt.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="cqww-cw", mycall="DL0OLD", station_role="place",
                                station_log_id=old, station_host_addr="127.0.0.1",
                                station_host_port="1")); db.close()
w.open_log(str(p))
w.station._started -= 20                          # Wartezeit nach dem Start vorbei
asked = []
QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2]), QMessageBox.StandardButton.No)[1])
spin(10, lambda: asked)
out["asked"] = asked[:1]
out["role"] = w.station.role
w._dirty = False
print(json.dumps(out)); sys.stdout.flush()
w.close()
'''


def test_place_without_host_is_offered_new_station_log(tmp_path):
    """Laptop startet mit altem Stationslog, dessen Hauptplatz nicht läuft: das neue
    Stationslog im Netz wird trotzdem angeboten."""
    pytest.importorskip("PySide6")
    udp, tcp = free_port(socket.SOCK_DGRAM), free_port()
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    pa = subprocess.Popen([sys.executable, "-c", HOST, str(ROOT), str(a), str(udp), str(tcp)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          env=env_for(a))
    pb = subprocess.Popen([sys.executable, "-c", OLD_PLACE, str(ROOT), str(b), str(udp),
                           str(tcp)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          env=env_for(b))
    ob, eb = pb.communicate(timeout=60)
    pa.kill()
    pa.communicate()
    assert pb.returncode == 0, eb[-3000:]
    B = json.loads(ob.strip().splitlines()[-1])
    assert B["role"] == "place" and B["asked"] and "DL0ABC" in B["asked"][0]


START = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui import main_window
main_window.MainWindow._ask_scp = lambda self, *a, **k: None
main_window.MainWindow._ask_station = lambda self: None
main_window.MainWindow._start_daily_update = lambda self, wait=10.0: None
main_window.MainWindow._serial_access_check = lambda self: None   # USB-Freigabe (0.10.25)
p = Path(sys.argv[2]) / "alt.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="cqww-cw", mycall="DO2GGH")); db.close()
from gogoham import config as cfgmod
cfg = cfgmod.load(); cfg["last_log"] = str(p); cfgmod.save(cfg)
out = {}
choice = sys.argv[3]
def fake_exec(box):
    out["text"] = box.text()
    for b in box.buttons():
        if b.text() == choice:
            box._clicked = b
    return 0
QMessageBox.exec = fake_exec
QMessageBox.clickedButton = lambda box: getattr(box, "_clicked", None)
w = main_window.MainWindow(progress=lambda s: None)
out["db_at_start"] = w.db is not None
w.run_startup_popups()
for _ in range(50):
    app.processEvents()
    import time; time.sleep(0.01)
out["db_after"] = Path(w.db.path).name if w.db else None
w._dirty = False
print(json.dumps(out))
'''


@pytest.mark.parametrize("choice,expect", [("Weitermachen", "alt.ggh"), ("Nein", None)])
def test_start_asks_for_last_log(tmp_path, choice, expect):
    pytest.importorskip("PySide6")
    r = subprocess.run([sys.executable, "-c", START, str(ROOT), str(tmp_path), choice],
                       capture_output=True, text=True, env=env_for(tmp_path), timeout=60)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["db_at_start"] is False                 # leer gestartet
    assert "CQ WW DX CW – alt.ggh (0 QSOs)" in out["text"] and "Weitermachen?" in out["text"]
    assert out["db_after"] == expect
