"""Piper – natürliche Stimme für die Ansagen (ab 0.8.26.2), läuft ohne Internet.

GoGoHam lädt auf Wunsch das Programm Piper (MIT-Lizenz, github.com/rhasspy/piper) und je eine
deutsche und englische Stimme (huggingface.co/rhasspy/piper-voices) nach
~/.local/share/gogoham/piper/ – ohne sudo. Jede Datei wird per SHA-256 geprüft.

Stimmen (frei nutzbar):
  Deutsch  „Thorsten“ (de_DE-thorsten-medium) – Datensatz Thorsten-Voice, CC0
  Englisch „Cori“     (en_GB-cori-medium)     – Aufnahmen von LibriVox, gemeinfrei
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import tarfile
import threading
import urllib.request
from pathlib import Path

from .i18n import tr

RELEASE = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/"
PROGRAMS = {
    "x86_64": ("piper_linux_x86_64.tar.gz", 26460462,
               "a50cb45f355b7af1f6d758c1b360717877ba0a398cc8cbe6d2a7a3a26e225992"),
    "aarch64": ("piper_linux_aarch64.tar.gz", 26004717,
                "fea0fd2d87c54dbc7078d0f878289f404bd4d6eea6e7444a77835d1537ab88eb"),
}
# Fester Stand (0.10.8): „main“ ändert sich – am 2026-11-09 wurden die Stimmen neu trainiert, die
# Prüfsummen passten nicht mehr. Dieser Stand hat genau die Dateien mit den Prüfsummen unten.
VOICE_REV = "e7229f7d33a10e145e109b886d661984201ac3c4"
VOICE_BASE = f"https://huggingface.co/rhasspy/piper-voices/resolve/{VOICE_REV}/"
# Sprache -> (Name, Pfad bei Hugging Face, [(Endung, Größe, SHA-256), …])
VOICES = {
    "de": ("de_DE-thorsten-medium", "de/de_DE/thorsten/medium/", [
        (".onnx", 63201294, "7e64762d8e5118bb578f2eea6207e1a35a8e0c30595010b666f983fc87bb7819"),
        (".onnx.json", 4819, "974adee790533adb273a1ac88f49027d2a1b8f0f2cf4905954a4791e79264e85")]),
    "en": ("en_GB-cori-medium", "en/en_GB/cori/medium/", [
        (".onnx", 63531379, "1899f98e5fb8310154f3c2973f4b8a929ba7245e722b3d3a85680b833d95f10d"),
        (".onnx.json", 4966, "e262c16d7f192f69d4edd6b4ef8a5915379e67495fcc402f1ab15eeb33da3d36")]),
}
VOICE_CREDITS = {"de": "Thorsten (Thorsten-Voice, CC0)", "en": "Cori (LibriVox, public domain)"}
# Übungsmodus SSB (0.8.28.1): eine Stimme mit 904 Sprechern – nur auf Wunsch geladen
PRACTICE_VOICE = ("en_US-libritts_r-medium", "en/en_US/libritts_r/medium/", [
    (".onnx", 78580914, "10bb85e071d616fcf4071f369f1799d0491492ab3c5d552ec19fb548fac13195"),
    (".onnx.json", 20123, "b471dc60d2d8335e819c393d196d6fbf792817f40051257b269878505bc9afb3")])
PRACTICE_CREDIT = "LibriTTS-R (CC BY 4.0, openslr.org/141)"
PRACTICE_SPEAKERS = 904


def base_dir() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "gogoham" / "piper"


def arch() -> str:
    m = platform.machine().lower()
    return {"amd64": "x86_64", "arm64": "aarch64"}.get(m, m)


def supported() -> bool:
    return arch() in PROGRAMS


def exe_path() -> Path:
    return base_dir() / "piper" / "piper"


def voice_path(lang: str) -> Path | None:
    """Stimme für die Sprache; None = nicht geladen oder keine Piper-Stimme für diese Sprache.
    Ab 0.10.27 kein englischer Ersatz mehr – sonst läse die englische Stimme z. B. spanischen
    Text. Ohne Stimme nimmt GoGoHam die Sprachausgabe des Systems (speech-dispatcher/espeak-ng),
    die viele Sprachen kann."""
    if lang not in VOICES:
        return None
    name = VOICES[lang][0]
    p = base_dir() / "voices" / f"{name}.onnx"
    return p if p.is_file() and p.with_suffix(".onnx.json").is_file() else None


def installed(lang: str | None = None) -> bool:
    """Programm da und (für lang bzw. irgendeine Sprache) eine Stimme?"""
    if not os.access(exe_path(), os.X_OK):
        return False
    langs = [lang] if lang else list(VOICES)
    return any(voice_path(lg) for lg in langs)


def practice_voice_path() -> Path | None:
    """Stimme für die SSB-Übung (904 Sprecher); None = nicht geladen."""
    p = base_dir() / "voices" / f"{PRACTICE_VOICE[0]}.onnx"
    return p if p.is_file() and p.with_suffix(".onnx.json").is_file() else None


def practice_ready() -> bool:
    return os.access(exe_path(), os.X_OK) and practice_voice_path() is not None


def total_size(what: str = "speech") -> int:
    prog = PROGRAMS.get(arch(), PROGRAMS["x86_64"])[1]
    if what == "practice":
        need = 0 if os.access(exe_path(), os.X_OK) else prog
        return need + sum(s for _e, s, _h in PRACTICE_VOICE[2])
    return prog + sum(s for _n, _p, files in VOICES.values() for _e, s, _h in files)


def missing_size(what: str = "speech") -> int:
    """Wie viel noch geladen werden müsste (Programm und Stimmen, die fehlen) – in Bytes."""
    need = 0 if os.access(exe_path(), os.X_OK) else PROGRAMS.get(arch(), PROGRAMS["x86_64"])[1]
    todo = [PRACTICE_VOICE] if what == "practice" else list(VOICES.values())
    for vname, _path, files in todo:
        for ext, size, _sha in files:
            p = base_dir() / "voices" / (vname + ext)
            if not (p.is_file() and p.stat().st_size == size):
                need += size
    return need


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class PiperDownloader(threading.Thread):
    """Lädt Programm + Stimmen im Hintergrund. Fortschritt: .percent, .phase; Fehler: .error."""

    def __init__(self, timeout: float = 60.0, opener=urllib.request.urlopen,
                 what: str = "speech"):
        super().__init__(daemon=True, name="piper-download")
        self.timeout = timeout
        self.what = what                 # speech = Ansage-Stimmen, practice = Übungsstimme
        self.percent = 0
        self.phase = ""
        self.error = ""
        self._open = opener
        self._done = 0
        self._total = total_size(what)

    def _get(self, url: str, target: Path, size: int, sha: str) -> None:
        if target.is_file() and target.stat().st_size == size and _sha256(target) == sha:
            self._done += size                       # schon da und unverändert
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        req = urllib.request.Request(url, headers={"User-Agent": "GoGoHam"})
        with self._open(req, timeout=self.timeout) as r, open(part, "wb") as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                self._done += len(chunk)
                self.percent = min(99, int(100 * self._done / max(self._total, 1)))
        if _sha256(part) != sha:
            part.unlink(missing_ok=True)
            raise ValueError(tr("{name}: Prüfsumme stimmt nicht", name=target.name))
        part.replace(target)

    def run(self) -> None:  # noqa: D401 (Thread-Methode)
        try:
            if not supported():
                raise ValueError(tr("Piper gibt es nicht für diesen Prozessor ({arch})", arch=arch()))
            base = base_dir()
            if self.what == "practice" and os.access(exe_path(), os.X_OK):
                self._voices(base)                     # Programm ist schon da
                self.percent = 100
                return
            name, size, sha = PROGRAMS[arch()]
            self.phase = "Piper"
            tgz = base / "download" / name
            self._get(RELEASE + name, tgz, size, sha)
            self.phase = tr("Piper (entpacken)")
            tmp = base / "piper.new"
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True)
            with tarfile.open(tgz) as t:
                t.extractall(tmp, filter="data")          # nichts außerhalb des Ordners
            if not (tmp / "piper" / "piper").is_file():
                raise ValueError(tr("Piper-Archiv unvollständig"))
            (tmp / "piper" / "piper").chmod(0o755)
            shutil.rmtree(base / "piper", ignore_errors=True)
            (tmp / "piper").replace(base / "piper")
            shutil.rmtree(tmp, ignore_errors=True)
            tgz.unlink(missing_ok=True)
            self._voices(base)
            self.percent = 100
        except Exception as e:                       # noqa: BLE001 – Meldung für die Hinweiszeile
            self.error = str(e) or e.__class__.__name__

    def _voices(self, base: Path) -> None:
        if self.what == "practice":
            todo = [(PRACTICE_CREDIT.split(" (")[0], PRACTICE_VOICE)]
        else:
            todo = [(VOICE_CREDITS[lang].split(" (")[0], v) for lang, v in VOICES.items()]
        for credit, (vname, path, files) in todo:
            self.phase = tr("Stimme {name}", name=credit)
            for ext, fsize, fsha in files:
                self._get(VOICE_BASE + path + vname + ext,
                          base / "voices" / (vname + ext), fsize, fsha)


def remove() -> None:
    shutil.rmtree(base_dir(), ignore_errors=True)
