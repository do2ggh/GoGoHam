"""0.10.34: EA RTTY, EA PSK63, JARL WW RTTY, Volta RTTY (Format 20) – und ihre neuen
Bausteine (serial_zone, zone_table, not_same_area, qsos_x_points_x_mults, extra_mult, wae_keep)."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from gogoham import rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.contests.rulebased import split_serial_zone
from gogoham.cty import CtyDB
from gogoham.export import cabrillo_qso_line

HERE = Path(__file__).parent
NEW = ["ea-rtty", "ea-psk63", "jarl-ww-rtty", "volta-rtty"]
EXTRA = """Spain:                    14:  37:  EU:   40.32:     3.43:    -1.0:  EA:
    AM,AN,AO,EA,EB,EC,ED,EE,EF,EG,EH;
Balearic Islands:         14:  37:  EU:   39.60:    -2.95:    -1.0:  EA6:
    AM6,AN6,AO6,EA6,EB6,EC6,ED6,EE6,EF6,EG6,EH6;
Canary Islands:           33:  36:  AF:   28.32:    15.85:     0.0:  EA8:
    AM8,AN8,AO8,EA8,EB8,EC8,ED8,EE8,EF8,EG8,EH8;
Italy:                    15:  28:  EU:   42.82:   -12.58:    -1.0:  I:
    I;
Sicily:                   15:  28:  EU:   37.50:   -14.00:    -1.0:  *IT9:
    IT9;
Asiatic Turkey:           20:  39:  AS:   39.18:   -35.65:    -2.0:  TA:
    TA,TB,TC,YM;
European Turkey:          20:  39:  EU:   41.02:   -28.97:    -2.0:  *TA1:
    TA1,TB1,TC1,YM1;
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
        call, ex, band = x[0], x[1], x[2] if len(x) > 2 else "20"
        mode = x[3] if len(x) > 3 else ("RTTY" if c.rig_modes else sorted(c.modes)[0])
        evs.append(s.evaluate(Qso(id=i + 1, time="2026-05-09 15:00:00", call=call, band=band,
                                  mode=mode, rst_s="599", rst_r="599", exch_r=ex), commit=True))
    return c, s, evs


def test_files_valid():
    for cid in NEW:
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert rulefiles.validate(d) == [], cid
    assert rulefiles.FORMAT_VERSION >= 20
    for cid in ("ea-rtty", "ea-psk63", "volta-rtty"):          # neue Bausteine -> Format 20
        assert CONTESTS[cid].rules["format"] == 20
    d = dict(CONTESTS["volta-rtty"].rules, format=rulefiles.FORMAT_VERSION + 1)
    assert "neuere GoGoHam-Version" in rulefiles.validate(d)[0]


def test_schedules():
    def periods(cid, year):
        return [p[0] for p in schedule.periods(CONTESTS[cid].rules["schedule"], year)]
    assert periods("hadx", 2026) == [datetime(2026, 1, 17, 12)]
    assert periods("hadx", 2025) == [datetime(2025, 1, 18, 12)]
    assert periods("ea-rtty", 2026) == [datetime(2026, 4, 4, 12)]
    assert periods("ea-rtty", 2012) == [datetime(2012, 4, 7, 12)]    # 1. April = Sonntag
    assert periods("ea-rtty", 2018) == [datetime(2018, 4, 7, 12)]
    assert periods("ea-psk63", 2026) == [datetime(2026, 3, 14, 12)]
    assert periods("ea-psk63", 2025) == [datetime(2025, 3, 8, 12)]
    assert periods("jarl-ww-rtty", 2026) == [datetime(2026, 10, 17, 0)]
    p = schedule.periods(CONTESTS["jarl-ww-rtty"].rules["schedule"], 2026)[0]
    assert p[1] == datetime(2026, 10, 19, 0)                         # 48 h
    assert periods("volta-rtty", 2026) == [datetime(2026, 5, 9, 12)]
    assert periods("volta-rtty", 2021) == [datetime(2021, 5, 8, 12)]
    assert periods("volta-rtty", 2022) == [datetime(2022, 5, 14, 12)]


def test_ha_dx_still_matches_rules_2026(cty):
    """Schon seit 0.8.7 drin – 2026 nachgeprüft (Vorcheck 0.10.34)."""
    c, s, evs = run("hadx", cty, "DL1ABC", [
        ("HA5AA", "BP", "20", "CW"), ("HA5AA", "BP", "20", "USB"),     # MIX: CW + SSB je Band
        ("HA5AA", "BP", "20", "CW"),                                   # Dupe
        ("DL2AA", "002", "20", "CW"), ("W1AW", "003", "20", "CW"),
        ("OE1AA/MM", "004", "20", "CW"), ("HA1BB", "XX", "40", "CW")])
    assert [e.points for e in evs[:2]] == [10, 10] and evs[2].dupe
    assert [e.points for e in evs[3:6]] == [2, 5, 2]
    assert evs[5].mults == []                                          # /MM: kein Multi
    assert c.validate_exchange("XX", cty.lookup("HA1BB")) is not None
    assert c.validate_exchange("SZ", cty.lookup("HA1BB")) is None
    assert ("country", "HA") not in evs[0].mults
    # 10+10+2+5+2 (+ HA1BB mit falschem Kürzel: 10 Punkte, kein Komitat)
    assert s.mult_count() == 3                                         # BP, DL, K
    assert s.score == (10 + 10 + 2 + 5 + 2 + 10) * 3
    assert c.sent_exchange(7) == "007"
    # HA-Station: sendet ihr Komitat, HA untereinander 10 Punkte
    c, s, evs = run("hadx", cty, "HA5AA", [("HA1BB", "GY", "20", "CW"),
                                            ("DL1ABC", "001", "20", "CW")], district="BP")
    assert c.sent_exchange(1) == "BP"
    assert [e.points for e in evs] == [10, 2]


