"""0.8.12: DX-Cluster und Bandmap – Zeilen lesen, Betriebsart, Filter, Verbindung zu einem
nachgebauten Knoten und der Ablauf im echten Qt-Fenster (offscreen)."""

import json
import shutil
import socket
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

from gogoham import dxcluster as dc

HERE = Path(__file__).parent


# ------------------------------------------------------------------ Zeilen
def test_parse_dx_lines():
    s = dc.parse_line("DX de HB9DCO-#:   7018.5  LZ2XA        CW 25 dB 36 WPM CQ             1751Z")
    assert (s.call, s.freq, s.spotter, s.spotter_call, s.utc) == ("LZ2XA", 7018500, "HB9DCO-#",
                                                                  "HB9DCO", "1751")
    assert "25 dB" in s.comment
    s = dc.parse_line("DX de F5AGK:      7169.0  DL40EUDXF    SPECIAL CALL 40 YEARS      1753Z JN18\x07\r\n")
    assert s.call == "DL40EUDXF" and s.freq == 7169000
    s = dc.parse_line(" 14025.0  DL1ABC      4-Nov-2026 1751Z  up 1               <OK1RR>")
    assert (s.call, s.freq, s.spotter, s.comment) == ("DL1ABC", 14025000, "OK1RR", "up 1")
    assert dc.parse_line("Hello DO2GGH, this is DB0SUE-7") is None
    assert dc.parse_line("DX de X1AB:  99999.0  DL1ABC  test  1200Z") is None   # kein Band


def test_mode_from_comment_and_bandplan():
    mk = lambda khz, c="": dc.Spot("DL1ABC", int(khz * 1000), "OK1RR", c)   # noqa: E731
    assert dc.spot_mode(mk(14025)) == "CW" and dc.rig_mode(mk(14025)) == "CW"
    assert dc.spot_mode(mk(14250)) == "PH" and dc.rig_mode(mk(14250)) == "USB"
    assert dc.rig_mode(mk(7150)) == "LSB" and dc.rig_mode(mk(3700)) == "LSB"
    assert dc.spot_mode(mk(14080)) == "DG"
    assert dc.spot_mode(mk(10120)) == "CW"
    assert dc.spot_mode(mk(14074, "FT8 -10 dB")) == "DG"
    assert dc.spot_mode(mk(14030, "SSB split")) == "PH"
    assert dc.spot_mode(mk(21300, "RTTY")) == "RY"
    # 0.8.12: FT8-Frequenzen im Sprechfunkbereich und Skimmer-Kommentare
    assert dc.spot_mode(mk(7074)) == "DG" and dc.spot_mode(mk(7076.5)) == "DG"
    assert dc.spot_mode(mk(7150)) == "PH" and dc.spot_mode(mk(14200)) == "PH"
    assert dc.spot_mode(mk(144174, "-03dB from JO90 1166Hz")) == "DG"
    assert dc.spot_mode(mk(14130, "25 dB 36 WPM CQ")) == "CW"


def test_store_dedupe_expire_and_sort():
    st = dc.SpotStore(30)
    a = dc.Spot("DL1ABC", 14250000, "OK1RR", received=1000.0)
    st.add(a)
    v = st.version
    st.add(dc.Spot("DL1ABC", 14250000, "OK2AA", received=1030.0))   # gleicher Spot
    assert st.version == v and len(st) == 1 and st.spots[("DL1ABC", "20")].received == 1030.0
    st.add(dc.Spot("DL1ABC", 14260000, "OK2AA", received=1040.0))   # neue Frequenz
    assert st.spots[("DL1ABC", "20")].freq == 14260000
    st.add(dc.Spot("K3LR", 14200000, "DL1X", received=1040.0))
    st.add(dc.Spot("K3LR", 7200000, "DL1X", received=1040.0))
    assert [s.call for s in st.on_band("20")] == ["K3LR", "DL1ABC"]
    st.expire(now=1040.0 + 30 * 60 + 1)
    assert len(st) == 0


