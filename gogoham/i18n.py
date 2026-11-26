"""Sprache der Bedienoberfläche (ab 0.8.0).

Alle Texte im Programm stehen auf Deutsch im Code und werden mit ``tr()`` übersetzt::

    tr("Log speichern")                       -> "Save log" (auf Englisch)
    tr("{n} QSOs gespeichert", n=12)          -> "12 QSOs saved"

Die Übersetzungen liegen in ``gogoham/i18n/<sprache>.json`` als einfache Liste
„deutscher Text -> Übersetzung“. Fehlt eine Übersetzung, erscheint der englische Text
(ab 0.10.27; bei Englisch selbst der deutsche) – es geht also nie etwas kaputt.
Neue Sprachen tragen in ``_meta`` ``"beta": true``, bis ein Muttersprachler sie durchgesehen
hat – in der Auswahl steht dann „(Beta)“. Neue Sprachen: einfach eine weitere Datei anlegen
(Werkzeug: ``tools/i18n_check.py`` listet fehlende Texte).

Die Sprache wird beim Start gesetzt (Einstellung „language“: auto / de / en …),
bevor die Programmteile geladen werden. Umschalten wirkt nach einem Neustart.
"""

from __future__ import annotations

import json
import locale
import os
from pathlib import Path

LANG_DIR = Path(__file__).parent / "i18n"
SOURCE_LANG = "de"
FALLBACK_LANG = "en"            # für Systeme, deren Sprache GoGoHam (noch) nicht kann

_lang = SOURCE_LANG
_table: dict[str, str] = {}
_fallback: dict[str, str] = {}   # Englisch für Texte, die in der gewählten Sprache noch fehlen


def available() -> dict[str, str]:
    """Verfügbare Sprachen: Kürzel -> Name in der eigenen Sprache."""
    out = {"de": "Deutsch"}
    for p in sorted(LANG_DIR.glob("*.json")):
        try:
            meta = json.loads(p.read_text(encoding="utf-8")).get("_meta", {})
        except (OSError, ValueError):
            continue
        name = meta.get("name", p.stem)
        out[p.stem] = f"{name} (Beta)" if meta.get("beta") else name
    # alphabetisch nach Namen (Akzente ignoriert: „Čeština“ bei C), nicht nach Kürzel
    return dict(sorted(out.items(), key=lambda kv: _sort_key(kv[1])))


def _sort_key(name: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", name)
                   if not unicodedata.combining(c)).casefold()


def system_language() -> str:
    """Sprache des Systems (z. B. "de" aus LANG=de_DE.UTF-8)."""
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        v = os.environ.get(var, "")
        if v and v not in ("C", "POSIX"):
            return v.split(":")[0].split("_")[0].split(".")[0].lower()
    try:
        loc = locale.getlocale()[0] or ""
    except ValueError:
        loc = ""
    return loc.split("_")[0].lower() if loc else SOURCE_LANG


def resolve(setting: str | None) -> str:
    """Einstellung („auto“, „de“, „en“ …) in eine verfügbare Sprache umsetzen."""
    langs = available()
    want = (setting or "auto").lower()
    if want == "auto":
        want = system_language()
    if want in langs:
        return want
    return FALLBACK_LANG if FALLBACK_LANG in langs else SOURCE_LANG


def set_language(setting: str | None) -> str:
    """Sprache setzen; Ergebnis ist das tatsächlich benutzte Kürzel."""
    global _lang, _table, _fallback
    _lang = resolve(setting)
    _table = _load(_lang) if _lang != SOURCE_LANG else {}
    _fallback = _load(FALLBACK_LANG) if _lang not in (SOURCE_LANG, FALLBACK_LANG) else {}
    return _lang


def _load(lang: str) -> dict[str, str]:
    try:
        data = json.loads((LANG_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if k != "_meta" and isinstance(v, str) and v}


def language() -> str:
    return _lang


def tr(text: str, **kw) -> str:
    """Text übersetzen; Platzhalter {name} werden mit kw gefüllt."""
    t = _table.get(text) or _fallback.get(text) or text
    if kw:
        try:
            return t.format(**kw)
        except (KeyError, IndexError, ValueError):
            en = _fallback.get(text)          # kaputte Übersetzung: lieber Englisch, sonst Deutsch
            if en:
                try:
                    return en.format(**kw)
                except (KeyError, IndexError, ValueError):
                    pass
            return text.format(**kw)
    return t


COMMA_LANGS = ("de", "fr", "es", "it", "nl", "pl", "pt", "cs", "sk", "sl", "hr", "da", "ro",
               "hu", "tr", "ru", "uk", "sv", "fi", "no", "nb", "id")


def decimal_comma() -> bool:
    """Schreibt die eingestellte Sprache Dezimalzahlen mit Komma (28,5)?"""
    return _lang in COMMA_LANGS


def num(x: float, decimals: int = 0) -> str:
    """Zahl im Format der Sprache: de 28.450,00 – en 28,450.00."""
    s = f"{x:,.{decimals}f}"
    if decimal_comma():
        s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return s
