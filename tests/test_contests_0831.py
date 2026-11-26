"""0.8.31: Contest-Paket LZ DX, 9A DX, AGCW Happy New Year, REF (CW/SSB) – Format 11."""

import json
import shutil
from pathlib import Path

import pytest

from conftest import builtin_newer_than
from gogoham import practice as pm, rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.contests.rulebased import (in_window, normalize_district, split_serial_member,
                                        station_fields)
from gogoham.cty import CtyDB

HERE = Path(__file__).parent
NEW = ("lzdx", "9adx", "agcw-hny", "ref-cw", "ref-ssb")
EXTRA = """Croatia:                  15:  28:  EU:   45.18:   -15.30:    -1.0:  9A:
    9A;
France:                   14:  27:  EU:   46.00:    -2.00:    -1.0:  F:
    F,TM;
Guadeloupe:               08:  11:  NA:   16.13:    61.67:     4.0:  FG:
    FG;
Bulgaria:                 20:  28:  EU:   42.83:   -25.08:    -2.0:  LZ:
    LZ;
"""

@pytest.fixture(autouse=True)
def _ref_samples(monkeypatch):
    """REF CW/SSB sind seit 0.10.41.1 nicht mehr in GoGoHam (Seite sperrt Abrufe); ihre Bausteine
    (Mutterland ↔ Übersee, Departement „1“ = „01“) werden mit den alten Dateien weiter geprüft."""
    import json as _j
    from gogoham.contests.rulebased import make_contest_class
    for cid in ("ref-cw", "ref-ssb"):
        p = Path(__file__).parent / "rule_samples" / f"{cid}.json"
        monkeypatch.setitem(CONTESTS, cid, make_contest_class(_j.loads(p.read_text(encoding="utf-8"))))



@pytest.fixture(scope="module")
def cty(tmp_path_factory):
    p = tmp_path_factory.mktemp("cty") / "cty.dat"
    p.write_text((HERE / "cty_sample.dat").read_text(encoding="utf-8") + EXTRA, encoding="utf-8")
    return CtyDB.from_file(p)


def run(cty, cid, call, qsos, **st):
    c = CONTESTS[cid](cty, Station(call=call, **st))
    s = Scorer(c)
    evs = []
    for i, row in enumerate(qsos, 1):
        cl, band, mode, ex = row[:4]
        t = row[4] if len(row) > 4 else "2026-12-19 15:00:00"
        q = Qso(id=i, time=t, call=cl, band=band, mode=mode, rst_s="59", rst_r="59",
                exch_s=c.sent_exchange(i), exch_r=ex)
        evs.append(s.evaluate(q, commit=True))
    return c, s, evs


def test_files_format_11_valid_and_dates():
    assert rulefiles.FORMAT_VERSION >= 11
    for cid in NEW:
        base = rulefiles.BUILTIN_DIR if not cid.startswith("ref-") else HERE / "rule_samples"
        d = json.loads((base / f"{cid}.json").read_text(encoding="utf-8"))
        # REF seit 0.10.28 Format 16 (Punkte für französische Stationen)
        assert d["format"] == (16 if cid.startswith("ref-") else 11) and rulefiles.validate(d) == [], cid
    s = {cid: CONTESTS[cid].schedule for cid in NEW}
    assert schedule.period(s["lzdx"], 2026)[0].isoformat() == "2026-11-21T12:00:00"
    assert schedule.period(s["9adx"], 2026)[0].isoformat() == "2026-12-19T14:00:00"
    assert schedule.period(s["agcw-hny"], 2027)[0].isoformat() == "2027-01-01T09:00:00"
    assert schedule.period(s["ref-cw"], 2027)[0].isoformat() == "2027-01-30T06:00:00"
    assert schedule.period(s["ref-ssb"], 2027)[1].isoformat() == "2027-02-28T18:00:00"
    assert station_fields(CONTESTS["lzdx"]) == {"itu", "district"}
    assert station_fields(CONTESTS["agcw-hny"]) == {"member"}


