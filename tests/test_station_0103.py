"""0.10.3: Fenster „Station“ – Plätze im Überblick, Warnung bei gleichem Band, Nachrichten."""

import json
import socket
import subprocess
import sys
import time

import pytest

from gogoham import speech
from gogoham import station as st
from gogoham.contests import Qso
from gogoham.db import LogDB

from test_station_010 import fast_kdf, station, tick_all, wait_for  # noqa: F401
from test_station_gui_010 import COMMON, ROOT, env_for, free_port


# ------------------------------------------------------------------ Bausteine ohne Netz
def test_place_stats_counts_and_rates():
    now = st._parse_utc("2026-11-28 12:00:00")
    qs = [Qso(time="2026-11-28 11:55:00", call="A", place="Platz 1"),     # 5 min
          Qso(time="2026-11-28 11:52:00", call="B", place="Platz 1"),     # 8 min
          Qso(time="2026-11-28 11:30:00", call="C", place="Platz 1"),     # 30 min
          Qso(time="2026-11-28 09:00:00", call="D", place="Platz 1"),     # alt
          Qso(time="2026-11-28 11:59:00", call="E", place="Laptop")]
    s = st.place_stats(qs, now)
    assert s["Platz 1"] == {"qsos": 4, "r10": 12, "r60": 3}
    assert s["Laptop"] == {"qsos": 1, "r10": 6, "r60": 1}


def test_band_conflicts_only_connected_and_shared():
    rows = [{"place": "A", "band": "20"}, {"place": "B", "band": "20"},
            {"place": "C", "band": "40"}, {"place": "D", "band": "40", "gone": "12:00"},
            {"place": "E", "band": ""}, {"place": "F", "band": ""}]
    assert st.band_conflicts(rows) == {"20": {"A", "B"}}


def test_make_chat_cleans_and_limits():
    m = st.make_chat("Platz 1", "", "  Kaffee\nist   fertig  ")
    assert m["text"] == "Kaffee ist fertig" and m["to"] == "" and len(m["mid"]) == 32
    assert len(st.make_chat("x", "", "a" * 900)["text"]) == st.CHAT_MAX


def test_chats_stored_locally(tmp_path):
    db = LogDB(tmp_path / "l.ggh")
    a = st.make_chat("Ich", "Laptop", "Hallo", when="2026-11-28 10:00:00")
    b = st.make_chat("Laptop", "", "Servus", when="2026-11-28 10:01:00")
    db.chat_add(a, "out")
    db.chat_add(b, "in")
    db.chat_add(b, "in")                                # doppelt = einmal
    assert [(c["text"], c["state"]) for c in db.chats()] == [("Hallo", "out"), ("Servus", "in")]
    db.chat_fail_pending()
    assert db.chats()[0]["state"] == "fail"
    db.chat_state(a["mid"], "ok")
    assert db.chats()[0]["state"] == "ok"
    assert db.all_records() == [] or all(k != "chat" for k, _d in db.all_records())


def test_new_announcements_off_by_default():
    class Sp:
        ok = True
        said = []

        def say(self, t):
            self.said.append(t)

    cfg = {"announce_enabled": True}
    a = speech.Announcer(cfg, Sp())
    assert {"band_busy", "chat"} <= set(speech.EVENTS)
    a.band_busy("20")
    a.chat("Laptop", "Hallo")
    assert Sp.said == []
    cfg["announce_events"] = {"band_busy": True, "chat": True}
    a.band_busy("20")
    a.chat("Laptop", "Hallo")
    assert Sp.said == ["Band belegt: 20 Meter", "Nachricht von Laptop: Hallo"]


# ------------------------------------------------------------------ übers Netz (ohne Qt)
def test_status_and_chat_routing(station):
    host, make = station
    a, b = make("Platz 2"), make("Platz 3")
    t = tick_all(host, a, b)
    assert wait_for(lambda: a.sync.synced and b.sync.synced, tick=t)
    assert host.set_own(op="DL1AAA", band="20", freq=14025000, mode="CW", tx="0")
    assert not host.set_own(op="DL1AAA", band="20", freq=14026000, mode="CW", tx="0")
    host.broadcast_places()
    a.sync.status(op="DO2GGH", band="20", freq=14030000, mode="CW", tx="1")
    assert wait_for(lambda: any(p.get("band") == "20" and p["place"] == "Platz 2"
                                for p in b.sync.places), tick=t)
    first = b.sync.places[0]
    assert first["host"] and first["place"] == "Platz 1" and first["band"] == "20"
    assert st.band_conflicts(b.sync.places) == {"20": {"Platz 1", "Platz 2"}}

    got_host, got_b, states_a = [], [], []

    def t2():
        got_host.extend(host.process()["chats"])
        r = a.sync.process()
        states_a.extend(r["chat_states"])
        got_b.extend(b.sync.process()["chats"])

    m, ok = a.sync.send_chat("Platz 2", "", "an alle")          # an alle
    assert ok is None
    assert wait_for(lambda: got_host and got_b and states_a, tick=t2)
    assert got_host[0]["text"] == got_b[0]["text"] == "an alle"
    assert got_b[0]["from"] == "Platz 2" and states_a == [(m["mid"], True)]
    got_host.clear(), got_b.clear(), states_a.clear()
    m, _ = a.sync.send_chat("Platz 2", "Platz 3", "nur an 3")      # an einen Platz
    assert wait_for(lambda: got_b and states_a, tick=t2)
    assert got_host == [] and states_a == [(m["mid"], True)]
    states_a.clear()
    m, _ = a.sync.send_chat("Platz 2", "Gibtsnicht", "?")
    assert wait_for(lambda: states_a, tick=t2)
    assert states_a == [(m["mid"], False)]
    m, ok = host.send_chat("Platz 3", "vom Hauptplatz")
    assert ok
    got_b.clear()
    assert wait_for(lambda: got_b, tick=t2) and got_b[0]["from"] == "Platz 1"
    assert host.send_chat("Gibtsnicht", "x")[1] is False
    a.client.stop()
    assert wait_for(lambda: not a.sync.connected, tick=t2)
    assert a.sync.send_chat("Platz 2", "", "weg")[1] is False


