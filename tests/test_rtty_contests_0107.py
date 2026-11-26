"""0.10.7: RTTY-Contests (CQ WW RTTY, CQ WPX RTTY, ARRL RTTY Roundup, WAE RTTY) und die neuen
Bausteine von Format 13 (Zone + State/Provinz, „skip_day“, QTC in beide Richtungen)."""

import json
import shutil
from pathlib import Path

import pytest

from conftest import builtin_newer_than

from gogoham import qtc as qtcmod
from gogoham import rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.cty import CtyDB
from gogoham.gui.companions import program_for

HERE = Path(__file__).parent
IDS = ("cqww-rtty", "wpx-rtty", "arrl-rtty", "wae-rtty")


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def make(cty, cid, call="DO2GGH"):
    c = CONTESTS[cid](cty, Station(call=call))
    return c, Scorer(c)


def qso(i, call, exch, band="20", t="2026-09-26 10:00:00"):
    return Qso(id=i, time=t, call=call, band=band, mode="RTTY", freq=0,
               rst_s="599", rst_r="599", exch_s=f"{i:03d}", exch_r=exch)


def test_files_valid_and_program():
    for cid in IDS:
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert rulefiles.validate(d) == [], cid
        assert d["modes"] == ["RY"]
        assert program_for(CONTESTS[cid](None, Station(call="DO2GGH"))) == "fldigi"
    assert rulefiles.FORMAT_VERSION >= 13
    names = {cid: CONTESTS[cid].cabrillo_name for cid in IDS}
    assert names == {"cqww-rtty": "CQ-WW-RTTY", "wpx-rtty": "CQ-WPX-RTTY",
                     "arrl-rtty": "ARRL-RTTY", "wae-rtty": "DARC-WAEDC-RTTY"}


def test_schedules():
    p = lambda cid, y: str(schedule.period(CONTESTS[cid].schedule, y)[0])   # noqa: E731
    assert p("cqww-rtty", 2026) == "2026-09-26 00:00:00"
    assert p("wpx-rtty", 2026) == "2026-02-14 00:00:00"
    assert p("wae-rtty", 2026) == "2026-11-14 00:00:00"
    assert p("arrl-rtty", 2026) == "2026-01-03 18:00:00"
    assert p("arrl-rtty", 2027) == "2027-01-02 18:00:00"
    assert p("arrl-rtty", 2028) == "2028-01-08 18:00:00"        # 1. Januar 2028 = Samstag
    s, e = schedule.period(CONTESTS["arrl-rtty"].schedule, 2027)
    assert (e - s).total_seconds() == 30 * 3600
    bad = {"weekend": "sunday", "skip_day": 1, "month": 1, "hours": 30}   # ab Format 15: full + saturday
    d = json.loads((rulefiles.BUILTIN_DIR / "arrl-rtty.json").read_text(encoding="utf-8"))
    d["schedule"] = bad
    assert any("skip_day" in e for e in rulefiles.validate(d))


def test_cqww_rtty_zone_and_state(cty):
    c, s = make(cty, "cqww-rtty")
    assert c.validate_exchange("05 MA", c.lookup("W1AW")) is None
    assert "State" in c.validate_exchange("05", c.lookup("W1AW"))
    assert c.validate_exchange("04 ON", c.lookup("VE3XX")) is None
    assert c.validate_exchange("14", c.lookup("DL1ABC")) is None
    evs = [s.evaluate(q, commit=True) for q in (
        qso(1, "W1AW", "05 MA"), qso(2, "VE3XX", "04 ON"), qso(3, "DL1ABC", "14"),
        qso(4, "JA1XX", "25"), qso(5, "W1AW", "05 MA", band="40"))]
    assert sorted(evs[0].new_mults) == [("country", "K"), ("state", "MA"), ("zone", "5")]
    assert ("province", "ON") in evs[1].new_mults
    assert [e.points for e in evs] == [3, 3, 1, 3, 3]          # DL–DL 1, andere Kontinente 3
    assert s.mult_count() == 3 + 3 + 2 + 2 + 3                  # 40 m zählt alles neu
    assert c.default_rcvd_exchange(c.lookup("DL1ABC")) == "14"


def test_wpx_rtty_points(cty):
    _c, s = make(cty, "wpx-rtty")
    pts = [s.evaluate(q, commit=True).points for q in (
        qso(1, "W1AW", "1", band="20"), qso(2, "W1AW", "2", band="40"),
        qso(3, "OK1AA", "3", band="15"), qso(4, "OK1AA", "4", band="80"),
        qso(5, "DL1ABC", "5", band="10"), qso(6, "DL1ABC", "6", band="80"))]
    assert pts == [3, 6, 2, 4, 1, 2]
    assert s.mult_count() == 3                                  # W1, OK1, DL1 – einmal


