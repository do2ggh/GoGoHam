"""Funkgeräte (0.6.3): Hamlib-Liste, Fähigkeiten, Profile, Bänder je Gerät, Titel."""

import shutil
import sys
from pathlib import Path

import pytest

from gogoham import hamlib, rigprofiles

HERE = Path(__file__).parent

LIST = """ Rig #  Mfg                    Model                   Version         Status      Macro
     1  Hamlib                 Dummy                   20240709.0      Stable      RIG_MODEL_DUMMY
     4  FLRig                  FLRig                   20260130.0      Stable      RIG_MODEL_FLRIG
     5  TRXManager             TRXManager 5.7.630+     20210613.0      Stable      RIG_MODEL_TRXMANAGER_RIG
  1035  Yaesu                  FT-991                  20241118.18     Stable      RIG_MODEL_FT991
  3073  Icom                   IC-7300                 20250517.14     Stable      RIG_MODEL_IC7300
  3081  Icom                   IC-9700                 20250517.20     Stable      RIG_MODEL_IC9700
  3094  Icom                   IC-7300MK2              20250517.14     Beta        RIG_MODEL_IC7300MK2
"""

CAPS_9700 = """Caps dump for model: 3081
Model name:\tIC-9700
Mfg name:\tIcom
Backend status:\tStable
Port type:\tRS-232
Serial speed: 4800..38400 baud, 8N1, ctrl=NONE
TX ranges #1 for ITU1:
\t144000000 Hz - 146000000 Hz
\t\tVFO list: VFOA VFOB MEM
\t\tLow power: 0.5 W, High power: 100 W
\t430000000 Hz - 440000000 Hz
\t1240000000 Hz - 1300000000 Hz
RX ranges #1 for ITU1:
\t30000 Hz - 60000000 Hz
TX ranges #1 status for ITU1:\tOK (0)
Can send Morse:\tY
Can send Voice:\tN
"""


def test_parse_list_and_search():
    rigs = hamlib.parse_list(LIST)
    assert len(rigs) == 7
    assert [r.label for r in rigs[:2]] == ["FLRig – FLRig", "Hamlib – Dummy"]   # sortiert
    trx = next(r for r in rigs if r.model == 5)
    assert trx.name == "TRXManager 5.7.630+"
    mk2 = next(r for r in rigs if r.model == 3094)
    assert mk2.status == "Beta" and mk2.mfg == "Icom"
    assert [r.model for r in hamlib.filter_rigs(rigs, "9700")] == [3081]
    assert [r.model for r in hamlib.filter_rigs(rigs, "ft991")] == [1035]     # ohne Bindestrich
    assert [r.model for r in hamlib.filter_rigs(rigs, "icom 7300")] == [3073, 3094]
    assert [r.model for r in hamlib.filter_rigs(rigs, "mk2")] == [3094]
    assert [r.model for r in hamlib.filter_rigs(rigs, "3073")] == [3073]       # Hamlib-Nummer
    assert len(hamlib.filter_rigs(rigs, "")) == 7


def test_parse_caps_bands_bauds():
    c = hamlib.parse_caps(3081, CAPS_9700)
    assert c.name == "IC-9700" and c.mfg == "Icom" and c.serial
    assert (c.speed_min, c.speed_max) == (4800, 38400)
    assert c.bauds() == [4800, 9600, 19200, 38400]
    assert c.bands() == ["2", "70cm", "23cm"]          # nur Sendebereiche, kein RX 30 kHz–60 MHz
    assert c.can_morse and not c.can_voice


def test_caps_without_ranges():
    c = hamlib.parse_caps(4, "Model name:\tFLRig\nPort type:\tNetwork link\n")
    assert c.bands() == [] and not c.serial
    assert c.bauds() == hamlib.STANDARD_BAUDS


def test_port_hint():
    assert "Enhanced" in hamlib.port_hint("/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_"
                                          "USB_to_UART_Bridge_Controller_00A5-if00-port0")
    assert "Standard" in hamlib.port_hint("/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_"
                                          "USB_to_UART_Bridge_Controller_00A5-if01-port0")
    assert hamlib.port_hint("/dev/ttyUSB0") == ""


