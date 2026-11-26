"""0.8.6: Russian DX, RSGB IOTA, All Asian DX (CW/SSB)."""

import json
import shutil
from pathlib import Path

import pytest

from conftest import builtin_newer_than

from gogoham import regions, rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.contests.rulebased import normalize_iota, split_serial_iota, station_fields
from gogoham.cty import CtyDB
from gogoham.export import cabrillo, cabrillo_qso_line

HERE = Path(__file__).parent
NEW = ("rdxc", "iota", "aa-cw", "aa-ssb")


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def run(cty, cid, call, qsos, **st):
    c = CONTESTS[cid](cty, Station(call=call, **st))
    s = Scorer(c)
    evs = []
    for i, (cl, band, mode, ex) in enumerate(qsos, 1):
        q = Qso(id=i, time="2027-03-20 12:00:00", call=cl, band=band, mode=mode,
                rst_s="59", rst_r="59", exch_s=c.sent_exchange(i), exch_r=ex)
        evs.append(s.evaluate(q, commit=True))
    return c, s, evs


# ------------------------------------------------------------ Regel-Dateien
def test_files_format_6_and_valid():
    assert rulefiles.FORMAT_VERSION >= 6
    for cid in NEW:
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert d["format"] == 6 and rulefiles.validate(d) == []
    assert CONTESTS["rdxc"].cabrillo_name == "RDXC"
    assert CONTESTS["iota"].cabrillo_name == "RSGB-IOTA"
    assert CONTESTS["aa-cw"].cabrillo_name == "AADX-CW"
    assert CONTESTS["aa-ssb"].cabrillo_name == "AADX-SSB"


def test_085_skips_format_6(tmp_path, monkeypatch):
    """Die installierte 0.8.5.2 (Format 5) überspringt die neuen Dateien sauber."""
    from gogoham import rulesupdate
    src = tmp_path / "gh"
    src.mkdir()
    for p in rulefiles.BUILTIN_DIR.glob("*.json"):
        shutil.copy(p, src / p.name)
    (src / "index.json").write_text(json.dumps(rulesupdate.make_index(src)), encoding="utf-8")
    monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 5)
    monkeypatch.setattr(rulefiles, "BUILTIN_DIR", tmp_path / "leer")
    (tmp_path / "leer").mkdir()
    res = rulesupdate.check_and_download(src.as_uri() + "/", tmp_path / "data")
    want, rest = builtin_newer_than(5)
    assert sorted(res.skipped) == want
    assert not res.errors and len(res.new) == rest


def test_bad_new_blocks_are_reported():
    d = json.loads((rulefiles.BUILTIN_DIR / "aa-ssb.json").read_text(encoding="utf-8"))
    d["multipliers"][1]["cont"] = "XX"
    del d["points"]["non_as"]
    errs = " ".join(rulefiles.validate(d))
    assert "XX" in errs and "non_as" in errs
    d = json.loads((rulefiles.BUILTIN_DIR / "iota.json").read_text(encoding="utf-8"))
    del d["points"]["island_same"]
    assert "island_same" in " ".join(rulefiles.validate(d))
    d["exchange"] = [{"field": "rst"}, {"field": "serial"}]
    errs = " ".join(rulefiles.validate(d))
    assert "serial_iota" in errs


def test_schedules():
    s, e = schedule.period(CONTESTS["rdxc"].schedule, 2027)
    assert str(s) == "2027-03-20 12:00:00" and (e - s).total_seconds() == 24 * 3600
    s, _e = schedule.period(CONTESTS["iota"].schedule, 2026)
    assert str(s) == "2026-07-25 12:00:00"
    s, e = schedule.period(CONTESTS["aa-cw"].schedule, 2025)
    assert str(s) == "2025-06-21 00:00:00" and (e - s).total_seconds() == 48 * 3600
    s, _e = schedule.period(CONTESTS["aa-ssb"].schedule, 2025)
    assert str(s) == "2025-09-06 00:00:00"


# ------------------------------------------------------------ Russian DX
def test_oblasts():
    assert regions.normalize_oblast("ma") == "MA"
    assert regions.normalize_oblast("MS") == "MA"       # laut FAQ gültig
    assert regions.normalize_oblast("XX") is None
    assert len(regions.RU_OBLASTS) > 80


def test_rdxc_dx_station(cty):
    c, s, evs = run(cty, "rdxc", "DO2GGH", [
        ("UA3AAA", "20", "USB", "MA"),     # Russland: 10, Oblast + Land
        ("UA3AAA", "20", "CW", "MA"),      # anderer Mode: zählt, aber kein neuer Multi
        ("UA9AA", "20", "USB", "SV"),      # Asiatisches Russland: 10
        ("OE1A", "20", "USB", "12"),       # gleicher Kontinent: 3
        ("DL1A", "40", "USB", "3"),        # eigenes Land: 2
        ("K1A", "20", "USB", "5"),         # anderer Kontinent: 5
        ("UA3AAA", "20", "USB", "MA"),     # Dupe
    ])
    assert [e.points for e in evs] == [10, 10, 10, 3, 2, 5, 0]
    assert evs[0].new_mults == [("oblast", "MA"), ("country", "UA")]
    assert evs[1].new_mults == [] and evs[6].dupe
    assert s.score == 40 * 7
    assert c.sent_exchange(7) == "007"
    assert c.validate_exchange("XX", cty.lookup("UA3AAA"))
    assert c.validate_exchange("12", cty.lookup("DL1A")) is None


