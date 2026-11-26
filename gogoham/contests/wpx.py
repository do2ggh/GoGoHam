"""Rechenweg WPX-Präfix (CQ WPX, Regel-Baustein „wpx_prefix“).

Die Punkte- und Multi-Regeln des WPX stehen seit 0.6.1 in den
Regel-Dateien gogoham/rules/wpx-ssb.json und wpx-cw.json.
"""

from __future__ import annotations

import re


_IGNORE = {"P", "M", "MM", "AM", "QRP", "QRPP", "A", "B", "J", "LH", "R", "N",
           "T", "E", "X", "PM"}


def _base_prefix(s: str) -> str:
    """Präfix eines einzelnen Rufzeichen-Teils.

    Alles bis einschließlich der letzten Ziffer vor dem Suffix:
    DL1ABC -> DL1, 4X1AB -> 4X1, LY2000X -> LY2000, 3DA0RS -> 3DA0.
    Ohne Ziffer wird eine 0 angehängt (RAEM -> RA0).
    """
    m = re.match(r"^(.*\d)[A-Z]+$", s)
    if m:
        return m.group(1)
    if any(ch.isdigit() for ch in s):
        return s
    return s[:2] + "0"


def wpx_prefix(call: str) -> str | None:
    call = (call or "").strip().upper()
    parts = [p for p in call.split("/") if p]
    while len(parts) > 1 and parts[-1] in _IGNORE:
        parts.pop()
    if not parts:
        return None
    if len(parts) == 1:
        return _base_prefix(parts[0])
    a, b = parts[0], parts[1]
    if b.isdigit():
        # N8BJQ/4 -> N4 (Ziffer des Präfixes ersetzen)
        p = _base_prefix(a)
        return re.sub(r"\d+$", "", p) + b
    designator = a if len(a) <= len(b) else b
    # Portabel-Präfix: KH6 bleibt KH6, DL wird DL0, OH0 bleibt OH0
    if designator[-1].isdigit():
        return designator
    return _base_prefix(designator)
