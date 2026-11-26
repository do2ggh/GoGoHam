"""Sprachausgabe mit der eigenen Stimme (ab 0.8.11).

Jeder nimmt seine Ansagen selbst auf (Einstellungen → Ton & Ansagen → Sprachaufnahmen): feste Texte wie CQ und TU,
dazu einmal die Buchstaben (Buchstabieralphabet), die Ziffern und den Schrägstrich. Daraus setzt
GoGoHam Rufzeichen und Nummern zusammen.

Dieser Teil kennt kein Qt – er speichert/liest die Aufnahmen (WAV, 48 kHz, mono, 16 Bit),
schneidet die Stille ab, macht alle gleich laut, wendet den Klang an und baut aus einem
Funktionstasten-Text (z. B. ``{CALL} {RST} {EXCH}``) die fertige Ansage zusammen.

Die Rohaufnahme bleibt immer unverändert auf der Platte – Klang, Lautstärke und Sendepegel
wirken erst beim Abspielen und lassen sich jederzeit ändern.
"""

from __future__ import annotations

import os
import re
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .i18n import tr

RATE = 48000                      # Abtastrate aller Aufnahmen und Ansagen

# Feste Ansagen: Kürzel (im Funktionstasten-Text als [KÜRZEL]) -> Name, Beispiel
PHRASES = (
    ("CQ", "CQ-Ruf", "CQ Contest"),
    ("MYCALL", "Eigenes Rufzeichen (wahlweise)", "„Delta Oscar Two …“ – sonst buchstabiert"),
    ("TU", "Danke", "Thank you"),
    ("QRZ", "QRZ?", "QRZ?"),
    ("AGN", "Bitte wiederholen", "Again please"),
    ("NR", "Nummer?", "Your number please?"),
    ("CALLQ", "Rufzeichen?", "Your call again?"),
    ("X1", "Eigene Ansage 1", ""),
    ("X2", "Eigene Ansage 2", ""),
    ("X3", "Eigene Ansage 3", ""),
    ("X4", "Eigene Ansage 4", ""),
)
PHONETIC = {
    "A": "Alfa", "B": "Bravo", "C": "Charlie", "D": "Delta", "E": "Echo", "F": "Foxtrot",
    "G": "Golf", "H": "Hotel", "I": "India", "J": "Juliett", "K": "Kilo", "L": "Lima",
    "M": "Mike", "N": "November", "O": "Oscar", "P": "Papa", "Q": "Quebec", "R": "Romeo",
    "S": "Sierra", "T": "Tango", "U": "Uniform", "V": "Victor", "W": "Whiskey", "X": "X-ray",
    "Y": "Yankee", "Z": "Zulu",
    "0": "Zero", "1": "One", "2": "Two", "3": "Three", "4": "Four", "5": "Five", "6": "Six",
    "7": "Seven", "8": "Eight", "9": "Nine",
}
SLASH = "SLASH"                   # „/“ – z. B. DO2GGH/P
PHRASE_IDS = tuple(p[0] for p in PHRASES)
# Nur damit das Übersetzungs-Werkzeug die Namen oben findet (übersetzt wird in all_items)
_FOR_TRANSLATION = (tr("CQ-Ruf"), tr("Eigenes Rufzeichen (wahlweise)"),
                    tr("„Delta Oscar Two …“ – sonst buchstabiert"), tr("Danke"),
                    tr("Bitte wiederholen"), tr("Nummer?"), tr("Rufzeichen?"),
                    tr("Eigene Ansage 1"), tr("Eigene Ansage 2"), tr("Eigene Ansage 3"),
                    tr("Eigene Ansage 4"))

GAP_LETTER = 0.08                 # Pause zwischen zwei Buchstaben (s)
GAP_WORD = 0.25                   # Pause zwischen zwei Wörtern / Ansagen (s)

