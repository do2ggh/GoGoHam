"""0.8.5: WAE DX Contest (CW/SSB) mit QTC-Empfang."""

import json
import shutil
from pathlib import Path

import pytest

from conftest import builtin_newer_than

from gogoham import qtc as qtcmod
from gogoham import rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.contests.rulebased import call_area
from gogoham.cty import CtyDB
from gogoham.db import LogDB
from gogoham.export import cabrillo

HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def make(cty, call="DO2GGH", cid="wae-ssb"):
    c = CONTESTS[cid](cty, Station(call=call))
    return c, Scorer(c)


def qso(i, call, band="20", mode="USB", nr="1", freq=0, t="2026-09-12 10:00:00"):
    return Qso(id=i, time=t, call=call, band=band, mode=mode, freq=freq,
               rst_s="59", rst_r="59", exch_s=f"{i:03d}", exch_r=nr)


# ------------------------------------------------------------ Regel-Dateien
def test_wae_files_format_5_and_valid():
    for cid in ("wae-cw", "wae-ssb"):
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert d["format"] == 5 and rulefiles.validate(d) == []
    assert rulefiles.FORMAT_VERSION >= 5
    assert CONTESTS["wae-cw"].cabrillo_name == "DARC-WAEDC-CW"
    assert CONTESTS["wae-ssb"].cabrillo_name == "DARC-WAEDC-SSB"


def test_084_skips_format_5(tmp_path, monkeypatch):
    """GoGoHam 0.8.4 (Format 4) überspringt die WAE-Dateien sauber."""
    from gogoham import rulesupdate
    src = tmp_path / "gh"
    src.mkdir()
    for p in rulefiles.BUILTIN_DIR.glob("*.json"):
        shutil.copy(p, src / p.name)
    (src / "index.json").write_text(json.dumps(rulesupdate.make_index(src)), encoding="utf-8")
    monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 4)
    monkeypatch.setattr(rulefiles, "BUILTIN_DIR", tmp_path / "leer")
    (tmp_path / "leer").mkdir()
    res = rulesupdate.check_and_download(src.as_uri() + "/", tmp_path / "data")
    want, rest = builtin_newer_than(4)
    assert sorted(res.skipped) == want
    assert not res.errors and len(res.new) == rest


def test_bad_new_blocks_are_reported():
    d = json.loads((rulefiles.BUILTIN_DIR / "wae-cw.json").read_text(encoding="utf-8"))
    d["mult_factor"] = {"80": 0, "99": 2}
    d["qtc"] = {"max_per_station": "zehn", "foo": 1}
    d["multipliers"][1]["areas"] = {"K": ""}
    errs = " ".join(rulefiles.validate(d))
    assert "mult_factor" in errs and "99" in errs and "max_per_station" in errs
    assert "foo" in errs and "call_area" in errs


def test_schedule_second_weekend():
    s, e = schedule.period(CONTESTS["wae-cw"].schedule, 2026)
    assert str(s) == "2026-08-08 00:00:00" and (e - s).total_seconds() == 48 * 3600
    s, _e = schedule.period(CONTESTS["wae-ssb"].schedule, 2026)
    assert str(s) == "2026-09-12 00:00:00"
    assert CONTESTS["wae-ssb"].max_hours_single == 36


# ------------------------------------------------------------ Wertung
def test_call_areas(cty):
    areas = json.loads((rulefiles.BUILTIN_DIR / "wae-ssb.json").read_text(
        encoding="utf-8"))["multipliers"][1]["areas"]
    ca = lambda c: call_area(c, cty.lookup(c), areas)     # noqa: E731
    assert ca("W1AW") == ca("K3ABC/1") == ca("KA1XYZ") == "W1"   # Beispiele der Ausschreibung
    assert ca("VE1AA") == ca("VO1AA") == ca("VY1AA") == "VE1"
    assert ca("JR4ABC") == ca("7K4AA") == "JA4"
    assert ca("UA9AA") == "RA9" and ca("UA0ZZ") == "RA0"
    assert ca("KH6XX") == "" and ca("DL1ABC") == ""                # eigenes Land / kein Gebiet


def test_eu_station_scores_with_band_bonus(cty):
    c, s = make(cty)
    assert c.mult_types == [("country", "Länder"), ("area", "Rufzeichengebiete")]
    evs = [s.evaluate(q, commit=True) for q in (
        qso(1, "W1AW", "80"), qso(2, "K3ABC/1", "80"), qso(3, "N2XX", "80"),
        qso(4, "JR4ABC", "40"), qso(5, "UA9AA", "20"), qso(6, "KH6XX", "20"),
        qso(7, "BY1PK", "15"))]
    assert evs[0].gain == 4                       # 1 Punkt × (1 Multi × 4 auf 80 m)
    assert evs[1].new_mults == []                 # K3ABC/1 zählt als W1 – schon da
    assert evs[5].mults == [("country", "KH6")]
    assert s.total_points == 7
    # 80 m: W1, W2 ×4 = 8 · 40 m: JA4 ×3 · 20 m: RA9, KH6 ×2 = 4 · 15 m: BY1 ×2
    assert s.weighted_mults() == 8 + 3 + 4 + 2 == 17
    assert s.weighted_mults("area") == 15 and s.mult_count() == 6
    assert s.score == 7 * 17
    s.set_qtcs(5)
    assert s.score == (7 + 5) * 17
    s.rebuild([qso(1, "W1AW", "80")])             # Neubewerten behält die QTCs
    assert s.score == (1 + 5) * 4


