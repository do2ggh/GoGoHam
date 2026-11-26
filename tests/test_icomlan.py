"""0.10.30: Icom-Funkgeräte über LAN/WLAN – geprüft gegen ein nachgebautes Funkgerät."""

import json
import os
import select
import struct
import threading

import pytest

from gogoham import icomlan as il
from fake_icom import FakeIcom, wait_for


class Out:
    def __init__(self):
        self.lines = []

    def write(self, s):
        self.lines += [json.loads(x) for x in s.splitlines() if x.strip()]

    def flush(self):
        pass

    def states(self):
        return [x["state"] for x in self.lines]


class FakeSound:
    """Ersatz für die virtuelle Soundkarte: Empfang in eine Liste, Senden aus einer Pipe."""

    def __init__(self, rig_port, name):
        self.rx = []
        self.sink, self.source = il.sound_names(rig_port)
        self.tx_r, self.tx_w = os.pipe()
        os.set_blocking(self.tx_r, False)
        self.tx_fd = self.tx_r

    def open(self):
        return True

    def write_rx(self, pcm):
        self.rx.append(pcm)

    def close(self):
        for fd in (self.tx_r, self.tx_w):
            try:
                os.close(fd)
            except OSError:
                pass


def _bridge(radio, user="franz", password="geheim", seconds=8.0):
    out = Out()
    sounds = []

    def factory(port, name):
        sounds.append(FakeSound(port, name))
        return sounds[-1]

    conf = {"host": "127.0.0.1", "ctrl_port": radio.port, "user": user, "password": password,
            "audio": True, "rig_port": 45990, "model": 0}
    b = Bridge = il.Bridge(conf, out=out, sound_factory=factory)
    res = {}
    t = threading.Thread(target=lambda: res.setdefault("rc", Bridge.run(max_seconds=seconds)),
                         daemon=True)
    t.start()
    return b, out, sounds, t, res


def _read_pty(b, n, timeout=3.0):
    data = b""
    end = __import__("time").monotonic() + timeout
    while len(data) < n and __import__("time").monotonic() < end:
        r, _w, _x = select.select([b.slave], [], [], 0.05)
        if r:
            data += os.read(b.slave, 4096)
    return data


@pytest.fixture
def radio():
    r = FakeIcom()
    yield r
    r.stop()


def test_passcode_is_stable_and_limited():
    assert il.passcode("beer") == il.passcode("beer")
    assert len(il.passcode("x" * 30)) == 16
    assert il.passcode("a") != il.passcode("b")


