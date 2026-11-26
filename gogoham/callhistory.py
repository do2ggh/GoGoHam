"""Call-History: bekannte feste Angaben von Stationen (Zone, Locator, DOK, Name …).

Seit 0.9.1 schreibt sich die Call-History selbst: Jedes geloggte QSO lernt die festen
Teile des empfangenen Austauschs (keine laufenden Nummern, keine Rapporte) und speichert
sie dauerhaft in ~/.local/share/gogoham/callhistory/gelernt.sqlite – auch wenn das Log
später gelöscht wird. Alte Logs (Cabrillo oder GoGoHam) lassen sich nachträglich einlesen.

Quellen (die höhere gewinnt):
1. gelernte Angaben (eigene QSOs, eingelesene Logs, von Hand geändert) – der neueste
   Eintrag gewinnt, damit ein einmaliger Tippfehler nicht hängen bleibt,
2. importierte Call-History-Dateien im N1MM-Format (Kopfzeile '!!Order!!,Call,…'),
3. der mitgelieferte Grundstock (gogoham/assets/callhistory-base.csv).
"""

from __future__ import annotations

from .i18n import tr

import csv
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .locator import is_grid, is_grid6, normalize

BASE_FILE = Path(__file__).parent / "assets" / "callhistory-base.csv"
LEARNED_NAME = "gelernt.sqlite"

# Rang der Quellen: höher gewinnt (bei gleichem Rang der neuere Eintrag)
RANK_BASE, RANK_FILE, RANK_OWN = 0, 1, 2
SRC_MANUAL = "manual"

# Spaltennamen im N1MM-Format -> unsere Schlüssel
_N1MM_FIELDS = {"CALL": "call", "CQZONE": "zone", "GRIDSQUARE": "grid", "GRID": "grid",
                "LOC1": "grid", "NAME": "name", "ITUZONE": "itu", "DOK": "dok",
                "STATE": "state", "LICYEAR": "lic_year"}

KEYS = ("zone", "itu", "iaru", "grid", "dok", "name", "state", "province", "xe_state",
        "oblast", "district", "lic_year", "age", "member", "iota")


def key_label(key: str) -> str:
    """Angabe für die Anzeige (Call-History-Fenster)."""
    labels = {"zone": tr("CQ-Zone"), "itu": tr("ITU-Zone"), "iaru": tr("Verband"),
              "grid": tr("Locator"), "dok": tr("DOK"), "name": tr("Name"),
              "state": tr("US-State"), "province": tr("Provinz"),
              "xe_state": tr("Mexikanischer State"), "oblast": tr("Oblast"),
              "district": tr("Bezirk"), "lic_year": tr("Lizenzjahr"), "age": tr("Alter"),
              "member": tr("Mitgliedsnummer"), "iota": tr("IOTA")}
    return labels.get(key, key)


def source_label(src: str) -> str:
    if src == SRC_MANUAL:
        return tr("von Hand")
    if src == "base":
        return tr("Grundstock")
    from .contests import CONTESTS
    cls = CONTESTS.get(src)
    return cls.name if cls else src


