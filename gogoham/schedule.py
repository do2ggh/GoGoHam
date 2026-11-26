"""Contest-Termine (Countdown) und Betriebszeit (z. B. WPX: Single-OP max. 36 h)."""

from __future__ import annotations

from .i18n import tr

from datetime import date, datetime, timedelta


def last_full_weekend(year: int, month: int) -> date:
    """Samstag des letzten Wochenendes, an dem Samstag UND Sonntag im Monat liegen."""
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    while d.weekday() != 6:          # letzter Sonntag
        d -= timedelta(days=1)
    return d - timedelta(days=1)


def full_weekends(year: int, month: int) -> list[date]:
    """Samstage aller vollen Wochenenden (Samstag UND Sonntag im Monat)."""
    out = []
    d = date(year, month, 1)
    while d.month == month:
        if d.weekday() == 5 and (d + timedelta(days=1)).month == month:
            out.append(d)
        d += timedelta(days=1)
    return out


def saturdays(year: int, month: int, weekday: int = 5) -> list[date]:
    """Alle Samstage (bzw. andere Wochentage, 6 = Sonntag) eines Monats."""
    d = date(year, month, 1)
    out = []
    while d.month == month:
        if d.weekday() == weekday:
            out.append(d)
        d += timedelta(days=1)
    return out


