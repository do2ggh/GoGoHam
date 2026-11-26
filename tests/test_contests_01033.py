"""0.10.33: 14 neue Contests (Format 19) – ARRL Sweepstakes, Africa All Mode, Baltic, SARTG
WW und Neujahr, Makrothen, ARRL June/September VHF, CQ WW VHF, IARU 50/70 MHz, Alpe Adria
UHF – und ihre neuen Bausteine."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from gogoham import bands, rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.contests.rulebased import grid_km, split_serial_name, split_ss
from gogoham.cty import CtyDB
from gogoham.export import cabrillo_qso_line

HERE = Path(__file__).parent
NEW = ["arrl-ss-cw", "arrl-ss-ssb", "af-all-mode", "baltic", "sartg-rtty", "sartg-ny-rtty",
       "makrothen", "arrl-vhf-jun", "arrl-vhf-sep", "cqww-vhf", "cqww-vhf-digi", "iaru-50",
       "iaru-70", "alpe-adria-uhf"]
EXTRA = """Sweden:                   14:  18:  EU:   58.90:   -15.33:    -1.0:  SM:
    7S,8S,SA,SB,SC,SD,SE,SF,SG,SH,SI,SJ,SK,SL,SM;
Norway:                   14:  18:  EU:   61.00:    -9.00:    -1.0:  LA:
    LA,LB,LC,LD,LE,LF,LG,LH,LI,LJ,LK,LL,LM,LN;
Denmark:                  14:  18:  EU:   56.00:   -10.00:    -1.0:  OZ:
    5P,5Q,OU,OV,OZ;
Finland:                  15:  18:  EU:   61.38:   -24.82:    -2.0:  OH:
    OF,OG,OH,OI,OJ;
Lithuania:                15:  29:  EU:   55.45:   -23.63:    -2.0:  LY:
    LY;
Latvia:                   15:  29:  EU:   57.03:   -24.65:    -2.0:  YL:
    YL;
South Africa:             38:  57:  AF:  -29.07:   -22.63:    -2.0:  ZS:
    H5,S4,S8,V9,ZR,ZS,ZT,ZU;
Canary Islands:           33:  36:  AF:   28.32:    15.85:     0.0:  EA8:
    AM8,AN8,AO8,EA8,EB8,EC8,ED8,EE8,EF8,EG8,EH8;
Italy:                    15:  28:  EU:   42.82:   -12.58:    -1.0:  I:
    I;
African Italy:            33:  37:  AF:   35.67:   -12.67:    -1.0:  *IG9:
    IG9,IH9;
Alaska:                   01:  01:  NA:   61.40:   148.87:     8.0:  KL:
    AL,KL,NL,WL;
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
        t = x[4] if len(x) > 4 else "2026-07-04 15:00:00"
        evs.append(s.evaluate(Qso(id=i + 1, time=t, call=call, band=band, mode=mode,
                                  rst_s="599", rst_r="599", exch_r=ex), commit=True))
    return c, s, evs


def test_files_valid_format_19():
    for cid in NEW:
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert d["format"] == 19 and rulefiles.validate(d) == [], cid
    assert rulefiles.FORMAT_VERSION >= 19


def test_new_bands_222_902():
    assert bands.band_for_freq(222_100_000) == "1.25"
    assert bands.band_for_freq(903_100_000) == "33cm"
    assert bands.band_label("1.25") == "1.25 m" and bands.adif_band("1.25") == "1.25M"
    assert bands.band_from_adif("1.25m") == "1.25" and bands.band_from_adif("33cm") == "33cm"
    assert bands.CABRILLO_VHF["1.25"] == "222" and bands.CABRILLO_VHF["33cm"] == "902"


def test_schedules():
    def periods(cid, year):
        return [p[0] for p in schedule.periods(CONTESTS[cid].rules["schedule"], year)]
    assert periods("arrl-ss-cw", 2026) == [datetime(2026, 11, 7, 21)]
    assert periods("arrl-ss-ssb", 2026) == [datetime(2026, 11, 21, 21)]
    p = schedule.periods(CONTESTS["arrl-ss-cw"].rules["schedule"], 2026)[0]
    assert p[1] == datetime(2026, 11, 9, 3)                   # bis 0259 UTC Montag
    assert periods("af-all-mode", 2026) == [datetime(2026, 3, 28, 12)]
    assert periods("af-all-mode", 2027) == [datetime(2027, 3, 27, 12)]
    assert periods("baltic", 2026) == [datetime(2026, 5, 16, 21)]
    assert periods("sartg-rtty", 2026) == [datetime(2026, 8, 15, 0), datetime(2026, 8, 15, 16),
                                           datetime(2026, 8, 16, 8)]
    assert periods("sartg-ny-rtty", 2027) == [datetime(2027, 1, 1, 8)]
    assert periods("makrothen", 2027) == [datetime(2027, 10, 9, 0), datetime(2027, 10, 9, 16),
                                          datetime(2027, 10, 10, 8)]
    assert periods("arrl-vhf-jun", 2026) == [datetime(2026, 6, 13, 18)]
    assert periods("arrl-vhf-sep", 2026) == [datetime(2026, 9, 12, 18)]
    assert periods("cqww-vhf", 2026) == [datetime(2026, 7, 4, 14)]
    assert periods("cqww-vhf-digi", 2026) == [datetime(2026, 7, 18, 14)]
    assert periods("cqww-vhf", 2027) == [datetime(2027, 7, 3, 14)]
    assert periods("iaru-50", 2026) == [datetime(2026, 6, 20, 14)]
    assert periods("iaru-70", 2026) == [datetime(2026, 7, 18, 14)]
    assert periods("alpe-adria-uhf", 2026) == [datetime(2026, 6, 21, 7)]