def test_filter_and_node():
    s = dc.Spot("JA1AAA", 14250000, "K1ZZ")
    assert dc.passes_filter(s, "NA", "AS", {"EU"}, set(dc.CONTINENTS)) is False
    assert dc.passes_filter(s, "EU", "AS", {"EU"}, set(dc.CONTINENTS)) is True
    assert dc.passes_filter(s, "EU", "AS", {"EU"}, {"NA", "SA"}) is False
    assert dc.passes_filter(s, None, None, {"EU"}, {"NA"}) is True      # unbekannt: durchlassen
    assert dc.parse_node("db0sue.de:8000") == ("db0sue.de", 8000)
    assert dc.parse_node("dxc.example.org 7300") == ("dxc.example.org", 7300)
    assert dc.parse_node("host:abc") is None and dc.parse_node("") is None


# ------------------------------------------------ nachgebauter Cluster-Knoten
def _fake_node():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(2)
    got = []

    def serve():
        try:
            c, _a = srv.accept()
        except OSError:
            return
        with c:
            c.sendall(b"Welcome to TEST-7\r\nlogin: ")
            buf = b""
            while b"\n" not in buf:
                buf += c.recv(100)
            got.append(buf.strip().decode())
            c.sendall(b"Hello DO2GGH\r\nDX de OK1RR:     14250.0  DL1ABC       up 5        1751Z\r\n")
            buf = b""
            c.settimeout(5)
            try:
                while b"\n" not in buf:
                    buf += c.recv(100)
            except OSError:
                return
            got.append(buf.strip().decode())
            c.sendall(b" 21025.0  K3LR      4-Nov-2026 1740Z  cq test   <DL2XX>\r\n")
            time.sleep(2)
    threading.Thread(target=serve, daemon=True).start()
    return srv, got


def test_client_logs_in_and_reads_spots():
    srv, got = _fake_node()
    cl = dc.ClusterClient("127.0.0.1", srv.getsockname()[1], "do2ggh", history=10)
    cl.start()
    spots = []
    end = time.monotonic() + 6
    while time.monotonic() < end and len(spots) < 2:
        try:
            spots.append(cl.spots.get(timeout=0.2))
        except Exception:
            pass
    assert cl.connected
    cl.stop()
    cl.join(3)
    srv.close()
    assert got[0] == "DO2GGH" and got[1] == "sh/dx 10"
    assert [s.call for s in spots] == ["DL1ABC", "K3LR"]
    assert cl.error == ""                                   # gewollt getrennt: kein Fehler


def test_client_reports_unreachable_node():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                                               # Port ist frei – niemand hört
    cl = dc.ClusterClient("127.0.0.1", port, "DO2GGH")
    cl.start()
    end = time.monotonic() + 3
    while time.monotonic() < end and not cl.error:
        time.sleep(0.05)
    cl.stop()
    cl.join(3)
    assert cl.error and not cl.connected


