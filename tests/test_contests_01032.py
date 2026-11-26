"""0.10.32: 15 neue Contests (Format 18) – JIDX, SAC, RAC Canada Day, NAQP, Alpe Adria VHF,
ARRL Digital, BARTG HF RTTY, DIG-QSO-Party, DTC, AOEC 160 m – und ihre neuen Bausteine."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from gogoham import rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.cty import CtyDB
from gogoham.export import cabrillo_qso_line

HERE = Path(__file__).parent
NEW = ["jidx-cw", "jidx-ph", "sac-cw", "sac-ssb", "canada-day", "naqp-cw", "naqp-ssb",
       "naqp-rtty", "alpe-adria-vhf", "arrl-digi", "bartg-rtty", "dig-ssb", "dig-cw", "dtc",
       "aoec-160"]
EXTRA = """Sweden:                   14:  18:  EU:   58.90:   -15.33:    -1.0:  SM:
    7S,8S,SA,SB,SC,SD,SE,SF,SG,SH,SI,SJ,SK,SL,SM;
Norway:                   14:  18:  EU:   61.00:    -9.00:    -1.0:  LA:
    LA,LB,LC,LD,LE,LF,LG,LH,LI,LJ,LK,LL,LM,LN;
Denmark:                  14:  18:  EU:   56.00:   -10.00:    -1.0:  OZ:
    5P,5Q,OU,OV,OZ;
Greenland:                40:  05:  NA:   74.00:    42.78:     3.0:  OX:
    OX,XP;
Mexico:                   06:  10:  NA:   21.32:   100.23:     6.0:  XE:
    XA,XB,XC,XD,XE,XF;
Ogasawara:                27:  45:  AS:   27.05:  -142.20:    -9.0:  JD/o:
    JD1;
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
        call, ex, band = x[0], x[1], x[2] if len(x) > 2 else "20"
        mode = x[3] if len(x) > 3 else sorted(c.modes)[0]
        t = x[4] if len(x) > 4 else "2026-07-01 12:00:00"
        evs.append(s.evaluate(Qso(id=i + 1, time=t, call=call, band=band, mode=mode,
                                  rst_s="599", rst_r="599", exch_r=ex), commit=True))
    return c, s, evs


def test_files_valid_format_18():
    for cid in NEW:
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert d["format"] == 18 and rulefiles.validate(d) == [], cid
    assert rulefiles.FORMAT_VERSION >= 18


def test_schedules():
    def start(cid, year, i=0):
        return schedule.periods(CONTESTS[cid].rules["schedule"], year)[i][0]
    assert start("jidx-cw", 2027) == datetime(2027, 4, 10, 7)
    assert start("jidx-ph", 2027) == datetime(2027, 11, 13, 7)
    assert start("sac-cw", 2026) == datetime(2026, 9, 19, 12)
    assert start("sac-ssb", 2026) == datetime(2026, 10, 10, 12)
    assert start("canada-day", 2026) == datetime(2026, 7, 1, 0)
    assert [p[0] for p in schedule.periods(CONTESTS["naqp-cw"].rules["schedule"], 2026)] == \
        [datetime(2026, 1, 10, 18), datetime(2026, 8, 1, 18)]
    assert [p[0] for p in schedule.periods(CONTESTS["naqp-ssb"].rules["schedule"], 2026)] == \
        [datetime(2026, 1, 17, 18), datetime(2026, 8, 15, 18)]
    assert [p[0] for p in schedule.periods(CONTESTS["naqp-rtty"].rules["schedule"], 2026)] == \
        [datetime(2026, 2, 28, 18), datetime(2026, 7, 18, 18)]
    assert start("alpe-adria-vhf", 2026) == datetime(2026, 8, 2, 6)
    assert start("arrl-digi", 2026) == datetime(2026, 6, 6, 18)
    assert start("bartg-rtty", 2027) == datetime(2027, 3, 20, 2)
    assert start("dig-ssb", 2026) == datetime(2026, 3, 14, 12)
    assert start("dig-cw", 2026) == datetime(2026, 4, 11, 12)
    assert start("dtc", 2027) == datetime(2027, 10, 3, 7)
    assert start("aoec-160", 2026) == datetime(2026, 11, 21, 16)