# Klang: Voreinstellungen (Regler in dB, Lautstärke in %)
# „Kräftig“ (ab 0.8.11.2): Kompromiss aus Normal und Contest – Brummfilter unter ~120 Hz,
# weniger Bass und Tiefmitten (dumpf), mehr Präsenz; keine eigene Kompression, weil der
# Sprachprozessor im Funkgerät das übernimmt
PRESETS = {
    "normal": {"bass": 0, "lowmid": 0, "mid": 0, "treble": 0},
    "strong": {"bass": -4, "lowmid": -4, "mid": 2, "treble": 5},
    "contest": {"bass": -6, "lowmid": 0, "mid": 3, "treble": 6},
}
DEFAULT_TONE = {"preset": "normal", "bass": 0, "lowmid": 0, "mid": 0, "treble": 0, "volume": 100}

# Funktionstasten-Texte für SSB, wenn GoGoHam selbst spricht
DEFAULT_SSB_TEXT = {
    "F1": "[CQ] {MYCALL} {MYCALL}",
    "F2": "{CALL} {RST} {EXCH}",
    "F3": "[TU] {MYCALL}",
    "F4": "{MYCALL}",
    "F5": "{CALL}",
    "F6": "[AGN]",
    "F7": "[CALLQ]",
    "F8": "[NR]",
}


def all_items() -> list[tuple[str, str, str]]:
    """Alles, was man aufnehmen kann: (Kürzel, Name, was man sagt)."""
    out = [(pid, tr(name), tr(hint) if hint else "") for pid, name, hint in PHRASES]
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
        out.append((ch, ch, PHONETIC[ch]))
    out.append((SLASH, "/", tr("„Stroke“ (Schrägstrich, z. B. /P)")))
    return out


def required_for_spelling() -> list[str]:
    """Was zum Buchstabieren von Rufzeichen und Nummern nötig ist."""
    return list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


# ------------------------------------------------------------------ Dateien
def voice_dir() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "gogoham" / "voice"


def clip_path(item: str, base: Path | None = None) -> Path:
    return (base or voice_dir()) / f"{item}.wav"


