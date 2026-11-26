"""0.10.25: GPS-Empfänger (NMEA lesen, Geräte erkennen, Zeit-Abweichung, gpsd) und die
USB-Freigabe (udev-Regel mit uaccess). Ohne echtes Gerät: Pseudo-Terminal und Attrappen."""

import json
import os
import shutil
import socket
import subprocess
import sys
import textwrap
import threading
import time
import tty
from datetime import datetime, timezone
from pathlib import Path

import pytest

from gogoham import gps, permissions
from gogoham.locator import from_latlon

HERE = Path(__file__).parent
ROOT = HERE.parent


def nmea(body: str) -> str:
    x = 0
    for c in body.encode():
        x ^= c
    return f"${body}*{x:02X}\r\n"


def epoch_lines(t: float, talker: str = "GN", lat="4911.4000,N", lon="01101.2000,E",
                valid=True, used=9):
    d = datetime.fromtimestamp(t, timezone.utc)
    hms, dmy = d.strftime("%H%M%S.00"), d.strftime("%d%m%y")
    q = 1 if valid else 0
    return [nmea(f"{talker}RMC,{hms},{'A' if valid else 'V'},{lat},{lon},0.0,,{dmy},,,A"),
            nmea(f"{talker}GGA,{hms},{lat},{lon},{q},{used:02d},1.0,380.0,M,47.0,M,,"),
            nmea(f"{talker}GSA,A,{3 if valid else 1},01,02,03,,,,,,,,,,1.5,1.0,1.1"),
            nmea("GPGSV,2,1,07,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45"),
            nmea("GLGSV,1,1,04,65,40,083,46,66,17,308,41,67,07,344,39,68,22,228,45")]


# --------------------------------------------------------------------------- Locator
@pytest.mark.parametrize("lat, lon, want", [(49.19, 11.02, "JN59me"), (-33.87, 151.21, "QF56od"),
                                            (40.0, -105.25, "DN70ja"), (0.0, 0.0, "JJ00aa"),
                                            (89.99999, 179.9999, "RR99xx")])
def test_from_latlon(lat, lon, want):
    assert from_latlon(lat, lon) == want


def test_from_latlon_8_and_4():
    assert from_latlon(49.19, 11.02, 4) == "JN59"
    assert len(from_latlon(49.19, 11.02, 8)) == 8


# --------------------------------------------------------------------------- NMEA
def test_checksum_and_parse_all_talkers():
    for talker in ("GP", "GN", "GL", "GA", "GB", "BD"):
        s = gps.parse(nmea(f"{talker}RMC,120000.00,A,4911.4000,N,01101.2000,W,0.0,,141126,,,A"))
        assert s["type"] == "RMC" and s["valid"]
        assert abs(s["lat"] - 49.19) < 1e-6 and abs(s["lon"] + 11.02) < 1e-6
    assert gps.parse("$GPRMC,120000.00,A,4911.4,N,01101.2,E,,,141126,,,A*00") is None
    assert gps.parse("Müll ohne Dollar") is None
    s = gps.parse(nmea("GNGGA,120000.00,3352.2000,S,15112.6000,E,2,12,0.8,25.5,M,,M,,"))
    assert s["quality"] == 2 and s["used"] == 12 and s["alt"] == 25.5 and s["lat"] < 0
    assert gps.parse(nmea("GNGSA,A,3,,,,,,,,,,,,,1.0,1.0,1.0"))["mode"] == 3
    assert gps.parse(nmea("GPGSV,3,1,11,01,40,083,46"))["view"] == 11
    z = gps.parse(nmea("GPZDA,120000.00,14,11,2026,00,00"))
    assert z["date"] == "141126" and z["year"] == 2026
    assert gps.parse(nmea("GNGNS,120000.00,4911.4,N,01101.2,E,AN,10,1.0,380,47,,"))["quality"] == 1
    assert gps.parse(nmea("GNGNS,120000.00,,,,,NN,00,,,,,"))["quality"] == 0