def test_arrl_rtty_dx_station(cty):
    c, s = make(cty, "arrl-rtty")
    assert c.validate_exchange("CT", c.lookup("W1AW")) is None
    assert c.validate_exchange("ON", c.lookup("VE3XX")) is None
    assert c.validate_exchange("12", c.lookup("OK1AA")) is None
    evs = [s.evaluate(q, commit=True) for q in (
        qso(1, "W1AW", "CT"), qso(2, "W1AW", "CT", band="40"), qso(3, "VE3XX", "ON"),
        qso(4, "OK1AA", "12"), qso(5, "DL1ABC", "7"), qso(6, "KH6XX", "3"))]
    assert all(e.valid for e in evs) and [e.points for e in evs] == [1] * 6
    assert evs[1].new_mults == []                               # Multis nur einmal
    assert ("country", "DL") in evs[4].new_mults               # eigenes Land zählt (DXCC)
    assert evs[5].new_mults == [("country", "KH6")]
    assert s.mult_count() == 5                                 # CT, ON, OK, DL, KH6


def test_wae_rtty_everyone_and_qtc_both_ways(cty):
    c, s = make(cty, "wae-rtty")
    ev = s.evaluate(qso(1, "OK1AA", "1", band="80"), commit=True)
    assert ev.valid and ev.gain == 4                           # EU–EU zählt in RTTY, 80 m ×4
    ev = s.evaluate(qso(2, "W1AW", "2", band="40"), commit=True)
    assert ("area", "W1") in ev.new_mults and ev.gain == 2 * (4 + 3) - 4     # 40 m ×3
    assert c.qtc_both_ways() and c.qtc_receiving()
    assert c.qtc_sender_problem(c.lookup("OK1AA"))              # gleicher Kontinent
    assert c.qtc_sender_problem(c.lookup("W1AW")) is None
    have = [qtcmod.Qtc(sender="W1AW", series=1, total=4, qso_call="OK1AA", qso_nr="1")
            for _ in range(4)]
    have += [qtcmod.Qtc(receiver="W1AW", series=1, total=5, qso_call="OK1AA", qso_nr="1")
             for _ in range(5)]
    assert qtcmod.remaining(have, "W1AW", 10, True) == 1        # 4 empfangen + 5 gegeben
    assert qtcmod.give_remaining(have, "W1AW", 10, True) == 1
    assert qtcmod.remaining(have, "W1AW", 10) == 6              # CW/SSB wie bisher
    assert "anderen Kontinent" in qtcmod.receiver_problem(c, "OK1AA", "DO2GGH", [])
    assert qtcmod.receiver_problem(c, "W1AW", "DO2GGH", []) == ""
    dx, _s2 = make(cty, "wae-rtty", "W1AW")
    assert dx.qtc_receiving()                                   # auch außerhalb Europas


def test_older_version_skips_format_13(tmp_path, monkeypatch):
    from gogoham import rulesupdate
    src = tmp_path / "gh"
    src.mkdir()
    for p in rulefiles.BUILTIN_DIR.glob("*.json"):
        shutil.copy(p, src / p.name)
    (src / "index.json").write_text(json.dumps(rulesupdate.make_index(src)), encoding="utf-8")
    monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 12)
    monkeypatch.setattr(rulefiles, "BUILTIN_DIR", tmp_path / "leer")
    (tmp_path / "leer").mkdir()
    res = rulesupdate.check_and_download(src.as_uri() + "/", tmp_path / "data")
    want, rest = builtin_newer_than(12)
    assert sorted(res.skipped) == want
    newer = [w for w in want if w.startswith(("AGCW QRP", "Frankencontest",   # Format 14
                                              "HSC", "Schwaben",            # Format 15
                                              "REF Contest", "PACC",        # Format 16
                                              "ARRL 160", "Stew Perry",     # Format 17
                                              "JIDX", "Scandinavian", "RAC Canada",
                                              "North American", "Alpe Adria", "ARRL International Digital",
                                              "BARTG", "DIG-QSO", "Deutscher Telegrafie",
                                              "All Austrian",               # Format 18
                                              "ARRL November", "Africa All", "Baltic",
                                              "SARTG", "Makrothen", "ARRL June", "ARRL September",
                                              "CQ WW VHF", "IARU Region 1 50",
                                              "IARU Region 1 70",           # Format 19
                                              "EA RTTY", "EA PSK63", "JARL World Wide",
                                              "Alessandro Volta",           # Format 19/20
                                              "New England QSO", "7th Call Area",  # Format 21
                                              "Ohio QSO", "Michigan QSO", "Indiana QSO", "Texas QSO",
                                              "New York QSO", "RSGB", "Oceania", "UK/EI", "PODXS",  # Format 22
                                              "North Carolina QSO", "Washington State Salmon",  # Format 23
                                              "AGCW Handtasten", "AGCW Schlacker", "VFDB DLPX"))]  # Format 24
    assert len(newer) == 10 + 3 + 3 - 2 + 2 + 15 + 14 + 4 + 2 + 11 + 7 + 5
    assert sorted(set(want) - set(newer)) == ["ARRL RTTY Roundup", "CQ WW DX RTTY",
                                              "WAE DX Contest RTTY"]
    assert not res.errors and len(res.new) == rest
