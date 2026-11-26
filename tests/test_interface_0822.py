"""0.8.22: Ältere Geräte über Interface – DTR/RTS-Versorgung, CI-V-Adresse, eingebaute
COM-Schnittstellen, verständliche Fehlermeldungen, aufgeräumter Funkgeräte-Reiter."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham import hamlib, rigdetect, rigprofiles, rigservice

HERE = Path(__file__).parent


# --- Profil -> rigctld-Optionen ---------------------------------------------------------
def test_parse_civaddr():
    p = rigprofiles.parse_civaddr
    assert p("94") == 0x94 and p("0x94") == 0x94 and p("94h") == 0x94 and p(" A4 ") == 0xA4
    assert p("") is None and p("zz") is None and p("100") is None and p("00") is None
    assert p("E0") is None                       # E0 = Adresse des Computers, nicht des Geräts


def test_full_extra():
    base = {"extra": ""}
    assert rigprofiles.full_extra(base) == ""
    assert rigprofiles.full_extra({"lines": "both"}) == "--set-conf=dtr_state=ON,rts_state=ON"
    assert rigprofiles.full_extra({"lines": "rts"}) == "--set-conf=dtr_state=OFF,rts_state=ON"
    assert rigprofiles.full_extra({"lines": "off", "civaddr": "5e", "extra": "-v"}) == \
        "--set-conf=dtr_state=OFF,rts_state=OFF,civaddr=0x5E -v"
    assert rigprofiles.full_extra({"civaddr": "kaputt"}) == ""       # ungültig: weglassen


def test_profile_and_service_use_full_extra():
    cfg = {"rig_profiles": [{"slot": 0, "name": "IC-706", "model": 3011, "device": "/dev/ttyUSB0",
                             "baud": 9600, "extra": "", "lines": "both", "civaddr": "58"}],
           "rig_profile": 0}
    rigprofiles.ensure_profiles(cfg)
    assert cfg["rig_extra"] == "--set-conf=dtr_state=ON,rts_state=ON,civaddr=0x58"
    unit = rigservice.unit_text(dict(cfg["rig_profiles"][0], port=4532), exe="/usr/bin/rigctld")
    assert "--set-conf=dtr_state=ON,rts_state=ON,civaddr=0x58" in unit


def test_old_profiles_get_defaults():
    cfg = {"rig_profiles": [{"slot": 0, "name": "x", "model": 3073}], "rig_profile": 0}
    p = rigprofiles.ensure_profiles(cfg)[0]
    assert p["lines"] == "" and p["civaddr"] == ""
    assert cfg["rig_extra"] == ""


def test_interface_problem(tmp_path):
    dev = str(tmp_path / "ttyUSB0")
    other = str(tmp_path / "ttyUSB1")
    ok = {"device": dev, "lines": "rts", "ptt_line": "RTS", "ptt_device": other}
    assert rigprofiles.interface_problem(ok) == ""
    bad = dict(ok, ptt_device=dev)                   # RTS versorgt UND tastet -> Dauersenden
    assert "dauernd senden" in rigprofiles.interface_problem(bad)
    assert rigprofiles.interface_problem(dict(ok, ptt_device=dev, lines="dtr")) == ""
    assert "ungültig" in rigprofiles.interface_problem({"civaddr": "xyz"})


# --- Schnittstellen und Fehlermeldungen ---------------------------------------------------
def test_builtin_serial_ports(tmp_path):
    sysd, devd = tmp_path / "sys", tmp_path / "dev"
    devd.mkdir()
    for name, typ in (("ttyS0", "4"), ("ttyS1", "0"), ("ttyS10", "4"), ("ttyS2", "4")):
        (sysd / name).mkdir(parents=True)
        (sysd / name / "type").write_text(typ + "\n")
        if name != "ttyS2":                          # ttyS2: Hardware, aber kein /dev-Eintrag
            (devd / name).write_text("")
    assert hamlib.builtin_serial_ports(str(sysd), str(devd)) == [str(devd / "ttyS0"),
                                                                 str(devd / "ttyS10")]


def test_port_problem_and_explain(tmp_path):
    assert "gibt es nicht" in hamlib.port_problem(str(tmp_path / "fehlt"))
    assert hamlib.port_problem("localhost:4532") == ""
    f = tmp_path / "ttyUSB9"
    f.write_text("")
    assert hamlib.port_problem(str(f)) == ""
    if os.geteuid() != 0:
        f.chmod(0)
        msg = hamlib.port_problem(str(f))
        assert "Keine Berechtigung" in msg and "usermod -aG" in msg
        r = rigdetect.detect(str(f), rigs=[], proc=str(tmp_path))
        assert not r.ok and "Keine Berechtigung" in r.text
    assert "anderen Programm" in hamlib.explain_error("rig_open: Device or resource busy")
    assert hamlib.explain_error("irgendwas") == ""


def test_test_connection_reports_missing_port(tmp_path, monkeypatch):
    monkeypatch.setattr(hamlib, "rigctl_exe", lambda: "/bin/true")
    r = hamlib.test_connection(3073, str(tmp_path / "ttyUSB7"), 9600)
    assert not r.ok and "gibt es nicht" in r.text


# --- Erkennung -----------------------------------------------------------------------------
def test_probe_tries_slow_bauds_and_passes_power():
    seen = []

    def exchange(path, baud, data, wait, rts=False, power=frozenset()):
        seen.append((baud, tuple(sorted(power))))
        return b""
    det = rigdetect.probe("/dev/x", exchange, power=frozenset({"DTR", "RTS"}))
    assert not det.ok and "Ältere Geräte" in det.text
    bauds = [b for b, _p in seen]
    assert 2400 in bauds and 1200 in bauds and bauds[-1] == 1200
    assert all(p == ("DTR", "RTS") for _b, p in seen)


def test_probe_without_power_keeps_old_call():
    """Ohne Versorgung wird exchange wie bisher aufgerufen (ohne power-Argument)."""
    def exchange(path, baud, data, wait, rts=False):
        return b"\xfe\xfe\xe0\x94\x19\x00\x94\xfd"
    det = rigdetect.probe("/dev/x", exchange)
    assert det.ok and det.name == "IC-7300"


def test_serial_exchange_on_pty_with_power():
    """Pseudo-Terminal hat keine Steuerleitungen: darf nicht abbrechen."""
    import pty
    master, slave = pty.openpty()
    try:
        out = rigdetect.serial_exchange(os.ttyname(slave), 9600, b"ID;", 0.05,
                                        power=frozenset({"DTR"}))
        assert out == b""
        assert os.read(master, 16) == b"ID;"
    finally:
        os.close(master)
        os.close(slave)


# --- Dialog ----------------------------------------------------------------------------------
SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import rigservice
rigservice.available = lambda run=None: False       # unabhängig vom Testrechner
from gogoham.gui.dialogs import RigDialog
cfg = {"rig_enabled": True, "rig_autostart": True, "rig_host": "127.0.0.1", "rig_port": 4532,
       "rig_model": 0, "rig_device": "", "rig_baud": 0, "rig_extra": "",
       "rig_profiles": [{"slot": 0, "name": "IC-7300", "model": 3073, "device": "/dev/ttyUSB0",
                         "baud": 115200, "extra": ""}], "rig_profile": 0}
d = RigDialog(cfg)
d.show(); app.processEvents()
out = {}
# Hauptseite: erweiterte Felder nicht sichtbar, Zusammenfassung „alles Standard“
out["main_hidden"] = [w.isVisibleTo(d) for w in (d.extra, d.lines, d.civaddr, d.cw_via,
                                                  d.startmode, d.ptt_via)]
out["main_shown"] = [w.isVisibleTo(d) for w in (d.profile, d.model, d.device, d.btn_detect,
                                                 d.baud, d.btn_test, d.btn_ptt, d.btn_adv)]
out["summary0"] = d.adv_summary.text()
# Icom: CI-V-Feld an, Standardadresse als Platzhalter
out["civ_icom"] = [d.civaddr.isEnabled(), d.civaddr.placeholderText()]
d.lines.setCurrentIndex(d.lines.findData("both"))
d.civaddr.setText("98")
out["warn"] = d.lines_warn.isVisibleTo(d.adv)
out["summary1"] = d.adv_summary.text()
d._store_slot()
out["stored"] = {k: d.slots[0][k] for k in ("lines", "civaddr")}
# OK übernimmt in die Einstellungen (rig_extra mit --set-conf)
out["apply"] = d.apply()
out["rig_extra"] = cfg["rig_extra"]
# Konflikt: RTS versorgt das Interface und schaltet PTT an derselben Schnittstelle
d.lines.setCurrentIndex(d.lines.findData("rts"))
d.ptt_via.setCurrentIndex(d.ptt_via.findData("RTS"))
d.ptt_device.setCurrentText("/dev/ttyUSB0")
out["conflict"] = [d.apply(), d.test_result.text()]
# Yaesu: kein CI-V
d.search.setText("FT-857"); d._search_changed("FT-857")
d.model.setCurrentIndex(max(0, d.model.findText("Yaesu – FT-857", )))
out["civ_yaesu"] = [d.model.currentText(), d.civaddr.isEnabled()]
# Fenster „Erweiterte Einstellungen“: passend groß, ohne abgeschnittene Texte
d.fit_advanced(); d.adv.show(); app.processEvents()
lw = d.lines_warn
out["warn_fits"] = lw.height() >= lw.heightForWidth(lw.width())
print("OUT" + json.dumps(out))
'''


def test_rig_dialog_layout(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HOME=str(tmp_path),
               XDG_CONFIG_HOME=str(tmp_path / "cfg"), XDG_DATA_HOME=str(tmp_path / "data"))
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent)],
                       capture_output=True, text=True, env=env, timeout=60)
    lines = [ln[3:] for ln in r.stdout.splitlines() if ln.startswith("OUT")]
    assert lines, r.stderr[-2000:]
    o = json.loads(lines[-1])
    assert o["main_hidden"] == [False] * 6
    assert o["main_shown"] == [True] * 8
    assert o["summary0"].startswith("Erweitert: alles Standard")
    assert o["civ_icom"] == [True, "94"]
    assert o["warn"] is True
    assert "Interface: DTR+RTS an" in o["summary1"] and "CI-V 98" in o["summary1"]
    assert o["stored"] == {"lines": "both", "civaddr": "98"}
    assert o["apply"] is True
    assert o["rig_extra"] == "--set-conf=dtr_state=ON,rts_state=ON,civaddr=0x98"
    assert o["conflict"][0] is False and "dauernd senden" in o["conflict"][1]
    assert "FT-857" in o["civ_yaesu"][0] and o["civ_yaesu"][1] is False
    assert o["warn_fits"] is True
