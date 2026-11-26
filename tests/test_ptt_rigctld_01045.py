"""0.10.45: PTT über DTR/RTS schaltet der rigctld – GoGoHam öffnet die Schnittstelle nie selbst.

So bleibt pro Gerät nur EIN Programm an der Schnittstelle (Regel A), und WSJT-X, fldigi,
GoGoHome und GoGoHandy senden über „PTT über CAT“ genauso über DTR/RTS.
"""
import os

from gogoham import hamlib, rigdetect, rigprofiles, rigservice, winkey
from gogoham.rig import RigWorker


def _p(**kw):
    p = {"model": 1035, "device": "/dev/ttyUSB0", "baud": 38400, "port": 4534, "conn": "usb"}
    p.update(kw)
    return p


def test_ptt_args_cases():
    assert rigprofiles.ptt_args(_p()) == []                                     # PTT über CAT
    assert rigprofiles.ptt_args(_p(ptt_line="DTR", ptt_device="")) == []        # ohne Schnittstelle
    assert rigprofiles.ptt_args(_p(ptt_line="DTR", ptt_device="/dev/ttyUSB1")) == \
        ["--ptt-type=DTR", "--ptt-file=/dev/ttyUSB1"]                           # eigenes Interface
    assert rigprofiles.ptt_args(_p(ptt_line="RTS", ptt_device="/dev/ttyUSB0")) == \
        ["--ptt-type=RTS"]                                  # gleiche Schnittstelle: Hamlib teilt sie
    assert rigprofiles.ptt_args(_p(ptt_line="RTS", ptt_device="/dev/ttyUSB1",
                                   extra="-P DTR")) == []                       # eigene Option gewinnt
    assert rigprofiles.ptt_args(_p(ptt_line="DTR", ptt_device="/dev/mein port")) == []
    assert rigprofiles.ptt_args(_p(ptt_line="XYZ", ptt_device="/dev/ttyUSB1")) == []


def test_icom_same_port_stays_on_cat():
    # GoGoHandy-Brücke hält Icom-Geräte exklusiv – Icom sendet immer auch über CI-V
    ic = _p(model=3073, device="/dev/ttyUSB0", ptt_line="DTR", ptt_device="/dev/ttyUSB0")
    assert rigprofiles.ptt_args(ic) == []
    assert rigprofiles.ptt_args(dict(ic, ptt_device="/dev/ttyUSB1")) == \
        ["--ptt-type=DTR", "--ptt-file=/dev/ttyUSB1"]


def test_full_extra_and_service_carry_ptt():
    p = _p(ptt_line="DTR", ptt_device="/dev/ttyUSB1", lines="rts", civaddr="", extra="-v")
    assert rigprofiles.full_extra(p) == \
        "--set-conf=dtr_state=OFF,rts_state=ON --ptt-type=DTR --ptt-file=/dev/ttyUSB1 -v"
    text = rigservice.unit_text(p, exe="/usr/bin/rigctld")
    assert "--ptt-type=DTR --ptt-file=/dev/ttyUSB1" in text


def test_no_own_line_code_left():
    assert not hasattr(winkey, "LinePtt") and not hasattr(winkey, "ptt_test")
    w = RigWorker("127.0.0.1", 1)
    assert not hasattr(w, "ptt_line")
    sent = []
    w.client.ptt = lambda on: sent.append(on)
    w._ptt(True)
    w._ptt(False)
    assert sent == [True, False]                          # immer über rigctld


def _proc(tmp_path, pid, argv):
    d = tmp_path / str(pid)
    d.mkdir()
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")


def test_ptt_type_on_port(tmp_path):
    _proc(tmp_path, 10, ["/usr/bin/rigctld", "-m", "1035", "-r", "/dev/x", "-t", "4534"])
    _proc(tmp_path, 11, ["/usr/bin/rigctld", "-m", "1", "-t", "4535", "--ptt-type=rts"])
    _proc(tmp_path, 12, ["/usr/bin/rigctld", "-m", "1", "-P", "DTR"])           # Standard 4532
    _proc(tmp_path, 13, ["/usr/bin/python3", "-t", "4536"])
    assert rigdetect.ptt_type_on_port(4534, str(tmp_path)) == "RIG"
    assert rigdetect.ptt_type_on_port(4535, str(tmp_path)) == "RTS"
    assert rigdetect.ptt_type_on_port(4532, str(tmp_path)) == "DTR"
    assert rigdetect.ptt_type_on_port(4536, str(tmp_path)) is None
    assert rigdetect.ptt_type_on_port(4532, str(tmp_path / "fehlt")) is None


class _Client:
    def __init__(self):
        self.cmds = []

    def command(self, cmd, lines=1):
        self.cmds.append(cmd)
        return ["1"] if cmd == "t" else ["RPRT 0"]

    def close(self):
        pass


def test_ptt_test_warns_when_running_rigctld_lacks_line():
    c = _Client()
    prof = _p(host="127.0.0.1", ptt_line="DTR", ptt_device="/dev/ttyUSB1")
    res = hamlib.ptt_test(prof, seconds=0, client_factory=lambda h, p: c,
                          in_use=lambda h, p: True, ptt_type=lambda port: "RIG")
    assert res.ok and "nicht über DTR" in res.text and "--ptt-type=DTR" in res.text
    assert c.cmds[0] == "T 1" and c.cmds[-1] == "T 0"
    res = hamlib.ptt_test(prof, seconds=0, client_factory=lambda h, p: _Client(),
                          in_use=lambda h, p: True, ptt_type=lambda port: "DTR")
    assert res.ok and "Achtung" not in res.text


def test_rigctld_accepts_ptt_options(tmp_path):
    """Echter rigctld (falls installiert): nimmt die Optionen an und will die Leitung beim
    Öffnen schalten (an einer pty geht das nicht – das Senden selbst kann nur ein Gerät zeigen)."""
    import pty
    import shutil
    import subprocess
    import time
    import pytest
    exe = shutil.which("rigctld")
    if not exe:
        pytest.skip("kein rigctld")
    m, s = pty.openpty()
    dev = os.ttyname(s)
    try:
        p = subprocess.Popen([exe, "-m", "1", "-t", "45991", "-vvv",
                              *rigprofiles.ptt_args(_p(model=1, ptt_line="DTR", ptt_device=dev))],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        time.sleep(1.5)
        p.terminate()
        err = p.communicate(timeout=5)[1].decode(errors="replace")
        assert "ser_set_dtr" in err and dev in err
    finally:
        os.close(m)
        os.close(s)
