"""0.6.4: eigener rigctld je Gerät, Port-Schutz, echtes Gerät, FT8-Programm-Sperre."""

import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gogoham import config as cfgmod
from gogoham import hamlib, rigprofiles
from gogoham.rig import port_in_use, query_model
from gogoham.wsjtx import (QSO_ONLY_TIMEOUT, TYPE_CLOSE, TYPE_HEARTBEAT, TYPE_LOGGED_ADIF,
                           TYPE_STATUS, ProgramActivity, build_logged_adif_packet, build_packet,
                           parse_header, wsjtx_direct_cat)

HERE = Path(__file__).parent


# ------------------------------------------------------------ Grundeinstellung
def test_no_default_rig_for_new_users():
    assert cfgmod.DEFAULTS["rig_model"] == 0 and cfgmod.DEFAULTS["rig_device"] == ""
    cfg = cfgmod.copy.deepcopy(cfgmod.DEFAULTS)
    assert rigprofiles.ensure_profiles(cfg) == []
    assert rigprofiles.active(cfg) is None


def test_old_profiles_get_own_ports():
    cfg = {"rig_host": "127.0.0.1", "rig_port": 4532, "rig_autostart": True, "rig_profile": 1,
           "rig_profiles": [{"name": "IC-7300", "model": 3073, "device": "/dev/ttyUSB0",
                             "baud": 115200, "extra": ""},
                            {"name": "dummy", "model": 1, "device": "", "baud": 115200,
                             "extra": ""}]}
    profs = rigprofiles.ensure_profiles(cfg)
    assert [p["port"] for p in profs] == [4532, 4533]
    assert all(p["start"] for p in profs)
    rigprofiles.apply_profile(cfg, 1)
    assert cfg["rig_port"] == 4533 and cfg["rig_model"] == 1
    assert rigprofiles.free_port(cfg) == 4534


# ------------------------------------------------------------ FT8-Programme
def test_parse_header():
    assert parse_header(build_packet(TYPE_HEARTBEAT, "JTDX")) == (TYPE_HEARTBEAT, "JTDX")
    assert parse_header(build_logged_adif_packet("<call:4>W1AW <eor>", "WSJT-X"))[0] == \
        TYPE_LOGGED_ADIF
    assert parse_header(b"<call:4>W1AW <eor>") is None


def test_activity_heartbeat_close_and_timeouts():
    a = ProgramActivity()
    assert a.active(0) is None
    a.packet(TYPE_HEARTBEAT, "WSJT-X", now=100)
    assert a.active(101) == "WSJT-X"
    assert a.active(129) == "WSJT-X"            # 29 s ohne Meldung: noch aktiv
    assert a.active(131) is None                # > 30 s: Steuerung zurück
    a.packet(TYPE_STATUS, "WSJT-X", now=200)
    a.packet(TYPE_CLOSE, "WSJT-X", now=201)
    assert a.active(201) is None                # Abmeldung: sofort zurück
    # Programm, das nur QSOs schickt: 2 Minuten
    a.packet(None, "FT8-Programm", now=300)
    assert a.active(300 + QSO_ONLY_TIMEOUT - 1) == "FT8-Programm"
    assert a.active(300 + QSO_ONLY_TIMEOUT + 1) is None
    # Wer sich einmal mit Heartbeat gemeldet hat, bleibt bei 30 s – auch nach einem QSO
    a.packet(TYPE_HEARTBEAT, "JTDX", now=400)
    a.packet(TYPE_LOGGED_ADIF, "JTDX", now=410)
    assert a.active(441) is None


def test_direct_cat_detection(tmp_path):
    (tmp_path / "WSJT-X.ini").write_text("[Configuration]\nRig=Icom IC-7300\n"
                                        "CATSerialPort=/dev/ttyUSB0\n", encoding="utf-8")
    (tmp_path / "JTDX.ini").write_text("[Configuration]\nRig=Hamlib NET rigctl\n"
                                      "CATSerialPort=\nCATNetworkPort=127.0.0.1:4532\n",
                                      encoding="utf-8")
    (tmp_path / "anderes.ini").write_text("Rig=etwas\n", encoding="utf-8")   # kein FT8-Programm
    found = wsjtx_direct_cat(str(tmp_path))
    assert [(Path(f).name, r, p) for f, r, p in found] == [("WSJT-X.ini", "Icom IC-7300",
                                                            "/dev/ttyUSB0")]


# ------------------------------------------------------------ echter rigctld (Dummy)
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


def test_port_and_model_query(dummy_rigctld):
    assert port_in_use("127.0.0.1", dummy_rigctld)
    assert query_model("127.0.0.1", dummy_rigctld) == 1
    assert query_model("127.0.0.1", 1) == 0                 # nichts da


