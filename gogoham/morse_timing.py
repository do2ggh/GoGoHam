"""Zeitablauf für den Morse-Ladebalken des Startbildschirms (ohne Qt, testbar).

Echtes Morse-Timing nach PARIS-Norm:
  Punkt = 1 Einheit, Strich = 3, Pause im Zeichen = 1,
  Pause zwischen Buchstaben = 3, Wortpause = 7.
  Eine Einheit dauert 1200 / WpM Millisekunden.
"""

from dataclasses import dataclass

MORSE = {"G": "--.", "H": "....", "D": "-..", "O": "---", "2": "..---"}

TEXT = "GGH"
WPM = 14


@dataclass(frozen=True)
class Element:
    kind: str        # "-" oder "."
    letter: int      # Index des Buchstabens (für Abstände im Balken)
    start: float     # ms ab Beginn des Durchlaufs
    duration: float  # ms


def unit_ms(wpm: float = WPM) -> float:
    return 1200.0 / wpm


def schedule(text: str = TEXT, wpm: float = WPM) -> list[Element]:
    u = unit_ms(wpm)
    t, out = 0.0, []
    for li, ch in enumerate(text):
        code = MORSE[ch]
        for ci, sym in enumerate(code):
            d = (3 if sym == "-" else 1) * u
            out.append(Element(sym, li, t, d))
            t += d
            if ci < len(code) - 1:
                t += u                 # Pause im Zeichen
        if li < len(text) - 1:
            t += 3 * u                 # Pause zwischen Buchstaben
    return out


def pass_ms(text: str = TEXT, wpm: float = WPM) -> float:
    """Dauer eines Durchlaufs (letztes Element endet)."""
    e = schedule(text, wpm)[-1]
    return e.start + e.duration


def cycle_ms(text: str = TEXT, wpm: float = WPM) -> float:
    """Durchlauf plus Wortpause – danach beginnt die Schleife von vorn."""
    return pass_ms(text, wpm) + 7 * unit_ms(wpm)


def fractions(t_ms: float, text: str = TEXT, wpm: float = WPM) -> list[float]:
    """Wie weit jedes Element zum Zeitpunkt t (ms seit Start) gefüllt ist (0…1)."""
    c = cycle_ms(text, wpm)
    t = t_ms % c
    res = []
    for e in schedule(text, wpm):
        f = (t - e.start) / e.duration
        res.append(0.0 if f <= 0 else 1.0 if f >= 1 else f)
    return res


def close_time(done_at_ms: float, text: str = TEXT, wpm: float = WPM) -> float:
    """Wann der Startbildschirm ausgeblendet wird.

    - Mindestens ein vollständiger Durchlauf plus Wortpause (bei 14 WpM ≈ 3,26 s).
    - Ist das Laden später fertig, wird der gerade laufende Durchlauf noch zu Ende
      gegeben; liegt man schon in der Wortpause, wird sofort ausgeblendet.
    """
    c, p = cycle_ms(text, wpm), pass_ms(text, wpm)
    if done_at_ms <= c:
        return c
    k = int(done_at_ms // c)
    t = done_at_ms - k * c
    if t >= p:
        return done_at_ms
    return k * c + p
