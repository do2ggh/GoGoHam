"""Gemischte Übung (ab 0.8.30): Run auf deiner eigenen Frequenz, zwischendurch S&P am VFO-Knopf.

Ohne Qt und ohne Ton – nur der Ablauf. Es wird nie gesendet; GoGoHam liest nur die Frequenz.

- Deine Run-Frequenz ist die Stelle, an der du CQ rufst. Rufst du woanders CQ, wandert sie mit
  (auch auf ein anderes Band).
- Steht der VFO auf deiner Run-Frequenz (CW ± 150 Hz, SSB ± 400 Hz), rufen dich die Stationen an
  wie in der Run-Übung. Ihre Signale liegen dort auf dem Band – drehst du weg, hörst du sie nicht
  mehr, und wer dich anrufen wollte, gibt bald auf.
- Weg von der Run-Frequenz ist alles wie in der S&P-Übung.
- Auf Wunsch (Settings.steal) übernimmt nach 1–2 Minuten Abwesenheit eine andere Station deine
  Run-Frequenz und ruft dort CQ – dann ruft dich dort kaum noch jemand an.
"""

from __future__ import annotations

import random

from . import practice_sp as sps
from .practice import Finding, Result, Transmission, evaluate_qsos

TOL = {"CW": 150, "SSB": 400}            # so nah heißt „auf der Run-Frequenz“
STEAL_S = (60.0, 120.0)                  # so lange weg, dann ist die Frequenz evtl. besetzt
THIEF_DAMP = 0.15                        # Anrufer, solange ein anderer dort CQ ruft


