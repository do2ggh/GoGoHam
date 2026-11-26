"""0.8.18.1: microHAM DXP erkennen – mit nachgebautem /sys (kein echtes Gerät)."""

import os


from gogoham import dxp, rigdetect


def make_sys(tmp_path, ttys, vid="0483", pid="a2f6", names=None, serial="DXP123"):
    """Nachgebautes /sys: ein USB-Gerät mit je einer CDC-Schnittstelle pro ttyACM."""
    sysfs = tmp_path / "sys"
    usb = sysfs / "devices" / "usb1" / "1-2"
    usb.mkdir(parents=True)
    (usb / "idVendor").write_text(vid + "\n")
    (usb / "idProduct").write_text(pid + "\n")
    (usb / "serial").write_text(serial + "\n")
    (sysfs / "class" / "tty").mkdir(parents=True)
    dev = tmp_path / "dev"
    dev.mkdir(exist_ok=True)
    paths = []
    for k, tty in enumerate(ttys):
        intf = usb / f"1-2:1.{2 * k + 3}"
        intf.mkdir()
        (intf / "bInterfaceNumber").write_text(f"{2 * k + 3:02x}\n")
        if names:
            (intf / "interface").write_text(names[k] + "\n")
        (sysfs / "class" / "tty" / tty).mkdir()
        os.symlink(intf, sysfs / "class" / "tty" / tty / "device")
        (dev / tty).write_text("")
        paths.append(str(dev / tty))
    return str(sysfs), paths


def test_usb_info_and_units(tmp_path):
    sysfs, paths = make_sys(tmp_path, ["ttyACM0", "ttyACM1", "ttyACM2"])
    i = dxp.usb_info(paths[1], sysfs)
    assert (i["vid"], i["pid"], i["iface"]) == ("0483", "a2f6", 5)
    assert dxp.is_dxp(paths[0], sysfs) and dxp.maybe_winkey(paths[0], sysfs)
    units = dxp.find_units(paths + [paths[0]], sysfs)              # doppelt → einmal
    assert len(units) == 1 and [p for _n, p, _m in units[0]] == paths


def test_other_device_is_no_dxp(tmp_path):
    sysfs, paths = make_sys(tmp_path, ["ttyACM0"], vid="10c4", pid="ea60")
    assert not dxp.is_dxp(paths[0], sysfs) and dxp.find_units(paths, sysfs) == []
    assert not dxp.maybe_winkey(paths[0], sysfs)


def test_roles_from_usb_names():
    unit = [(3, "/a", "DXP CAT"), (5, "/b", "DXP FSK"), (7, "/c", "DXP WinKey")]
    assert dxp.roles_from_names(unit) == {"cat": "/a", "fsk": "/b", "winkey": "/c"}
    assert dxp.roles_from_names([(3, "/a", "CDC"), (5, "/b", "CDC"), (7, "/c", "CDC")]) == {}


def det_ok(path):
    return rigdetect.Detection(True, "", name="IC-7300", model=3073, baud=19200, device=path)


def det_none(path):
    return rigdetect.Detection(False, "Keine Antwort", device=path)


def test_identify_winkey_first_never_cat_query_to_winkey():
    unit = [(3, "/dev/A", ""), (5, "/dev/B", ""), (7, "/dev/C", "")]
    order = []

    def probe_wk(p):
        order.append(("wk", p))
        return 31 if p == "/dev/B" else 0

    def detect(p):
        order.append(("cat", p))
        return det_ok(p) if p == "/dev/C" else det_none(p)
    r = dxp.identify(unit, probe_wk=probe_wk, detect=detect, held=lambda p: False)
    assert r.ok and (r.winkey, r.cat, r.fsk, r.version) == ("/dev/B", "/dev/C", "/dev/A", 31)
    assert r.detection.model == 3073
    first_cat = next(i for i, (k, _p) in enumerate(order) if k == "cat")
    assert all(k == "wk" for k, _p in order[:first_cat])          # erst WinKey suchen …
    assert ("cat", "/dev/B") not in order                         # … nie CAT-Fragen an ihn


def test_identify_radio_off_and_no_winkey():
    unit = [(3, "/dev/A", ""), (5, "/dev/B", ""), (7, "/dev/C", "")]
    r = dxp.identify(unit, probe_wk=lambda p: 23 if p == "/dev/A" else 0, detect=det_none,
                     held=lambda p: False)
    assert r.ok and r.winkey == "/dev/A" and r.cat == "" and "CAT" in r.text
    r = dxp.identify(unit, probe_wk=lambda p: 0, detect=det_ok, held=lambda p: False)
    assert not r.ok and not r.cat


