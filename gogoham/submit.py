"""Wohin mit dem Log? (ab 0.10.41) – Einsendeweg aus dem Block „submit“ der Regel-Datei.

Aufbau (alles freiwillig, mindestens „email“ oder „upload_url“ oder „note“):

    "submit": {
        "email": "logs@example.org"            – oder je Betriebsart {"CW": …, "PH": …}
        "cc": "kopie@example.org"              – verlangte Kopie (Baltic Contest)
        "upload_url": "https://…",              – Upload-Seite / Log-Robot
        "subject": "{call}",                    – vorgeschriebener Betreff ({call}, {contest},
                                                  {category}); fehlt = „<Contest> – <Rufzeichen>“
        "deadline": {"days": 5}                 – Frist nach Contest-Ende: „days“ (dazu evtl.
                                                  „time“: "23:59" UTC) oder „hours“,
                    {"day_of_month": 15, "months": 1}   oder fester Tag im Folgemonat (months 0 = im
                                                  Contest-Monat, 31 = Monatsende),
                    {"month": 5, "day": 13}     oder fester Tag im Jahr (23:59:59 UTC)
        "note": {"de": "…", "en": "…"},         – weitere Hinweise (Sprache, sonst Englisch)
        "checked": "2026-11"                    – wann gegen die Ausschreibung geprüft
    }

Die Dateien behalten ihre Formatnummer: ältere GoGoHam-Versionen übergehen den Block einfach.
Eine Mail kann aus GoGoHam heraus keinen Anhang mitbringen (das kann ``mailto:`` nicht, und
jedes E-Mail-Programm macht es anders) – deshalb öffnet GoGoHam zusätzlich den Ordner mit der
markierten Log-Datei zum Hineinziehen.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from calendar import monthrange
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from . import i18n
from .i18n import tr

KEYS = {"email", "cc", "upload_url", "subject", "deadline", "note", "checked"}
MODE_KEYS = {"CW", "PH", "RY", "DG"}
PLACEHOLDERS = {"call", "contest", "category"}
_MAIL = re.compile(r"[^@\s<>\"]+@[^@\s<>\"]+\.[A-Za-z]{2,}")


def validate(sub) -> list[str]:
    """Fehler im Block „submit“ (leer = in Ordnung)."""
    if not isinstance(sub, dict):
        return [tr("„submit“ muss ein Objekt { … } sein")]
    errs = []
    for k in sub:
        if k not in KEYS:
            errs.append(tr("„submit“: Angabe „{k}“ unbekannt", k=k))
    mail = sub.get("email")
    if mail is not None:
        items = mail.items() if isinstance(mail, dict) else [("", mail)]
        for mode, addr in items:
            if mode and mode not in MODE_KEYS:
                errs.append(tr("„submit“ → „email“: Betriebsart „{m}“ unbekannt", m=mode))
            if not isinstance(addr, str) or not _MAIL.fullmatch(addr):
                errs.append(tr("„submit“ → „email“: „{a}“ ist keine E-Mail-Adresse", a=addr))
    cc = sub.get("cc")
    if cc is not None and not (isinstance(cc, str) and _MAIL.fullmatch(cc)):
        errs.append(tr("„submit“ → „cc“: „{a}“ ist keine E-Mail-Adresse", a=cc))
    url = sub.get("upload_url")
    if url is not None and not (isinstance(url, str) and re.match(r"https?://\S+$", url)):
        errs.append(tr("„submit“ → „upload_url“: Internet-Adresse (https://…) erwartet"))
    subj = sub.get("subject")
    if subj is not None:
        names = set(re.findall(r"{(\w*)}", subj)) if isinstance(subj, str) else {"?"}
        if not isinstance(subj, str) or not subj.strip() or names - PLACEHOLDERS:
            errs.append(tr("„submit“ → „subject“: Text erwartet, Platzhalter nur {call}, "
                           "{contest}, {category}"))
    dl = sub.get("deadline")
    if dl is not None and not _deadline_ok(dl):
        errs.append(tr("„submit“ → „deadline“: {\"days\": 5, \"time\": \"23:59\"}, {\"hours\": 72} oder "
                       "{\"day_of_month\": 15, \"months\": 1} oder {\"month\": 5, \"day\": 13} erwartet"))
    note = sub.get("note")
    if note is not None and not (isinstance(note, dict) and note and all(
            isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in note.items())):
        errs.append(tr("„submit“ → „note“: {\"de\": \"…\", \"en\": \"…\"} erwartet"))
    if not any(sub.get(k) for k in ("email", "upload_url", "note")):
        errs.append(tr("„submit“ braucht „email“, „upload_url“ oder „note“"))
    return errs


def _pos_int(v, top: int) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= top


def _hhmm(v) -> tuple[int, int] | None:
    m = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", v) if isinstance(v, str) else None
    return (int(m[1]), int(m[2])) if m else None


def _deadline_ok(dl) -> bool:
    if not isinstance(dl, dict) or len(dl) == 0:
        return False
    if set(dl) <= {"days", "time"} and "days" in dl:
        return _pos_int(dl["days"], 366) and ("time" not in dl or _hhmm(dl["time"]) is not None)
    if set(dl) == {"hours"}:
        return _pos_int(dl["hours"], 24 * 366)
    if set(dl) <= {"month", "day", "time"} and {"month", "day"} <= set(dl):   # fester Tag im Jahr
        if "time" in dl and _hhmm(dl["time"]) is None:
            return False
        return _pos_int(dl["month"], 12) and _pos_int(dl["day"], monthrange(2024, dl["month"])[1]
                                                     if _pos_int(dl["month"], 12) else 31)
    if set(dl) <= {"day_of_month", "months"} and "day_of_month" in dl:
        months = dl.get("months", 1)                # 0 = Ende des Contest-Monats (AGCW HTP)
        return _pos_int(dl["day_of_month"], 31) and (months == 0 or _pos_int(months, 12))
    return False


# --- Auswerten ------------------------------------------------------------------------

def current_rules(contest) -> list[dict]:
    """Regeln des Logs und – falls anders – die aktuellen Regeln desselben Contests. Ein Log merkt
    sich die Regeln vom Anlegen; Einsendeweg und Deckblatt sollen trotzdem vom aktuellen Stand
    kommen (Log von vor 0.10.41 hatte noch keinen Einsendeweg)."""
    out = [getattr(contest, "rules", None) or {}]
    try:
        from .contests import CONTESTS
        cur = CONTESTS.get(getattr(contest, "id", "") or "")
    except ImportError:                                  # pragma: no cover
        cur = None
    if cur is not None and cur is not contest:
        out.insert(0, getattr(cur, "rules", None) or {})
    return out


def block(contest) -> dict:
    for rules in current_rules(contest):
        sub = rules.get("submit")
        if isinstance(sub, dict) and not validate(sub):
            return sub
    return {}


def deadline(sub: dict, end: datetime | None) -> datetime | None:
    """Einsendeschluss (UTC) aus dem Contest-Ende; None = unbekannt."""
    dl = sub.get("deadline")
    if not dl or end is None:
        return None
    if "days" in dl:
        d = end + timedelta(days=dl["days"])
        if "time" in dl:                        # „15 Tage, 00:00 UTC“: Tag nach den Tagen, feste Zeit
            h, mi = _hhmm(dl["time"])
            d = d.replace(hour=h, minute=mi, second=0)
        return d
    if "hours" in dl:
        return end + timedelta(hours=dl["hours"])
    if "month" in dl:                           # fester Tag: der erste nach dem Contest-Ende
        for y in (end.year, end.year + 1):
            h, mi = _hhmm(dl["time"]) if "time" in dl else (23, 59)
            d = datetime(y, dl["month"], min(dl["day"], monthrange(y, dl["month"])[1]), h, mi,
                         0 if "time" in dl else 59)
            if d >= end:
                return d
    y, m = divmod(end.month - 1 + dl.get("months", 1), 12)
    y, m = end.year + y, m + 1
    day = min(dl["day_of_month"], monthrange(y, m)[1])
    return datetime(y, m, day, 23, 59, 59)


def emails(sub: dict, modes) -> list[str]:
    """Empfänger für die Betriebsarten im Log (je Betriebsart eigene Adresse möglich)."""
    mail = sub.get("email")
    if not mail:
        return []
    if isinstance(mail, str):
        return [mail]
    out = []
    for m in sorted(modes) or sorted(mail):
        a = mail.get(m)
        if a and a not in out:
            out.append(a)
    return out or list(dict.fromkeys(mail.values()))


def subject(sub: dict, call: str, contest_name: str, category: str = "") -> str:
    tpl = sub.get("subject")
    if not tpl:
        return f"{contest_name} – {call}" if call else contest_name
    return tpl.format(call=call, contest=contest_name, category=category).strip()


def note(sub: dict) -> str:
    n = sub.get("note") or {}
    lang = i18n.language()
    return n.get(lang) or n.get("en") or n.get("de") or ""


def mailto(addresses: list[str], subj: str, cc: str = "") -> str:
    return "mailto:" + ",".join(addresses) + "?subject=" + quote(subj) + \
        ("&cc=" + quote(cc, safe="@") if cc else "")


# --- Ordner mit markierter Datei ------------------------------------------------------------

def show_in_folder(paths: list[str], run=subprocess.run, which=shutil.which) -> bool:
    """Dateimanager öffnen und die Datei(en) markieren (freedesktop „FileManager1“, das
    können Dolphin, Nautilus, Nemo, Thunar, Caja, PCManFM-Qt …). False = nicht geklappt –
    dann öffnet der Aufrufer nur den Ordner."""
    uris = [Path(p).resolve().as_uri() for p in paths]
    if which("gdbus"):
        cmd = ["gdbus", "call", "--session", "--dest", "org.freedesktop.FileManager1",
               "--object-path", "/org/freedesktop/FileManager1",
               "--method", "org.freedesktop.FileManager1.ShowItems",
               "[" + ",".join(f"'{u}'" for u in uris) + "]", ""]
    elif which("dbus-send"):
        cmd = ["dbus-send", "--session", "--print-reply", "--dest=org.freedesktop.FileManager1",
               "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1.ShowItems",
               "array:string:" + ",".join(uris), "string:"]
    else:
        return False
    try:
        return run(cmd, capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