def test_sweepstakes_exchange_and_score(cty):
    assert split_ss("43 M W1AW 31 CT") == ("43", "M", "31", "CT")
    assert split_ss("43M 31 ntx") == ("43", "M", "31", "NTX")
    st = dict(state="CT", lic_year="1979", cat_power="LOW")
    c, s, evs = run("arrl-ss-cw", cty, "W1AW", [
        ("K5ZD", "43 M 31 EMA", "40"), ("K5ZD", "44 M 31 EMA", "20"),   # Dupe (nur einmal)
        ("VE3AA", "12 B 65 ONS", "20"), ("KL7RA", "3 A 70 AK", "80"),
        ("DL1ABC", "1 A 80 CT", "20")], **st)
    assert c.sent_exchange(7) == "7 A W1AW 79 CT"
    assert evs[1].dupe
    assert "USA/Kanada" in evs[4].warning
    assert s.score == 2 * 3 * 3                              # 3 QSOs × 2 Punkte × 3 Sections
    assert c.validate_exchange("43 M 31") is not None        # Section fehlt
    assert c.validate_exchange("43 M W1AW 31 EMA") is None
    line = cabrillo_qso_line(c, Qso(time="2026-11-07 21:00:00", call="K5ZD", band="40",
                                    freq=7_030_000, mode="CW", exch_s=c.sent_exchange(1),
                                    exch_r="43 M K5ZD 31 EMA"), "W1AW")
    assert line.split()[6:] == ["1", "A", "79", "CT", "K5ZD", "43", "M", "31", "EMA", "0"]
    assert c.uses_serial
    # Precedence aus den Kategorien
    for kw, prec in ((dict(cat_power="QRP"), "Q"), (dict(cat_power="HIGH"), "B"),
                     (dict(cat_assisted="ASSISTED"), "U"), (dict(cat_operator="MULTI-OP"), "M")):
        cc = CONTESTS["arrl-ss-cw"](cty, Station(call="W1AW", lookup=cty.lookup("W1AW"), **kw))
        assert cc.ss_precedence() == prec
    # DX-Stationen nehmen nicht teil
    _c, _s, evs = run("arrl-ss-cw", cty, "DL1ABC", [("W1AW", "1 A 79 CT")])
    assert "USA/Kanada" in evs[0].warning


def test_africa_all_mode(cty):
    c, s, evs = run("af-all-mode", cty, "DL1ABC", [
        ("ZS6A", "001", "20", "CW"), ("ZS6A", "002", "20", "USB"),   # neuer Multi je Mode
        ("ZS6A", "003", "20", "CW"),                                  # Dupe
        ("EA8AA", "004", "15", "CW"), ("G3AAA", "005", "15", "CW"),  # G: Punkt, kein Multi
        ("IG9A", "006", "15", "CW")])                                 # IG9 = Italien im DXCC
    assert evs[2].dupe
    assert s.total_points == 5 and s.mult_count() == 3 and s.score == 15


def test_baltic(cty):
    c, s, _ = run("baltic", cty, "DL1ABC", [
        ("LY2AA", "001", "80", "CW", "2026-05-16 21:10:00"),
        ("LY2AA", "002", "80", "USB", "2026-05-16 21:20:00"),          # neu in SSB
        ("G3AAA", "003", "80", "CW"), ("UA3AA", "004", "80", "CW")])   # RU zählt nicht
    assert s.score == 10 + 10 + 1
    _c, s, _ = run("baltic", cty, "W1AW", [("LY2AA", "001", "80", "CW"), ("G3AAA", "002", "80", "CW")])
    assert s.score == 20 + 1
    _c, s, _ = run("baltic", cty, "LY2AA", [("YL2AA", "001", "80", "CW"), ("W1AW", "002", "80", "CW")])
    assert s.score == 1 + 2
    seg = c.segment_problem(Qso(call="LY2AA", band="80", mode="CW", freq=3_650_000))
    assert seg and "3510" in seg