def test_ea_rtty_and_psk63(cty):
    for cid in ("ea-rtty", "ea-psk63"):
        mode = "RTTY" if cid == "ea-rtty" else "PSK63"
        c, s, evs = run(cid, cty, "DL1ABC", [
            ("EA3AAA", "B", "20", mode), ("W1AW", "001", "20", mode),
            ("GM3ZET", "002", "20", mode), ("IT9AAA", "003", "20", mode),
            ("TA1AA", "004", "20", mode), ("EA4URE", "HQ", "20", mode),
            ("EA6AA", "IB", "15", mode)])
        assert [e.points for e in evs] == [3, 1, 1, 1, 1, 3, 3], cid
        assert set(evs[0].mults) == {("subdiv", "B"), ("country", "EA")}
        assert set(evs[1].mults) == {("country", "K"), ("area", "W1")}
        assert ("country", "*GM/S") in evs[2].mults           # Shetland zählt eigen
        assert ("country", "*IT9") in evs[3].mults            # Sizilien zählt eigen
        assert ("country", "TA") in evs[4].mults              # Europ. Türkei = Türkei
        assert ("subdiv", "HQ") in evs[5].mults
        assert s.score == 13 * (2 + 2 + 1 + 1 + 1 + 1 + 2)
        assert c.mode_ok(Qso(call="X", band="20", mode=mode))
    # EA-Station: EA untereinander 2, mit DX 1
    c, s, evs = run("ea-rtty", cty, "EA3AAA", [("EA5BBB", "V"), ("DL1ABC", "001")],
                    district="B")
    assert c.sent_exchange(1) == "B" and [e.points for e in evs] == [2, 1]


def test_jarl_ww_rtty(cty):
    c, s, evs = run("jarl-ww-rtty", cty, "DL1ABC", [
        ("JA1AA", "45", "20"), ("JA1BB", "50", "20"), ("W1AW", "60", "15"),
        ("OE1AA", "33", "20"), ("DL2AA", "40", "20"), ("JA1AA", "45", "20")], age="42")
    assert [e.points for e in evs[:5]] == [3, 3, 3, 2, 2] and evs[5].dupe
    assert evs[0].mults == [("area", "JA1")]                  # JA zählt nur als Gebiet
    assert s.mult_count() == 4                                # JA1, W1, OE, DL
    assert s.score == 13 * 4                                  # Summe Punkte × Summe Multis
    assert c.sent_exchange(1) == "42"


def test_volta(cty):
    table = CONTESTS["volta-rtty"].rules["points"]["table"]
    assert len(table) == 40 and table[13][0] == 21 and table[13][4] == 18
    assert all(table[i][j] == table[j][i] for i in range(40) for j in range(40))
    assert split_serial_zone("001 05") == ("001", "5")
    assert split_serial_zone("1 41") == ("1", "")
    c, s, evs = run("volta-rtty", cty, "DL1ABC", [
        ("W1AW", "001 5", "20"), ("W1AW", "002 5", "40"), ("W1AW", "003 5", "15"),
        ("W1AW", "004 5", "80"),                                   # 80 m: anderer Kontinent ×2
        ("OE1AA", "005 15", "20"), ("OE1AA", "006 15", "40"), ("OE1AA", "007 15", "15"),
        ("OE1AA", "008 15", "80"),                                 # Europa: kein Extra-Multi
        ("DL2AA", "009 14", "20"),                                 # eigenes Land: zählt nicht
        ("W1AW", "010 5", "20")], cq_zone=14)                      # Dupe
    assert [e.points for e in evs[:4]] == [18, 18, 18, 36]
    oe = table[13][14]
    assert [e.points for e in evs[4:8]] == [oe] * 4
    assert not evs[8].valid and "eigenen Land" in evs[8].warning
    assert evs[9].dupe
    assert s.valid_qsos == 8 and s.extra_mults() == 1
    pts = 18 * 3 + 36 + 4 * oe
    assert s.score == 8 * pts * (8 + 1)                       # W1 + OE je 4 Bänder + 1 Extra
    assert c.sent_exchange(3) == "003 14"
    assert c.validate_exchange("001") is not None and c.validate_exchange("001 14") is None
    # Gain beim 4. Band enthält den Extra-Multi
    c2, s2, evs2 = run("volta-rtty", cty, "DL1ABC", [
        ("W1AW", "001 5", "20"), ("W1AW", "002 5", "40"), ("W1AW", "003 5", "15")], cq_zone=14)
    before = s2.score
    ev = s2.evaluate(Qso(id=9, time="2026-05-09 16:00:00", call="W1AW", band="10", mode="RTTY",
                         rst_s="599", rst_r="599", exch_r="004 5"))
    assert ev.gain == 4 * (18 * 3 + 36) * 5 - before
    # USA: anderes Rufzeichengebiet zählt, gleiches nicht
    c, s, evs = run("volta-rtty", cty, "K5AA", [("W1AW", "001 5"), ("K5BB", "002 4")],
                    cq_zone=4)
    assert evs[0].valid and evs[0].points == table[3][4]
    assert not evs[1].valid and "Rufzeichengebiet" in evs[1].warning
    line = cabrillo_qso_line(c, Qso(time="2026-05-09 12:00:00", call="W1AW", band="20",
                                    freq=14_085_000, mode="RTTY", rst_s="599", rst_r="599",
                                    exch_s="001 04", exch_r="12 5"), "K5AA")
    assert line.split()[-3:] == ["599", "012", "05"] or line.split()[-4:-1] == ["599", "012", "05"]
