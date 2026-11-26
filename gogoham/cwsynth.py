"""CW-Töne für den Übungsmodus (ab 0.8.28): Morsezeichen, Rauschen, Schwund (QSB), Mischen.

Ohne Qt, nur numpy – testbar. Zeitmaß nach PARIS-Norm: Punkt = 1 Einheit, Strich = 3, Pause im
Zeichen = 1, zwischen Buchstaben = 3, zwischen Wörtern = 7; eine Einheit = 1,2 s / WpM.
Jeder Ton hat weiche Flanken (5 ms), sonst klickt es.
"""

from __future__ import annotations

import math

import numpy as np

RATE = 48000

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.",
    "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.",
    "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-",
    "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-", "5": ".....",
    "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    "/": "-..-.", "?": "..--..", "=": "-...-", ",": "--..--", ".": ".-.-.-", "+": ".-.-.",
    "-": "-....-",
}


def unit_s(wpm: float) -> float:
    return 1.2 / max(5.0, float(wpm))


def elements(text: str) -> list[tuple[bool, int]]:
    """(Ton an?, Länge in Einheiten) – unbekannte Zeichen werden übersprungen."""
    out: list[tuple[bool, int]] = []
    words = [w for w in text.upper().split() if any(c in MORSE for c in w)]
    for wi, word in enumerate(words):
        letters = [c for c in word if c in MORSE]
        for li, ch in enumerate(letters):
            code = MORSE[ch]
            for ei, sym in enumerate(code):
                out.append((True, 1 if sym == "." else 3))
                if ei < len(code) - 1:
                    out.append((False, 1))
            if li < len(letters) - 1:
                out.append((False, 3))
        if wi < len(words) - 1:
            out.append((False, 7))
    return out


def duration_s(text: str, wpm: float) -> float:
    return sum(n for _on, n in elements(text)) * unit_s(wpm)


def render(text: str, wpm: float, pitch: float = 600.0, rate: int = RATE,
           rise_ms: float = 5.0) -> np.ndarray:
    """Morsezeichen als Tonfolge (Spitzenwert 1.0, float32)."""
    env = envelope(text, wpm, rate, rise_ms)
    t = np.arange(len(env), dtype=np.float64) / rate
    return (env * np.sin(2 * math.pi * pitch * t)).astype(np.float32)


def render_analytic(text: str, wpm: float, pitch: float = 600.0, rate: int = RATE
                    ) -> np.ndarray:
    """Wie render(), aber als komplexes Signal (nur positive Frequenz) – zum Verschieben beim
    Abstimmen (S&P-Übung, 0.8.29)."""
    env = envelope(text, wpm, rate)
    t = np.arange(len(env), dtype=np.float64) / rate
    return (env * np.exp(2j * math.pi * pitch * t)).astype(np.complex64)