def test_tracker_fix_grid_and_offset():
    now = [1_800_000_000.0]
    mono = [100.0]
    tr = gps.Tracker(clock=lambda: now[0], mono=lambda: mono[0])
    # ohne Fix: verbunden, aber kein Standort
    for ln in epoch_lines(now[0], valid=False, used=0):
        tr.feed(ln, recv=now[0] + 0.3)
    st = tr.state
    assert st.connected and st.fix == 0 and not st.has_fix and st.view == 11
    assert st.offset is None                     # ohne Fix keine Zeit
    # mit Fix; PC-Uhr geht 2 s nach (GPS-Zeit 2 s weiter als die PC-Zeit)
    for i, lat in enumerate((0.25, 0.4, 0.3, 0.2, 0.6, 0.35)):
        t = now[0] + 10 + i
        for ln in epoch_lines(t):
            tr.feed(ln, recv=t - 2 + lat)        # kommt 0,2–0,6 s nach der Sekunde an
    st = tr.state
    assert st.has_fix and st.fix == 3 and st.used == 9 and st.grid == "JN59me"
    assert st.samples == 6 and abs(st.offset - 1.8) < 1e-6     # beste (kleinste) Verspätung
    # vertrauenswürdig erst nach 13 Minuten (Schaltsekunden), große Abweichung nach 1 Minute
    assert not st.time_trusted(now=mono[0] + 60)
    assert st.time_trusted(now=mono[0] + gps.LEAP_SAFE_S + 1)
    st.offset = 3600.0
    assert st.time_trusted(now=mono[0] + 61) and not st.time_trusted(now=mono[0] + 30)
    tr.reset_time()
    assert tr.state.offset is None and tr.state.samples == 0
    tr.stale()
    assert not tr.state.connected and not tr.state.has_fix


def test_tracker_week_rollover_flagged():
    tr = gps.Tracker()
    old = time.time() - 1024 * 7 * 86400       # alter Empfänger: 19,6 Jahre zurück
    for ln in epoch_lines(old):
        tr.feed(ln)
    assert tr.state.bad_date and tr.state.offset is None and not tr.state.time_trusted()


def test_status_text():
    st = gps.GpsState(connected=True, fix=3, used=8, lat=49.19, lon=11.02, grid="JN59me")
    assert gps.status_text(st) == ("GPS JN59me · 8 Sat", "ok")
    assert gps.status_text(gps.GpsState(connected=True, view=4))[1] == "wait"
    assert gps.status_text(gps.GpsState(error_kind="missing"))[1] == "off"
    assert gps.status_text(gps.GpsState(error_kind="access"))[1] == "error"


# --------------------------------------------------------------------------- Geräte
def fake_tree(tmp_path, devices):
    """devices: [(tty, vid, pid, manufacturer, product, serial, by_id)]"""
    dev, sysr = tmp_path / "dev", tmp_path / "sys"
    (dev / "serial" / "by-id").mkdir(parents=True)
    (sysr / "class" / "tty").mkdir(parents=True)
    for n, (ttyn, vid, pid, man, prod, ser, byid) in enumerate(devices):
        (dev / ttyn).write_text("")
        usb = sysr / "devices" / f"usb{n}" / "1-1"
        intf = usb / "1-1:1.0"
        (intf / ttyn).mkdir(parents=True)
        for f, v in (("idVendor", vid), ("idProduct", pid), ("manufacturer", man),
                     ("product", prod), ("serial", ser)):
            if v:
                (usb / f).write_text(v + "\n")
        (sysr / "class" / "tty" / ttyn).mkdir()
        os.symlink(intf, sysr / "class" / "tty" / ttyn / "device")
        if byid:
            os.symlink(dev / ttyn, dev / "serial" / "by-id" / byid)
    return str(dev), str(sysr)


