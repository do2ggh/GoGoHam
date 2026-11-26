"""Tägliches Update beim Start (ab 0.8.10).

Einmal am Tag sieht GoGoHam beim Start nach, ob es Neues gibt:

* Contest-Regeln (GitHub, nur geänderte Dateien)
* Länderdatei cty.dat + cty.csv (country-files.com)
* MASTER.SCP (supercheckpartial.com)
* DOK-Liste (DARC/VFDB, Sonder-DOKs)
* Flaggen – nur fehlende, höchstens einmal im Monat

Schutz im Contest: Läuft der Contest des geöffneten Logs gerade, bleiben Contest-Regeln
und Länderdatei unverändert (sonst könnten sich Punkte verschieben). MASTER.SCP und
DOK-Liste liefern nur Vorschläge und dürfen auch dann erneuert werden.

Heruntergeladen wird nur, was schon einmal da war (wer MASTER.SCP oder die Flaggen nie
haben wollte, bekommt sie auch nicht ungefragt). cty.dat und MASTER.SCP werden nur
geholt, wenn die Datei auf dem Server neuer ist als die eigene.

Ohne Internet passiert nichts. Alles läuft in einem eigenen Thread; die Oberfläche
liest am Ende nur das Ergebnis aus. Es wird nur gelesen (HTTP GET/HEAD).
"""

from __future__ import annotations

from .i18n import tr

import email.utils
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from . import __version__

FLAGS_EVERY_DAYS = 30


@dataclass
class DailyResult:
    offline: bool = False
    rules: object = None                 # rulesupdate.UpdateResult oder None
    cty: bool = False                    # neue cty.dat gespeichert
    scp: bool = False                    # neue MASTER.SCP gespeichert
    doks: bool = False                   # DOK-Liste neu geladen
    flags: list[str] = field(default_factory=list)   # Codes der fehlenden Flaggen
    map_month: bool = False              # NASA-Kartenbild: neuer Monat → neues Bild laden
    kept: list[str] = field(default_factory=list)    # wegen laufendem Contest ausgelassen
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.offline:
            return tr("Kein Internet – tägliches Update übersprungen, es gilt der bisherige Stand")
        parts = []
        if self.rules is not None and getattr(self.rules, "changed", False):
            parts.append(self.rules.summary())
        if self.cty:
            parts.append(tr("Länderdatei erneuert"))
        if self.scp:
            parts.append(tr("MASTER.SCP erneuert"))
        if self.doks:
            parts.append(tr("DOK-Liste erneuert"))
        if self.flags:
            parts.append(tr("{n} fehlende Flaggen werden geladen", n=len(self.flags)))
        if self.map_month:
            parts.append(tr("NASA-Kartenbild des neuen Monats wird geladen"))
        if self.kept:
            parts.append(tr("Contest läuft – unverändert: {what}", what=", ".join(self.kept)))
        if not parts:
            return tr("Tägliches Update: alles aktuell")
        return tr("Tägliches Update: ") + " · ".join(parts)


def is_due(cfg: dict, today: date | None = None) -> bool:
    """Heute schon nachgesehen? (Häkchen aus = nie)"""
    if not cfg.get("daily_update", True):
        return False
    return cfg.get("daily_update_last", "") != (today or date.today()).isoformat()


def contest_running(schedule_rule: dict | None, now: datetime) -> bool:
    """Läuft der Contest gerade? now = UTC ohne Zeitzone."""
    if not schedule_rule:
        return False
    from .schedule import next_period
    try:
        s, e = next_period(schedule_rule, now)
    except (KeyError, ValueError, IndexError, TypeError):
        return False
    return s <= now < e


def remote_is_newer(url: str, path: Path, timeout: float) -> bool:
    """Ist die Datei auf dem Server neuer als die eigene? Fehlt die eigene: ja.

    Nur eine kurze Nachfrage (HEAD), nichts wird heruntergeladen. Sagt der Server
    nichts zum Datum, wird sicherheitshalber geladen. Kein Internet → OSError.
    """
    if not path.is_file():
        return True
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": f"GoGoHam/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (feste Adresse)
            lm = r.headers.get("Last-Modified")
    except urllib.error.HTTPError:
        return True                      # Server mag kein HEAD – dann eben laden
    if not lm:
        return True
    try:
        remote = email.utils.parsedate_to_datetime(lm).timestamp()
    except (TypeError, ValueError):
        return True
    return remote > path.stat().st_mtime + 60


