"""0.8.4: DARC-Conteste WAG, 10 m, Weihnachten, Ostern und die DOK-Bausteine."""

from datetime import date
from pathlib import Path

import pytest

from conftest import builtin_newer_than

from gogoham import dok, rulefiles, schedule, stats
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.cty import CtyDB
from gogoham.export import adif, cabrillo_qso_line
from gogoham.logcheck import check

HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def make(cid, cty, call="DL1ABC", dk="B36"):
    c = CONTESTS[cid](cty, Station(call=call, cq_zone=14, dok=dk))
    return c, Scorer(c)


def qso(i, call, ex, band="40", mode="CW", freq=0, t="2026-10-17 15:00:00", ex_s=""):
    return Qso(id=i, time=t, call=call, band=band, mode=mode, freq=freq,
               rst_s="599", rst_r="599", exch_r=ex, exch_s=ex_s)


# ------------------------------------------------------------ DOK
def test_dok_form_and_district():
    assert dok.form_error("B36") is None and dok.form_error("nm") is None
    assert dok.form_error("750UEM") is None                 # Sonder-DOK
    assert "B06" in dok.form_error("B6")                    # Null vergessen
    assert dok.form_error("12") and dok.form_error("B-36")
    assert dok.district("B36") == "B" and dok.district("750UEM") == "U"
    assert not dok.counts("NM") and dok.counts("H13")


def test_dok_list_and_hints():
    from conftest import DOK_SAMPLE
    db = dok.DokDB()
    if dok.BUILTIN_OV.is_file():                   # vollständige Liste (nicht auf GitHub)
        assert db.load_ov(dok.BUILTIN_OV.read_text(encoding="utf-8")) >= 980
    else:
        assert db.load_ov(DOK_SAMPLE.read_text(encoding="utf-8")) == 4
    assert db.name("B36") and db.name("Z12") == "VFDB"
    assert "gibt es laut Liste nicht" in db.hint("B99")
    assert db.hint("B36") is None and db.hint("NM") is None
    assert db.hint("750UEM") is None                         # ohne S-DOK-Liste: nichts sagen
    db.load_sdok("750UEM;750 Jahre Uelzen;DQ750UEM;01.01.26;31.12.26;H33\n"
                 "ALT08;Alt;DL0ALT;01.01.08;31.12.08;F12\n")
    assert db.hint("750UEM", "DQ750UEM", date(2026, 10, 17)) is None
    assert "für DQ750UEM vergeben" in db.hint("750UEM", "DL1ABC", date(2026, 10, 17))
    assert "galt nur bis 31.12.2008" in db.hint("ALT08", "DL0ALT", date(2026, 10, 17))
    assert "unbekannt" in db.hint("NEU26", "DL1ABC", date(2026, 10, 17))


def test_parse_download_pages():
    page = ('<a href="/der-club/distrikte/b/ortsverbaende/36/">Ortsverband Bad Kreuznach (B36)</a>'
            '<a href="/der-club/distrikte/c/ortsverbaende/01/">Ortsverband München-Nord (C01)</a>')
    assert dok.parse_districts_page(page) == {"B36": "Bad Kreuznach", "C01": "München-Nord"}
    assert dok.parse_vfdb_page("OV Z12 und Z01, Z12") == ["Z01", "Z12"]


# ------------------------------------------------------------ Termine
def test_schedules_2026():
    s = {cid: CONTESTS[cid].schedule for cid in ("wag", "darc-10m", "darc-xmas", "darc-easter")}
    assert schedule.period(s["wag"], 2026)[0].isoformat() == "2026-10-17T15:00:00"
    assert schedule.period(s["darc-10m"], 2026) == (
        schedule.datetime(2026, 1, 11, 9), schedule.datetime(2026, 1, 11, 11))
    assert schedule.period(s["darc-xmas"], 2026)[0].isoformat() == "2026-12-26T08:30:00"
    assert schedule.period(s["darc-xmas"], 2026)[1].isoformat() == "2026-12-26T11:00:00"
    assert schedule.period(s["darc-easter"], 2026)[0].isoformat() == "2026-04-06T15:00:00"
    assert schedule.period(s["darc-easter"], 2027)[0].isoformat() == "2027-03-29T15:00:00"
    assert schedule.easter_sunday(2025) == date(2025, 4, 20)