def test_only_eu_with_non_eu(cty):
    c, s = make(cty)
    ev = s.evaluate(qso(1, "DL1ABC"))
    assert not ev.valid and "nur Stationen außerhalb Europas" in ev.warning
    dx, s2 = make(cty, "W1AW")
    assert dx.mult_types == [("country", "Länder")]       # DX: Länder der WAE-Liste
    assert not s2.evaluate(qso(1, "K1AA")).valid
    ev = s2.evaluate(qso(2, "GM/DL1ABC/S"))
    assert ev.valid
    assert not dx.qtc_receiving() and c.qtc_receiving()


def test_band_segments(cty):
    # 0.10.28: die Liste der Ausschreibung sind die CONTESTFREIEN Bereiche (darc.de)
    c, _s = make(cty, cid="wae-ssb")
    assert c.segment_problem(qso(1, "W1AW", "40", freq=7_080_000)) is None
    assert "contestfreien" in c.segment_problem(qso(1, "W1AW", "40", freq=7_110_000))
    assert c.segment_problem(qso(1, "W1AW", "15", freq=21_200_000)) is None


# ------------------------------------------------------------ QTC
def test_parse_qtc_lines():
    assert qtcmod.parse_line("1307 dl1abc 042") == (("1307", "DL1ABC", "042"), "")
    assert qtcmod.parse_line("13:07 DL1ABC 42")[0] == ("1307", "DL1ABC", "42")
    assert qtcmod.parse_line("907 DL1ABC 1")[0][0] == "0907"
    assert "unvollständig" in qtcmod.parse_line("1307 DL1A? 042")[1]
    assert "gibt es nicht" in qtcmod.parse_line("2575 DL1ABC 1")[1]
    assert qtcmod.parse_line("1307 DL1ABC")[1]
    assert qtcmod.parse_line("") == (None, "")
    assert qtcmod.parse_series("3/5") == (3, 5) and qtcmod.parse_series("3") == (3, 0)
    assert qtcmod.parse_series("3/11") is None and qtcmod.parse_series("x") is None


def test_qtc_checks():
    have = [qtcmod.Qtc(sender="W1AW", series=1, total=2, qso_call="OK1AA", qso_nr="12"),
            qtcmod.Qtc(sender="W1AW", series=1, total=2, qso_call="G4AAA", qso_nr="8")]
    assert qtcmod.remaining(have, "w1aw") == 8 and qtcmod.remaining(have, "K1AA") == 10
    assert qtcmod.next_series_hint(have, "W1AW") == 2
    lp = lambda e, earlier=(): qtcmod.line_problem(e, "W1AW", "DO2GGH", have, earlier)  # noqa
    assert "Eigenes Rufzeichen" in lp(("1300", "DO2GGH/P", "5"))
    assert "Gegenstation selbst" in lp(("1300", "W1AW", "5"))
    assert "schon gemeldet" in lp(("1300", "OK1AA", "012"))
    assert "in dieser Serie" in lp(("1300", "SP1A", "3"), [("1200", "SP1A", "3")])
    assert lp(("1300", "SP1A", "3")) == ""


def test_qtc_in_db_and_cabrillo(cty, tmp_path):
    c, s = make(cty)
    db = LogDB(tmp_path / "wae.ggh")
    q = qso(1, "W1AW", "15", freq=21_250_000)
    db.add(q)
    t = qtcmod.Qtc(time="2026-09-12 10:28:00", band="15", mode="USB", freq=21_250_000,
                   sender="W1AW", series=7, total=10, qso_time="1332", qso_call="S59XYZ",
                   qso_nr="112")
    db.add_qtcs([t])
    got = db.all_qtcs()
    assert len(got) == 1 and got[0].qso_call == "S59XYZ" and got[0].id is not None
    got[0].qso_nr = "113"
    db.update_qtc(got[0])
    assert db.all_qtcs()[0].qso_nr == "113"
    s.rebuild([q])
    s.set_qtcs(1)
    txt = cabrillo(c, {"mycall": "DO2GGH"}, [q], s, db.all_qtcs())
    line = [ln for ln in txt.splitlines() if ln.startswith("QTC:")][0]
    assert line.split() == ["QTC:", "21250", "PH", "2026-09-12", "1028", "DO2GGH", "7/10",
                            "W1AW", "1332", "S59XYZ", "113"]
    assert "CONTEST: DARC-WAEDC-SSB" in txt and "CLAIMED-SCORE: 4" in txt   # (1+1) × 2
    db.delete_qtc(got[0].id)
    assert db.all_qtcs() == []
    db.close()


def test_old_contests_ignore_qtcs(cty):
    c = CONTESTS["cqww-ssb"](cty, Station(call="DO2GGH", cq_zone=14))
    s = Scorer(c)
    s.set_qtcs(5)
    assert s.qtc_points == 0 and not c.qtc and c.mult_weight("80") == 1