def _online(timeout: float) -> bool:
    """Kurzer Test, ob GitHub erreichbar ist (ohne Internet sofort aufhören)."""
    from .rulesupdate import BASE_URL
    req = urllib.request.Request(BASE_URL + "index.json", method="HEAD",
                                 headers={"User-Agent": f"GoGoHam/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout):  # noqa: S310
            return True
    except urllib.error.HTTPError:
        return True                      # Server antwortet – Internet ist da
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def run(running: bool, flags_due: bool, timeout: float = 8.0) -> DailyResult:
    """Alle Updates nacheinander. running = Contest des geöffneten Logs läuft gerade."""
    from . import cty, dok, flags, rulesupdate, scp
    res = DailyResult()
    if not _online(min(timeout, 4.0)):
        res.offline = True
        return res

    # Contest-Regeln
    if running:
        res.kept.append(tr("Contest-Regeln"))
    else:
        try:
            res.rules = rulesupdate.check_and_download(timeout=timeout)
            if res.rules.offline:
                res.rules = None
        except Exception as e:  # noqa: BLE001
            res.errors.append(tr("Contest-Regeln: {e}", e=e))

    # Länderdatei – nur wenn schon eine eigene da ist (sonst fragt GoGoHam beim Start)
    p = cty.user_cty_path()
    if running:
        res.kept.append(tr("Länderdatei"))
    elif p.is_file():
        try:
            if remote_is_newer(cty.CTY_URL, p, timeout):
                cty.download(timeout=timeout)
                res.cty = True
        except Exception as e:  # noqa: BLE001
            res.errors.append(tr("Länderdatei: {e}", e=e))

    # MASTER.SCP – nur wenn der Nutzer sie schon einmal geladen hat
    p = scp.user_scp_path()
    if p.is_file():
        try:
            if remote_is_newer(scp.SCP_URL, p, timeout):
                scp.download(timeout=max(timeout, 20))
                res.scp = True
        except Exception as e:  # noqa: BLE001
            res.errors.append(tr("MASTER.SCP: {e}", e=e))

    # DOK-Liste – nur wenn schon einmal geladen, höchstens einmal am Tag
    age = dok.age_days()
    if age is not None and age >= 1:
        try:
            dok.download(timeout=timeout)
            res.doks = True
        except Exception as e:  # noqa: BLE001
            res.errors.append(tr("DOK-Liste: {e}", e=e))

    # Flaggen – nur fehlende, und nur wenn überhaupt Flaggen gewünscht waren
    if flags_due and flags.flags_dir().is_dir() and any(flags.flags_dir().glob("*.png")):
        res.flags = flags.missing_codes()

    # NASA-Kartenbild (ab 0.8.15): jeden Monat das passende Bild – nur, wenn schon geladen
    from . import mapimages
    if mapimages.nasa_update_due():
        if running:
            res.kept.append(tr("Kartenbild"))
        else:
            res.map_month = True
    return res


def flags_due(cfg: dict, today: date | None = None) -> bool:
    last = cfg.get("flags_last_check", "")
    today = today or date.today()
    try:
        return today - date.fromisoformat(last) >= timedelta(days=FLAGS_EVERY_DAYS)
    except (TypeError, ValueError):
        return True


class DailyUpdater(threading.Thread):
    """Führt run() im Hintergrund aus; Ergebnis danach in .result."""

    def __init__(self, running: bool, flags_due: bool, timeout: float = 8.0):
        super().__init__(daemon=True, name="daily-update")
        self.running, self.flags_due, self.timeout = running, flags_due, timeout
        self.result: DailyResult | None = None

    def run(self) -> None:  # noqa: D401 (Thread-Methode)
        try:
            self.result = run(self.running, self.flags_due, self.timeout)
        except Exception as e:  # noqa: BLE001 – Update darf GoGoHam nie stören
            self.result = DailyResult(errors=[str(e)])
