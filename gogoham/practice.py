"""Übungsmodus (ab 0.8.28): erfundene Stationen rufen dich an – es wird nie gesendet.

Ohne Qt und ohne Ton – nur der Ablauf, damit er sich testen lässt. Die Zeit ist die des
Tonstroms (Sekunden seit Beginn, siehe cwsynth.Mixer).

Ablauf im Run-Betrieb (wie im echten Contest):
- Nach CQ oder TU rufen eine oder mehrere Stationen (je nach „Betrieb“), versetzt und mit
  eigener Tonhöhe, eigenem Tempo und eigener Lautstärke.
- Gibst du ein Rufzeichen genau zurück, antwortet diese Station mit ihrem Austausch; die anderen
  warten. Ein falsches oder halbes Rufzeichen („ABC?“) beantworten die passenden Stationen mit
  ihrem Rufzeichen. AGN/?/NR? → Wiederholung.
- TU (oder ein neuer CQ) beendet das QSO; wer dann noch ruft, ruft wieder – bis die Geduld zu
  Ende ist.
- Am Ende vergleicht evaluate() dein Log mit dem, was wirklich gesendet wurde.
"""

from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import cwsynth, propagation as pr, regions, ssbvoice

# Zustände einer Station
CALLING, WORKING, SENT, DONE, GONE = "calling", "working", "sent", "done", "gone"

KEYWORDS = {"CQ", "TEST", "QRZ", "TU", "TNX", "TKS", "73", "EE", "AGN", "NR", "CL", "RPT", "PSE",
            "R", "QSL", "DE", "K", "BK", "5NN", "599", "ENN", "RST", "UR", "ES", "GL", "FB",
            "QRL", "SRI", "CFM"}
AGN = {"AGN", "AGN?", "?", "NR?", "RPT", "RPT?", "CL?", "PSE", "NR"}
TU = {"TU", "TNX", "TKS", "73", "EE", "QSL", "QRZ", "QRZ?", "THANKS", "THANK"}
SSB_WORDS = {"CALLQ": "?", "AGN": "AGN?", "NR": "NR?"}     # Sprachspeicher → Bedeutung
CALLISH = re.compile(r"^[A-Z0-9/]*[A-Z][A-Z0-9/]*$|^[A-Z0-9/]*[0-9][A-Z0-9/]*$")

ACTIVITY = {1: 0.7, 2: 1.2, 3: 1.8, 4: 2.8, 5: 4.2}     # mittlere Anrufer je CQ
WEIGHT = {pr.GOOD: 4.0, pr.FAIR: 2.0, pr.POOR: 0.8, pr.CLOSED: 0.15}
# grober Anteil der Anrufer je Kontinent (der eigene Kontinent bekommt OWN_SHARE)
SHARE = {"EU": 2.5, "NA": 2.5, "AS": 1.5, "SA": 0.6, "AF": 0.4, "OC": 0.3}
OWN_SHARE = 5.0
GAIN = {pr.GOOD: (-2, -10), pr.FAIR: (-8, -16), pr.POOR: (-14, -22), pr.CLOSED: (-18, -25)}
QSB_DB = {0: 0.0, 1: 4.0, 2: 9.0, 3: 15.0}
NOISE_DB = {0: -60.0, 1: -34.0, 2: -26.0, 3: -20.0}
# SSB (0.8.30): breiteres Rauschen (300–2700 Hz) und Computerstimmen – sonst bei leichtem
# Rauschen schon undeutlich. Rauschen leiser, Stimmen etwas lauter.
NOISE_DB_SSB = {0: -60.0, 1: -42.0, 2: -36.0, 3: -31.0}
SSB_LIFT_DB = 3.0


def noise_db(s: "Settings") -> float:
    return (NOISE_DB_SSB if s.mode == "SSB" else NOISE_DB)[s.noise]


def lift(mode: str) -> float:
    """Zusätzliche Lautstärke der Gegenstationen (dB) – nur SSB."""
    return SSB_LIFT_DB if mode == "SSB" else 0.0

# Austausch-Arten, die der Übungsmodus erzeugen kann (UKW und Digital kommen später)
POWERS = ("100", "100", "100", "KW", "KW", "500", "1K", "400", "200", "5")