@pytest.mark.skipif(not shutil.which("rigctl"), reason="Hamlib nicht installiert")
def test_real_hamlib_and_dummy_connection():
    rigs = hamlib.list_rigs()
    assert len(rigs) > 100
    assert hamlib.find_model(3073).name == "IC-7300"
    caps = hamlib.rig_caps(3073)
    assert "20" in caps.bands() and "2" not in caps.bands() and caps.speed_max == 115200
    res = hamlib.test_connection(1, "", 0)       # Hamlib-Dummy: liest nur Frequenz/Mode
    assert res.ok and "kHz" in res.text
    bad = hamlib.test_connection(3073, "/dev/gibt-es-nicht", 115200, timeout=8)
    assert not bad.ok


def test_profiles_migration_and_switch():
    cfg = {"rig_model": 3073, "rig_device": "/dev/ttyUSB0", "rig_baud": 115200, "rig_extra": ""}
    profs = rigprofiles.ensure_profiles(cfg)
    assert len(profs) == 1 and profs[0]["model"] == 3073 and profs[0]["device"] == "/dev/ttyUSB0"
    assert profs[0]["name"]                                    # z. B. "IC-7300"
    cfg["rig_profiles"].append({"name": "IC-9700 UKW", "model": 3081, "device": "/dev/ttyUSB1",
                                "baud": 38400, "extra": ""})
    rigprofiles.apply_profile(cfg, 1)
    assert (cfg["rig_model"], cfg["rig_device"], cfg["rig_baud"]) == (3081, "/dev/ttyUSB1", 38400)
    assert rigprofiles.active(cfg)["name"] == "IC-9700 UKW"
    # kaputter Index und zu viele Profile werden repariert
    cfg["rig_profile"] = 7
    cfg["rig_profiles"] += [dict(profs[0]) for _ in range(5)]
    rigprofiles.ensure_profiles(cfg)
    assert len(cfg["rig_profiles"]) == 5 and cfg["rig_profile"] == 0     # fünf ab 0.10.4


# ------------------------------------------------------------ mit Qt-Attrappe
@pytest.fixture()
def fq():
    sys.path.insert(0, str(HERE))
    import fake_qt
    fake_qt.install()
    for m in [m for m in sys.modules if m.startswith("gogoham.gui")]:
        del sys.modules[m]
    return fake_qt


def test_rig_dialog_profiles(fq, monkeypatch):
    rigs = tuple(hamlib.parse_list(LIST))
    monkeypatch.setattr(hamlib, "list_rigs", lambda: rigs)
    monkeypatch.setattr(hamlib, "find_model", lambda m: next((r for r in rigs if r.model == m), None))
    monkeypatch.setattr(hamlib, "rig_caps",
                        lambda m: hamlib.parse_caps(3081, CAPS_9700) if m == 3081 else None)
    monkeypatch.setattr(hamlib, "serial_ports", lambda: ["/dev/ttyUSB0"])
    from gogoham.gui.dialogs import RigDialog
    cfg = {"rig_enabled": True, "rig_autostart": True, "rig_host": "127.0.0.1", "rig_port": 4532,
           "rig_model": 3073, "rig_device": "/dev/ttyUSB0", "rig_baud": 115200, "rig_extra": ""}
    dlg = RigDialog(cfg)
    assert dlg.model.currentData() == 3073
    assert dlg.baud.currentData() == 115200
    assert dlg.profile.count() == 5                  # fünf Plätze ab 0.10.4
    # Profil 2 anlegen: IC-9700 suchen und wählen
    dlg.profile.setCurrentIndex(1)
    dlg.search.type("9700")
    assert [dlg.model.itemText(i) for i in range(1, dlg.model.count())] == ["Icom – IC-9700"]
    assert dlg.model.currentData() == 3081                    # erster Treffer vorgeschlagen
    assert dlg.baud.currentData() == 38400                     # höchste laut Hamlib
    assert "70 cm" in dlg.info.text() and "Sprachspeicher über CAT: nein" in dlg.info.text()
    dlg.name.setText("IC-9700 UKW")
    dlg.accept()
    assert [p["name"] for p in cfg["rig_profiles"]] == ["IC-7300", "IC-9700 UKW"]
    assert cfg["rig_profile"] == 1 and cfg["rig_model"] == 3081 and cfg["rig_baud"] == 38400