def test_test_profile_existing_rigctld(dummy_rigctld):
    prof = {"model": 1, "host": "127.0.0.1", "port": dummy_rigctld, "start": False}
    res = hamlib.test_profile(prof)
    assert res.ok and "Dummy" in res.text
    # Profil für ein anderes Gerät auf diesem Port -> klare Warnung
    res = hamlib.test_profile({**prof, "model": 3073})
    assert not res.ok and "antwortet ein Dummy" in res.text
    # vorhandener rigctld erwartet, aber keiner da
    res = hamlib.test_profile({**prof, "port": 1})
    assert not res.ok and "läuft kein rigctld" in res.text


# ------------------------------------------------------------ Hauptfenster (Attrappe)
@pytest.fixture()
def win(tmp_path, monkeypatch):
    sys.path.insert(0, str(HERE))
    import fake_qt
    fake_qt.install()
    for m in [m for m in sys.modules if m.startswith("gogoham.gui")]:
        del sys.modules[m]
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path))
    import gogoham.cty as cty
    monkeypatch.setattr(cty.CtyDB, "load_default",
                        classmethod(lambda c: c.from_file(HERE / "cty_sample.dat")))
    cfg = cfgmod.load()
    cfg.update(rig_enabled=False, wsjtx_enabled=False, rig_profile=2, rig_profiles=[
        {"name": "IC-7300", "model": 3073, "device": "/dev/ttyUSB0", "baud": 115200,
         "extra": "", "port": 4532, "start": False},
        {"name": "Dummy", "model": 1, "device": "", "baud": 0, "extra": "", "port": 4533,
         "start": True},
        {"name": "IC-9700", "model": 3081, "device": "", "baud": 38400, "extra": "",
         "port": 4534, "start": True}])
    cfgmod.save(cfg)
    from gogoham.gui import main_window as mw
    started = []
    monkeypatch.setattr(mw, "start_rigctld", lambda *a, **k: started.append(a))
    w = mw.MainWindow()
    yield w, mw, started, fake_qt
    w.closeEvent(fake_qt.Stub())


def test_starts_with_last_used_profile(win):
    """0.8.31.1: zuletzt benutztes Profil (hier Platz 3) – samt seinen Einstellungen."""
    w, mw, _s, _fq = win
    assert w.cfg["rig_profile"] == 2 and w._profile_name() == "IC-9700"
    assert w.cfg["rig_model"] == 3081 and w.cfg["rig_port"] == 4534


def test_never_second_rigctld_on_busy_port(win, monkeypatch):
    w, mw, started, _fq = win
    w.cfg["rig_enabled"] = True
    monkeypatch.setattr(mw, "port_in_use", lambda h, p: p == 4533)   # 4533 ist belegt
    w.switch_profile(1)                                             # Dummy, „selbst starten“
    assert started == [] and w.rig_foreign
    assert "startet keinen zweiten" in w.statusBar().currentMessage()
    monkeypatch.setattr(mw, "port_in_use", lambda h, p: False)
    w.switch_profile(2)                                             # IC-9700, Port frei
    assert len(started) == 1 and started[0][0] == 3081 and started[0][3] == 4534


def test_cat_text_shows_real_device(win):
    _w, mw, _s, _fq = win
    text, style = mw.cat_text(3073, 3073, "IC-7300", None)
    assert text == "CAT: verbunden · IC-7300" and "1b8a3a" in style
    text, style = mw.cat_text(3073, 1, "Dummy", None)
    assert "IC-7300" in text and "Profil ist „Dummy“" in text and mw.ORANGE in style
    text, _st = mw.cat_text(3073, 3073, "IC-7300", "WSJT-X")
    assert "gesteuert von WSJT-X" in text and "nur Anzeige" in text


def test_ft8_program_locks_rig(win, monkeypatch):
    w, mw, _s, _fq = win
    sent = []

    class FakeRig:
        def submit(self, *a):
            sent.append(a)

        def snapshot(self):
            from gogoham.rig import RigState
            return RigState(connected=True, freq=14_074_000, mode="PKTUSB", model=3073)

        def stop(self):
            pass

        def join(self, *_a):
            pass

    class FakeWsjtx:
        who = "WSJT-X"
        error = ""

        def active_program(self):
            return self.who

        def stop(self):
            pass

    w.rig = FakeRig()
    w.wsjtx = FakeWsjtx()
    monkeypatch.setattr(mw, "wsjtx_direct_cat", lambda: [])
    w._update_lock()
    assert w.locked_by == "WSJT-X"
    w.qsy_khz(7074)                                   # Frequenz eintippen: gesperrt
    w._band_changed("40")                             # Band wählen: gesperrt
    w.cb_mode.setCurrentText("USB")
    w.cb_mode.setCurrentText("CW")                    # Mode wählen: gesperrt
    w.run_macro(1, manual=True)                       # F1: nichts senden
    w.toggle_autocq(True)                             # Auto-CQ: nicht starten
    assert sent == []
    assert not w.autocq_timer.isActive()
    w.wsjtx.who = None                                # WSJT-X beendet
    w._update_lock()
    assert w.locked_by is None
    w.qsy_khz(7074)
    assert sent == [("set_freq", 7_074_000)]          # GoGoHam steuert wieder