@dataclass
class Settings:
    contest: str = "cqww-cw"
    band: str = "20"
    mode: str = "CW"
    minutes: int = 10                # 0 = ohne Ende
    wpm_min: int = 24
    wpm_max: int = 32
    activity: int = 3                # 1 … 5
    noise: int = 1                   # 0 … 3
    qsb: int = 1                     # 0 … 3
    qrm: bool = False
    doubles: bool = True             # gelegentlich ruft eine schon gearbeitete Station nochmal
    cut_numbers: bool = True
    my_wpm: int = 28
    my_pitch: int = 600
    volume: int = 70                 # Prozent
    style: str = "run"               # „run“: du rufst CQ · „sp“: du suchst am VFO (0.8.29)
                                     # · „mix“: Run + S&P (0.8.30)
    spots: bool = True               # S&P: nachgebildete Spots in der Bandmap
    steal: bool = False              # gemischt: Frequenz wird übernommen, wenn du lange weg bist

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Settings":
        s = cls()
        for k, v in (d or {}).items():
            if hasattr(s, k) and isinstance(v, type(getattr(s, k))):
                setattr(s, k, v)
        return s


@dataclass
class Caller:
    call: str
    exch: str                        # was die Station sendet (ohne RST), z. B. „14“ oder „123“
    wpm: int
    pitch: float
    gain_db: float
    qsb: tuple[float, float, float]
    patience: int
    twice: bool                      # gibt das Rufzeichen zweimal
    cut: bool                        # abgekürzte Zahlen
    voice: int = 0                   # SSB: Sprecher
    rate: float = 1.0                # SSB: etwas schneller/langsamer
    say_call: str = ""               # SSB: fertig formulierte Sätze (vorab erzeugt)
    say_call2: str = ""
    say_exch: str = ""
    say_again: str = ""
    state: str = CALLING
    muted: bool = False              # wartet, weil gerade jemand anderes dran ist
    repeat: bool = False             # ruft trotzdem dazwischen (Doppelanrufe)


@dataclass
class Transmission:
    who: str
    text: str
    wpm: int
    pitch: float
    gain_db: float
    start: float
    qsb: tuple[float, float, float] | None = None
    key: str = ""                    # SSB: Schlüssel der erzeugten Stimme
    rf: int = 0                      # S&P: Frequenz der Station (Hz) – Ton hängt vom VFO ab


@dataclass
class Finding:
    kind: str                        # call / exch / nil / missed
    logged: str = ""
    right: str = ""
    call: str = ""


@dataclass
class Result:
    qsos: int = 0
    correct: int = 0
    seconds: float = 0.0
    findings: list[Finding] = field(default_factory=list)
    parts: dict | None = None        # gemischte Übung: {"run": {...}, "sp": {...}}

    @property
    def rate(self) -> int:
        return int(round(self.qsos * 3600 / self.seconds)) if self.seconds >= 60 else 0

    @property
    def errors(self) -> int:
        return len(self.findings)


def norm_tokens(text: str) -> list[str]:
    out = []
    for t in (text or "").upper().replace("/", " ").split():
        t = t.replace("Ø", "0")
        if re.fullmatch(r"[0-9TN]+", t) and any(c.isdigit() for c in t):
            t = t.replace("T", "0").replace("N", "9")
        if t.isdigit():
            t = str(int(t))
        out.append(t)
    return out