def easter_sunday(year: int) -> date:
    """Ostersonntag (gregorianisch, Gauß/Meeus)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month, day = divmod(h + ll - 7 * m + 114, 31)
    return date(year, month, day + 1)


def contest_saturday(rule: dict, year: int, month: int | None = None) -> date:
    """Bezugs-Samstag eines Contests im Jahr.

    rule["weekend"]:
      "last_full" (Standard) – letztes volles Wochenende im Monat (CQ WW, WPX …)
      "full"     – n-tes volles Wochenende, rule["nth"] = 1, 2, 3 … oder -1 (letztes)
      "saturday" – n-ter Samstag im Monat (z. B. EU HF: 1. Samstag im August); mit
                   rule["skip_day"] zählt ein Samstag an diesem Tag nicht (Schwaben: nie am
                   1. Januar, Format 15)
      "sunday"   – n-ter Sonntag im Monat (DARC 10 m: 2. Sonntag im Januar)
      "date"     – fester Tag, rule["day"] (Weihnachtswettbewerb: 26. Dezember)
      "easter"   – Ostersonntag + rule["offset"] Tage (Ostercontest: Ostermontag = 1)
      "weekday"  – n-ter Wochentag rule["weekday"] (0 = Montag … 6 = Sonntag) im Monat
                   (Format 9, DARC FT4: 2. Dienstag)
    Bei „sunday“, „date“, „easter“ und „weekday“ ist es kein Samstag, sondern der
    Contest-Tag selbst. ``month`` wählt bei mehreren Monaten (rule["months"]) einen davon.
    """
    kind = rule.get("weekend", "last_full")
    if kind == "easter":
        return easter_sunday(year) + timedelta(days=int(rule.get("offset", 0)))
    if month is None:
        month = months(rule)[0]
    if kind == "date":
        return date(year, month, int(rule["day"]))
    if kind == "last_full":
        return last_full_weekend(year, month)
    if kind == "sunday":
        days = saturdays(year, month, weekday=6)
    elif kind == "weekday":
        days = saturdays(year, month, weekday=int(rule["weekday"]))
    else:
        days = full_weekends(year, month) if kind == "full" else saturdays(year, month)
        if kind in ("full", "saturday") and rule.get("skip_day"):
            # „nie am 1. Januar“: ein Wochenende, dessen Samstag dieser Tag ist, zählt nicht
            days = [d for d in days if d.day != int(rule["skip_day"])]
    n = int(rule.get("nth", 1))
    return days[n - 1] if n > 0 else days[n]


def months(rule: dict) -> list[int]:
    """Monate eines Termins: rule["months"] (mehrmals im Jahr, Format 9) oder rule["month"]."""
    ms = rule.get("months")
    return sorted(int(m) for m in ms) if ms else [int(rule["month"])]


def period(rule: dict, year: int, month: int | None = None) -> tuple[datetime, datetime]:
    """rule = {"month": 10, "start_hour": 0, "hours": 48} (letztes volles Wochenende),
    dazu wahlweise "weekend"/"nth" (siehe contest_saturday) und "start_day":
    Abstand des Beginns zum Samstag in Tagen (-1 = Freitag, wie beim CQ 160).
    Ohne ``month`` der erste Termin im Jahr."""
    sat = contest_saturday(rule, year, month) + timedelta(days=int(rule.get("start_day", 0)))
    start = datetime(sat.year, sat.month, sat.day, rule.get("start_hour", 0),
                     rule.get("start_minute", 0))
    return start, start + timedelta(hours=rule["hours"], minutes=rule.get("minutes", 0))


def periods(rule: dict, year: int) -> list[tuple[datetime, datetime]]:
    """Alle Termine eines Jahres (meist nur einer). Format 15: rule["also"] = weitere Termine
    mit eigener Regel (HSC: letzter Sonntag im Februar und erster Sonntag im November)."""
    if rule.get("weekend") == "easter":
        out = [period(rule, year)]
    else:
        out = [period(rule, year, m) for m in months(rule)]
    for extra in rule.get("also") or ():
        out += periods(extra, year)
    return sorted(out)


def upcoming(rule: dict, now: datetime, count: int = 1) -> list[tuple[datetime, datetime]]:
    """Laufender bzw. die nächsten ``count`` Termine (UTC, ohne Zeitzone)."""
    out: list[tuple[datetime, datetime]] = []
    y = now.year - 1
    while len(out) < count and y <= now.year + count + 1:
        out += [p for p in periods(rule, y) if p[1] > now]
        y += 1
    return out[:count]


def next_period(rule: dict, now: datetime) -> tuple[datetime, datetime]:
    """Laufender oder nächster Termin (UTC, ohne Zeitzone)."""
    return upcoming(rule, now, 1)[0]


def period_of(rule: dict, when: datetime) -> tuple[datetime, datetime] | None:
    """Der Termin, in dem ``when`` liegt (z. B. ein Log aus einem früheren Contest)."""
    for y in (when.year - 1, when.year):
        for s, e in periods(rule, y):
            if s <= when <= e:
                return s, e
    return None


def _fmt(td: timedelta) -> str:
    secs = max(0, int(td.total_seconds()))
    d, rest = divmod(secs, 86400)
    h, rest = divmod(rest, 3600)
    m = rest // 60
    if d:
        return tr("{d} T {h:02d}:{m:02d} h", d=d, h=h, m=m)       # T = Tage
    return f"{h:02d}:{m:02d} h"


def countdown(rule: dict | None, now: datetime) -> str:
    if not rule:
        return ""
    s, e = next_period(rule, now)
    if now < s:
        return tr("Beginn in {fmt}", fmt=_fmt(s - now))
    return tr("läuft · noch {fmt}", fmt=_fmt(e - now))


def operating_time(times: list[datetime], start: datetime, end: datetime, now: datetime,
                   min_off: timedelta = timedelta(minutes=60)) -> timedelta:
    """Betriebszeit nach WPX-Regel: Pausen zählen nur, wenn sie ≥ 60 Minuten sind.

    Gezählt wird ab Contest-Beginn bis jetzt (bzw. Ende); Zeit vor dem ersten QSO
    und nach dem letzten QSO zählt als Pause, wenn sie lang genug ist.
    """
    stop = min(now, end)
    if stop <= start:
        return timedelta(0)
    ts = sorted(t for t in times if start <= t <= stop)
    if not ts:
        return timedelta(0)
    points = [start] + ts + [stop]
    off = timedelta(0)
    for a, b in zip(points, points[1:]):
        if b - a >= min_off:
            off += b - a
    return (stop - start) - off