# ------------------------------------------------------------------ echtes Programm (Qt)
HOST = COMMON + r'''
from pathlib import Path
w = main_window.MainWindow(); w.show()
p = Path(sys.argv[2]) / "station.ggh"
meta = dict(DEFAULT_META, contest="cqww-cw", mycall="DL0ABC", cat_operator="MULTI-OP",
            cat_transmitter="ONE")
meta = w.station.new_host_meta(meta, "geheim")
db = LogDB(p); db.set_meta(meta); db.close()
w.cfg["station_operator"] = "DL1AAA"; w.cfg["station_place_name"] = "Platz 1"
w.cfg["station_cable_asked"] = 9
msgs = []
orig = w.statusBar().showMessage
w.statusBar().showMessage = lambda t, *a, **k: (msgs.append(t), orig(t, *a, **k))
w.open_log(str(p)); spin(0.3)
w.cb_band.setCurrentText("20"); w.cb_mode.setCurrentText("CW")
log(w, "W1AW")
w.write_station_message()
out["dock"] = not w.st_dock.isHidden()
spin(25, lambda: any("Achtung: Platz „Platz 2“ ist auch auf 20 m" in m for m in msgs))
out["warn"] = [m for m in msgs if m.startswith("Achtung")][:1]
spin(15, lambda: any(c["state"] == "in" for c in w.db.chats()))
out["chats_in"] = [c["text"] for c in w.db.chats() if c["state"] == "in"]
out["note"] = [m for m in msgs if m.startswith("Nachricht von")][:1]
v = w.station_view
v.to.setCurrentIndex(v.to.findData("Platz 2"))
v.edit.setText("Danke, 73"); v._send()
out["chats_out"] = [(c["text"], c["to"], c["state"]) for c in w.db.chats() if c["state"] != "in"]
spin(1.5)
out["rows"] = [[v.table.item(r, c).text() for c in (0, 1, 2, 3, 6)] for r in range(v.table.rowCount())]
out["red"] = v.table.item(0, 0).background().color().name()
out["history"] = v.history.toPlainText()
out["targets"] = [v.to.itemText(i) for i in range(v.to.count())]
spin(4)
w._dirty = False
print(json.dumps(out)); sys.stdout.flush()
w.close()
'''

PLACE = COMMON + r'''
w = main_window.MainWindow(); w.show()
w.cfg["station_operator"] = "DO2GGH"; w.cfg["station_place_name"] = "Platz 2"
w.cfg["station_cable_asked"] = 9
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QInputDialog.getText = staticmethod(lambda *a, **k: ("geheim", True))
ok = spin(20, lambda: w.station.active and w.station.connected())
out["joined"] = ok
w.cb_band.setCurrentText("20"); w.cb_mode.setCurrentText("CW")
spin(3)
w.station.send_chat("", "Kaffee ist fertig")
spin(15, lambda: any(c["state"] == "in" for c in w.db.chats()))
spin(6)            # verbunden bleiben, bis der Hauptplatz seine Tabelle angesehen hat
out["chats"] = [(c["text"], c["state"]) for c in w.db.chats()]
w._dirty = False
print(json.dumps(out)); sys.stdout.flush()
w.close()
'''


def test_two_programs_overview_warning_and_chat(tmp_path):
    pytest.importorskip("PySide6")
    udp, tcp = free_port(socket.SOCK_DGRAM), free_port()
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    pa = subprocess.Popen([sys.executable, "-c", HOST, str(ROOT), str(a), str(udp), str(tcp)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          env=env_for(a))
    time.sleep(0.5)
    pb = subprocess.Popen([sys.executable, "-c", PLACE, str(ROOT), str(b), str(udp), str(tcp)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          env=env_for(b))
    oa, ea = pa.communicate(timeout=120)
    ob, eb = pb.communicate(timeout=120)
    assert pa.returncode == 0, ea[-3000:]
    assert pb.returncode == 0, eb[-3000:]
    A = json.loads(oa.strip().splitlines()[-1])
    B = json.loads(ob.strip().splitlines()[-1])
    assert B["joined"], eb[-2000:]
    assert A["dock"]
    assert A["warn"] == ["Achtung: Platz „Platz 2“ ist auch auf 20 m"], (A, ea[-2000:])
    assert A["chats_in"] == ["Kaffee ist fertig"]
    assert A["note"] == ["Nachricht von Platz 2: Kaffee ist fertig"]
    assert A["chats_out"] == [["Danke, 73", "Platz 2", "ok"]]
    # Hauptplatz zuerst (dieser Platz, fett), dann der Laptop – beide auf 20 m = rot
    assert A["rows"][0][:4] == ["Platz 1 (dieser Platz)", "DL1AAA", "Run (Sender 0)", "20"]
    assert A["rows"][0][4] == "1"
    assert A["rows"][1][:4] == ["Platz 2", "DO2GGH", "Multi (Sender 1)", "20"]
    assert A["red"] == "#f8d0d0"
    assert "Platz 2: Kaffee ist fertig" in A["history"]
    assert "Ich → Platz 2: Danke, 73 (zugestellt)" in A["history"]
    assert A["targets"] == ["alle Plätze", "Platz 2"]
    assert B["chats"] == [["Kaffee ist fertig", "ok"], ["Danke, 73", "in"]]
