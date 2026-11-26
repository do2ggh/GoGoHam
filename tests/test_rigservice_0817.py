"""0.8.17: Hintergrund-rigctld von GoGoHam, Nachprüfen und Übernehmen eines fremden rigctld."""
import os
import subprocess

from gogoham import rigdetect, rigservice as rs

BYID = "/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_x-if00-port0"
PROF = {"name": "FT-891", "model": 1036, "device": BYID, "baud": 4800, "extra": "",
        "host": "127.0.0.1", "port": 4533, "start": False, "service": True}


class Run:
    def __init__(self, rc=0):
        self.calls, self.rc = [], rc

    def __call__(self, cmd, timeout=30):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, self.rc(cmd) if callable(self.rc) else self.rc, "", "")


def test_unit_text_uses_fixed_name_and_restarts():
    t = rs.unit_text(PROF, exe="/usr/bin/rigctld")
    assert f"ExecStart=/usr/bin/rigctld -m 1036 -r {BYID} -s 4800 -t 4533\n" in t
    assert "Restart=always" in t and "WantedBy=default.target" in t
    assert '"/dev/x y"' in rs.unit_text(dict(PROF, device="/dev/x y"), exe="r")
    assert "100%%" in rs.unit_text(dict(PROF, extra="--set-conf=a=100%"), exe="r")


def test_sync_writes_restarts_only_changed_and_removes(tmp_path):
    run = Run()
    assert rs.sync([PROF, dict(PROF, port=4532, service=False)], run, str(tmp_path)) == []
    assert (tmp_path / "gogoham-rigctld-4533.service").exists()
    assert not (tmp_path / "gogoham-rigctld-4532.service").exists()
    assert ["systemctl", "--user", "restart", "gogoham-rigctld-4533.service"] in run.calls
    run = Run()
    rs.sync([PROF], run, str(tmp_path))                    # unverändert: kein Neustart
    assert not any("restart" in c for c in run.calls)
    assert ["systemctl", "--user", "start", "gogoham-rigctld-4533.service"] in run.calls
    run = Run()
    rs.sync([], run, str(tmp_path))                        # Profil gelöscht -> Dienst weg
    assert ["systemctl", "--user", "disable", "--now", "gogoham-rigctld-4533.service"] in run.calls
    assert not list(tmp_path.iterdir())
    run = Run(rc=lambda c: 1 if "restart" in c else 0)
    assert rs.sync([PROF], run, str(tmp_path))             # Fehler wird gemeldet


def _proc(tmp_path, pid, cgroup, uid):
    d = tmp_path / str(pid)
    d.mkdir(parents=True)
    (d / "cgroup").write_text(f"0::{cgroup}\n")
    (d / "status").write_text(f"Name:\trigctld\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
    return d


def test_owner_kinds(tmp_path):
    _proc(tmp_path, 10, "/system.slice/rigctld.service", 0)
    _proc(tmp_path, 11, "/user.slice/user-1000.slice/user@1000.service/app.slice/x.service", 1000)
    _proc(tmp_path, 12, "/user.slice/user-1000.slice/session-2.scope", 1000)
    assert rs.owner(10, str(tmp_path)) == {"kind": "system", "unit": "rigctld.service", "uid": 0}
    assert rs.owner(11, str(tmp_path))["kind"] == "user"
    assert rs.owner(12, str(tmp_path))["kind"] == "process"


def test_take_over_system_service_with_password_fallback(tmp_path, monkeypatch):
    d = _proc(tmp_path, 10, "/system.slice/rigctld.service", 0)
    monkeypatch.setattr(rs.shutil, "which", lambda x: "/usr/bin/" + x)

    def rc(cmd):
        if cmd[0] == "pkexec":
            for f in d.iterdir():
                f.unlink()
            d.rmdir()
            return 0
        return 1                                   # ohne Passwortfenster abgelehnt
    run = Run(rc)
    ok, unit = rs.take_over(10, run, str(tmp_path), wait=1)
    assert ok and unit == "rigctld.service"
    assert run.calls == [["systemctl", "disable", "--now", "rigctld.service"],
                         ["pkexec", "systemctl", "disable", "--now", "rigctld.service"]]
    _proc(tmp_path, 10, "/system.slice/rigctld.service", 0)
    ok, msg = rs.take_over(10, Run(1), str(tmp_path), wait=0.2)
    assert not ok and "rigctld.service" in msg


def test_take_over_own_process_and_foreign_user(tmp_path):
    d = _proc(tmp_path, 12, "/user.slice/session-2.scope", os.getuid())
    killed = []

    def kill(pid, sig):
        killed.append(pid)
        for f in d.iterdir():
            f.unlink()
        d.rmdir()
    assert rs.take_over(12, Run(), str(tmp_path), kill=kill, wait=1)[0] and killed == [12]
    _proc(tmp_path, 13, "/user.slice/session-9.scope", os.getuid() + 1)
    assert not rs.take_over(13, Run(), str(tmp_path), kill=kill, wait=0.2)[0]


def test_detect_does_not_trust_running_rigctld(tmp_path):
    dev = tmp_path / "ttyUSB0"
    dev.write_text("")
    proc = tmp_path / "proc"
    p = proc / "77"
    p.mkdir(parents=True)
    (p / "cmdline").write_bytes(b"/usr/bin/rigctld\0-m\x003073\0-r\0" + str(dev).encode() +
                                b"\0-s\x00115200\0")
    (p / "fd").mkdir()

    def no(*a):
        raise AssertionError("Schnittstelle darf nicht abgefragt werden")
    r = rigdetect.detect(str(dev), [], exchange=no, proc=str(proc), verify=lambda port: False)
    assert not r.ok and r.blocker["pid"] == 77 and r.blocker["port"] == 4532
    assert "antwortet ihm nicht" in r.text
    r = rigdetect.detect(str(dev), [], exchange=no, proc=str(proc), verify=lambda port: True)
    assert r.ok and r.rigctld_port == 4532


def test_appimage_uses_only_system_rigctld(tmp_path, monkeypatch):
    """Beta-AppImage: Dauerdienst nur mit eigenem Hamlib des Systems, nie der mitgelieferte."""
    import os
    from gogoham import rigservice
    app, sysbin = tmp_path / "app" / "usr" / "bin", tmp_path / "usr" / "bin"
    for d in (app, sysbin):
        d.mkdir(parents=True)
        (d / "rigctld").write_text("#!/bin/sh\n")
        (d / "rigctld").chmod(0o755)
    monkeypatch.setenv("APPDIR", str(tmp_path / "app"))
    assert rigservice.system_rigctld(str(app)) == ""
    assert rigservice.system_rigctld(f"{app}{os.pathsep}{sysbin}") == str(sysbin / "rigctld")
    monkeypatch.setenv("PATH", str(app))
    monkeypatch.setattr(rigservice.shutil, "which", lambda n: "/usr/bin/systemctl")
    ok = lambda cmd, t=30: rigservice.subprocess.CompletedProcess(cmd, 0, "running\n", "")  # noqa: E731
    assert not rigservice.available(ok)
    monkeypatch.setenv("PATH", f"{app}{os.pathsep}{sysbin}")
    assert rigservice.available(ok)
    monkeypatch.delenv("APPDIR")
    assert rigservice.system_rigctld(str(app)) == str(app / "rigctld")
