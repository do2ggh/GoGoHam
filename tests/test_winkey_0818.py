"""0.8.18: CW über WinKey, PTT über DTR/RTS – mit nachgebautem WinKey (kein echtes Gerät)."""

import time


from gogoham import rigprofiles, winkey


class FakeWinKey:
    """Verhält sich wie ein WinKey nach K1EL-Datenblatt (nur das, was GoGoHam benutzt)."""

    def __init__(self, version=31, pot=10):
        self.version, self.pot = version, pot
        self.sent = bytearray()          # alles, was GoGoHam geschickt hat
        self.out = bytearray()           # Antworten an GoGoHam
        self.closed = False

    def __call__(self, _path):           # als „opener“ benutzbar
        return self

    def write(self, data: bytes) -> None:
        self.sent += data
        if data.startswith(b"\x00\x02"):
            self.out.append(self.version)
        if b"\x07" in data and not data.startswith(b"\x00"):
            self.out.append(0x80 | self.pot)

    def read(self, timeout: float) -> bytes:
        if not self.out:
            time.sleep(min(timeout, 0.01))
            return b""
        data, self.out[:] = bytes(self.out), b""
        return data

    def close(self) -> None:
        self.closed = True


def wait_for(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_clean_text_never_sends_command_bytes():
    assert winkey.clean_text("cq test dl1abc\x02\x0a") == b"CQ TEST DL1ABC"
    assert winkey.clean_text("599 äöü 001") == b"599  001"
    assert winkey.version_text(31) == "WK3.1" and winkey.version_text(23) == "WK2.3"


def test_probe_reads_version_and_closes():
    fk = FakeWinKey(version=23)
    assert winkey.probe("/dev/x", opener=fk) == 23
    assert fk.sent == b"\x00\x02\x00\x03" and fk.closed


def test_probe_no_winkey():
    class Mute(FakeWinKey):
        def write(self, data):
            self.sent += data
    assert winkey.probe("/dev/x", opener=Mute()) == 0


def test_worker_connects_sets_pot_and_sends_text():
    fk = FakeWinKey(version=31, pot=15)
    w = winkey.WinKeyWorker("/dev/x", opener=fk)
    w.start()
    try:
        assert wait_for(lambda: w.snapshot().wpm == 25)        # 10 + Knopfwert 15
        st = w.snapshot()
        assert st.connected and st.version == 31
        assert bytes([0x05, 10, 40, 0]) in fk.sent               # Knopf 10–50 WpM
        assert bytes([0x02, 25]) in fk.sent                      # Tempo vom Knopf übernommen
        w.submit("send", "cq test " * 5)                         # länger als ein Häppchen
        assert wait_for(lambda: b"CQ TEST CQ TEST CQ TEST CQ TEST CQ TEST " in fk.sent)
        w.submit("set_wpm", 99)
        assert wait_for(lambda: w.snapshot().wpm == 60)          # begrenzt wie Bild auf/ab
        w.submit("stop")
        assert wait_for(lambda: fk.sent.endswith(b"\x0A"))
    finally:
        w.stop()
        w.join(2)
    assert fk.sent.endswith(b"\x0A\x00\x03") and fk.closed      # Puffer leer, Host Close


def test_worker_xoff_breakin_and_pot():
    fk = FakeWinKey()
    w = winkey.WinKeyWorker("/dev/x", opener=fk)
    w.start()
    try:
        assert wait_for(lambda: w.snapshot().connected)
        fk.out.append(0xC0 | 0x01 | 0x04)                       # XOFF + sendet
        assert wait_for(lambda: w.snapshot().busy)
        n = len(fk.sent)
        w.submit("send", "TEST")
        time.sleep(0.2)
        assert b"TEST" not in fk.sent[n:]                        # wartet bei XOFF
        fk.out.append(0xC0)                                      # Puffer wieder frei
        assert wait_for(lambda: b"TEST" in fk.sent[n:])
        w.submit("send", "X" * 40)
        fk.out.append(0xC0 | 0x01 | 0x02)                        # Paddle unterbricht
        assert wait_for(lambda: w.snapshot().breakin_id == 1)
        fk.out.append(0x80 | 20)                                 # Knopf gedreht
        assert wait_for(lambda: w.snapshot().wpm == 30)
    finally:
        w.stop()
        w.join(2)


def test_worker_reports_missing_winkey():
    def fail(_path):
        raise OSError("kein Gerät")
    w = winkey.WinKeyWorker("/dev/x", opener=fail, retry=0.05)
    w.start()
    try:
        assert wait_for(lambda: w.snapshot().error)
        assert not w.snapshot().connected
    finally:
        w.stop()
        w.join(2)


def test_profile_defaults_and_check():
    from gogoham.gui.dialogs import cw_ptt_problem
    cfg = {"rig_profiles": [{"model": 3073, "device": "/dev/ttyACM0"}]}
    p = rigprofiles.ensure_profiles(cfg)[0]
    assert p["winkey"] == "" and p["ptt_line"] == "" and p["ptt_device"] == ""
    assert cw_ptt_problem(p) == ""
    assert cw_ptt_problem(dict(p, ptt_line="DTR"))
    assert cw_ptt_problem(dict(p, winkey="/dev/ttyACM0"))
    assert cw_ptt_problem(dict(p, winkey="/dev/ttyACM2", ptt_line="DTR", ptt_device="/dev/ttyACM1")) == ""


# ------------------------------------------------- echtes Hauptfenster + WinKey an einer pty
GUI_SCRIPT = r'''
import json, os, pty, sys, threading, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import winkey
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui.main_window import MainWindow
MainWindow._welcome = lambda self: None
MainWindow._ask_scp = lambda self, *a, **k: None
master, slave = pty.openpty()
got = bytearray()
def fake_wk():                         # Gegenstelle: antwortet wie ein WinKey 3.1
    while True:
        try:
            data = os.read(master, 256)
        except OSError:
            return
        got.extend(data)
        if b"\x00\x02" in data:
            os.write(master, bytes([31]))
        if data == b"\x07" or data.endswith(b"\x07"):
            os.write(master, bytes([0x80 | 12]))
threading.Thread(target=fake_wk, daemon=True).start()
w = MainWindow()
p = Path(sys.argv[2]) / "wpx.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="wpx-cw", mycall="DO2GGH")); db.close()
w.open_log(str(p))
rigcmds = []
class Rig:
    def submit(self, *a): rigcmds.append(list(a))
    def snapshot(self): return None
    def stop(self): pass
    def join(self, t=None): pass
w.rig = Rig(); w._rig_connected = lambda: True; w.rig_caps = None
w.keyer = winkey.WinKeyWorker(os.ttyname(slave)); w.keyer.start()
w.show(); app.processEvents()
w._updating = True; w.cb_mode.setCurrentText("CW"); w._updating = False
end = time.monotonic() + 3
while w._cw_wpm() == 0 and time.monotonic() < end:
    app.processEvents(); time.sleep(0.02)
out = {"wpm0": w._cw_wpm()}
w.run_macro(1, manual=True)
time.sleep(0.5); app.processEvents()
w.change_wpm(+1); out["wpm1"] = w._cw_wpm()
time.sleep(0.2)
w.escape_pressed(); time.sleep(0.3)
w.stop_rig(); time.sleep(0.2)
out["got"] = got.hex(); out["rig"] = rigcmds
print("OUT" + json.dumps(out))
w.close()
'''


def test_main_window_cw_over_winkey(tmp_path):
    import json
    import shutil
    import subprocess
    import sys
    import textwrap
    from pathlib import Path
    here = Path(__file__).parent
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    (data / "gogoham").mkdir(parents=True)
    (cfg / "gogoham").mkdir(parents=True)
    logs.mkdir()
    shutil.copy(here / "cty_sample.dat", data / "gogoham" / "cty.dat")
    (cfg / "gogoham" / "config.json").write_text(json.dumps({
        "rig_enabled": False, "wsjtx_enabled": False, "livescore_enabled": False,
        "rules_auto_update": False, "last_log": "", "language": "de"}))
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(GUI_SCRIPT), str(here.parent),
                        str(logs)], capture_output=True, text=True, env=env, timeout=60)
    lines = [ln[3:] for ln in r.stdout.splitlines() if ln.startswith("OUT")]
    assert lines, r.stderr[-2000:]
    o = json.loads(lines[-1])
    got = bytes.fromhex(o["got"])
    assert o["wpm0"] == 22 and o["wpm1"] == 24                 # Knopf 10+12, dann Bild auf (+2)
    assert got.startswith(b"\x00\x02")                          # Host Open
    assert b"CQ TEST DO2GGH DO2GGH TEST" in got                 # F1 geht an den WinKey …
    assert not any(c[0] == "send_morse" for c in o["rig"])      # … nicht ans Funkgerät
    assert bytes([0x02, 24]) in got                             # Tempo
    assert got.endswith(b"\x0A\x00\x03")                        # Abbruch, Host Close
    assert b"\x0A" in got[got.index(bytes([0x02, 24])):]        # Esc bricht ab
