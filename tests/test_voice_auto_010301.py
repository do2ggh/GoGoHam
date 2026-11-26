"""0.10.30.1: Soundkarte für die Sprachspeicher wird automatisch zum Funkgerät gefunden."""

from gogoham import rigaudio


def _cfg(**prof):
    p = {"slot": 0, "name": "IC-7300", "model": 3073, "device": "/dev/ttyUSB0", "port": 4532}
    p.update(prof)
    return {"rig_profiles": [p], "rig_profile": 0}


def test_manual_choice_wins():
    cfg = _cfg()
    cfg["voice_rig_out"] = "alsa_output.handgewaehlt"
    assert rigaudio.voice_out(cfg, finder=lambda p: ("x", "y", "auto")) == \
        ("alsa_output.handgewaehlt", "chosen")


def test_automatic_from_profile():
    cfg = _cfg()
    found = ("alsa_output.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo",
             "alsa_input.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo", "auto")
    assert rigaudio.voice_out(cfg, finder=lambda p: found) == (found[0], "auto")


def test_fallback_is_not_used_and_nothing_found():
    cfg = _cfg()
    assert rigaudio.voice_out(cfg, finder=lambda p: ("alsa_output.x", "", "fallback")) == ("", "")
    assert rigaudio.voice_out(cfg, finder=lambda p: ("", "", "")) == ("", "")
    assert rigaudio.voice_out({"rig_profiles": []}) == ("", "")


def test_icom_network_always_uses_network_sound():
    cfg = _cfg(conn="icom", port=4533, net_audio=True)
    cfg["voice_rig_out"] = "alsa_output.usb-anderes-geraet"
    assert rigaudio.voice_out(cfg) == ("gogoham_icom_4533_tx", "net")


def test_pulse_names_via_libpulse(monkeypatch):
    from gogoham import pulse
    monkeypatch.setattr(pulse, "devices", lambda kind: {
        "sinks": [("alsa_output.pci.analog", "1"), ("alsa_output.usb-CODEC.analog", "3")],
        "sources": [("alsa_output.usb-CODEC.analog.monitor", "3"),
                    ("alsa_input.usb-CODEC.analog", "3")]}[kind])
    assert rigaudio.pulse_names(3) == ("alsa_output.usb-CODEC.analog", "alsa_input.usb-CODEC.analog")
    # ohne Tonsystem-Verbindung: Notweg pactl (hier: nichts gefunden)
    monkeypatch.setattr(pulse, "devices", lambda kind: None)
    monkeypatch.setattr(rigaudio, "_run", lambda args, timeout=5: (1, ""))
    assert rigaudio.pulse_names(3, run=rigaudio._run) == ("", "")