# --------------------------------------------------------- im echten Fenster
SCRIPT = r'''
import json, queue, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham.db import DEFAULT_META, LogDB
from gogoham import dxcluster as dc
from gogoham.gui.main_window import MainWindow
from gogoham.gui import bandmap as bm
MainWindow._welcome = lambda self: None
MainWindow._ask_scp = lambda self, *a, **k: None
class FakeCluster:
    def __init__(self, *a):
        self.spots = queue.Queue(); self.connected = True; self.error = ""; self.host = "test.node"
    def start(self): pass
    def stop(self): pass
fake = FakeCluster()
MainWindow._make_cluster = lambda self, h, p, c: fake
w = MainWindow()
p = Path(sys.argv[2]) / "wpx.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="wpx-ssb", mycall="DO2GGH")); db.close()
w.open_log(str(p))
w.show(); app.processEvents()
w._updating = True; w.cb_mode.setCurrentText("USB"); w._updating = False
w.qsy_khz(14265)
w.ed_call.setText("DL1ABC"); w.update_check(); w.ed_exch.setText("12"); w.exch_auto = False
w.log_qso()
out = {"esm_before": w.cfg.get("esm_mode", "run")}
for call, khz, spotter, comment in (("DL1ABC", 14250.0, "OK1XX", ""),     # Dupe
                                    ("JA1AAA", 14260.0, "K1ZZ", ""),      # von NA gehört: weg
                                    ("K3LR", 14270.0, "DL2BB", ""),       # neuer Multi
                                    ("OK1RR", 14030.0, "DL3CC", ""),      # CW im SSB-Contest: weg
                                    ("DL1XYZ", 14280.0, "DL4DD-#", ""),   # neues QSO, kein Multi
                                    ("VK2AB", 21250.0, "DL5EE", "")):     # anderes Band
    fake.spots.put(dc.Spot(call, int(khz * 1000), spotter, comment, "1800"))
rows_seen = []
orig = w.bandmap.show_rows
def spy(rows, own, band, now=None):
    rows_seen.append([(s.call, st) for s, st, *_ in rows]); return orig(rows, own, band, now)
w.bandmap.show_rows = spy
w._bm_next = 0; w._cluster_tick(); app.processEvents()
out["rows"] = rows_seen[-1] if rows_seen else None
out["store"] = sorted(k[0] for k in w.spots.spots)
out["items"] = [w.bandmap.item(i).text() for i in range(w.bandmap.count())]
out["label"] = w.lbl_sb_cluster.text()
out["title"] = w.bm_dock.windowTitle()
out["menu"] = [w.act_bandmap.text(), w.act_bandmap.isChecked()]
k3 = [s for s in w.spots.spots.values() if s.call == "K3LR"][0]
w.act_bandmap.setChecked(False); app.processEvents()
out["menu_off"] = [w.bm_dock.isVisible(), w.cluster is None, len(w.spots)]
w.act_bandmap.setChecked(True); app.processEvents()
out["menu_on"] = w.cluster is fake
# Klick auf K3LR: QSY + Mode, Rufzeichen eintragen, S&P – nichts senden
sent = []
class Rig:
    def submit(self, *a): sent.append(list(a))
    def snapshot(self): return None
    def stop(self): pass
w.rig = Rig(); w._rig_connected = lambda: True; w.rig_caps = None
w.bandmap_pick(k3)
out["pick"] = [list(sent), w.ed_call.text(), w.cfg.get("esm_mode"), w.cb_band.currentText(),
               w.cb_mode.currentText()]
# 40 m LSB
sent.clear()
w.bandmap_pick(dc.Spot("EA8AH", 7150000, "DL1X", "", "1800"))
out["pick40"] = [sent, w.cb_band.currentText(), w.cb_mode.currentText()]
# Verbindung weg
fake.connected = False; fake.error = "Knoten antwortet nicht"
w._update_cluster_label()
out["label_err"] = w.lbl_sb_cluster.text()
print("RESULT " + json.dumps(out, ensure_ascii=False))
w.close()
'''