def analytic(x: np.ndarray) -> np.ndarray:
    """Reelles Signal → komplexes ohne negative Frequenzen (Hilbert über die FFT)."""
    n = len(x)
    if n == 0:
        return np.zeros(0, np.complex64)
    spec = np.fft.fft(x)
    h = np.zeros(n)
    h[0] = 1.0
    if n % 2 == 0:
        h[n // 2] = 1.0
        h[1:n // 2] = 2.0
    else:
        h[1:(n + 1) // 2] = 2.0
    return np.fft.ifft(spec * h).astype(np.complex64)


def envelope(text: str, wpm: float, rate: int = RATE, rise_ms: float = 5.0) -> np.ndarray:
    """Tastung (0 … 1) mit weichen Flanken."""
    els = elements(text)
    u = unit_s(wpm)
    total = int(round(sum(n for _o, n in els) * u * rate))
    if total <= 0:
        return np.zeros(0, np.float32)
    env = np.zeros(total, np.float32)
    rise = max(1, int(rise_ms / 1000.0 * rate))
    ramp = (0.5 - 0.5 * np.cos(np.linspace(0, math.pi, rise))).astype(np.float32)
    pos = 0.0
    for on, n in els:
        a, b = int(round(pos * rate)), int(round((pos + n * u) * rate))
        if on and b > a:
            env[a:b] = 1.0
            r = min(rise, (b - a) // 2)
            if r > 1:
                rr = ramp if r == rise else \
                    (0.5 - 0.5 * np.cos(np.linspace(0, math.pi, r))).astype(np.float32)
                env[a:a + r] *= rr
                env[b - r:b] *= rr[::-1]
        pos += n * u
    return env


def cut_numbers(text: str, leading_only: bool = False) -> str:
    """Abgekürzte Zahlen: 0 → T, 9 → N (z. B. „5NN 109“ → „5NN 1TN“)."""
    out = []
    for tok in text.split():
        if tok.isdigit():
            if leading_only:
                s = tok.lstrip("0")
                tok = "T" * (len(tok) - len(s)) + s
            else:
                tok = tok.replace("0", "T").replace("9", "N")
        out.append(tok)
    return " ".join(out)


def band_noise(seconds: float = 8.0, low: float = 300.0, high: float = 1000.0,
               rate: int = RATE, seed: int = 1) -> np.ndarray:
    """Rauschen wie hinter einem CW-Filter: nur 300–1000 Hz. Über die FFT erzeugt, daher ohne
    Naht wiederholbar (Effektivwert 1)."""
    n = int(seconds * rate)
    rng = np.random.default_rng(seed)
    spec = rng.normal(size=n // 2 + 1) + 1j * rng.normal(size=n // 2 + 1)
    f = np.fft.rfftfreq(n, 1.0 / rate)
    edge = 80.0
    gain = np.clip((f - low + edge) / edge, 0, 1) * np.clip((high + edge - f) / edge, 0, 1)
    x = np.fft.irfft(spec * gain, n)
    x /= max(1e-9, float(np.sqrt(np.mean(x * x))))
    return x.astype(np.float32)


def db(x: float) -> float:
    return float(10 ** (x / 20.0))


class Mixer:
    """Fortlaufender Tonstrom: Rauschen + alle geplanten Signale.

    Die Zeit ist der Strom selbst (Abtastwerte seit Beginn) – so passen Ablauf und Gehörtes
    immer zusammen, egal wie die Soundkarte puffert."""

    def __init__(self, noise_db: float = -30.0, volume: float = 0.5, rate: int = RATE,
                 band: tuple[float, float] = (300.0, 1000.0)):
        self.rate = rate
        self.pos = 0                                  # nächster Abtastwert
        self.noise = band_noise(low=band[0], high=band[1], rate=rate)   # SSB: 300–2700 Hz
        self.noise_gain = db(noise_db)
        self.volume = volume
        self._sig: list[list] = []                    # [start, daten, wer]
        # abstimmbare Signale (S&P-Übung, 0.8.29): [start, komplex, wer, Frequenz Hz, Phase]
        self._tun: list[list] = []
        self.vfo: float | None = None                 # Frequenz des Funkgeräts (Hz)
        self.sideband = 1                             # +1: USB/CW, −1: LSB/CW-R
        self._vfo_s: float | None = None              # geglättet – kein Springen des Tons
        self._filt = (600.0, 250.0)                   # Mitte, halbe Breite des Empfangsfilters
        self._tail = np.zeros(0, np.complex64)
        self._h: dict = {}

    @property
    def now(self) -> float:
        return self.pos / self.rate

    def add(self, samples: np.ndarray, start_s: float, gain_db: float = 0.0,
            qsb: tuple[float, float, float] | None = None, who: str = "") -> float:
        """Signal ab start_s (Sekunden im Strom) einplanen; gibt das Ende zurück.
        qsb = (Frequenz Hz, Tiefe dB, Phase) – langsames Auf und Ab der Lautstärke."""
        start = max(self.pos, int(round(start_s * self.rate)))
        x = samples.astype(np.float32) * db(gain_db)
        if qsb and qsb[1] > 0 and len(x):
            t = (start + np.arange(len(x))) / self.rate
            fade = (1 - np.sin(2 * math.pi * qsb[0] * t + qsb[2])) / 2       # 0 … 1
            x = x * (10 ** (-qsb[1] * fade / 20.0)).astype(np.float32)
        self._sig.append([start, x, who])
        return (start + len(x)) / self.rate

    def add_tuned(self, samples: np.ndarray, start_s: float, rf_hz: float, gain_db: float = 0.0,
                  qsb: tuple[float, float, float] | None = None, who: str = "") -> float:
        """Signal einer Station auf rf_hz (komplex, so wie es genau abgestimmt klingt). Was man
        hört, hängt vom VFO ab: daneben höher/tiefer, außerhalb des Filters nichts."""
        start = max(self.pos, int(round(start_s * self.rate)))
        x = samples.astype(np.complex64) * db(gain_db)
        if qsb and qsb[1] > 0 and len(x):
            t = (start + np.arange(len(x))) / self.rate
            fade = (1 - np.sin(2 * math.pi * qsb[0] * t + qsb[2])) / 2
            x = x * (10 ** (-qsb[1] * fade / 20.0)).astype(np.float32)
        self._tun.append([start, x, who, float(rf_hz), 0.0])
        return (start + len(x)) / self.rate

    def set_filter(self, center: float, half_width: float) -> None:
        """Empfangsfilter (Hz im Ton), z. B. CW 600 ± 250, SSB 1500 ± 1200."""
        self._filt = (float(center), float(half_width))
        self._h.clear()

    def tune(self, vfo_hz: float | None, sideband: int = 1) -> None:
        self.vfo = vfo_hz
        self.sideband = -1 if sideband < 0 else 1
        if vfo_hz is None:
            self._vfo_s = None

    def cancel(self, who: str) -> None:
        """Signale von „who“ ab jetzt abbrechen (eigenes Senden mit Esc)."""
        for name in ("_sig", "_tun"):
            keep = []
            for s in getattr(self, name):
                if s[2] != who:
                    keep.append(s)
                elif s[0] < self.pos:
                    s[1] = s[1][: self.pos - s[0]]
                    keep.append(s)
            setattr(self, name, keep)

    def busy_until(self, who: str) -> float:
        ends = [(s[0] + len(s[1])) / self.rate for s in self._sig + self._tun if s[2] == who]
        return max(ends, default=0.0)

    TAPS = 1023

    def _kernel(self, nfft: int) -> np.ndarray:
        h = self._h.get(nfft)
        if h is None:
            c, w = self._filt
            n = np.arange(self.TAPS) - (self.TAPS - 1) / 2
            lp = 2 * w / self.rate * np.sinc(2 * w / self.rate * n) * np.blackman(self.TAPS)
            k = lp * np.exp(2j * math.pi * c * n / self.rate)
            h = self._h[nfft] = np.fft.fft(k, nfft)
        return h

    def _render_tuned(self, a: int, b: int) -> np.ndarray | None:
        n = b - a
        if not self._tun and not len(self._tail):
            return None
        acc = np.zeros(n, np.complex128)
        vfo = self.vfo
        if vfo is not None:
            v0 = self._vfo_s if self._vfo_s is not None else vfo
            v1 = v0 + (vfo - v0) * (1 - math.exp(-n / self.rate / 0.06))
            self._vfo_s = v1
            vline = np.linspace(v0, v1, n, endpoint=False)
        keep = []
        for s in self._tun:
            st, x, _who, rf, ph = s
            end = st + len(x)
            if end <= a:
                continue
            keep.append(s)
            if st >= b or vfo is None:
                continue
            lo, hi = max(a, st), min(b, end)
            df = self.sideband * (rf - vline[lo - a:hi - a])
            if float(np.min(np.abs(df))) > 6000:       # weit weg: nicht hörbar
                s[4] = ph + 2 * math.pi * float(np.sum(df)) / self.rate
                continue
            phase = ph + 2 * math.pi * np.cumsum(df) / self.rate
            s[4] = float(phase[-1])
            acc[lo - a:hi - a] += x[lo - st:hi - st] * np.exp(1j * (phase - 2 * math.pi * df
                                                                   / self.rate))
        self._tun = keep
        # Empfangsfilter (komplex: nur das eingestellte Seitenband), Überlapp-Addition
        nfft = 1 << int(math.ceil(math.log2(n + self.TAPS - 1)))
        y = np.fft.ifft(np.fft.fft(acc, nfft) * self._kernel(nfft))
        t = self._tail
        y[:len(t)] += t
        self._tail = y[n:n + self.TAPS - 1].astype(np.complex64)
        return y[:n].real.astype(np.float32)

    def render(self, n: int) -> np.ndarray:
        a, b = self.pos, self.pos + n
        k = len(self.noise)
        idx = np.arange(a, b) % k
        out = self.noise[idx] * self.noise_gain
        keep = []
        for s in self._sig:
            st, x = s[0], s[1]
            end = st + len(x)
            if end <= a:
                continue
            keep.append(s)
            if st >= b:
                continue
            lo, hi = max(a, st), min(b, end)
            out[lo - a:hi - a] += x[lo - st:hi - st]
        self._sig = keep
        tuned = self._render_tuned(a, b)
        if tuned is not None:
            out = out + tuned
        self.pos = b
        out = out * self.volume
        return np.tanh(out * 1.2).astype(np.float32) / 1.2 * 1.0      # weich begrenzen
