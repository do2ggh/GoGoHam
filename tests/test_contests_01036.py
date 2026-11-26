"""0.10.36: Contest-Paket (Format 22) – US-QSO-Partys Ohio, Michigan, Indiana, Texas, New York;
RSGB 1.8 MHz; Oceania DX; UK/EI DX CW; PSKFest – und ihre neuen Bausteine."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from gogoham import rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.cty import CtyDB
from gogoham.export import cabrillo_qso_line

HERE = Path(__file__).parent
NEW = ["ohqp", "miqp", "inqp", "txqp", "nyqp", "rsgb-160-feb", "rsgb-160-nov", "ocdx-ssb",
       "ocdx-cw", "ukei-cw", "pskfest"]
EXTRA = """France:                   14:  27:  EU:   46.00:    -2.00:    -1.0:  F:
    F,HW,HX,HY,TH,TM,TO,TP,TQ,TV,TW,TX;
Ireland:                  14:  27:  EU:   53.13:     8.02:     0.0:  EI:
    EI,EJ;
New Zealand:              32:  60:  OC:  -41.83:  -173.27:   -12.0:  ZL:
    ZL,ZM;
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
        mode = x[3] if len(x) > 3 else "CW"
        t = x[4] if len(x) > 4 else "2026-05-02 15:00:00"
        evs.append(s.evaluate(Qso(id=i + 1, time=t, call=call, band=band, mode=mode,
                                  rst_s="599", rst_r="599", exch_r=ex), commit=True))
    return c, s, evs


def test_files_valid():
    for cid in NEW:
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert d["format"] == 22 and rulefiles.validate(d) == [], cid
    assert rulefiles.FORMAT_VERSION >= 22
    n = {cid: len(CONTESTS[cid].rules["qso_party"]["counties"])
         for cid in ("ohqp", "miqp", "inqp", "txqp", "nyqp")}
    assert n == {"ohqp": 88, "miqp": 83, "inqp": 92, "txqp": 254, "nyqp": 62}
    assert len(CONTESTS["rsgb-160-feb"].rules["host"]["codes"]) == 129
    assert len(CONTESTS["ukei-cw"].rules["host"]["codes"]) == 155


def test_schedules():
    def first(cid, year):
        return schedule.periods(CONTESTS[cid].rules["schedule"], year)[0][0]
    assert first("ohqp", 2027) == datetime(2027, 8, 28, 16)
    assert first("miqp", 2026) == datetime(2026, 4, 18, 16)
    assert first("miqp", 2027) == datetime(2027, 4, 17, 16)
    assert first("inqp", 2026) == datetime(2026, 5, 2, 15)
    assert schedule.periods(CONTESTS["txqp"].rules["schedule"], 2024) == [
        (datetime(2024, 9, 21, 14), datetime(2024, 9, 22, 2)),
        (datetime(2024, 9, 22, 14), datetime(2024, 9, 22, 20))]
    assert first("nyqp", 2026) == datetime(2026, 10, 17, 14)
    assert first("rsgb-160-feb", 2026) == datetime(2026, 2, 14, 20)
    assert first("rsgb-160-feb", 2025) == datetime(2025, 2, 8, 20)
    assert first("rsgb-160-nov", 2026) == datetime(2026, 11, 21, 20)
    assert first("rsgb-160-nov", 2024) == datetime(2024, 11, 16, 20)
    assert first("ocdx-ssb", 2026) == datetime(2026, 10, 3, 6)
    assert first("ocdx-cw", 2026) == datetime(2026, 10, 10, 6)
    assert first("ocdx-ssb", 2023) == datetime(2023, 10, 7, 6)
    for y, d in ((2025, 26), (2026, 25), (2027, 24), (2028, 29), (2029, 28), (2030, 27)):
        assert first("ukei-cw", y) == datetime(y, 4, d, 12)        # Tabelle des Veranstalters
    assert first("pskfest", 2027) == datetime(2027, 1, 2, 0)
    assert first("pskfest", 2022) == datetime(2022, 1, 8, 0)       # 1. Januar = Samstag


def test_ohio_michigan_per_mode(cty):
    c, s, evs = run("ohqp", cty, "DL1ABC", [
        ("W8AA", "FRAN", "20", "CW"), ("W8AA", "FRAN", "20", "USB"),     # Multi je Mode
        ("W8AA", "FRAN", "40", "CW"), ("W8BB", "FRAN/DELA", "20", "CW"),  # keine County-Grenze
        ("W8BB", "xxxx", "20", "CW")])
    assert [e.points for e in evs[:3]] == [2, 1, 2]
    assert s.mult_count() == 2                                     # FRAN auf CW und SSB
    assert c.validate_exchange("FRAN/DELA") is not None
    assert not evs[4].valid
    assert s.score == 5 * 2
    c, s, evs = run("miqp", cty, "DL1ABC", [("W8MQP", "KZOO", "20", "CW"),
                                            ("W8MQP", "KZOO", "20", "CW")])
    assert evs[0].points == 2 and evs[1].dupe and "160" not in c.bands


def test_indiana_county_line(cty):
    c, s, evs = run("inqp", cty, "DL1ABC", [
        ("W9AA", "INMRN/DEL", "20", "CW"), ("W9BB", "INMRN", "20", "USB")])
    assert evs[0].points == 4 and set(evs[0].mults) == {("county", "INMRN"), ("county", "INDEL")}
    assert evs[1].points == 2
    assert s.mult_count() == 3                                     # 2× CW + INMRN auf SSB
    assert c.validate_exchange("INMRN/INDEL/INOHI") is not None   # höchstens 2 Countys