def test_full_connection_civ_and_audio(radio):
    b, out, sounds, t, _res = _bridge(radio)
    try:
        assert wait_for(lambda: radio.civ_open), out.states()
        assert "radio" in out.states() and "authenticated" in out.states()
        assert radio.client_ports[0] and radio.client_ports[1]
        # Funkgerät -> GoGoHam (Pseudo-Terminal, dort liest rigctld)
        frame = bytes.fromhex("fefee0a20300401407" + "00fd")
        radio.send_civ(frame)
        assert _read_pty(b, len(frame)) == frame
        assert wait_for(lambda: "connected" in out.states())
        # GoGoHam (rigctld) -> Funkgerät
        cmd = bytes.fromhex("fefea2e003fd")
        os.write(b.slave, cmd)
        assert wait_for(lambda: cmd in b"".join(radio.civ_in))
        # Ton vom Funkgerät -> Soundkarte
        pcm = struct.pack("<4h", 1, -1, 300, -300) * 120
        radio.send_audio(pcm)
        assert wait_for(lambda: sounds and pcm in b"".join(sounds[0].rx))
        # Ton zum Funkgerät (20-ms-Stücke, Stille wird nicht gesendet)
        os.write(sounds[0].tx_w, bytes(il.TX_FRAME))
        tone = struct.pack("<h", 1000) * (il.TX_FRAME // 2)
        os.write(sounds[0].tx_w, tone)
        assert wait_for(lambda: b"".join(radio.audio_in) == tone), len(radio.audio_in)
    finally:
        b.stop()
        t.join(3)
    assert "stopped" in out.states()


def test_wrong_password_stops_with_message(radio):
    b, out, _s, t, res = _bridge(radio, password="falsch")
    t.join(6)
    assert res.get("rc") == 2
    assert "error-auth" in out.states()
    assert not radio.civ_open


def test_radio_busy_is_reported():
    radio = FakeIcom(busy_by="SHACK-PC")
    try:
        b, out, _s, t, _res = _bridge(radio)
        assert wait_for(lambda: "busy" in out.states())
        assert [x["text"] for x in out.lines if x["state"] == "busy"][0] == "SHACK-PC"
        assert not radio.civ_open
        b.stop()
        t.join(3)
    finally:
        radio.stop()


def test_lost_civ_packet_is_requested_again(radio):
    b, out, _s, t, _res = _bridge(radio)
    try:
        assert wait_for(lambda: radio.civ_open)
        radio.send_civ(bytes.fromhex("fefee0a2fbfd"))          # kommt an
        assert _read_pty(b, 6)
        lost = bytes.fromhex("fefee0a20300001407" + "00fd")
        radio.send_civ(lost, drop=True)                          # geht „verloren“
        after = bytes.fromhex("fefee0a2fbfd")
        radio.send_civ(after)
        got = _read_pty(b, len(lost) + len(after))
        assert radio.retransmit_requests, "keine Nachforderung"
        assert lost in got and after in got
    finally:
        b.stop()
        t.join(3)


def test_discover_finds_radio(radio):
    assert il.discover(timeout=1.0, port=radio.port, targets=["127.0.0.1"]) == ["127.0.0.1"]


def test_sound_devices_load_and_clean_up(tmp_path, monkeypatch):
    """0.10.30.1: virtuelle Soundkarte über ein Tonsystem-Backend (libpulse oder pactl)."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

    class Fake:
        def __init__(self):
            self.mods = {7: ("module-pipe-sink", "sink_name=gogoham_icom_4533_tx file=/x")}
            self.next = 100

        def load(self, module, args):
            path = [a for a in args.split() if a.startswith("file=")][0][5:]
            os.mkfifo(path)
            self.next += 1
            self.mods[self.next] = (module, args)
            return self.next

        def unload(self, idx):
            return self.mods.pop(idx, None) is not None

        def modules(self):
            return [(i, m, a) for i, (m, a) in self.mods.items()]

    fake = Fake()
    sd = il.SoundDevices(4533, "IC-9700", backend=fake)
    assert sd.open()
    assert 7 not in fake.mods                      # Rest eines alten Laufs entfernt
    kinds = sorted(m for m, _a in fake.mods.values())
    assert kinds == ["module-pipe-sink", "module-pipe-source"]
    assert any("source_name=gogoham_icom_4533_rx" in a and "GoGoHam-IC-9700-Empfang" in a
               for _m, a in fake.mods.values())
    sd.write_rx(b"\0\1" * 10)                    # niemand liest: darf nicht hängen
    sd.close()
    assert fake.mods == {}


def test_pactl_fallback_parses_output():
    from gogoham import pulse

    class R:
        def __init__(self, rc=0, out=""):
            self.returncode, self.stdout = rc, out
    calls = []

    def run(cmd, **_k):
        calls.append(cmd)
        if cmd[1] == "load-module":
            return R(0, "536870917\n")
        if cmd[1] == "list":
            return R(0, "5\tmodule-pipe-sink\tsink_name=a file=/b\n6\tmodule-x\t\n")
        return R(0, "")
    cli = pulse.PactlCli(run=run)
    assert cli.load("module-pipe-sink", "sink_name=a file=/b") == 536870917
    assert calls[0][:3] == ["pactl", "load-module", "module-pipe-sink"]
    assert cli.modules() == [(5, "module-pipe-sink", "sink_name=a file=/b"), (6, "module-x", "")]
    assert cli.unload(5)


def test_libpulse_real_sound_system(tmp_path):
    """Am echten Tonsystem (wenn vorhanden): Soundkarte anlegen, finden, wieder entfernen."""
    from gogoham import pulse
    lp = pulse.LibPulse(timeout=3)
    if not lp.available():
        pytest.skip("kein PipeWire/PulseAudio erreichbar")
    name = f"gogoham_test_{os.getpid()}"
    idx = lp.load("module-pipe-source", f"source_name={name} file={tmp_path / 'p'} "
                                        "format=s16le rate=48000 channels=1")
    assert idx is not None
    try:
        assert any(i == idx and f"source_name={name}" in a for i, _m, a in lp.modules())
    finally:
        assert lp.unload(idx)
    assert not any(f"source_name={name}" in a for _i, _m, a in lp.modules())
    assert lp.load("module-gibt-es-nicht", "") is None


@pytest.mark.skipif(not __import__("shutil").which("rigctld"), reason="Hamlib fehlt")
def test_real_rigctld_through_bridge():
    """Echter rigctld (IC-9700) über die Brücke: Frequenz lesen und setzen."""
    from gogoham.rig import RigctldClient, port_in_use
    radio = FakeIcom(answer_civ=True)
    out = Out()
    port = 45993
    conf = {"host": "127.0.0.1", "ctrl_port": radio.port, "user": "franz", "password": "geheim",
            "audio": False, "rig_port": port, "model": 3081}
    b = il.Bridge(conf, out=out, sound_factory=None)
    t = threading.Thread(target=lambda: b.run(max_seconds=30), daemon=True)
    t.start()
    try:
        assert wait_for(lambda: port_in_use("127.0.0.1", port), 15), out.states()
        c = RigctldClient("127.0.0.1", port, timeout=5)
        assert c.get_freq() == 145_000_000
        c.set_freq(14_074_000)
        assert wait_for(lambda: radio.freq == 14_074_000)
        assert c.get_freq() == 14_074_000
        c.close()
    finally:
        b.stop()
        t.join(5)
        radio.stop()
    assert "rigctld" in out.states()


DIALOG = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import hamlib, rigprofiles
hamlib.serial_ports = lambda: []
from gogoham.gui.dialogs import RigDialog
cfg = {"rig_enabled": True, "rig_autostart": True, "rig_host": "127.0.0.1", "rig_port": 4532,
       "rig_model": 0, "rig_device": "", "rig_baud": 0, "rig_extra": ""}
d = RigDialog(cfg)
d._fill_models(3081)
out = {"usb_visible": d._form.isRowVisible(d.baud), "user_visible": d._form.isRowVisible(d.net_user)}
d.conn.setCurrentIndex(d.conn.findData("icom"))
out["icom_port"] = d.net_port.value()
out["icom_user_visible"] = d._form.isRowVisible(d.net_user)
out["icom_baud_visible"] = d._form.isRowVisible(d.baud)
ok_empty = d.apply()
out["empty_msg"] = d.test_result.text()
d.net_host.setText("192.168.1.40"); d.net_user.setText("franz"); d.net_pass.setText("geheim")
out["apply"] = d.apply()
p = cfg["rig_profiles"][0]
out["prof"] = {k: p[k] for k in ("conn", "net_host", "net_port", "net_user", "start", "service")}
out["ok_empty"] = ok_empty
d.conn.setCurrentIndex(d.conn.findData("remote"))
out["remote_port"] = d.net_port.value()
d.apply()
p = cfg["rig_profiles"][0]
out["remote"] = [p["start"], p["port"], cfg["rig_host"], cfg["rig_autostart"]]
d.conn.setCurrentIndex(d.conn.findData("net"))
d.net_port.setValue(9200)
d.apply()
out["net_dev"] = cfg["rig_device"]
print("OUT" + json.dumps(out))
'''


def test_settings_page_network(tmp_path):
    import subprocess
    import sys
    import textwrap
    from pathlib import Path
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HOME=str(tmp_path),
               XDG_CONFIG_HOME=str(tmp_path / "cfg"), XDG_DATA_HOME=str(tmp_path / "data"))
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(DIALOG),
                        str(Path(__file__).parent.parent)], capture_output=True, text=True,
                       env=env, timeout=60)
    lines = [ln[3:] for ln in r.stdout.splitlines() if ln.startswith("OUT")]
    assert lines, r.stderr[-2000:]
    o = json.loads(lines[-1])
    assert o["usb_visible"] and not o["user_visible"]
    assert o["icom_port"] == 50001 and o["icom_user_visible"] and not o["icom_baud_visible"]
    assert o["ok_empty"] is False and o["empty_msg"]
    assert o["apply"] is True
    assert o["prof"] == {"conn": "icom", "net_host": "192.168.1.40", "net_port": 50001,
                         "net_user": "franz", "start": True, "service": False}
    assert o["remote_port"] == 4532 and o["remote"] == [False, 4532, "192.168.1.40", False]
    assert o["net_dev"] == "192.168.1.40:9200"


def test_profile_device_and_sound_names():
    from gogoham import rigaudio, rigprofiles
    p = {"conn": "icom", "port": 4533, "net_audio": True}
    assert rigaudio.for_profile(p) == ("gogoham_icom_4533_tx", "gogoham_icom_4533_rx", "profile")
    assert rigprofiles.device({"conn": "net", "net_host": "10.0.0.5", "net_port": 9200}) == \
        "10.0.0.5:9200"
    assert rigprofiles.device({"conn": "usb", "device": "/dev/ttyUSB0"}) == "/dev/ttyUSB0"
    # Steuerleitungen nur am Kabel
    assert "dtr_state" not in rigprofiles.full_extra({"conn": "icom", "lines": "both"})
    assert "dtr_state" in rigprofiles.full_extra({"conn": "usb", "lines": "both"})


def test_netscan_finds_only_real_rigctld():
    import socket as so
    from gogoham import netscan
    srv = so.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    port = srv.getsockname()[1]
    try:
        found = netscan.find_rigctld(["127.0.0.1"], ports=(port, port + 1),
                                     query=lambda h, p: 3081 if p == port else 0)
        assert found == [("127.0.0.1", port, "IC-9700")]
        assert netscan.find_rigctld(["127.0.0.1"], ports=(port,), query=lambda h, p: 0) == []
    finally:
        srv.close()
    assert netscan.candidates("8.8.8.8") == []
    assert len(netscan.candidates("192.168.1.7")) == 253


MAIN = r'''
import json, os, sys, threading, time
sys.path[:0] = [sys.argv[1], os.path.join(sys.argv[1], "tests")]
from fake_icom import FakeIcom
radio = FakeIcom(answer_civ=True)
cfg_dir = os.path.join(os.environ["XDG_CONFIG_HOME"], "gogoham")
os.makedirs(cfg_dir, exist_ok=True)
prof = {"slot": 0, "name": "IC-9700 Netz", "model": 3081, "port": int(sys.argv[2]),
        "conn": "icom", "net_host": "127.0.0.1", "net_port": radio.port, "net_user": "franz",
        "net_pass": "geheim", "net_audio": False, "start": True, "service": False}
json.dump({"rig_enabled": True, "rig_profiles": [prof], "rig_profile": 0, "wsjtx_enabled": False,
           "livescore_enabled": False, "last_log": "", "rules_auto_update": False,
           "version_check": False}, open(os.path.join(cfg_dir, "config.json"), "w"))
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.exec = lambda self: 0
from gogoham.gui.main_window import MainWindow
w = MainWindow()
w.start_rig()
end = time.time() + 25
freq = 0
while time.time() < end:
    app.processEvents()
    if w.rig is not None:
        st = w.rig.snapshot()
        if st.connected and st.freq:
            freq = st.freq
            break
    time.sleep(0.05)
for _ in range(20):
    app.processEvents(); time.sleep(0.05)
msg = w.statusBar().currentMessage()
w.stop_rig()
radio.stop()
print("OUT" + json.dumps({"freq": freq, "bridge_gone": w.icom_bridge is None, "msg": msg}), flush=True)
os._exit(0)
'''


@pytest.mark.skipif(not __import__("shutil").which("rigctld"), reason="Hamlib fehlt")
def test_main_window_uses_icom_over_network(tmp_path):
    import subprocess
    import sys
    import textwrap
    from pathlib import Path
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HOME=str(tmp_path),
               XDG_CONFIG_HOME=str(tmp_path / "cfg"), XDG_DATA_HOME=str(tmp_path / "data"),
               XDG_RUNTIME_DIR=str(tmp_path / "run"))
    os.makedirs(tmp_path / "run", mode=0o700)
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(MAIN),
                        str(Path(__file__).parent.parent), "45995"], capture_output=True,
                       text=True, env=env, timeout=90)
    lines = [ln[3:] for ln in r.stdout.splitlines() if ln.startswith("OUT")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1])
    assert o["freq"] == 145_000_000, o
    assert o["bridge_gone"]


@pytest.mark.skipif(not __import__("shutil").which("rigctld"), reason="Hamlib fehlt")
def test_connection_test_button_over_network():
    from gogoham import hamlib
    radio = FakeIcom(answer_civ=True)
    try:
        prof = {"model": 3081, "port": 45997, "conn": "icom", "net_host": "127.0.0.1",
                "net_port": radio.port, "net_user": "franz", "net_pass": "geheim"}
        res = hamlib.test_profile(prof)
        assert res.ok, res.text
        assert "145" in res.text
        bad = hamlib.test_profile(dict(prof, net_pass="falsch"))
        assert not bad.ok and "Passwort" in bad.text
    finally:
        radio.stop()


@pytest.mark.skipif(not __import__("shutil").which("rigctld"), reason="Hamlib fehlt")
def test_ptt_test_over_network_switches_back():
    """PTT-Test (nur gegen das nachgebaute Gerät): an, Rückmeldung, sicher wieder aus."""
    from gogoham import hamlib
    radio = FakeIcom(answer_civ=True)
    seen = []
    orig = radio._answer

    def spy(body):
        if body[:2] == b"\x1c\x00" and len(body) == 3:
            seen.append(body[2])
        orig(body)
    radio._answer = spy
    try:
        prof = {"model": 3081, "port": 45998, "conn": "icom", "net_host": "127.0.0.1",
                "net_port": radio.port, "net_user": "franz", "net_pass": "geheim", "start": True}
        res = hamlib.ptt_test(prof, seconds=0.3)
        assert res.ok, res.text
        assert seen and seen[0] == 1 and seen[-1] == 0 and radio.ptt == 0
    finally:
        radio.stop()