# ------------------------------------------------------------ WAG
def test_wag_dl_station(cty):
    c, s = make("wag", cty)
    assert c.sent_exchange(5) == "B36"
    assert c.expected_kind(cty.lookup("DK5HH")) == "dok"
    assert c.expected_kind(cty.lookup("OE1ABC")) == "serial"
    assert [k for k, _l in c.mult_types] == ["country"]
    log = [qso(1, "DK5HH", "H13"),                 # DL–DL 1 Punkt, Multi DL
           qso(2, "OE1ABC", "12"),                 # Europa 3, Multi OE
           qso(3, "W1AW", "7"),                    # DX 5, Multi K
           qso(4, "OE1ABC", "13", mode="USB"),     # anderer Mode: kein Dupe, neuer Multi OE (SSB)
           qso(5, "OE1ABC", "14")]                 # Dupe (40 m CW)
    s.rebuild(log)
    assert s.total_points == 1 + 3 + 5 + 3 and s.dupes == 1
    assert s.mult_count() == 4 and s.score == 12 * 4


def test_wag_foreign_station(cty):
    c, s = make("wag", cty, call="OE1ABC", dk="")
    assert c.sent_exchange(7) == "007"
    assert [k for k, _l in c.mult_types] == ["district"]
    log = [qso(1, "DK5HH", "H13"), qso(2, "DL1ABC", "H08"), qso(3, "DQ750UEM", "750UEM"),
           qso(4, "G4ABC", "5"),                   # Ausland–Ausland zählt nicht
           qso(5, "DL2XYZ", "NM")]                 # NM: Punkte ja, Multi nein
    s.rebuild(log)
    assert s.total_points == 3 * 4
    assert s.mults[("district", "40:CW")] == {"H", "U"}
    assert "nur QSOs mit DL" in s.evals[4].warning


def test_wag_segments_and_logcheck(cty):
    c, s = make("wag", cty)
    q = qso(1, "DK5HH", "H13", freq=7_050_000)
    assert "contestfreien Bereich 7040–7200" in c.notes(q, cty.lookup("DK5HH"))[0]
    assert c.notes(qso(2, "DK5HH", "H13", freq=7_020_000), cty.lookup("DK5HH")) == []
    log = [q, qso(2, "DK5HH", "B99", band="80", freq=3_530_000)]
    s.rebuild(log)
    texts = [f.text for f in check(c, log, s)]
    assert any("contestfreien" in t for t in texts)
    assert any("B99 gibt es laut Liste nicht" in t for t in texts)


# ------------------------------------------------------------ 10 m
def test_10m_serial_and_dok(cty):
    c, s = make("darc-10m", cty)
    assert c.sent_exchange(3) == "003 B36"
    assert c.sent_serial("003 B36") == 3
    lk = cty.lookup("DK5HH")
    assert c.validate_exchange("12 H13", lk) is None
    assert "DOK fehlt" in c.validate_exchange("12", lk)
    assert c.validate_exchange("12", cty.lookup("OE1ABC")) is None
    log = [qso(1, "DK5HH", "12 H13", band="10", freq=28_020_000),
           qso(2, "DK5HH", "13 H13", band="10", mode="USB", freq=28_400_000),  # anderer Mode ok
           qso(3, "OE1ABC", "4", band="10", freq=28_030_000),
           qso(4, "DK5HH", "14 H13", band="10", freq=28_025_000)]            # Dupe (CW)
    s.rebuild(log)
    assert s.total_points == 3 and s.dupes == 1
    # Multis je Mode: CW DL, H13, OE; SSB DL, H13
    assert s.mult_count() == 5
    assert "außerhalb der Contest-Bereiche" in c.notes(
        qso(5, "DK5HH", "1 H13", band="10", mode="USB", freq=28_250_000), lk)[0]