def test_mainwindow_title_profiles_bands(fq, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path))
    import gogoham.cty as cty
    monkeypatch.setattr(cty.CtyDB, "load_default",
                        classmethod(lambda c: c.from_file(HERE / "cty_sample.dat")))
    caps = {3073: hamlib.RigCaps(3073, "IC-7300", tx_ranges=[(1_800_000, 54_000_000)],
                                 can_morse=True, can_voice=True),
            3081: hamlib.parse_caps(3081, CAPS_9700)}
    monkeypatch.setattr(hamlib, "rig_caps", lambda m: caps.get(m))
    import gogoham.config as cfgmod
    cfg = cfgmod.load()
    cfg.update(rig_enabled=False, wsjtx_enabled=False, rig_profiles=[
        {"name": "IC-7300 KW", "model": 3073, "device": "/dev/ttyUSB0", "baud": 115200, "extra": ""},
        {"name": "IC-9700 UKW", "model": 3081, "device": "/dev/ttyUSB1", "baud": 38400, "extra": ""}])
    cfgmod.save(cfg)
    from gogoham.gui import main_window as mw
    monkeypatch.setattr(mw, "start_rigctld", lambda *a, **k: None)
    w = mw.MainWindow()
    try:
        assert "70cm" in [w.cb_band.itemText(i) for i in range(w.cb_band.count())]   # ohne CAT: alle
        w.cfg["rig_enabled"] = True
        w.cfg["rig_autostart"] = False
        w.switch_profile(1)
        assert w.cfg["rig_model"] == 3081 and w._profile_name() == "IC-9700 UKW"
        assert [w.cb_band.itemText(i) for i in range(w.cb_band.count())] == ["2", "70cm", "23cm"]
        assert cfgmod.load()["rig_profile"] == 1      # 0.8.31.1: Umschalten wird gemerkt
        w.switch_profile(0)
        bands = [w.cb_band.itemText(i) for i in range(w.cb_band.count())]
        assert "20" in bands and "70cm" not in bands
    finally:
        w.closeEvent(fq.Stub())


def test_window_title():
    from gogoham import APP_TITLE
    assert APP_TITLE == "GoGoHam by DO2GGH"


def test_rig_dialog_detect_0816(fq, monkeypatch):
    rigs = tuple(hamlib.parse_list(LIST))
    monkeypatch.setattr(hamlib, "list_rigs", lambda: rigs)
    monkeypatch.setattr(hamlib, "find_model", lambda m: next((r for r in rigs if r.model == m), None))
    monkeypatch.setattr(hamlib, "rig_caps", lambda m: None)
    monkeypatch.setattr(hamlib, "serial_ports", lambda: ["/dev/ttyUSB0"])
    from gogoham import rigdetect
    from gogoham.gui.dialogs import RigDialog
    cfg = {"rig_enabled": True, "rig_autostart": True, "rig_host": "127.0.0.1", "rig_port": 4532,
           "rig_model": 0, "rig_device": "", "rig_baud": 0, "rig_extra": ""}
    dlg = RigDialog(cfg)
    dlg.detect_fn = lambda p: rigdetect.Detection(True, "", name="IC-7300", model=3073,
                                                  baud=115200, device=p, rigctld_port=4532)
    dlg._detect()
    assert dlg.model.currentData() == 3073 and dlg.baud.currentData() == 115200
    assert dlg.device.currentText() == "/dev/ttyUSB0" and dlg.name.text() == "IC-7300"
    assert dlg.startmode.currentData() == "external" and dlg.port.value() == 4532
    assert "Erkannt: IC-7300" in dlg.test_result.text()
    # nicht eindeutig: Suche wird vorbelegt, nichts stillschweigend gewählt außer Vorschlag
    dlg.detect_fn = lambda p: rigdetect.Detection(False, "unklar", device=p, search="9700")
    dlg._detect()
    assert dlg.search.text() == "9700" and dlg.model.currentData() == 3081
    assert dlg.test_result.text().startswith("✘ unklar")


