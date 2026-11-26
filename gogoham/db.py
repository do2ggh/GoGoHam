"""Speicherung eines Contest-Logs als SQLite-Datei (*.ggh)."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import uuid
from pathlib import Path

from .contests.base import Qso
from .qtc import Qtc

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS qso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT NOT NULL,
    call TEXT NOT NULL,
    band TEXT NOT NULL,
    mode TEXT NOT NULL,
    freq INTEGER NOT NULL DEFAULT 0,
    rst_s TEXT DEFAULT '',
    exch_s TEXT DEFAULT '',
    rst_r TEXT DEFAULT '',
    exch_r TEXT DEFAULT '',
    source TEXT DEFAULT 'manual'
);
CREATE INDEX IF NOT EXISTS qso_call ON qso(call);
CREATE TABLE IF NOT EXISTS callbook (
    call TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    qth TEXT DEFAULT '',
    grid TEXT DEFAULT '',
    source TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS qtc (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT NOT NULL,
    band TEXT NOT NULL,
    mode TEXT NOT NULL,
    freq INTEGER NOT NULL DEFAULT 0,
    sender TEXT NOT NULL,
    series INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    qso_time TEXT NOT NULL,
    qso_call TEXT NOT NULL,
    qso_nr TEXT NOT NULL,
    receiver TEXT NOT NULL DEFAULT '',
    qso_id INTEGER NOT NULL DEFAULT 0,
    uid TEXT NOT NULL DEFAULT ''
);
-- Stationslog (ab 0.10): Hauptplatz führt ein Änderungsbuch, Plätze merken Unversandtes
CREATE TABLE IF NOT EXISTS sync_journal (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    uid TEXT NOT NULL,
    del INTEGER NOT NULL DEFAULT 0,
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS sync_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    msg TEXT NOT NULL
);
-- Nachrichten zwischen den Plätzen (ab 0.10.3) – bleiben auf diesem Rechner, nie im Export
CREATE TABLE IF NOT EXISTS station_chat (
    mid TEXT PRIMARY KEY,
    time TEXT NOT NULL DEFAULT '',
    sender TEXT NOT NULL DEFAULT '',
    recipient TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT ''
);
"""
# Spalten, die erst später dazukamen: (Tabelle, Spalte, Typ) – werden beim Öffnen nachgerüstet
_ADDED_COLUMNS = [
    ("qtc", "receiver", "TEXT NOT NULL DEFAULT ''"),     # 0.9.4
    ("qtc", "qso_id", "INTEGER NOT NULL DEFAULT 0"),     # 0.9.4
    ("qtc", "uid", "TEXT NOT NULL DEFAULT ''"),          # 0.10
    ("qso", "uid", "TEXT DEFAULT ''"),                   # 0.10
    ("qso", "place", "TEXT DEFAULT ''"),                 # 0.10
    ("qso", "operator", "TEXT DEFAULT ''"),              # 0.10
    ("qso", "tx", "TEXT DEFAULT ''"),                    # 0.10.2
]
QTC_FIELDS = ["time", "band", "mode", "freq", "sender", "series", "total", "qso_time",
              "qso_call", "qso_nr", "receiver", "qso_id", "uid"]

FIELDS = ["time", "call", "band", "mode", "freq", "rst_s", "exch_s", "rst_r",
          "exch_r", "source", "uid", "place", "operator", "tx"]

# Standardwerte für die Log-Einstellungen
DEFAULT_META = {
    "contest": "cqww-ssb",
    "mycall": "",
    "operators": "",
    "my_zone": "14",
    "my_grid": "",
    "my_state": "",          # eigener US-State / kanadische Provinz (nur W/VE)
    "my_power": "",          # Leistung im Austausch (ARRL DX), leer = aus Kategorie
    "my_itu": "",            # ITU-Zone oder Verbandskürzel (IARU HF), leer = Länderdatei
    "my_licyear": "",        # Jahr der ersten Lizenz, zweistellig (EU HF)
    "my_dok": "",            # eigener DOK, leer = „NM“ (DARC-Conteste, ab 0.8.4)
    "my_oblast": "",         # eigener Oblast (nur Stationen in Russland, Russian DX)
    "my_iota": "",           # eigene IOTA-Referenz, leer = keine Insel (IOTA, ab 0.8.6)
    "my_age": "",            # Alter des Operators (All Asian), leer = „01“
    "my_iota_dxped": "",     # IOTA: "1" = DXpedition, leer = feste Station (ab 0.8.7)
    "my_iota_island": "",    # IOTA: Name der Insel (Cabrillo IOTA-ISLAND-NAME)
    "my_district": "",       # eigenes Kürzel im Gastgeberland (Länder-Contests, ab 0.8.7)
    "edi_section": "SO",     # UKW-Sektion für den EDI-Kopf (SO, MO, SO-LP, MO-LP, 6H; ab 0.8.8)
    "my_power_w": "",        # Sendeleistung in Watt (EDI)
    "my_antenna": "",        # Antenne (EDI)
    "name": "",
    "address": "",
    "email": "",
    "club": "",
    "cat_operator": "SINGLE-OP",
    "cat_band": "ALL",
    "cat_power": "HIGH",
    "cat_assisted": "NON-ASSISTED",
    "cat_transmitter": "ONE",
    "cat_overlay": "",
    "soapbox": "",
}


