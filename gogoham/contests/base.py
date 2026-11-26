"""Grundgerüst für Contest-Regeln und die laufende Punkteberechnung."""

from __future__ import annotations

from ..i18n import tr

from dataclasses import dataclass, field
from typing import Iterable

from ..bands import CONTEST_BANDS, band_label, cabrillo_mode
from ..cty import CtyDB, Lookup


@dataclass
class Station:
    """Eigene Station (aus den Log-Einstellungen)."""
    call: str = ""
    cq_zone: int = 14
    grid: str = ""
    lookup: Lookup | None = None
    state: str = ""          # eigener US-State bzw. kanadische Provinz (nur W/VE)
    power: str = ""          # Leistung für den Austausch (ARRL DX, z. B. "100", "KW")
    itu: str = ""            # eigene ITU-Zone oder Verbandskürzel (IARU HF), leer = Länderdatei
    lic_year: str = ""       # Jahr der ersten Lizenz, zweistellig (EU HF)
    dok: str = ""            # eigener DOK oder „NM“ (DARC-Conteste, ab 0.8.4)
    oblast: str = ""         # eigener Oblast (nur Stationen in Russland, Russian DX)
    iota: str = ""           # eigene IOTA-Referenz, z. B. EU-005 (leer = keine Insel)
    age: str = ""            # Alter des Operators, zweistellig (All Asian; leer = „01“)
    district: str = ""       # eigenes Kürzel im Gastgeberland (Provinz, Bezirk …; ab 0.8.7)
    member: str = ""         # eigene Mitgliedsnummer (AGCW; leer = kein Mitglied; ab 0.8.31)
    pclass: str = ""         # eigene Leistungsklasse (AGCW QRP: VLP/QRP/MP/QRO; ab 0.10.23)
    cat_power: str = ""      # Kategorie Leistung HIGH/LOW/QRP (Stew Perry: Faktor; ab 0.10.31)
    name: str = ""           # Vorname für den Austausch (NAQP; ab 0.10.32)
    cat_operator: str = ""   # SINGLE-OP / MULTI-OP (Sweepstakes: Precedence; ab 0.10.33)
    cat_assisted: str = ""   # ASSISTED / NON-ASSISTED (Sweepstakes: „U“; ab 0.10.33)


@dataclass
class Qso:
    id: int | None = None
    time: str = ""            # UTC, ISO "YYYY-MM-DD HH:MM:SS"
    call: str = ""
    band: str = ""
    mode: str = ""            # Rig-/ADIF-Mode (USB, CW, FT8 …)
    freq: int = 0             # Hz
    rst_s: str = ""
    exch_s: str = ""
    rst_r: str = ""
    exch_r: str = ""
    source: str = "manual"    # manual / wsjtx / import
    # Stationslog mit mehreren Plätzen (ab 0.10): eindeutige Kennung, Platz, Operator
    uid: str = ""
    place: str = ""
    operator: str = ""
    tx: str = ""              # Sendernummer (Multi-OP, ab 0.10.2): "0"/"1", leer = "0"


@dataclass
class QsoEval:
    """Ergebnis der Bewertung eines (geplanten oder geloggten) QSOs."""
    dupe: bool = False
    points: int = 0
    new_mults: list[tuple[str, str]] = field(default_factory=list)  # (Typ, Wert)
    mults: list[tuple[str, str]] = field(default_factory=list)
    lookup: Lookup | None = None
    info: str = ""
    warning: str = ""
    valid: bool = True
    gain: int = 0          # Zuwachs des Gesamtergebnisses durch dieses QSO
    extra_key: str | None = None   # Volta: Land für den Extra-Multi (Format 20)


