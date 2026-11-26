"""0.10.5/0.10.6: fldigi einrichten, Zusatzprogramme passend zum Contest starten, QSOs aus
fldigi übernehmen. Mit einem nachgebauten fldigi (XML-RPC im Test); gesendet wird nichts."""

import json
import subprocess
import sys
import textwrap
import socket
import threading
import time
import xmlrpc.client
from pathlib import Path
from xmlrpc.server import SimpleXMLRPCServer

from gogoham import fldigi

HERE = Path(__file__).parent


class FakeFldigi:
    """Nachbau der XML-RPC-Befehle, die GoGoHam benutzt."""

    def __init__(self):
        self.rx = ""
        self.tx = []
        self.calls = []
        self.state = "RX"
        self.call = ""
        self.counter = None
        self.srv = SimpleXMLRPCServer(("127.0.0.1", 0), logRequests=False, allow_none=True)
        self.port = self.srv.server_address[1]
        f = self.srv.register_function
        f(lambda: "4.2.13", "fldigi.version")
        f(lambda name: self._log("modem", name), "modem.set_by_name")
        f(lambda: "RTTY", "modem.get_name")
        f(lambda: len(self.rx), "text.get_rx_length")
        f(lambda a, n: xmlrpc.client.Binary(self.rx[a:a + n].encode()), "text.get_rx")
        f(lambda: self._log("clear_tx"), "text.clear_tx")
        f(lambda t: self.tx.append(t) or 0, "text.add_tx")
        f(lambda: self._set("TX"), "main.tx")
        f(lambda: self._set("RX", "abort"), "main.abort")
        f(lambda: self.state, "main.get_trx_state")
        f(lambda i: self._log("terminate"), "fldigi.terminate")
        f(lambda: self.call, "log.get_call")
        f(lambda v: self._counter(v), "log.set_contest_counter")
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def _log(self, *a):
        self.calls.append(a)
        return 0

    def _counter(self, v):
        if not isinstance(v, str):                 # wie das echte fldigi: nur Text
            raise TypeError("type error")
        self.counter = v
        return 0

    def _set(self, st, what="tx"):
        self.state = st
        return self._log(what)


def test_wanted_and_apply(tmp_path):
    w = fldigi.wanted("127.0.0.1", 4533, "do2ggh", "jn59me")
    assert w["HAMRIGDEVICE"] == "127.0.0.1:4533" and w["HAMRIGMODEL"] == "2"
    assert w["HAMLIBCMDPTT"] == "1" and w["CHKUSEHAMLIBIS"] == "1"
    assert (w["RTTYBAUD"], w["RTTYSHIFT"], w["RTTYBITS"], w["RTTYSTOP"]) == ("1", "3", "0", "1")
    assert w["MYCALL"] == "DO2GGH" and w["MYLOC"] == "JN59ME" and w["USEFSK"] == "0"
    f = fldigi.wanted("127.0.0.1", 4532, tx="fsk", fsk_port="/dev/ttyUSB1", fsk_line="RTS")
    assert (f["USEFSK"], f["FSK_PORT"], f["FSK_ON_DTR"]) == ("1", "/dev/ttyUSB1", "0")
    assert "MYCALL" not in f
    p = tmp_path / "fldigi_def.xml"
    orig = ("<FLDIGI_DEFS>\n\n<!-- type: bool\nkeep -->\n<CONFIRMEXIT>1</CONFIRMEXIT>\n"
            "<HAMRIGDEVICE>/dev/ttyS0</HAMRIGDEVICE>\n<MYNAME>Franz</MYNAME>\n</FLDIGI_DEFS>\n")
    p.write_text(orig)
    assert len(fldigi.changes(p, w)) == len(w) - 0 - 0 or fldigi.changes(p, w)
    b = fldigi.apply(p, w)
    assert b and b.read_text() == orig
    text = p.read_text()
    assert "<MYNAME>Franz</MYNAME>" in text and "keep -->" in text
    assert "<HAMRIGDEVICE>127.0.0.1:4533</HAMRIGDEVICE>" in text
    assert "<CONFIRMEXIT>0</CONFIRMEXIT>" in text and text.rstrip().endswith("</FLDIGI_DEFS>")
    assert fldigi.changes(p, w) == []
    assert fldigi.apply(p, w) is None                      # nichts zu tun
    # zweite Änderung: die Original-Sicherung bleibt die vom allerersten Stand
    fldigi.apply(p, fldigi.wanted("127.0.0.1", 4534))
    assert b.read_text() == orig and "127.0.0.1:4534" in p.read_text()
    # ohne Datei: neu anlegen
    q = tmp_path / "neu" / "fldigi_def.xml"
    assert fldigi.apply(q, {"MYCALL": "A&B"}) is None
    assert "<MYCALL>A&amp;B</MYCALL>" in q.read_text() and fldigi.changes(q, {"MYCALL": "A&B"}) == []