def test_lzdx_as_dl_station(cty):
    c, s, evs = run(cty, "lzdx", "DL1ABC", [
        ("LZ1AA", "40", "CW", "SF"),         # LZ: 10 Punkte, Bezirk + nichts sonst
        ("LZ2BB", "40", "PH", "VN"),         # gleiches Band, anderer Mode: erlaubt
        ("OK1AA", "40", "CW", "28"),         # gleicher Kontinent: 1, ITU-Zone 28
        ("JA1AA", "40", "CW", "45"),         # anderer Kontinent: 3
        ("LZ1AA", "40", "CW", "SF"),         # Dupe
        ("LZ1AA", "40", "PH", "SF"),         # anderer Mode: kein Dupe, Bezirk nicht neu
    ])
    assert c.sent_exchange(1) == "28"                    # eigene ITU-Zone aus der Länderdatei
    assert [e.points for e in evs[:4]] == [10, 10, 1, 3]
    assert evs[4].dupe and not evs[5].dupe and evs[5].new_mults == []
    assert evs[0].new_mults == [("subdiv", "SF")]          # keine Zone für LZ-Stationen
    assert evs[2].new_mults == [("itu", "28")]
    assert c.validate_exchange("XX", cty.lookup("LZ1AA")) and \
        not c.validate_exchange("sf", cty.lookup("LZ1AA"))
    assert c.validate_exchange("95", cty.lookup("OK1AA"))
    assert c.default_rcvd_exchange(cty.lookup("OK1AA"), "OK1AA") == "28"


def test_lzdx_as_lz_station(cty):
    c, s, evs = run(cty, "lzdx", "LZ1ZZ", [("LZ2AA", "20", "CW", "PD"), ("OK1AA", "20", "CW", "28")],
                    district="SF")
    assert c.sent_exchange(1) == "SF"
    assert [e.points for e in evs] == [1, 1]
    assert ("country", "OK") in evs[1].new_mults and ("itu", "28") in evs[1].new_mults


def test_9adx_band_points_night_bonus_and_mults_per_mode(cty):
    c, s, evs = run(cty, "9adx", "DL1ABC", [
        ("9A1AA", "80", "CW", "ZG"),                         # 9A auf 80 m: 10
        ("9A1AA", "20", "CW", "ZG"),                         # 9A auf 20 m: 6
        ("OK1AA", "160", "CW", "28"),                        # Europa 160 m: 2
        ("JA1AA", "20", "CW", "45"),                         # anderer Kontinent 20 m: 3
        ("JA1AA", "40", "CW", "45", "2026-12-19 23:30:00"),  # Nacht: 6 + 2
        ("JA1AA", "40", "PH", "45", "2026-12-20 04:59:00"),  # noch Nacht, anderer Mode
        ("OK1AA", "20", "CW", "28", "2026-12-20 05:00:00"),  # nicht mehr Nacht
    ])
    assert [e.points for e in evs] == [10, 6, 2, 3, 8, 8, 1]
    assert ("subdiv", "ZG") in evs[0].new_mults and ("country", "9A") in evs[0].new_mults
    assert ("itu", "45") in evs[5].new_mults                 # je Band UND Mode neu
    assert c.validate_exchange("XX", cty.lookup("9A1AA"))


def test_9adx_as_9a_station(cty):
    c, s, evs = run(cty, "9adx", "9A1ZZ", [("9A2AA", "80", "CW", "ST"), ("OK1AA", "80", "CW", "28"),
                                           ("JA1AA", "40", "CW", "45")], district="ZG")
    assert [e.points for e in evs] == [1, 4, 8]


def test_in_window():
    assert in_window("2026-12-19 23:00:00", "2300", "0500")
    assert in_window("2026-12-20 00:10:00", "2300", "0500")
    assert not in_window("2026-12-20 05:00:00", "2300", "0500")
    assert not in_window("2026-12-19 22:59:00", "2300", "0500")
    assert in_window("2026-12-19 10:00:00", "0900", "1200") and not in_window("", "0900", "1200")