# ------------------------------------------------------------ Hilfsdateien aufräumen (0.10.7.2)
# SQLite legt im WAL-Modus neben jedes geöffnete Log „….ggh-wal“ und „….ggh-shm“. Solange das Log
# offen ist, braucht es sie; danach nicht mehr. GoGoHam räumt sie beim Schließen weg, entfernt
# Reste ohne zugehöriges Log und schließt liegen gebliebene sauber ab.
SIDE_SUFFIXES = ("-wal", "-shm", "-journal")


def side_files(path: str | Path) -> list[Path]:
    p = Path(path)
    return [p.with_name(p.name + s) for s in SIDE_SUFFIXES if p.with_name(p.name + s).exists()]


def finish_file(path: str | Path) -> bool:
    """Ein nicht geöffnetes Log sauber abschließen: Inhalt des WAL in die Datei übernehmen und
    in den normalen Modus schalten – dabei verschwinden -wal und -shm. False = ging nicht
    (z. B. gerade von einem anderen Programm benutzt); dann bleibt alles, wie es ist."""
    p = Path(path)
    if not p.is_file() or not side_files(p):
        return True
    try:
        conn = sqlite3.connect(str(p), timeout=0.5)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("PRAGMA journal_mode=DELETE")
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return not side_files(p)


def tidy_folder(folder: str | Path, skip: tuple = ()) -> int:
    """Hilfsdateien im Ordner aufräumen: Reste ohne Log löschen, liegen gebliebene bei nicht
    geöffneten Logs abschließen. ``skip`` = gerade offene Logs (die brauchen sie). Rückgabe:
    Zahl der entfernten Dateien."""
    d = Path(folder)
    if not d.is_dir():
        return 0
    keep = {Path(s).resolve() for s in skip if s}
    removed = 0
    for side in sorted(d.glob("*.ggh-*")):
        name = side.name
        suf = next((s for s in SIDE_SUFFIXES if name.endswith(".ggh" + s)), None)
        if suf is None:
            continue
        base = side.with_name(name[: -len(suf)])
        if base.exists():
            continue
        try:
            side.unlink()                       # Log gibt es nicht mehr: Rest ist wertlos
            removed += 1
        except OSError:
            pass
    for log in sorted(d.glob("*.ggh")):
        if log.resolve() in keep:
            continue
        before = len(side_files(log))
        if before and finish_file(log):
            removed += before
    return removed


@contextlib.contextmanager
def read_only(path: str | Path):
    """Ein Log nur lesen (Call-History, Prüfung) – ohne Hilfsdateien zu hinterlassen."""
    had = bool(side_files(path))
    conn = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    try:
        yield conn
    finally:
        conn.close()
        if not had:
            finish_file(path)