def test_jidx(cty):
    c, s, ev = run("jidx-cw", cty, "DL1ABC", [("JA1XX", "10"), ("JA1XX", "10", "40"),
                                             ("JA6YY", "40", "160"), ("W1AW", "05"),
                                             ("JD1BIA", "48")])
    assert [e.points for e in ev] == [1, 1, 4, 0, 1]
    assert not ev[3].valid                                # DX–DX zählt nicht
    assert ev[4].new_mults == [("subdiv", "48")]          # Ogasawara = Präfektur 48
    assert c.validate_exchange("51", cty.lookup("JA1XX")) is not None
    c, s, ev = run("jidx-cw", cty, "JA1ABC", [("DL1XX", "14"), ("JA2YY", "20"),
                                             ("JD1BIA", "48")], district="10")
    assert ev[0].new_mults == [("country", "DL"), ("zone", "14")]
    assert not ev[1].valid and not ev[2].valid          # JA untereinander, auch JD1
    assert c.sent_exchange(1) == "10" and c.cabrillo_name == "JIDX-CW"
    assert CONTESTS["jidx-ph"].cabrillo_name == "JIDX-PH"


def test_sac(cty):
    c, s, ev = run("sac-cw", cty, "DL1ABC", [("SM3XX", "001", "40"), ("7S3YY", "002", "40"),
                                            ("OZ150A", "003"), ("LA/G3XYZ", "004"),
                                            ("DL2XX", "005"), ("OX3XX", "006", "40")])
    assert [e.new_mults for e in ev[:4]] == [[("area", "SM3")], [], [("area", "OZ1")],
                                             [("area", "LA0")]]
    assert not ev[4].valid
    assert ev[5].points == 1                              # DL in Europa: 1 Punkt
    c, s, ev = run("sac-cw", cty, "W1ABC", [("SM3XX", "001", "40"), ("SM3XX", "002", "20")])
    assert [e.points for e in ev] == [3, 1]               # außerhalb Europas: 80/40 m 3
    c, s, ev = run("sac-cw", cty, "SM3ABC", [("DL1XX", "001"), ("W1AW", "002", "40"),
                                            ("LA1XX", "003"), ("OX3XX", "004")])
    assert [e.points for e in ev] == [2, 3, 0, 0]          # OX zählt als Skandinavien
    assert ev[0].new_mults == [("country", "DL")]


def test_canada_day(cty):
    c, s, ev = run("canada-day", cty, "DL1ABC", [("VE3XX", "ON", "20", "CW"),
                                                ("VE3RHQ", "ON", "20", "CW"),
                                                ("VE3XX", "ON", "20", "PH"),
                                                ("DL2XX", "012", "20", "CW")])
    assert [e.points for e in ev] == [10, 20, 10, 2]
    assert ev[2].new_mults == [("subdiv", "ON")]           # Multi je Band und Mode
    assert s.score == 42 * 2
    c, s, ev = run("canada-day", cty, "DL1ABC", [("DL2XX", "001")])
    assert s.score == 2                                    # ohne Multi: Multi 1
    c = CONTESTS["canada-day"](cty, Station(call="VE3ABC", lookup=cty.lookup("VE3ABC")))
    assert c.validate_exchange("017", cty.lookup("VE7XX")) is None   # VE0: Nummer
    assert c.sent_exchange(5) == "005"                     # ohne eigene Provinz: Nummer


def test_naqp(cty):
    c, s, ev = run("naqp-cw", cty, "DL1ABC", [("W1AW", "BOB CT"), ("W1AW", "BOB CT", "40"),
                                             ("VE1AA", "JIM NL"), ("VE1BB", "JOE LB"),
                                             ("XE1XX", "PACO XE"), ("KH6XX", "AL HI"),
                                             ("G3XX", "JOHN")], name="FRANZ")
    assert c.sent_exchange(1) == "FRANZ"
    assert [m for e in ev for m in e.new_mults] == [
        ("state", "CT"), ("state", "CT"), ("province", "NL"), ("country", "XE"), ("state", "HI")]
    assert not ev[6].valid                                  # DX–DX zählt nicht
    assert c.validate_exchange("ED", cty.lookup("W2XX")) is not None
    assert c.validate_exchange("JOHN", cty.lookup("G3XX")) is None
    c = CONTESTS["naqp-ssb"](cty, Station(call="W1ABC", lookup=cty.lookup("W1ABC"),
                                          name="JOHN", state="CT"))
    assert c.sent_exchange(1) == "JOHN CT"
    assert "160" not in CONTESTS["naqp-rtty"].bands


def test_arrl_digi_points_round_up(cty):
    c, s, ev = run("arrl-digi", cty, "DL1ABC", [("DL2XX", "JN59"), ("G3XX", "IO91")],
                   grid="JN59me")
    assert [e.points for e in ev] == [2, 3]                 # mindestens 1 + 1, aufgerundet
    assert s.score == 5 and c.cabrillo_name == "ARRL-DIGI"


