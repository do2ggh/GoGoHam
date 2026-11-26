"""0.10.37: North Carolina QSO Party, Washington Salmon Run, UN DX, PODXS St. Patrick's Day,
New Member Jamboree, Great Pumpkin, Triple Play (Format 23) – und ihre neuen Bausteine."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from gogoham import rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.contests.rulebased import call_suffix, split_member_year
from gogoham.cty import CtyDB

HERE = Path(__file__).parent
NEW = ["ncqp", "wa-salmon-run", "undx", "podxs-stpat", "podxs-nmj", "podxs-pumpkin",
       "podxs-tp-nov", "podxs-tp-dec"]
EXTRA = """Kazakhstan:               17:  30:  AS:   48.17:   -65.18:    -5.0:  UN:
    UN,UO,UP,UQ;
"""


@pytest.fixture(scope="module")
def cty(tmp_path_factory):
    p = tmp_path_factory.mktemp("cty") / "cty.dat"
    p.write_text((HERE / "cty_sample.dat").read_text(encoding="utf-8") + EXTRA, encoding="utf-8")
    return CtyDB.from_file(p)


def run(cid, cty, me, qsos, **st):
    c = CONTESTS[cid](cty, Station(call=me, lookup=cty.lookup(me), **st))
    s = Scorer(c)
    evs = []
    for i, x in enumerate(qsos):
        call, ex = x[0], x[1]
        band = x[2] if len(x) > 2 else "20"
        mode = x[3] if len(x) > 3 else ("PSK31" if c.rig_modes and "PSK31" in c.rig_modes
                                        and c.modes == {"DG"} else "CW")
        evs.append(s.evaluate(Qso(id=i + 1, time="2026-03-21 15:00:00", call=call, band=band,
                                  mode=mode, rst_s="599", rst_r="599", exch_r=ex), commit=True))
    return c, s, evs


def test_files_valid():
    for cid in NEW:
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert rulefiles.validate(d) == [], cid
    assert rulefiles.FORMAT_VERSION >= 23
    assert len(CONTESTS["ncqp"].rules["qso_party"]["counties"]) == 100
    assert len(CONTESTS["wa-salmon-run"].rules["qso_party"]["counties"]) == 39
    assert len(CONTESTS["undx"].rules["host"]["codes"]) == 212


def test_schedules():
    def per(cid, year):
        return schedule.periods(CONTESTS[cid].rules["schedule"], year)
    # NCQP: Sonntag nach dem letzten Samstag im Februar
    for y, d in ((2019, (2, 24)), (2020, (3, 1)), (2025, (2, 23)), (2026, (3, 1)), (2027, (2, 28))):
        assert per("ncqp", y)[0][0] == datetime(y, *d, 15), y
    assert per("wa-salmon-run", 2024) == [(datetime(2024, 9, 21, 16), datetime(2024, 9, 22, 7)),
                                          (datetime(2024, 9, 22, 16), datetime(2024, 9, 23, 0))]
    assert per("undx", 2026)[0] == (datetime(2026, 5, 16, 6), datetime(2026, 5, 16, 21))
    assert per("undx", 2022)[0][0] == datetime(2022, 5, 21, 6)
    assert per("podxs-stpat", 2026)[0][0] == datetime(2026, 3, 21)
    assert per("podxs-nmj", 2028)[0][0] == datetime(2028, 4, 1)        # 1. April = Samstag
    assert per("podxs-pumpkin", 2026)[0] == (datetime(2026, 10, 10, 20), datetime(2026, 10, 11, 20))
    assert per("podxs-tp-nov", 2026)[0] == (datetime(2026, 11, 14), datetime(2026, 11, 17))
    assert per("podxs-tp-dec", 2026)[0][0] == datetime(2026, 12, 12)


def test_ncqp_bonus_stations(cty):
    calls = ["N4H", "N4I", "N4K", "N4E", "N4N"]
    qsos = [(c, "WAK", "20", "CW") for c in calls] + [("N4H", "WAK", "40", "CW"),
                                                     ("W4AA", "MCD", "20", "RTTY")]
    c, s, evs = run("ncqp", cty, "DL1ABC", qsos)
    assert [e.points for e in evs] == [3] * 6 + [5]
    assert s.call_bonus() == 5 * 50                                  # N4H nur einmal
    ev = s.evaluate(Qso(id=99, time="2027-02-28 16:00:00", call="N4C", band="20", mode="CW",
                        rst_s="599", rst_r="599", exch_r="WAK"))
    pts, mults = 6 * 3 + 5, 2
    assert ev.gain == 3 * mults + 50 + 200                          # 6. Station + Sweep
    assert not run("ncqp", cty, "DL1ABC", [("W4AA", "WAK", "20", "FT8")])[2][0].valid


def test_salmon_run_bonus_per_mode(cty):
    c, s, evs = run("wa-salmon-run", cty, "DL1ABC", [
        ("W7DX", "KING", "20", "CW"), ("W7DX", "KING", "40", "CW"), ("W7DX", "KING", "20", "USB"),
        ("K7AA", "CLAL", "20", "CW")])
    assert [e.points for e in evs] == [3, 3, 2, 3]
    assert s.call_bonus() == 1000                                    # je Mode einmal 500
    assert s.score == 11 * 2 + 1000
    assert c.sent_exchange(1) == "DX"


def test_undx(cty):
    c, s, evs = run("undx", cty, "DL1ABC", [
        ("UN7AA", "L17", "20", "CW"), ("UN7AA", "L17", "20", "USB"), ("UN7BB", "Z04", "40", "CW"),
        ("DL2AA", "001", "20", "CW"), ("OE1AA", "002", "20", "CW"), ("JA1AA", "003", "20", "CW")])
    assert [e.points for e in evs] == [10, 10, 10, 2, 3, 5]
    assert set(evs[0].mults) == {("subdiv", "L17"), ("country", "UN")}   # KZ zählt doppelt
    assert s.mult_count() == 2 + 2 + 3                               # L17,UN / Z04,UN / DL,OE,JA
    assert c.validate_exchange("L1", cty.lookup("UN7AA")) is not None
    c, s, evs = run("undx", cty, "UN7AA", [("UN7BB", "A01"), ("DL1ABC", "001")], district="L17")
    assert c.sent_exchange(1) == "L17" and [e.points for e in evs] == [10, 5]   # DL = anderer Kontinent


def test_stpat_suffix_bonus(cty):
    assert call_suffix("W4KRN") == "KRN" and call_suffix("DL/W4KRN/P") == "KRN"
    assert call_suffix("2E0ABC") == "ABC" and call_suffix("DL") == ""
    word = ["K1E", "K1R", "K1I", "K1N"]                              # ERIN
    c, s, evs = run("podxs-stpat", cty, "DL1ABC", [(x + "AA", "CT") for x in word])
    assert s.call_bonus() == 100                                     # Suffixe EAA, RAA … -> ERIN
    assert s.letters == {"E": 1, "R": 1, "I": 1, "N": 1}
    assert c.suffix_value({"E": 1, "R": 1, "I": 1, "N": 1}) == 100
    full = {"E": 1, "R": 2, "I": 1, "N": 1, "G": 2, "O": 1, "B": 1, "A": 1, "H": 1}
    assert c.suffix_value(full) == 500
    assert c.suffix_value(dict(full, R=1)) == 200                    # R fehlt für ERIN + BRAGH
    assert s.score == 4 * 2 + 100                                    # K + CT; ERIN


def test_nmj(cty):
    assert split_member_year("483 2006") == ("483", "2006") and split_member_year("TU") == ("", "")
    c, s, evs = run("podxs-nmj", cty, "DL1ABC", [
        ("K5SP", "483 2006"), ("W1AW", "3500 2026"), ("W2AA", "TU 73"), ("W3AA", "1200 2006")],
        member="")
    assert [e.points for e in evs] == [5, 11, 3, 7]
    assert s.mult_count() == 2                                       # 2006, 2026
    assert s.score == 26 * 2
    assert c.sent_exchange(1) == "NM"


def test_pumpkin_and_triple_play(cty):
    c, s, evs = run("podxs-pumpkin", cty, "DL1ABC", [("W1AW", "CT", "160"), ("W1AW", "CT", "160")])
    assert evs[1].dupe and evs[0].points == 1
    c, s, evs = run("podxs-tp-nov", cty, "DL1ABC", [
        ("W1AW", "CT", "40"), ("W1AW", "CT", "80"), ("W1AW", "CT", "160"), ("VE3AA", "ON", "160")])
    assert [e.points for e in evs] == [1, 2, 3, 3]
    assert s.mult_count() == 4                                       # K, CT, VE, ON – nicht je Band