class Contest:
    """Basisklasse. Unterklassen definieren Punkte, Multis und Austausch."""

    id = "base"
    name = "Basis"
    cabrillo_name = ""
    bands: list[str] = CONTEST_BANDS
    modes: set[str] = {"PH", "CW", "RY", "DG"}      # erlaubte Cabrillo-Modes
    mult_types: list[tuple[str, str]] = []          # (Schlüssel, Anzeige)
    mults_per_band = True
    mult_per: str | None = None   # band / once / mode / band_mode; None = nach mults_per_band
    mult_per_type: dict | None = None  # je Multi eigene Zählweise (Format 18, DIG/BARTG)
    dupe_per_mode = False
    dupe_rule: str | None = None  # „mode“ = einmal je Mode, egal auf welchem Band (DARC 10 m)
    exchange_label = tr("Austausch")
    uses_rst = True
    uses_serial = False
    # Standard-Spalten der Log-Tabelle (siehe gogoham/columns.py); None = Grundauswahl
    columns: list[str] | None = None
    # Regelstand: offizielle Ausschreibung und wann sie zuletzt geprüft wurde (JJJJ-MM)
    rules_url = ""
    rules_checked = ""
    # Termin für den Countdown: letztes volles Wochenende im Monat (siehe schedule.py)
    schedule: dict | None = None
    # Höchstbetriebszeit für Single-OP in Stunden (WPX: 36), None = keine Grenze
    max_hours_single: int | None = None
    max_hours_classic: int | None = None
    # Multi-Gewichtung je Band (WAE: 80 m ×4, 40 m ×3, sonst ×2), None = alle ×1
    mult_factor: dict | None = None
    power_factor: dict | None = None   # Endergebnis × Faktor je Leistungsklasse (Stew Perry)
    # QTC (WAE): {"max_per_station": 10, "points": 1}, None = keine QTCs
    qtc: dict | None = None
    # Multi-OP-Regeln (ab 0.10.2, Format 12): {"MS": {...}, "M2": {...}, "MM": {...}}
    multi: dict | None = None
    # Wertung: „points_x_mults“ (Punkte × Multis) oder „points_sum“ (nur Punkte, UKW)
    score_rule = "points_x_mults"
    serial_per_band = False       # UKW: laufende Nummer beginnt auf jedem Band bei 001

    def __init__(self, cty: CtyDB | None, station: Station) -> None:
        self.cty = cty
        self.station = station
        if cty and station.call and station.lookup is None:
            station.lookup = cty.lookup(station.call)

    # --- von Unterklassen zu überschreiben -----------------------------------
    def sent_exchange(self, serial: int) -> str:
        return ""

    def default_rcvd_exchange(self, lk: Lookup | None, call: str = "") -> str:
        return ""

    def expected_kind(self, lk: Lookup | None) -> str | None:
        """Art des Austauschs, den die Gegenstation sendet (cq_zone, serial …)."""
        return getattr(self, "exchange_kind", None)

    def contact_problem(self, q: Qso, lk: Lookup | None) -> str | None:
        """Grund, warum ein QSO nach den Regeln nicht zählt (z. B. DX–DX im ARRL DX)."""
        return None

    def validate_exchange(self, exch: str, lk: Lookup | None = None) -> str | None:
        """Fehlermeldung oder None, wenn der empfangene Austausch passt."""
        return None

    def qso_points(self, q: Qso, lk: Lookup | None) -> int:
        return 1

    def qso_mults(self, q: Qso, lk: Lookup | None) -> list[tuple[str, str]]:
        return []

    def describe(self, q: Qso, lk: Lookup | None) -> str:
        """Kurzinfo zur Gegenstation, z. B. Land und Kontinent."""
        if lk is None:
            return tr("Unbekanntes Präfix")
        if lk.maritime:
            return "Maritime Mobile"
        return f"{lk.name} · {lk.cont} · CQ {lk.cq} · ITU {lk.itu}"

    def notes(self, q: Qso, lk: Lookup | None) -> list[str]:
        """Zusätzliche Hinweise für die Eingabezeile (z. B. ungewöhnliche Zone)."""
        return []

    def needs_country(self) -> bool:
        return True

    def score_factor(self) -> float:
        """Faktor fürs Endergebnis nach eigener Leistungsklasse (Stew Perry: LOW ×1,5, QRP ×3)."""
        f = self.power_factor
        if not f:
            return 1
        return f.get((self.station.cat_power or "HIGH").upper(), 1)

    def mult_weight(self, band: str) -> int:
        """Wie oft ein Multi auf diesem Band zählt (WAE: 80 m ×4, 40 m ×3, sonst ×2)."""
        f = self.mult_factor
        if not f:
            return 1
        return int(f.get(band, f.get("default", 1)))

    def qtc_both_ways(self) -> bool:
        """WAE RTTY: jede Station darf QTCs geben und empfangen (nur zwischen Kontinenten)."""
        return bool(self.qtc) and bool(self.qtc.get("both_ways"))

    def qtc_receiving(self) -> bool:
        """Darf die eigene Station QTCs empfangen? (WAE: nur Stationen in Europa)"""
        me = self.station.lookup
        return bool(self.qtc) and (self.qtc_both_ways() or me is None or me.cont == "EU")

    def qtc_other_continent_problem(self, lk: Lookup | None) -> str | None:
        """RTTY: QTCs nur mit Stationen auf einem anderen Kontinent."""
        me = self.station.lookup
        if lk is None or me is None:
            return None
        if lk.maritime or lk.cont == me.cont:
            return tr("QTCs gibt es nur mit Stationen auf einem anderen Kontinent")
        return None

    def qtc_sender_problem(self, lk: Lookup | None) -> str | None:
        """Warum diese Station keine QTCs geben darf (None = sie darf)."""
        if lk is None:
            return None
        if self.qtc_both_ways():
            return self.qtc_other_continent_problem(lk)
        if lk.maritime or lk.cont == "EU":
            return tr("QTCs kommen nur von Stationen außerhalb Europas")
        return None

    # --- allgemein -----------------------------------------------------------
    def lookup(self, call: str) -> Lookup | None:
        return self.cty.lookup(call) if self.cty else None

    def dupe_key(self, q: Qso) -> tuple:
        if self.dupe_rule == "band_opmode":              # Format 15: SSB und FM getrennt
            from ..bands import op_mode
            return (q.call.upper(), q.band, op_mode(q.mode))
        if self.dupe_rule == "band_mode_county":         # Format 21: QSO-Party, je County
            m = cabrillo_mode(q.mode)
            counties = getattr(self, "party_counties", lambda _e: [])(q.exch_r)
            return (q.call.upper(), q.band, "DG" if m == "RY" else m, tuple(sorted(counties)))
        if self.dupe_rule == "once":                     # Format 19: nur einmal (Sweepstakes)
            return (q.call.upper(),)
        if self.dupe_rule == "mode":
            return (q.call.upper(), cabrillo_mode(q.mode))
        if self.dupe_per_mode:
            return (q.call.upper(), q.band, cabrillo_mode(q.mode))
        return (q.call.upper(), q.band)

    def mode_ok(self, q: Qso) -> bool:
        return cabrillo_mode(q.mode) in self.modes

    def band_ok(self, q: Qso) -> bool:
        return q.band in self.bands