class LogDB:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        # ältere Logs: später dazugekommene Spalten nachrüsten
        for table, col, typ in _ADDED_COLUMNS:
            cols = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        self.conn.execute("CREATE INDEX IF NOT EXISTS qso_uid ON qso(uid)")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.commit()

    def close(self) -> None:
        """Schließen und die Hilfsdateien (-wal, -shm) gleich wegräumen (0.10.7.2)."""
        try:
            self.conn.commit()
            self.conn.execute("PRAGMA busy_timeout=300")   # nicht warten, wenn noch woanders offen
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.execute("PRAGMA journal_mode=DELETE")
        except sqlite3.Error:
            pass                                 # z. B. noch woanders offen – dann bleibt WAL
        self.conn.close()

    # Gesammelt speichern (Stationslog, 0.10.2): viele Änderungen, ein Schreibvorgang
    _defer = False

    @contextlib.contextmanager
    def batch(self):
        if self._defer:
            yield
            return
        self._defer = True
        try:
            with self.conn:
                yield
        finally:
            self._defer = False

    def _w(self):
        return contextlib.nullcontext() if self._defer else self.conn

    # ---------------------------------------------------------------- meta
    def get_meta(self) -> dict[str, str]:
        data = dict(DEFAULT_META)
        for row in self.conn.execute("SELECT key, value FROM meta"):
            data[row["key"]] = row["value"]
        return data

    def set_meta(self, data: dict[str, str]) -> None:
        with self._w():
            for k, v in data.items():
                self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                                  (k, str(v)))

    # ----------------------------------------------------------------- qso
    @staticmethod
    def _row(row: sqlite3.Row) -> Qso:
        return Qso(id=row["id"], **{f: row[f] for f in FIELDS})

    def all_qsos(self) -> list[Qso]:
        return [self._row(r) for r in self.conn.execute("SELECT * FROM qso ORDER BY time, id")]

    def add(self, q: Qso) -> int:
        if not q.uid:
            q.uid = new_uid()
        with self.conn:
            cur = self.conn.execute(
                f"INSERT INTO qso ({', '.join(FIELDS)}) VALUES ({', '.join('?' * len(FIELDS))})",
                [getattr(q, f) for f in FIELDS],
            )
        q.id = cur.lastrowid
        return q.id

    def update(self, q: Qso) -> None:
        with self.conn:
            self.conn.execute(
                f"UPDATE qso SET {', '.join(f + '=?' for f in FIELDS)} WHERE id=?",
                [getattr(q, f) for f in FIELDS] + [q.id],
            )

    def delete(self, qso_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM qso WHERE id=?", (qso_id,))

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM qso").fetchone()[0]

    # ----------------------------------------------------------------- QTC
    def all_qtcs(self) -> list[Qtc]:
        return [Qtc(id=r["id"], **{f: r[f] for f in QTC_FIELDS})
                for r in self.conn.execute("SELECT * FROM qtc ORDER BY time, id")]

    def add_qtcs(self, qtcs: list[Qtc]) -> None:
        with self._w():
            for q in qtcs:
                if not q.uid:
                    q.uid = new_uid()
                cur = self.conn.execute(
                    f"INSERT INTO qtc ({', '.join(QTC_FIELDS)}) "
                    f"VALUES ({', '.join('?' * len(QTC_FIELDS))})",
                    [getattr(q, f) for f in QTC_FIELDS])
                q.id = cur.lastrowid

    def update_qtc(self, q: Qtc) -> None:
        with self.conn:
            self.conn.execute(
                f"UPDATE qtc SET {', '.join(f + '=?' for f in QTC_FIELDS)} WHERE id=?",
                [getattr(q, f) for f in QTC_FIELDS] + [q.id])

    def delete_qtc(self, qtc_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM qtc WHERE id=?", (qtc_id,))

    # ------------------------------------------------- Stationslog (ab 0.10)
    def ensure_uids(self) -> None:
        """QSOs/QTCs ohne Kennung bekommen eine (z. B. aus Logs von vor 0.10)."""
        with self.conn:
            for table in ("qso", "qtc"):
                for (rid,) in self.conn.execute(
                        f"SELECT id FROM {table} WHERE uid IS NULL OR uid = ''").fetchall():
                    self.conn.execute(f"UPDATE {table} SET uid=? WHERE id=?", (new_uid(), rid))

    def record(self, kind: str, uid: str) -> dict | None:
        """QSO bzw. QTC mit dieser Kennung als dict (ohne id) – None, wenn es keins gibt."""
        table, fields = ("qso", FIELDS) if kind == "qso" else ("qtc", QTC_FIELDS)
        r = self.conn.execute(f"SELECT * FROM {table} WHERE uid=?", (uid,)).fetchone()
        return {f: r[f] for f in fields} if r else None

    def put_record(self, kind: str, data: dict) -> None:
        """QSO/QTC von einem anderen Platz übernehmen (neu oder geändert, über uid)."""
        table, fields = ("qso", FIELDS) if kind == "qso" else ("qtc", QTC_FIELDS)
        vals = {f: data.get(f, "" if f not in ("freq", "series", "total", "qso_id") else 0)
                for f in fields}
        with self._w():
            r = self.conn.execute(f"SELECT id FROM {table} WHERE uid=?",
                                  (vals["uid"],)).fetchone()
            if r:
                self.conn.execute(f"UPDATE {table} SET {', '.join(f + '=?' for f in fields)} "
                                  "WHERE id=?", [vals[f] for f in fields] + [r[0]])
            else:
                self.conn.execute(f"INSERT INTO {table} ({', '.join(fields)}) VALUES "
                                  f"({', '.join('?' * len(fields))})", [vals[f] for f in fields])

    def delete_record(self, kind: str, uid: str) -> None:
        table = "qso" if kind == "qso" else "qtc"
        with self._w():
            self.conn.execute(f"DELETE FROM {table} WHERE uid=?", (uid,))

    def all_records(self) -> list[tuple[str, dict]]:
        out = [("qso", {f: r[f] for f in FIELDS})
               for r in self.conn.execute("SELECT * FROM qso ORDER BY time, id")]
        out += [("qtc", {f: r[f] for f in QTC_FIELDS})
                for r in self.conn.execute("SELECT * FROM qtc ORDER BY time, id")]
        return out

    def journal_add(self, kind: str, uid: str, deleted: bool, data: dict | None) -> int:
        with self.conn:
            cur = self.conn.execute("INSERT INTO sync_journal (kind, uid, del, data) "
                                    "VALUES (?, ?, ?, ?)",
                                    (kind, uid, int(deleted), json.dumps(data or {})))
        return cur.lastrowid

    def journal_since(self, seq: int) -> list[dict]:
        """Änderungen nach ``seq`` – je Kennung nur der letzte Stand."""
        rows = self.conn.execute("SELECT seq, kind, uid, del, data FROM sync_journal "
                                 "WHERE seq > ? ORDER BY seq", (seq,)).fetchall()
        last: dict[tuple, dict] = {}
        for r in rows:
            last[(r[1], r[2])] = {"seq": r[0], "kind": r[1], "uid": r[2], "del": bool(r[3]),
                                  "data": json.loads(r[4])}
        return sorted(last.values(), key=lambda x: x["seq"])

    def journal_seq(self) -> int:
        return self.conn.execute("SELECT COALESCE(MAX(seq), 0) FROM sync_journal").fetchone()[0]

    def journal_empty(self) -> bool:
        return self.journal_seq() == 0

    def outbox_add(self, msg: dict) -> int:
        with self._w():
            cur = self.conn.execute("INSERT INTO sync_outbox (msg) VALUES (?)", (json.dumps(msg),))
        return cur.lastrowid

    def outbox(self) -> list[tuple[int, dict]]:
        return [(r[0], json.loads(r[1]))
                for r in self.conn.execute("SELECT id, msg FROM sync_outbox ORDER BY id")]

    def outbox_done(self, oid: int) -> None:
        with self._w():
            self.conn.execute("DELETE FROM sync_outbox WHERE id=?", (oid,))

    # ------------------------------------------------------- Nachrichten (0.10.3)
    # state: "in" = empfangen, "out" = unterwegs, "ok" = zugestellt, "fail" = nicht zugestellt
    def chat_add(self, m: dict, state: str) -> None:
        with self._w():
            self.conn.execute("INSERT OR IGNORE INTO station_chat (mid, time, sender, recipient, "
                              "text, state) VALUES (?, ?, ?, ?, ?, ?)",
                              (m["mid"], m.get("time", ""), m.get("from", ""), m.get("to", ""),
                               m.get("text", ""), state))

    def chat_state(self, mid: str, state: str) -> None:
        with self._w():
            self.conn.execute("UPDATE station_chat SET state=? WHERE mid=?", (state, mid))

    def chat_fail_pending(self) -> None:
        """Verbindung weg: was noch unterwegs war, kommt nicht mehr an."""
        with self._w():
            self.conn.execute("UPDATE station_chat SET state='fail' WHERE state='out'")

    def chats(self, limit: int = 300) -> list[dict]:
        rows = self.conn.execute("SELECT mid, time, sender, recipient, text, state FROM "
                                 "station_chat ORDER BY time DESC, rowid DESC LIMIT ?", (limit,))
        return [{"mid": r[0], "time": r[1], "from": r[2], "to": r[3], "text": r[4],
                 "state": r[5]} for r in rows][::-1]

    # ------------------------------------------------------------ Callbook
    def callbook(self) -> dict[str, dict]:
        return {r["call"]: dict(r) for r in self.conn.execute("SELECT * FROM callbook")}

    def set_callbook(self, call: str, name: str, qth: str, grid: str, source: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO callbook(call, name, qth, grid, source) VALUES (?,?,?,?,?)",
                (call.upper(), name, qth, grid, source))

    def next_serial(self) -> int:
        """Nächste laufende Nummer (WPX …): höchste gesendete Nummer + 1. Auch „007 B36“
        (DARC 10 m: Nummer und DOK) zählt mit seiner Nummer."""
        best = 0
        for (v,) in self.conn.execute("SELECT exch_s FROM qso"):
            first = str(v or "").split()
            if first and first[0].isdigit():
                best = max(best, int(first[0]))
        return best + 1


def new_uid() -> str:
    return uuid.uuid4().hex
