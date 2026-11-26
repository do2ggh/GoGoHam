"""0.7.0: CQ WW 160 m, ARRL DX und neue Bausteine (Austausch je Herkunft, States, Provinzen)."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from conftest import builtin_newer_than

from gogoham import regions, rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.cty import CtyDB
from gogoham.export import adif

HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def make(cid, cty, call="DL1ABC", zone=14, state="", power="100"):
    c = CONTESTS[cid](cty, Station(call=call, cq_zone=zone, state=state, power=power))
    return c, Scorer(c)


def qso(i, call, ex, band="160", mode="CW"):
    return Qso(id=i, time="2026-01-24 00:00:00", call=call, band=band, mode=mode,
               rst_s="599", rst_r="599", exch_r=ex)


# ------------------------------------------------------------ Listen
def test_regions_lists():
    assert len(regions.US_STATES) == 51 and len(regions.STATES_48_DC) == 49
    assert "DC" in regions.STATES_48_DC and "AK" not in regions.STATES_48_DC
    assert len(regions.VE_PROVINCES) == 14
    assert regions.normalize_state("ct") == "CT" and regions.normalize_state("Texas") == "TX"
    assert regions.normalize_state("XX") is None
    assert regions.normalize_province("VO1") == "NF" and regions.normalize_province("vo2") == "LB"
    assert regions.normalize_province("PEI") == "PE" and regions.normalize_province("VE3") == "ON"
    assert regions.normalize_province("PQ") == "QC" and regions.normalize_province("ZZ") is None
    assert regions.province_from_call("VE3ABC") == "ON"
    assert regions.province_from_call("VA7XX") == "BC"
    assert regions.province_from_call("VO1AA") == "NF" and regions.province_from_call("VY2ZZ") == "PE"
    assert regions.province_from_call("VE1ABC") == ""          # NS oder NB – nicht raten
    assert regions.province_from_call("VE3ABC/7") == ""


def test_region_of_stations(cty):
    assert regions.region(cty.lookup("W1AW")) == "us"
    assert regions.region(cty.lookup("VE3ABC")) == "ve"
    assert regions.region(cty.lookup("KH6XX")) == "dx"          # Hawaii zählt als DX
    assert regions.region(cty.lookup("DL1ABC")) == "dl"          # ab 0.8.4 (DARC)
    assert regions.region(cty.lookup("OE1ABC")) == "dx"
    assert regions.region(cty.lookup("K1ABC/MM")) == "mm"
    assert regions.region(None) is None


# ------------------------------------------------------------ CQ 160
def test_cq160_points_and_mults(cty):
    c, s = make("cq160-cw", cty)
    assert c.sent_exchange(1) == "14"
    assert [k for k, _l in c.mult_types] == ["state", "province", "country"]
    log = [qso(1, "W1AW", "CT"),        # anderer Kontinent: 10, State CT
           qso(2, "VE3XYZ", "ON"),      # 10, Provinz ON
           qso(3, "DL2XX", "14"),       # eigenes Land: 2, Land DL
           qso(4, "OE1XX", "15"),       # gleicher Kontinent: 5, Land OE
           qso(5, "KH6XX", "31"),       # anderer Kontinent: 10, Land KH6
           qso(6, "K1ABC/MM", "08"),    # Maritime Mobile: 5, kein Multi
           qso(7, "W1AW", "CT"),        # Dupe
           qso(8, "JA1XX", "25")]       # 10, Land JA
    s.rebuild(log)
    assert [s.evals[i].points for i in range(1, 9)] == [10, 10, 2, 5, 10, 5, 0, 10]
    assert s.total_points == 52
    assert s.mults[("state", "160")] == {"CT"}
    assert s.mults[("province", "160")] == {"ON"}
    assert s.mults[("country", "160")] == {"DL", "OE", "KH6", "JA"}    # USA/Kanada nicht als Land
    assert s.score == 52 * 6
    assert s.evals[1].mults == [("state", "CT")]


def test_cq160_exchange_by_origin(cty):
    c, _s = make("cq160-ssb", cty)
    w, ve, dl = cty.lookup("W1AW"), cty.lookup("VE3XYZ"), cty.lookup("DL2XX")
    assert c.expected_kind(w) == "state" and c.expected_kind(ve) == "province"
    assert c.expected_kind(dl) == "cq_zone"
    assert c.default_rcvd_exchange(ve, "VE3XYZ") == "ON"
    assert c.default_rcvd_exchange(dl, "DL2XX") == "14"
    assert c.default_rcvd_exchange(w, "W1AW") == ""             # State muss man hören
    assert c.validate_exchange("CT", w) is None
    assert "US-State" in c.validate_exchange("14", w)
    assert "Provinz" in c.validate_exchange("CT", ve)
    assert "Zone" in c.validate_exchange("CT", dl)
    assert c.validate_exchange("ON") is None                    # ohne Land: alles Gültige ok
    assert "erfragen" in c.describe(Qso(call="W1AW"), w)


def test_cq160_us_station(cty):
    c, s = make("cq160-cw", cty, call="W1AW", zone=5, state="CT")
    assert c.sent_exchange(1) == "CT"
    s.rebuild([qso(1, "K5XX", "TX"), qso(2, "VE3XYZ", "ON"), qso(3, "DL1ABC", "14")])
    assert [s.evals[i].points for i in (1, 2, 3)] == [2, 5, 10]   # eigenes Land / NA / EU


# ------------------------------------------------------------ ARRL DX
def test_arrl_dx_as_dx_station(cty):
    c, s = make("arrl-dx-ssb", cty, power="KW")
    assert c.sent_exchange(1) == "KW"
    assert [k for k, _l in c.mult_types] == ["state", "province"]
    log = [qso(1, "W1AW", "CT", "20", "USB"), qso(2, "VE3XYZ", "ON", "20", "USB"),
           qso(3, "W1AW", "CT", "40", "USB"),           # anderes Band: neuer Multi
           qso(4, "DL2XX", "KW", "20", "USB"),          # DX–DX zählt nicht
           qso(5, "KH6XX", "100", "20", "USB")]         # Hawaii ist DX
    s.rebuild(log)
    assert [s.evals[i].points for i in range(1, 6)] == [3, 3, 3, 0, 0]
    assert "DX arbeitet nur W/VE" in s.evals[4].warning and not s.evals[4].valid
    assert s.mult_count() == 3 and s.score == 27


def test_arrl_dx_as_w_station(cty):
    c, s = make("arrl-dx-cw", cty, call="W1AW", zone=5, state="CT")
    assert c.sent_exchange(1) == "CT"
    assert [k for k, _l in c.mult_types] == ["country"]
    s.rebuild([qso(1, "DL1ABC", "100", "20"), qso(2, "KH6XX", "KW", "20"),
               qso(3, "VE3XYZ", "ON", "20"), qso(4, "GM3ZET", "100", "20")])
    assert [s.evals[i].points for i in (1, 2, 3, 4)] == [3, 3, 0, 3]
    # Shetland (WAE) zählt im ARRL DX als Schottland (nur DXCC)
    assert s.mults[("country", "20")] == {"DL", "KH6", "GM"}
    assert c.validate_exchange("KW", cty.lookup("DL1ABC")) is None
    assert "Leistung" in c.validate_exchange("1500W!", cty.lookup("DL1ABC"))


def test_adif_has_state_and_province(cty):
    c, _s = make("arrl-dx-ssb", cty)
    out = adif(c, {"mycall": "DL1ABC"}, [qso(1, "W1AW", "CT", "20", "USB"),
                                         qso(2, "VE3XYZ", "ON", "20", "USB")])
    assert "<STATE:2>CT" in out and "<VE_PROV:2>ON" in out


# ------------------------------------------------------------ Termine
@pytest.mark.parametrize("cid, year, start", [
    ("cq160-cw", 2026, datetime(2026, 1, 23, 22)),     # laut Ausschreibung 2026
    ("cq160-ssb", 2026, datetime(2026, 2, 27, 22)),
    ("arrl-dx-cw", 2026, datetime(2026, 2, 21, 0)),
    ("arrl-dx-ssb", 2026, datetime(2026, 3, 7, 0)),
    ("arrl-dx-cw", 2025, datetime(2025, 2, 15, 0)),
    ("cqww-ssb", 2026, datetime(2026, 10, 24, 0)),
])
def test_schedules(cid, year, start):
    s, e = schedule.period(CONTESTS[cid].schedule, year)
    assert s == start and (e - s).total_seconds() == 48 * 3600


def test_cq160_operating_time():
    c = CONTESTS["cq160-cw"]
    assert c.max_hours_single == 30 and c.min_break_minutes == 30


# ------------------------------------------------------------ Format 2 und ältere Versionen
def test_new_files_are_format_2_old_ones_format_1():
    for p in rulefiles.BUILTIN_DIR.glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        want = 24 if d["id"] in ("vfdb-dlpx-cw", "vfdb-dlpx-ssb", "agcw-htp-80", "agcw-htp-40", "agcw-sta") else \
            23 if d["id"] in ("ncqp", "wa-salmon-run", "podxs-stpat", "podxs-nmj") else \
            22 if d["id"] in ("podxs-pumpkin", "podxs-tp-nov", "podxs-tp-dec", "ohqp", "miqp", "inqp", "txqp", "nyqp", "rsgb-160-feb", "rsgb-160-nov", "ocdx-ssb", "ocdx-cw", "ukei-cw", "pskfest") else \
            21 if d["id"] in ("neqp", "7qp") else \
            20 if d["id"] in ("ea-rtty", "ea-psk63", "volta-rtty") else \
            19 if d["id"] in ("jarl-ww-rtty", "arrl-ss-cw", "arrl-ss-ssb", "af-all-mode", "baltic", "sartg-rtty", "sartg-ny-rtty", "makrothen", "arrl-vhf-jun", "arrl-vhf-sep", "cqww-vhf", "cqww-vhf-digi", "iaru-50", "iaru-70", "alpe-adria-uhf") else \
            18 if d["id"] in ("jidx-cw", "jidx-ph", "sac-cw", "sac-ssb", "canada-day", "naqp-cw", "naqp-ssb", "naqp-rtty", "alpe-adria-vhf", "arrl-digi", "bartg-rtty", "dig-ssb", "dig-cw", "dtc", "aoec-160") else \
            17 if d["id"] in ("arrl-160", "stew-perry") else \
            16 if d["id"] in ("ref-cw", "ref-ssb", "pacc") or d["id"].startswith("franken-") else \
            15 if d["id"] in ("hsc", "schwaben-kw", "schwaben-ukw") else \
            14 if d["id"].startswith(("agcw-qrp", "franken-")) else \
            10 if d["id"].startswith("bbt-") else \
            12 if d["id"] in ("cqww-cw", "cqww-ssb", "wpx-cw", "wpx-ssb", "arrl-dx-cw",
                                 "arrl-dx-ssb", "iaru-hf") else \
            11 if d["id"] in ("lzdx", "9adx", "agcw-hny", "ref-cw", "ref-ssb") else \
            10 if d["id"] in ("darc-vhf", "darc-ukw-spring", "darc-microwave", "marconi-vhf", "darc-ukw-fd-winter", "darc-ukw-fd-summer") else \
            9 if d["id"] in ("darc-fd-cw", "darc-fd-ssb", "darc-ft4", "darc-cwa",
                                "darc-ac") else \
            8 if d["id"] in ("iaru-vhf", "iaru-uhf") else \
            7 if d["id"] in ("okom-cw", "okom-ssb", "hadx", "uba-cw", "uba-ssb", "pacc",
                                "spdx", "yodx", "ea-majestad-cw", "ea-majestad-ssb", "undx") else \
            6 if d["id"] in ("rdxc", "iota", "aa-cw", "aa-ssb") else \
            13 if d["id"] in ("cqww-rtty", "arrl-rtty", "wae-rtty") else \
            12 if d["id"] == "wpx-rtty" else \
            5 if d["id"].startswith("wae-") else \
            4 if d["id"] in ("wag", "darc-10m", "darc-xmas", "darc-easter") else \
            3 if d["id"] in ("arrl-10", "iaru-hf", "euhfc") else \
            2 if d["id"].startswith(("cq160", "arrl-dx")) else 1
        assert d["format"] == want, p.name


def test_old_gogoham_skips_format_2(tmp_path, monkeypatch):
    """GoGoHam 0.6.5 (Format 1) soll die neuen Dateien überspringen, nicht als Fehler melden."""
    import shutil
    from gogoham import rulesupdate
    src = tmp_path / "gh"
    src.mkdir()
    for p in rulefiles.BUILTIN_DIR.glob("*.json"):
        shutil.copy(p, src / p.name)
    (src / "index.json").write_text(json.dumps(rulesupdate.make_index(src)), encoding="utf-8")
    monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 1)
    monkeypatch.setattr(rulefiles, "BUILTIN_DIR", tmp_path / "leer")
    (tmp_path / "leer").mkdir()
    res = rulesupdate.check_and_download(src.as_uri() + "/", tmp_path / "data")
    want, rest = builtin_newer_than(1)
    assert sorted(res.skipped) == want
    assert not res.errors and len(res.new) == rest
