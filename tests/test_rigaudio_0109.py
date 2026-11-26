"""0.10.9: Soundkarte des Funkgeräts finden; WSJT-X/JTDX bekommen Rufzeichen, Locator, Soundkarte."""
import os
from pathlib import Path

from gogoham import extapps, rigaudio

SINKS = """Sink #845
\tState: SUSPENDED
\tName: alsa_output.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo
\tProperties:
\t\talsa.card = "4"
Sink #58
\tName: alsa_output.usb-Razer-00.stereo-chat
\tProperties:
\t\talsa.card = "3"
"""
SOURCES = """Source #9
\tName: alsa_output.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo.monitor
\tProperties:
\t\talsa.card = "4"
Source #846
\tName: alsa_input.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo
\tProperties:
\t\talsa.card = "4"
"""
OUT = "alsa_output.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo"
INP = "alsa_input.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo"


def fake_run(args, timeout=5):
    if "sinks" in args:
        return 0, SINKS
    if "sources" in args and "short" not in args:
        return 0, SOURCES
    return 0, f"846\t{INP}\tPipeWire\n"


def _sysfs(tmp_path, cards):
    """Nachgebautes /sys: IC-7300 am Verteiler 5-4 (CAT 5-4.1), weitere Karten nach Wunsch."""
    root = tmp_path / "sys"
    usb = root / "devices" / "pci0" / "usb5"
    tty_dev = usb / "5-4" / "5-4.1" / "5-4.1:1.0" / "ttyUSB0"
    tty_dev.mkdir(parents=True)
    (root / "class" / "tty" / "ttyUSB0").mkdir(parents=True)
    os.symlink(tty_dev, root / "class" / "tty" / "ttyUSB0" / "device")
    (root / "class" / "sound").mkdir(parents=True)
    for n, where, cid in cards:
        d = usb / where
        (d / f"{d.name}:1.0").mkdir(parents=True, exist_ok=True)
        c = root / "class" / "sound" / f"card{n}"
        c.mkdir()
        os.symlink(d / f"{d.name}:1.0", c / "device")
        (c / "id").write_text(cid + "\n")
    dev = tmp_path / "dev"
    dev.mkdir()
    (dev / "ttyUSB0").touch()
    os.symlink(dev / "ttyUSB0", dev / "ic7300")
    return str(root), str(dev / "ic7300")


def test_card_on_same_hub(tmp_path):
    sysfs, cat = _sysfs(tmp_path, [(4, "5-4/5-4.4", "CODEC"), (2, "5-2", "Mini")])
    # Achtung: realpath des CAT-Links endet auf „ttyUSB0“ → /sys/class/tty/ttyUSB0
    assert rigaudio.card_for_device(cat, sysfs) == 4
    out, inp, origin = rigaudio.for_profile({"device": cat}, run=fake_run, sysfs=sysfs)
    assert (out, inp, origin) == (OUT, INP, "auto")


def test_no_guess(tmp_path):
    # Headset am selben Tisch-Verteiler: kein „CODEC“ → nicht raten
    sysfs, cat = _sysfs(tmp_path, [(5, "5-4/5-4.3", "Headset")])
    assert rigaudio.card_for_device(cat, sysfs) is None
    # zwei Karten am Verteiler → nicht eindeutig
    sysfs2, cat2 = _sysfs(tmp_path / "b", [(4, "5-4/5-4.4", "CODEC"), (6, "5-4/5-4.2", "CODEC")])
    assert rigaudio.card_for_device(cat2, sysfs2) is None
    assert rigaudio.card_for_device("", sysfs) is None


def test_profile_choice_and_fallback(tmp_path):
    sysfs, cat = _sysfs(tmp_path, [])
    assert rigaudio.for_profile({"device": cat, "audio_out": OUT}, run=fake_run,
                                sysfs=sysfs) == (OUT, INP, "profile")
    assert rigaudio.for_profile({"device": cat}, OUT, run=fake_run, sysfs=sysfs)[2] == "fallback"
    assert rigaudio.for_profile({"device": cat}, run=fake_run, sysfs=sysfs) == ("", "", "")