def save_wav(path: Path, samples: np.ndarray) -> None:
    """Gleitkomma-Samples (-1 … 1) als WAV 48 kHz mono 16 Bit speichern."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data)
    tmp.replace(path)


def load_wav(path: Path) -> np.ndarray:
    """WAV lesen und nach 48 kHz mono (Gleitkomma) umwandeln."""
    with wave.open(str(path), "rb") as w:
        ch, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    elif width == 1:
        x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 4:
        x = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(tr("WAV-Format wird nicht unterstützt"))
    return to_mono(x, ch, rate)


def to_mono(x: np.ndarray, channels: int, rate: int) -> np.ndarray:
    """Mehrkanal -> mono (Mittelwert) und auf 48 kHz umrechnen."""
    if channels > 1:
        n = len(x) // channels
        x = x[: n * channels].reshape(n, channels).mean(axis=1)
    return resample(x.astype(np.float32), rate, RATE)


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or len(x) == 0:
        return x
    n = max(1, int(round(len(x) * dst / src)))
    t = np.linspace(0, len(x) - 1, n)
    return np.interp(t, np.arange(len(x)), x).astype(np.float32)


def recorded(base: Path | None = None) -> set[str]:
    """Kürzel aller vorhandenen Aufnahmen."""
    d = base or voice_dir()
    return {p.stem for p in d.glob("*.wav")} if d.is_dir() else set()


# ---------------------------------------------------------- Bearbeitung
def _frames_rms(x: np.ndarray, frame: int) -> np.ndarray:
    n = len(x) // frame
    if n == 0:
        return np.zeros(0, np.float32)
    return np.sqrt((x[: n * frame].reshape(n, frame) ** 2).mean(axis=1))


def trim_silence(x: np.ndarray, pad_start: float = 0.03, pad_end: float = 0.06) -> np.ndarray:
    """Stille am Anfang und Ende abschneiden (mit kurzem Rand und weichem Ein-/Ausblenden).

    Ab 0.8.11.1: Die Schwelle richtet sich nach dem Grundrauschen der Aufnahme, und kurze
    Knackser (Mausklick auf Aufnehmen/Stopp, Einschaltknacks des Mikrofons) zählen nicht als
    Sprache – nur Stellen, die mindestens 60 ms lang laut sind. Kurze Laute dicht davor oder
    danach (z. B. das „t“ am Ende von „Eight“) bleiben erhalten.
    """
    frame = RATE // 100                                     # 10 ms
    rms = _frames_rms(x, frame)
    if len(rms) == 0 or rms.max() < 10 ** (-60 / 20):
        return np.zeros(0, np.float32)
    db = 20 * np.log10(np.maximum(rms, 1e-7))
    noise = float(np.percentile(db, 10))
    # Rauschen + 12 dB – aber nie näher als 15 dB an der Spitze (Aufnahme ohne Pause)
    thr = max(db.max() - 30.0, min(noise + 12.0, db.max() - 15.0), -60.0)
    loud = db >= thr
    # zusammenhängende laute Stellen
    runs, i, n = [], 0, len(loud)
    while i < n:
        if loud[i]:
            j = i
            while j < n and loud[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    speech = [r for r in runs if r[1] - r[0] >= 6]          # mindestens 60 ms
    if not speech:
        speech = [max(runs, key=lambda r: r[1] - r[0])]
    a, b = speech[0][0], speech[-1][1]
    near = 15                                               # 150 ms: gehört noch dazu
    for r0, r1 in reversed([r for r in runs if r[1] <= a]):
        if a - r1 <= near:
            a = r0
        else:
            break
    for r0, r1 in [r for r in runs if r[0] >= b]:
        if r0 - b <= near:
            b = r1
        else:
            break
    s0 = max(0, a * frame - int(pad_start * RATE))
    s1 = min(len(x), b * frame + int(pad_end * RATE))
    y = x[s0:s1].copy()
    fade = min(len(y) // 2, RATE // 200)                    # 5 ms
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        y[:fade] *= ramp
        y[-fade:] *= ramp[::-1]
    return y


def normalize(x: np.ndarray, target_db: float = -20.0, peak: float = 0.89) -> np.ndarray:
    """Alle gleich laut: Lautheit der gesprochenen Teile auf target_db, Spitzen höchstens peak."""
    if len(x) == 0:
        return x
    frame = RATE // 100
    rms = _frames_rms(x, frame)
    if len(rms) == 0 or rms.max() <= 0:
        return x
    active = rms[rms >= rms.max() * 10 ** (-30 / 20)]
    level = float(np.sqrt((active ** 2).mean())) if len(active) else float(rms.max())
    gain = 10 ** (target_db / 20) / max(level, 1e-6)
    pk = float(np.abs(x).max()) * gain
    if pk > peak:
        gain *= peak / pk
    return (x * gain).astype(np.float32)


def prepare_clip(x: np.ndarray) -> np.ndarray:
    """Rohaufnahme -> abgeschnitten und auf gleiche Lautstärke gebracht."""
    return normalize(trim_silence(x))


def _eq_gain_db(f: np.ndarray, bass: float, mid: float, treble: float,
                lowmid: float = 0.0) -> np.ndarray:
    ff = np.maximum(f, 1.0)
    low = 1.0 / (1.0 + (ff / 250.0) ** 2)                   # Bässe unter ~250 Hz
    high = 1.0 / (1.0 + (2500.0 / ff) ** 2)                 # Höhen über ~2,5 kHz
    bell = np.exp(-(np.log2(ff / 1000.0) ** 2) / (2 * 0.9 ** 2))   # Mitten um 1 kHz
    lbell = np.exp(-(np.log2(ff / 420.0) ** 2) / (2 * 0.6 ** 2))   # Tiefmitten um 420 Hz
    return bass * low + lowmid * lbell + mid * bell + treble * high


def _highpass_db(f: np.ndarray, fc: float = 120.0) -> np.ndarray:
    """Brummfilter: alles unter fc kräftig absenken (Netzbrummen, Tritt- und Pultgeräusche)."""
    ff = np.maximum(f, 1.0)
    return 20 * np.log10(np.maximum(1.0 / np.sqrt(1.0 + (fc / ff) ** 8), 1e-4))


def _bandpass_db(f: np.ndarray) -> np.ndarray:
    """Contest: tiefe Brummtöne und Höhen über der SSB-Bandbreite weg (300 Hz … 2,7 kHz)."""
    ff = np.maximum(f, 1.0)
    hp = 1.0 / np.sqrt(1.0 + (300.0 / ff) ** 8)
    lp = 1.0 / np.sqrt(1.0 + (ff / 2700.0) ** 8)
    return 20 * np.log10(np.maximum(hp * lp, 1e-4))


def equalize(x: np.ndarray, bass: float, mid: float, treble: float,
             bandpass: bool = False, lowmid: float = 0.0, highpass: bool = False) -> np.ndarray:
    if len(x) == 0 or (not bandpass and not highpass and bass == mid == treble == lowmid == 0):
        return x
    pad = RATE // 10                                         # Rand gegen Echo am Ende
    n = 1 << int(np.ceil(np.log2(len(x) + 2 * pad)))
    spec = np.fft.rfft(x, n)
    f = np.fft.rfftfreq(n, 1.0 / RATE)
    db = _eq_gain_db(f, bass, mid, treble, lowmid)
    if bandpass:
        db = db + _bandpass_db(f)
    elif highpass:
        db = db + _highpass_db(f)
    y = np.fft.irfft(spec * 10 ** (db / 20), n)[: len(x)]
    return y.astype(np.float32)


def compress(x: np.ndarray, threshold_db: float = -26.0, ratio: float = 3.0) -> np.ndarray:
    """Einfacher Kompressor: leise Silben kommen näher an die lauten heran."""
    if len(x) == 0:
        return x
    win = RATE // 50                                        # 20 ms
    c = np.concatenate(([0.0], np.cumsum(x.astype(np.float64) ** 2)))
    idx = np.arange(len(x))
    lo = np.maximum(idx - win // 2, 0)
    hi = np.minimum(idx + win // 2, len(x))
    env = np.sqrt((c[hi] - c[lo]) / np.maximum(hi - lo, 1))
    thr = 10 ** (threshold_db / 20)
    gain = np.where(env > thr, (np.maximum(env, 1e-9) / thr) ** (1.0 / ratio - 1.0), 1.0)
    return (x * gain).astype(np.float32)


def apply_tone(x: np.ndarray, tone: dict | None) -> np.ndarray:
    """Klang (Voreinstellung + Regler) und Lautstärke anwenden – so klingt es beim Probehören
    und beim Senden gleich."""
    t = dict(DEFAULT_TONE, **(tone or {}))
    contest = t.get("preset") == "contest"
    y = equalize(x, float(t["bass"]), float(t["mid"]), float(t["treble"]), bandpass=contest,
                 lowmid=float(t.get("lowmid", 0)), highpass=t.get("preset") == "strong")
    if contest:
        y = compress(y)
        y = normalize(y, target_db=-17.0)
    else:
        y = normalize(y)
    y = y * (max(0, int(t.get("volume", 100))) / 100.0)
    return np.clip(y, -1.0, 1.0).astype(np.float32)


def apply_send_level(x: np.ndarray, percent: int) -> np.ndarray:
    """Sendepegel: nur auf dem Weg zum Funkgerät."""
    return np.clip(x * (max(0, int(percent)) / 100.0), -1.0, 1.0).astype(np.float32)


def to_int16_bytes(x: np.ndarray, channels: int = 1) -> bytes:
    y = (np.clip(x, -1.0, 1.0) * 32767).astype("<i2")
    if channels > 1:
        y = np.repeat(y, channels)
    return y.tobytes()


# ----------------------------------------------------------- Zusammenbau
@dataclass
class Plan:
    """Was aus einem Funktionstasten-Text gesprochen wird."""
    parts: list = field(default_factory=list)   # Kürzel (str) oder Pause (float, Sekunden)
    missing: list = field(default_factory=list)  # fehlende Aufnahmen (Kürzel), ohne Doppelte
    text: str = ""                               # lesbare Fassung für die Anzeige

    @property
    def empty(self) -> bool:
        return not any(isinstance(p, str) for p in self.parts)


_TOKEN = re.compile(r"\[([A-Za-z0-9]+)\]|(\S+)")


def substitute(text: str, values: dict, have: set[str]) -> str:
    """Platzhalter einsetzen. {MYCALL} wird zur Aufnahme [MYCALL], wenn es eine gibt."""
    my = values.get("MYCALL", "")
    out = text.replace("{MYCALL}", "[MYCALL]" if "MYCALL" in have else my)
    for k in ("CALL", "EXCH", "RST"):
        out = out.replace("{" + k + "}", values.get(k, ""))
    return out


def plan(text: str, values: dict, have: set[str]) -> Plan:
    """Text mit Platzhaltern -> Reihenfolge der Aufnahmen und Pausen."""
    p = Plan()
    shown = []
    for m in _TOKEN.finditer(substitute(text, values, have)):
        if p.parts:
            p.parts.append(GAP_WORD)
        if m.group(1):
            pid = m.group(1).upper()
            p.parts.append(pid)
            shown.append(values.get("MYCALL", pid) if pid == "MYCALL" else pid)
            if pid not in have and pid not in p.missing:
                p.missing.append(pid)
            continue
        word = m.group(2).upper()
        spelled = []
        for ch in word:
            item = SLASH if ch == "/" else ch
            if item != SLASH and item not in PHONETIC:
                continue                                # Satzzeichen wie „?“ werden übergangen
            if spelled:
                p.parts.append(GAP_LETTER)
            p.parts.append(item)
            spelled.append(ch)
            if item not in have and item not in p.missing:
                p.missing.append(item)
        if not spelled and p.parts and p.parts[-1] == GAP_WORD:
            p.parts.pop()
        if spelled:
            shown.append("".join(spelled))
    while p.parts and not isinstance(p.parts[-1], str):
        p.parts.pop()
    p.text = " ".join(shown)
    return p


class ClipCache:
    """Hält die bearbeiteten Aufnahmen im Speicher (neu geladen, wenn sich die Datei ändert)."""

    def __init__(self, base: Path | None = None):
        self.base = base
        self._c: dict[str, tuple[float, np.ndarray]] = {}

    def get(self, item: str) -> np.ndarray | None:
        path = clip_path(item, self.base)
        try:
            mt = path.stat().st_mtime
        except OSError:
            self._c.pop(item, None)
            return None
        hit = self._c.get(item)
        if hit and hit[0] == mt:
            return hit[1]
        try:
            x = prepare_clip(load_wav(path))
        except (OSError, ValueError, EOFError, wave.Error):
            return None
        self._c[item] = (mt, x)
        return x

    def forget(self, item: str) -> None:
        self._c.pop(item, None)

    def have(self) -> set[str]:
        return recorded(self.base)


def render(p: Plan, cache: ClipCache, tone: dict | None) -> np.ndarray:
    """Plan -> fertige Ansage (Klang schon angewendet, ohne Sendepegel)."""
    out = []
    for part in p.parts:
        if isinstance(part, str):
            x = cache.get(part)
            if x is not None:
                out.append(x)
        else:
            out.append(np.zeros(int(part * RATE), np.float32))
    if not out:
        return np.zeros(0, np.float32)
    return apply_tone(np.concatenate(out), tone)


def missing_text(missing: list[str]) -> str:
    """Fehlende Aufnahmen lesbar, z. B. „Q (Quebec), 7 (Seven)“."""
    names = {pid: tr(name) for pid, name, _h in PHRASES}
    out = []
    for m in missing:
        if m in PHONETIC:
            out.append(f"{m} ({PHONETIC[m]})")
        elif m == SLASH:
            out.append("/")
        else:
            out.append(names.get(m, m))
    return ", ".join(out)
