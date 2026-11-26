"""S&P-Übung (ab 0.8.29): Auf einem Bandstück rufen erfundene Stationen CQ – du drehst am
VFO-Knopf deines Funkgeräts, suchst sie und rufst sie an. Es wird nie gesendet; GoGoHam liest nur
die Frequenz.

Ohne Qt und ohne Ton – nur der Ablauf. Die Zeit ist die des Tonstroms (cwsynth.Mixer). Jede
Station hat eine feste Frequenz (rf); wie sie klingt, rechnet der Mixer aus dem VFO aus.

Ablauf einer Station (wie im echten Contest):
- CQ → kurz hören. Hört sie dich (du sendest dein Rufzeichen nah genug an ihrer Frequenz und
  nicht, während sie selbst sendet), gibt sie dir den Austausch – manchmal mit falsch
  verstandenem Rufzeichen („DO2GCH 5NN 14“) oder nur halb („DO2?“). Dann berichtigst du.
- Dein Austausch → „TU …“ – das QSO steht im Log der Station.
- Manchmal ruft sie jemand anderes an (leise, etwas daneben); dann arbeitet sie erst den.
- Stationen kommen und gehen; schon gearbeitete bleiben auf dem Band (Doppel-QSO-Gefahr).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from . import propagation as pr, ssbvoice
from .practice import (GAIN, QSB_DB, Finding, Practice, Result, Settings, Transmission,
                       evaluate_qsos, lift)

# Bandstücke (kHz), auf denen die Stationen sitzen
SEGMENTS = {
    "CW": {"160": (1810, 1850), "80": (3500, 3560), "40": (7000, 7040), "20": (14000, 14060),
           "15": (21000, 21070), "10": (28000, 28070)},
    "SSB": {"160": (1840, 1900), "80": (3600, 3790), "40": (7060, 7190), "20": (14150, 14340),
            "15": (21200, 21440), "10": (28300, 28700)},
}
# Stationen auf dem Bandstück (20 m; andere Bänder im Verhältnis ihrer Breite) – 0.8.29.1 mehr
COUNT = {"CW": {1: 15, 2: 30, 3: 50, 4: 75, 5: 100},
         "SSB": {1: 10, 2: 20, 3: 30, 4: 42, 5: 55}}
NEAR_HZ = 10000                                      # SSB: Stimmen in diesem Umkreis zuerst
SPACING = {"CW": 250, "SSB": 2800}                   # Mindestabstand (Hz)
HEAR = {"CW": 200, "SSB": 700}                       # so weit daneben hört dich die Station
P_GHOST = {1: 0.12, 2: 0.2, 3: 0.3, 4: 0.4, 5: 0.55}  # nach CQ ruft jemand anderes
P_LOSE = 0.45                                        # ruft ihr beide: sie nimmt den anderen
P_PARTIAL, P_BUST = 0.06, 0.07                       # dein Rufzeichen halb / falsch verstanden
SPOT_SHARE = 0.45                                    # so viele Stationen werden gespottet

CONFUSE = {"G": "Z", "Z": "G", "C": "K", "K": "C", "H": "S", "S": "H", "B": "D", "D": "B",
           "U": "V", "V": "U", "W": "J", "J": "W", "P": "W", "E": "I", "I": "E", "T": "M",
           "M": "T", "N": "A", "A": "N", "R": "L", "L": "R", "F": "L", "O": "M", "Y": "Q",
           "Q": "Y", "X": "K", "2": "3", "3": "2", "4": "5", "5": "4", "6": "7", "7": "6",
           "1": "2", "8": "9", "9": "8", "0": "9"}


def segment(band: str, mode: str) -> tuple[int, int]:
    """Bandstück in Hz (unbekanntes Band: 50 kHz ab Bandanfang)."""
    seg = SEGMENTS["SSB" if mode == "SSB" else "CW"].get(band)
    if seg is None:
        mhz = pr.BAND_MHZ.get(band, 14.0)
        seg = (int(mhz * 1000), int(mhz * 1000) + 50)
    return seg[0] * 1000, seg[1] * 1000


def bust(call: str, rng: random.Random) -> str:
    """Rufzeichen so, wie man es falsch hören könnte (genau ein Zeichen anders)."""
    base, _, rest = call.partition("/")
    idx = [i for i, ch in enumerate(base) if ch in CONFUSE]
    if not idx:
        return call
    i = rng.choice(idx[1:] or idx)
    out = base[:i] + CONFUSE[base[i]] + base[i + 1:]
    return out + ("/" + rest if rest else "")


def partial(call: str, rng: random.Random) -> str:
    base = call.split("/")[0]
    return base[:3] if rng.random() < 0.5 or len(base) < 5 else base[-3:]


@dataclass
class Done:
    """Ein QSO aus Sicht der Gegenstation."""
    call: str                        # Rufzeichen der Station
    exch: str                        # was sie gesendet hat
    logged_as: str                   # wie sie DICH geloggt hat
    t: float = 0.0


@dataclass
class SimSpot:
    call: str
    freq: int
    spotter: str
    comment: str


@dataclass
class Runner:
    call: str
    exch: str
    rf: int
    wpm: int
    gain_db: float
    qsb: tuple[float, float, float]
    leave_at: float
    cut: bool = False
    voice: int = 0
    rate: float = 1.0
    cq: str = ""
    after: str = ""                  # nach dem QSO („TU DL1ABC TEST“)
    mode: str = "cq"                 # cq · listen · me · part · ghost
    next_at: float = 0.0
    heard_as: str = ""
    tries: int = 0
    ghost_now: bool = False
    ghost: tuple | None = None       # (Rufzeichen, Austausch, Stimme, Versatz Hz)
    spot_at: float | None = None
    planned: list = field(default_factory=list)
    tx: list = field(default_factory=list)      # (Beginn, Ende) der eigenen Sendungen
    gone: bool = False
    thief: bool = False              # gemischte Übung: hat deine Run-Frequenz übernommen


class SPPractice:
    """S&P-Übung – gleiche Schnittstelle wie practice.Practice (tick, on_sent, evaluate …)."""

    tuned = True                     # der Controller verschiebt den Ton nach dem VFO

    def __init__(self, contest, settings: Settings, calls: list[str], mycall: str,
                 home, sfi=None, k=None, history=None, doks: list[str] | None = None,
                 seed: int | None = None, when=None, voices=None):
        self.p = Practice(contest, settings, calls, mycall, home, sfi, k, history, doks,
                          seed, when, voices)
        self.s = settings
        self.rng = self.p.rng
        self.ssb = settings.mode == "SSB"
        self.voices = voices
        self.mycall = self.p.mycall
        self.contest = contest
        self._home, self._sfi, self._k, self._when = home, sfi, k, when
        self.band: str | None = settings.band
        self.runners: list[Runner] = []
        self.done: list[Done] = []
        self.spots: list[SimSpot] = []
        self.started = True
        self._next_new = 0.0
        self.keep_free: list[int] = []   # gemischte Übung: deine Run-Frequenz frei lassen
        self.others = set                # gemischte Übung: Rufzeichen, die dich gerade anrufen
        self._seg = segment(self.band, settings.mode)
        self._populate(0.0, initial=True)

    # -------------------------------------------------------------- Band und Stationen
    @property
    def pool_size(self) -> int:
        return self.p.pool_size

    def target(self) -> int:
        mode = "SSB" if self.ssb else "CW"
        n = COUNT[mode].get(self.s.activity, COUNT[mode][3])
        lo, hi = segment("20", mode)
        width = (self._seg[1] - self._seg[0]) / max(1, hi - lo)
        return max(4, int(round(n * min(1.5, width))))

    def set_band(self, band: str | None, t: float) -> None:
        """Das Funkgerät steht auf einem anderen Band: dort ein neues Bandstück füllen
        (None = Band gehört nicht zum Contest – Stille)."""
        if band == self.band:
            return
        for r in self.runners:
            r.planned.clear()
        self.runners = []
        self.band = band
        if band is None:
            return
        self.s.band = band
        self._seg = segment(band, self.s.mode)
        self._relevel(band)
        self._populate(t, initial=True)

    def _relevel(self, band: str) -> None:
        """Bandöffnung je Kontinent für das neue Band (die Rufzeichen bleiben dieselben)."""
        levels = {}
        if self._home is not None and band in pr.BAND_MHZ:
            from datetime import datetime, timezone
            g = pr.grid_now(self._home, [band], self._when or datetime.now(timezone.utc),
                            self._sfi, self._k)
            levels = {c: g[(band, c)].level for c in pr.CONTINENTS}
        self.p._pool = [(c, levels.get(lk.cont, pr.FAIR), lk) for c, _l, lk in self.p._pool]
        if hasattr(self.p, "_by_cont"):
            del self.p._by_cont

    def _populate(self, t: float, initial: bool = False) -> None:
        want = self.target()
        while len(self.runners) < want:
            r = self._new_runner(t, initial)
            if r is None:
                break
            self.runners.append(r)
            if not initial:
                break

    def _free_rf(self) -> int | None:
        lo, hi = self._seg
        gap = SPACING["SSB" if self.ssb else "CW"]
        for _ in range(200):
            if self.ssb:
                f = self.rng.uniform(lo + 2000, hi - 2000)
                f = round(f / 1000) * 1000 if self.rng.random() < 0.6 else round(f / 100) * 100
            else:
                f = round(self.rng.uniform(lo + 500, hi - 500) / 10) * 10
            if all(abs(f - r.rf) >= gap for r in self.runners) and \
                    all(abs(f - k) >= gap + 200 for k in self.keep_free):
                return int(f)
        return None

    def _new_runner(self, t: float, initial: bool) -> Runner | None:
        if not self.p._pool:
            return None
        rf = self._free_rf()
        if rf is None:
            return None
        busy = {r.call for r in self.runners} | self.others()
        for _ in range(40):
            call, level, lk = self.p._weighted_quick()
            if call in busy:
                continue
            exch = self.p.maker.make(call, lk, t / 60.0)
            if exch is None:
                continue
            lo, hi = GAIN[level]
            q = QSB_DB[self.s.qsb]
            life = self.rng.uniform(4, 30) * 60
            r = Runner(call=call, exch=exch, rf=rf,
                       wpm=self.rng.randint(min(self.s.wpm_min, self.s.wpm_max),
                                            max(self.s.wpm_min, self.s.wpm_max)),
                       gain_db=self.rng.uniform(hi, lo) + lift(self.s.mode),
                       qsb=(self.rng.uniform(0.05, 0.3), q * self.rng.uniform(0.5, 1.0),
                            self.rng.uniform(0, 2 * math.pi)),
                       leave_at=t + (life * self.rng.uniform(0.2, 1.0) if initial else life),
                       cut=(not self.ssb) and self.s.cut_numbers and self.rng.random() < 0.4)
            r.next_at = t + (self.rng.uniform(0, 8) if initial else self.rng.uniform(0.5, 3))
            self._texts(r)
            r.ghost = self._make_ghost(r)
            if self.s.spots and self.rng.random() < SPOT_SHARE:
                r.spot_at = t + self.rng.uniform(5 if initial else 20, 240)
            return r
        return None

    def _texts(self, r: Runner) -> None:
        c = r.call
        if self.ssb:
            n = self.voices.speakers() if self.voices is not None else 904
            r.voice = self.rng.randrange(max(1, n))
            r.rate = self.rng.uniform(0.92, 1.12)
            sp = ssbvoice.spell(c)
            r.cq = self.rng.choice((f"CQ contest, CQ contest, {sp}, {sp}, contest",
                                    f"CQ contest, {sp}, contest", f"{sp}, contest"))
            r.after = self.rng.choice((f"thank you, {sp}, contest", "thanks, QRZ?",
                                       f"QSL, {sp}"))
            for text in (r.cq, r.after, self._exch_text(r, self.mycall), self._again_text(r)):
                self._req(r.voice, r.rate, text, r.call)
        else:
            r.cq = self.rng.choice((f"CQ TEST {c} {c}", f"CQ {c} {c} TEST", f"TEST {c} {c}",
                                    f"{c} TEST", f"CQ TEST {c}"))
            r.after = self.rng.choice((f"TU {c} TEST", f"TU {c}", "TU", f"TU {c} CQ"))

    def _make_ghost(self, r: Runner):
        for _ in range(20):
            call, _lvl, lk = self.p._weighted_quick()
            if call != r.call and call != self.mycall:
                break
        else:
            return None
        ex = self.p.maker.make(call, lk) or "1"
        voice = self.rng.randrange(self.voices.speakers() if self.voices else 904) if self.ssb else 0
        off = self.rng.uniform(-150, 150) if self.ssb else self.rng.uniform(-60, 60)
        g = (call, ex, voice, off)
        if self.ssb:
            self._req(voice, 1.0, ssbvoice.call_text(call, False), r.call)
            self._req(r.voice, r.rate, self._exch_text(r, call), r.call)
        return g

    # -------------------------------------------------------------- Texte
    def _exch_text(self, r: Runner, heard: str) -> str:
        if self.ssb:
            return f"{ssbvoice.spell(heard)}, " + ssbvoice.exchange_text(f"59 {r.exch}",
                                                                          random.Random(r.call))
        return f"{heard} 5NN {r.exch}"

    def _again_text(self, r: Runner) -> str:
        if self.ssb:
            return ssbvoice.exchange_text(f"{r.exch} {r.exch}", random.Random(r.call + "2"))
        return f"{r.exch} {r.exch}"

    def _partial_text(self, part: str) -> str:
        return f"the {ssbvoice.spell(part)}, again?" if self.ssb else f"{part}?"

    @staticmethod
    def _key(voice: int, rate: float, text: str) -> str:
        return f"SP|{voice}|{rate:.3f}|{text}"

    def _req(self, voice: int, rate: float, text: str, tag: str = "") -> str:
        key = self._key(voice, rate, text)
        if self.voices is not None:
            try:
                self.voices.request(key, text, voice, rate, tag=tag)
            except TypeError:                           # einfache Stimmen ohne Vorrang
                self.voices.request(key, text, voice, rate)
        return key

    def near_calls(self, rf: float | None, span: float = NEAR_HZ) -> set[str]:
        """Stationen nahe der VFO-Frequenz – deren Stimmen rechnet GoGoHam zuerst."""
        if rf is None:
            return set()
        return {r.call for r in self.runners if abs(r.rf - rf) <= span}

    def _ready(self, r: Runner, text: str) -> bool:
        """SSB: ist die Stimme schon fertig? (Sonst wartet die Station kurz statt zu fehlen.)"""
        if not self.ssb or self.voices is None:
            return True
        self._req(r.voice, r.rate, text, r.call)
        return self.voices.get(self._key(r.voice, r.rate, text)) is not None

    # -------------------------------------------------------------- Senden der Stationen
    def _send(self, r: Runner, text: str, at: float, ghost: bool = False) -> float:
        """Station r (oder ihr Anrufer) sendet text ab at; gibt das Ende zurück."""
        if ghost:
            g = r.ghost
            who, rf, wpm = "G:" + r.call, int(r.rf + g[3]), max(16, r.wpm + self.rng.randint(-6, 4))
            gain, voice, rate = r.gain_db - self.rng.uniform(3, 12), g[2], 1.0
        else:
            who, rf, wpm, gain, voice, rate = r.call, r.rf, r.wpm, r.gain_db, r.voice, r.rate
            if r.cut:
                from . import cwsynth
                text = cwsynth.cut_numbers(text, leading_only=True)
        key = self._req(voice, rate, text, r.call) if self.ssb else ""
        tx = Transmission(who, text, wpm, 0.0, gain, at, None if ghost else r.qsb, key, rf)
        r.planned.append(tx)
        end = at + self.p._duration(key, text, wpm)
        if not ghost:
            r.tx.append((at, end))
            r.tx = r.tx[-6:]
        return end

    def _listen(self) -> float:
        return self.rng.uniform(1.8, 3.0) if self.ssb else self.rng.uniform(1.2, 2.2)

    def _wait_me(self) -> float:
        return self.rng.uniform(5.0, 6.5) if self.ssb else self.rng.uniform(3.5, 5.0)

    def _ghost_chance(self, r: Runner) -> float:
        p = P_GHOST.get(self.s.activity, 0.3)
        lk = self.contest.lookup(r.call)
        if lk is not None and getattr(self.p, "_own_cont", None) and lk.cont != self.p._own_cont:
            p *= 1.4                                    # DX ist gefragter
        return min(0.85, p)

    def _act(self, r: Runner, t: float) -> None:
        if r.mode == "cq":
            if not self._ready(r, r.cq):
                r.next_at = t + 0.5                     # Stimme rechnet noch: gleich nochmal
                return
            end = self._send(r, r.cq, t)
            self._after_cq(r, end)
        elif r.mode == "listen":
            if r.ghost_now and r.ghost is not None:      # der andere war dran
                g = r.ghost
                e1 = self._send(r, self._exch_text(r, g[0]), t)
                rep = ("QSL, thank you, " + ssbvoice.exchange_text(f"59 {g[1]}", self.rng)
                       if self.ssb else f"TU 5NN {g[1]}")
                e2 = self._send(r, rep, e1 + self.rng.uniform(0.2, 0.6), ghost=True)
                e3 = self._send(r, r.after, e2 + self.rng.uniform(0.2, 0.5))
                r.ghost_now = False
                r.ghost = self._make_ghost(r)
                self._after_qso(r, e3)
            else:
                r.mode, r.next_at = "cq", t + self.rng.uniform(0.0, 0.6)
        elif r.mode == "me":
            if r.tries == 0:                               # du schweigst: noch einmal
                r.tries = 1
                end = self._send(r, self._exch_text(r, r.heard_as), t)
                r.next_at = end + self._wait_me()
            else:                                          # aufgegeben
                r.mode, r.next_at = "cq", t + self.rng.uniform(0.5, 1.5)
        elif r.mode == "part":
            r.mode, r.next_at = "cq", t + self.rng.uniform(0.3, 1.0)

    def _after_cq(self, r: Runner, end: float) -> None:
        r.mode, r.next_at = "listen", end + self._listen()
        r.ghost_now = r.ghost is not None and self.rng.random() < self._ghost_chance(r)
        if r.ghost_now:
            text = ssbvoice.call_text(r.ghost[0], False) if self.ssb else r.ghost[0]
            self._send(r, text, end + self.rng.uniform(0.2, 0.9), ghost=True)

    def _after_qso(self, r: Runner, end: float) -> None:
        """Nach „TU“: enthält es das Rufzeichen, gilt es als CQ – sonst gleich CQ."""
        if self.ssb and "contest" in r.after or (not self.ssb and r.call in r.after.split()):
            self._after_cq(r, end)
        else:
            r.mode, r.next_at = "cq", end + self.rng.uniform(0.2, 0.6)

    # -------------------------------------------------------------- dein Senden
    def nearest(self, rf: float | None) -> Runner | None:
        if rf is None or not self.runners:
            return None
        r = min(self.runners, key=lambda x: abs(x.rf - rf))
        return r if abs(r.rf - rf) <= HEAR["SSB" if self.ssb else "CW"] else None

    def on_sent(self, text: str, t_start: float, t_end: float, my_exch: str = "",
                rf: float | None = None) -> None:
        r = self.nearest(rf)
        if r is None:
            return
        # sendet die Station gerade selbst, hört sie dich nicht
        if any(a <= t_start + 0.2 and b > t_start + 0.25 for a, b in r.tx):
            return
        toks = text.upper().split()
        has_me = self.mycall in toks or any(t.rstrip("?") == self.mycall for t in toks)
        msg = Practice.parse(text, self.mycall, my_exch)
        at = t_end + self.rng.uniform(0.2, 0.6)

        def hold():                                 # geplante eigene Sendungen zurückhalten
            r.planned = [p for p in r.planned if p.start <= t_start or p.who != r.call]
            r.tx = [(a, b) for a, b in r.tx if a <= t_start]

        if r.mode in ("cq", "listen"):
            if not has_me:
                return
            if r.ghost_now and self.rng.random() < P_LOSE:
                return                              # der andere war lauter
            hold()
            r.ghost_now = False
            x = self.rng.random()
            if x < P_PARTIAL:
                end = self._send(r, self._partial_text(partial(self.mycall, self.rng)), at)
                r.mode, r.next_at = "part", end + self._wait_me()
                return
            r.heard_as = bust(self.mycall, self.rng) if x < P_PARTIAL + P_BUST else self.mycall
            self._give(r, at)
        elif r.mode == "part":
            if has_me:
                hold()
                r.heard_as = self.mycall
                self._give(r, at)
        elif r.mode == "me":
            if msg["exch"]:
                hold()
                if has_me:
                    r.heard_as = self.mycall        # mit Rufzeichen berichtigt
                self.done.append(Done(r.call, r.exch, r.heard_as, t_end))
                end = self._send(r, r.after, at)
                self._after_qso(r, end)
            elif has_me:
                hold()
                r.heard_as = self.mycall
                self._give(r, at)
            elif msg["agn"]:
                hold()
                end = self._send(r, self._again_text(r), at)
                r.next_at = end + self._wait_me()

    def _give(self, r: Runner, at: float) -> None:
        end = self._send(r, self._exch_text(r, r.heard_as), at)
        r.mode, r.tries, r.next_at = "me", 0, end + self._wait_me()

    def abort_own(self, t: float) -> None:
        pass

    # -------------------------------------------------------------- Takt
    def tick(self, t: float) -> list[Transmission]:
        if self.band is None:
            return []
        for r in self.runners:
            idle = r.mode in ("cq", "listen") and not r.ghost_now
            if t >= r.leave_at and idle and not r.planned:
                r.gone = True
        self.runners = [r for r in self.runners if not r.gone]
        if len(self.runners) < self.target() and t >= self._next_new:
            self._next_new = t + self.rng.uniform(15, 60)
            self._populate(t)
        due = []
        for r in self.runners:
            if t >= r.next_at:
                r.next_at = t + 3600                # _act setzt den nächsten Zeitpunkt
                self._act(r, t)
            if r.spot_at is not None and t >= r.spot_at:
                self.spots.append(self._spot(r))
                r.spot_at = t + self.rng.uniform(300, 900) if self.rng.random() < 0.3 else None
            now = [p for p in r.planned if p.start <= t]
            if now:
                r.planned = [p for p in r.planned if p.start > t]
                due += now
        return due

    def _spot(self, r: Runner) -> SimSpot:
        call = r.call if self.rng.random() > 0.03 else bust(r.call, self.rng)
        spotter = self.p._weighted_quick()[0] if self.p._pool else "DL0XX"
        if self.ssb:
            off = self.rng.choice((0, 0, 0, 100, -100, 500, -500, 1000))
            return SimSpot(call, int(round((r.rf + off) / 100) * 100), spotter,
                           self.rng.choice(("", "CQ TEST", "59", "TNX QSO")))
        off = self.rng.choice((0, 0, 0, 0, 100, -100, 200))
        return SimSpot(call, int(round((r.rf + off) / 100) * 100), spotter + "-#",
                       f"CW {self.rng.randint(6, 34)} dB {r.wpm} WPM CQ")

    def take_spots(self) -> list[SimSpot]:
        out, self.spots = self.spots, []
        return out

    def finished(self, t: float) -> bool:
        return self.s.minutes > 0 and t >= self.s.minutes * 60

    # -------------------------------------------------------------- Auswertung
    def truths(self) -> list[Done]:
        return list(self.done)

    def evaluate(self, qsos, seconds: float) -> Result:
        res = evaluate_qsos(self.truths(), qsos, seconds)
        self.extra_findings(res, qsos)
        return res

    def extra_findings(self, res: Result, qsos) -> None:
        """Falsch geloggt worden und Doppel-QSOs (auch für die gemischte Übung)."""
        for d in self.done:
            if d.logged_as != self.mycall:
                res.findings.append(Finding("theirs", d.logged_as, self.mycall, d.call))
        seen: dict[tuple[str, str], int] = {}
        for q in qsos:
            key = ((q.call or "").upper(), getattr(q, "band", ""))
            seen[key] = seen.get(key, 0) + 1
            if seen[key] == 2:
                res.findings.append(Finding("dupe", key[0], "", key[0]))