def test_bandmap_in_window(tmp_path):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    (data / "gogoham").mkdir(parents=True)
    (cfg / "gogoham").mkdir(parents=True)
    logs.mkdir()
    shutil.copy(HERE / "cty_sample.dat", data / "gogoham" / "cty.dat")
    (cfg / "gogoham" / "config.json").write_text(json.dumps({
        "rig_enabled": False, "wsjtx_enabled": False, "livescore_enabled": False,
        "rules_auto_update": False, "daily_update": False, "last_log": "", "language": "de",
        "open_bandmap": True}))      # 0.8.14.1: Bandmap beim Start offen = verbunden
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(logs)], capture_output=True, text=True, env=env, timeout=90)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["store"] == ["DL1ABC", "DL1XYZ", "K3LR", "VK2AB"]        # JA1AAA, OK1RR gefiltert
    assert o["rows"] == [["DL1ABC", "dupe"], ["K3LR", "mult"], ["DL1XYZ", "new"]]
    items = o["items"]
    assert any("hier bist du" in t for t in items)
    pos = lambda txt: next(i for i, t in enumerate(items) if txt in t)   # noqa: E731
    assert pos("DL1ABC") < pos("hier bist du") < pos("K3LR") < pos("DL1XYZ")
    assert "14.265,0" in items[pos("hier bist du")]
    assert "★" in [t for t in items if "K3LR" in t][0]
    assert "test.node" in o["label"] and "NON-ASSISTED" in o["label"]
    assert "4 Spots (alle Contest-Bänder)" in o["label"]          # 0.8.12.2
    assert o["title"] == "Bandmap 20 m"
    assert o["menu"] == ["Bandmap", True] and o["menu_off"] == [False, True, 0]   # 0.8.12.3
    assert o["menu_on"] is True                       # 0.8.14.1: Bandmap auf = verbunden
    sent, call, esm, band, mode = o["pick"]
    assert sent == [["set_mode", "USB", 0], ["set_freq", 14270000]]
    assert (call, esm, band, mode) == ("K3LR", "sp", "20", "USB")
    assert o["pick40"] == [[["set_mode", "LSB", 0], ["set_freq", 7150000]], "40", "LSB"]
    assert "antwortet nicht" in o["label_err"]



def test_mode_change_uses_rig_default_filter():
    """0.8.12.7: Beim Wechsel der Betriebsart wählt das Funkgerät seinen Standardfilter."""
    from gogoham.rig import RIG_FILTER, RigctldClient
    sent = []
    c = RigctldClient()
    c.command = lambda cmd, lines=1: sent.append(cmd) or ["RPRT 0"]
    c.set_mode("CW")
    assert RIG_FILTER == 0 and sent == ["M CW 0"]



def test_client_detects_silent_disconnect():
    """0.8.12.8: Netzwerkkabel gezogen – der Knoten schweigt, die Verbindung wirkt aber offen.
    GoGoHam fragt per Leerzeile nach und meldet den Abbruch, wenn keine Antwort kommt."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(2)
    probes = []

    def serve():
        c, _a = srv.accept()
        c.sendall(b"login: ")
        c.settimeout(10)
        buf = b""
        try:
            while True:                      # nimmt alles an, antwortet aber nie mehr
                d = c.recv(100)
                if not d:
                    break
                buf += d
                probes.append(buf.count(b"\r\n"))
        except OSError:
            pass
        c.close()
    threading.Thread(target=serve, daemon=True).start()
    cl = dc.ClusterClient("127.0.0.1", srv.getsockname()[1], "DO2GGH", history=0)
    cl.idle_probe, cl.probe_timeout = 1.0, 1.0
    cl.start()
    end = time.monotonic() + 10
    seen_connected = False
    while time.monotonic() < end and not cl.error:
        seen_connected = seen_connected or cl.connected
        time.sleep(0.05)
    cl.stop()
    cl.join(3)
    srv.close()
    assert seen_connected
    assert "unterbrochen" in cl.error and not cl.connected
    assert probes and max(probes) >= 2                # Anmeldung + Leerzeile


def test_client_answering_node_stays_connected():
    """Ein Knoten, der auf die Leerzeile antwortet, bleibt verbunden."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(2)

    def serve():
        c, _a = srv.accept()
        c.sendall(b"login: ")
        c.settimeout(10)
        try:
            while True:
                d = c.recv(100)
                if not d:
                    break
                c.sendall(b"DO2GGH de TEST-7 dxspider >\r\n")
        except OSError:
            pass
        c.close()
    threading.Thread(target=serve, daemon=True).start()
    cl = dc.ClusterClient("127.0.0.1", srv.getsockname()[1], "DO2GGH", history=0)
    cl.idle_probe, cl.probe_timeout = 0.5, 1.0
    cl.start()
    time.sleep(4)
    ok = cl.connected and not cl.error
    cl.stop()
    cl.join(3)
    srv.close()
    assert ok