def test_bartg(cty):
    c, s, ev = run("bartg-rtty", cty, "DL1ABC", [
        ("W1AW", "001 1200", "20", "RTTY"), ("W6XX", "002 1201", "20", "RTTY"),
        ("JA1XX", "003 1202", "20", "RTTY"), ("DL2XX", "004 1203", "40", "RTTY"),
        ("W1AW", "005 1204", "40", "RTTY")])
    assert ev[0].new_mults == [("country", "K"), ("area", "W1"), ("cont", "NA")]
    assert ev[4].new_mults == [("country", "K"), ("area", "W1")]   # je Band neu, Kontinent nicht
    # 5 Punkte × (Länder 2+2, Gebiete 3+1) × 3 Kontinente
    assert s.score == 5 * 8 * 3 and sum(e.gain for e in ev) == s.score
    assert c.validate_exchange("006", cty.lookup("W1ZZ")) is not None
    assert c.validate_exchange("006 2460", cty.lookup("W1ZZ")) is not None
    assert c.sent_serial("012 1530") == 12


def test_dig(cty):
    c, s, ev = run("dig-cw", cty, "DL1ABC", [
        ("DL2XX", "1234", "20", "CW", "2026-04-11 12:30:00"),
        ("DL3XX", "", "20", "CW", "2026-04-11 12:31:00"),
        ("DL2XX", "1234", "80", "CW", "2026-04-12 07:30:00"),
        ("DL4XX", "555", "80", "CW", "2026-04-11 12:40:00")])
    assert [e.points for e in ev[:3]] == [10, 1, 10]
    assert ev[2].new_mults == [("country", "DL")]           # Mitglied nur einmal, Land je Band
    assert not ev[3].valid                                  # 80 m nur Sonntag 07–09 UTC
    assert c.sent_exchange(1) == "" and c.exchange_optional(cty.lookup("DL3XX"))
    c2 = CONTESTS["dig-cw"](cty, Station(call="DL1ABC", lookup=cty.lookup("DL1ABC"),
                                         member="4711"))
    assert c2.sent_exchange(1) == "4711"


def test_dtc(cty):
    c, s, ev = run("dtc", cty, "DL1ABC", [("DL2XX", "DA", "80"), ("DL0DA", "DA", "80"),
                                         ("OE1XX", "", "80"), ("DL3XX", "plö", "40")],
                   district="RH")
    assert [e.points for e in ev] == [1, 2, 0, 1]
    assert c.validate_exchange("PLÖ", cty.lookup("DL3XX")) is None
    assert s.score == 4 and c.sent_exchange(1) == "RH"
    c = CONTESTS["dtc"](cty, Station(call="OE1ABC", lookup=cty.lookup("OE1ABC")))
    assert c.sent_exchange(1) == "" and c.exchange_optional(cty.lookup("DL2XX")) is False


def test_aoec(cty):
    c, s, ev = run("aoec-160", cty, "DL1ABC", [("OE1XX", "001 WC", "160"),
                                              ("OE3XX", "002 AM", "160"),
                                              ("DL2XX", "003", "160")])
    assert [m for e in ev for m in e.new_mults] == [("subdiv", "WC"), ("country", "OE"),
                                                   ("subdiv", "AM"), ("country", "DL")]
    assert s.score == 3 * 4
    assert c.validate_exchange("004 XX", cty.lookup("OE5XX")) is not None
    assert len(c.host["codes"]) == 94


def test_alpe_adria(cty):
    c, s, ev = run("alpe-adria-vhf", cty, "DL1ABC", [("OE8XX", "001 JN66AA", "2", "CW")],
                   grid="JN59me")
    assert ev[0].points > 300 and c.log_format == "edi"


def test_cabrillo_lines(cty):
    c = CONTESTS["naqp-cw"](cty, Station(call="DL1ABC", lookup=cty.lookup("DL1ABC"),
                                         name="FRANZ"))
    q = Qso(id=1, time="2026-01-10 18:00:00", call="W1AW", band="20", mode="CW",
            freq=14_025_000, exch_s="FRANZ", exch_r="BOB CT")
    assert cabrillo_qso_line(c, q, "DL1ABC").split()[5:] == ["DL1ABC", "FRANZ", "W1AW", "BOB",
                                                             "CT", "0"]


def test_mixed_per_only_from_format_18():
    d = json.loads((rulefiles.BUILTIN_DIR / "dig-cw.json").read_text(encoding="utf-8"))
    d["format"] = 17
    assert any("gleich zählen" in e for e in rulefiles.validate(d))