class MixedPractice:
    """Gleiche Schnittstelle wie SPPractice (tick, on_sent, set_band, evaluate …)."""

    tuned = True

    def __init__(self, contest, settings, calls, mycall, home, sfi=None, k=None, history=None,
                 doks=None, seed=None, when=None, voices=None):
        settings.qrm = False                         # Störer gibt es hier echt: das Band
        self.sp = sps.SPPractice(contest, settings, calls, mycall, home, sfi, k, history, doks,
                                 seed, when, voices)
        self.run = self.sp.p                          # gleiche Rufzeichen, gleiche Bandöffnung
        self.run.voice_tag = "RUN"                    # Stimmen der Anrufer zuerst rechnen
        # niemand ist zugleich Anrufer und S&P-Station
        self.run.others = lambda: {r.call for r in self.sp.runners}
        self.sp.others = lambda: {c.call for c in self.run.callers}
        self.s = settings
        self.rng = self.sp.rng
        self.ssb = settings.mode == "SSB"
        self.tol = TOL["SSB" if self.ssb else "CW"]
        self.voices, self.contest, self.mycall = voices, contest, self.sp.mycall
        self.started = True
        self.run_rf: int | None = None
        self.vfo: int | None = None
        self.run_seconds = 0.0
        self._last_t: float | None = None
        self._away_since: float | None = None
        self._steal_at: float | None = None
        self.thief = None
        self._offs: dict[str, int] = {}
        self.run_calls: set[str] = set()              # wer dir im Run geantwortet hat

    # -------------------------------------------------------------- Weiterreichen
    @property
    def pool_size(self) -> int:
        return self.sp.pool_size

    @property
    def band(self):
        return self.sp.band

    @property
    def runners(self):
        return self.sp.runners

    @property
    def done(self):
        return self.sp.done

    def set_band(self, band, t: float) -> None:
        if band != self.sp.band and self.thief is not None:
            self.thief = None                         # das Bandstück wird neu gefüllt
        self.sp.set_band(band, t)
        self._clear_run_rf()

    def take_spots(self):
        return self.sp.take_spots()

    def near_calls(self, rf, span: float = sps.NEAR_HZ) -> set[str]:
        return self.sp.near_calls(rf, span) | {"RUN"}

    def finished(self, t: float) -> bool:
        return self.sp.finished(t)

    def abort_own(self, t: float) -> None:
        self.run.abort_own(t)

    # -------------------------------------------------------------- Run-Frequenz
    def at_run(self, vfo=None) -> bool | None:
        """None = noch keine Run-Frequenz (oder kein VFO), sonst: steht der VFO darauf?"""
        vfo = self.vfo if vfo is None else vfo
        if self.run_rf is None or vfo is None:
            return None
        return abs(vfo - self.run_rf) <= self.tol

    def _move_run(self, rf: int, t: float) -> None:
        """Neue Run-Frequenz: wer bisher anrief, ist weg; S&P-Stationen direkt dort weichen."""
        self.run_rf = int(rf)
        self.run.callers, self.run.current, self.run.planned = [], None, []
        self.run.waiting_since = None
        self._offs.clear()
        self._away_since = self._steal_at = None
        self.thief = None
        gap = max(sps.SPACING["SSB" if self.ssb else "CW"], self.tol + 50)
        for r in self.sp.runners:
            if abs(r.rf - self.run_rf) < gap:
                r.gone = True
                r.planned.clear()
        self.sp.runners = [r for r in self.sp.runners if not r.gone]
        self._clear_run_rf()

    def _clear_run_rf(self) -> None:
        """Neue S&P-Stationen nicht auf deine Run-Frequenz setzen."""
        self.sp.keep_free = [self.run_rf] if self.run_rf is not None and self.thief is None \
            else []

    def set_vfo(self, vfo, t: float) -> None:
        """Vom Controller in jedem Takt: wo der VFO steht (None = kein Funkgerät)."""
        self.vfo = None if vfo is None else int(vfo)
        dt = 0.0 if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t
        at = self.at_run()
        if at:
            self.run_seconds += dt
            self._away_since = self._steal_at = None
        elif at is False and self._away_since is None:
            self._away_since = t
            if self.s.steal and self.thief is None:
                self._steal_at = t + self.rng.uniform(*STEAL_S)

    def _steal(self, t: float) -> None:
        from .bands import band_for_freq
        if self.sp.band is None or self.run_rf is None or \
                band_for_freq(self.run_rf) != self.sp.band:   # du bist auf einem anderen Band
            return
        r = self.sp._new_runner(t, False)
        if r is None:
            self._steal_at = t + 10.0                  # gerade niemand frei – etwas später
            return
        off = self.rng.uniform(-200, 200) if self.ssb else self.rng.uniform(-50, 50)
        r.rf = int(self.run_rf + off)
        r.leave_at = t + self.rng.uniform(180, 480)
        r.spot_at = None
        r.next_at = t + self.rng.uniform(0.0, 2.0)
        r.thief = True
        self.sp.runners.append(r)
        self.thief = r
        self._clear_run_rf()

    def _thief_here(self) -> bool:
        r = self.thief
        if r is None:
            return False
        if r.gone or r not in self.sp.runners:
            self.thief = None
            self._clear_run_rf()
            return False
        return True

    # -------------------------------------------------------------- dein Senden
    def on_sent(self, text: str, t_start: float, t_end: float, my_exch: str = "",
                rf=None) -> None:
        rf = self.vfo if rf is None else rf
        msg = self.run.parse(text, self.mycall, my_exch)
        if msg["cq"] and rf is not None and (self.run_rf is None or
                                             abs(rf - self.run_rf) > self.tol):
            self._move_run(int(rf), t_start)
        if self.at_run(rf):
            self.run.on_sent(text, t_start, t_end, my_exch)
            self.run_calls |= {c.call for c in self.run.callers if c.state != "calling"}
        else:
            self.sp.on_sent(text, t_start, t_end, my_exch, rf=rf)

    # -------------------------------------------------------------- Takt
    def _offset(self, tx: Transmission) -> int:
        """Anrufer sitzen etwas neben deiner Frequenz (CW: wie ihre Tonhöhe, SSB: ± 120 Hz)."""
        off = self._offs.get(tx.who)
        if off is None:
            if self.ssb:
                off = int(random.Random(tx.who).uniform(-120, 120))
            else:
                off = int(max(-130, min(130, (tx.pitch - 600) * 0.6))) if tx.pitch else 0
            self._offs[tx.who] = off
        return off

    def tick(self, t: float) -> list[Transmission]:
        if self._steal_at is not None and t >= self._steal_at and self.thief is None:
            self._steal_at = None
            self._steal(t)
        self.run.damp = THIEF_DAMP if self._thief_here() else 1.0
        due = self.sp.tick(t)
        if self.run_rf is not None:
            for tx in self.run.tick(t):
                tx.rf = self.run_rf + self._offset(tx)
                due.append(tx)
        return due

    # -------------------------------------------------------------- Auswertung
    def truths(self):
        return self.run.truths() + self.sp.truths()

    def evaluate(self, qsos, seconds: float) -> Result:
        res = evaluate_qsos(self.truths(), qsos, seconds)
        self.sp.extra_findings(res, qsos)
        run_calls = {c.call for c in self.run.truths()} | self.run_calls
        n_run = sum(1 for q in qsos if (q.call or "").upper() in run_calls)
        err_run = sum(1 for f in res.findings if f.call in run_calls)
        sp_s = max(0.0, seconds - self.run_seconds)
        res.parts = {
            "run": {"qsos": n_run, "errors": err_run, "seconds": self.run_seconds,
                    "rate": _rate(n_run, self.run_seconds)},
            "sp": {"qsos": res.qsos - n_run, "errors": res.errors - err_run, "seconds": sp_s,
                   "rate": _rate(res.qsos - n_run, sp_s)},
        }
        return res


def _rate(n: int, seconds: float) -> int:
    return int(round(n * 3600 / seconds)) if seconds >= 60 else 0


__all__ = ["MixedPractice", "TOL", "Finding"]
