"""Stimmen der Gegenstationen für die SSB-Übung (ab 0.8.28.1).

Die erfundenen Stationen sprechen Englisch mit Buchstabieralphabet („Delta Lima One Alpha …“).
Erzeugt wird im Hintergrund, vorzugsweise mit Piper und der Stimme „libritts_r“ (904 Sprecher,
CC BY 4.0), sonst mit espeak-ng (Computerstimme, viele Varianten). Danach klingt alles wie über
Funk: nur 300–2700 Hz, etwas verdichtet. Es wird nichts gesendet – nur die Soundkarte.
"""

from __future__ import annotations

import io
import json
import os
import random
import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np

from . import cwsynth

RATE = cwsynth.RATE
PHONETIC = {
    "A": "Alpha", "B": "Bravo", "C": "Charlie", "D": "Delta", "E": "Echo", "F": "Foxtrot",
    "G": "Golf", "H": "Hotel", "I": "India", "J": "Juliett", "K": "Kilo", "L": "Lima",
    "M": "Mike", "N": "November", "O": "Oscar", "P": "Papa", "Q": "Quebec", "R": "Romeo",
    "S": "Sierra", "T": "Tango", "U": "Uniform", "V": "Victor", "W": "Whiskey", "X": "X-ray",
    "Y": "Yankee", "Z": "Zulu", "/": "stroke",
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six",
    "7": "seven", "8": "eight", "9": "nine",
}
TEENS = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
WORDS = {"KW": "kilowatt", "1K": "one kilowatt"}


def spell(word: str) -> str:
    return " ".join(PHONETIC[c] for c in word.upper() if c in PHONETIC)


def number(tok: str, rng: random.Random) -> str:
    """Zahl so, wie Funker sie sagen: Ziffern einzeln, Zonen oft als Wort („fourteen“)."""
    n = int(tok)
    if len(tok) <= 2 and 10 <= n <= 99 and rng.random() < 0.5:
        return TEENS[n - 10] if n < 20 else (TENS[n // 10] + ("" if n % 10 == 0 else
                                                             " " + PHONETIC[str(n % 10)]))
    return spell(tok)


def call_text(call: str, twice: bool) -> str:
    s = spell(call)
    return f"{s}, {s}" if twice else s


def exchange_text(exch: str, rng: random.Random, prefix: str = "") -> str:
    """„59 14“ → „five nine, fourteen“. prefix z. B. „QSL“ oder „thank you“."""
    parts = []
    for tok in exch.upper().split():
        if tok in WORDS:
            parts.append(WORDS[tok])
        elif tok.isdigit():
            parts.append("five nine" if tok in ("59", "599") else number(tok, rng))
        else:
            parts.append(spell(tok))
    body = ", ".join(parts)
    return f"{prefix}, {body}" if prefix else body


def estimate_s(text: str) -> float:
    """Ungefähre Sprechdauer (bevor die Stimme fertig ist)."""
    words = len(text.replace(",", " ").split())
    return 0.25 + 0.36 * words


def radio(x: np.ndarray, rate: int = RATE, low: float = 300.0, high: float = 2700.0
          ) -> np.ndarray:
    """Klang wie über SSB: Bandpass, etwas verdichtet, gleich laut (Effektivwert 0,25)."""
    if len(x) == 0:
        return x.astype(np.float32)
    n = len(x)
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1.0 / rate)
    edge = 150.0
    gain = np.clip((f - low + edge) / edge, 0, 1) * np.clip((high + edge - f) / edge, 0, 1)
    y = np.fft.irfft(spec * gain, n)
    rms = float(np.sqrt(np.mean(y * y))) or 1.0
    y = np.tanh(y / rms * 0.6) / 0.6 * 0.25 / 1.2
    return y.astype(np.float32)


def speed(x: np.ndarray, factor: float) -> np.ndarray:
    """Etwas schneller/langsamer (und höher/tiefer) – jede Station klingt anders."""
    if abs(factor - 1.0) < 1e-3 or len(x) < 2:
        return x
    n = max(2, int(len(x) / factor))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def read_wav(data: bytes) -> np.ndarray:
    from .voice import to_mono
    with wave.open(io.BytesIO(data), "rb") as w:
        ch, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError("WAV")
    return to_mono(np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0, ch, rate)


ESPEAK_VARIANTS = ("m1", "m2", "m3", "m4", "m5", "m6", "m7", "f1", "f2", "f3", "f4", "klatt",
                   "klatt2", "klatt3")