def test_station_settings():
    cfg = {"station_defaults": {"mycall": "DO2GGH", "my_grid": "JN59me"},
           "voice_rig_out": OUT, "rig_profiles": [{"model": 1}]}
    seen = []

    def audio(prof, fallback):
        seen.append(fallback)
        return ("", "", "")
    st, origin = extapps.station_settings(cfg, None, {"model": 1}, audio=audio)
    assert st["mycall"] == "DO2GGH" and st["grid"] == "JN59me" and origin == ""
    assert seen == [OUT]                                  # ein Funkgerät → Sprachspeicher-Karte
    cfg["rig_profiles"].append({"model": 2})
    extapps.station_settings(cfg, {"mycall": "DL0ABC", "my_grid": "JO62"}, {}, audio=audio)
    assert seen[-1] == ""                                 # mehrere → nicht die globale Karte


def test_wanted_and_apply(tmp_path):
    st = {"mycall": "do2ggh", "grid": "jn59me", "sound_out": OUT, "sound_in": INP}
    keys = {k: v for k, v, _l in extapps.wanted("127.0.0.1", 4532, "127.0.0.1", 2237, st)}
    assert keys["MyCall"] == "DO2GGH" and keys["MyGrid"] == "JN59ME"
    assert keys["SoundInName"] == INP and keys["SoundOutName"] == OUT
    ini = tmp_path / "WS.ini"
    ini.write_text("[Configuration]\nMyCall=DL1XX\nSoundInName=alsa_input.pci-0000_0d_00.3"
                   ".analog-stereo\nAudioInputChannel=Mono\n")
    diff = dict(extapps.changes(ini, "127.0.0.1", 4532, "127.0.0.1", 2237, st))
    assert diff[extapps.tr("Rufzeichen: {v}", v="DO2GGH")] == "DL1XX"
    assert any(old == "0000 0d 00.3" for old in diff.values())     # lesbar gemacht
    extapps.apply(ini, "127.0.0.1", 4532, "127.0.0.1", 2237, st, now=0)
    cur = extapps.current(ini)
    assert cur["MyCall"] == "DO2GGH" and cur["SoundOutName"] == OUT
    assert cur["AudioInputChannel"] == "Mono"                      # Rest bleibt
    assert extapps.changes(ini, "127.0.0.1", 4532, "127.0.0.1", 2237, st) == []
    # ohne Stationsangaben: nur die Verbindung, wie bisher
    assert len(extapps.wanted("127.0.0.1", 4532, "127.0.0.1", 2237)) == 5


def test_nice_sound():
    assert extapps.nice_sound(OUT) == "Burr-Brown from TI USB Audio CODEC"
    assert extapps.nice_sound("hw:1") == "hw:1"


def test_real_system_does_not_crash():
    # auf jedem Rechner: darf nie abstürzen, auch ohne Funkgerät
    out, inp, origin = rigaudio.for_profile({"device": "/dev/gibtsnicht"})
    assert origin in ("", "auto")
    assert Path("/").exists()


DIALOG = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import rigservice
rigservice.available = lambda run=None: False
from gogoham.gui.dialogs import RigDialog
cfg = {"rig_enabled": True, "rig_autostart": True, "rig_host": "127.0.0.1", "rig_port": 4532,
       "rig_model": 0, "rig_device": "", "rig_baud": 0, "rig_extra": "",
       "rig_profiles": [{"slot": 0, "name": "FT-891", "model": 1036, "device": "/dev/gibtsnicht",
                         "baud": 38400, "extra": "", "audio_out": "alsa_output.usb-Digirig-00.x"}],
       "rig_profile": 0}
d = RigDialog(cfg)
d.show(); app.processEvents()
out = {"sel": d.audio_out.currentData(), "text": d.audio_out.currentText(),
       "hint": d.audio_hint.text()}
d.audio_out.setCurrentIndex(0); app.processEvents()
out["auto_hint"] = d.audio_hint.text()
d._store_slot()
out["stored"] = d.slots[0]["audio_out"]
print("OUT" + json.dumps(out))
'''


def test_profile_dialog_sound_field(tmp_path):
    import json
    import subprocess
    import sys
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XDG_CONFIG_HOME=str(tmp_path),
               XDG_DATA_HOME=str(tmp_path))
    r = subprocess.run([sys.executable, "-c", DIALOG, str(Path(__file__).parent.parent)],
                       capture_output=True, text=True, env=env, timeout=60)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("OUT")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[0][3:])
    assert o["sel"] == "alsa_output.usb-Digirig-00.x" and o["text"] == "Digirig"   # nicht angesteckt
    assert o["hint"] == ""
    assert "FT-891" in o["auto_hint"] and o["stored"] == ""