def test_identify_skips_held_ports():
    unit = [(3, "/dev/A", ""), (5, "/dev/B", ""), (7, "/dev/C", "")]
    probed = []
    r = dxp.identify(unit, probe_wk=lambda p: probed.append(p) or (31 if p == "/dev/C" else 0),
                     detect=det_ok, held=lambda p: p == "/dev/A")
    assert "/dev/A" not in probed and r.winkey == "/dev/C"


def test_detect_guard_refuses_winkey_port(tmp_path, monkeypatch):
    sysfs, paths = make_sys(tmp_path, ["ttyACM0"])
    from gogoham import winkey
    monkeypatch.setattr(dxp, "maybe_winkey", lambda p, sysfs="/sys": True)
    monkeypatch.setattr(winkey, "probe", lambda p: 31)
    sent = []
    d = rigdetect.detect(paths[0], exchange=lambda *a, **k: sent.append(a) or b"",
                         proc=str(tmp_path / "proc"))
    assert not d.ok and "WinKey" in d.text and sent == []          # keine CAT-Frage
    monkeypatch.setattr(winkey, "probe", lambda p: 0)
    d = rigdetect.detect(paths[0], exchange=lambda *a, **k: sent.append(a) or b"",
                         proc=str(tmp_path / "proc"))
    assert sent                                                    # kein WinKey: normal fragen


def test_linux_hints(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    (proc / "77").mkdir(parents=True)
    (proc / "77" / "comm").write_text("ModemManager\n")
    f = tmp_path / "ttyACM0"
    f.write_text("")
    hints = dxp.linux_hints([str(f)], str(proc))
    assert len(hints) == 1 and "ID_MM_DEVICE_IGNORE" in hints[0][1] and "a2f6" in hints[0][1]
    monkeypatch.setattr(os, "access", lambda p, m: False)
    hints = dxp.linux_hints([str(f)], str(tmp_path / "leer"))
    assert len(hints) == 1 and hints[0][1].startswith("sudo usermod -aG ")


DIALOG_SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import dxp, hamlib, rigdetect, winkey
ports = ["/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyACM2"]
hamlib.serial_ports = lambda: ports
dxp.find_units = lambda p, sysfs="/sys": [[(3, ports[0], ""), (5, ports[1], ""), (7, ports[2], "")]]
dxp.linux_hints = lambda paths, proc="/proc": []
winkey.probe = lambda p: 31 if p == ports[2] else 0
winkey.held_here = lambda p: False
rigdetect.port_held = lambda p, proc="/proc": False
rigdetect.stable_name = lambda p: p
calls = []
def fake_detect(p, rigs=None, progress=None, wk_guard=True, **k):
    calls.append([p, wk_guard])
    if p == ports[0]:
        return rigdetect.Detection(True, "", name="IC-7300", model=3073, baud=19200, device=p)
    return rigdetect.Detection(False, "Keine Antwort", device=p)
rigdetect.detect = fake_detect
from gogoham.gui.dialogs import RigDialog
cfg = {"rig_enabled": True, "rig_autostart": True, "rig_host": "127.0.0.1", "rig_port": 4532,
       "rig_model": 0, "rig_device": "", "rig_baud": 0, "rig_extra": ""}
d = RigDialog(cfg)
d.device.setCurrentText("")
d._detect()
print("OUT" + json.dumps({"cw": d.cw_via.currentData(), "wk": d.wk_device.currentText(),
      "dev": d.device.currentText(), "model": d.model.currentData(), "calls": calls,
      "text": d.test_result.text()}))
'''


def test_dialog_fills_dxp(tmp_path):
    import json
    import subprocess
    import sys
    import textwrap
    from pathlib import Path
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HOME=str(tmp_path),
               XDG_CONFIG_HOME=str(tmp_path / "cfg"), XDG_DATA_HOME=str(tmp_path / "data"))
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(DIALOG_SCRIPT),
                        str(Path(__file__).parent.parent)], capture_output=True, text=True,
                       env=env, timeout=60)
    lines = [ln[3:] for ln in r.stdout.splitlines() if ln.startswith("OUT")]
    assert lines, r.stderr[-2000:]
    o = json.loads(lines[-1])
    assert o["cw"] == "winkey" and o["wk"] == "/dev/ttyACM2" and o["dev"] == "/dev/ttyACM0"
    assert o["model"] == 3073
    assert "/dev/ttyACM2" not in [p for p, _g in o["calls"]]      # nie CAT-Fragen an den WinKey
    assert all(not g for _p, g in o["calls"])
    assert "WK3.1" in o["text"] and "DTR = PTT" in o["text"]
