"""Spalten der Log-Tabelle: alle verfügbaren Spalten, Standard je Contest,
gespeicherte Anordnung (Reihenfolge, Sichtbarkeit, Breite) pro Contest-Art.

Ein Contest legt seine Vorgabe über das Klassenattribut ``columns`` fest
(Liste von Spalten-Schlüsseln in der gewünschten Reihenfolge). Fehlt sie,
gilt DEFAULT_COLUMNS.
"""

from __future__ import annotations

from .i18n import tr

# Schlüssel -> (Spaltenkopf, Standardbreite). Platzhalter {ex} = Austausch-Name.
ALL_COLUMNS: dict[str, tuple[str, int]] = {
    "nr": (tr("Nr"), 50),
    "utc": ("UTC", 60),
    "band": ("Band", 50),
    "mode": ("Mode", 65),
    "khz": ("kHz", 85),
    "call": (tr("Rufzeichen"), 130),
    "rst_s": (tr("RST ges."), 65),
    "ex_s": (tr("{ex} ges."), 75),
    "rst_r": (tr("RST empf."), 70),
    "ex_r": (tr("{ex} empf."), 80),
    "land": (tr("Land"), 190),
    "prefix": (tr("Präfix"), 70),
    "km": ("km", 70),
    "name": (tr("Name"), 150),
    "pts": (tr("Pkt"), 45),
    "gain": (tr("Wert"), 60),
    "mult": (tr("Multi"), 90),
}
COLUMN_KEYS = list(ALL_COLUMNS)

DEFAULT_COLUMNS = ["utc", "band", "call", "ex_s", "ex_r", "land", "pts"]


def header_label(key: str, exchange_label: str) -> str:
    return ALL_COLUMNS[key][0].replace("{ex}", exchange_label)


def default_layout(contest_cls) -> dict:
    visible = [k for k in (getattr(contest_cls, "columns", None) or DEFAULT_COLUMNS)
               if k in ALL_COLUMNS]
    hidden = [k for k in COLUMN_KEYS if k not in visible]
    return {"order": visible + hidden, "hidden": hidden,
            "widths": {k: ALL_COLUMNS[k][1] for k in COLUMN_KEYS}}


def normalize(saved: dict | None, contest_cls) -> dict:
    """Gespeicherte Anordnung prüfen und um neue Spalten ergänzen."""
    base = default_layout(contest_cls)
    if not saved:
        return base
    order = [k for k in saved.get("order", []) if k in ALL_COLUMNS]
    order += [k for k in base["order"] if k not in order]          # neu hinzugekommene Spalten
    known = set(saved.get("order", []))
    hidden = [k for k in saved.get("hidden", []) if k in ALL_COLUMNS]
    hidden += [k for k in base["hidden"] if k not in known and k not in hidden]
    widths = dict(base["widths"])
    for k, w in (saved.get("widths") or {}).items():
        if k in widths and isinstance(w, int) and 20 <= w <= 1000:
            widths[k] = w
    if len(hidden) >= len(order):           # nie alle Spalten ausblenden
        hidden = [k for k in hidden if k != "call"]
    return {"order": order, "hidden": hidden, "widths": widths}