def history_dir() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "gogoham" / "callhistory"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------ feste Teile finden
def extract(kind: str | None, exch: str, host: dict | None = None) -> list[tuple[str, str]]:
    """Feste Angaben aus dem empfangenen Austausch: [(Schlüssel, Wert), …].

    Laufende Nummern, Rapporte und die Leistung ändern sich – die werden nie gelernt."""
    from .contests import rulebased as rb
    from . import dok as dokmod, regions
    e = (exch or "").strip().upper()
    if not kind or not e:
        return []
    out: list[tuple[str, str]] = []

    def num(lo: int, hi: int, key: str, s: str) -> None:
        if s.isdigit() and lo <= int(s) <= hi:
            out.append((key, str(int(s))))

    if kind == "cq_zone":
        num(1, 40, "zone", e)
    elif kind == "itu_zone":
        num(1, 90, "itu", e)
    elif kind == "iaru":
        if e.isdigit():
            num(1, 90, "itu", e)
        elif re.fullmatch(r"[A-Z][A-Z0-9]{1,5}", e):
            out.append(("iaru", e))
    elif kind in ("state", "province", "xe_state", "oblast"):
        f = {"state": regions.normalize_state, "province": regions.normalize_province,
             "xe_state": regions.normalize_xe_state, "oblast": regions.normalize_oblast}[kind]
        v = f(e)
        if v:
            out.append((kind, v))
    elif kind in ("district", "serial_district"):
        code = e if kind == "district" else rb.split_serial_dok(e)[1]
        v = rb.normalize_district(code, host)
        if v:
            out.append(("district", v))
    elif kind in ("dok", "serial_dok"):
        d = dokmod.normalize(e if kind == "dok" else rb.split_serial_dok(e)[1])
        if d and d != "NM" and not dokmod.form_error(d):
            out.append(("dok", d))
    elif kind == "grid4":
        if is_grid(e):
            out.append(("grid", normalize(e)))
    elif kind == "serial_grid6":
        g = rb.split_serial_grid(e)[1]
        if is_grid6(g):
            out.append(("grid", g))
    elif kind in ("lic_year", "age"):
        if re.fullmatch(r"\d\d", e):
            out.append((kind, e))
    elif kind == "serial_member":
        m = rb.split_serial_member(e)[1]
        if m.isdigit():
            out.append(("member", m))
    elif kind == "serial_iota":
        ref = rb.split_serial_iota(e)[1]
        if ref and ref != "?":
            out.append(("iota", ref))
    return out


def _contest_for(cid: str, cty=None):
    from .contests import CONTESTS, Station
    cls = CONTESTS.get(cid)
    return cls(cty, Station()) if cls else None


