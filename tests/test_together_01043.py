"""0.10.43: GoGoHam + GoGoHome gleichzeitig – beide bekommen geloggte QSOs (fldigi, WSJT-X)."""

import socket
import time


from gogoham import wsjtx

ADIF = "<CALL:5>DL1AB <MODE:4>RTTY <QSO_DATE:8>20261123 <TIME_ON:6>120000 <BAND:3>40m <EOR>"


def _wait(lst, n=1, t=4.0):
    end = time.monotonic() + t
    while time.monotonic() < end:
        got = []
        for li in lst:
            while not li.records.empty():
                li.got.append(li.records.get())
        if all(len(li.got) >= n for li in lst):
            return True
        time.sleep(0.05)
    return False


def _listeners(port, address="127.0.0.1", program="fldigi", n=2):
    ls = []
    for _ in range(n):
        li = wsjtx.WsjtxListener(port, address, program=program)
        li.got = []
        li.start()
        ls.append(li)
    end = time.monotonic() + 3
    while time.monotonic() < end and not all(li.sock for li in ls):
        time.sleep(0.05)
    return ls


def test_unicast_packet_reaches_both_programs():
    port = 24739
    a, b = _listeners(port)
    try:
        assert not a.error and not b.error and a.relay is not None
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(ADIF.encode(), ("127.0.0.1", port))       # wie fldigi: nur an 127.0.0.1
        assert _wait([a, b]), (a.got, b.got)
        time.sleep(0.8)
        assert len(a.got) == 1 and len(b.got) == 1           # keiner doppelt
        assert a.got[0]["CALL"] == b.got[0]["CALL"] == "DL1AB"
    finally:
        for li in (a, b):
            li.stop()


def test_single_program_still_works():
    port = 24741
    (a,) = _listeners(port, n=1)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(ADIF.encode(), ("127.0.0.1", port))
        assert _wait([a])
        time.sleep(0.6)
        assert len(a.got) == 1
    finally:
        a.stop()


def test_multicast_reaches_both_and_replies_go_to_sender():
    port = 24743
    a, b = _listeners(port, address="224.0.0.1", program="")
    try:
        assert a.relay is None and not a.error
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton("127.0.0.1"))
        s.bind(("127.0.0.1", 0))
        s.sendto(wsjtx.build_logged_adif_packet(ADIF), ("224.0.0.1", port))
        assert _wait([a, b])
        assert a.clients["WSJT-X"] == b.clients["WSJT-X"] == s.getsockname()
        s.settimeout(2)
        assert a.close_clients() == 1 and b.close_clients() == 1    # beide können antworten
        assert len({s.recvfrom(100)[0] for _ in range(2)}) == 1
    finally:
        for li in (a, b):
            li.stop()


# ------------------------------------------------------------ Regel A + C (Dienste)
from gogoham import config, extapps, rigservice  # noqa: E402

BYID = "/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_0141C8FB-if00-port0"
IC = "/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_IC-7300_03025959-if00-port0"


class Run:
    def __init__(self, active=()):
        self.calls, self.active = [], set(active)

    def __call__(self, cmd, timeout=30):
        import subprocess
        self.calls.append(cmd)
        out = ""
        if cmd[-2] in ("is-active", "is-enabled"):
            out = ("active" if cmd[-2] == "is-active" else "enabled") if cmd[-1] in self.active else "inactive"
        return subprocess.CompletedProcess(cmd, 0, out, "")


def _units(d):
    d.mkdir(parents=True, exist_ok=True)
    (d / "rigctld-4534.service").write_text(
        f"[Service]\nExecStart=/usr/bin/rigctld -m 1036 -r {BYID} -s 38400 -t 4534\n")
    (d / "rigctld-4532.service").write_text(
        f"[Service]\nExecStart=/usr/bin/rigctld -m 3073 -r {IC} -s 115200 -t 4532\n")
    dd = d / "rigctld-4532.service.d"
    dd.mkdir()
    (dd / "gogohandy.conf").write_text(
        "[Service]\nExecStart=\nExecStart=/bin/sh -c 'D=/run/user/1000/gogohandy/by-id/"
        f"{IC.rsplit('/', 1)[1]}; [ -e \"$D\" ] || D={IC}; exec /usr/bin/rigctld -m 3073 -r \"$D\" -t 4532'\n")
    (d / "gogoham-rigctld-4533.service").write_text("[Service]\nExecStart=/usr/bin/rigctld -t 4533\n")