def test_sartg_ww(cty):
    c, s, evs = run("sartg-rtty", cty, "DL1ABC", [
        ("DL2ZZ", "001", "20", "RTTY"), ("G3AAA", "002", "20", "RTTY"),
        ("W1AW", "003", "20", "RTTY"), ("WA4AA", "004", "20", "RTTY"),
        ("JA1AA", "005", "15", "RTTY")])
    assert [e.points for e in evs] == [5, 10, 15, 15, 15]
    # Länder: DL, G, K (20) + JA (15); Gebiete: W1, W4 (20) + JA1 (15)
    assert s.mult_count() == 4 + 3
    assert s.score == 60 * 7


def test_sartg_new_year(cty):
    assert split_serial_name("049 vlad") == ("049", "VLAD")
    c, s, evs = run("sartg-ny-rtty", cty, "DL1ABC", [
        ("SM5FUG", "049 JAN", "80", "RTTY"), ("7S5AA", "012 OLLE", "80", "RTTY"),  # SM5 = 7S5
        ("OZ150A", "003 BO", "80", "RTTY"), ("LA/G3XYZ", "004 JOHN", "80", "RTTY"),
        ("G3AAA", "005 TOM", "80", "RTTY"), ("SM5FUG", "050 JAN", "40", "RTTY")],
        name="FRANZ")
    assert c.sent_exchange(7) == "007 FRANZ"
    mults = sorted(v for e in evs for _t, v in e.new_mults)
    assert mults == ["G", "LA0", "OZ1", "SM5", "SM5"]          # ohne Ziffer: 10. Gebiet (0)
    assert s.score == 6 * 5
    assert c.validate_exchange("049") is not None


def test_makrothen(cty):
    assert int(grid_km("CM87", "EL49", 6378.16)) == 3084            # Beispiel der Ausschreibung
    c, s, evs = run("makrothen", cty, "W6AA", [
        ("W4AA", "EL49", "20", "RTTY"), ("W4AA", "EL49", "40", "RTTY"),
        ("W4AA", "EL49", "80", "RTTY"), ("W6BB", "CM87", "80", "RTTY")], grid="CM87")
    assert [e.points for e in evs] == [3084, 4626, 6168, 100]
    assert s.score == 3084 + 4626 + 6168 + 100
    assert c.validate_exchange("EL49AB") is not None             # nur 4 Stellen
    assert c.validate_exchange("el49") is None


def test_cq_vhf_and_arrl_vhf(cty):
    c, s, evs = run("cqww-vhf", cty, "DL1ABC", [
        ("G3AAA", "IO91", "6", "USB"), ("G4BBB", "IO91", "6", "CW"),
        ("G3AAA", "IO91", "2", "USB"), ("OE1AA", "JN88", "2", "USB")], grid="JO62")
    assert [e.points for e in evs] == [1, 1, 2, 2]
    assert s.mult_count() == 3 and s.score == 6 * 3
    line = cabrillo_qso_line(c, Qso(time="2026-07-04 15:00:00", call="G3AAA", band="6",
                                    mode="USB", exch_s="JO62", exch_r="IO91"), "DL1ABC")
    assert line.split()[1:] == ["50", "PH", "2026-07-04", "1500", "DL1ABC", "JO62", "G3AAA",
                                "IO91", "0"]
    c, s, evs = run("arrl-vhf-jun", cty, "W1AW", [
        ("K1AA", "FN42", "6"), ("K1AA", "FN42", "1.25"), ("K1AA", "FN42", "33cm"),
        ("K1AA", "FN42", "13cm"), ("DL1ABC", "JO62", "6")], grid="FN31")
    assert [e.points for e in evs] == [1, 2, 3, 4, 1]
    assert s.score == 11 * 5
    _c, _s, evs = run("arrl-vhf-sep", cty, "DL1ABC", [("G3AAA", "IO91", "6"), ("W1AW", "FN31", "6")])
    assert "W/VE" in evs[0].warning and evs[1].valid


def test_iaru_50_70_and_alpe_adria_uhf(cty):
    c, s, evs = run("iaru-50", cty, "DL1ABC", [("W1AW", "001 FN31MM", "6", "USB")],
                    grid="JO62QM")
    assert evs[0].valid and evs[0].points > 5000                # 4-stellig + „MM“
    assert CONTESTS["iaru-70"].bands == ["4"] and CONTESTS["iaru-70"].log_format == "edi"
    c, s, evs = run("alpe-adria-uhf", cty, "OE1AA", [
        ("S51AA", "001 JN76HD", "70cm", "USB", "2026-06-21 08:00:00"),
        ("S51AA", "002 JN76HD", "70cm", "FM", "2026-06-21 08:05:00"),     # FM erst ab 23 cm
        ("S51AA", "001 JN76HD", "23cm", "FM", "2026-06-21 08:10:00"),
        ("S51AA", "002 JN76HD", "23cm", "CW", "2026-06-21 15:10:00")],    # nach Contestende
        grid="JN88EF")
    assert evs[0].valid and not evs[1].valid and evs[2].valid and not evs[3].valid