def test_agcw_member_multipliers(cty):
    assert split_serial_member("067/2583") == ("067", "2583")
    assert split_serial_member("12 2583") == ("12", "2583") and split_serial_member("5") == ("5", "")
    c, s, evs = run(cty, "agcw-hny", "DL1ABC", [
        ("DL2AA", "80", "CW", "001/2583"),                  # Mitglied: Multi
        ("OK1AA", "80", "CW", "012"),                       # kein Mitglied: nur Punkt
        ("DL2AA", "40", "CW", "005/2583"),                  # anderes Band: neuer Multi
        ("DL2AA", "40", "CW", "006/2583"),                  # Dupe auf dem Band
    ], member="1234")
    assert c.sent_exchange(7) == "007/1234"
    assert CONTESTS["agcw-hny"](cty, Station(call="DL1ABC")).sent_exchange(7) == "007"
    assert [e.points for e in evs[:3]] == [1, 1, 1] and evs[3].dupe
    assert evs[0].new_mults == [("member", "DL2AA")] and evs[1].new_mults == []
    assert evs[2].new_mults == [("member", "DL2AA")]
    assert s.score == 3 * 2
    assert c.validate_exchange("12/ab") and c.validate_exchange("") and \
        not c.validate_exchange("12/345")
    seg = c.segment_problem(Qso(id=1, time="2027-01-01 09:00:00", call="DL2AA", band="80",
                                mode="CW", freq=3570000))
    assert seg                                            # außerhalb 3510–3560 kHz


def test_ref_as_dx_station(cty):
    c, s, evs = run(cty, "ref-cw", "DL1ABC", [
        ("F5AA", "40", "CW", "75"),          # Frankreich, Europa: 1 Punkt, Dép. 75
        ("F6REF", "40", "CW", "00"),         # REF-Zentrale: Dép. 00
        ("TM1A", "40", "CW", "2a"),          # Korsika (Süd)
        ("FG5AA", "40", "CW", "FG"),         # Übersee, anderer Kontinent: 3, Präfix als Multi
        ("OK1AA", "40", "CW", "12"),         # DX untereinander zählt nicht
        ("F5BB", "20", "CW", "1"),           # „1“ = Dép. 01
    ])
    assert c.sent_exchange(3) == "003"
    assert [e.points for e in evs[:4]] == [1, 1, 1, 3]
    assert [e.new_mults for e in evs[:4]] == [[("subdiv", "75")], [("subdiv", "00")],
                                              [("subdiv", "2A")], [("subdiv", "FG")]]
    assert evs[4].points == 0 and not evs[4].new_mults
    assert evs[5].new_mults == [("subdiv", "01")]
    assert normalize_district("1", CONTESTS["ref-cw"].host) == "01"


def test_practice_can_make_the_new_exchanges():
    for cid, mode in (("lzdx", "CW"), ("9adx", "SSB"), ("agcw-hny", "CW"), ("ref-cw", "CW"),
                      ("ref-ssb", "SSB")):
        assert pm.can_practice(CONTESTS[cid], mode), cid


def test_0830_skips_format_11(tmp_path, monkeypatch):
    """Die installierte 0.8.30 (Format 10) überspringt die neuen Dateien sauber."""
    from gogoham import rulesupdate
    src = tmp_path / "gh"
    src.mkdir()
    for p in rulefiles.BUILTIN_DIR.glob("*.json"):
        shutil.copy(p, src / p.name)
    (src / "index.json").write_text(json.dumps(rulesupdate.make_index(src)), encoding="utf-8")
    monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 10)
    monkeypatch.setattr(rulefiles, "BUILTIN_DIR", tmp_path / "leer")
    (tmp_path / "leer").mkdir()
    res = rulesupdate.check_and_download(src.as_uri() + "/", tmp_path / "data")
    want, rest = builtin_newer_than(10)
    # dazu die 7 Multi-OP-Dateien mit Format 12 (0.10.2), 4 RTTY-Contests (0.10.7) und
    # 10 Dateien mit Format 14 (0.10.23: AGCW QRP, QRP-Party, Frankencontest)
    assert sorted(res.skipped) == want and len(want) == len(NEW) - 2 + 7 + 4 + 10 + 3 + 1 + 2 + 15 + 14 + 4 + 2 + 11 + 7 + 5   # + PACC (16), ARRL 160, Stew Perry (17), 15 neue (18), 14 neue (19)
    assert not res.errors and len(res.new) == rest
