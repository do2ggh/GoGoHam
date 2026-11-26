"""0.10.8: Piper-Stimmen aus festem Stand, speech-dispatcher unter Debian mit Qt-Verbindungsstück."""

from gogoham import piper, speech


def test_piper_voices_pinned_to_fixed_revision():
    # „main“ ändert sich (2026-11-09 neu trainiert) – dann passt keine Prüfsumme mehr
    assert "/resolve/main/" not in piper.VOICE_BASE
    assert piper.VOICE_REV in piper.VOICE_BASE and len(piper.VOICE_REV) == 40


def test_debian_speechd_install_includes_qt_plugin():
    script = speech.install_script(which=lambda n: "/usr/bin/" + n if n == "apt-get" else None)
    assert script.startswith("apt-get update && ")
    assert "qt6-speech-speechd-plugin" in script and "speech-dispatcher-espeak-ng" in script
