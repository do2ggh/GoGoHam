"""0.8.26.2: natürliche Stimme Piper – Download (Prüfsummen, Entpacken) und dauerhaft laufendes
Piper mit Abspielen nur der neuesten Ansage. Statt des echten Piper läuft ein Ersatzskript."""

import hashlib
import io
import os
import subprocess
import tarfile
import time
from pathlib import Path

import pytest

from gogoham import piper, speech

FAKE_PIPER = r'''#!/usr/bin/env python3
import sys, os, time
args = sys.argv
out = args[args.index("--output_dir") + 1]
log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "piper-args.txt")
open(log, "w").write(" ".join(args[1:]))
n = 0
for line in sys.stdin:
    n += 1
    if line.startswith("langsam"):
        time.sleep(0.4)
    p = os.path.join(out, f"{n}.wav")
    open(p, "w").write(line)
    print(p, flush=True)
'''
FAKE_PLAYER = r'''#!/bin/sh
cat "$1" >> "$(dirname "$0")/played.txt"
'''


def _script(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(0o755)
    return path


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path


def _install_fake(home) -> Path:
    exe = piper.exe_path()
    exe.parent.mkdir(parents=True)
    _script(exe, FAKE_PIPER)
    v = piper.base_dir() / "voices"
    v.mkdir(parents=True)
    for lang in ("de", "en"):
        name = piper.VOICES[lang][0]
        (v / f"{name}.onnx").write_text("x")
        (v / f"{name}.onnx.json").write_text("{}")
    return _script(home / "player.sh", FAKE_PLAYER)


def _wait(cond, sec=5):
    end = time.monotonic() + sec
    while not cond() and time.monotonic() < end:
        time.sleep(0.02)
    return cond()


# ------------------------------------------------------------ Dateien und Erkennung
def test_paths_and_installed(home):
    assert piper.base_dir() == home / "data" / "gogoham" / "piper"
    assert not piper.installed() and piper.voice_path("de") is None
    _install_fake(home)
    assert piper.installed() and piper.installed("de")
    assert piper.voice_path("de").name == "de_DE-thorsten-medium.onnx"
    assert piper.voice_path("fr") is None      # 0.10.27: keine Piper-Stimme → Sprachausgabe des Systems
    assert 145e6 < piper.total_size() < 160e6
    assert "CC0" in piper.VOICE_CREDITS["de"] and "public domain" in piper.VOICE_CREDITS["en"]


# ------------------------------------------------------------ Download
def _fake_release(tmp_path):
    """Kleines Piper-Archiv + Stimmen; liefert opener und passende Tabellen."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in (("piper/piper", b"#!/bin/sh\n"), ("piper/espeak-ng-data/x", b"1")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    files = {"piper_linux_x86_64.tar.gz": buf.getvalue(),
             "de_DE-thorsten-medium.onnx": b"de-model", "de_DE-thorsten-medium.onnx.json": b"{}",
             "en_GB-cori-medium.onnx": b"en-model", "en_GB-cori-medium.onnx.json": b"{}"}
    sha = lambda b: hashlib.sha256(b).hexdigest()
    programs = {"x86_64": ("piper_linux_x86_64.tar.gz", len(files["piper_linux_x86_64.tar.gz"]),
                           sha(files["piper_linux_x86_64.tar.gz"]))}
    voices = {lang: (n, p, [(e, len(files[n + e]), sha(files[n + e])) for e in (".onnx", ".onnx.json")])
              for lang, (n, p, _f) in piper.VOICES.items()}
    calls = []

    def opener(req, timeout=0):
        name = req.full_url.rsplit("/", 1)[-1]
        calls.append(name)
        return io.BytesIO(files[name])
    return files, programs, voices, opener, calls


def test_download_and_checksums(home, monkeypatch):
    files, programs, voices, opener, calls = _fake_release(home)
    monkeypatch.setattr(piper, "PROGRAMS", programs)
    monkeypatch.setattr(piper, "VOICES", voices)
    monkeypatch.setattr(piper, "arch", lambda: "x86_64")
    d = piper.PiperDownloader(opener=opener)
    d.run()
    assert d.error == "" and d.percent == 100
    assert piper.installed() and os.access(piper.exe_path(), os.X_OK)
    assert (piper.base_dir() / "piper" / "espeak-ng-data" / "x").is_file()
    assert not list(piper.base_dir().rglob("*.part"))
    calls.clear()
    piper.PiperDownloader(opener=opener).run()                 # schon da: Stimmen nicht neu
    assert calls == ["piper_linux_x86_64.tar.gz"]
    # verfälschte Stimme: Fehler, nichts Halbes bleibt liegen
    (piper.base_dir() / "voices" / "en_GB-cori-medium.onnx").unlink()
    files["en_GB-cori-medium.onnx"] = b"manipuliert"
    d = piper.PiperDownloader(opener=opener)
    d.run()
    assert "Prüfsumme" in d.error and piper.voice_path("en") is None
    assert not list(piper.base_dir().rglob("*.part"))


def test_download_rejects_paths_outside(home, monkeypatch):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo("../../boese")
        info.size = 1
        t.addfile(info, io.BytesIO(b"x"))
    data = buf.getvalue()
    monkeypatch.setattr(piper, "PROGRAMS", {"x86_64": ("p.tgz", len(data),
                                                       hashlib.sha256(data).hexdigest())})
    monkeypatch.setattr(piper, "arch", lambda: "x86_64")
    d = piper.PiperDownloader(opener=lambda req, timeout=0: io.BytesIO(data))
    d.run()
    assert d.error and not (home / "data" / "boese").exists() and not (home / "boese").exists()


def test_unsupported_cpu(home, monkeypatch):
    monkeypatch.setattr(piper, "arch", lambda: "riscv64")
    d = piper.PiperDownloader(opener=lambda *a, **k: None)
    d.run()
    assert "riscv64" in d.error and not piper.supported()


# ------------------------------------------------------------ Sprechen mit (Ersatz-)Piper
def test_piper_voice_plays_only_newest(home, monkeypatch):
    player = _install_fake(home)
    monkeypatch.setattr(speech, "player_exe", lambda: str(player))
    assert speech.piper_ok()
    sp = speech.Speaker("piper", "fast", lang="de")
    assert sp.backend == "piper"
    args = (piper.exe_path().parent / "piper-args.txt")
    assert _wait(args.exists)
    a = args.read_text()
    assert "de_DE-thorsten-medium.onnx" in a and "--length_scale 0.8" in a
    played = home / "played.txt"
    sp.say("langsam eins")                     # wird von der nächsten Ansage überholt
    sp.say("⚠ Neuer Multi")
    assert _wait(lambda: played.exists() and "Neuer Multi" in played.read_text())
    time.sleep(0.6)
    assert played.read_text() == "Neuer Multi\n"
    sp.say("langsam drei")
    sp.stop()                                  # Esc: was noch berechnet wird, verwerfen
    time.sleep(0.8)
    assert "drei" not in played.read_text()
    tmp = Path(sp._piper.dir)
    sp.close()
    assert not tmp.exists() and sp._piper is None


def test_piper_missing_falls_back(home, monkeypatch):
    monkeypatch.setattr(speech, "speechd_ok", lambda: False)
    monkeypatch.setattr(speech, "espeak_exe", lambda: "/usr/bin/espeak-ng")
    sp = speech.Speaker("piper", lang="de", popen=lambda *a, **k: None)
    assert sp.backend == "espeak"              # nicht geladen: nächstbeste Sprachausgabe


def test_piper_crash_falls_back(home, monkeypatch):
    player = _install_fake(home)
    _script(piper.exe_path(), "#!/bin/sh\nexit 3\n")        # Piper startet nicht richtig
    monkeypatch.setattr(speech, "player_exe", lambda: str(player))
    monkeypatch.setattr(speech, "espeak_exe", lambda: "/usr/bin/espeak-ng")
    started = []
    real = subprocess.Popen

    def popen(args, **kw):
        if args[0] == "/usr/bin/espeak-ng":
            started.append(args)
            return type("P", (), {"poll": lambda s: 0, "terminate": lambda s: None})()
        return real(args, **kw)
    sp = speech.Speaker("piper", lang="de", popen=popen)
    assert sp.backend == "piper"
    _wait(lambda: not sp._piper.alive)
    sp.say("Dupe")
    assert sp.backend == "espeak" and started and started[-1][-1] == "Dupe"
    sp.close()