def similar(a: str, b: str) -> int:
    """Levenshtein-Abstand (kurze Rufzeichen – einfach gerechnet)."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# ------------------------------------------------------------------ Austausch erzeugen
class ExchangeMaker:
    """Austausch einer erfundenen Station passend zum Contest. None = kann nicht erzeugt werden."""

    def __init__(self, contest, history=None, doks: list[str] | None = None,
                 rng: random.Random | None = None):
        self.contest = contest
        self.history = history
        self.doks = doks or []
        self.rng = rng or random.Random()
        self.serial_base = self.rng.randint(5, 120)

    def kind(self, lk) -> str | None:
        return self.contest.expected_kind(lk)

    def make(self, call: str, lk, minute: float = 0.0) -> str | None:
        k = self.kind(lk)
        r = self.rng
        h = self.history.get(call) if self.history is not None else None
        serial = lambda: str(max(1, int(self.serial_base + minute * r.uniform(0.5, 2.5)  # noqa: E731
                                        + r.randint(-60, 400))))
        if k == "cq_zone":
            return f"{lk.cq:02d}" if lk and lk.cq else None
        if k == "itu_zone":
            return f"{lk.itu:02d}" if lk and lk.itu else None
        if k == "serial_member":                # AGCW: etwa jede dritte Station ist Mitglied
            return serial() + (f"/{r.randint(100, 4200)}" if r.random() < 0.35 else "")
        if k == "iaru":
            return f"{lk.itu:02d}" if lk and lk.itu else None
        if k in ("serial", "serial_iota"):
            return serial()
        if k == "dok":
            d = (h.dok if h and h.dok else "") or (r.choice(self.doks) if self.doks else "")
            return d or None
        if k == "state":
            return r.choice(sorted(regions.STATES_48_DC))
        if k == "province":
            return regions.province_from_call(call) or r.choice(sorted(regions.VE_PROVINCES))
        if k == "power":
            return r.choice(POWERS)
        if k == "age":
            return f"{r.randint(18, 85):02d}"
        if k == "lic_year":
            return f"{r.choice(list(range(60, 100)) + list(range(0, 25))):02d}"
        if k == "oblast":
            return r.choice(sorted(regions.RU_OBLASTS))
        if k == "itu_region":
            if not lk:
                return None
            return "2" if lk.cont in ("NA", "SA") else "3" if lk.cont == "OC" or (
                lk.cont == "AS" and (lk.lon or 0) > 60) else "1"
        if k in ("district", "serial_district"):
            host = getattr(self.contest, "host", None) or {}
            codes = host.get("codes") or []
            # REF: Übersee-Gebiete senden ihren Präfix (FG …), das Festland ein Departement
            own = [c for c in codes if c in (host.get("countries") or ())]
            if lk is not None and lk.country in own:
                return lk.country if k == "district" else f"{serial()} {lk.country}"
            codes = [c for c in codes if c not in own] or codes
            if not codes:
                return None
            c = r.choice(codes)
            return c if k == "district" else f"{serial()} {c}"
        return None                     # grid4, serial_grid6, xe_state … (noch nicht)


def supported_kinds() -> set[str]:
    return {"cq_zone", "iaru", "serial", "serial_iota", "dok", "state", "province", "power",
            "age", "lic_year", "oblast", "itu_region", "district", "serial_district", "itu_zone",
            "serial_member"}


def can_practice(contest_cls, mode: str = "CW") -> bool:
    """CW bzw. SSB, Kurzwelle und ein Austausch, den der Übungsmodus erzeugen kann."""
    if getattr(contest_cls, "free", False):     # freies Log (0.10.18): kein Contest zum Üben
        return False
    rules = getattr(contest_cls, "rules", {}) or {}
    if ("PH" if mode == "SSB" else "CW") not in (rules.get("modes") or []):
        return False
    if not pr.hf_bands(rules.get("bands") or []):
        return False
    kinds = set()
    for f in rules.get("exchange", []):
        if f.get("field") == "rst":
            continue
        if f.get("field") == "location":
            kinds |= set((f.get("by_region") or {}).values())
        else:
            kinds.add(f.get("field"))
    return bool(kinds) and bool(kinds & supported_kinds())


# ------------------------------------------------------------------ die Übung
class Practice:
    def __init__(self, contest, settings: Settings, calls: list[str], mycall: str,
                 home: tuple[float, float] | None, sfi=None, k=None, history=None,
                 doks: list[str] | None = None, seed: int | None = None,
                 when: datetime | None = None, voices=None):
        self.contest = contest
        self.s = settings
        self.ssb = settings.mode == "SSB"
        self.voices = voices                   # SSB: ssbvoice.VoiceBank (None = nur rechnen)
        self.rng = random.Random(seed)
        self.mycall = mycall.upper()
        self.maker = ExchangeMaker(contest, history, doks, self.rng)
        self.callers: list[Caller] = []
        self.done: list[Caller] = []           # QSO von der Gegenseite aus fertig
        self.worked: set[str] = set()
        self.current: Caller | None = None
        self.planned: list[Transmission] = []
        self.waiting_since: float | None = None
        self.qrm_next = 20.0
        self.started = False
        self.damp = 1.0                        # gemischt: weniger Anrufer (Frequenz besetzt)
        self.voice_tag = ""                    # gemischt: Vorrang beim Rechnen der Stimmen
        self.others = set                      # gemischt: Rufzeichen, die schon S&P machen
        self._pool = self._make_pool(calls, home, sfi, k, when)

    # -------------------------------------------------------------- Auswahl der Stationen
    def _make_pool(self, calls, home, sfi, k, when) -> list[tuple[str, int, object]]:
        """(Rufzeichen, Stufe der Bandöffnung, Lookup) – nur Stationen, die dich arbeiten dürfen
        und deren Austausch sich erzeugen lässt."""
        levels = {}
        if home is not None and self.s.band in pr.BAND_MHZ:
            when = when or datetime.now(timezone.utc)
            g = pr.grid_now(home, [self.s.band], when, sfi, k)
            levels = {c: g[(self.s.band, c)].level for c in pr.CONTINENTS}
        rng = random.Random(self.rng.random())
        cand = [c for c in calls if c and c != self.mycall and "/" not in c[:1]]
        rng.shuffle(cand)
        pool = []
        me = self.contest.lookup(self.mycall)
        self._own_cont = me.cont if me is not None else None
        per: dict[str, int] = {}
        for call in cand[:20000]:
            lk = self.contest.lookup(call)
            if lk is None or lk.entity is None:
                continue
            if self.maker.kind(lk) is None or self.maker.make(call, lk) is None:
                continue
            probe = _ProbeQso(call, self.s.band)
            try:
                if self.contest.contact_problem(probe, lk):
                    continue
            except Exception:                   # noqa: BLE001 – Regeln ohne Prüfung
                pass
            if per.get(lk.cont, 0) >= 600:
                continue
            per[lk.cont] = per.get(lk.cont, 0) + 1
            pool.append((call, levels.get(lk.cont, pr.FAIR), lk))
        return pool

    @property
    def pool_size(self) -> int:
        return len(self._pool)

    def _pick(self, now: float) -> Caller | None:
        if not self._pool:
            return None
        busy = {c.call for c in self.callers} | self.others()
        for _ in range(40):
            call, level, lk = self._weighted_quick()
            if call in busy:
                continue
            if call in self.worked and not (self.s.doubles and self.rng.random() < 0.06):
                continue
            exch = self.maker.make(call, lk, now / 60.0)
            if exch is None:
                continue
            lo, hi = GAIN[level]
            q = QSB_DB[self.s.qsb]
            c = Caller(call=call, exch=exch,
                          wpm=self.rng.randint(min(self.s.wpm_min, self.s.wpm_max),
                                               max(self.s.wpm_min, self.s.wpm_max)),
                          pitch=600 + self.rng.choice((-1, 1)) * self.rng.uniform(0, 220),
                          gain_db=self.rng.uniform(hi, lo) + lift(self.s.mode),
                          qsb=(self.rng.uniform(0.05, 0.3), q * self.rng.uniform(0.5, 1.0),
                               self.rng.uniform(0, 2 * math.pi)),
                          patience=self.rng.randint(2, 5),
                          twice=self.rng.random() < 0.3,
                          cut=(not self.ssb) and self.s.cut_numbers and self.rng.random() < 0.35)
            if self.ssb:
                self._prepare_voice(c)
            return c
        return None

    def _prepare_voice(self, c: Caller) -> None:
        """SSB: Sprecher wählen und alles, was die Station sagen wird, schon vorab erzeugen."""
        n = self.voices.speakers() if self.voices is not None else 904
        c.voice = self.rng.randrange(max(1, n))
        c.rate = self.rng.uniform(0.92, 1.12)
        c.say_call = ssbvoice.call_text(c.call, c.twice)
        c.say_call2 = ssbvoice.call_text(c.call, True)
        pre = self.rng.choice(("", "", "", "QSL", "thank you"))
        c.say_exch = ssbvoice.exchange_text(f"59 {c.exch}", self.rng, pre)
        c.say_again = ssbvoice.exchange_text(f"{c.exch} {c.exch}", self.rng)
        for t in (c.say_call, c.say_exch, c.say_call2, c.say_again):
            self._request(c, t)

    def _request(self, c: Caller, text: str) -> str:
        key = f"{c.call}|{c.voice}|{text}"
        if self.voices is not None:
            if self.voice_tag:
                try:
                    self.voices.request(key, text, c.voice, c.rate, tag=self.voice_tag)
                    return key
                except TypeError:                       # einfache Stimmen ohne Vorrang
                    pass
            self.voices.request(key, text, c.voice, c.rate)
        return key

    def _duration(self, key: str, text: str, wpm: int) -> float:
        if not self.ssb:
            return cwsynth.duration_s(text, wpm)
        x = self.voices.get(key) if self.voices is not None else None
        return len(x) / cwsynth.RATE if x is not None else ssbvoice.estimate_s(text)

    def _weighted_quick(self):
        """Erst den Kontinent (Anteil × Bandöffnung), dann ein Rufzeichen von dort – sonst
        kämen fast nur US-Stationen (die SCP-Liste hat sehr viele)."""
        if not hasattr(self, "_by_cont"):
            by: dict[str, list] = {}
            for p in self._pool:
                by.setdefault(p[2].cont, []).append(p)
            self._by_cont = by
            self._conts = list(by)
            self._cweights = [(OWN_SHARE if c == self._own_cont else SHARE.get(c, 0.2))
                              * WEIGHT[by[c][0][1]] for c in self._conts]
        cont = self.rng.choices(self._conts, weights=self._cweights)[0]
        return self.rng.choice(self._by_cont[cont])

    # -------------------------------------------------------------- Senden der Stationen
    def _say(self, c: Caller, text: str, at: float) -> float:
        if c.cut:
            text = cwsynth.cut_numbers(text, leading_only=self.rng.random() < 0.5)
        key = self._request(c, text) if self.ssb else ""
        tx = Transmission(c.call, text, c.wpm, c.pitch, c.gain_db, at, c.qsb, key)
        self.planned.append(tx)
        return at + self._duration(key, text, c.wpm)

    def _call_out(self, c: Caller, at: float) -> float:
        if self.ssb:
            return self._say(c, c.say_call, at)
        return self._say(c, f"{c.call} {c.call}" if c.twice else c.call, at)

    def _correct(self, c: Caller, at: float) -> float:
        """Station wiederholt ihr Rufzeichen (falsch oder nur halb verstanden)."""
        return self._say(c, c.say_call2 if self.ssb else f"{c.call} {c.call}", at)

    def _send_exchange(self, c: Caller, at: float, again: bool = False) -> float:
        ex = c.exch
        if self.ssb:
            text = c.say_again if again else c.say_exch
        elif again:
            text = f"{ex} {ex}"
        else:
            pre = self.rng.choice(("", "", "", "R ", "TU "))
            text = f"{pre}5NN {ex}"
        c.state = SENT
        return self._say(c, text, at)

    def _round(self, at: float, new: bool) -> float:
        """Eine Anrufrunde: wer noch ruft, ruft wieder; bei new kommen neue dazu. Wer wartet
        (muted, weil gerade jemand anderes dran ist), ruft erst nach dem QSO wieder."""
        end = at
        if new or self.current is None:
            for c in self.callers:
                c.muted = False
        active = [c for c in self.callers if c.state == CALLING and not c.muted]
        for c in active:
            c.patience -= 1
            if c.patience < 0:
                c.state = GONE
        if new:
            n = self._poisson(ACTIVITY.get(self.s.activity, 1.8) * self.damp)
            for _ in range(n):
                c = self._pick(at)
                if c is not None:
                    self.callers.append(c)
        for c in [c for c in self.callers if c.state == CALLING and not c.muted]:
            end = max(end, self._call_out(c, at + self.rng.uniform(0.1, 1.3)))
        self.callers = [c for c in self.callers if c.state != GONE]
        return end

    def _poisson(self, lam: float) -> int:
        l, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= self.rng.random()
            if p <= l:
                return k
            k += 1

    # -------------------------------------------------------------- dein Senden
    @staticmethod
    def parse(text: str, mycall: str, my_exch: str = "") -> dict:
        toks = [t for t in text.upper().split() if t]
        ex = set(my_exch.upper().split())
        calls, queries = [], []
        for t in toks:
            bare = t.rstrip("?")
            if not bare or bare in KEYWORDS or bare == mycall or t in AGN or bare in ex:
                continue
            if bare.isdigit() or not CALLISH.match(bare):
                continue
            (queries if t.endswith("?") else calls).append(bare)
        return {"cq": "CQ" in toks, "tu": any(t in TU for t in toks),
                "agn": any(t in AGN for t in toks) and not calls and not queries,
                "calls": calls, "queries": queries,
                "exch": any(t in ("5NN", "599", "ENN", "59") for t in toks) or
                bool(ex & set(toks))}

    def on_sent(self, text: str, t_start: float, t_end: float, my_exch: str = "") -> None:
        """Du hast etwas gesendet (Mithörton von t_start bis t_end)."""
        self.started = True
        self.planned = [p for p in self.planned if p.start < t_start]   # wer noch nicht dran
        msg = self.parse(text, self.mycall, my_exch)                   # war, schweigt jetzt
        at = t_end + self.rng.uniform(0.15, 0.6)
        self.waiting_since = None
        live = [c for c in self.callers if c.state in (CALLING, WORKING, SENT)]
        if msg["calls"] or msg["queries"]:
            frag = (msg["calls"] or msg["queries"])[-1]
            exact = [c for c in live if c.call == frag]
            if exact and not msg["queries"]:
                c = exact[0]
                if self.current is not None and self.current is not c and \
                        self.current.state == WORKING:
                    self.current.state = CALLING
                self.current = c
                c.state = WORKING
                end = self._send_exchange(c, at)
                for o in live:
                    if o is not c and o.state == CALLING:
                        o.muted = True
                        if self.s.doubles and self.rng.random() < 0.12:   # ruft trotzdem
                            self._call_out(o, at + self.rng.uniform(0.0, 0.5))
                self._arm(end)
                return
            # halbes oder falsches Rufzeichen: wer passt, gibt sein Rufzeichen
            match = [c for c in live if frag in c.call] if len(frag) <= 3 or msg["queries"] \
                else []
            if not match:
                near = sorted(live, key=lambda c: similar(frag, c.call))
                match = [c for c in near[:1] if similar(frag, c.call) <= max(2, len(frag) // 3)]
            end = at
            for c in match:
                if c.state == CALLING or c is self.current:
                    end = max(end, self._correct(c, at + self.rng.uniform(0.0, 0.4)))
                    if c.state == SENT:
                        c.state = WORKING
            if not match:
                end = self._round(at, new=False)
            self._arm(end)
            return
        cur = self.current
        if msg["agn"]:
            if cur is not None and cur.state in (WORKING, SENT):
                self._arm(self._send_exchange(cur, at, again=True))
            else:
                self._arm(self._round(at, new=False))
            return
        if msg["tu"] or msg["cq"]:
            if cur is not None:
                if cur.state == SENT:
                    cur.state = DONE
                    self.done.append(cur)
                    self.worked.add(cur.call)
                else:
                    cur.state = GONE
                self.callers = [c for c in self.callers if c is not cur]
                self.current = None
            self._arm(self._round(at, new=True))
            return
        if msg["exch"] and cur is not None and cur.state == WORKING:
            self._arm(self._send_exchange(cur, at))
            return
        self._arm(at)

    def _arm(self, end: float) -> None:
        """Nach dem letzten Anruf: wenn du schweigst, rufen sie in 2–4 s noch einmal."""
        self.waiting_since = end

    def abort_own(self, t: float) -> None:
        """Du hast dein Senden mit Esc abgebrochen – Stationen warten wie bisher."""
        self.waiting_since = t

    # -------------------------------------------------------------- Takt
    def tick(self, t: float) -> list[Transmission]:
        """Was jetzt beginnen soll (Zeit des Tonstroms)."""
        if self.waiting_since is not None and t > self.waiting_since + 2.5 and \
                any(c.state == CALLING and not c.muted for c in self.callers):
            # niemand geantwortet – wer noch Geduld hat, ruft wieder
            end = self._round(t, new=False)
            self.waiting_since = end + self.rng.uniform(0.0, 1.5)
        if self.s.qrm and t >= self.qrm_next:
            self.qrm_next = t + self.rng.uniform(25, 70)
            pick = self._weighted_quick() if self._pool else None
            if pick and self.ssb:
                text = "CQ contest, CQ contest, " + ssbvoice.spell(pick[0])
                v = self.rng.randrange(self.voices.speakers() if self.voices else 904)
                key = f"QRM|{v}|{text}"
                if self.voices is not None:
                    self.voices.request(key, text, v, 1.0)
                self.planned.append(Transmission("QRM", text, 0, 0, self.rng.uniform(-28, -18),
                                                 t + 2.0, None, key))
            elif pick:
                self.planned.append(Transmission(
                    "QRM", f"CQ TEST {pick[0]} {pick[0]} TEST",
                    self.rng.randint(22, 34), 600 + self.rng.choice((-1, 1)) *
                    self.rng.uniform(250, 420), self.rng.uniform(-24, -14), t))
        due = [p for p in self.planned if p.start <= t]
        self.planned = [p for p in self.planned if p.start > t]
        return due

    def finished(self, t: float) -> bool:
        return self.s.minutes > 0 and t >= self.s.minutes * 60

    # -------------------------------------------------------------- Auswertung
    def truths(self) -> list[Caller]:
        extra = [c for c in self.callers if c.state == SENT and c not in self.done]
        return self.done + extra

    def evaluate(self, qsos, seconds: float) -> Result:
        """qsos: Einträge mit .call und .exch_r (dein Übungslog)."""
        return evaluate_qsos(self.truths(), qsos, seconds)


def evaluate_qsos(truths, qsos, seconds: float) -> Result:
    """Dein Log gegen das, was die Gegenstationen wirklich gesendet haben (.call, .exch)."""
    res = Result(qsos=len(qsos), seconds=seconds)
    left = list(truths)
    for q in qsos:
        call = (q.call or "").upper()
        hit = next((c for c in left if c.call == call), None)
        if hit is None and left:
            near = min(left, key=lambda c: similar(call, c.call))
            if similar(call, near.call) <= 3:
                hit = near
                res.findings.append(Finding("call", call, near.call, near.call))
        if hit is None:
            res.findings.append(Finding("nil", call, "", call))
            continue
        left.remove(hit)
        if norm_tokens(q.exch_r) != norm_tokens(hit.exch):
            res.findings.append(Finding("exch", (q.exch_r or "").upper(), hit.exch, hit.call))
        elif hit.call == call:
            res.correct += 1
    for c in left:
        res.findings.append(Finding("missed", "", c.exch, c.call))
    return res


def ssb_meaning(text: str, mycall: str) -> str:
    """SSB-Tastentext (mit [CQ], [TU] … und eingesetzten Platzhaltern) → Bedeutung wie in CW,
    z. B. „[CQ] DO2GGH“ → „CQ DO2GGH“, „[AGN]“ → „AGN?“."""
    out = []
    for m in re.finditer(r"\[([A-Za-z0-9]+)\]|(\S+)", text or ""):
        if m.group(1):
            w = m.group(1).upper()
            out.append(mycall if w == "MYCALL" else SSB_WORDS.get(w, w))
        else:
            out.append(m.group(2).upper())
    return " ".join(out)


def spoken_estimate(meaning: str, mycall: str) -> float:
    """Wie lange du ungefähr sprichst (Rufzeichen buchstabiert, Wörter je eins)."""
    words = 0
    for t in meaning.split():
        b = t.rstrip("?")
        if b and b not in KEYWORDS and CALLISH.match(b) and not b.isdigit():
            words += len(b)
        else:
            words += 1 if not b.isdigit() else len(b)
    return 0.3 + 0.38 * words


@dataclass
class _ProbeQso:
    call: str
    band: str
    mode: str = "CW"
    freq: int = 0
    rst_s: str = "599"
    exch_s: str = ""
    rst_r: str = "599"
    exch_r: str = ""
    time: str = ""


# ------------------------------------------------------------------ Verlauf
def history_path() -> Path:
    from .cty import user_cty_path
    return user_cty_path().parent / "practice.json"


def load_history() -> list[dict]:
    try:
        return json.loads(history_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save_result(s: Settings, r: Result, when: datetime | None = None) -> list[dict]:
    hist = load_history()
    hist.append({"date": (when or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M"),
                 "contest": s.contest, "mode": s.mode, "band": s.band, "style": s.style,
                 "minutes": round(r.seconds / 60, 1), "qsos": r.qsos, "correct": r.correct,
                 "errors": r.errors, "rate": r.rate})
    hist = hist[-200:]
    try:
        p = history_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return hist
