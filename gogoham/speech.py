"""Ansagen per Sprachausgabe (ab 0.8.26) – vor allem für sehbehinderte Funkamateure.

GoGoHam spricht wichtige Ereignisse von selbst aus (Dupe, neuer Multi, Band-/Modewechsel,
geloggt, Warnungen) und auf Tastendruck (Alt+1 … Alt+6). Die Ansagen laufen über die
normale Sprachausgabe des Systems – nie über die Soundkarte des Funkgeräts und nie mit PTT.

Sprachausgabe: Piper (natürliche Stimme, lädt GoGoHam auf Wunsch selbst, ab 0.8.26.2),
speech-dispatcher (über Qt, nutzt die Stimme, die im System eingestellt ist) oder espeak-ng
(eigener Aufruf). „auto“ nimmt Piper, sonst speech-dispatcher, sonst espeak-ng.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .bands import GHZ_LABEL
from .i18n import decimal_comma, language, num, tr

BACKENDS = ("auto", "piper", "speechd", "espeak")
# automatische Ansagen (je einzeln an/aus, Standard: alle an, sobald Ansagen eingeschaltet sind)
EVENTS = ("dupe", "new_mult", "invalid", "band", "mode", "logged", "hints", "band_busy",
          "chat")
# Tempo: (espeak-ng Wörter/min, Qt-Rate, Piper length_scale)
RATES = {"slow": (140, -0.3, 1.3), "normal": (175, 0.0, 1.0), "fast": (230, 0.4, 0.8),
         "very_fast": (290, 0.8, 0.65)}
PLAYERS = ("pw-play", "paplay", "aplay")        # spielt Piper-WAVs über die Standard-Ausgabe
ICAO = {"A": "Alfa", "B": "Bravo", "C": "Charlie", "D": "Delta", "E": "Echo", "F": "Foxtrot",
        "G": "Golf", "H": "Hotel", "I": "India", "J": "Juliett", "K": "Kilo", "L": "Lima",
        "M": "Mike", "N": "November", "O": "Oscar", "P": "Papa", "Q": "Quebec", "R": "Romeo",
        "S": "Sierra", "T": "Tango", "U": "Uniform", "V": "Victor", "W": "Whiskey",
        "X": "X-Ray", "Y": "Yankee", "Z": "Zulu"}


# ------------------------------------------------------------------ Sprachausgabe finden
def espeak_exe() -> str | None:
    return shutil.which("espeak-ng") or shutil.which("espeak")


def speechd_ok() -> bool:
    """speech-dispatcher installiert und Qt kann es ansprechen?"""
    if not (shutil.which("speech-dispatcher") or shutil.which("spd-say")):
        return False
    try:
        from PySide6.QtTextToSpeech import QTextToSpeech
    except ImportError:
        return False
    return "speechd" in QTextToSpeech.availableEngines()


def player_exe() -> str | None:
    for name in PLAYERS:
        exe = shutil.which(name)
        if exe:
            return exe
    return None


def piper_ok() -> bool:
    """Piper und eine Stimme geladen, und es gibt ein Abspielprogramm?"""
    from . import piper
    return piper.installed() and player_exe() is not None


def choose(pref: str, have_speechd: bool | None = None, have_espeak: bool | None = None,
           have_piper: bool | None = None) -> str | None:
    """Welche Sprachausgabe benutzt wird ("piper", "speechd", "espeak" oder None = keine da).
    Die gewünschte zuerst, sonst in der Reihenfolge Piper – speech-dispatcher – espeak-ng."""
    have = {"piper": piper_ok() if have_piper is None else have_piper,
            "speechd": speechd_ok() if have_speechd is None else have_speechd,
            "espeak": bool(espeak_exe()) if have_espeak is None else have_espeak}
    for b in ([pref] if pref in have else []) + ["piper", "speechd", "espeak"]:
        if have[b]:
            return b
    return None


# ------------------------------------------------------------------ speech-dispatcher installieren
# Paketverwaltung -> (Befehl, Pakete). Reihenfolge = Suchreihenfolge. espeak-ng kommt mit, weil
# speech-dispatcher damit spricht (und GoGoHam es als Ersatz nimmt).
INSTALLERS = (
    ("pacman", "pacman -S --needed --noconfirm", "speech-dispatcher espeak-ng"),
    ("apt-get", "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y",
     # Debian/Ubuntu: Qt spricht speech-dispatcher nur über dieses eigene Paket an (0.10.8)
     "speech-dispatcher speech-dispatcher-espeak-ng espeak-ng qt6-speech-speechd-plugin"),
    ("dnf", "dnf install -y", "speech-dispatcher speech-dispatcher-espeak-ng espeak-ng"),
    ("zypper", "zypper --non-interactive install",
     "speech-dispatcher speech-dispatcher-module-espeak espeak-ng"),
)


def install_script(which=shutil.which) -> str:
    """Befehl zum Installieren für diese Distribution ("" = Paketverwaltung unbekannt)."""
    for exe, cmd, pkgs in INSTALLERS:
        if which(exe):
            return f"{cmd} {pkgs}"
    return ""


def install_command(which=shutil.which) -> list[str] | None:
    """Aufruf zum Installieren (pkexec fragt nach dem Passwort) – None, wenn das nicht geht."""
    script = install_script(which)
    if not script or not which("pkexec"):
        return None
    return ["pkexec", "/bin/sh", "-c", script]


def manual_commands() -> str:
    """Befehle zum Kopieren, falls es per Klick nicht geht."""
    return "\n".join(f"sudo {cmd.replace('&& ', '&& sudo ')} {pkgs}"
                      for _exe, cmd, pkgs in INSTALLERS)


def backend_name(backend: str | None) -> str:
    return {"piper": "Piper", "speechd": "speech-dispatcher",
            "espeak": "espeak-ng"}.get(backend or "", tr("keine"))


# ------------------------------------------------------------------ Texte zum Sprechen
def spell_call(call: str, phonetic: bool = False) -> str:
    """„DL1ABC/P“ -> „D L 1 A B C Strich P“ bzw. „Delta Lima 1 Alfa …“."""
    out = []
    for ch in (call or "").upper():
        if ch == "/":
            out.append(tr("Strich"))
        elif ch.isalpha():
            out.append(ICAO.get(ch, ch) if phonetic else ch)
        elif ch.isdigit():
            out.append(ch)
    return " ".join(out)


def band_words(band: str) -> str:
    """„20“ -> „20 Meter“, „70cm“ -> „70 Zentimeter“, „6mm“ -> „47 Gigahertz“."""
    b = band or ""
    if b in GHZ_LABEL:
        return GHZ_LABEL[b].replace(">", tr("über ")).replace("GHz", tr("Gigahertz"))
    if b.endswith("cm"):
        return tr("{n} Zentimeter", n=b[:-2].replace(".", "," if decimal_comma() else "."))
    return tr("{n} Meter", n=b) if b else ""


def mode_words(mode: str) -> str:
    """Betriebsart zum Vorlesen: Abkürzungen als einzelne Buchstaben („C W“, „U S B“)."""
    m = (mode or "").upper()
    if m.startswith("PKT"):
        return tr("Daten") + " " + " ".join(m[3:])
    return " ".join(m) if m.isalnum() and len(m) <= 5 else m


def freq_words(hz: float | None, mode: str = "") -> str:
    if not hz:
        return mode_words(mode)
    txt = tr("{mhz} Megahertz", mhz=num(hz / 1e6, 3))
    return f"{txt}, {mode_words(mode)}" if mode else txt


def clean(text: str) -> str:
    """Zeichen weg, die beim Vorlesen stören (⚠, Pfeile, Sterne …)."""
    keep = []
    for ch in text or "":
        if ch.isalnum() or ch in " .,:;!?-+%/()'\"„“":
            keep.append(ch)
        elif ch in "·|–—":
            keep.append(", ")
        else:
            keep.append(" ")
    return " ".join("".join(keep).split())


# ------------------------------------------------------------------ Sprechen
class PiperVoice:
    """Ein dauerhaft laufendes Piper (Stimme nur einmal laden): eine Zeile Text rein, Piper
    schreibt eine WAV-Datei und nennt ihren Pfad; abgespielt wird nur die jeweils neueste."""

    def __init__(self, exe: Path, model: Path, length_scale: float, player: str,
                 popen=subprocess.Popen):
        self._popen = popen
        self.player = player
        self.dir = tempfile.mkdtemp(prefix="gogoham-piper-")
        env = dict(os.environ)
        env["LD_LIBRARY_PATH"] = os.pathsep.join(
            [str(exe.parent)] + ([env["LD_LIBRARY_PATH"]] if env.get("LD_LIBRARY_PATH") else []))
        self.proc = popen([str(exe), "--model", str(model), "--output_dir", self.dir,
                           "--length_scale", str(length_scale)],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env, cwd=self.dir)
        self._lock = threading.Lock()
        self.want = self.got = self.skip = 0
        self._play = None
        self._last_wav: str | None = None
        threading.Thread(target=self._reader, daemon=True, name="piper-reader").start()

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    def say(self, text: str) -> bool:
        with self._lock:
            self.want += 1
        try:
            self.proc.stdin.write(" ".join(text.split()) + "\n")
            self.proc.stdin.flush()
            return True
        except (OSError, ValueError, AttributeError):
            return False

    def _reader(self) -> None:
        for line in self.proc.stdout or ():
            path = line.strip()
            if not path:
                continue
            with self._lock:
                self.got += 1
                newest = self.got == self.want and self.got > self.skip
            if newest:
                self._start(path)
            else:
                Path(path).unlink(missing_ok=True)       # überholt oder abgebrochen

    def _start(self, path: str) -> None:
        self._stop_player()
        old, self._last_wav = self._last_wav, path
        if old:
            Path(old).unlink(missing_ok=True)
        try:
            self._play = self._popen([self.player, path], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        except OSError:
            self._play = None

    def _stop_player(self) -> None:
        p, self._play = self._play, None
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass

    def stop(self) -> None:
        with self._lock:
            self.skip = self.want                       # was noch berechnet wird: verwerfen
        self._stop_player()

    def close(self) -> None:
        self.stop()
        try:
            self.proc.stdin.close()
        except (OSError, AttributeError):
            pass
        if self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass
        shutil.rmtree(self.dir, ignore_errors=True)


class Speaker:
    """Spricht einen Text; ein neuer Text unterbricht den laufenden."""

    def __init__(self, backend: str | None, rate: str = "normal", lang: str | None = None,
                 popen=subprocess.Popen):
        self.backend = backend
        self.rate = rate if rate in RATES else "normal"
        self.lang = lang or language()
        self._popen = popen
        self._proc = None
        self._tts = None
        self._piper: PiperVoice | None = None
        if backend == "piper":
            self._piper = self._make_piper()
            if self._piper is None:                      # Piper fehlt/kaputt: nächstbeste
                self.backend = choose("speechd", have_piper=False)
                backend = self.backend
        if backend == "speechd":
            self._tts = self._make_tts()
            if self._tts is None:                       # Qt/Daemon versagt: espeak-ng versuchen
                self.backend = "espeak" if espeak_exe() else None

    def _make_piper(self) -> PiperVoice | None:
        from . import piper
        model, player = piper.voice_path(self.lang), player_exe()
        if model is None or player is None or not piper.installed():
            return None
        try:
            return PiperVoice(piper.exe_path(), model, RATES[self.rate][2], player, self._popen)
        except OSError:
            return None

    def _make_tts(self):
        try:
            from PySide6.QtCore import QLocale
            from PySide6.QtTextToSpeech import QTextToSpeech
            tts = QTextToSpeech("speechd")
            if tts.state() == QTextToSpeech.State.Error:
                return None
            tts.setLocale(QLocale(self.lang))
            tts.setRate(RATES[self.rate][1])
            return tts
        except Exception:                               # noqa: BLE001 – lieber stumm als Absturz
            return None

    @property
    def ok(self) -> bool:
        return self.backend is not None

    def say(self, text: str) -> None:
        text = clean(text)
        if not text or not self.backend:
            return
        self.stop()
        if self._piper is not None:
            if self._piper.alive and self._piper.say(text):
                return
            self._piper.close()                          # Piper abgestürzt: espeak-ng nehmen
            self._piper = None
            self.backend = "espeak" if espeak_exe() else None
            if not self.backend:
                return
        if self._tts is not None:
            self._tts.say(text)
            return
        exe = espeak_exe()
        if not exe:
            return
        try:
            self._proc = self._popen([exe, "-v", self.lang, "-s", str(RATES[self.rate][0]), text],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self._proc = None

    def stop(self) -> None:
        if self._piper is not None:
            self._piper.stop()
        if self._tts is not None:
            self._tts.stop()
        p, self._proc = self._proc, None
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass


    def close(self) -> None:
        """Beim Wechsel der Einstellungen bzw. Beenden: auch Piper beenden."""
        self.stop()
        if self._piper is not None:
            self._piper.close()
            self._piper = None


class Announcer:
    """Entscheidet, was angesagt wird – ohne Wiederholungen beim Tippen."""

    def __init__(self, cfg: dict, speaker: Speaker | None):
        self.cfg = cfg
        self.speaker = speaker
        self._last_status: tuple[str, str] | None = None
        self._band: str | None = None
        self._mode: str | None = None
        self.last_text = ""
        # Ruhezeit für Band-/Modewechsel: beim Start (bis das Fenster zu sehen ist), nach dem
        # Öffnen eines Logs und nach dem Verbinden mit dem Funkgerät – das sind keine Wechsel
        # durch den Nutzer. Bis dahin wird der Stand still übernommen.
        self.quiet_until = float("inf")

    def quiet(self, seconds: float) -> None:
        self.quiet_until = time.monotonic() + seconds

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("announce_enabled")) and bool(self.speaker and self.speaker.ok)

    # Ansagen, die von sich aus aus sind (fehlt in announce_events = aus)
    # Neue Ansagen sind immer erst einmal aus (ab 0.10.3) – man schaltet sie selbst ein
    OFF_BY_DEFAULT = {"qtc", "band_busy", "chat"}

    def wants(self, event: str) -> bool:
        return self.enabled and bool((self.cfg.get("announce_events") or {}).get(
            event, event not in self.OFF_BY_DEFAULT))

    @property
    def phonetic(self) -> bool:
        return self.cfg.get("announce_spelling", "letters") == "phonetic"

    def say(self, text: str) -> None:
        """Auf Tastendruck: immer sprechen (wenn Ansagen an sind)."""
        if self.enabled and text:
            self.last_text = text
            self.speaker.say(text)

    def _auto(self, event: str, text: str) -> None:
        if self.wants(event) and text:
            self.last_text = text
            self.speaker.say(text)

    def call_status(self, call: str, kind: str) -> None:
        """Beim Tippen (nach kurzer Pause): „Dupe“, „Neuer Multi“, „Zählt nicht“ – je
        Rufzeichen und Zustand nur einmal."""
        key = (call, kind)
        if not self.enabled or not call or key == self._last_status:
            return
        self._last_status = key
        text = {"dupe": tr("Dupe"), "new_mult": tr("Neuer Multi"),
                "invalid": tr("Zählt nicht")}.get(kind)
        if text:
            self._auto(kind, text)

    def band_mode(self, band: str, mode: str) -> None:
        """Bandwechsel / Modewechsel ansagen (der erste Wert und alles in der Ruhezeit nicht)."""
        if time.monotonic() < self.quiet_until:
            self._band, self._mode = band or self._band, mode or self._mode
            return
        if band != self._band:
            first = self._band is None
            self._band = band
            if not first and band:
                self._auto("band", band_words(band))
        if mode != self._mode:
            first = self._mode is None
            self._mode = mode
            if not first and mode:
                self._auto("mode", mode_words(mode))

    def logged(self, call: str) -> None:
        self._last_status = None
        self._auto("logged", tr("Geloggt: {call}", call=spell_call(call, self.phonetic)))

    def qtc(self, text: str) -> None:
        """QTC geben in SSB (ab 0.9.4): die Zeile, die dran ist, zum Nachsprechen ansagen."""
        if self.wants("qtc") and text:
            self.stop()
            self._auto("qtc", text)

    def band_busy(self, band: str) -> None:
        """Stationslog (0.10.3): ein anderer Platz ist auf demselben Band."""
        self._auto("band_busy", tr("Band belegt: {band}", band=band_words(band)))

    def chat(self, sender: str, text: str) -> None:
        """Stationslog (0.10.3): eine Nachricht von einem anderen Platz vorlesen."""
        self._auto("chat", tr("Nachricht von {place}: {msg}", place=sender, msg=text))

    def hint(self, text: str, level: str) -> None:
        """Hinweiszeile: nur Warnungen und Fehler (Infos wären zu viel Gerede)."""
        if level in ("warn", "error"):
            self._auto("hints", text)

    def stop(self) -> None:
        if self.speaker:
            self.speaker.stop()
