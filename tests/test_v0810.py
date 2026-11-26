"""0.8.10: tägliches Update beim Start, CW-Tempo mit Bild auf/ab."""

import json
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from gogoham import dailyupdate as du
from gogoham.rig import RigctldClient, RigWorker, port_in_use

HERE = Path(__file__).parent
ROOT = HERE.parent


# ------------------------------------------------------------ tägliches Update
def test_is_due_once_a_day():
    today = date(2026, 11, 5)
    assert du.is_due({}, today)
    assert not du.is_due({"daily_update_last": "2026-11-05"}, today)
    assert du.is_due({"daily_update_last": "2026-11-04"}, today)
    assert not du.is_due({"daily_update": False}, today)


def test_flags_monthly():
    today = date(2026, 11, 5)
    assert du.flags_due({}, today)
    assert not du.flags_due({"flags_last_check": "2026-10-20"}, today)
    assert du.flags_due({"flags_last_check": "2026-10-01"}, today)


def test_contest_running():
    cqww = {"month": 10, "start_hour": 0, "hours": 48}     # letztes volles Wochenende Oktober
    assert du.contest_running(cqww, datetime(2026, 10, 24, 12, 0))
    assert not du.contest_running(cqww, datetime(2026, 10, 26, 0, 0))   # Ende = 0 UTC Montag
    assert not du.contest_running(cqww, datetime(2026, 11, 5, 12, 0))
    assert not du.contest_running(None, datetime(2026, 10, 24, 12, 0))
    assert not du.contest_running({"kaputt": 1}, datetime(2026, 10, 24, 12, 0))


def test_offline_does_nothing(monkeypatch):
    monkeypatch.setattr(du, "_online", lambda t: False)
    called = []
    import gogoham.rulesupdate as ru
    monkeypatch.setattr(ru, "check_and_download", lambda **k: called.append(1))
    res = du.run(running=False, flags_due=True)
    assert res.offline and not called
    assert "Kein Internet" in res.summary()


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(du, "_online", lambda t: True)


