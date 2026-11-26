"""0.8.32: YO DX HF Contest und S.M. El Rey de España (King of Spain) CW/SSB."""

import json
from pathlib import Path

import pytest

from gogoham import practice as pm, rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.cty import CtyDB
from gogoham.export import cabrillo_qso_line

HERE = Path(__file__).parent
NEW = ("yodx", "ea-majestad-cw", "ea-majestad-ssb")
EXTRA = """Romania:                  20:  28:  EU:   45.78:   -24.70:    -2.0:  YO:
    YO,YP,YQ,YR;
Spain:                    14:  37:  EU:   40.32:     3.43:    -1.0:  EA:
    AM,AN,AO,EA,EB,EC,ED,EE,EF,EG,EH;
Canary Islands:           33:  36:  AF:   28.32:    15.85:     0.0:  EA8:
    AM8,AN8,AO8,EA8,EB8,EC8,ED8,EE8,EF8,EG8,EH8;
"""


@pytest.fixture(scope="module")
def cty(tmp_path_factory):
    p = tmp_path_factory.mktemp("cty") / "cty.dat"
    p.write_text((HERE / "cty_sample.dat").read_text(encoding="utf-8") + EXTRA, encoding="utf-8")
    return CtyDB.from_file(p)


def run(cty, cid, call, qsos, **st):
    c = CONTESTS[cid](cty, Station(call=call, **st))
    s = Scorer(c)
    evs = []
    for i, (cl, band, mode, ex) in enumerate(qsos, 1):
        q = Qso(id=i, time="2027-05-15 13:00:00", call=cl, band=band, mode=mode, rst_s="599",
                rst_r="599", exch_s=c.sent_exchange(i), exch_r=ex)
        evs.append(s.evaluate(q, commit=True))
    return c, s, evs


def test_files_valid_and_dates():
    for cid in NEW:
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert d["format"] == 7 and rulefiles.validate(d) == [], cid
    s = {cid: CONTESTS[cid].schedule for cid in NEW}
    assert schedule.period(s["yodx"], 2026)[0].isoformat() == "2026-08-22T12:00:00"
    assert schedule.period(s["ea-majestad-cw"], 2026)[0].isoformat() == "2026-05-16T12:00:00"
    assert schedule.period(s["ea-majestad-ssb"], 2026)[0].isoformat() == "2026-06-27T12:00:00"
    assert CONTESTS["ea-majestad-cw"].cabrillo_name == "EA-MAJESTAD-CW"
    assert len(CONTESTS["yodx"].host["codes"]) == 42 and len(CONTESTS["ea-majestad-cw"].host["codes"]) == 53


def test_yodx_as_dl_station(cty):
    c, s, evs = run(cty, "yodx", "DL1ABC", [
        ("YO3AA", "40", "CW", "BU"),         # YO: 8, Kreis + Land
        ("YO3AA", "40", "PH", "BU"),         # anderer Mode: kein Dupe, nichts Neues
        ("OK1AA", "40", "CW", "12"),         # gleicher Kontinent: 2
        ("JA1AA", "40", "CW", "7"),          # anderer Kontinent: 4
        ("DL2AA", "40", "CW", "3"),          # eigenes Land: 1
        ("YO3AA", "40", "CW", "BU"),         # Dupe
        ("YO3AA", "20", "CW", "BU"),         # anderes Band: Kreis und Land neu
    ])
    assert c.sent_exchange(5) == "005"
    assert [e.points for e in evs[:5]] == [8, 8, 2, 4, 1]
    assert sorted(evs[0].new_mults) == [("country", "YO"), ("subdiv", "BU")]
    assert evs[1].new_mults == [] and evs[5].dupe and not evs[1].dupe
    assert sorted(evs[6].new_mults) == [("country", "YO"), ("subdiv", "BU")]
    assert c.validate_exchange("XX", cty.lookup("YO3AA"))


def test_yodx_as_yo_station(cty):
    c, s, evs = run(cty, "yodx", "YO3ZZ", [("YO2AA", "20", "CW", "TM"), ("OK1AA", "20", "CW", "5"),
                                           ("JA1AA", "20", "CW", "9")], district="BU")
    assert c.sent_exchange(1) == "BU"
    assert [e.points for e in evs] == [0, 4, 8]
    assert all(m[0] != "subdiv" for e in evs for m in e.new_mults)   # Kreise nur für DX


def test_king_of_spain_as_dl_station(cty):
    c, s, evs = run(cty, "ea-majestad-cw", "DL1ABC", [
        ("EA4AA", "40", "CW", "M"),          # Spanien: 3, Provinz
        ("EF0F", "40", "CW", "SMR"),         # Station des Königs: Multi SMR
        ("EA8AA", "40", "CW", "tf"),         # Kanaren: Provinz TF, kein Land-Multi
        ("OK1AA", "40", "CW", "17"),         # DX – DX: 1 Punkt, Land-Multi
        ("EA4AA", "40", "PH", "M"),          # Dupe: einmal je Band
    ])
    assert [e.points for e in evs[:4]] == [3, 3, 3, 1]
    assert evs[0].new_mults == [("subdiv", "M")] and evs[1].new_mults == [("subdiv", "SMR")]
    assert evs[2].new_mults == [("subdiv", "TF")]
    assert evs[3].new_mults == [("country", "OK")]
    assert evs[4].dupe
    line = cabrillo_qso_line(c, Qso(id=1, time="2027-05-15 13:00:00", call="EA4AA", band="40",
                                    mode="CW", freq=7012000, rst_s="599", rst_r="599",
                                    exch_s="001", exch_r="M"), "DL1ABC")
    assert line.split()[-4:-1] == ["EA4AA", "599", "M"]


def test_king_of_spain_as_ea_station(cty):
    c, s, evs = run(cty, "ea-majestad-ssb", "EA4ZZ", [("EA1AA", "20", "USB", "LE"),
                                                      ("DL1AA", "20", "USB", "5")], district="M")
    assert c.sent_exchange(1) == "M"
    assert [e.points for e in evs] == [2, 1]


def test_practice_offers_the_new_contests():
    for cid, mode in (("yodx", "CW"), ("yodx", "SSB"), ("ea-majestad-cw", "CW"),
                      ("ea-majestad-ssb", "SSB")):
        assert pm.can_practice(CONTESTS[cid], mode), cid