def test_rig_dialog_take_over_0817(fq, monkeypatch):
    rigs = tuple(hamlib.parse_list(LIST)) + (hamlib.RigModel(1036, "Yaesu", "FT-891"),)
    monkeypatch.setattr(hamlib, "list_rigs", lambda: rigs)
    monkeypatch.setattr(hamlib, "find_model", lambda m: next((r for r in rigs if r.model == m), None))
    monkeypatch.setattr(hamlib, "rig_caps", lambda m: None)
    yaesu = "/dev/serial/by-id/usb-CP2105_Dual-if00-port0"
    monkeypatch.setattr(hamlib, "serial_ports", lambda: [yaesu])
    from gogoham import config, rigdetect, rigservice
    synced, taken = [], []
    monkeypatch.setattr(rigservice, "available", lambda run=None: True)
    monkeypatch.setattr(rigservice, "owner", lambda pid, proc="/proc": {"kind": "system",
                                                                        "unit": "rigctld.service", "uid": 0})
    monkeypatch.setattr(rigservice, "take_over", lambda pid, **k: (taken.append(pid), (True, "x"))[1])
    monkeypatch.setattr(rigservice, "sync", lambda profs, **k: synced.append([dict(p) for p in profs]) or [])
    monkeypatch.setattr(config, "save", lambda cfg: None)
    from gogoham.gui.dialogs import RigDialog
    ic = "/dev/serial/by-id/usb-CP2102_IC-7300_1-if00-port0"
    cfg = {"rig_enabled": True, "rig_profile": 0, "rig_profiles": [
        {"name": "IC-7300", "model": 3073, "device": ic, "baud": 115200, "extra": "",
         "host": "127.0.0.1", "port": 4532, "start": False}]}
    dlg = RigDialog(cfg)
    dlg.profile.setCurrentIndex(1)                        # neues Profil 2
    dlg.device.setCurrentText("")
    answers = [rigdetect.Detection(False, "blockiert", device=yaesu, blocker={
                   "pid": 99, "device": "/dev/ttyUSB0", "model": 3073, "baud": 115200, "port": 4532}),
               rigdetect.Detection(True, "", name="FT-891", model=1036, baud=4800, device=yaesu)]
    dlg.detect_fn = lambda p: answers.pop(0)
    dlg._detect()
    assert taken == [99]
    # Profil 1 hat sofort einen eigenen Hintergrund-rigctld auf Port 4532 (WSJT-X & Co.)
    assert synced and synced[0][0]["service"] and synced[0][0]["port"] == 4532
    assert cfg["rig_profiles"][0]["service"] is True
    assert cfg["rig_replaced_services"] == ["rigctld.service"]
    # Profil 2: FT-891, eigener Hintergrund-rigctld auf freiem Port
    assert dlg.model.currentData() == 1036 and dlg.baud.currentData() == 4800
    assert dlg.startmode.currentData() == "service" and dlg.port.value() == 4533
    dlg.accept()
    p2 = cfg["rig_profiles"][1]
    assert p2["service"] and not p2["start"] and p2["device"] == yaesu


def test_rig_dialog_free_slots_and_ptt_08172(fq, monkeypatch):
    rigs = tuple(hamlib.parse_list(LIST))
    monkeypatch.setattr(hamlib, "list_rigs", lambda: rigs)
    monkeypatch.setattr(hamlib, "find_model", lambda m: next((r for r in rigs if r.model == m), None))
    monkeypatch.setattr(hamlib, "rig_caps", lambda m: None)
    monkeypatch.setattr(hamlib, "serial_ports", lambda: ["/dev/ttyUSB0"])
    from gogoham.gui.dialogs import RigDialog
    cfg = {"rig_enabled": True, "rig_profiles": []}
    dlg = RigDialog(cfg)
    dlg.profile.setCurrentIndex(1)                          # erst Platz 2 belegen
    dlg.search.type("9700")
    dlg.accept()
    assert [(p["slot"], p["model"]) for p in cfg["rig_profiles"]] == [(1, 3081)]
    dlg = RigDialog(cfg)
    assert dlg.cur == 1 and dlg.model.currentData() == 3081
    assert "Start-Profil" not in dlg.profile.itemText(1) and "frei" in dlg.profile.itemText(0)
    called = []
    dlg.ptt_fn = lambda prof: called.append(prof) or hamlib.TestResult(True, "ok")
    dlg._test_ptt()                                         # Test-Qt antwortet „Ja“
    assert called and called[0]["model"] == 3081 and dlg.test_result.text() == "✔ ok"


