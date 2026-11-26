"""0.7.1: ARRL 10 m, IARU HF, EU HF Championship – und der doppelte „Zählt nicht“-Text."""

from datetime import datetime
from pathlib import Path

import pytest

from conftest import builtin_newer_than

from gogoham import logcheck, regions, schedule, stats
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.cty import CtyDB
from gogoham.export import adif

HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def make(cid, cty, call="DL1ABC", **st):
    c = CONTESTS[cid](cty, Station(call=call, cq_zone=14, **st))
    return c, Scorer(c)


def qso(i, call, ex, band="10", mode="CW", freq=0, t=None):
    return Qso(id=i, time=t or f"2026-12-12 10:{i:02d}:00", call=call, band=band, mode=mode,
               freq=freq, rst_s="599", rst_r="599", exch_r=ex)


# ------------------------------------------------------------ ARRL 10 m
def test_arrl10_points_and_mults_per_mode(cty):
    c, s = make("arrl-10", cty)
    assert c.uses_serial and c.sent_exchange(7) == "007" and c.mult_per == "mode"
    log = [qso(1, "W1AW", "CT", mode="USB"), qso(2, "W1AW", "CT", mode="CW"),   # je Mode einmal
           qso(3, "W1AW", "CT", mode="LSB"),                                    # Dupe in SSB
           qso(4, "VE3XYZ", "ON", mode="USB"), qso(5, "KH6XX", "HI", mode="CW"),  # Hawaii = State
           qso(6, "OE1XX", "12", mode="CW"), qso(7, "K1ABC/MM", "2", mode="USB")]
    s.rebuild(log)
    assert [s.evals[i].points for i in range(1, 8)] == [2, 4, 0, 2, 4, 4, 2]
    assert s.mults[("state", "PH")] == {"CT"} and s.mults[("state", "CW")] == {"CT", "HI"}
    assert s.mults[("province", "PH")] == {"ON"}
    assert s.mults[("country", "CW")] == {"OE"}            # KH6 zählt als State, nicht als Land
    assert s.mults[("region", "PH")] == {"2"}
    assert s.score == 18 * 6


def test_arrl10_exchange_and_cw_limit(cty):
    c, s = make("arrl-10", cty)
    w, kh6, dl, mm = (cty.lookup(x) for x in ("W1AW", "KH6XX", "OE1XX", "K1ABC/MM"))
    assert c.expected_kind(w) == "state" and c.expected_kind(kh6) == "state"
    assert c.expected_kind(dl) == "serial" and c.expected_kind(mm) == "itu_region"
    assert "Nummer" in c.validate_exchange("CT", dl)
    assert "ITU-Region" in c.validate_exchange("5", mm)
    ev = s.evaluate(qso(1, "OE1XX", "12", mode="CW", freq=28_350_000))
    assert not ev.valid and "CW nur unter 28,300 MHz" in ev.warning
    assert s.evaluate(qso(2, "OE1XX", "12", mode="CW", freq=28_025_000)).points == 4
    assert s.evaluate(qso(3, "OE1XX", "12", mode="USB", freq=28_450_000)).points == 2


def test_xe_states():
    assert len(regions.XE_STATES) == 32
    assert regions.normalize_xe_state("jal") == "JAL" and regions.normalize_xe_state("DF") == "CMX"
    assert regions.normalize_xe_state("XX") is None


# ------------------------------------------------------------ IARU HF
def test_iaru_points_and_mults(cty):
    c, s = make("iaru-hf", cty)
    assert c.sent_exchange(1) == "28"
    log = [qso(1, "DL2XX", "28", "20"),             # gleiche Zone: 1
           qso(2, "OE1XX", "28", "20"),             # gleiche Zone: 1, kein neuer Multi
           qso(3, "G4ABC", "27", "20"),             # gleicher Kontinent, andere Zone: 3
           qso(4, "W1AW", "8", "20"),               # anderer Kontinent: 5
           qso(5, "DA0HQ", "DARC", "20"),           # Verband: 1
           qso(6, "ON4XX", "R1", "20"),             # IARU-Funktionär: 1
           qso(7, "W1AW", "ARRL", "20", "USB"),     # anderer Mode: kein Dupe
           qso(8, "W1AW", "8", "40")]               # anderes Band: neuer Zonen-Multi
    s.rebuild(log)
    assert [s.evals[i].points for i in range(1, 9)] == [1, 1, 3, 5, 1, 1, 1, 5]
    assert s.mults[("itu", "20")] == {"28", "27", "8"} and s.mults[("itu", "40")] == {"8"}
    assert s.mults[("hq", "20")] == {"DARC", "R1", "ARRL"}
    assert s.score == 18 * 7


def test_iaru_prefill_and_validation(cty):
    c, _s = make("iaru-hf", cty)
    assert c.default_rcvd_exchange(cty.lookup("OE1XX"), "OE1XX") == "28"
    assert c.default_rcvd_exchange(cty.lookup("W1AW"), "W1AW") == ""   # USA: 3 ITU-Zonen
    assert c.default_rcvd_exchange(cty.lookup("VE3XX"), "VE3XX") == ""
    assert c.validate_exchange("28") is None and c.validate_exchange("DARC") is None
    assert "1 und 90" in c.validate_exchange("91")
    assert c.validate_exchange("1!") is not None
    hq, _ = make("iaru-hf", cty, itu="darc")
    assert hq.sent_exchange(1) == "DARC"             # eigene HQ-Station
    other, _ = make("iaru-hf", cty, itu="27")
    assert other.sent_exchange(1) == "27" and other.own_itu() == 27


