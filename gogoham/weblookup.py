"""Rufzeichen im Browser nachschlagen (ab 0.8.19.2): Rechtsklick im Log und in der Bandmap.

QRZ.com kennt nur Grundrufzeichen – „W1AW/P“ oder „EA8/DL1ABC“ findet es nicht. Deshalb
werden Zusätze wie /P, /M, /QRP und Gastland-Präfixe weggelassen.
"""

from __future__ import annotations

from urllib.parse import quote

QRZ_URL = "https://www.qrz.com/db/{call}"

# Zusätze, die nie das eigentliche Rufzeichen sind
_SUFFIXES = {"P", "M", "MM", "AM", "QRP", "A", "B", "R", "T", "LH", "J", "E"}


def base_call(call: str, is_prefix=None) -> str:
    """Grundrufzeichen: „W1AW/P“ -> „W1AW“, „EA8/DL1ABC“ -> „DL1ABC“, „DL1ABC/VE3“ -> „DL1ABC“.

    ``is_prefix(teil)`` (ab 0.8.15.1, aus der Länderdatei): True, wenn der Teil nur ein
    Länderpräfix ist. Damit wird auch „VP2E/W1AW“ richtig (VP2E = Anguilla), wo beide Teile
    gleich lang sind. Ohne Länderdatei entscheidet die Länge, bei Gleichstand der erste Teil."""
    parts = [p for p in (call or "").strip().upper().split("/") if p]
    if len(parts) <= 1:
        return parts[0] if parts else ""
    cand = [p for p in parts if p not in _SUFFIXES and not p.isdigit()]
    if not cand:
        return parts[0]
    if is_prefix is not None and len(cand) > 1:
        calls = [p for p in cand if not is_prefix(p)]
        if calls:
            cand = calls
    # Das Rufzeichen ist meist der längste Teil (DL/W1AW -> W1AW, W1AW/VE3 -> W1AW)
    return max(cand, key=len)


def qrz_url(call: str, is_prefix=None) -> str | None:
    """Adresse der QRZ.com-Seite zum Rufzeichen, None wenn nichts Brauchbares da ist."""
    c = base_call(call, is_prefix)
    if not c or not any(ch.isdigit() for ch in c):
        return None
    return QRZ_URL.format(call=quote(c, safe=""))