def test_rig_dialog_net_hint_08173(fq, monkeypatch):
    rigs = tuple(hamlib.parse_list(LIST))
    monkeypatch.setattr(hamlib, "list_rigs", lambda: rigs)
    monkeypatch.setattr(hamlib, "find_model", lambda m: next((r for r in rigs if r.model == m), None))
    monkeypatch.setattr(hamlib, "rig_caps", lambda m: None)
    monkeypatch.setattr(hamlib, "serial_ports", lambda: [])
    from gogoham.gui.dialogs import RigDialog
    cfg = {"rig_enabled": True, "rig_profile": 0, "rig_profiles": [
        {"name": "FT-891", "model": 3073, "device": "/dev/x", "baud": 38400, "host": "127.0.0.1",
         "port": 4533, "start": True, "service": False, "slot": 0}]}
    dlg = RigDialog(cfg)
    assert dlg.net_hint.text() == "WS & Co.: „Hamlib NET rigctl“ mit 127.0.0.1:4533 – nur solange GoGoHam läuft"
    dlg.host.setText("192.168.1.20")
    dlg._set_mode("external")
    dlg._update_net_hint()
    assert dlg.net_hint.text() == "WS & Co.: „Hamlib NET rigctl“ mit 192.168.1.20:4533"


def test_rig_dialog_restarts_hanging_service_01043(fq, monkeypatch):
    """Regel C: hängender rigctld-Dienst (vor der Brücke gestartet) -> neu starten, nie abschalten."""
    rigs = tuple(hamlib.parse_list(LIST))
    monkeypatch.setattr(hamlib, "list_rigs", lambda: rigs)
    monkeypatch.setattr(hamlib, "find_model", lambda m: next((r for r in rigs if r.model == m), None))
    monkeypatch.setattr(hamlib, "rig_caps", lambda m: None)
    ic = "/dev/serial/by-id/usb-CP2102_IC-7300_1-if00-port0"
    monkeypatch.setattr(hamlib, "serial_ports", lambda: [ic])
    from gogoham import rigdetect, rigservice
    restarted, taken = [], []
    monkeypatch.setattr(rigservice, "restart", lambda pid, **k: (restarted.append(pid), (True, "rigctld-4532.service"))[1])
    monkeypatch.setattr(rigservice, "via_bridge", lambda rd, **k: True)
    monkeypatch.setattr(rigservice, "take_over", lambda pid, **k: (taken.append(pid), (True, "x"))[1])
    from gogoham.gui.dialogs import RigDialog
    blocked = rigdetect.Detection(False, "antwortet nicht", device=ic, blocker={
        "pid": 42, "device": "/run/user/1000/gogohandy/by-id/x", "model": 3073, "baud": 115200,
        "port": 4532})
    ok = rigdetect.Detection(True, "", name="IC-7300", model=3073, baud=115200, device=ic,
                             rigctld_port=4532)
    for answers, want_ok in (([blocked, ok], True), ([blocked] * 9, False)):
        dlg = RigDialog({"rig_enabled": True, "rig_profiles": []})
        dlg._sleep = lambda s: None
        dlg.detect_fn = lambda p, a=answers: a.pop(0)
        dlg._detect()
        assert taken == []                                    # nie abgeschaltet
        if want_ok:
            assert dlg.model.currentData() == 3073
        else:
            assert "GoGoHandy-Brücke" in dlg.test_result.text()
    assert restarted == [42, 42]
