"""0.10.38: deutsche Vereins-Contests (Format 24) – VFDB DLPX (CW/SSB), AGCW Handtastenparty
(80/40 m), AGCW Schlackertasten-Abend."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from gogoham import rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.contests.rulebased import split_serial_class_name
from gogoham.cty import CtyDB

HERE = Path(__file__).parent
NEW = ["vfdb-dlpx-cw", "vfdb-dlpx-ssb", "agcw-htp-80", "agcw-htp-40", "agcw-sta"]


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def run(cid, cty, me, qsos, **st):
    c = CONTESTS[cid](cty, Station(call=me, lookup=cty.lookup(me), **st))
    s = Scorer(c)
    evs = []
    for i, x in enumerate(qsos):
        call, ex = x[0], x[1]
        band = x[2] if len(x) > 2 else c.bands[0]
        mode = x[3] if len(x) > 3 else ("USB" if c.modes == {"PH"} else "CW")
        evs.append(s.evaluate(Qso(id=i + 1, time="2026-02-07 16:30:00", call=call, band=band,
                                  mode=mode, rst_s="599", rst_r="599", exch_r=ex), commit=True))
    return c, s, evs


def test_files_valid():
    for cid in NEW:
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert d["format"] == 24 and rulefiles.validate(d) == [], cid
    assert rulefiles.FORMAT_VERSION >= 24


def test_schedules():
    def per(cid, year):
        return schedule.periods(CONTESTS[cid].rules["schedule"], year)
    assert per("vfdb-dlpx-cw", 2026)[0] == (datetime(2026, 1, 18, 15), datetime(2026, 1, 18, 17))
    assert per("vfdb-dlpx-cw", 2025)[0][0] == datetime(2025, 1, 19, 15)
    assert per("vfdb-dlpx-ssb", 2026)[0][0] == datetime(2026, 3, 22, 15)
    assert per("vfdb-dlpx-ssb", 2027)[0][0] == datetime(2027, 3, 21, 15)
    assert per("agcw-htp-80", 2027)[0] == (datetime(2027, 2, 6, 16), datetime(2027, 2, 6, 19))
    assert per("agcw-htp-40", 2026)[0][0] == datetime(2026, 9, 5, 13)
    assert [p[0] for p in per("agcw-sta", 2026)] == [datetime(2026, 2, 18, 19),
                                                     datetime(2026, 10, 21, 19)]
    assert per("agcw-sta", 2027)[0] == (datetime(2027, 2, 17, 19), datetime(2027, 2, 17, 20, 30))


def test_dlpx(cty):
    c, s, evs = run("vfdb-dlpx-cw", cty, "DL1ABC", [
        ("DL2AA", "001 B36"), ("DL2BB", "002 F05"), ("DK5CC", "003 NM"),
        ("DL2024X", "004 Z99"), ("DL0DBP", "005 Z01"), ("OE1AA", "006 NM"), ("DL2AA", "007 B36")],
        dok="B26")
    assert [e.points for e in evs[:6]] == [1] * 6 and evs[6].dupe
    assert ("area", "DL2") in evs[0].mults and ("area", "DK5") in evs[2].mults
    assert ("area", "DL2") in evs[3].mults                       # DL2024X: zweite Ziffer = Suffix
    assert set(evs[4].mults) == {("area", "DL0"), ("call", "DL0DBP")}
    assert evs[5].mults == []                                    # OE: kein DL-Präfix
    assert s.score == 6 * 4                                      # DL2, DK5, DL0, DL0DBP
    assert c.sent_exchange(3) == "003 B26"
    c2 = CONTESTS["vfdb-dlpx-cw"](cty, Station(call="OE1AA", lookup=cty.lookup("OE1AA")))
    assert c2.sent_exchange(1) == "001 NM"


def test_htp(cty):
    assert split_serial_class_name("001/B/HEINZ/84") == ("001", "B", "HEINZ", "84")
    assert split_serial_class_name("12 a tom xx") == ("12", "A", "TOM", "XX")
    assert split_serial_class_name("001 A") == ("", "", "", "")
    c, s, evs = run("agcw-htp-80", cty, "DL1ABC", [
        ("DL2AA", "001 A TOM 39"), ("DL2BB", "002 B ANNA XX"), ("DL2CC", "003 C OTTO"),
        ("DL2AA", "004 A TOM 39")], pclass="A", name="Franz Muster", age="42")
    assert [e.points for e in evs[:3]] == [9, 7, 5] and evs[3].dupe
    assert s.score == 21
    assert c.sent_exchange(1) == "001/A/FRANZ/42"
    assert c.validate_exchange("001 D TOM") is not None and c.validate_exchange("001 B TOM") is None
    c, s, evs = run("agcw-htp-40", cty, "DL1ABC", [("DL2AA", "001 C TOM 39")], pclass="C")
    assert evs[0].points == 2 and c.sent_exchange(1) == "001/C//XX"      # ohne Name/Alter


def test_sta(cty):
    c, s, evs = run("agcw-sta", cty, "DL1ABC", [
        ("DL2AA", "017/89", "80"), ("DL2AA", "018/89", "40"), ("DL2AA", "019/89", "80")],
        member="89")
    assert [e.points for e in evs[:2]] == [1, 1] and evs[2].dupe
    assert s.score == 2 and c.sent_exchange(17) == "017/89"