def test_foreign_units_and_dropin(tmp_path):
    d = tmp_path / "user"
    _units(d)
    us = {u["unit"]: u for u in rigservice.foreign_units(str(d), system_dirs=())}
    assert set(us) == {"rigctld-4532.service", "rigctld-4534.service"}      # eigene nicht
    assert us["rigctld-4534.service"]["port"] == 4534
    assert any("gogohandy" in x for x in us["rigctld-4532.service"]["devices"])


def test_sync_uses_foreign_service_instead_of_second(tmp_path):
    d = tmp_path / "user"
    _units(d)
    run = Run(active={"rigctld-4534.service"})
    ft = {"name": "FT-891", "model": 1036, "device": BYID, "baud": 38400, "port": 4533,
          "service": True, "conn": "usb"}
    notes = []
    errs = rigservice.sync([ft], run=run, directory=str(d), notes=notes, system_dirs=())
    assert errs == [] and notes and "rigctld-4534.service" in notes[0]
    assert not (d / "gogoham-rigctld-4533.service").exists()      # eigener Doppel-Dienst weg
    assert ["systemctl", "--user", "disable", "--now", "gogoham-rigctld-4533.service"] in run.calls
    # fremder Dienst abgeschaltet -> GoGoHam legt seinen eigenen an (wie bisher)
    run = Run(active=())
    rigservice.sync([ft], run=run, directory=str(d), system_dirs=())
    assert (d / "gogoham-rigctld-4533.service").exists()


def test_restart_instead_of_disable(tmp_path, monkeypatch):
    run = Run()
    monkeypatch.setattr(rigservice, "owner", lambda pid, proc="/proc": {
        "kind": "user", "unit": "rigctld-4532.service", "uid": __import__("os").getuid()})
    assert rigservice.restart(5, run=run) == (True, "rigctld-4532.service")
    assert run.calls == [["systemctl", "--user", "restart", "rigctld-4532.service"]]
    d = tmp_path / "user"
    _units(d)
    assert rigservice.via_bridge({"pid": 5, "device": IC}, directory=str(d))      # Drop-in
    monkeypatch.setattr(rigservice, "owner", lambda pid, proc="/proc": {
        "kind": "system", "unit": "rigctld.service", "uid": 0})
    assert rigservice.restart(5, run=run) == (False, "")                          # Passwort nötig
    assert not rigservice.via_bridge({"pid": 5, "device": "/dev/ttyUSB0"}, directory=str(d))


def test_wsjtx_multicast_settings_and_migration(tmp_path, monkeypatch):
    want = {k: v for k, v, _l in extapps.wanted("127.0.0.1", 4532, "224.0.0.1", 2237)}
    assert want["UDPServer"] == "224.0.0.1" and want["UDPInterface"] == "lo" and want["UDPTTL"] == "1"
    assert "UDPInterface" not in {k for k, _v, _l in extapps.wanted("127.0.0.1", 4532, "127.0.0.1", 2237)}
    ini = tmp_path / "WSJT-X.ini"
    ini.write_text("[Configuration]\nUDPServer=127.0.0.1\nUDPServerPort=2237\nUDPInterface=@Invalid()\n")
    labels = [lb for lb, _old in extapps.changes(ini, "127.0.0.1", 4532, "224.0.0.1", 2237)]
    assert any("lo" in lb for lb in labels) and "" not in labels
    cfg = dict(config.DEFAULTS)
    config.migrate(cfg, {"wsjtx_address": "127.0.0.1"})
    assert cfg["wsjtx_address"] == "224.0.0.1" and cfg["wsjtx_multicast_done"]
    cfg = dict(config.DEFAULTS, wsjtx_address="192.168.1.5")
    config.migrate(cfg, {"wsjtx_address": "192.168.1.5"})
    assert cfg["wsjtx_address"] == "192.168.1.5"                     # eigene Adresse bleibt
    cfg = dict(config.DEFAULTS, wsjtx_address="127.0.0.1")
    config.migrate(cfg, {"wsjtx_address": "127.0.0.1", "wsjtx_multicast_done": True})
    assert cfg["wsjtx_address"] == "127.0.0.1"                       # nur einmal umstellen
