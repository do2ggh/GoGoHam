"""Sicherungen und Reparatur von Log-Dateien (SQLite)."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

KEEP = 20          # so viele Sicherungen je Log bleiben liegen


def backup_dir(log_path: str | Path) -> Path:
    return Path(log_path).parent / "Sicherungen"


def make_backup(conn: sqlite3.Connection, log_path: str | Path, keep: int = KEEP) -> Path:
    """Konsistente Kopie über die SQLite-Backup-Funktion (auch während das Log offen ist)."""
    log_path = Path(log_path)
    d = backup_dir(log_path)
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = d / f"{log_path.stem}_{stamp}{log_path.suffix}"
    n = 1
    while target.exists():
        target = d / f"{log_path.stem}_{stamp}-{n}{log_path.suffix}"
        n += 1
    dest = sqlite3.connect(str(target))
    try:
        conn.backup(dest)
    finally:
        dest.close()
    prune(log_path, keep)
    return target


def list_backups(log_path: str | Path) -> list[Path]:
    log_path = Path(log_path)
    d = backup_dir(log_path)
    if not d.is_dir():
        return []
    files = list(d.glob(f"{log_path.stem}_*{log_path.suffix}"))
    # nach Entstehungszeit sortieren (der Name allein ordnet „…-1“ falsch ein)
    return sorted(files, key=lambda p: (p.stat().st_mtime_ns, p.name))


def prune(log_path: str | Path, keep: int = KEEP) -> None:
    files = list_backups(log_path)
    for old in files[:-keep] if keep > 0 else []:
        try:
            old.unlink()
        except OSError:
            pass


def check(path: str | Path) -> str:
    """'ok' oder eine Fehlerbeschreibung."""
    from .db import read_only
    try:
        with read_only(path) as conn:              # hinterlässt keine -wal/-shm (0.10.7.2)
            res = conn.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.DatabaseError as e:
        return str(e)
    msg = "; ".join(r[0] for r in res)
    return "ok" if msg == "ok" else msg


def repair(broken: str | Path) -> tuple[Path, int]:
    """Rettet, was zu retten ist, in eine neue Datei '<name>-repariert'.

    Das Original bleibt unverändert. Gibt (neue Datei, Zahl geretteter QSOs) zurück.
    """
    broken = Path(broken)
    target = broken.with_name(f"{broken.stem}-repariert{broken.suffix}")
    n = 1
    while target.exists():
        target = broken.with_name(f"{broken.stem}-repariert{n}{broken.suffix}")
        n += 1
    # 1. Weg: sqlite3-Kommandozeile mit .recover (am gründlichsten)
    exe = shutil.which("sqlite3")
    if exe:
        try:
            dump = subprocess.run([exe, str(broken), ".recover"], capture_output=True,
                                  timeout=120, check=False).stdout
            if dump:
                subprocess.run([exe, str(target)], input=dump, capture_output=True,
                               timeout=120, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
    if not _usable(target):
        if target.exists():
            target.unlink()
        _salvage(broken, target)
    from .db import LogDB
    db = LogDB(target)              # legt fehlende Tabellen an
    count = db.count()
    db.close()
    return target, count


def _usable(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        conn = sqlite3.connect(str(path))
        conn.execute("SELECT COUNT(*) FROM qso").fetchone()
        conn.close()
        return True
    except sqlite3.DatabaseError:
        return False


def _salvage(broken: Path, target: Path) -> None:
    """2. Weg ohne sqlite3-Programm: Zeile für Zeile lesen, was noch lesbar ist."""
    from .db import FIELDS, LogDB
    # Ziel mit dem vollen, aktuellen Aufbau anlegen (auch später dazugekommene Spalten wie
    # uid/place/operator/tx – mit nur SCHEMA ging seit 0.10 jedes QSO beim Einfügen verloren)
    LogDB(target).close()
    out = sqlite3.connect(str(target))
    try:
        src = sqlite3.connect(f"file:{broken}?mode=ro", uri=True)
    except sqlite3.DatabaseError:
        out.close()
        return
    def copy_rows(table, cols, rows):
        for row in rows:
            try:
                out.execute(f"INSERT OR IGNORE INTO {table} ({', '.join(cols)}) "
                            f"VALUES ({', '.join('?' * len(cols))})", row)
            except sqlite3.DatabaseError:
                continue

    for table, cols in (("meta", ["key", "value"]),
                        ("callbook", ["call", "name", "qth", "grid", "source"])):
        rows = []
        try:
            cur = src.execute(f"SELECT {', '.join(cols)} FROM {table}")
            while True:
                row = cur.fetchone()
                if row is None:
                    break
                rows.append(row)
        except sqlite3.DatabaseError:
            pass
        copy_rows(table, cols, rows)

    # QSOs einzeln über ihre Nummer lesen – eine kaputte Seite blockiert so nicht alles
    try:                                      # ältere Logs haben nicht alle Spalten
        have = {r[1] for r in src.execute("PRAGMA table_info(qso)")}
    except sqlite3.DatabaseError:
        have = set()
    cols = ["id"] + [f for f in FIELDS if not have or f in have]
    sql = f"SELECT {', '.join(cols)} FROM qso WHERE id = ?"
    misses, qid, rows = 0, 1, []
    while misses < 5000:
        try:
            row = src.execute(sql, (qid,)).fetchone()
        except sqlite3.DatabaseError:
            row = None
        if row is None:
            misses += 1
        else:
            misses = 0
            rows.append(row)
        qid += 1
    copy_rows("qso", cols, rows)
    out.commit()
    out.close()
    src.close()
