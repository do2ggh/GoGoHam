"""Freies Log (ab 0.10.18): Alltags-QSOs loggen, ohne Contest.

Bewusst schlank (Nutzer 2026-11-13): Rufzeichen, RST gegeben/erhalten und eine freie
Bemerkung. Name, QTH und Locator kommen wie gewohnt aus der Online-Abfrage (Name/QTH).
Keine Punkte, keine Multis, keine Dupe-Sperre – stattdessen der Hinweis „schon gearbeitet“.
Gespeichert und exportiert wird ADIF.

Technisch ein eingebauter Sonderfall der Regel-Technik (keine Regel-Datei): so bleibt das
Regel-Format unverändert, und Logs öffnen sich wie jedes andere Log.
"""

from __future__ import annotations

from ..i18n import tr
from .base import Qso
from .rulebased import make_contest_class

FREE_ID = "freies-log"

# Alle Amateurfunkbänder bis 23 cm, alle Betriebsarten
RULES = {
    "format": 1,
    "revision": 1,
    "id": FREE_ID,
    "name": "Freies Log (kein Contest)",
    "bands": ["160", "80", "60", "40", "30", "20", "17", "15", "12", "10", "6", "4", "2",
              "70cm", "23cm"],
    "modes": ["PH", "CW", "RY", "DG"],
    "exchange": [{"field": "rst"}, {"field": "serial", "label": "Bemerkung"}],
    "points": {"type": "fixed", "value": 0},
    "multipliers": [],
    "score": "points_sum",
    "log_format": "adif",
    "columns": ["nr", "utc", "band", "mode", "khz", "call", "rst_s", "rst_r", "ex_r",
                "land", "name"],
}

_Base = make_contest_class(RULES)


class FreeLog(_Base):
    """Kein Contest: jedes QSO zählt einfach als QSO."""

    free = True
    exchange_kind = "remark"
    exchange_label = tr("Bemerkung")

    def __init__(self, cty, station) -> None:
        super().__init__(cty, station)
        self.uses_serial = False

    def sent_kind(self):
        return None

    def expected_kind(self, lk=None):
        return None

    def sent_exchange(self, serial: int) -> str:
        return ""

    def default_rcvd_exchange(self, lk=None, call: str = "") -> str:
        return ""

    def validate_exchange(self, exch: str, lk=None):
        return None

    def qso_points(self, q: Qso, lk) -> int:
        return 0

    def qso_mults(self, q: Qso, lk) -> list:
        return []

    def notes(self, q: Qso, lk) -> list[str]:
        return []

    def needs_country(self) -> bool:
        return False

    def dupe_key(self, q: Qso) -> tuple:
        # nie doppelt: dasselbe Rufzeichen darf beliebig oft ins Log
        return ("#free", q.id if q.id is not None else id(q))


def worked_text(history: list[tuple[str, str, str]]) -> str:
    """„Schon gearbeitet: 2× – zuletzt 03.11.2026 40 m SSB“ (history: (Zeit, Band, Mode))."""
    from ..bands import band_label
    if not history:
        return tr("Noch nie gearbeitet")
    t, band, mode = max(history)
    day = f"{t[8:10]}.{t[5:7]}.{t[0:4]}" if len(t) >= 10 else t
    return tr("Schon gearbeitet: {n}× – zuletzt {day} {band} {mode}", n=len(history), day=day,
              band=band_label(band), mode=mode)
