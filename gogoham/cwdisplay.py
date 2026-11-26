"""Mitlaufende Anzeige des gesendeten CW-Texts (ab 0.8.10.1, ohne Qt, testbar).

Das Funkgerät meldet über Hamlib nicht, welchen Buchstaben es gerade gibt. GoGoHam
rechnet es deshalb aus dem Tempo aus (PARIS-Norm: Punkt 1 Einheit, Strich 3, Pause im
Zeichen 1, zwischen Buchstaben 3, zwischen Wörtern 7; eine Einheit = 1200 / WpM ms).

Mehrere Texte kurz hintereinander (z. B. S&P: Austausch + TU) reiht das Funkgerät
aneinander – die Anzeige auch.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.",
    "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.",
    "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-",
    "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-", "5": ".....",
    "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    "/": "-..-.", "?": "..--..", "=": "-...-", ".": ".-.-.-", ",": "--..--", "+": ".-.-.",
    "-": "-....-", "'": ".----.", "(": "-.--.", ")": "-.--.-", ":": "---...", "@": ".--.-.",
}

START_DELAY = 0.2        # s, bis das Funkgerät den Text bekommen hat und loslegt
LINGER = 3.0             # s, so lange bleibt der Text nach dem Ende stehen


def unit(wpm: float) -> float:
    return 1.2 / max(1.0, float(wpm))


def char_units(ch: str) -> int:
    """Dauer eines Zeichens in Einheiten, ohne die Pause danach."""
    code = MORSE.get(ch.upper())
    if not code:
        return 0
    return sum(3 if e == "-" else 1 for e in code) + len(code) - 1


def timeline(text: str, wpm: float) -> list[tuple[float, float]]:
    """(Beginn, Ende) jedes Zeichens in Sekunden ab Sendebeginn."""
    u = unit(wpm)
    t = 0.0
    out: list[tuple[float, float]] = []
    for i, ch in enumerate(text):
        if ch == " ":
            out.append((t, t + 4 * u))          # 3 Einheiten Buchstabenpause sind schon drin
            t += 4 * u
            continue
        d = char_units(ch) * u
        out.append((t, t + d))
        t += d
        if i + 1 < len(text):
            t += 3 * u                          # Pause bis zum nächsten Buchstaben
    return out


@dataclass
class _Part:
    text: str
    start: float
    times: list[tuple[float, float]]

    @property
    def end(self) -> float:
        return self.start + (self.times[-1][1] if self.times else 0.0)


@dataclass
class CwTicker:
    parts: list[_Part] = field(default_factory=list)
    stopped_at: float | None = None

    def add(self, text: str, wpm: float, now: float) -> None:
        """Neuer Text an das Funkgerät geschickt. wpm <= 0: Tempo unbekannt (keine Markierung)."""
        text = " ".join((text or "").upper().split())
        if not text:
            return
        if self.stopped_at is not None or not self.active(now):
            self.parts, self.stopped_at = [], None
        start = now + START_DELAY
        if self.parts:
            start = max(start, self.parts[-1].end + 7 * unit(wpm if wpm > 0 else 25))
        self.parts.append(_Part(text, start, timeline(text, wpm) if wpm > 0 else []))

    def stop(self, now: float) -> None:
        """Esc: Senden abgebrochen – Anzeige bleibt nicht stehen."""
        self.parts, self.stopped_at = [], now

    def end(self) -> float:
        if not self.parts:
            return 0.0
        last = self.parts[-1]
        if not last.times:              # Tempo unbekannt: grob 0,25 s je Zeichen
            return last.start + 0.25 * len(last.text)
        return last.end

    def active(self, now: float) -> bool:
        return bool(self.parts) and now < self.end() + LINGER

    def state(self, now: float) -> tuple[str, int, int] | None:
        """(ganzer Text, Anzahl fertiger Zeichen, Index des aktuellen Zeichens oder -1).

        Ohne bekanntes Tempo: fertig = -1 (Text nur anzeigen, nichts markieren).
        """
        if not self.active(now):
            return None
        full = " ".join(p.text for p in self.parts)
        if any(not p.times for p in self.parts):
            return full, -1, -1
        done, cur, offset = 0, -1, 0
        for p in self.parts:
            t = now - p.start
            for i, (a, b) in enumerate(p.times):
                if t >= b:
                    done = offset + i + 1
                elif t >= a:
                    cur = offset + i
                    break
                else:
                    break
            if cur >= 0 or t < p.times[-1][1]:
                break
            offset += len(p.text) + 1
            done = offset                       # Leerzeichen zwischen den Texten ist „fertig“
        return full, min(done, len(full)), cur
