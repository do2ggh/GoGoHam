"""Tests für 0.6: Sicherung/Reparatur, Termine/Betriebszeit, Call-History,
Log-Prüfung, Live-Score, Rate."""

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.cty import CtyDB
from gogoham.db import LogDB

HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def q(call, band="20", mode="USB", exch_r="", qid=None, exch_s="14", t="2026-10-24 00:01:00"):
    return Qso(id=qid, time=t, call=call, band=band, mode=mode, freq=14_250_000,
               rst_s="59", exch_s=exch_s, rst_r="59", exch_r=exch_r)


# ------------------------------------------------------------ Sicherung
def test_backup_and_prune(tmp_path):
    from gogoham import backup
    db = LogDB(tmp_path / "cq.ggh")
    db.add(q("W1AW", exch_r="5"))
    p = backup.make_backup(db.conn, db.path)
    assert p.parent.name == "Sicherungen" and p.exists()
    copy = LogDB(p)
    assert copy.count() == 1
    copy.close()
    for _ in range(5):
        backup.make_backup(db.conn, db.path, keep=3)
    assert len(backup.list_backups(db.path)) == 3
    db.close()


def test_check_and_repair(tmp_path):
    from gogoham import backup
    path = tmp_path / "kaputt.ggh"
    db = LogDB(path)
    db.set_meta({"contest": "cqww-ssb", "mycall": "DO2GGH"})
    for i in range(300):
        db.add(q(f"W{i % 10}AB{chr(65 + i % 26)}", exch_r="5",
                 t=f"2026-10-24 {i // 60:02d}:{i % 60:02d}:00"))
    db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    # eine Blattseite der QSO-Tabelle aus der Mitte (fest „Seite 12“ verrutschte, sobald eine
    # neue Tabelle dazukam – 0.10.3)
    leaves = [r[0] for r in db.conn.execute(
        "SELECT pageno FROM dbstat WHERE name='qso' AND pagetype='leaf' ORDER BY pageno")]
    db.close()
    assert backup.check(path) == "ok"
    # Datei mitten im Inhalt beschädigen
    data = bytearray(path.read_bytes())
    page = 4096
    start = (leaves[len(leaves) // 2] - 1) * page
    for i in range(start, start + 60):             # Kopf einer Blattseite der QSO-Tabelle
        data[i] = 0xFF
    path.write_bytes(bytes(data))
    assert backup.check(path) != "ok"
    fixed, n = backup.repair(path)
    assert fixed.name == "kaputt-repariert.ggh" and fixed.exists()
    assert 150 < n < 300                         # der Rest der QSOs ist gerettet
    assert backup.check(fixed) == "ok"
    assert LogDB(fixed).get_meta()["mycall"] == "DO2GGH"
    assert path.exists()                         # Original bleibt


# ------------------------------------------------------------ Termine
def test_last_full_weekend():
    from gogoham.schedule import last_full_weekend
    assert last_full_weekend(2026, 10) == date(2026, 10, 24)     # 31.10. ist Samstag, 1.11. Sonntag
    assert last_full_weekend(2026, 3) == date(2026, 3, 28)
    assert last_full_weekend(2026, 5) == date(2026, 5, 30)
    assert last_full_weekend(2026, 8) == date(2026, 8, 29)
    assert last_full_weekend(2026, 11) == date(2026, 11, 28)
    assert last_full_weekend(2026, 12) == date(2026, 12, 26)


def test_countdown():
    from gogoham.schedule import countdown, next_period
    rule = CONTESTS["cqww-cw"].schedule
    s, e = next_period(rule, datetime(2026, 11, 2, 0, 0))
    assert s == datetime(2026, 11, 28, 0, 0) and e == datetime(2026, 11, 30, 0, 0)
    assert countdown(rule, datetime(2026, 11, 27, 22, 30)) == "Beginn in 01:30 h"
    assert countdown(rule, datetime(2026, 11, 29, 23, 0)).startswith("läuft · noch 01:00")
    assert "T" in countdown(rule, datetime(2026, 11, 2))
    digi = CONTESTS["ww-digi"].schedule
    s, e = next_period(digi, datetime(2027, 1, 1))
    assert s == datetime(2027, 8, 28, 12, 0) and e - s == timedelta(hours=24)


def test_operating_time():
    from gogoham.schedule import operating_time
    start = datetime(2026, 3, 28, 0, 0)
    end = start + timedelta(hours=48)
    # QSOs von 00:00 bis 02:00 alle 5 min, Pause 59 min, weiter bis 04:00, Pause 2 h, 06:00-07:00
    ts = []
    t = start
    while t <= start + timedelta(hours=2):
        ts.append(t)
        t += timedelta(minutes=5)
    t = start + timedelta(hours=2, minutes=59)
    while t <= start + timedelta(hours=4):
        ts.append(t)
        t += timedelta(minutes=5)
    t = start + timedelta(hours=6)
    while t <= start + timedelta(hours=7):
        ts.append(t)
        t += timedelta(minutes=5)
    now = start + timedelta(hours=7, minutes=10)
    op = operating_time(ts, start, end, now)
    # 0-~4:00 zählt durch (59 min Pause ist zu kurz), 2 h Pause zählt nicht, 6:00-7:10
    assert timedelta(hours=5) < op < timedelta(hours=5, minutes=20)
    assert operating_time([], start, end, now) == timedelta(0)


# ------------------------------------------------------------ Call-History
N1MM = """# CQWW SSB call history
!!Order!!,Call,Name,CQZone,ITUZone
W1AW,Hiram,5,8
VK6ABC,Bob,29,58
K6XX,,3,6
"""


def test_call_history(tmp_path, monkeypatch):
    from gogoham import callhistory as ch
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    src = tmp_path / "CQWW_SSB.txt"
    src.write_text(N1MM)
    ch.import_file(src)
    bad = tmp_path / "x.txt"
    bad.write_text("hallo\nwelt\n")
    with pytest.raises(ValueError):
        ch.import_file(bad)
    # eigenes Log: W1AW hat dort Zone 4 gegeben -> eigenes Log gewinnt
    logs = tmp_path / "GoGoHam"
    logs.mkdir()
    db = LogDB(logs / "cq2025.ggh")
    db.set_meta({"contest": "cqww-ssb"})
    db.add(q("W1AW", exch_r="04"))
    db.close()
    d = LogDB(logs / "digi.ggh")
    d.set_meta({"contest": "ww-digi"})
    d.add(q("JA1ABC", mode="FT8", exch_r="PM95"))
    d.close()
    h = ch.build(logs)
    assert h.get("W1AW").zone == "4" and h.get("W1AW").name == "Hiram"
    assert h.get("vk6abc").zone == "29" and h.get("K6XX").zone == "3"
    assert h.get("JA1ABC").grid == "PM95"
    assert h.get("XX1XX") is None
    h.learn_qso("cqww-ssb", "VK6ABC", "30")
    assert h.get("VK6ABC").zone == "30"


# ------------------------------------------------------------ Log-Prüfung
def test_logcheck(cty):
    from gogoham.logcheck import check
    from gogoham.scp import ScpDB
    from gogoham.callhistory import CallHistory
    c = CONTESTS["cqww-ssb"](cty, Station(call="DO2GGH", cq_zone=14))
    s = Scorer(c)
    qs = [q("W1AW", exch_r="05", qid=1), q("W1AW", exch_r="05", qid=2),
          q("VK2ABC", exch_r="14", qid=3), q("JA1XYZ", exch_r="25", qid=4),
          q("XX9QQQ", exch_r="05", qid=5)]
    s.rebuild(qs)
    hist = CallHistory()
    hist._merge("W1AW", zone="4", source="test")
    f = check(c, qs, s, ScpDB.parse("W1AW\nVK2ABC\n"), hist)
    texts = {(x.qso_id, x.text.split(" ")[0]) for x in f}
    assert (2, "Dupe") in texts
    assert any(x.qso_id == 3 and "ungewöhnlich" in x.text for x in f)
    assert any(x.qso_id == 4 and "SCP" in x.text for x in f)          # JA1XYZ nicht in SCP
    assert any(x.qso_id == 5 and "Präfix unbekannt" in x.text for x in f)
    assert any(x.qso_id == 1 and "Call-History" in x.text for x in f)
    # WPX: fehlende gesendete Nummern
    c = CONTESTS["wpx-ssb"](cty, Station(call="DO2GGH"))
    s = Scorer(c)
    qs = [q("W1AW", exch_r="1", exch_s="001", qid=1), q("W2AW", exch_r="7", exch_s="003", qid=2)]
    s.rebuild(qs)
    assert any("fehlen" in x.text and "2" in x.text for x in check(c, qs, s))


# ------------------------------------------------------------ Live-Score
def test_livescore_xml(cty):
    import xml.etree.ElementTree as ET
    from gogoham.livescore import build_xml
    c = CONTESTS["cqww-ssb"](cty, Station(call="DO2GGH", cq_zone=14, grid="JN59me"))
    s = Scorer(c)
    s.rebuild([q("W1AW", exch_r="05", qid=1), q("JA1ABC", band="15", exch_r="25", qid=2)])
    meta = {"mycall": "DO2GGH", "my_zone": "14", "my_grid": "JN59me", "cat_power": "LOW"}
    root = ET.fromstring(build_xml(c, meta, s, datetime(2026, 10, 24, 12, 0)))
    assert root.tag == "dynamicresults" and root.findtext("contest") == "CQ-WW-SSB"
    assert root.findtext("call") == "DO2GGH" and root.find("class").get("mode") == "PH"
    assert root.find("class").get("power") == "LOW"
    assert root.findtext("score") == str(s.score) and root.findtext("soft") == "GoGoHam"
    tot = {(e.tag, e.get("type")): e.text for e in root.find("breakdown")
           if e.get("band") == "total"}
    assert tot[("qso", None)] == "2" and tot[("mult", "zone")] == "2"
    assert tot[("mult", "country")] == "2"
    assert root.findtext("timestamp") == "2026-10-24 12:00:00"
    assert root.find("qth").findtext("dxcccountry") == "DL"


def test_livescore_post():
    """Echter HTTP-POST gegen einen lokalen Test-Server."""
    import base64
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from gogoham.livescore import post
    got = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers["Content-Length"])
            got["body"] = self.rfile.read(n).decode()
            got["auth"] = self.headers.get("Authorization")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":200,"status_message":"OK-Full"}')

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    ans = post(f"http://127.0.0.1:{srv.server_port}/post/", "DO2GGH", "geheim",
               "<dynamicresults/>")
    assert "OK-Full" in ans and got["body"] == "<dynamicresults/>"
    assert base64.b64decode(got["auth"].split()[1]).decode() == "DO2GGH:geheim"
    srv.server_close()


# ------------------------------------------------------------ Rate
def test_rate_by_hour():
    from gogoham.stats import rate_by_hour
    qs = [q("A1A", t="2026-10-24 00:10:00", qid=1), q("A2A", t="2026-10-24 00:50:00", qid=2),
          q("A3A", band="40", t="2026-10-24 02:05:00", qid=3)]
    r = rate_by_hour(qs, ["40", "20"], dupes={2})
    assert [lab for lab, _ in r] == ["24.10. 00 UTC", "24.10. 01 UTC", "24.10. 02 UTC"]
    assert r[0][1] == {"20": 1} and r[1][1] == {} and r[2][1] == {"40": 1}


def test_mult_matrix(cty):
    from gogoham.stats import mult_matrix
    c = CONTESTS["cqww-ssb"](cty, Station(call="DO2GGH", cq_zone=14))
    s = Scorer(c)
    qs = [q("W1AW", exch_r="05", qid=1), q("W1AW", band="40", exch_r="05", qid=2),
          q("JA1ABC", band="15", exch_r="25", qid=3)]
    s.rebuild(qs)
    m = mult_matrix(c, s, qs)
    assert m["zone"]["rows"][0] == "1" and len(m["zone"]["rows"]) == 40
    assert ("5", "20") in m["zone"]["worked"] and ("5", "40") in m["zone"]["worked"]
    assert ("25", "15") in m["zone"]["worked"] and ("25", "20") not in m["zone"]["worked"]
    assert m["country"]["rows"] == ["JA", "K"]
    c = CONTESTS["wpx-ssb"](cty, Station(call="DO2GGH"))
    s = Scorer(c)
    qs = [q("W1AW", band="40", exch_r="1", qid=1), q("W1XX", band="20", exch_r="2", qid=2)]
    s.rebuild(qs)
    m = mult_matrix(c, s, qs)
    assert m["prefix"]["worked"] == {("W1", "40")}
