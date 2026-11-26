"""0.8.24: DARC-Paket – Fieldday CW/SSB, FT4, CW-Ausbildungscontest, Ausbildungscontest.
Neue Bausteine (Format 9): Termin „weekday“ + „months“, Punkte „portable“, „trainee“."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from gogoham import contestcal, rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.contests.rulebased import is_portable_call, is_trainee_call
from gogoham.cty import CtyDB
from gogoham.export import cabrillo

HERE = Path(__file__).parent
NEW = ("darc-fd-cw", "darc-fd-ssb", "darc-ft4", "darc-cwa", "darc-ac")


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def make(cid, cty, call="DL1ABC", dok="B36"):
    c = CONTESTS[cid](cty, Station(call=call, lookup=cty.lookup(call), dok=dok, grid="JN59"))
    return c, Scorer(c)


def qso(i, call, ex, band="40", mode="CW", khz=7020):
    return Qso(id=i, time="2026-06-06 15:00:00", call=call, band=band, mode=mode,
               rst_s="599", rst_r="599", exch_r=ex, freq=khz * 1000)


# ------------------------------------------------------------ Termine
def test_dates_2026_match_darc_calendar():
    def starts(cid, n):
        return [s for s, _ in schedule.upcoming(CONTESTS[cid].rules["schedule"],
                                                datetime(2026, 1, 1), n)]
    assert starts("darc-ft4", 4) == [datetime(2026, 2, 10, 19), datetime(2026, 5, 12, 19),
                                     datetime(2026, 8, 11, 19), datetime(2026, 11, 10, 19)]
    assert starts("darc-cwa", 4) == [datetime(2026, 3, 10, 18), datetime(2026, 6, 9, 18),
                                     datetime(2026, 9, 8, 18), datetime(2026, 12, 8, 18)]
    assert starts("darc-fd-cw", 1) == [datetime(2026, 6, 6, 15)]
    assert starts("darc-fd-ssb", 1) == [datetime(2026, 9, 5, 13)]
    assert starts("darc-ac", 1) == [datetime(2026, 10, 17, 12)]
    s, e = schedule.next_period(CONTESTS["darc-ft4"].rules["schedule"], datetime(2026, 11, 10, 20))
    assert (s, e) == (datetime(2026, 11, 10, 19), datetime(2026, 11, 10, 20, 30))   # läuft


def test_period_of_and_calendar_counts():
    rule = CONTESTS["darc-ft4"].rules["schedule"]
    assert schedule.period_of(rule, datetime(2026, 5, 12, 19, 40))[0] == datetime(2026, 5, 12, 19)
    assert schedule.period_of(rule, datetime(2026, 5, 13, 19, 40)) is None
    now = datetime(2026, 11, 14)
    one = [x for x in contestcal.entries(CONTESTS, now) if x.cid == "darc-ft4"]
    assert len(one) == 1 and one[0].start == datetime(2027, 2, 9, 19)
    two = [x for x in contestcal.entries(CONTESTS, now, count=2) if x.cid == "darc-ft4"]
    assert len(two) == 5                            # nächster Termin + ein Jahr mit 4 Terminen
    assert len([x for x in contestcal.entries(CONTESTS, now, count=2) if x.cid == "wag"]) == 2


def test_schedule_validation():
    base = {"format": 9, "id": "x", "name": "X", "bands": ["80"], "modes": ["CW"],
            "exchange": [{"field": "rst"}, {"field": "serial"}],
            "points": {"type": "fixed", "value": 1}, "multipliers": []}
    ok = {**base, "schedule": {"weekend": "weekday", "weekday": 1, "nth": 2,
                               "months": [3, 6], "start_hour": 18, "hours": 1}}
    assert rulefiles.validate(ok) == []
    bad = {**base, "schedule": {"weekend": "weekday", "weekday": 7, "months": [13],
                                "hours": 1}}
    errs = rulefiles.validate(bad)
    assert any("months" in e for e in errs) and any("weekday" in e for e in errs)
    assert any("trainee" in e for e in rulefiles.validate(
        {**base, "points": {"type": "fixed", "value": 1, "trainee": -1}}))
    assert any("fixed_fixed" in e for e in rulefiles.validate(
        {**base, "points": {"type": "portable", "fixed_eu": 2, "fixed_dx": 3,
                            "portable_eu": 4, "portable_dx": 6}}))


def test_new_files_need_format_9(monkeypatch):
    for cid in NEW:
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert d["format"] == 9 and rulefiles.validate(d) == []
        monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 8)
        assert "neuere GoGoHam-Version" in rulefiles.validate(d)[0]
        monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 9)


# ------------------------------------------------------------ Fieldday
def test_call_helpers():
    assert is_portable_call("DL1ABC/P") and is_portable_call("OE/DL1ABC/M")
    assert is_portable_call("DL1ABC/MM") and is_portable_call("DL1ABC/AM")
    assert not is_portable_call("DL1ABC") and not is_portable_call("DL1ABC/QRP")
    assert not is_portable_call("P/DL1ABC")
    assert is_trainee_call("DN1ABC") and is_trainee_call("DN8XY/P") and is_trainee_call("DO1XYZ")
    assert not is_trainee_call("DN9ABC") and not is_trainee_call("DL1ABC")


def test_fieldday_points_portable(cty):
    c, sc = make("darc-fd-cw", cty, call="DL1ABC/P")
    pts = [c.qso_points(qso(1, call, "001"), cty.lookup(call))
           for call in ("DK2XY", "W1AW", "OE1XX/P", "JA1AA/P", "G4ABC/MM")]
    assert pts == [2, 3, 4, 6, 6]                    # /MM: Standort unbekannt -> außerhalb


def test_fieldday_points_fixed_station(cty):
    c, sc = make("darc-fd-ssb", cty, call="DL1ABC")
    assert c.qso_points(qso(1, "DK2XY", "001", mode="SSB"), cty.lookup("DK2XY")) == 0
    assert c.qso_points(qso(2, "DK2XY/P", "001", mode="SSB"), cty.lookup("DK2XY/P")) == 4
    assert c.qso_points(qso(3, "W1AW/P", "001", mode="SSB"), cty.lookup("W1AW/P")) == 6


def test_fieldday_score_and_cabrillo(cty):
    c, sc = make("darc-fd-cw", cty, call="DL1ABC/P")
    qs = [qso(1, "DK2XY", "001"), qso(2, "OE1XX/P", "015"),
          qso(3, "DK2XY", "002", band="80", khz=3520), qso(4, "DK2XY", "003")]
    for q in qs:
        sc.evaluate(q, commit=True)
    # 40 m: DL 2 + OE 4 (Dupe zählt nicht), 80 m: DL 2; Multis: DL, OE auf 40 + DL auf 80
    assert sc.score == (2 + 4 + 2) * 3
    text = cabrillo(c, {"mycall": "DL1ABC/P"}, qs[:3], sc)
    assert "CONTEST: IARU-FD-R1-DARC-CW" in text and "CATEGORY-STATION: PORTABLE" in text
    text = cabrillo(c, {"mycall": "DL1ABC"}, qs[:3], sc)
    assert "CATEGORY-STATION: FIXED" in text
    c2, _ = make("darc-cwa", cty)
    assert "CATEGORY-STATION" not in cabrillo(c2, {"mycall": "DL1ABC"}, [], Scorer(c2))


# ------------------------------------------------------------ AC, CWA, FT4
def test_ausbildungscontest(cty):
    c, sc = make("darc-ac", cty)
    assert c.qso_points(qso(1, "DN1ABC", "B36"), cty.lookup("DN1ABC")) == 2
    assert c.qso_points(qso(2, "DO5XY", "C01"), cty.lookup("DO5XY")) == 2
    assert c.qso_points(qso(3, "DK2XY", "C12"), cty.lookup("DK2XY")) == 1
    qs = [qso(1, "DN1ABC", "B36"), qso(2, "DK2XY", "B01"), qso(3, "DK3XY", "C12"),
          qso(4, "OE1XX", "007"), qso(5, "DK4XY", "NM"),
          qso(6, "DK2XY", "B01", mode="SSB", khz=7150)]
    for q in qs:
        sc.evaluate(q, commit=True)
    # Punkte 2+1+1+1+1 (CW) + 1 (SSB); Multis CW: Distrikt B, C, Land DL, OE; SSB: B, DL
    assert sc.score == 7 * 6
    assert c.segment_problem(qso(7, "DK5XY", "B01", khz=7100)) is not None   # 40 m CW gesperrt
    assert c.segment_problem(qso(8, "DK5XY", "B01", khz=7020)) is None


def test_cw_training_contest(cty):
    c, sc = make("darc-cwa", cty)
    qs = [qso(1, "DK2XY", "B01", band="80", khz=3530), qso(2, "DK3XY", "B01", band="80", khz=3530),
          qso(3, "OE1XX", "001", band="80", khz=3530), qso(4, "DK4XY", "NM", band="80", khz=3530)]
    for q in qs:
        sc.evaluate(q, commit=True)
    # 4 Punkte; Multis: DOK B01 + Präfixe DK2, DK3, OE1, DK4
    assert sc.score == 4 * 5


def test_ft4_contest(cty):
    c, sc = make("darc-ft4", cty)
    qs = [Qso(id=1, time="2026-11-10 19:00:00", call="DK2XY", band="80", mode="FT4",
              rst_s="-10", rst_r="-05", exch_r="JO31"),
          Qso(id=2, time="2026-11-10 19:05:00", call="DK2XY", band="40", mode="FT4",
              rst_s="-10", rst_r="-05", exch_r="JO31"),
          Qso(id=3, time="2026-11-10 19:06:00", call="DK2XZ", band="40", mode="FT4",
              rst_s="-10", rst_r="-05", exch_r="JO40")]
    for q in qs:
        sc.evaluate(q, commit=True)
    assert sc.score == 3 * 2                       # DK2 auf 80 und auf 40
    assert c.mode_ok(qs[0])