def test_sound_and_env():
    out = ("1\talsa_input.pci-0000.analog-stereo\tx\n"
           "2\talsa_input.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo\tx\n")
    run = lambda a, t=5: (0, out)                           # noqa: E731
    sink = "alsa_output.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo"
    assert fldigi.source_for_sink(sink, run) == \
        "alsa_input.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo"
    out2 = "2\talsa_input.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.mono-fallback\tx\n"
    assert fldigi.source_for_sink(sink, lambda a, t=5: (0, out2)).endswith("mono-fallback")
    assert fldigi.source_for_sink("bluez_output.x", run) == ""
    env = fldigi.environment(sink, run, base={"HOME": "/x"})
    assert env["PULSE_SINK"] == sink and env["PULSE_SOURCE"].startswith("alsa_input.usb-Burr")
    assert env["LC_NUMERIC"] == "C" and env["HOME"] == "/x"
    assert "PULSE_SINK" not in fldigi.environment("", run, base={})


def test_logging_and_macros(tmp_path):
    w = fldigi.logging_settings(2239)
    assert (w["ENABLE_UDP_LOGGING"], w["UDP_LOG_PORT"], w["LOGGING"], w["CLEARONSAVE"]) == \
        ("1", "2239", "1", "1")
    m = fldigi.contest_macros("<CNTR>")
    assert m[0] == ("CQ", "<TX>\nCQ TEST <MYCALL> <MYCALL> CQ\n<RX>")
    assert m[1][1] == "<TX>\n<CALL> 599 <CNTR> <CNTR> <CALL>\n<RX>"
    assert "<LOG><INCR>" in m[2][1] and "<LOG><INCR>" in m[4][1]
    assert fldigi.contest_macros("")[1][1] == "<TX>\n<CALL> 599 <CALL>\n<RX>"
    p = tmp_path / "macros" / "macros.mdf"
    assert fldigi.write_macros(p, "14") is None              # neu: keine Sicherung nötig
    text = p.read_text()
    assert text.startswith("//fldigi macro definition file extended\n")
    assert "\n/$ 0 CQ\n<TX>\n" in text and "\n/$ 1 EXCH\n<TX>\n<CALL> 599 14 14 <CALL>\n" in text
    p.write_text("eigene Makros")
    b = fldigi.write_macros(p, "15")
    assert b.read_text() == "eigene Makros" and "599 15 15" in p.read_text()
    fldigi.write_macros(p, "16")
    assert b.read_text() == "eigene Makros"                  # Original bleibt


def test_program_choice():
    from gogoham.gui import companions as cp

    class C:
        def __init__(self, modes, ex=lambda n: f"{n:03d}"):
            self.modes, self.sent_exchange = modes, ex
    assert cp.program_for(C({"RY"})) == "fldigi" and cp.program_for(C({"DG"})) == "ft8"
    assert cp.program_for(C({"CW", "PH"})) is None and cp.program_for(C({"CW", "RY"})) is None
    assert cp.program_for(None) is None
    have = {"jtdx", "wsjtx_improved"}
    find = lambda k: "/x" if k in have else None              # noqa: E731
    assert cp.ft8_choice({}, find) == "wsjtx_improved"
    # 0.10.17: JTDX nicht mehr dabei – früher gewählt → WS
    assert cp.ft8_choice({"ft8_program": "jtdx"}, find) == "wsjtx_improved"
    assert cp.ft8_choice({"ft8_program": "wsjtx"}, find) == "wsjtx_improved"
    assert cp.ft8_choice({}, lambda k: None) is None
    assert cp.serial_template(C({"RY"}, lambda n: f"599 {n:03d}")) == "599 <CNTR>"
    assert cp.serial_template(C({"RY"}, lambda n: "14")) == "14"


def test_fldigi_link_and_udp():
    from gogoham.gui.companions import FldigiLink
    from gogoham.wsjtx import WsjtxListener
    fake = FakeFldigi()
    link = FldigiLink(lambda: fldigi.Client(port=fake.port), poll=0.05)
    link.start()
    assert link.events.get(timeout=5) == ("connected", "4.2.13")
    assert ("modem", "RTTY") in fake.calls
    assert link.events.get(timeout=5) == ("call", "")
    fake.call = "dl1abc"
    assert link.events.get(timeout=5) == ("call", "DL1ABC")
    link.submit("counter", 12)
    t0 = time.monotonic()
    while fake.counter is None and time.monotonic() - t0 < 5:
        time.sleep(0.05)
    assert fake.counter == "12"
    link.submit("terminate")
    got = [link.events.get(timeout=5) for _ in range(1)]
    while ("terminated", "") not in got:
        got.append(link.events.get(timeout=5))
    assert ("terminate",) in fake.calls
    fake.srv.shutdown()
    w2 = FldigiLink(lambda: fldigi.Client(port=1), connect_timeout=0.3)
    w2.start()
    assert w2.events.get(timeout=5) == ("failed", "")
    # UDP: reines ADIF von fldigi – kommt an, sperrt aber kein Funkgerät („FT8 aktiv“)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    lst = WsjtxListener(port, "127.0.0.1", program="fldigi")
    lst.start()
    time.sleep(0.2)
    rec = ("<CALL:6>DL1ABC<MODE:4>RTTY<FREQ:9>14.086500<BAND:3>20m<QSO_DATE:8>20261110"
           "<TIME_ON:4>0914<RST_SENT:3>599<RST_RCVD:3>599<STX:3>007<SRX_STRING:2>14<EOR>")
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    out.sendto(rec.encode(), ("127.0.0.1", port))
    r = lst.records.get(timeout=5)
    assert r["CALL"] == "DL1ABC" and r["SRX_STRING"] == "14" and lst.active_program() is None
    lst.stop()