def test_scan_and_classify(tmp_path):
    dev, sysr = fake_tree(tmp_path, [
        ("ttyACM0", "1546", "01a7", "u-blox AG - www.u-blox.com", "u-blox 7 - GPS/GNSS Receiver",
         "", "usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00"),
        ("ttyUSB0", "10c4", "ea60", "Silicon Labs", "CP2102 USB to UART Bridge Controller",
         "IC-7300 03001234", "usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_IC-7300"
         "_03001234-if00-port0"),
        ("ttyUSB1", "067b", "2303", "Prolific Technology Inc.", "USB-Serial Controller", "",
         ""),
        ("ttyACM1", "1234", "5678", "Noname", "GNSS Mouse", "", ""),
    ])
    ports = {os.path.basename(p.path): p for p in gps.scan(dev, sysr)}
    assert ports["ttyACM0"].kind == "gps" and ports["ttyACM0"].key.startswith("usb-u-blox")
    assert "u-blox" in ports["ttyACM0"].label and "ttyACM0" in ports["ttyACM0"].label
    assert ports["ttyUSB0"].kind == "adapter"          # Funkgerät-Chip: nie von selbst
    assert ports["ttyUSB1"].kind == "adapter" and ports["ttyUSB1"].key == "usb-067b:2303"
    assert ports["ttyACM1"].kind == "gps"              # „GNSS“ im Namen
    # vom Nutzer geprüft → gilt als GPS
    again = {os.path.basename(p.path): p for p in gps.scan(dev, sysr, verified=["usb-067b:2303"])}
    assert again["ttyUSB1"].kind == "gps"


def test_profile_ports_never_used(tmp_path):
    dev, sysr = fake_tree(tmp_path, [("ttyACM0", "1546", "01a8", "u-blox", "u-blox 8", "", "x")])
    p = gps.scan(dev, sysr)[0]
    cfg = {"rig_profiles": [{"device": p.path}], "rotor": {}}
    assert gps.is_profile_port(p.path, cfg)
    assert gps.auto_port({"ignored": []}, [p], blocked=lambda x: gps.is_profile_port(x, cfg)) is None
    assert gps.auto_port({"ignored": []}, [p]) is p
    assert gps.auto_port({"ignored": [p.key]}, [p]) is None


def test_source_from_cfg(tmp_path):
    dev, sysr = fake_tree(tmp_path, [("ttyACM0", "1546", "01a7", "u-blox", "u-blox 7", "", "ub7")])
    ports = gps.scan(dev, sysr)
    g = gps.gps_settings({})
    assert g["source"] == "auto" and g["enabled"] is False and g["ignored"] == []
    assert gps.source_from_cfg(g, ports, gpsd=True).kind == "gpsd"
    s = gps.source_from_cfg(g, ports, gpsd=False)
    assert s.kind == "serial" and s.key == "ub7" and s.known_gps
    assert gps.source_from_cfg(dict(g, source="serial", device="weg", label="Alt"), [],
                               gpsd=True).label == "Alt"       # gemerkt, nicht eingesteckt
    assert gps.source_from_cfg(dict(g, ignored=["ub7"]), ports, gpsd=False) is None
    s = gps.source_from_cfg(dict(g, path="/dev/ttyS0", baud=4800), ports, gpsd=False)
    assert s.path == "/dev/ttyS0" and s.baud == 4800 and not s.known_gps


# --------------------------------------------------------------------------- echtes Lesen
class FakeGps:
    """Pseudo-Terminal, das jede halbe Sekunde einen Satz-Block schickt."""

    def __init__(self, shift: float = 0.0):
        self.m, self.s = os.openpty()
        tty.setraw(self.s)
        self.path = os.ttyname(self.s)
        self.shift = shift
        self.run = True
        self.th = threading.Thread(target=self._feed, daemon=True)
        self.th.start()

    def _feed(self):
        while self.run:
            for ln in epoch_lines(time.time() + self.shift):
                try:
                    os.write(self.m, ln.encode())
                except OSError:
                    return
            time.sleep(0.5)

    def close(self):
        self.run = False
        self.th.join(2)
        for fd in (self.m, self.s):
            try:
                os.close(fd)
            except OSError:
                pass


