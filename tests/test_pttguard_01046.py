"""0.10.46: Sende-Wächter (Absturz/Hänger beim Senden → Empfang) und PTT-Leitung in einem
mitbenutzten Dienst eintragen."""
import os
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

from gogoham import pttguard, rigservice
from gogoham.rig import RigWorker

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "gogoham" / "pttguard.py"


class FakeRigctld:
    """Winziger rigctld-Nachbau: merkt sich alle Befehle, antwortet RPRT 0 (f/m mit Werten)."""

    def __init__(self):
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(8)
        self.port = self.srv.getsockname()[1]
        self.cmds: list[str] = []
        self.ptt = "0"
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                c, _a = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        f = c.makefile("rwb")
        try:
            for raw in f:
                cmd = raw.decode().strip()
                self.cmds.append(cmd)
                if cmd.startswith("T "):
                    self.ptt = cmd[2:]
                    out = "RPRT 0\n"
                elif cmd == "t":
                    out = self.ptt + "\n"
                elif cmd == "f":
                    out = "14025000\n"
                elif cmd == "m":
                    out = "CW\n500\n"
                elif cmd in ("\\get_info", "_"):
                    out = "Dummy\n"
                else:
                    out = "RPRT 0\n"
                f.write(out.encode())
                f.flush()
        except OSError:
            pass

    def wait_for(self, cmd, sec=10.0):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            if cmd in self.cmds:
                return True
            time.sleep(0.05)
        return False

    def close(self):
        self.srv.close()


def _guard(port, hang=None):
    args = [sys.executable, "-I", str(GUARD), "127.0.0.1", str(port)]
    if hang:
        args.append(str(hang))
    return subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            start_new_session=True)


def test_eof_while_sending_unkeys():
    fake = FakeRigctld()
    try:
        g = _guard(fake.port)
        g.stdin.write(b"1\n")
        g.stdin.flush()
        g.stdin.close()                                  # wie ein Absturz: Leitung zu
        assert g.wait(15) == 0
        assert fake.wait_for("T 0")
    finally:
        fake.close()


def test_eof_on_receive_does_nothing():
    fake = FakeRigctld()
    try:
        g = _guard(fake.port)
        g.stdin.write(b"1\n0\n")
        g.stdin.flush()
        g.stdin.close()
        assert g.wait(5) == 0
        time.sleep(0.3)
        assert "T 0" not in fake.cmds                    # z. B. WSJT-X sendet gerade: nicht stören
    finally:
        fake.close()


def test_hang_unkeys_and_reports():
    fake = FakeRigctld()
    try:
        g = _guard(fake.port, hang=1.0)
        g.stdin.write(b"1\n")
        g.stdin.flush()
        assert fake.wait_for("T 0", 6)                   # kein Lebenszeichen mehr
        assert g.stdout.readline().strip() == b"off"
        g.stdin.close()
        assert g.wait(5) == 0
    finally:
        fake.close()


def test_heartbeat_keeps_sending():
    fake = FakeRigctld()
    try:
        g = _guard(fake.port, hang=1.0)
        g.stdin.write(b"1\n")
        g.stdin.flush()
        for _ in range(8):
            time.sleep(0.25)
            g.stdin.write(b".\n")
            g.stdin.flush()
        assert "T 0" not in fake.cmds
        g.stdin.write(b"0\n")
        g.stdin.close()
        g.wait(5)
    finally:
        fake.close()


def test_gui_heartbeat_counts_once_seen():
    fake = FakeRigctld()
    try:
        g = _guard(fake.port, hang=1.0)
        g.stdin.write(b"g\n1\n")                         # Oberfläche meldet sich – dann zählt sie
        g.stdin.flush()
        for _ in range(8):                               # nur der RigWorker lebt, die Oberfläche hängt
            time.sleep(0.25)
            g.stdin.write(b".\n")
            g.stdin.flush()
        assert fake.wait_for("T 0", 3)
        g.stdin.close()
        g.wait(5)
    finally:
        fake.close()


