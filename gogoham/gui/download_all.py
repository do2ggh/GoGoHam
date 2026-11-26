"""„Alles herunterladen“ (ab 0.8.28.3): alle Daten nacheinander im Hintergrund holen.

Contest-Regeln, Länderdatei, MASTER.SCP, DOK-Liste, Flaggen, beide Kartenbilder – auf Wunsch die
natürlichen Stimmen (Piper für Ansagen und Übung) – und zum Schluss speech-dispatcher (fragt
nach dem Passwort). Fortschritt über report(text), am Ende eine Zusammenfassung über
finished(lines). Die Einzelknöpfe bleiben unverändert.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from PySide6.QtCore import QTimer

from ..i18n import tr


@dataclass
class Step:
    name: str
    work: object                     # läuft im Hintergrund, gibt (ok, Text) zurück
    after: object = None             # danach im Fenster-Thread, bekommt das Ergebnis


@dataclass
class Outcome:
    name: str
    ok: bool
    text: str = ""


def _rules():
    from .. import rulesupdate
    res = rulesupdate.check_and_download()
    return (not res.offline and not res.errors), res.summary(), res


def _cty():
    from .. import cty
    p = cty.download()
    db = cty.CtyDB.from_file(p)
    return True, tr("{n} Gebiete", n=len(db.entities)), db


def _scp():
    from .. import scp
    p = scp.download()
    db = scp.ScpDB.from_file(p)
    return True, tr("{n} Rufzeichen", n=len(db)), db


def _doks():
    from .. import dok
    n_ov, n_s = dok.download()
    return True, tr("{n_ov} Ortsverbände, {n_s} Sonder-DOKs", n_ov=n_ov, n_s=n_s), None


def _flags():
    from .. import flags
    codes = flags.missing_codes()
    if not codes:
        return True, tr("schon vollständig"), None
    d = flags.FlagDownloader(codes)
    d.run()                                         # hier im Hintergrund-Thread
    ok = d.total - len(d.failed)
    return not d.failed, tr("{ok} von {total}", ok=ok, total=d.total), None


def _map(what: str):
    def work():
        from .. import mapimages
        d = mapimages.MapDownloader(what)
        d.run()
        return (not d.error), (d.error or tr("geladen")), None
    return work


def _piper(what: str):
    def work():
        from .. import piper
        d = piper.PiperDownloader(what=what)
        d.run()
        return (not d.error), (d.error or tr("geladen")), None
    return work


def steps(win, voices: bool) -> list[Step]:
    def after_rules(res):
        if res is not None and getattr(res, "changed", False):
            from .. import contests as contestmod
            contestmod.reload()

    def after_cty(db):
        win.cty = db
        win._update_cty_label()
        if win.db:
            win._setup_contest()
            win.reload()

    def after_scp(db):
        win.scp = db
        win._update_cty_label()

    def after_doks(_r):
        from ..contests.rulebased import reload_doks
        reload_doks()

    def after_flags(_r):
        win._pixmaps.clear()
        win.update_check()

    def after_map(_r):
        win.map_view.reload_layers()

    def after_piper(_r):
        win._setup_speech()

    out = [Step(tr("Contest-Regeln"), _rules, after_rules),
           Step(tr("Länderdatei"), _cty, after_cty),
           Step("MASTER.SCP", _scp, after_scp),
           Step(tr("DOK-Liste"), _doks, after_doks),
           Step(tr("Flaggen"), _flags, after_flags),
           Step(tr("Kartenbild NASA"), _map("nasa"), after_map),
           Step(tr("Kartenbild Relief"), _map("relief"), after_map)]
    if voices:
        out += [Step(tr("Stimmen für die Ansagen (Piper)"), _piper("speech"), after_piper),
                Step(tr("Stimmen für die SSB-Übung"), _piper("practice"), None)]
    return out


class DownloadAll:
    """Arbeitet die Schritte nacheinander ab; speech-dispatcher kommt zuletzt (Passwort)."""

    def __init__(self, win, voices: bool, report, finished, speechd: bool = True):
        self.win = win
        self.steps = steps(win, voices)
        self.speechd = speechd
        self.report, self.finished = report, finished
        self.results: list[Outcome] = []
        self._i = -1
        self._thread = None
        self._box: dict = {}
        self._timer = QTimer()
        self._timer.timeout.connect(self._poll)
        self.total = len(self.steps) + (1 if speechd else 0)
        self._done = False

    @property
    def running(self) -> bool:
        return self._i >= 0 and not self._done

    def start(self) -> None:
        self._next()
        self._timer.start(150)

    def _say(self, text: str) -> None:
        try:
            self.report(text)
        except RuntimeError:                      # Einstellungsfenster schon zu
            pass

    def _next(self) -> None:
        self._i += 1
        if self._i >= len(self.steps):
            self._timer.stop()
            self._speechd()
            return
        st = self.steps[self._i]
        self._say(tr("{i} von {n}: {name} …", i=self._i + 1, n=self.total, name=st.name))
        box = self._box = {}

        def run():
            try:
                box["r"] = st.work()
            except Exception as e:                # noqa: BLE001 – jeder Schritt für sich
                box["r"] = (False, str(e) or e.__class__.__name__, None)

        self._thread = threading.Thread(target=run, daemon=True, name="download-all")
        self._thread.start()

    def _poll(self) -> None:
        if self._thread is None or self._thread.is_alive():
            return
        st = self.steps[self._i]
        ok, text, data = self._box.get("r", (False, tr("unbekannter Fehler"), None))
        if ok and st.after is not None:
            try:
                st.after(data)
            except Exception as e:                # noqa: BLE001
                ok, text = False, str(e)
        self.results.append(Outcome(st.name, ok, text))
        self._thread = None
        self._next()

    def _speechd(self) -> None:
        from .. import speech
        if not self.speechd:
            self._finish()
            return
        name = "speech-dispatcher"
        if speech.speechd_ok():
            self.results.append(Outcome(name, True, tr("schon installiert")))
            self._finish()
            return
        self._say(tr("{i} von {n}: {name} – bitte Passwort eingeben …", i=self.total,
                     n=self.total, name=name))

        def done(ok: bool) -> None:
            self.results.append(Outcome(name, ok, tr("installiert") if ok else
                                        tr("nicht installiert")))
            self._finish()

        self.win.install_speechd(done=done)

    def _finish(self) -> None:
        self._done = True
        good = sum(1 for r in self.results if r.ok)
        self._say(tr("Fertig: {ok} von {n} erledigt", ok=good, n=len(self.results)))
        try:
            self.finished(self.results)
        except RuntimeError:
            pass
