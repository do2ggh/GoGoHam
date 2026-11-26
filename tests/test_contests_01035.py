"""0.10.35: QSO-Partys New England (NEQP) und 7QP (Format 21) – County-Kürzel, County-Grenzen,
Dupe je County, nur Stationen außerhalb des Gebiets."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from gogoham import rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.cty import CtyDB
from gogoham.export import cabrillo_qso_line

HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def run(cid, cty, me, qsos, **st):
    c = CONTESTS[cid](cty, Station(call=me, lookup=cty.lookup(me), **st))
    s = Scorer(c)
    evs = []
    for i, x in enumerate(qsos):
        call, ex, band, mode = x[0], x[1], x[2] if len(x) > 2 else "20", x[3] if len(x) > 3 else "CW"
        evs.append(s.evaluate(Qso(id=i + 1, time="2026-05-02 21:00:00", call=call, band=band,
                                  mode=mode, rst_s="599", rst_r="599", exch_r=ex), commit=True))
    return c, s, evs


def test_files_valid_and_counties():
    for cid, n in (("neqp", 68), ("7qp", 259)):
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert d["format"] == 21 and rulefiles.validate(d) == [], cid
        assert len(set(d["qso_party"]["counties"])) == n
    assert rulefiles.FORMAT_VERSION >= 21
    ne = CONTESTS["neqp"].rules["qso_party"]["counties"]
    assert sum(c.startswith("CT") for c in ne) == 9 and sum(c.startswith("ME") for c in ne) == 16
    q7 = CONTESTS["7qp"].rules["qso_party"]["counties"]
    assert sum(c.startswith("MT") for c in q7) == 56 and "ORDES" in q7 and "AZYVP" in q7


def test_schedules():
    def periods(cid, year):
        return [(p[0], p[1]) for p in schedule.periods(CONTESTS[cid].rules["schedule"], year)]
    assert periods("neqp", 2026) == [(datetime(2026, 5, 2, 20), datetime(2026, 5, 3, 5)),
                                     (datetime(2026, 5, 3, 13), datetime(2026, 5, 4, 0))]
    assert periods("7qp", 2026) == [(datetime(2026, 5, 2, 13), datetime(2026, 5, 3, 7))]
    assert periods("7qp", 2027)[0][0] == datetime(2027, 5, 1, 13)        # 1. Mai = Samstag
    assert periods("neqp", 2027)[0][0] == datetime(2027, 5, 1, 20)


def test_neqp(cty):
    c, s, evs = run("neqp", cty, "DL1ABC", [
        ("W1AW", "CTCAP", "20", "CW"), ("W1AW", "CTCAP", "20", "USB"),   # CW 2, SSB 1
        ("W1AW", "CTCAP", "20", "CW"),                                   # Dupe
        ("W1AW", "CTCAP", "40", "CW"),                                   # anderes Band
        ("K1M", "MA MID", "20", "CW"), ("K1M", "MAMID", "20", "CW"),     # Dupe, gleiche Schreibweise
        ("K1M", "MANOR", "20", "CW"),                                    # Mobil: neues County
        ("K5ZD", "TX", "20", "CW")])                                     # außerhalb: zählt nicht
    assert [e.points for e in evs[:2]] == [2, 1] and evs[2].dupe and not evs[3].dupe
    assert evs[5].dupe and not evs[6].dupe
    assert not evs[7].valid and "Neuengland" in evs[7].warning
    assert s.mult_count() == 3                                           # CTCAP, MAMID, MANOR
    assert s.score == (2 + 1 + 2 + 2 + 2) * 3
    assert c.sent_exchange(1) == "DX"
    assert c.validate_exchange("CTCAP/CTWES") is not None                # je County ein QSO
    assert c.validate_exchange("XXXXX") is not None and c.validate_exchange("vtadd") is None
    line = cabrillo_qso_line(c, Qso(time="2026-05-02 21:00:00", call="W1AW", band="20",
                                    freq=14_030_000, mode="CW", rst_s="599", rst_r="599",
                                    exch_s="DX", exch_r="CTCAP"), "DL1ABC")
    assert line.split()[5:11] == ["DL1ABC", "599", "DX", "W1AW", "599", "CTCAP"]


def test_neqp_us_station_outside_and_inside(cty):
    c, s, evs = run("neqp", cty, "K5ZD", [("W1AW", "CTCAP")], state="tx")
    assert c.sent_exchange(1) == "TX" and evs[0].points == 2
    c, s, evs = run("neqp", cty, "W1AW", [("K5ZD", "TX")], state="CT")
    assert not evs[0].valid and "nur für Stationen außerhalb" in evs[0].warning


def test_7qp_county_line_and_modes(cty):
    c, s, evs = run("7qp", cty, "DL1ABC", [
        ("W7AA", "ORDES", "20", "CW"), ("W7AA", "ORDES", "20", "USB"),
        ("W7AA", "ORDES", "20", "RTTY"), ("W7AA", "ORDES", "20", "PSK31"),  # RTTY = Digital: Dupe
        ("K7CL", "UTRIC/IDBEA", "20", "CW"),                                # County-Grenze: 2×
        ("K7CL", "ORDES/JEF", "40", "CW"),                                  # Staat nur einmal
        ("K7CL", "WAKIN", "20", "FT8")])                                    # FT8 verboten
    assert [e.points for e in evs[:3]] == [3, 2, 4] and evs[3].dupe
    assert evs[4].points == 6 and set(evs[4].mults) == {("county", "UTRIC"), ("county", "IDBEA")}
    assert evs[5].points == 6 and ("county", "ORJEF") in evs[5].mults
    assert not evs[6].valid
    assert s.mult_count() == 4                                       # ORDES, UTRIC, IDBEA, ORJEF
    assert s.score == (3 + 2 + 4 + 6 + 6) * 4