def test_texas_mobile_bonus(cty):
    counties = ["HARR", "MGMY", "BEE", "BEXA", "BELL", "AUST"]
    qsos = [("K5M/M", co, "20", "CW") for co in counties] + [("W5AA", "HARR", "40", "USB")]
    c, s, evs = run("txqp", cty, "DL1ABC", qsos)
    assert [e.points for e in evs] == [3] * 6 + [2]
    assert s.mult_count() == 6
    assert s.mobile_bonus() == 500                                 # 6 Countys = einmal 5
    assert s.score == (6 * 3 + 2) * 6 + 500
    assert evs[4].gain == (5 * 3) * 5 + 500 - (4 * 3) * 4          # 5. County bringt den Bonus
    assert c.validate_exchange("HARR/MGMY") is not None            # je County eigene Zeile
    assert "6" in c.bands and "60" not in c.bands and "30" not in c.bands


def test_new_york(cty):
    c, s, evs = run("nyqp", cty, "DL1ABC", [
        ("W2AA", "DUT", "20", "CW"), ("W2AA", "DUT", "20", "USB"), ("W2AA", "DUT", "20", "RTTY"),
        ("W2BB", "NEW", "20", "FT8")])
    assert [e.points for e in evs[:3]] == [2, 1, 3] and not evs[3].valid
    assert s.score == 6 * 1                                        # DUT einmal im Contest


def test_rsgb_160(cty):
    c, s, evs = run("rsgb-160-feb", cty, "DL1ABC", [
        ("G3AAA", "001 OX", "160", "CW"), ("G3AAA", "002 OX", "160", "LSB"),
        ("GM3BBB", "003 AB", "160", "CW"), ("OE1AA", "004", "160", "CW"),
        ("DL2AA", "005", "160", "CW"), ("G3AAA", "006 OX", "160", "CW")])
    assert [e.points for e in evs[:5]] == [2] * 5 and evs[5].dupe
    assert ("country", "G") not in evs[0].mults
    assert s.mult_count() == 4                                     # OX, AB, OE, DL
    assert s.score == 5 * 2 + 4 * 5                                # Punkte + Bonus
    assert evs[0].gain == 2 + 5 and evs[1].gain == 2
    line = cabrillo_qso_line(c, Qso(time="2026-02-14 20:00:00", call="OE1AA", band="160",
                                    freq=1_830_000, mode="CW", rst_s="599", rst_r="599",
                                    exch_s="001", exch_r="4"), "DL1ABC")
    assert line.split()[5:] == ["DL1ABC", "599", "001", "--", "OE1AA", "599", "4", "--", "0"] \
        or line.split()[5:-1] == ["DL1ABC", "599", "001", "--", "OE1AA", "599", "4", "--"]
    assert CONTESTS["rsgb-160-nov"].modes == {"CW"}


def test_oceania(cty):
    c, s, evs = run("ocdx-cw", cty, "DL1ABC", [
        ("VK2AA", "001", "20"), ("ZL1AA", "002", "80"), ("VK2BB", "003", "20"),
        ("W1AW", "004", "20")])
    assert [e.points for e in evs[:3]] == [1, 10, 1]
    assert not evs[3].valid and "Ozeanien" in evs[3].warning
    assert s.score == 12 * 2                                       # VK2, ZL1
    c, s, evs = run("ocdx-cw", cty, "VK2AA", [("W1AW", "001", "10")])
    assert evs[0].valid and evs[0].points == 3


def test_ukei(cty):
    c, s, evs = run("ukei-cw", cty, "DL1ABC", [
        ("G4AAA", "001 LD", "20"), ("G4AAA", "002 LD", "80"), ("F5AA", "003", "20"),
        ("W1AW", "004", "20"), ("EI7CC", "005 DU", "40")])
    assert [e.points for e in evs] == [2, 4, 1, 2, 4]
    assert evs[0].mults == [("subdiv", "LD")]                      # UK zählt nur als Bezirk
    assert s.mult_count() == 5                                     # LD 20/80, F, K, DU
    c, s, evs = run("ukei-cw", cty, "G4AAA", [
        ("W1AW", "001", "20", "CW", "2026-04-26 02:00:00"),
        ("W1AW", "002", "40", "CW", "2026-04-26 12:00:00"),
        ("DL1ABC", "003", "20", "CW", "2026-04-26 05:00:00")], district="LD")
    assert [e.points for e in evs] == [8, 8, 2]                    # nachts doppelt
    assert c.sent_exchange(7) == "007 LD"


def test_pskfest(cty):
    c, s, evs = run("pskfest", cty, "DL1ABC", [
        ("W1AW", "CT", "20", "PSK31"), ("K3AA", "DC", "20", "PSK31"), ("K3BB", "MD", "40", "PSK31"),
        ("VE3AA", "ON", "20", "PSK31"), ("OE1AA", "OE", "20", "PSK31"), ("W1AW", "CT", "20", "PSK31")])
    assert [e.points for e in evs[:5]] == [1] * 5 and evs[5].dupe
    assert set(evs[0].mults) == {("state", "CT"), ("country", "K")}
    assert ("state", "MD") in evs[1].mults                         # DC zählt als MD
    assert s.mult_count() == 6                                     # K, CT, MD, VE, ON, OE
    assert s.score == 5 * 6
    assert c.sent_exchange(1) == "DL" and c.log_format == "adif"


def test_adif_psk_submode():
    from gogoham.bands import adif_mode
    assert adif_mode("PSK31") == ("PSK", "PSK31") and adif_mode("BPSK63") == ("PSK", "PSK63")