def bucket_band(b: str) -> str:
    """Band aus einem Multi-Fach („20“ oder „20:CW“ bei Zählung je Band und Mode)."""
    return b.split(":", 1)[0]


class Scorer:
    """Hält den aktuellen Contest-Stand: Dupes, Multis, Punkte je Band."""

    def __init__(self, contest: Contest) -> None:
        self.contest = contest
        self.reset()

    def reset(self) -> None:
        self.worked: dict[tuple, int] = {}                  # dupe_key -> qso.id
        self.mults: dict[tuple, set[str]] = {}              # (typ, band|"ALL") -> Werte
        self.band_stats: dict[str, dict] = {}
        self.total_qsos = 0
        self.total_points = 0
        self.valid_qsos = 0                                 # gültige QSOs (Volta-Formel)
        self.xbands: dict[str, set[str]] = {}               # Volta: Extra-Multi -> Bänder
        self.mobiles: dict[str, set[str]] = {}              # Texas: Mobilstation -> Countys
        self.bonus_hits: set[tuple[str, str]] = set()       # NCQP/Salmon Run: Bonusstationen
        self.letters: dict[str, int] = {}                   # St. Patrick's: Suffix-Buchstaben
        self.dupes = 0
        self.evals: dict[int, QsoEval] = {}
        self.calls: dict[str, set[str]] = {}                # Rufzeichen -> Bänder
        # Freies Log (0.10.18): Rufzeichen -> [(Zeit, Band, Mode, id)] für „schon gearbeitet“
        self.history: dict[str, list[tuple[str, str, str, int | None]]] = {}
        # QTC-Punkte bleiben beim Neubewerten der QSOs erhalten (siehe set_qtcs)
        self.qtc_points = getattr(self, "qtc_points", 0)

    def set_qtcs(self, count: int) -> None:
        """Anzahl der empfangenen QTCs (WAE) – jedes zählt wie ein QSO-Punkt."""
        q = self.contest.qtc or {}
        self.qtc_points = count * int(q.get("points", 1)) if q else 0

    def _mult_bucket(self, mtype: str, q: Qso) -> tuple:
        per = (getattr(self.contest, "mult_per_type", None) or {}).get(mtype) \
            or getattr(self.contest, "mult_per", None) \
            or ("band" if self.contest.mults_per_band else "once")
        if per == "mode":
            return (mtype, cabrillo_mode(q.mode))          # ARRL 10 m: einmal je Mode
        if per == "band_mode":                            # DARC: je Band und Mode
            return (mtype, f"{q.band}:{cabrillo_mode(q.mode)}")
        return (mtype, q.band if per == "band" else "ALL")

    def evaluate(self, q: Qso, commit: bool = False) -> QsoEval:
        c = self.contest
        ev = QsoEval()
        call = q.call.strip().upper()
        if not call:
            ev.valid = False
            return ev
        lk = c.lookup(call)
        ev.lookup = lk
        ev.info = c.describe(q, lk)
        if getattr(c, "free", False):
            from .freelog import worked_text
            seen = [h[:3] for h in self.history.get(call, []) if h[3] is None or h[3] != q.id]
            ev.info = " · ".join(x for x in (ev.info, worked_text(seen)) if x)

        key = c.dupe_key(q)
        if key in self.worked and self.worked[key] != q.id:
            ev.dupe = True
        if not c.band_ok(q):
            ev.warning = tr("{band_label} zählt in diesem Contest nicht", band_label=band_label(q.band))
            ev.valid = False
        elif not c.mode_ok(q):
            ev.warning = (tr("Mode {mode} passt nicht zum Contest (erlaubt: {join})", mode=q.mode, join=', '.join(sorted(c.modes))))
            ev.valid = False
        elif lk is None and c.needs_country():
            ev.warning = tr("Land unbekannt – Präfix prüfen")
        if ev.valid:
            problem = c.contact_problem(q, lk)
            if problem:
                ev.warning = problem[0].upper() + problem[1:]
                ev.valid = False

        if ev.valid:
            ev.mults = c.qso_mults(q, lk)       # auch bei Dupes – für die Infobox
        if ev.valid and not ev.dupe:
            ev.points = c.qso_points(q, lk)
            for mtype, val in ev.mults:
                if val and val not in self.mults.get(self._mult_bucket(mtype, q), set()):
                    ev.new_mults.append((mtype, val))
            w = self.contest.mult_weight(q.band)
            rule = self.contest.score_rule
            raw = self._raw_score()                  # ohne Boni (Texas, NCQP …) – die kommen extra
            ev.extra_key = self._extra_key(q, ev)
            nx = 1 if ev.extra_key and q.band not in self.xbands.get(ev.extra_key, set()) \
                and len(self.xbands.get(ev.extra_key, ())) + 1 == self.contest.extra_mult["min_bands"] else 0
            if rule == "points_plus_bonus":          # RSGB 1.8 MHz: Punkte + Bonus je Multi
                gain = ev.points + self.contest.mult_bonus * len(ev.new_mults)
            elif rule == "qsos_x_points_x_mults":    # Volta: QSOs × Punkte × Multis
                gain = ((self.valid_qsos + 1) * (self.total_points + ev.points)
                        * (self.weighted_mults() + self.extra_mults() + w * len(ev.new_mults) + nx)
                        - raw)
            elif rule == "points_sum":
                gain = ev.points
            elif rule == "band_sum":                 # QRP-Party: je Band rechnen
                bp, bm = self._band_pm(q.band)
                gain = (bp + ev.points) * (bm + len(ev.new_mults)) - bp * bm
            elif rule == "points_x_mults_or_points":
                m = self.weighted_mults() + w * len(ev.new_mults)
                pts = self.total_points + self.qtc_points + ev.points
                gain = (pts * m if m else pts) - raw
            elif rule == "points_x_mults_x_cont":   # BARTG: Punkte × Multis × Kontinente
                nc = sum(1 for t, _v in ev.new_mults if t == "cont")
                gain = ((self.total_points + ev.points)
                        * (self.mult_count() - self.mult_count("cont") + len(ev.new_mults) - nc)
                        * (self.mult_count("cont") + nc)) - raw
            else:
                gain = ((self.total_points + self.qtc_points + ev.points)
                        * (self.weighted_mults() + w * len(ev.new_mults)) - raw)
            total = self.raw_score
            gain += self._mobile_gain(q) + self._bonus_gain(q)
            ev.gain = self._factored(total + gain) - self._factored(total)

        if commit:
            self._commit(q, ev)
        return ev

    def _commit(self, q: Qso, ev: QsoEval) -> None:
        bs = self.band_stats.setdefault(q.band, {"qsos": 0, "points": 0, "dupes": 0,
                                                 "mults": {}})
        self.calls.setdefault(q.call.upper(), set()).add(q.band)
        self.history.setdefault(q.call.upper(), []).append((q.time, q.band, q.mode, q.id))
        if ev.dupe:
            bs["dupes"] += 1
            self.dupes += 1
        else:
            self.worked[self.contest.dupe_key(q)] = q.id
            bs["qsos"] += 1
            bs["points"] += ev.points
            self.total_qsos += 1
            self.total_points += ev.points
            if ev.valid:
                self.valid_qsos += 1
            if ev.valid:
                bk = getattr(self.contest, "bonus_call_key", lambda _q: None)(q)
                if bk:
                    self.bonus_hits.add(bk)
                if getattr(self.contest, "suffix_bonus", None):
                    ch = self._suffix_letter(q)
                    if ch:
                        self.letters[ch] = self.letters.get(ch, 0) + 1
            mk = getattr(self.contest, "mobile_key", lambda _q: None)(q) if ev.valid else None
            if mk and mk[1]:
                self.mobiles.setdefault(mk[0], set()).update(mk[1])
            xk = getattr(ev, "extra_key", None)
            if xk:
                self.xbands.setdefault(xk, set()).add(q.band)
            for mtype, val in ev.new_mults:
                self.mults.setdefault(self._mult_bucket(mtype, q), set()).add(val)
                bs["mults"][mtype] = bs["mults"].get(mtype, 0) + 1
        if q.id is not None:
            self.evals[q.id] = ev

    def rebuild(self, qsos: Iterable[Qso]) -> None:
        self.reset()
        for q in qsos:
            self.evaluate(q, commit=True)

    # --- Auswertung ----------------------------------------------------------
    def _extra_key(self, q: Qso, ev: QsoEval) -> str | None:
        f = getattr(self.contest, "extra_mult_key", None)
        if not f or not getattr(self.contest, "extra_mult", None):
            return None
        return f(q, ev.lookup, ev.mults)

    def mobile_bonus(self) -> int:
        """Texas: Bonus für jede Mobilstation, je volle „counties“ verschiedene Countys."""
        mb = getattr(self.contest, "mobile_bonus", None)
        if not mb:
            return 0
        return sum(mb["points"] * (len(c) // mb["counties"]) for c in self.mobiles.values())

    @staticmethod
    def _suffix_letter(q: Qso) -> str:
        from .rulebased import call_suffix
        return call_suffix(q.call)[:1]

    def call_bonus(self) -> int:
        """NCQP, Salmon Run: Bonus für Bonusstationen; St. Patrick's: Wörter aus Suffixen."""
        c = self.contest
        v = c.bonus_value(self.bonus_hits) if getattr(c, "bonus_calls", None) else 0
        if getattr(c, "suffix_bonus", None):
            v += c.suffix_value(self.letters)
        return v

    def _bonus_gain(self, q: Qso) -> int:
        c = self.contest
        v = 0
        if getattr(c, "bonus_calls", None):
            bk = c.bonus_call_key(q)
            if bk and bk not in self.bonus_hits:
                v += c.bonus_value(self.bonus_hits | {bk}) - c.bonus_value(self.bonus_hits)
        if getattr(c, "suffix_bonus", None):
            ch = self._suffix_letter(q)
            if ch:
                new = dict(self.letters)
                new[ch] = new.get(ch, 0) + 1
                v += c.suffix_value(new) - c.suffix_value(self.letters)
        return v

    def _mobile_gain(self, q: Qso) -> int:
        mb = getattr(self.contest, "mobile_bonus", None)
        mk = getattr(self.contest, "mobile_key", lambda _q: None)(q) if mb else None
        if not mk or not mk[1]:
            return 0
        old = self.mobiles.get(mk[0], set())
        new = old | set(mk[1])
        return mb["points"] * (len(new) // mb["counties"] - len(old) // mb["counties"])

    def extra_mults(self) -> int:
        """Volta: Länder anderer Kontinente auf mindestens „min_bands“ Bändern."""
        xm = getattr(self.contest, "extra_mult", None)
        if not xm:
            return 0
        return sum(1 for b in self.xbands.values() if len(b) >= xm["min_bands"])

    def mult_count(self, mtype: str | None = None) -> int:
        n = 0
        for (t, _b), vals in self.mults.items():
            if mtype is None or t == mtype:
                n += len(vals)
        return n

    def weighted_mults(self, mtype: str | None = None) -> int:
        """Summe der Multis mit Band-Gewichtung (ohne Gewichtung = mult_count())."""
        if not self.contest.mult_factor:
            return self.mult_count(mtype)
        return sum(len(vals) * self.contest.mult_weight(bucket_band(b))
                   for (t, b), vals in self.mults.items() if mtype is None or t == mtype)

    def _band_pm(self, band: str) -> tuple[int, int]:
        """Punkte und Multis eines Bandes (für „band_sum“)."""
        bs = self.band_stats.get(band)
        if not bs:
            return 0, 0
        return bs["points"], sum(bs["mults"].values())

    def _factored(self, raw: int) -> int:
        """Ergebnis mit Leistungsfaktor (Stew Perry), kaufmännisch gerundet."""
        f = self.contest.score_factor()
        return raw if f == 1 else int(raw * f + 0.5)

    @property
    def score(self) -> int:
        return self._factored(self.raw_score)

    @property
    def raw_score(self) -> int:
        """Ergebnis ohne Leistungsfaktor (mit dem Bonus der Mobilstationen, Texas)."""
        return self._raw_score() + self.mobile_bonus() + self.call_bonus()

    def _raw_score(self) -> int:
        rule = self.contest.score_rule
        if rule == "points_sum":
            return self.total_points + self.qtc_points
        if rule == "band_sum":                       # Summe der Bandergebnisse
            return sum(p * m for p, m in (self._band_pm(b) for b in self.band_stats))
        pts = self.total_points + self.qtc_points
        if rule == "points_plus_bonus":              # RSGB 1.8 MHz: Punkte + Bonus je Multi
            return pts + self.contest.mult_bonus * self.mult_count()
        if rule == "qsos_x_points_x_mults":          # Volta: QSOs × Punkte × Multis
            return self.valid_qsos * pts * (self.weighted_mults() + self.extra_mults())
        if rule == "points_x_mults_x_cont":          # BARTG: Kontinente als eigener Faktor
            return pts * (self.mult_count() - self.mult_count("cont")) * self.mult_count("cont")
        if rule == "points_x_mults_or_points":       # Frankencontest: ohne Multi die Punkte
            m = self.weighted_mults()
            return pts * m if m else pts
        return pts * self.weighted_mults()

    def worked_bands(self, call: str) -> set[str]:
        return self.calls.get(call.upper(), set())
