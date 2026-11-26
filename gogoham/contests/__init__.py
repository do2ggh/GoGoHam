"""Verfügbare Contests – seit 0.6.1 aus den Regel-Dateien (gogoham/rules/*.json).

Neue Contests: einfach eine Regel-Datei anlegen (siehe Handbuch „Regel-Dateien“),
eingebaut in gogoham/rules/ oder eigene in ~/.local/share/gogoham/rules/.
"""

from __future__ import annotations

from ..i18n import tr

from .. import rulefiles
from .base import Contest, Qso, QsoEval, Scorer, Station
from .freelog import FREE_ID, FreeLog
from .rulebased import RuleContest, make_contest_class
from .wpx import wpx_prefix


def build_contests(result: rulefiles.LoadResult) -> dict[str, type[RuleContest]]:
    classes = [make_contest_class(rs.data, rs.path, rs.builtin, rs.source)
               for rs in result.rules.values()]
    classes.sort(key=lambda c: c.name.lower())
    # 0.10.18: das freie Log (kein Contest) steht immer ganz oben
    return {FREE_ID: FreeLog, **{c.id: c for c in classes if c.id != FREE_ID}}


def is_free(cls) -> bool:
    """Freies Log (kein Contest)? Gilt für Klasse und Objekt."""
    return bool(getattr(cls, "free", False))


def contest_count() -> int:
    """Anzahl echter Contests (ohne das freie Log)."""
    return sum(1 for c in CONTESTS.values() if not is_free(c))


LOAD_RESULT = rulefiles.load_all()
CONTESTS: dict[str, type[RuleContest]] = build_contests(LOAD_RESULT)


def reload() -> rulefiles.LoadResult:
    """Regeln neu laden (z. B. nach einem Download). CONTESTS wird an Ort und Stelle
    erneuert, damit alle Programmteile die neuen Regeln sehen."""
    res = rulefiles.load_all()
    LOAD_RESULT.rules, LOAD_RESULT.problems, LOAD_RESULT.overrides = \
        res.rules, res.problems, res.overrides
    CONTESTS.clear()
    CONTESTS.update(build_contests(res))
    return res


def class_from_log(meta: dict) -> tuple[type[RuleContest] | None, str]:
    """Contest-Klasse aus den im Log gespeicherten Regeln (meta["rules_json"]).

    Ergebnis (Klasse oder None, Hinweistext). None = keine/ungültige Regeln im Log.
    """
    import json
    raw = meta.get("rules_json") or ""
    if not raw:
        return None, ""
    try:
        d = json.loads(raw)
    except ValueError:
        return None, tr("Die im Log gespeicherten Regeln sind beschädigt – es gelten die aktuellen.")
    errs = rulefiles.validate(d)
    if isinstance(d, dict) and d.get("id") == FREE_ID:
        return FreeLog, ""                       # freies Log: eingebaut, nicht aus Regeln
    if errs:
        return None, (tr("Die im Log gespeicherten Regeln passen nicht zu dieser "
                         "GoGoHam-Version ({p1}) – es gelten die aktuellen.", p1=errs[0]))
    return make_contest_class(d, None, False, "log"), ""

__all__ = ["CONTESTS", "FREE_ID", "LOAD_RESULT", "Contest", "FreeLog", "Qso", "QsoEval",
           "RuleContest", "Scorer", "Station", "build_contests", "class_from_log",
           "contest_count", "is_free", "reload", "wpx_prefix"]
