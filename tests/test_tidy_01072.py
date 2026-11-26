"""0.10.7.2: Hilfsdateien der Logs (-wal/-shm) aufräumen – nichts geht verloren."""

import shutil
import sqlite3

from gogoham import db
from gogoham.contests.base import Qso


def _log_with_qsos(path, n=3):
    d = db.LogDB(path)
    d.set_meta({"contest": "cqww-cw", "mycall": "DO2GGH"})
    for i in range(n):
        d.add(Qso(time=f"2026-11-28 10:0{i}:00", call=f"DL{i}ABC", band="20", mode="CW",
                      freq=14_020_000, rst_s="599", exch_s="14", rst_r="599", exch_r="14"))
    return d


def _count(path):
    c = sqlite3.connect(str(path))
    try:
        return c.execute("SELECT COUNT(*) FROM qso").fetchone()[0]
    finally:
        c.close()


def test_close_removes_side_files(tmp_path):
    p = tmp_path / "a.ggh"
    d = _log_with_qsos(p)
    assert db.side_files(p)                       # offen: WAL-Dateien da
    d.close()
    assert db.side_files(p) == [] and _count(p) == 3
    d2 = db.LogDB(p)                              # wieder öffnen: geht, WAL wieder an
    assert len(d2.all_qsos()) == 3
    d2.close()


def test_stale_wal_with_data_is_finished_not_lost(tmp_path):
    p = tmp_path / "b.ggh"
    d = _log_with_qsos(p, 5)
    # Zustand „Programm abgestürzt“: Kopie samt -wal/-shm, während das Log offen ist
    crash = tmp_path / "crash"
    crash.mkdir()
    for f in [p] + db.side_files(p):
        shutil.copy2(f, crash / f.name)
    d.close()
    c = crash / "b.ggh"
    assert db.side_files(c)
    assert db.tidy_folder(crash) >= 1
    assert db.side_files(c) == [] and _count(c) == 5    # alle QSOs übernommen


def test_orphans_deleted_open_log_kept(tmp_path):
    (tmp_path / "weg.ggh-wal").write_bytes(b"")
    (tmp_path / "weg.ggh-shm").write_bytes(b"x" * 10)
    (tmp_path / "notiz.txt").write_text("bleibt")
    p = tmp_path / "offen.ggh"
    d = _log_with_qsos(p)
    assert db.tidy_folder(tmp_path, skip=(str(p),)) == 2
    names = sorted(x.name for x in tmp_path.iterdir())
    assert "weg.ggh-wal" not in names and "notiz.txt" in names
    assert db.side_files(p)                       # offenes Log: Hilfsdateien bleiben
    d.close()


def test_read_only_leaves_nothing(tmp_path):
    p = tmp_path / "c.ggh"
    _log_with_qsos(p).close()
    with db.read_only(p) as conn:
        assert conn.execute("SELECT COUNT(*) FROM qso").fetchone()[0] == 3
    assert db.side_files(p) == []
    from gogoham import backup
    assert backup.check(p) == "ok" and db.side_files(p) == []
