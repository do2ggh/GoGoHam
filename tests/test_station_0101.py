"""0.10.1: Stationslog auch ohne Router (IPv6-Link-Local), Netzwerk-Check, Uhrzeit-Abgleich,
USB-Berechtigung."""

import json
import os
import socket

import pytest

from gogoham import permissions
from gogoham import station as st
from gogoham.db import LogDB
from test_station_010 import free_port, wait_for


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    monkeypatch.setattr(st, "KDF_ROUNDS", 1000)
    # nie auf dem echten Anschluss rufen – ein laufendes GoGoHam im Heimnetz würde sonst fragen
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("", 0))
    monkeypatch.setattr(st, "UDP_PORT", s.getsockname()[1])
    s.close()


def own_link_local():
    for s in st.network_state():
        if s["up"] and s["ll6"] and s["kind"] in ("cable", "wifi"):
            return s["ll6"][0], s["name"]
    return None


def test_find_over_ipv6_only(monkeypatch):
    """Ohne IPv4-Rufe (wie am Switch ohne Router): der Ruf kommt über IPv6-Multicast an."""
    if not st.ipv6_ok() or own_link_local() is None:
        pytest.skip("kein Netzwerkanschluss mit IPv6-Link-Local")
    monkeypatch.setattr(st, "UDP_PORT", free_port())
    monkeypatch.setattr(st, "BEACON_EVERY", 0.2)
    monkeypatch.setattr(st, "beacon_targets", lambda: [])
    d = st.Discovery()
    d.start()
    b = st.Beacon({"log_id": "v6only", "station": "DL0ABC", "port": 4711})
    b.start()
    try:
        ok = wait_for(lambda: "v6only" in d.found(), timeout=5)
        if not ok and os.environ.get("CI"):
            pytest.skip("IPv6-Multicast in dieser Umgebung nicht verfügbar")
        assert ok
        f = d.found()["v6only"]
        assert f["addr"].lower().startswith("fe80") and "%" in f["addr"]
        assert f["addrs"][0] == (f["addr"], 4711)
    finally:
        b.stop()
        d.stop()


def test_connect_over_link_local(tmp_path):
    ll = own_link_local()
    if ll is None:
        pytest.skip("kein Netzwerkanschluss mit IPv6-Link-Local")
    key = st.password_key("geheim", "ll")
    db = LogDB(tmp_path / "h.ggh")
    db.set_meta({"contest": "cqww-cw", "mycall": "DL0ABC"})
    server = st.HostServer({"log_id": "ll", "station": "DL0ABC"}, key, port=free_port())
    host = st.HostSync(db, server, "Platz 1")
    try:
        addr = f"{ll[0]}%{ll[1]}"
        import threading
        res = {}

        def go():
            try:
                res["meta"] = st.probe(addr, server.port, key, {"t": "join", "probe": True})
            except Exception as e:  # noqa: BLE001
                res["err"] = e
        th = threading.Thread(target=go)
        th.start()
        assert wait_for(lambda: not th.is_alive(), timeout=8, tick=host.process)
        assert res.get("meta", {}).get("mycall") == "DL0ABC", res
        # IPv4 geht über denselben Anschluss weiterhin
        assert st.ask_info("127.0.0.1", server.port)["log_id"] == "ll"
    finally:
        server.stop()


IP_JSON = json.dumps([
    {"ifname": "lo", "flags": ["UP", "LOWER_UP"], "addr_info": []},
    {"ifname": "enp5s0", "flags": ["UP", "LOWER_UP"], "operstate": "UP", "addr_info": [
        {"family": "inet6", "local": "fe80::1", "scope": "link"}]},
    {"ifname": "eno1", "flags": ["NO-CARRIER", "UP"], "operstate": "DOWN", "addr_info": []},
    {"ifname": "eno2", "flags": ["UP", "LOWER_UP"], "operstate": "UP", "addr_info": []},
    {"ifname": "wlan0", "flags": ["UP", "LOWER_UP"], "operstate": "UP", "addr_info": [
        {"family": "inet", "local": "192.168.1.7", "scope": "global"}]},
    {"ifname": "docker0", "flags": ["UP", "LOWER_UP"], "addr_info": [
        {"family": "inet", "local": "172.17.0.1"}]},
    {"ifname": "wg0", "flags": ["UP", "LOWER_UP"], "operstate": "UNKNOWN", "addr_info": []},
])


def test_network_summary_in_plain_words():
    state = st.network_state(run=lambda: IP_JSON)
    names = [s["name"] for s in state]
    assert "lo" not in names and "docker0" not in names
    lines, broken = st.network_summary(state)
    text = "\n".join(lines)
    assert "Kabel (enp5s0): ohne Router – Direktverbindung" in text
    assert "WLAN (wlan0): im Netz mit Router – 192.168.1.7" in text
    assert "Kabel (eno2): verbunden, aber der Rechner hat dort keine Adresse" in text
    assert "eno1" not in text                                   # kein Kabel drin
    assert "VPN eingeschaltet (wg0)" in text
    assert broken["name"] == "eno2"
    lines, broken = st.network_summary([])
    assert "Keine Netzwerkverbindung" in lines[0] and broken is None


