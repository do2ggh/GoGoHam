"""0.8.16: Funkgerät erkennen (rigdetect) – nur lesend."""
import os
import pty
import threading

from gogoham import rigdetect as d
from gogoham.hamlib import RigModel

RIGS = [RigModel(3073, "Icom", "IC-7300"), RigModel(1035, "Yaesu", "FT-991"),
        RigModel(2037, "Kenwood", "TS-590SG"), RigModel(2029, "Elecraft", "K3")]


def test_parse_civ_skips_echo():
    echo = d.CIV_QUERY
    answer = bytes([0xFE, 0xFE, 0xE0, 0x94, 0x19, 0x00, 0x94, 0xFD])
    assert d.parse_civ(echo) is None
    assert d.parse_civ(echo + answer) == 0x94


def test_parse_cat():
    assert d.parse_cat(b"ID0570;") == "0570"
    assert d.parse_cat(b"?;") is None


def test_probe_bytes_never_transmit_on_old_yaesu():
    # alte Yaesu (5-Byte-Befehle): 0x08 = PTT ein, 0x0F/0x8F = Ein/Aus
    for b in d.CIV_QUERY + d.CAT_QUERY:
        assert b not in (0x08, 0x0F, 0x8F)


def test_usb_guess_and_model():
    assert d.usb_guess("/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_"
                       "Controller_IC-7300_03025959-if00-port0") == "IC-7300"
    assert d.usb_guess("/dev/ttyUSB0") == ""
    assert d.hamlib_model("FT 991", RIGS) == 1035


def _fake(answers):
    """answers: {(baud, query): bytes}"""
    calls = []

    def ex(path, baud, data, wait, rts=False):
        calls.append((baud, data, rts))
        return answers.get((baud, data, rts), answers.get((baud, data), b"") if not rts else b"")
    return ex, calls


def test_probe_icom_kenwood_yaesu_ambiguous_none():
    ex, calls = _fake({(19200, d.CIV_QUERY): d.CIV_QUERY + bytes([0xFE, 0xFE, 0xE0, 0x94,
                                                                   0x19, 0x00, 0x94, 0xFD])})
    r = d.probe("/x", ex)
    assert r.ok and r.name == "IC-7300" and r.baud == 19200
    ex, _ = _fake({(4800, d.CAT_QUERY): b"ID0570;"})
    assert d.probe("/x", ex).name == "FT-991"
    ex, _ = _fake({(115200, d.CAT_QUERY): b"ID023;"})
    assert d.probe("/x", ex).name == "TS-590SG"
    ex, _ = _fake({(38400, d.CAT_QUERY): b"ID017;"})
    r = d.probe("/x", ex)
    assert not r.ok and r.search == "Elecraft" and r.baud == 38400
    ex, calls = _fake({})
    assert not d.probe("/x", ex).ok
    assert {b for b, _, _ in calls} == set(d.PROBE_BAUDS)
    assert not any(rts for _, _, rts in calls)          # ohne Yaesu-Anschluss nie RTS


def test_probe_yaesu_with_rts_only_on_retry():
    # FT-891 ab Werk „CAT RTS = ON“: antwortet nur mit RTS (am Gerät so gemessen: 38400, ID0650;)
    ex, calls = _fake({(38400, d.CAT_QUERY, True): b"ID0650;"})
    r = d.probe("/x", ex, rts_retry=True)
    assert r.ok and r.name == "FT-891" and r.baud == 38400
    assert all(data == d.CAT_QUERY for _, data, rts in calls if rts)   # mit RTS nie die Icom-Frage
    first_rts = next(i for i, c in enumerate(calls) if c[2])
    assert {b for b, _, rts in calls[:first_rts]} == set(d.PROBE_BAUDS)


def _fake_proc(tmp_path, argv, pid="4711"):
    p = tmp_path / pid
    p.mkdir()
    (p / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    (p / "fd").mkdir()
    return str(tmp_path)


def test_running_rigctld_is_used_and_port_not_touched(tmp_path):
    dev = tmp_path / "ttyUSB0"
    dev.write_text("")
    (tmp_path / "proc").mkdir()
    proc = _fake_proc(tmp_path / "proc", ["/usr/bin/rigctld", "-m", "3073", "-r", str(dev), "-s", "115200",
                       "--port=4533"])

    def no(*a):
        raise AssertionError("Schnittstelle darf nicht abgefragt werden")
    r = d.detect(str(dev), RIGS, exchange=no, proc=proc, verify=lambda port: True)
    assert r.ok and r.model == 3073 and r.baud == 115200 and r.rigctld_port == 4533


def test_held_port_uses_usb_name_only(tmp_path):
    dev = tmp_path / "usb-IC-705_x-if00-port0"
    dev.write_text("")
    proc = tmp_path / "proc"
    proc.mkdir()
    _fake_proc(proc, ["wsjtx"])
    os.symlink(str(dev), proc / "4711" / "fd" / "3")

    def no(*a):
        raise AssertionError("Schnittstelle darf nicht abgefragt werden")
    rigs = RIGS + [RigModel(3085, "Icom", "IC-705")]
    r = d.detect(str(dev), rigs, exchange=no, proc=str(proc))
    assert r.ok and r.model == 3085 and r.baud == 0


def test_real_serial_exchange_with_simulated_icom():
    master, slave = pty.openpty()
    path = os.ttyname(slave)

    def radio():
        buf = b""
        while d.CIV_QUERY not in buf:
            buf += os.read(master, 64)
        os.write(master, bytes([0xFE, 0xFE, 0xE0, 0x94, 0x19, 0x00, 0x94, 0xFD]))
    t = threading.Thread(target=radio, daemon=True)
    t.start()
    try:
        r = d.detect(path, RIGS, proc="/nonexistent")
    finally:
        os.close(slave)
        os.close(master)
    assert r.ok and r.model == 3073 and r.baud == d.PROBE_BAUDS[0]
