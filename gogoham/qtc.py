"""QTC im WAE DX Contest (ab 0.8.5): Stationen außerhalb Europas melden europäischen
Stationen frühere Verbindungen (Uhrzeit, Rufzeichen, Nummer). Jedes QTC zählt 1 Punkt.

Empfangen (eigene Station in Europa, ab 0.8.5) und geben (eigene Station außerhalb
Europas, ab 0.9.4). Ein gegebenes QTC erkennt man an `receiver` (wer es bekommen hat);
`sender` ist dann das eigene Rufzeichen.

Hier stehen nur die Rechen- und Prüfregeln – ohne Qt, damit sie sich testen lassen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .i18n import tr

MAX_PER_STATION = 10        # höchstens 10 QTCs zwischen zwei Stationen (alle Bänder)

_CALL = re.compile(r"[A-Z0-9]+(/[A-Z0-9]+)*")


@dataclass
class Qtc:
    """Ein empfangenes QTC – eine gemeldete Verbindung der Gegenstation."""
    id: int | None = None
    time: str = ""        # UTC, wann das QTC empfangen wurde ("YYYY-MM-DD HH:MM:SS")
    band: str = ""
    mode: str = ""
    freq: int = 0         # Hz
    sender: str = ""      # wer das QTC gegeben hat (Station außerhalb Europas)
    series: int = 0       # Serien-Nummer, wie angesagt („QTC 3/5“ -> 3)
    total: int = 0        # angesagte Anzahl der Serie („QTC 3/5“ -> 5)
    qso_time: str = ""    # „1307“
    qso_call: str = ""    # „DL1ABC“
    qso_nr: str = ""      # „042“
    receiver: str = ""    # nur bei gegebenen QTCs: wer es bekommen hat (ab 0.9.4)
    qso_id: int = 0       # nur bei gegebenen QTCs: das gemeldete QSO im eigenen Log
    uid: str = ""         # eindeutige Kennung (Stationslog, ab 0.10)

    @property
    def given(self) -> bool:
        return bool(self.receiver)


def parse_series(text: str) -> tuple[int, int] | None:
    """„3/5“ -> (3, 5); „3“ -> (3, 0) (Anzahl ergibt sich aus den Zeilen)."""
    t = (text or "").strip().replace(" ", "")
    m = re.fullmatch(r"(\d{1,4})(?:/(\d{1,2}))?", t)
    if not m:
        return None
    n, total = int(m.group(1)), int(m.group(2) or 0)
    if n < 1 or total > MAX_PER_STATION:
        return None
    return n, total


def parse_line(text: str) -> tuple[tuple[str, str, str] | None, str]:
    """Eine QTC-Zeile „1307 DL1ABC 042“ -> ((Zeit, Rufzeichen, Nummer), Fehler).

    Die Uhrzeit darf auch „13:07“ oder dreistellig „907“ sein. Ist die Zeile in
    Ordnung, ist der Fehler leer."""
    parts = (text or "").strip().upper().replace(":", "").split()
    if not parts:
        return None, ""
    if len(parts) != 3:
        return None, tr("Bitte Uhrzeit, Rufzeichen und Nummer eingeben, z. B. „1307 DL1ABC 042“")
    t, call, nr = parts
    if not re.fullmatch(r"\d{3,4}", t):
        return None, tr("Uhrzeit „{t}“: bitte vierstellig, z. B. 1307", t=t)
    t = t.zfill(4)
    if int(t[:2]) > 23 or int(t[2:]) > 59:
        return None, tr("Uhrzeit „{t}“ gibt es nicht", t=t)
    if "?" in call:
        return None, tr("Rufzeichen unvollständig – bitte nachfragen")
    if not _CALL.fullmatch(call) or not re.search(r"\d", call) or not re.search(r"[A-Z]", call):
        return None, tr("„{call}“ ist kein Rufzeichen", call=call)
    if not nr.isdigit():
        return None, tr("Nummer „{nr}“: bitte nur Ziffern", nr=nr)
    return (t, call, nr), ""


def received_from(qtcs: list[Qtc], sender: str) -> int:
    """Wie viele QTCs schon von dieser Station empfangen wurden (alle Bänder)."""
    s = (sender or "").upper()
    return sum(1 for q in qtcs if not q.given and q.sender.upper() == s)


def remaining(qtcs: list[Qtc], sender: str, limit: int = MAX_PER_STATION,
              both: bool = False) -> int:
    """Wie viele QTCs von dieser Station noch gehen. ``both`` (WAE RTTY): gegebene und
    empfangene zusammen höchstens ``limit`` je Stationspaar."""
    used = received_from(qtcs, sender) + (sent_to(qtcs, sender) if both else 0)
    return max(0, limit - used)


def next_series_hint(qtcs: list[Qtc], sender: str) -> int:
    """Höchste bisher notierte Serien-Nummer dieser Station + 1 (nur als Vorschlag –
    die Nummer vergibt die Gegenstation selbst)."""
    s = (sender or "").upper()
    nums = [q.series for q in qtcs if not q.given and q.sender.upper() == s]
    return max(nums) + 1 if nums else 0


# ------------------------------------------------------------ QTCs geben (ab 0.9.4)
def _base(call: str) -> str:
    """Kern des Rufzeichens: „OE/DL1ABC/P“ -> „DL1ABC“."""
    return max((call or "").upper().split("/"), key=len)


def sent_to(qtcs: list[Qtc], receiver: str) -> int:
    """Wie viele QTCs schon an diese Station gegeben wurden (alle Bänder)."""
    r = (receiver or "").upper()
    return sum(1 for q in qtcs if q.given and q.receiver.upper() == r)


def give_remaining(qtcs: list[Qtc], receiver: str, limit: int = MAX_PER_STATION,
                   both: bool = False) -> int:
    used = sent_to(qtcs, receiver) + (received_from(qtcs, receiver) if both else 0)
    return max(0, limit - used)


def next_own_series(qtcs: list[Qtc]) -> int:
    """Nummer der nächsten eigenen Serie – die eigenen Serien werden fortlaufend gezählt,
    egal an wen („QTC 3/7“ = die 3. Serie dieser Station)."""
    nums = [q.series for q in qtcs if q.given]
    return max(nums) + 1 if nums else 1


def qso_nr(q) -> str:
    """Nummer, die die Gegenstation im QSO gegeben hat – leer, wenn es keine brauchbare gibt
    („000“ = keine Nummer bekommen; so ein QSO lässt sich nicht als QTC melden)."""
    nr = (q.exch_r or "").strip().split()
    nr = nr[-1] if nr else ""
    return nr if nr.isdigit() and int(nr) > 0 else ""


def give_candidates(qsos: list, qtcs: list[Qtc], receiver: str, dupe_key=None) -> list:
    """QSOs, die sich noch an diese Station melden lassen – die ältesten zuerst.

    Nicht dabei: QSOs mit dem Empfänger selbst (darf nicht zurückgemeldet werden), schon
    gemeldete QSOs (jedes QSO nur einmal), QSOs ohne Nummer, doppelte QSOs (Dupes)."""
    r = _base(receiver)
    done_ids = {q.qso_id for q in qtcs if q.given and q.qso_id}
    done = {(q.qso_call.upper(), q.qso_nr.lstrip("0"), q.qso_time) for q in qtcs if q.given}
    seen: set = set()
    out = []
    for q in sorted(qsos, key=lambda x: (x.time, x.id or 0)):
        nr = qso_nr(q)
        if dupe_key is not None:
            k = dupe_key(q)
            if k in seen:
                continue
            seen.add(k)
        if not nr or _base(q.call) == r:
            continue
        t = qso_hhmm(q)
        if (q.id and q.id in done_ids) or (q.call.upper(), nr.lstrip("0"), t) in done:
            continue
        out.append(q)
    return out


def qso_hhmm(q) -> str:
    """„2026-08-08 13:07:45“ -> „1307“."""
    _d, _s, tm = (q.time or "").partition(" ")
    return tm.replace(":", "")[:4]


def give_line(q) -> tuple[str, str, str]:
    """Die QTC-Zeile zu einem eigenen QSO: (Uhrzeit, Rufzeichen, Nummer)."""
    return qso_hhmm(q), q.call.upper(), qso_nr(q)


def cw_header(series: int, total: int) -> str:
    return f"QTC {series}/{total}"


def cw_line(entry: tuple[str, str, str]) -> str:
    return " ".join(entry)


def receiver_problem(contest, receiver: str, mycall: str, qtcs: list[Qtc]) -> str:
    """Warum an diese Station keine QTCs gehen (leer = es geht)."""
    r = (receiver or "").strip().upper()
    if not r:
        return tr("Rufzeichen der Station eingeben, die die QTCs bekommt")
    if mycall and _base(r) == _base(mycall):
        return tr("Das ist dein eigenes Rufzeichen")
    lk = contest.lookup(r)
    both = contest.qtc_both_ways()
    if both:
        p = contest.qtc_other_continent_problem(lk)
        if p:
            return p
    elif lk is not None and (lk.maritime or lk.cont != "EU"):
        return tr("QTCs gehen nur an Stationen in Europa")
    limit = int((contest.qtc or {}).get("max_per_station", MAX_PER_STATION))
    if give_remaining(qtcs, r, limit, both) == 0:
        return tr("{receiver} hat schon {limit} QTCs von dir – mehr sind nicht erlaubt",
                  receiver=r, limit=limit)
    return ""


def line_problem(entry: tuple[str, str, str], sender: str, mycall: str, qtcs: list[Qtc],
                 earlier: list[tuple[str, str, str]] = ()) -> str:
    """Grund, warum dieses QTC nicht zählt (leer = in Ordnung).

    earlier: die Zeilen davor in derselben Serie (für doppelte Einträge)."""
    t, call, nr = entry
    base = lambda c: max(c.upper().split("/"), key=len)   # noqa: E731
    if mycall and base(call) == base(mycall):
        return tr("Eigenes Rufzeichen – die Gegenstation darf dir dein eigenes QSO nicht melden")
    if sender and base(call) == base(sender):
        return tr("Das ist die Gegenstation selbst")
    s = sender.upper()
    for q in qtcs:
        if q.sender.upper() == s and q.qso_call.upper() == call and q.qso_nr.lstrip("0") == nr.lstrip("0"):
            return tr("Diese Verbindung hat {sender} schon gemeldet", sender=sender)
    for e in earlier:
        if e[1] == call and e[2].lstrip("0") == nr.lstrip("0"):
            return tr("Steht in dieser Serie schon")
    return ""


def cabrillo_line(q: Qtc, mycall: str, freq_text: str, mode: str) -> str:
    """QTC-Zeile im Cabrillo-Log, wie der DARC sie verlangt:
    QTC: QRG MODE DATUM ZEIT EMPFÄNGER SERIE/ANZAHL GEBER QSO-ZEIT QSO-CALL QSO-NR
    Empfangen: Empfänger = man selbst. Gegeben: Geber = man selbst."""
    date, _, tm = q.time.partition(" ")
    hhmm = tm.replace(":", "")[:4]
    grp = f"{q.series}/{q.total}"
    return (f"QTC: {freq_text:>5} {mode} {date} {hhmm} {(q.receiver or mycall):<13} {grp:<5} "
            f"{q.sender:<13} {q.qso_time} {q.qso_call:<13} {q.qso_nr}").rstrip()