def test_rdxc_russian_station(cty):
    c, s, evs = run(cty, "rdxc", "UA3AAA", [
        ("UA9AA", "20", "USB", "SV"),      # Russland, anderer Kontinent: 5
        ("RA3X", "20", "USB", "MO"),       # Russland, gleicher Kontinent: 2
        ("DL1A", "20", "USB", "5"),        # gleicher Kontinent: 3
    ], oblast="MA")
    assert [e.points for e in evs] == [5, 2, 3]
    assert c.sent_exchange(1) == "MA"
    assert station_fields(CONTESTS["rdxc"]) == {"oblast"}
    meta = {"mycall": "UA3AAA", "my_oblast": "MA"}
    assert "LOCATION: MA" in cabrillo(c, meta, [], s)


# ------------------------------------------------------------ IOTA
def test_iota_parsing():
    assert normalize_iota("eu5") == "EU-005" and normalize_iota("EU-005") == "EU-005"
    assert normalize_iota("XX005") == ""
    assert split_serial_iota("12 eu005") == ("12", "EU-005")
    assert split_serial_iota("12") == ("12", "")
    assert split_serial_iota("12 foo") == ("12", "?")


def test_iota_world_station(cty):
    c, s, evs = run(cty, "iota", "DO2GGH", [
        ("G3A", "20", "USB", "5 EU005"),   # Insel: 15, Multi
        ("G3A", "20", "CW", "6 eu-5"),     # gleiche Insel auf CW: 15, Multi je Band+Mode
        ("DL1A", "20", "USB", "7"),        # Weltstation: 2
    ])
    assert [e.points for e in evs] == [15, 15, 2]
    assert evs[0].new_mults == [("iota", "EU-005")] and evs[1].new_mults == [("iota", "EU-005")]
    assert s.score == 32 * 2
    assert c.uses_serial and c.sent_exchange(3) == "003"
    assert c.validate_exchange("8 XX12", cty.lookup("GM3X"))
    q = Qso(id=1, time="2026-07-25 12:00:00", call="G3A", band="20", mode="USB", freq=14200000,
            rst_s="59", rst_r="59", exch_s="001", exch_r="5 EU005")
    line = cabrillo_qso_line(c, q, "DO2GGH")
    assert " 0001 ------ " in line and line.endswith("0005 EU-005 0")
    assert "CATEGORY-LOCATION: WORLD" in cabrillo(c, {"mycall": "DO2GGH"}, [q], s)


def test_iota_island_station(cty):
    c, s, evs = run(cty, "iota", "G3B", [
        ("G3A", "20", "USB", "5 EU005"),   # gleiche Referenz: 5
        ("DL1A", "20", "USB", "7"),        # Weltstation: 5
        ("JA1A", "20", "USB", "9 AS007"),  # andere Insel: 15
    ], iota="eu005")
    assert [e.points for e in evs] == [5, 5, 15]
    assert c.sent_exchange(4) == "004 EU-005"
    assert station_fields(CONTESTS["iota"]) == {"iota"}
    assert "CATEGORY-LOCATION: NON-DXPEDITION" in cabrillo(
        c, {"mycall": "G3B", "my_iota": "EU-005"}, [], s)


# ------------------------------------------------------------ All Asian
def test_aa_non_asian_station(cty):
    c, s, evs = run(cty, "aa-ssb", "DO2GGH", [
        ("JA1AAA", "160", "LSB", "55"),    # 160 m: 3
        ("JA1AAA", "20", "USB", "55"),     # 20 m: 1, Präfix je Band
        ("JA2B", "10", "USB", "40"),       # 10 m: 2
        ("DL1A", "20", "USB", "40"),       # nicht Asien: zählt nicht
        ("BY1A", "20", "USB", "01"),
    ], age="44")
    assert [e.points for e in evs] == [3, 1, 2, 0, 1]
    assert evs[3].warning and not evs[3].valid
    assert evs[1].new_mults == [("prefix", "JA1")]
    assert s.score == 7 * 4
    assert c.sent_exchange(1) == "44"
    assert c.validate_exchange("4", None) and c.validate_exchange("44", None) is None
    assert station_fields(CONTESTS["aa-cw"]) == {"age"}
    assert "Präfix" not in c.describe(Qso(call="DL1A", band="20", mode="USB"),
                                      cty.lookup("DL1A"))


def test_aa_asian_station(cty):
    c, s, evs = run(cty, "aa-ssb", "JA1AAA", [
        ("JA2B", "20", "USB", "40"),       # eigenes Land: zählt nicht
        ("BY1A", "20", "USB", "30"),       # Asien: 1
        ("DL1A", "20", "USB", "40"),       # außerhalb Asiens: 3
        ("DL1A", "160", "LSB", "40"),      # 160 m: 9
    ])
    assert [e.points for e in evs] == [0, 1, 3, 9]
    assert not evs[0].valid
    assert evs[2].new_mults == [("country", "DL")]
    assert c.sent_exchange(1) == "01"              # kein Alter eingetragen
    assert s.score == 13 * 3