# ------------------------------------------------------------ Datenspeicher
class LearnedStore:
    """Dauerhafte Datei mit allem Gelernten – eine Zeile je QSO und Angabe."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("CREATE TABLE IF NOT EXISTS learned (call TEXT NOT NULL, "
                          "key TEXT NOT NULL, value TEXT NOT NULL, time TEXT NOT NULL, "
                          "source TEXT NOT NULL DEFAULT '', PRIMARY KEY (call, key, time))")
        self.conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.conn.commit()

    def flag(self, key: str) -> bool:
        r = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return bool(r and r[0] == "1")

    def set_flag(self, key: str, on: bool = True) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, "1" if on else "0"))
        self.conn.commit()

    def add(self, rows: list[tuple[str, str, str, str, str]]) -> None:
        """rows: (call, key, value, time, source); gleiche Station+Angabe+Zeit wird ersetzt."""
        if rows:
            self.conn.executemany("INSERT OR REPLACE INTO learned VALUES (?, ?, ?, ?, ?)", rows)
            self.conn.commit()

    def forget_qso(self, call: str, time: str) -> None:
        self.conn.execute("DELETE FROM learned WHERE call = ? AND time = ? AND source != ?",
                          (call.upper(), time, SRC_MANUAL))
        self.conn.commit()

    def rows(self, call: str | None = None):
        if call:
            return self.conn.execute("SELECT call, key, value, time, source FROM learned "
                                     "WHERE call = ? ORDER BY time", (call,)).fetchall()
        return self.conn.execute("SELECT call, key, value, time, source FROM learned "
                                 "ORDER BY time").fetchall()

    def close(self) -> None:
        self.conn.close()


@dataclass
class Entry:
    zone: str = ""
    grid: str = ""
    name: str = ""
    source: str = ""
    dok: str = ""
    # alle Angaben: Schlüssel -> (Wert, Zeit, Quelle)
    values: dict[str, tuple[str, str, str]] = field(default_factory=dict)

    def value(self, key: str) -> str:
        v = self.values.get(key)
        return v[0] if v else ""


@dataclass
class CallHistory:
    entries: dict[str, Entry] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    store: LearnedStore | None = None
    # (call, key) -> (Rang, Zeit) des gültigen Werts
    _rank: dict[tuple[str, str], tuple[int, str]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.entries)

    def get(self, call: str) -> Entry | None:
        return self.entries.get((call or "").strip().upper())

    def calls(self) -> list[str]:
        return sorted(self.entries)

    # ------------------------------------------------------------ Grundbaustein
    def _put(self, call: str, key: str, value: str, rank: int, time: str = "",
             source: str = "") -> None:
        """Wert übernehmen, wenn er mindestens so wichtig und so neu ist wie der alte.
        Ein leerer Wert (von Hand „vergessen“) löscht die Angabe."""
        call = call.strip().upper()
        if not call or not key:
            return
        old = self._rank.get((call, key))
        if old is not None and (rank, time) < old:
            return
        self._rank[(call, key)] = (rank, time)
        e = self.entries.setdefault(call, Entry(source=source))
        if value:
            e.values[key] = (value, time, source)
        else:
            e.values.pop(key, None)
        e.zone, e.grid, e.name, e.dok = (e.value("zone"), e.value("grid"), e.value("name"),
                                         e.value("dok"))
        if value and key == "zone":
            e.source = source
        if not e.values:
            del self.entries[call]

    def _merge(self, call: str, zone: str = "", grid: str = "", name: str = "",
               source: str = "", override: bool = False, dok: str = "") -> None:
        """Angaben aus einer Call-History-Datei (oder einem Test) übernehmen."""
        rank = RANK_OWN if override else RANK_FILE
        zone = zone.strip()
        if zone.isdigit() and 1 <= int(zone) <= 40:
            self._put(call, "zone", str(int(zone)), rank, "", source)
        grid = grid.strip().upper()
        if is_grid(grid):
            self._put(call, "grid", grid, rank, "", source)
        if name.strip():
            self._put(call, "name", name.strip(), rank, "", source)
        for key, v in extract("dok", dok):
            self._put(call, key, v, rank, "", source)

    # ------------------------------------------------------------ Vorschläge
    def suggest(self, call: str, kind: str | None, year: int | None = None) -> tuple[str, str]:
        """Vorschlag für den Austausch dieser Art: (Wert, Schlüssel) oder ("", "")."""
        e = self.get(call)
        if e is None or not kind:
            return "", ""
        if kind == "cq_zone" and e.value("zone"):
            return f"{int(e.value('zone')):02d}", "zone"
        if kind == "itu_zone" and e.value("itu"):
            return f"{int(e.value('itu')):02d}", "itu"
        if kind == "iaru":
            cand = [(e.values[k][1], k) for k in ("itu", "iaru") if k in e.values]
            if not cand:
                return "", ""
            k = max(cand)[1]
            v = e.value(k)
            return (f"{int(v):02d}" if k == "itu" else v), k
        if kind == "grid4" and e.value("grid"):
            return e.value("grid")[:4], "grid"
        if kind == "serial_grid6" and is_grid6(e.value("grid")):
            return e.value("grid"), "grid"
        if kind == "age" and e.value("age"):
            v, t, _src = e.values["age"]       # Alter: die Jahre seit dem QSO dazuzählen
            year = year or datetime.now(timezone.utc).year
            if t[:4].isdigit():
                v = str(min(99, int(v) + max(0, year - int(t[:4]))))
            return v, "age"
        key = {"dok": "dok", "serial_dok": "dok", "state": "state", "province": "province",
               "xe_state": "xe_state", "oblast": "oblast", "district": "district",
               "serial_district": "district", "lic_year": "lic_year",
               "serial_member": "member", "serial_iota": "iota"}.get(kind)
        if key and e.value(key):
            return e.value(key), key
        return "", ""

    # ------------------------------------------------------------ lernen
    def _learn_rows(self, contest, call: str, exch: str, time: str,
                    source: str) -> list[tuple[str, str, str, str, str]]:
        call = (call or "").strip().upper()
        if not call or contest is None or getattr(contest, "free", False):
            return []                             # freies Log: Bemerkungen nie lernen
        lk = contest.lookup(call) if getattr(contest, "cty", None) else None
        kind = contest.expected_kind(lk)
        host = getattr(contest, "host", None)
        return [(call, k, v, time, source) for k, v in extract(kind, exch, host)]

    def _apply(self, rows, write: bool = True) -> int:
        for call, k, v, t, src in rows:
            self._put(call, k, v, RANK_OWN, t, src)
        if write and self.store is not None:
            self.store.add(list(rows))
        return len(rows)

    def learn_qso(self, contest, call: str, exch: str, time: str | None = None,
                  source: str = "") -> int:
        """Während des Contests gleich mitlernen (contest: Contest-Objekt oder Kennung)."""
        if isinstance(contest, str):
            src = source or contest
            contest = _contest_for(contest)
        else:
            src = source or getattr(contest, "id", "")
        return self._apply(self._learn_rows(contest, call, exch, time or _now(), src))

    def forget_qso(self, call: str, time: str) -> None:
        """QSO gelöscht oder geändert: was es gelehrt hat, wieder vergessen."""
        if self.store is None:
            return
        self.store.forget_qso(call, time)
        self.reload_learned(call)

    def reload_learned(self, call: str | None = None) -> None:
        """Gelernte Angaben neu einlesen – alle oder nur die einer Station."""
        if self.store is None:
            return
        if call:
            call = call.strip().upper()
            e = self.entries.get(call)
            if e is not None:                      # Gelerntes weg, Datei/Grundstock neu
                for k in list(e.values):
                    if self._rank.get((call, k), (0, ""))[0] == RANK_OWN:
                        del self._rank[(call, k)]
                        e.values.pop(k)
                if not e.values:
                    del self.entries[call]
            for c, k, v, t in (_base_rows() if self.base_enabled() else []):
                if c == call:
                    self._put(c, k, v, RANK_BASE, t, "base")
            for f in self.files:
                p = history_dir() / f
                if p.is_file():
                    self.load_n1mm(p, only=call, remember=False)
        self._apply(self.store.rows(call), write=False)

    def set_value(self, call: str, key: str, value: str) -> None:
        """Von Hand ändern („“ = vergessen) – gilt, bis ein neueres QSO etwas anderes lehrt."""
        call = call.strip().upper()
        value = value.strip() if key == "name" else value.strip().upper()
        row = (call, key, value, _now(), SRC_MANUAL)
        self._put(call, key, value, RANK_OWN, row[3], SRC_MANUAL)
        if self.store is not None:
            self.store.add([row])

    def learn_from_logs(self, folder: str | Path, skip: str | Path | None = None,
                        cty=None) -> int:
        """Alle GoGoHam-Logs im Ordner lernen (ohne Unterordner wie „Übung“)."""
        folder = Path(folder)
        n = 0
        if not folder.is_dir():
            return 0
        for f in sorted(folder.glob("*.ggh")):
            if skip and Path(skip).resolve() == f.resolve():
                continue
            n += self.learn_ggh(f, cty)[0]
        return n

    def learn_ggh(self, path: str | Path, cty=None) -> tuple[int, int, str]:
        """GoGoHam-Log lernen: (QSOs, gelernte Angaben, Contest-Kennung)."""
        from .db import read_only
        try:
            with read_only(path) as conn:          # hinterlässt keine -wal/-shm (0.10.7.2)
                meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
                rows = conn.execute("SELECT call, exch_r, time FROM qso ORDER BY time").fetchall()
        except sqlite3.DatabaseError:
            return 0, 0, ""
        cid = meta.get("contest", "")
        contest = None
        if meta.get("rules_json"):
            from .contests import class_from_log, Station
            cls, _hint = class_from_log(meta)
            contest = cls(cty, Station()) if cls else None
        if contest is None:
            contest = _contest_for(cid, cty)
        out = []
        for call, exch, time in rows:
            out += self._learn_rows(contest, call, exch or "", time or "", cid)
        return len(rows), self._apply(out), cid

    def learn_cabrillo(self, path: str | Path, cty=None) -> tuple[int, int, str]:
        """Cabrillo-Log lernen: (QSOs, gelernte Angaben, Contest-Name).
        Aus dem Kopf (Name, Adresse …) wird nichts übernommen."""
        qsos, contest, cname = read_cabrillo(path, cty)
        if contest is None:
            raise ValueError(tr("Contest „{name}“ ist GoGoHam nicht bekannt – daraus lässt "
                                "sich nichts lernen.", name=cname or "?"))
        out = []
        for call, exch, time in qsos:
            out += self._learn_rows(contest, call, exch, time, contest.id)
        return len(qsos), self._apply(out), cname

    def learn_file(self, path: str | Path, cty=None) -> tuple[int, int, str]:
        """Altes Log lernen – GoGoHam (.ggh) oder Cabrillo."""
        if Path(path).suffix.lower() == ".ggh":
            return self.learn_ggh(path, cty)
        return self.learn_cabrillo(path, cty)

    # ------------------------------------------------------- N1MM-Dateien
    def load_n1mm(self, path: str | Path, only: str | None = None,
                  remember: bool = True) -> int:
        text = Path(path).read_text(encoding="latin-1", errors="replace")
        cols: list[str] = []
        n = 0
        src = Path(path).name
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.upper().startswith("!!ORDER!!"):
                cols = [c.strip().upper() for c in line.split(",")[1:]]
                continue
            if not cols:
                continue
            vals = [v.strip() for v in line.split(",")]
            rec = {}
            for c, v in zip(cols, vals):
                key = _N1MM_FIELDS.get(c)
                if key and v:
                    rec[key] = v
            call = rec.get("call", "").upper()
            if not call or (only and call != only):
                continue
            self._merge(call, zone=rec.get("zone", ""), grid=rec.get("grid", ""),
                        name=rec.get("name", ""), source=src, dok=rec.get("dok", ""))
            for key, kind in (("itu", "itu_zone"), ("state", "state"),
                              ("lic_year", "lic_year")):
                for k, v in extract(kind, rec.get(key, "")):
                    self._put(call, k, v, RANK_FILE, "", src)
            n += 1
        if remember and src not in self.files:
            self.files.append(src)
        return n

    def load_imported(self) -> int:
        d = history_dir()
        n = 0
        if d.is_dir():
            for f in sorted(d.glob("*")):
                if f.is_file() and f.suffix.lower() in (".txt", ".csv"):
                    try:
                        n += self.load_n1mm(f)
                    except OSError:
                        pass
        return n

    def base_enabled(self) -> bool:
        return self.store is None or not self.store.flag("base_off")

    def set_base_enabled(self, on: bool) -> None:
        """Grundstock an/aus (z. B. um nur eigene Logs oder N1MM-Dateien zu nutzen)."""
        if self.store is not None:
            self.store.set_flag("base_off", not on)
        self.reload_all()

    def reload_all(self) -> None:
        """Alles neu einlesen: Grundstock (falls an), N1MM-Dateien, Gelerntes."""
        self.entries.clear()
        self._rank.clear()
        self.files.clear()
        self.load_base()
        self.load_imported()
        self.reload_learned()

    def load_base(self, path: Path | None = None) -> int:
        if not self.base_enabled():
            return 0
        rows = _base_rows(path)
        for c, k, v, t in rows:
            self._put(c, k, v, RANK_BASE, t, "base")
        return len(rows)


# ------------------------------------------------------------ Grundstock
def _base_rows(path: Path | None = None) -> list[tuple[str, str, str, str]]:
    """Mitgelieferter Grundstock: Zeilen „Rufzeichen,Angabe,Wert,Datum“."""
    p = path or BASE_FILE
    if not p.is_file():
        return []
    out = []
    with open(p, encoding="utf-8", newline="") as fh:
        for row in csv.reader(line for line in fh if not line.startswith("#")):
            if len(row) >= 4 and row[0] != "call" and row[1] in KEYS:
                out.append((row[0].strip().upper(), row[1], row[2].strip(), row[3].strip()))
    return out


def write_base(rows, path: Path | None = None) -> int:
    """Grundstock schreiben – je Station und Angabe nur der neueste Wert.
    rows: (Rufzeichen, Angabe, Wert, Zeit)."""
    best: dict[tuple[str, str], tuple[str, str]] = {}
    for c, k, v, t in rows:
        if (c, k) not in best or t >= best[(c, k)][1]:
            best[(c, k)] = (v, t)
    p = path or BASE_FILE
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write("# GoGoHam - Grundstock fuer die Call-History (CC BY 4.0)\n"
                 "# Nur feste Angaben aus Contest-QSOs: Rufzeichen, Angabe, Wert, Datum\n")
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["call", "key", "value", "date"])
        for (c, k), (v, t) in sorted(best.items()):
            w.writerow([c, k, v, t[:10]])
    return len(best)


# ------------------------------------------------------------ Cabrillo lesen
_RST = re.compile(r"^[1-5][1-9][1-9]?[A-Z]?$")


def read_cabrillo(path: str | Path, cty=None):
    """QSO-Zeilen eines Cabrillo-Logs: ([(Rufzeichen, Austausch ohne RST, Zeit)], Contest, Name).

    Die Spalten werden so geteilt, dass gesendeter und empfangener Teil gleich lang sind
    (so schreiben es die Logger); eine Sender-Nummer am Ende wird weggelassen."""
    from .contests import CONTESTS, Station
    text = Path(path).read_text(encoding="latin-1", errors="replace")
    cname, mode, lines = "", "", []
    for line in text.splitlines():
        tag, _, val = line.partition(":")
        tag = tag.strip().upper()
        if tag == "CONTEST":
            cname = val.strip().upper()
        elif tag == "CATEGORY-MODE":
            mode = val.strip().upper()
        elif tag == "QSO":
            lines.append(val.split())
    if not lines and not cname:
        raise ValueError(tr("Das ist kein Cabrillo-Log (keine Zeilen „QSO:“)."))
    contest = None
    cands = [c for c in CONTESTS.values() if (c.cabrillo_name or "").upper() == cname]
    if cands:
        pick = next((c for c in cands if mode and mode.lower() in c.id.split("-")), cands[0])
        contest = pick(cty, Station())
    with_rst = contest is not None and any(
        f.get("field") == "rst" for f in (contest.rules or {}).get("exchange", []))
    out = []
    for tok in lines:
        if len(tok) < 7:
            continue
        date, hhmm, rest = tok[2], tok[3], tok[4:]
        if len(rest) % 2 == 1 and len(rest) > 3 and rest[-1].isdigit() and len(rest[-1]) == 1:
            rest = rest[:-1]                 # Sender-Nummer (0/1) am Zeilenende
        if len(rest) < 2 or len(rest) % 2:
            continue
        k = len(rest) // 2 - 1
        call, rcvd = rest[k + 1], rest[k + 2:]
        if with_rst and rcvd and _RST.match(rcvd[0]):
            rcvd = rcvd[1:]
        exch = " ".join(p for p in rcvd if p.strip("-"))
        t = f"{date} {hhmm[:2]}:{hhmm[2:4]}:00" if len(hhmm) >= 4 else date
        out.append((call.upper(), exch, t))
    return out, contest, cname


def import_file(src: str | Path) -> Path:
    """N1MM-Datei in den Call-History-Ordner übernehmen (vorher prüfen, ob sie lesbar ist)."""
    test = CallHistory()
    if test.load_n1mm(src) == 0:
        raise ValueError(tr("Keine Rufzeichen gefunden – ist das eine Call-History-Datei "
                         "im N1MM-Format (Kopfzeile '!!Order!!,Call,…')?"))
    d = history_dir()
    d.mkdir(parents=True, exist_ok=True)
    target = d / Path(src).name
    shutil.copy2(src, target)
    return target


def open_store() -> LearnedStore | None:
    try:
        return LearnedStore(history_dir() / LEARNED_NAME)
    except (OSError, sqlite3.DatabaseError):
        return None


def build(log_folder: str | Path | None, current_log: str | Path | None = None, cty=None,
          learn_logs: bool = True, store: LearnedStore | None = None) -> CallHistory:
    """Grundstock, importierte Dateien und Gelerntes. Die Logs im Ordner werden nur beim
    allerersten Mal gelernt (ältere Logs); danach lernt jedes QSO von selbst – so kommt
    nichts zurück, was man im Fenster „Call-History“ gelöscht hat."""
    ch = CallHistory(store=store if store is not None else open_store())
    ch.reload_all()
    if learn_logs and log_folder and (ch.store is None or not ch.store.flag("logs_scanned")):
        ch.learn_from_logs(log_folder, skip=None, cty=cty)
        if ch.store is not None:
            ch.store.set_flag("logs_scanned")
    return ch