def test_contest_running_keeps_rules_and_cty(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    import gogoham.cty as cty
    import gogoham.rulesupdate as ru
    calls = []
    monkeypatch.setattr(ru, "check_and_download", lambda **k: calls.append("rules"))
    monkeypatch.setattr(cty, "download", lambda **k: calls.append("cty"))
    cty.user_cty_path().parent.mkdir(parents=True, exist_ok=True)
    cty.user_cty_path().write_text("alt")
    monkeypatch.setattr(du, "remote_is_newer", lambda *a: True)
    res = du.run(running=True, flags_due=False)
    assert calls == []
    assert res.kept == ["Contest-Regeln", "Länderdatei"]
    assert "Contest läuft" in res.summary()


def test_only_what_was_there_before(monkeypatch, tmp_path):
    """Wer MASTER.SCP, DOK-Liste oder Flaggen nie hatte, bekommt sie nicht ungefragt."""
    _isolate(monkeypatch, tmp_path)
    import gogoham.dok as dok
    import gogoham.rulesupdate as ru
    import gogoham.scp as scp
    calls = []
    monkeypatch.setattr(ru, "check_and_download", lambda **k: ru.UpdateResult())
    monkeypatch.setattr(scp, "download", lambda **k: calls.append("scp"))
    monkeypatch.setattr(dok, "download", lambda **k: calls.append("dok"))
    res = du.run(running=False, flags_due=True)
    assert calls == [] and res.flags == [] and not res.cty
    assert res.summary() == "Tägliches Update: alles aktuell"


def test_existing_files_are_refreshed(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    import gogoham.dok as dok
    import gogoham.flags as flags
    import gogoham.rulesupdate as ru
    import gogoham.scp as scp
    calls = []
    monkeypatch.setattr(ru, "check_and_download", lambda **k: ru.UpdateResult())
    monkeypatch.setattr(scp, "download", lambda **k: calls.append("scp"))
    monkeypatch.setattr(dok, "download", lambda **k: calls.append("dok"))
    monkeypatch.setattr(dok, "age_days", lambda: 3)
    monkeypatch.setattr(du, "remote_is_newer", lambda *a: True)
    scp.user_scp_path().parent.mkdir(parents=True, exist_ok=True)
    scp.user_scp_path().write_text("K1ABC\n")
    flags.flags_dir().mkdir(parents=True)
    (flags.flags_dir() / "de.png").write_bytes(b"\x89PNG")
    res = du.run(running=True, flags_due=True)      # SCP/DOK auch im Contest
    assert calls == ["scp", "dok"] and res.scp and res.doks
    assert res.flags and "de" not in res.flags
    assert du.run(running=False, flags_due=False).flags == []


class _Handler(BaseHTTPRequestHandler):
    last_modified = "Wed, 04 Nov 2026 10:00:00 GMT"

    def do_HEAD(self):  # noqa: N802
        self.send_response(200)
        if self.last_modified:
            self.send_header("Last-Modified", self.last_modified)
        self.end_headers()

    def log_message(self, *a):
        pass


def test_remote_is_newer(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/cty.dat"
    try:
        p = tmp_path / "cty.dat"
        assert du.remote_is_newer(url, p, 3)                 # eigene fehlt
        p.write_text("x")
        import os
        old = datetime(2026, 11, 1).timestamp()
        os.utime(p, (old, old))
        assert du.remote_is_newer(url, p, 3)                 # Server neuer
        new = datetime(2026, 11, 5).timestamp()
        os.utime(p, (new, new))
        assert not du.remote_is_newer(url, p, 3)             # eigene ist aktuell
        _Handler.last_modified = ""
        assert du.remote_is_newer(url, p, 3)                 # Server sagt nichts → laden
    finally:
        _Handler.last_modified = "Wed, 04 Nov 2026 10:00:00 GMT"
        srv.shutdown()
    with pytest.raises(OSError):
        du.remote_is_newer("http://127.0.0.1:1/x", p, 1)     # kein Internet


# ------------------------------------------------------------ CW-Tempo (Dummy-rigctld)
@pytest.fixture()
def dummy_rigctld():
    if not shutil.which("rigctld"):
        pytest.skip("Hamlib nicht installiert")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen(["rigctld", "-m", "1", "-t", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    from gogoham.rig import query_model
    for _ in range(100):                 # bis der Dummy wirklich antwortet (nicht nur lauscht)
        if port_in_use("127.0.0.1", port) and query_model("127.0.0.1", port) == 1:
            break
        time.sleep(0.1)
    yield port
    proc.terminate()
    proc.wait(3)


def test_keyspd_get_set(dummy_rigctld):
    c = RigctldClient("127.0.0.1", dummy_rigctld)
    c.set_keyspd(28)
    assert c.get_keyspd() == 28
    c.close()


def test_worker_reads_wpm_only_in_cw(dummy_rigctld):
    c = RigctldClient("127.0.0.1", dummy_rigctld)
    c.set_mode("USB")
    c.set_keyspd(24)
    c.close()
    w = RigWorker("127.0.0.1", dummy_rigctld, poll=0.1)
    w.start()
    def until(cond, sec=5.0):            # warten statt fester Zeit (langsame Rechner)
        end = time.monotonic() + sec
        while time.monotonic() < end and not cond():
            time.sleep(0.05)
        return cond()

    try:
        assert until(lambda: w.snapshot().connected and w.snapshot().mode == "USB")
        time.sleep(0.3)
        assert w.snapshot().wpm == 0                                  # SSB: nicht gefragt
        w.submit("set_mode", "CW")
        assert until(lambda: w.snapshot().wpm == 24)
        w.submit("set_keyspd", 32)
        assert until(lambda: w.snapshot().wpm == 32)
    finally:
        w.stop()
        w.join(3)


# ------------------------------------------------------------ im echten Qt-Fenster
SCRIPT = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham.db import DEFAULT_META, LogDB
from gogoham.rig import RigState
from gogoham import dailyupdate as du
from gogoham.gui.main_window import MainWindow
MainWindow._welcome = lambda self: None
MainWindow._ask_scp = lambda self, *a, **k: None
w = MainWindow()
p = Path(sys.argv[2]) / "wpx.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="wpx-cw", mycall="DO2GGH")); db.close()
w.open_log(str(p))
import threading
sent = []
class Rig:
    lock = threading.Lock()
    state = RigState(connected=True, wpm=30, mode="CW")
    def submit(self, *a):
        if a[0] == "set_keyspd": sent.append(list(a))
    def snapshot(self): return RigState(**self.state.__dict__)
    def stop(self): pass
w.rig = Rig(); w._rig_connected = lambda: True; w.rig_caps = None
out = {}
w.cb_mode.setCurrentText("CW")
w.change_wpm(+1); w.change_wpm(+1); w.change_wpm(-1)
out["cw"] = sent[:]; out["label"] = w.lbl_sb_wpm.text()
sent.clear()
w.cb_mode.setCurrentText("USB")
w.change_wpm(+1)
out["ssb"] = sent[:]
w.cb_mode.setCurrentText("CW")
w.locked_by = "WSJT-X"
w.change_wpm(+1)
out["locked"] = sent[:]
w.locked_by = None
Rig.state.wpm = 60
w.change_wpm(+1)
out["max"] = sent[:]
# Ergebnis des täglichen Updates übernehmen
class D:
    flags_due = True
    result = du.DailyResult(offline=True)
    def is_alive(self): return False
w.daily = D(); w._finish_daily_update()
out["offline_last"] = w.cfg.get("daily_update_last", "")
out["offline_msg"] = w.statusBar().currentMessage()
d = D(); d.result = du.DailyResult(kept=["Länderdatei"])
w.daily = d; w._finish_daily_update()
out["ok_last"] = w.cfg.get("daily_update_last", "")
out["flags_last"] = w.cfg.get("flags_last_check", "")
out["ok_msg"] = w.statusBar().currentMessage()
print(json.dumps(out))
'''


def test_gui_wpm_and_daily_result(tmp_path):
    pytest.importorskip("PySide6")
    data = tmp_path / "data" / "gogoham"
    data.mkdir(parents=True)
    shutil.copy(HERE / "cty_sample.dat", data / "cty.dat")
    env = {"QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path),
           "XDG_CONFIG_HOME": str(tmp_path / "cfg"), "XDG_DATA_HOME": str(tmp_path / "data"),
           "PATH": "/usr/bin:/bin", "GOGOHAM_LANG": "de"}
    (tmp_path / "cfg" / "gogoham").mkdir(parents=True)
    (tmp_path / "cfg" / "gogoham" / "config.json").write_text(json.dumps(
        {"rig_enabled": False, "wsjtx_enabled": False, "language": "de"}))
    r = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT), str(tmp_path)],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["cw"] == [["set_keyspd", 32], ["set_keyspd", 34], ["set_keyspd", 32]]
    assert out["label"] == "CW 32 WpM"
    assert out["ssb"] == [] and out["locked"] == [] and out["max"] == []
    assert out["offline_last"] == "" and "Kein Internet" in out["offline_msg"]
    assert out["ok_last"] and out["flags_last"] and "Contest läuft" in out["ok_msg"]