def test_10m_cabrillo_columns(cty):
    c, _s = make("darc-10m", cty, call="DQ4W", dk="Z06")
    q1 = qso(1, "VK2AA", "1", band="10", freq=28_002_000, ex_s="001 Z06")
    q2 = qso(2, "DL1A", "7 C30", band="10", mode="USB", freq=28_490_000, ex_s="002 Z06")
    l1, l2 = cabrillo_qso_line(c, q1, "DQ4W"), cabrillo_qso_line(c, q2, "DQ4W")
    assert l1.split()[5:] == ["DQ4W", "599", "001", "Z06", "VK2AA", "599", "1", "-", "0"]
    assert l2.split()[5:] == ["DQ4W", "599", "002", "Z06", "DL1A", "599", "7", "C30", "0"]
    a = adif(c, {"mycall": "DQ4W", "my_dok": "Z06"}, [q2])
    assert "<DARC_DOK:3>C30" in a and "<MY_DARC_DOK:3>Z06" in a and "<STX:1>2" in a


# ------------------------------------------------------------ Weihnachten / Ostern
@pytest.mark.parametrize("cid", ["darc-xmas", "darc-easter"])
def test_sprint_dok_and_prefix(cty, cid):
    c, s = make(cid, cty)
    assert [k for k, _l in c.mult_types] == ["dok", "prefix"]
    log = [qso(1, "DK5HH", "H13", band="80", freq=3_520_000),     # DOK H13 + Präfix DK5
           qso(2, "DL1ABC", "H13", band="80", freq=3_530_000),    # nur Präfix DL1 neu
           qso(3, "DK5HH", "H13", band="40", freq=7_020_000),     # anderes Band: alles neu
           qso(4, "OE1ABC", "5", band="40", freq=7_025_000)]      # Ausland: Präfix OE1
    s.rebuild(log)
    assert s.total_points == 4 and s.mult_count() == 3 + 2 + 1


def test_sprint_change_limit(cty):
    c, s = make("darc-xmas", cty)
    log = []
    for i in range(23):                                           # 22 Wechsel 80 <-> 40
        band, f = ("80", 3_520_000) if i % 2 == 0 else ("40", 7_020_000)
        log.append(qso(i + 1, f"DL{i}AA", "B36", band=band, freq=f,
                       t=f"2026-12-26 08:{30 + i:02d}:00"))
    s.rebuild(log)
    assert stats.changes_total(log) == 22
    f = [x for x in check(c, log, s) if "im Contest" in x.text]
    assert len(f) == 1 and f[0].qso_id == 22                      # der 21. Wechsel


# ------------------------------------------------------------ Regel-Dateien
def test_format_4_rules_load_and_old_versions_skip():
    for cid in ("wag", "darc-10m", "darc-xmas", "darc-easter"):
        d = CONTESTS[cid].rules
        assert d["format"] == 4 and rulefiles.validate(d) == []
    assert rulefiles.FORMAT_VERSION >= 4


def test_old_contests_unchanged_for_dl(cty):
    """Herkunft „dl“ darf bisherige Contests nicht ändern (DL fällt dort auf „dx“)."""
    c, _ = make("cq160-cw", cty)
    assert c.sent_kind() == "cq_zone" and c.sent_exchange(1) == "14"
    c, _ = make("arrl-10", cty)
    assert c.sent_kind() == "serial"


def test_083_skips_format_4(tmp_path, monkeypatch):
    """Die installierte 0.8.3 (Format 3) überspringt die DARC-Dateien, statt Fehler zu melden."""
    import json
    import shutil
    from gogoham import rulesupdate
    src = tmp_path / "gh"
    src.mkdir()
    for p in rulefiles.BUILTIN_DIR.glob("*.json"):
        shutil.copy(p, src / p.name)
    (src / "index.json").write_text(json.dumps(rulesupdate.make_index(src)), encoding="utf-8")
    (tmp_path / "leer").mkdir()
    monkeypatch.setattr(rulefiles, "BUILTIN_DIR", tmp_path / "leer")
    monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 3)
    res = rulesupdate.check_and_download(src.as_uri() + "/", tmp_path / "data")
    want, rest = builtin_newer_than(3)
    assert sorted(res.skipped) == want
    assert not res.errors and len(res.new) == rest
