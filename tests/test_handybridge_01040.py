"""0.10.40: GoGoHandy-PC-Brücke mitbenutzen – Erkennen, Test, rigctld und Dienste über deren pty."""
import os

from gogoham import handybridge as hb, rigdetect, rigservice as rs
from gogoham.rigdetect import CIV_QUERY

NAME = "usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_IC-7300_03025959-if00-port0"
ICOM = {"name": "IC-7300", "model": 3073, "device": "/dev/serial/by-id/" + NAME, "baud": 115200,
        "extra": "", "host": "127.0.0.1", "port": 4532, "start": False, "service": True}


def _fake_proc(tmp_path, comm, target):
    proc = tmp_path / "proc"
    (proc / "4711" / "fd").mkdir(parents=True)
    (proc / "4711" / "comm").write_text(comm + "\n")
    os.symlink(target, proc / "4711" / "fd" / "3")
    return str(proc)


def test_pty_by_fixed_name(tmp_path):
    base = tmp_path / "gogohandy"
    (base / "by-id").mkdir(parents=True)
    pty = tmp_path / "pts1"
    pty.write_text("")
    os.symlink(pty, base / "by-id" / NAME)
    assert hb.pty_for(ICOM["device"], base=str(base)) == str(base / "by-id" / NAME)
    assert hb.resolve("/dev/serial/by-id/anderes", base=str(base)) == "/dev/serial/by-id/anderes"
    assert hb.pty_for("127.0.0.1:50001", base=str(base)) == ""       # Netzwerk: nie


def test_pty_by_model_only_when_bridge_holds(tmp_path, monkeypatch):
    dev = tmp_path / "ttyUSB9"
    dev.write_text("")
    assert hb.held_by_bridge(str(dev), proc=_fake_proc(tmp_path / "b", hb.COMM, dev))
    assert not hb.held_by_bridge(str(dev), proc=_fake_proc(tmp_path / "a", "rigctld", dev))
    base = tmp_path / "gogohandy"
    base.mkdir()
    (tmp_path / "pts1").write_text("")
    os.symlink(tmp_path / "pts1", base / "ic7300")
    path = "/dev/serial/by-id/usb-Icom_IC-7300_XYZ-if00-port0"    # Ausweichweg über das Modell
    monkeypatch.setattr(hb, "held_by_bridge", lambda p, proc="/proc": False)
    assert hb.pty_for(path, base=str(base)) == ""                 # fremder Halter: nicht umleiten
    monkeypatch.setattr(hb, "held_by_bridge", lambda p, proc="/proc": True)
    assert hb.pty_for(path, base=str(base)) == str(base / "ic7300")


def test_detect_via_bridge_reports_115200_and_keeps_device(tmp_path, monkeypatch):
    pty = str(tmp_path / "pts")
    open(pty, "w").close()
    monkeypatch.setattr(hb, "pty_for", lambda path, **kw: pty)
    dev = tmp_path / "ttyUSB9"
    dev.write_text("")
    seen = []

    def exchange(path, baud, data, wait, **kw):
        seen.append((path, baud))
        return b"\xfe\xfe\xe0\x94\x19\x00\x94\xfd" if data == CIV_QUERY else b""
    monkeypatch.setattr(rigdetect, "hamlib_model", lambda name, rigs=None: 3073)
    det = rigdetect.detect(str(dev), rigs=[], exchange=exchange, proc=str(tmp_path / "keins"))
    assert seen == [(pty, 115200)]                       # nur über die Brücke, nur 115200
    assert det.device == str(dev) and det.baud == 115200 and det.bridge
    assert det.ok and det.name == "IC-7300" and det.model == 3073
    assert "GoGoHandy" in rigdetect.describe(det)


def test_unit_falls_back_to_device_without_bridge():
    t = rs.unit_text(ICOM, exe="/usr/bin/rigctld")
    assert "After=gogohandy-bruecke.service" in t
    assert f"D={hb.root()}/by-id/{NAME}; [ -e \"$D\" ] || D=/dev/serial/by-id/{NAME};" in t
    assert "exec /usr/bin/rigctld -m 3073 -r \"$D\" -s 115200 -t 4532'" in t
    yaesu = rs.unit_text(dict(ICOM, model=1036, name="FT-891"), exe="/usr/bin/rigctld")
    assert "/bin/sh" not in yaesu and "gogohandy" not in yaesu   # nur Icom
    assert "/bin/sh" not in rs.unit_text(dict(ICOM, device="/dev/ttyUSB77"), exe="r")