def wait_for(cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def test_worker_reads_pty_and_notices_unplug():
    fake = FakeGps()
    w = gps.GpsWorker(gps.Source("serial", path=fake.path, label="Test", known_gps=False),
                      retry=0.2)
    w.start()
    try:
        assert wait_for(lambda: w.snapshot().has_fix)
        st = w.snapshot()
        assert st.grid == "JN59me" and st.baud == 9600 and st.source == "Test" and st.used == 9
        fake.close()                                   # abgezogen
        assert wait_for(lambda: not w.snapshot().connected, 12)
    finally:
        w.stop()
        fake.close()


def test_worker_missing_and_blocked(tmp_path):
    w = gps.GpsWorker(gps.Source("serial", key="gibtsnicht"), scan_fn=lambda: [], retry=0.1)
    w.start()
    assert wait_for(lambda: w.snapshot().error_kind == "missing", 3)
    w.stop()
    f = tmp_path / "ttyUSB0"
    f.write_text("")
    w = gps.GpsWorker(gps.Source("serial", path=str(f)), retry=0.1, blocked=lambda p: True)
    w.start()
    assert wait_for(lambda: w.snapshot().error_kind == "blocked", 3)
    w.stop()


def test_listen_never_writes_and_gives_up():
    m, s = os.openpty()
    tty.setraw(s)
    path = os.ttyname(s)
    try:
        assert gps.listen(path, [9600], listen_s=0.4) is None
        os.set_blocking(m, False)
        with pytest.raises(BlockingIOError):
            os.read(m, 100)                            # nichts ans „Gerät“ geschickt
    finally:
        os.close(m)
        os.close(s)


def test_open_read_is_read_only():
    m, s = os.openpty()
    path = os.ttyname(s)
    fd = gps.open_read(path, 4800)
    try:
        with pytest.raises(OSError):
            os.write(fd, b"x")
    finally:
        os.close(fd)
        os.close(m)
        os.close(s)


def test_gpsd_source():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    addr = srv.getsockname()
    got = {}

    def serve():
        c, _ = srv.accept()
        got["watch"] = c.recv(200)
        try:
            for _ in range(6):
                for ln in epoch_lines(time.time()):
                    c.sendall(ln.encode())
                time.sleep(0.3)
        except OSError:
            pass                                   # GoGoHam hat schon aufgelegt
        c.close()
    th = threading.Thread(target=serve, daemon=True)
    th.start()
    w = gps.GpsWorker(gps.Source("gpsd", label="gpsd"), gpsd_addr=addr, retry=5)
    w.start()
    try:
        assert wait_for(lambda: w.snapshot().has_fix)
        assert w.snapshot().source == "gpsd"
        assert b'"nmea":true' in got["watch"]
    finally:
        w.stop()
        srv.close()
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    assert not gps.gpsd_available(("127.0.0.1", port))


# --------------------------------------------------------------------------- Freigabe
def test_rule_file():
    text = permissions.rule_text()
    assert 'TAG+="uaccess"' in text and 'KERNEL=="ttyUSB[0-9]*|ttyACM[0-9]*"' in text
    assert 'ENV{ID_MM_DEVICE_IGNORE}="1"' in text
    if shutil.which("udevadm"):
        r = subprocess.run(["udevadm", "verify", str(ROOT / "gogoham" / "assets" /
                                                     permissions.RULE_NAME)],
                           capture_output=True, text=True)
        if "Unknown command" not in r.stderr and "invalid" not in r.stderr.lower():
            assert r.returncode == 0, r.stdout + r.stderr


def test_rule_installed_and_command(tmp_path):
    assert not permissions.rule_installed([str(tmp_path)])
    (tmp_path / permissions.RULE_NAME).write_text("x")
    assert permissions.rule_installed([str(tmp_path)])
    cmd = permissions.rule_command("REGEL")
    assert cmd[:3] == ["pkexec", "/bin/sh", "-c"] and cmd[-1] == "REGEL"
    assert "REGEL" not in cmd[3]                       # Inhalt als Argument, nicht im Skript
    assert permissions.RULE_TARGET in cmd[3] and "udevadm trigger" in cmd[3]
    assert not permissions.uaccess_supported(seats=str(tmp_path / "nichts"))


def test_rule_script_writes_file(tmp_path):
    """Das Skript wirklich laufen lassen – in einen Ersatzordner, udevadm als Attrappe."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "udevadm").write_text("#!/bin/sh\necho \"$@\" >> " + str(tmp_path / "calls") + "\n")
    (bin_ / "udevadm").chmod(0o755)
    target = tmp_path / "etc" / "udev" / "rules.d"
    script = permissions.RULE_SCRIPT.replace("/etc/udev/rules.d", str(target))
    r = subprocess.run(["/bin/sh", "-c", script, "sh", permissions.rule_text()],
                       env={"PATH": f"{bin_}:/usr/bin:/bin"}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (target / permissions.RULE_NAME).read_text() == permissions.rule_text()
    calls = (tmp_path / "calls").read_text()
    assert "control --reload-rules" in calls and "--sysname-match=ttyUSB*" in calls


def test_packages_install_rule():
    rel = "gogoham/assets/70-gogoham.rules"
    assert rel in (ROOT / "packaging/obs/debian.rules").read_text()
    spec = (ROOT / "packaging/obs/gogoham.spec").read_text()
    assert rel in spec and "/udev/rules.d/70-gogoham.rules" in spec.split("%files")[1]
    assert rel in (ROOT / "packaging/obs/PKGBUILD").read_text()
    assert "70-gogoham.rules" in (ROOT / "install.sh").read_text()


# --------------------------------------------------------------------------- Hauptfenster
SCRIPT = r'''
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[1] + "/tests")
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from test_gps_01025 import FakeGps
from gogoham import config as cfgmod, gps, station
fake = FakeGps(shift=120.0)                 # GPS-Zeit 2 Minuten weiter: PC-Uhr geht nach
cfg = cfgmod.load(); cfg.update(rig_enabled=False, wsjtx_enabled=False, rules_auto_update=False,
                                gps={"enabled": True, "source": "serial", "path": fake.path})
cfgmod.save(cfg)
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui import main_window, gps_watch
main_window.MainWindow._welcome = lambda self: None
main_window.MainWindow._ask_scp = lambda self, *a, **k: None
main_window.MainWindow._start_daily_update = lambda self, wait=10.0: None
gps_watch.GRID_STABLE_S = 0.5
gps.GpsState.time_trusted = lambda self, now=None: self.has_fix and self.offset is not None
asked = []
def question(parent, title, text, *a, **k):
    asked.append(title)
    asked.append(text)
    return QMessageBox.StandardButton.Yes
QMessageBox.question = staticmethod(question)
station.clock_command = lambda off: ["/bin/sh", "-c", "exit 0"]
p = Path(sys.argv[2]) / "log.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="cq-ww-ssb", mycall="DL1ABC", my_grid="JN58aa")); db.close()
w = main_window.MainWindow(); w.open_log(str(p)); w.show()
msgs = []
_show = w.statusBar().showMessage
w.statusBar().showMessage = lambda text, *a, **k: (msgs.append(text), _show(text, *a, **k))
end = time.monotonic() + 15
while time.monotonic() < end and not (w.meta.get("my_grid") == "JN59me" and any("PC-Uhr" in m for m in msgs)):
    app.processEvents(); w.gpsw._next_tick = 0; w.gpsw.tick(); time.sleep(0.05)
st = w.gpsw.snapshot()
out = {"label": w.gpsw.label.text(), "grid": w.meta.get("my_grid"), "asked": asked,
       "home": w._home_pos(), "offset": st.offset, "msg": " | ".join(msgs)}
from gogoham.gui.dialogs import SettingsDialog
d = SettingsDialog(w.cfg, w, start="gps", actions={"gps_watch": w.gpsw}, check_apps=False)
d.gps_page.refresh()
out["page"] = d.gps_page.live.text()
out["key"] = d.current_key()
d.reject()
w.close(); fake.close()
print("RESULT " + json.dumps(out))
'''


def test_gps_in_main_window(tmp_path):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    (cfg / "gogoham").mkdir(parents=True)
    (data / "gogoham").mkdir(parents=True)
    logs.mkdir()
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(ROOT), str(logs),
                        str(HERE / "cty_sample.dat")],
                       capture_output=True, text=True, env=env, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert "JN59me" in o["label"]
    assert o["grid"] == "JN59me"                       # Locator vom GPS übernommen
    assert "Locator vom GPS" in o["asked"] and "Uhrzeit vom GPS" in o["asked"]
    assert abs(o["home"][0] - 49.19) < 0.01            # Karte: Standort vom GPS
    import re
    assert any(re.search(r"geht (11\d,\d Sekunden|2 Minuten) nach", t) for t in o["asked"])
    assert o["offset"] is None                         # nach dem Stellen: neu messen
    assert "PC-Uhr nach GPS gestellt" in o["msg"]
    assert o["key"] == "gps" and "JN59me" in o["page"]