def test_iaru_adif_ituz(cty):
    c, _s = make("iaru-hf", cty)
    out = adif(c, {"mycall": "DL1ABC"}, [qso(1, "W1AW", "7", "20")])
    assert "<ITUZ:1>7" in out


# ------------------------------------------------------------ EU HF
def test_euhfc_only_europe_and_year_mults(cty):
    c, s = make("euhfc", cty, lic_year="06")
    assert c.sent_exchange(1) == "06" and c.max_changes_per_hour == 10
    log = [qso(1, "OE1XX", "82", "20"), qso(2, "DL2XX", "95", "20", "USB"),
           qso(3, "DL2XX", "95", "20", "CW"),            # anderer Mode: zählt, Jahr schon da
           qso(4, "W1AW", "70", "20"),                   # nicht Europa
           qso(5, "OE1XX", "82", "40")]                  # anderes Band: Jahr neu
    s.rebuild(log)
    assert [s.evals[i].points for i in range(1, 6)] == [1, 1, 1, 0, 1]
    assert "nicht in Europa" in s.evals[4].warning
    assert s.mults[("year", "20")] == {"82", "95"} and s.mults[("year", "40")] == {"82"}
    assert "Zwei Ziffern" in c.validate_exchange("1982")
    ja, s2 = make("euhfc", cty, call="JA1XX", lic_year="70")
    assert "nicht in Europa" in s2.evaluate(qso(1, "DL2XX", "95", "20")).warning


def test_band_mode_changes_per_hour(cty):
    c, s = make("euhfc", cty, lic_year="06")
    calls = ["OE1XX", "DL2XX", "OK1XX", "G4ABC", "PA3XX", "ON4XX"]
    log = []
    for i in range(12):                                   # 12 QSOs, jedes auf anderem Band/Mode
        band, mode = ["20", "40"][i % 2], ["CW", "USB"][(i // 2) % 2]
        log.append(qso(i + 1, calls[i % 6], "82", band, mode, t=f"2026-08-01 13:{i:02d}:00"))
    n, hour = stats.changes_in_hour(log)
    assert n == 11 and hour == "2026-08-01 13"
    s.rebuild(log)
    found = [f for f in logcheck.check(c, log, s) if "Band-/Modewechsel" in f.text]
    assert len(found) == 1 and "11 Band-/Modewechsel" in found[0].text
    # Wechsel beim Stundenübergang zählt zur neuen Stunde
    nxt = qso(99, "OE1XX", "82", "10", "CW", t="2026-08-01 14:00:00")
    assert stats.changes_in_hour(log, nxt) == (1, "2026-08-01 14")


# ------------------------------------------------------------ Termine
@pytest.mark.parametrize("cid, start, hours", [
    ("arrl-10", datetime(2026, 12, 12, 0), 48),
    ("iaru-hf", datetime(2026, 7, 11, 12), 24),      # laut ARRL-Seite: 11.–12. Juli 2026
    ("euhfc", datetime(2026, 8, 1, 12), 12),         # laut Ausschreibung: 1. August 2026
])
def test_schedules_071(cid, start, hours):
    s, e = schedule.period(CONTESTS[cid].schedule, 2026)
    assert s == start and (e - s).total_seconds() == hours * 3600


def test_arrl10_operating_time():
    c = CONTESTS["arrl-10"]
    assert c.max_hours_single == 36 and c.min_break_minutes == 30


# ------------------------------------------------------------ Textkorrektur
def test_no_double_zaehlt_nicht(cty):
    c, s = make("arrl-dx-ssb", cty)
    ev = s.evaluate(qso(1, "OE1XX", "KW", "20", "USB"))
    assert ev.warning == "DX arbeitet nur W/VE (USA/Kanada)"
    assert "zählt nicht" not in ev.warning.lower()
    assert "zählt nicht" not in c.describe(Qso(call="OE1XX"), cty.lookup("OE1XX")).lower()


def test_older_versions_skip_newer_formats(tmp_path, monkeypatch):
    """0.7.0 (Format 2) überspringt die Format-3-Dateien, statt Fehler zu melden."""
    import json
    import shutil
    from gogoham import rulefiles, rulesupdate
    src = tmp_path / "gh"
    src.mkdir()
    for p in rulefiles.BUILTIN_DIR.glob("*.json"):
        shutil.copy(p, src / p.name)
    (src / "index.json").write_text(json.dumps(rulesupdate.make_index(src)), encoding="utf-8")
    (tmp_path / "leer").mkdir()
    monkeypatch.setattr(rulefiles, "BUILTIN_DIR", tmp_path / "leer")
    monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 2)
    res = rulesupdate.check_and_download(src.as_uri() + "/", tmp_path / "data")
    want, rest = builtin_newer_than(2)
    assert sorted(res.skipped) == want
    assert not res.errors and len(res.new) == rest