def test_unkey_gives_up_without_rigctld():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    t0 = time.monotonic()
    assert pttguard.unkey("127.0.0.1", port, tries=2, gap=0.1) is False
    assert time.monotonic() - t0 < 5


def test_crash_of_program_while_sending_unkeys(tmp_path):
    """Echter Ablauf: RigWorker in einem eigenen Prozess sendet, Prozess wird hart beendet
    (SIGKILL – kein Aufräumen möglich) → Wächter schaltet auf Empfang."""
    fake = FakeRigctld()
    script = tmp_path / "sender.py"
    script.write_text(textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(ROOT)!r})
        from gogoham.rig import RigWorker
        w = RigWorker("127.0.0.1", {fake.port}, poll=0.2)
        w.start()
        while not w.snapshot().connected:
            time.sleep(0.05)
        w.submit("ptt", True)
        while not w.snapshot().ptt:
            time.sleep(0.05)
        print("SENDET", flush=True)
        time.sleep(60)
    """))
    p = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE)
    try:
        assert p.stdout.readline().strip() == b"SENDET"
        assert fake.ptt == "1"
        os.kill(p.pid, signal.SIGKILL)
        p.wait(5)
        assert fake.wait_for("T 0", 15)
        assert fake.ptt == "0"
    finally:
        if p.poll() is None:
            p.kill()
        fake.close()


def test_worker_normal_stop_unkeys_itself_and_guard_ends():
    fake = FakeRigctld()
    try:
        w = RigWorker("127.0.0.1", fake.port, poll=0.2)
        w.start()
        end = time.monotonic() + 5
        while not w.snapshot().connected and time.monotonic() < end:
            time.sleep(0.05)
        g = w.guard
        assert g is not None and g.poll() is None
        w.submit("ptt", True)
        assert fake.wait_for("T 1")
        w.stop()
        w.join(5)
        assert fake.ptt == "0"
        assert g.wait(5) == 0
    finally:
        fake.close()


def test_listen_only_has_no_guard():
    w = RigWorker("127.0.0.1", 1, listen_only=True)
    w._start_guard()
    assert w.guard is None


# --------------------------------------------------- PTT-Leitung im mitbenutzten Dienst
def test_ptt_exec():
    assert rigservice.ptt_exec("/usr/bin/rigctld -m 1036 -r /dev/x -t 4534", ["--ptt-type=DTR"]) \
        == "/usr/bin/rigctld --ptt-type=DTR -m 1036 -r /dev/x -t 4534"
    assert rigservice.ptt_exec("/usr/bin/rigctld -P RTS -p /dev/y -m 1 --ptt-type=RTS -t 1",
                               ["--ptt-type=DTR", "--ptt-file=/dev/z"]) == \
        "/usr/bin/rigctld --ptt-type=DTR --ptt-file=/dev/z -m 1 -t 1"
    assert rigservice.ptt_exec("/bin/sh -c 'D=/run/a; exec /usr/bin/rigctld -m 3 -r \"$D\"'",
                               ["--ptt-type=RTS"]) == \
        "/bin/sh -c 'D=/run/a; exec /usr/bin/rigctld --ptt-type=RTS -m 3 -r \"$D\"'"
    assert rigservice.ptt_exec("/usr/bin/flrig", ["--ptt-type=DTR"]) == ""
    assert rigservice.ptt_exec("/usr/bin/rigctld -m 1", []) == ""


class _R:
    def __init__(self, rc=0):
        self.returncode, self.stdout, self.stderr = rc, "", ""


def _unit(tmp_path, dropin=False):
    d = tmp_path / "user"
    d.mkdir()
    (d / "rigctld-4534.service").write_text(
        "# übergeben\n[Unit]\nDescription=rigctld FT-891\n\n[Service]\n"
        "ExecStart=/usr/bin/rigctld -m 1036 -r /dev/ttyUSB0 -s 38400 -t 4534\nRestart=always\n")
    if dropin:
        (d / "rigctld-4534.service.d").mkdir()
        (d / "rigctld-4534.service.d" / "z.conf").write_text(
            "[Service]\nExecStart=\nExecStart=/usr/bin/rigctld -m 1036 -r /dev/ttyUSB0 -t 4534 -vv\n")
    units = rigservice.foreign_units(str(d), system_dirs=())
    assert len(units) == 1 and units[0]["port"] == 4534
    return d, units[0]


PROF = {"model": 1036, "device": "/dev/ttyUSB0", "port": 4534, "conn": "usb",
        "ptt_line": "DTR", "ptt_device": "/dev/ttyUSB1"}


def test_add_ptt_user_unit(tmp_path):
    d, u = _unit(tmp_path)
    assert rigservice.ptt_in_unit(u) == "RIG"
    calls = []
    errs = rigservice.add_ptt(u, PROF, run=lambda c, t=0: calls.append(c) or _R(), stamp="X")
    assert errs == []
    text = (d / "rigctld-4534.service").read_text()
    assert "ExecStart=/usr/bin/rigctld --ptt-type=DTR --ptt-file=/dev/ttyUSB1 -m 1036" in text
    assert rigservice.MARK in text and "Restart=always" in text
    assert (d / "rigctld-4534.service.gogoham-X.bak").read_text().count("--ptt") == 0
    assert calls == [["systemctl", "--user", "daemon-reload"],
                     ["systemctl", "--user", "restart", "rigctld-4534.service"]]
    assert rigservice.ptt_in_unit(u) == "DTR"
    # zweimal: Markierung nur einmal, alte PTT-Angabe ersetzt
    rigservice.add_ptt(u, dict(PROF, ptt_line="RTS"), run=lambda c, t=0: _R(), stamp="Y")
    text = (d / "rigctld-4534.service").read_text()
    assert text.count(rigservice.MARK) == 1 and "--ptt-type=RTS" in text and "DTR" not in text
    assert len(list(d.glob("*.bak"))) == 2                  # Backup-Dateien lädt systemd nicht
    assert len(rigservice.foreign_units(str(d), system_dirs=())) == 1


def test_add_ptt_changes_dropin_that_wins(tmp_path):
    d, u = _unit(tmp_path, dropin=True)
    assert rigservice.add_ptt(u, PROF, run=lambda c, t=0: _R(), stamp="X") == []
    assert "--ptt" not in (d / "rigctld-4534.service").read_text()
    conf = (d / "rigctld-4534.service.d" / "z.conf").read_text()
    assert "ExecStart=\n" in conf and "--ptt-type=DTR --ptt-file=/dev/ttyUSB1 -m 1036" in conf


def test_add_ptt_system_unit_uses_pkexec(tmp_path):
    d, u = _unit(tmp_path)
    u = dict(u, scope="system")
    calls = []
    errs = rigservice.add_ptt(u, PROF, run=lambda c, t=0: calls.append(list(c)) or _R(),
                              stamp="X", which=lambda n: "/usr/bin/pkexec")
    assert errs == [] and len(calls) == 1
    c = calls[0]
    assert c[:3] == ["pkexec", "/bin/sh", "-c"] and "systemctl restart" in c[3]
    assert c[5] == str(d / "rigctld-4534.service") and c[6].endswith(".gogoham-X.bak")
    assert not os.path.exists(c[7])                          # Zwischendatei wieder weg
    assert "--ptt" not in (d / "rigctld-4534.service").read_text()   # nur pkexec schreibt
    assert rigservice.add_ptt(u, PROF, run=lambda c, t=0: _R(), which=lambda n: None)


def test_add_ptt_reports_failure(tmp_path):
    d, u = _unit(tmp_path)
    r = _R(1)
    r.stderr = "Job failed"
    errs = rigservice.add_ptt(u, PROF, run=lambda c, t=0: r, stamp="X")
    assert errs and "Job failed" in errs[0]
    assert rigservice.add_ptt(dict(u, path=str(tmp_path / "fehlt.service")), PROF)