def test_clock_offset_measurement(monkeypatch):
    c = st.PlaceClient(b"k" * 32, lambda: [], dict)
    now = [1000.2]
    monkeypatch.setattr(st.time, "time", lambda: now[0])
    c._clock({"t0": 1000.0, "th": 1005.1})            # Hauptplatz 5 s voraus, Laufzeit 0,2 s
    assert c.clock_offset == pytest.approx(5.0) and c.clock_rtt == pytest.approx(0.2)
    now[0] = 1013.0
    c._clock({"t0": 1010.0, "th": 1000.0})             # 3 s Laufzeit: unbrauchbar
    assert c.clock_offset == pytest.approx(5.0)
    cmd = st.clock_command(-2.5)
    assert cmd[:3] == ["pkexec", "sh", "-c"] and cmd[-1] == "-2.500"


def test_host_answers_time_request(tmp_path):
    key = st.password_key("geheim", "t")
    db = LogDB(tmp_path / "h.ggh")
    server = st.HostServer({"log_id": "t"}, key, port=free_port())
    host = st.HostSync(db, server, "Platz 1")
    c = st.PlaceClient(key, lambda: [("127.0.0.1", server.port)],
                       lambda: {"t": "join", "place": "P2", "last_seq": 0})
    c.start()
    try:
        assert wait_for(lambda: c.clock_offset is not None, timeout=8, tick=host.process)
        assert abs(c.clock_offset) < 0.5                 # gleicher Rechner, gleiche Uhr
        assert c.via == "127.0.0.1"
    finally:
        c.stop()
        server.stop()


def test_permission_command_without_dollar(monkeypatch):
    monkeypatch.setattr(permissions, "user", lambda: "franz")
    assert permissions.command("uucp") == "sudo usermod -aG uucp franz"
    assert permissions.fix_command("dialout") == ["pkexec", "usermod", "-aG", "dialout", "franz"]
    from gogoham import hamlib
    monkeypatch.setattr(permissions, "member_not_active", lambda g: False)
    assert "$USER" not in hamlib.access_hint("/dev/null")
    assert "sudo usermod -aG" in hamlib.access_hint("/dev/null")


class FakeNM:
    """Attrappe für nmcli: zwei Kabelverbindungen, eine schon vorbereitet, eine mit fester
    Adresse (die bleibt unangetastet)."""

    def __init__(self, allowed=True):
        self.ll = {"Kabelgebundene Verbindung 1": "0", "Büro": "4", "Fest": "0", "Alt": "4"}
        self.to = {"Kabelgebundene Verbindung 1": "0", "Büro": "2147483647", "Fest": "0",
                   "Alt": "0"}
        self.method = {"Kabelgebundene Verbindung 1": "auto", "Büro": "auto", "Fest": "manual",
                       "Alt": "auto"}
        self.allowed = allowed
        self.calls = []

    def __call__(self, a):
        import types
        self.calls.append(a)
        ok = lambda out="": types.SimpleNamespace(returncode=0, stdout=out, stderr="")  # noqa
        if a[:5] == ["nmcli", "-t", "-f", "NAME,TYPE", "connection"]:
            return ok("Franz:802-11-wireless\n" + "".join(
                f"{n}:802-3-ethernet\n" for n in self.ll) + "lo:loopback\n")
        if a[1:3] == ["-g", "ipv4.method,ipv4.link-local,ipv4.dhcp-timeout"]:
            n = a[-1]
            return ok(f"{self.method[n]}\n{self.ll[n]}\n{self.to[n]}\n")
        if a[1:3] == ["connection", "modify"] or a[2:4] == ["connection", "modify"]:
            if a[0] == "nmcli" and not self.allowed:
                return types.SimpleNamespace(returncode=1, stdout="", stderr="Insufficient")
            n = a[a.index("modify") + 1]
            self.ll[n], self.to[n] = "4", "2147483647"
            return ok()
        return ok()


def test_prepare_cable_for_no_router():
    nm = FakeNM()
    run = lambda a: nm(a)  # noqa: E731
    # „Alt“ = nur link-local (Vorabversion) – reicht nicht, wird nachgezogen
    assert st.cable_profiles(run) == [("Kabelgebundene Verbindung 1", False), ("Büro", True),
                                      ("Alt", False)]
    assert st.cable_prepared(run) is False
    assert st.prepare_cable("enp5s0", run=run)
    assert st.cable_prepared(run) is True
    assert ["nmcli", "connection", "modify", "Kabelgebundene Verbindung 1", "ipv4.link-local",
            "fallback", "ipv4.dhcp-timeout", "2147483647"] in nm.calls
    assert nm.to["Alt"] == "2147483647"
    assert ["nmcli", "device", "connect", "enp5s0"] in nm.calls
    assert nm.ll["Fest"] == "0"                       # feste Adresse: nicht anfassen
    # ohne Berechtigung (z. B. per ssh): mit pkexec
    nm2 = FakeNM(allowed=False)
    used = []
    assert st.prepare_cable(None, run=lambda a: nm2(a),
                            pkexec_run=lambda a: (used.append(a), nm2(a[1:]) if False else
                                                  nm2(["pkexec"] + a[1:]))[1])
    assert used and used[0][:2] == ["pkexec", "nmcli"]
    assert st.cable_prepared(lambda a: None) is None   # kein NetworkManager
