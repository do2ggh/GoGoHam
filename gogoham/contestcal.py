"""Contest-Kalender (ab 0.8.21): nächste Termine aller Contests, die GoGoHam loggen kann.

Die Termine werden offline aus den Regel-Dateien berechnet („schedule“, siehe schedule.py) –
keine Internetverbindung nötig. Veranstalter verschieben Termine selten, aber es kommt vor:
im Zweifel die Ausschreibung prüfen (rules_url).

Dazu: Filter CW/SSB/Digi/UKW, Erinnerungstext für den Programmstart und Export als
iCalendar-Datei (.ics, RFC 5545) für Thunderbird, Google- oder Handy-Kalender.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from . import schedule
from .i18n import tr

HF_BANDS = {"160", "80", "60", "40", "30", "20", "17", "15", "12", "10"}
KINDS = ("CW", "SSB", "RTTY", "DIGI", "UKW")          # Filter-Schlüssel
REMIND_DAYS = 7                               # Erinnerung: Beginn innerhalb dieser Tage


@dataclass
class Entry:
    cid: str
    name: str
    start: datetime                           # UTC, ohne Zeitzone (wie schedule)
    end: datetime
    kinds: frozenset                          # Teilmenge von KINDS
    rules_url: str = ""

    def running(self, now: datetime) -> bool:
        return self.start <= now < self.end

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


def kinds_of(cls) -> frozenset:
    """Betriebsarten/Bereich eines Contests für den Filter."""
    out = set()
    modes = set(getattr(cls, "modes", ()) or ())
    if "CW" in modes:
        out.add("CW")
    if "PH" in modes:
        out.add("SSB")
    if "RY" in modes:
        out.add("RTTY")                       # 0.10.7
    if "DG" in modes:
        out.add("DIGI")
    if any(str(b) not in HF_BANDS for b in (getattr(cls, "bands", ()) or ())):
        out.add("UKW")
    return frozenset(out)


def entries(contests: dict, now: datetime, count: int = 1) -> list[Entry]:
    """Laufende und kommende Termine, nach Beginn sortiert. ``count`` = Termine je Contest
    (1 = nur der nächste; 2 = auch der im Jahr darauf, für den .ics-Export)."""
    out = []
    for cid, cls in contests.items():
        rules = getattr(cls, "rules", None) or {}
        rule = rules.get("schedule")
        if not rule:
            continue
        try:
            # count > 1 (.ics): je weiteres Jahr alle Termine (FT4: viermal im Jahr)
            n = 1 + (count - 1) * len(schedule.periods(rule, now.year))
            periods = schedule.upcoming(rule, now, n)
        except (KeyError, ValueError, IndexError, TypeError):
            continue                          # fehlerhafte Regel: lieber weglassen
        for s, e in periods:
            out.append(Entry(cid, cls.name, s, e, kinds_of(cls), rules.get("rules_url", "")))
    out.sort(key=lambda x: (x.start, x.name))
    return out


def filtered(items: list[Entry], kinds) -> list[Entry]:
    """Nur Contests mit mindestens einer der gewählten Arten. Nichts gewählt = nichts
    (Nutzerwunsch 0.8.21.1; vorher hieß leer „alle“)."""
    return [x for x in items if x.kinds & set(kinds or ())]


def status(x: Entry, now: datetime) -> str:
    """„läuft · noch 05:12 h“ / „in 3 Tagen“ / „morgen“ / „in 06:30 h“."""
    if x.running(now):
        return tr("läuft · noch {fmt}", fmt=schedule._fmt(x.end - now))
    delta = x.start - now
    if delta < timedelta(hours=24):
        return tr("in {fmt}", fmt=schedule._fmt(delta))
    days = (x.start.date() - now.date()).days
    if days == 1:
        return tr("morgen")
    return tr("in {n} Tagen", n=days)


def reminder(items: list[Entry], now: datetime, days: int = REMIND_DAYS) -> str:
    """Text für die Statuszeile beim Start: laufende Contests und Beginn in den nächsten
    ``days`` Tagen. Leer, wenn nichts ansteht."""
    soon = [x for x in items if x.running(now) or x.start - now <= timedelta(days=days)]
    if not soon:
        return ""
    parts = [f"{x.name} ({status(x, now)})" for x in soon[:3]]
    if len(soon) > 3:
        parts.append(tr("{n} weitere", n=len(soon) - 3))
    return tr("Contest-Kalender: {list}", list=" · ".join(parts))


# ------------------------------------------------------------------ iCalendar (.ics)
def _ics_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\n", "\\n"))


def _fold(line: str) -> list[str]:
    """Zeilen über 75 Byte falten (RFC 5545, 3.1) – ohne UTF-8-Zeichen zu zerschneiden."""
    out, cur = [], ""
    for ch in line:
        limit = 75 if not out else 74          # Folgezeilen beginnen mit einem Leerzeichen
        if len((cur + ch).encode("utf-8")) > limit:
            out.append(cur)
            cur = ch
        else:
            cur += ch
    out.append(cur)
    return [out[0]] + [" " + x for x in out[1:]]


ALARM_CHOICES = (0, 15, 30, 60, 120, 1440)     # Erinnerung vorher in Minuten (0 = keine)
ALARM_DEFAULT = 60


def _alarm(name: str, minutes: int) -> list[str]:
    if not minutes:
        return []
    return ["BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:" + _ics_escape(name),
            f"TRIGGER:-PT{int(minutes)}M", "END:VALARM"]


def qr_event(x: Entry, alarm: int = ALARM_DEFAULT) -> str:
    """Ein Termin als Text für einen QR-Code (0.10.15) – die Handy-Kamera erkennt „BEGIN:VEVENT“
    und bietet „Zum Kalender hinzufügen“ an. Bewusst kurz (je kürzer, desto leichter zu scannen);
    Zeiten in UTC, das Handy rechnet in seine Ortszeit um."""
    fmt = "%Y%m%dT%H%M%SZ"
    lines = ["BEGIN:VEVENT", "SUMMARY:" + _ics_escape(x.name),
             "DTSTART:" + x.start.strftime(fmt), "DTEND:" + x.end.strftime(fmt)]
    if x.rules_url:
        lines.append("URL:" + x.rules_url)
    lines += _alarm(x.name, alarm)
    lines.append("END:VEVENT")
    return "\r\n".join(lines)


def to_ics(items: list[Entry], stamp: datetime, call: str = "", alarm: int = 0) -> str:
    """Termine als iCalendar-Text (Zeiten in UTC). UID je Contest und Jahr – erneutes
    Importieren aktualisiert die Termine, statt sie doppelt anzulegen."""
    fmt = "%Y%m%dT%H%M%SZ"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//GoGoHam//Contest-Kalender//DE",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:" + _ics_escape(tr("Contests (GoGoHam)"))]
    for x in items:
        desc = tr("Berechnet aus den GoGoHam-Regeln – im Zweifel die Ausschreibung prüfen.")
        if x.rules_url:
            desc += "\n" + x.rules_url
        lines += ["BEGIN:VEVENT",
                  f"UID:{x.cid}-{x.start:%Y}@gogoham",
                  "DTSTAMP:" + stamp.strftime(fmt),
                  "DTSTART:" + x.start.strftime(fmt),
                  "DTEND:" + x.end.strftime(fmt),
                  "SUMMARY:" + _ics_escape(x.name),
                  "DESCRIPTION:" + _ics_escape(desc),
                  "CATEGORIES:" + ",".join(sorted(x.kinds))]
        if x.rules_url:
            lines.append("URL:" + x.rules_url)
        lines.append("TRANSP:TRANSPARENT")                 # blockiert keine Termine
        lines += _alarm(x.name, alarm)                      # 0.10.15: Erinnerung wie eingestellt
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    out = []
    for ln in lines:
        out += _fold(ln)
    return "\r\n".join(out) + "\r\n"
