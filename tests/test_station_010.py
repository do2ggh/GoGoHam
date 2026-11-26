"""0.10: Stationslog mit mehreren Plätzen im Netzwerk – Baustein station.py ohne Qt."""

import socket
import time

import pytest

from gogoham import station as st
from gogoham.contests import Qso
from gogoham.db import LogDB

LOG_ID = "a1b2c3"


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    monkeypatch.setattr(st, "KDF_ROUNDS", 1000)
    # nie auf dem echten Anschluss rufen – ein laufendes GoGoHam im Heimnetz würde sonst fragen
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("", 0))
    monkeypatch.setattr(st, "UDP_PORT", s.getsockname()[1])
    s.close()


def wait_for(cond, timeout=5.0, tick=None):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if tick:
            tick()
        if cond():
            return True
        time.sleep(0.02)
    return False


def free_port():
    s = socket.socket()
    s.bind(("", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Place:
    def __init__(self, path, key, port, name):
        self.db = LogDB(path)
        self.name = name
        self.target = ("127.0.0.1", port)
        self.client = st.PlaceClient(key, lambda: self.target, self.hello)
        self.sync = st.PlaceSync(self.db, self.client)
        self.client.start()

    def hello(self):
        return {"t": "join", "place": self.name, "op": "DO2GGH",
                "last_seq": self.sync.last_seq()}

    def log(self, call, nr, t="10:00"):
        q = Qso(time=f"2026-11-28 {t}:00", call=call, band="20", mode="CW", exch_s=str(nr),
                exch_r="14", place=self.name)
        self.db.add(q)
        self.sync.put("qso", self.db.record("qso", q.uid))
        return q

    def calls(self):
        return sorted(q.call for q in self.db.all_qsos())


@pytest.fixture
def station(tmp_path):
    key = st.password_key("geheim", LOG_ID)
    hdb = LogDB(tmp_path / "host.ggh")
    hdb.set_meta({"contest": "cqww-cw", "mycall": "DL0ABC"})
    hdb.add(Qso(time="2026-11-28 09:00:00", call="W1AW", band="20", mode="CW", exch_s="1",
                exch_r="5"))
    server = st.HostServer({"log_id": LOG_ID, "station": "DL0ABC"}, key, port=free_port())
    host = st.HostSync(hdb, server, "Platz 1", "DL1AAA")
    places = []

    def make(name, k=key):
        p = Place(tmp_path / f"{name}.ggh", k, server.port, name)
        places.append(p)
        return p

    yield host, make
    for p in places:
        p.client.stop()
    server.stop()


def tick_all(host, *places):
    def f():
        host.process()
        for p in places:
            p.sync.process()
    return f


def test_crypto_roundtrip_and_tamper():
    a, b = socket.socketpair()
    key = b"k" * 32
    ca, cb = st.Channel(a, key, True), st.Channel(b, key, False)
    ca.send({"t": "x", "n": "äöü"})
    assert cb.recv() == {"t": "x", "n": "äöü"}
    # verändertes Byte -> abgelehnt
    raw = bytearray()
    ca.tx_ctr += 0
    data = b'{"t":"y"}'
    ctr = st.struct.pack(">Q", 2)
    ct = st._xor(data, st._keystream(ca.k_tx_enc, 2, len(data)))
    tag = st._mac(ca.k_tx_mac, ctr, ct)
    raw = bytearray(ctr + ct + tag)
    raw[10] ^= 1
    a.sendall(st.struct.pack(">I", len(raw)) + bytes(raw))
    with pytest.raises(ConnectionError):
        cb.recv()
    a.close()
    b.close()


def test_sync_two_places(station):
    host, make = station
    p2, p3 = make("Platz 2"), make("Platz 3")
    tick = tick_all(host, p2, p3)
    assert wait_for(lambda: p2.sync.connected and p3.sync.connected, tick=tick)
    # Stand des Hauptplatzes ist überall, Meta auch
    assert p2.calls() == ["W1AW"] and p2.db.get_meta()["mycall"] == "DL0ABC"
    assert {p["place"] for p in p3.sync.places} == {"Platz 1", "Platz 2", "Platz 3"}
    q = p2.log("JA1AAA", 2)
    assert wait_for(lambda: "JA1AAA" in p3.calls(), tick=tick)
    assert sorted(x.call for x in host.db.all_qsos()) == ["JA1AAA", "W1AW"]
    got = [x for x in p3.db.all_qsos() if x.call == "JA1AAA"][0]
    assert got.uid == q.uid and got.place == "Platz 2"
    assert wait_for(lambda: p2.db.outbox() == [], tick=tick)     # bestätigt
    # Ändern und Löschen
    q.call = "JA1AAB"
    p2.db.update(q)
    p2.sync.put("qso", p2.db.record("qso", q.uid))
    assert wait_for(lambda: "JA1AAB" in p3.calls(), tick=tick)
    p3.db.delete_record("qso", q.uid)
    p3.sync.delete("qso", q.uid)
    assert wait_for(lambda: p2.calls() == ["W1AW"] and
                    [x.call for x in host.db.all_qsos()] == ["W1AW"], tick=tick)
    # Hauptplatz loggt selbst
    hq = Qso(time="2026-11-28 10:30:00", call="VK2AA", band="15", mode="CW", exch_s="3")
    host.db.add(hq)
    host.put("qso", host.db.record("qso", hq.uid))
    assert wait_for(lambda: "VK2AA" in p2.calls() and "VK2AA" in p3.calls(), tick=tick)


def test_offline_logging_and_catch_up(station):
    host, make = station
    p2 = make("Platz 2")
    tick = tick_all(host, p2)
    assert wait_for(lambda: p2.sync.connected, tick=tick)
    real = p2.target
    p2.target = ("127.0.0.1", 1)                 # Verbindung weg, Wiederverbinden scheitert
    p2.client.ch.close()
    assert wait_for(lambda: not p2.client.connected, tick=tick)
    assert not p2.sync.connected
    p2.log("ZL1AAA", 7)                          # offline geloggt -> Warteschlange
    hq = Qso(time="2026-11-28 11:00:00", call="PY2AA", band="20", mode="CW", exch_s="8")
    host.db.add(hq)
    host.put("qso", host.db.record("qso", hq.uid))
    assert len(p2.db.outbox()) == 1
    p2.target = real
    assert wait_for(lambda: p2.sync.connected and p2.db.outbox() == [] and
                    "PY2AA" in p2.calls(), timeout=8, tick=tick)
    assert sorted(x.call for x in host.db.all_qsos()) == ["PY2AA", "W1AW", "ZL1AAA"]


def test_wrong_password(station):
    host, make = station
    bad = make("Platz 9", k=st.password_key("falsch", LOG_ID))
    res = {"d": []}

    def tick():
        res["d"] += host.process()["denied"]
        bad.sync.process()
    assert wait_for(lambda: bad.sync.denied and res["d"], tick=tick)
    assert not bad.client.connected and bad.calls() == []


def test_serials_reserved_per_place(station):
    host, make = station
    p2 = make("Platz 2")
    tick = tick_all(host, p2)
    assert wait_for(lambda: p2.sync.connected, tick=tick)
    assert host.serial() == 2                     # 1 ist schon im Log
    assert host.serial() == 2                     # unbenutzt -> dieselbe
    p2.sync.ask_serial()
    assert wait_for(lambda: p2.sync.serial_cache.get("") == 3, tick=tick)
    p2.log("JA1AAA", 3)
    assert wait_for(lambda: any(x.call == "JA1AAA" for x in host.db.all_qsos()), tick=tick)
    p2.sync.ask_serial()
    assert wait_for(lambda: p2.sync.serial_cache.get("") == 4, tick=tick)
    assert host.serial() == 2


def test_ask_info(station):
    host, _make = station
    info = st.ask_info("127.0.0.1", host.server.port)
    assert info["log_id"] == LOG_ID and info["station"] == "DL0ABC"


def test_discovery_finds_beacon(monkeypatch):
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)      # freier UDP-Anschluss
    u.bind(("", 0))
    port = u.getsockname()[1]
    u.close()
    monkeypatch.setattr(st, "UDP_PORT", port)
    monkeypatch.setattr(st, "BEACON_EVERY", 0.2)
    monkeypatch.setattr(st, "beacon_targets", lambda: ["127.0.0.1", "255.255.255.255",
                                                       st.MCAST_GROUP])
    d = st.Discovery()
    d.start()
    b = st.Beacon({"log_id": "xyz", "station": "DL0ABC", "port": 4711})
    b.start()
    try:
        assert wait_for(lambda: "xyz" in d.found(), timeout=10), \
            (getattr(d, "ok", None), b.errors, port)
        assert d.found()["xyz"]["port"] == 4711
    finally:
        b.stop()
        d.stop()