SCRIPT = r'''
import json, sys, os, time, socket
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[3])
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[2])))
from test_companions_0106 import FakeFldigi
fake = FakeFldigi()
from gogoham import fldigi, extapps, config as cfgmod
from gogoham.gui import companions
fldigi.XMLRPC_PORT = fake.port
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("127.0.0.1", 0))
companions.FLDIGI_UDP_PORT = s.getsockname()[1]; s.close()
extapps.find = lambda k, *a, **kw: "/usr/bin/fldigi" if k == "fldigi" else None
fldigi.running = lambda run=None: False
started = []
class Proc:
    def __init__(self, args, **kw):
        started.append([args, kw.get("env", {}).get("PULSE_SINK")])
    def wait(self, t=None): return 0
    def terminate(self): pass
    def poll(self): return 0
cfg = cfgmod.load()
cfg.update(rig_enabled=True, wsjtx_enabled=False, voice_rig_out="alsa_output.usb-X-00.analog-stereo",
           rig_profiles=[{"name": "IC-7300", "model": 3073, "port": 4532, "slot": 0, "start": False}],
           rig_profile=0)
cfgmod.save(cfg)
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui import main_window
main_window.MainWindow._welcome = lambda self: None
main_window.MainWindow._ask_scp = lambda self: None
p = Path(os.environ["HOME"]) / "t.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="wpx-cw", mycall="DO2GGH", my_grid="JN59ME")); db.close()
w = main_window.MainWindow()
w.companions.popen = Proc
w.open_log(str(p))
w.contest.modes = {"RY"}                   # so tun, als wäre es ein RTTY-Contest
w.show()
out = {}
for _ in range(80):
    app.processEvents(); time.sleep(0.05)
    if fake.counter is not None: break
out["started"] = started
cur = fldigi.current(fldigi.def_path())
out["def"] = [cur.get("HAMRIGDEVICE"), cur.get("UDP_LOG_PORT"), cur.get("MYCALL"), cur.get("LOGGING")]
out["macros"] = fldigi.macros_path().read_text()
out["counter"] = fake.counter
out["mode"] = w.current_mode()
fake.call = "DL1ABC"
for _ in range(40):
    app.processEvents(); time.sleep(0.05)
    if w.ed_call.text() == "DL1ABC": break
out["mirror"] = w.ed_call.text()
rec = ("<CALL:6>DL1ABC<MODE:4>RTTY<FREQ:9>14.086500<BAND:3>20m<QSO_DATE:8>20261110"
       "<TIME_ON:4>0914<RST_SENT:3>599<RST_RCVD:3>599<STX:3>001<SRX_STRING:3>005<EOR>")
fake.call = ""
socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(rec.encode(), ("127.0.0.1", companions.FLDIGI_UDP_PORT))
for _ in range(60):
    app.processEvents(); time.sleep(0.05)
    if w.qsos and fake.counter == "2" and not w.ed_call.text(): break
out["qsos"] = [[q.call, q.mode, q.band, q.exch_r, q.exch_s] for q in w.qsos]
out["counter2"] = fake.counter
out["cleared"] = w.ed_call.text()
out["menu"] = [a.text() for a in w.menu_companions.actions()] if (w._fill_companion_menu() or True) else []
w.close()
out["terminated"] = ("terminate",) in fake.calls
print("RESULT " + json.dumps(out))
'''


def test_companion_flow(tmp_path):
    data, cfg = tmp_path / "data", tmp_path / "cfg"
    (cfg / "gogoham").mkdir(parents=True)
    (data / "gogoham").mkdir(parents=True)
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin",
           "GOGOHAM_NO_DISCOVERY": "1"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(HERE / "cty_sample.dat"), str(HERE)],
                       capture_output=True, text=True, env=env, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["started"] == [[["/usr/bin/fldigi"], "alsa_output.usb-X-00.analog-stereo"]]
    assert o["def"][0] == "127.0.0.1:4532" and o["def"][2:] == ["DO2GGH", "1"]
    assert "/$ 1 EXCH\n<TX>\n<CALL> 599 <CNTR> <CNTR> <CALL>" in o["macros"]
    assert o["counter"] == "1" and o["mode"] == "RTTY"
    assert o["mirror"] == "DL1ABC"
    assert o["qsos"] == [["DL1ABC", "RTTY", "20", "005", o["qsos"][0][4]]]
    assert o["qsos"][0][4].endswith("1")
    assert o["counter2"] == "2" and o["cleared"] == ""
    assert o["menu"] == ["fldigi"]
    assert o["terminated"] is True