def backend() -> str:
    """piper, espeak oder '' (keine Stimme da)."""
    from . import piper
    if piper.practice_ready():
        return "piper"
    if shutil.which("espeak-ng"):
        return "espeak"
    return ""


class VoiceBank:
    """Erzeugt Sprache im Hintergrund. request() sofort, get() liefert fertige Töne (48 kHz,
    mit Funkklang) oder None, solange es noch rechnet."""

    def __init__(self, kind: str | None = None, popen=subprocess.Popen, run=subprocess.run):
        self.kind = backend() if kind is None else kind
        self._popen, self._run = popen, run
        self._jobs: list = []                # (key, text, voice, rate, tag) – noch zu rechnen
        self._pending: set[str] = set()
        self._focus: set[str] = set()        # S&P (0.8.29.1): diese Stationen zuerst
        self._done: dict[str, np.ndarray] = {}
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self.error = ""
        self._proc = None
        self._dir = tempfile.mkdtemp(prefix="gogoham-ssb-")
        self._stop = False
        if self.kind:
            threading.Thread(target=self._worker, daemon=True, name="ssb-voices").start()

    @property
    def ok(self) -> bool:
        return bool(self.kind) and not self.error

    def speakers(self) -> int:
        from . import piper
        return piper.PRACTICE_SPEAKERS if self.kind == "piper" else len(ESPEAK_VARIANTS)

    def request(self, key: str, text: str, voice: int, rate: float, tag: str = "") -> None:
        with self._cond:
            if key in self._done or key in self._pending:
                return
            self._pending.add(key)
            self._jobs.append((key, text, voice, rate, tag))
            self._cond.notify()

    def focus(self, tags) -> None:
        """Aufträge dieser Stationen (tag) vorziehen – z. B. die nahe der VFO-Frequenz."""
        with self._cond:
            self._focus = set(tags)

    def _next_job(self):
        with self._cond:
            while not self._jobs and not self._stop:
                self._cond.wait(0.5)
            if self._stop:
                return None
            i = next((n for n, j in enumerate(self._jobs) if j[4] and j[4] in self._focus), 0)
            return self._jobs.pop(i)

    def get(self, key: str) -> np.ndarray | None:
        with self._lock:
            return self._done.get(key)

    def close(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        if self._proc is not None:
            try:
                self._proc.stdin.close()
                self._proc.terminate()
            except (OSError, ValueError, AttributeError):
                pass
        shutil.rmtree(self._dir, ignore_errors=True)

    # -------------------------------------------------------------- Hintergrund
    def _worker(self) -> None:
        while not self._stop:
            job = self._next_job()
            if job is None:
                return
            key, text, voice, rate, _tag = job
            try:
                x = self._piper(text, voice) if self.kind == "piper" else \
                    self._espeak(text, voice)
                x = radio(speed(x, rate))
            except Exception as e:                       # noqa: BLE001 – ohne Stimme weiter
                self.error = str(e) or e.__class__.__name__
                x = np.zeros(int(0.3 * RATE), np.float32)
            with self._lock:
                self._done[key] = x
                self._pending.discard(key)

    def _piper(self, text: str, voice: int) -> np.ndarray:
        from . import piper
        if self._proc is None or self._proc.poll() is not None:
            exe = piper.exe_path()
            env = dict(os.environ)
            env["LD_LIBRARY_PATH"] = os.pathsep.join(
                [str(exe.parent)] + ([env["LD_LIBRARY_PATH"]] if env.get("LD_LIBRARY_PATH")
                                     else []))
            self._proc = self._popen(
                [str(exe), "--model", str(piper.practice_voice_path()), "--json-input",
                 "--output_dir", self._dir], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env, cwd=self._dir)
        self._proc.stdin.write(json.dumps({"text": text, "speaker_id": int(voice)}) + "\n")
        self._proc.stdin.flush()
        path = (self._proc.stdout.readline() or "").strip()
        if not path:
            raise RuntimeError("Piper")
        p = Path(path)
        try:
            return read_wav(p.read_bytes())
        finally:
            p.unlink(missing_ok=True)

    def _espeak(self, text: str, voice: int) -> np.ndarray:
        v = ESPEAK_VARIANTS[int(voice) % len(ESPEAK_VARIANTS)]
        r = self._run(["espeak-ng", "-v", f"en-us+{v}", "-s", "165",
                       "-p", str(35 + (int(voice) * 7) % 35), "--stdout", text],
                      capture_output=True, timeout=20)
        if r.returncode != 0 or not r.stdout:
            raise RuntimeError("espeak-ng")
        return read_wav(r.stdout)
