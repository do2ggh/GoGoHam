"""0.10.31: ARRL 160 m (Sections, W/VE mit allen, DX nur mit W/VE) und Stew Perry
(Entfernungspunkte, Faktor für die eigene Leistung) – Format 17."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from gogoham import regions, rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.contests.rulebased import station_fields
from gogoham.cty import CtyDB
from gogoham.export import cabrillo_qso_line

HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def make(cid, cty, call="DL1ABC", **kw):
    c = CONTESTS[cid](cty, Station(call=call, lookup=cty.lookup(call), **kw))
    return c, Scorer(c)


def qso(i, call, ex, t="2026-12-05 01:00:00"):
    return Qso(id=i, time=t, call=call, band="160", mode="CW", rst_s="599", rst_r="599",
               exch_r=ex)


def test_sections():
    assert len(regions.ARRL_SECTIONS) == 85 == len(set(regions.ARRL_SECTIONS))
    assert regions.normalize_section("ema") == "EMA" and regions.normalize_section("NF") == "NL"
    assert regions.normalize_section("YT") == "TER" and regions.normalize_section("ON") is None
    assert regions.normalize_section("CA") is None          # Kalifornien hat mehrere Sections
    assert regions.section_from_call("VE7ABC") == "BC"
    assert regions.section_from_call("VE3ABC") == ""         # ONE/ONN/ONS – nicht raten
    assert regions.section_from_call("KH6XX", "KH6") == "PAC"
    assert regions.section_from_call("KH2XX", "KH2") == "PAC"
    assert regions.section_from_call("KL7XX", "KL") == "AK"
    assert regions.section_from_call("W1AW", "K") == ""


def test_rule_files_valid():
    for cid in ("arrl-160", "stew-perry"):
        d = json.loads((Path(rulefiles.__file__).parent / "rules" / f"{cid}.json").read_text())
        assert d["format"] == 17 and rulefiles.validate(d) == []
    assert rulefiles.FORMAT_VERSION >= 17


def test_arrl160_dx_station(cty):
    c, s = make("arrl-160", cty)
    assert c.sent_exchange(1) == "" and c.mult_types == [("section", "Sections")]
    w, ve, kh6 = cty.lookup("W1XX"), cty.lookup("VE3XX"), cty.lookup("KH6XX")
    assert c.validate_exchange("", w) is not None              # Section fehlt
    assert c.validate_exchange("XYZ", w) is not None
    assert c.validate_exchange("ema", w) is None
    assert c.default_rcvd_exchange(kh6, "KH6XX") == "PAC"
    ev = s.evaluate(qso(1, "W1XX", "EMA"), commit=True)
    assert ev.valid and ev.points == 5 and ev.new_mults == [("section", "EMA")]
    ev = s.evaluate(qso(2, "KH6XX", "PAC"), commit=True)       # Hawaii zählt als W/VE
    assert ev.valid and ev.points == 5
    ev = s.evaluate(qso(3, "JA1XX", ""), commit=True)          # DX–DX zählt nicht
    assert not ev.valid and "W/VE" in ev.warning
    s.evaluate(qso(4, "VE3XX", "ONS"), commit=True)
    s.evaluate(qso(5, "W2XX", "EMA"), commit=True)             # Section schon da
    assert s.score == 4 * 5 * 3
    assert c.ask_text(qso(6, "KH6YY", ""), kh6).startswith("Section: PAC")


def test_arrl160_w_ve_station(cty):
    c, s = make("arrl-160", cty, call="W1AW", state="EMA")
    assert c.sent_exchange(1) == "EMA"
    assert ("country", "Länder") in c.mult_types
    ja = cty.lookup("JA1XX")
    assert c.validate_exchange("", ja) is None                 # DX sendet nur den Rapport
    assert c.expected_kind(ja) == "none"
    ev = s.evaluate(qso(1, "W2XX", "ENY"), commit=True)
    assert ev.valid and ev.points == 2
    ev = s.evaluate(qso(2, "JA1XX", ""), commit=True)
    assert ev.valid and ev.points == 5 and ("country", "JA") in ev.new_mults
    ev = s.evaluate(qso(3, "KH6XX", "PAC"), commit=True)       # Section, kein Land
    assert ev.points == 2 and ev.new_mults == [("section", "PAC")]
    assert s.score == (2 + 5 + 2) * 3
    assert "state" in station_fields(type(c))


def test_arrl160_cabrillo_and_schedule(cty):
    c, _s = make("arrl-160", cty)
    q = qso(1, "W1XX", "EMA")
    q.freq, q.exch_s = 1_830_000, ""
    line = cabrillo_qso_line(c, q, "DL1ABC")
    assert line.split()[5:] == ["DL1ABC", "599", "W1XX", "599", "EMA", "0"]
    r = c.rules["schedule"]
    assert schedule.period(r, 2026) == (datetime(2026, 12, 4, 22), datetime(2026, 12, 6, 16))
    assert c.cabrillo_name == "ARRL-160"


def test_stew_perry(cty):
    c, s = make("stew-perry", cty, grid="JN59me")
    assert c.sent_exchange(1) == "JN59"
    assert c.validate_exchange("io91", cty.lookup("G3XX")) is None
    assert c.validate_exchange("599", cty.lookup("G3XX")) is not None
    pts = [s.evaluate(Qso(id=i + 1, time="2026-12-26 16:00:00", call=call, band="160",
                          mode="CW", exch_r=g), commit=True).points
           for i, (call, g) in enumerate([("DL2XX", "JN59"), ("G3XX", "IO91"),
                                          ("W1XX", "FN42")])]
    assert pts == [1, 2, 13]                                   # 1 + je volle 500 km
    assert s.score == 16                                       # HIGH: kein Faktor
    for power, score in (("LOW", 24), ("QRP", 48), ("HIGH", 16)):
        c2, s2 = make("stew-perry", cty, grid="JN59me", cat_power=power)
        gains = [s2.evaluate(Qso(id=i + 1, time="2026-12-26 16:00:00", call=call,
                                 band="160", mode="CW", exch_r=g), commit=True).gain
                 for i, (call, g) in enumerate([("DL2XX", "JN59"), ("G3XX", "IO91"),
                                                ("W1XX", "FN42")])]
        assert s2.score == score and sum(gains) == score
    r = c.rules["schedule"]
    assert schedule.period(r, 2026)[0] == datetime(2026, 12, 26, 15)   # laut Ausschreibung
    assert schedule.period(r, 2024)[0] == datetime(2024, 12, 28, 15)   # Soapbox 2024
    assert c.cabrillo_name == "STEW-PERRY"


def test_power_factor_validation():
    d = json.loads((Path(rulefiles.__file__).parent / "rules" / "stew-perry.json").read_text())
    d["power_factor"] = {"MEDIUM": 2}
    assert rulefiles.validate(d)
    d["power_factor"] = {"LOW": 0}
    assert rulefiles.validate(d)


def test_adif_section(cty):
    from gogoham.export import adif
    c, s = make("arrl-160", cty)
    q = qso(1, "W1XX", "ema")
    q.freq = 1_830_000
    out = adif(c, {"mycall": "DL1ABC"}, [q])
    assert "<ARRL_SECT:3>EMA" in out
