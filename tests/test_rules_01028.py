"""0.10.28: Korrekturen aus der Regel-Prüfung – CQ 160 CW (Termin), WAE (contestfreie
Bereiche), OK/OM DX (RU/BY gesperrt, /MM 5, offizielle Bezirksliste), AGCW QRP-Party (nur
DXCC), Cabrillo-Namen Ostern/Weihnachten/FT4/YO DX."""

from pathlib import Path

import pytest

from gogoham import schedule
from gogoham.bands import DEFAULT_FREQ
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.contests.rulebased import normalize_district
from gogoham.cty import CtyDB

HERE = Path(__file__).parent

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
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def make(cid, cty, call="DL1ABC", **st):
    c = CONTESTS[cid](cty, Station(call=call, lookup=cty.lookup(call), **st))
    return c, Scorer(c)


def qso(i, call, ex, band="20", mode="CW", freq=0, t="2026-11-14 13:00:00"):
    return Qso(id=i, time=t, call=call, band=band, mode=mode,
               freq=freq or DEFAULT_FREQ[band], rst_s="599", rst_r="599", exch_r=ex)


def starts(cid, year):
    return [a.strftime("%Y-%m-%d %H:%M")
            for a, _b in schedule.periods(CONTESTS[cid].rules["schedule"], year)]


def test_cq160_cw_last_full_weekend():
    # belegt (cq160.com, WA7BNM): Januar mit 5 Samstagen → letztes volles Wochenende
    assert starts("cq160-cw", 2016) == ["2016-01-29 22:00"]
    assert starts("cq160-cw", 2021) == ["2021-01-29 22:00"]
    assert starts("cq160-cw", 2022) == ["2022-01-28 22:00"]
    assert starts("cq160-cw", 2026) == ["2026-01-23 22:00"]
    assert starts("cq160-cw", 2027) == ["2027-01-29 22:00"]
    assert starts("cq160-cw", 2028) == ["2028-01-28 22:00"]
    assert starts("cq160-ssb", 2026) == ["2026-02-27 22:00"]       # SSB unverändert


def test_wae_contest_free_segments(cty):
    c, _s = make("wae-cw", cty)
    assert c.segment_problem(qso(1, "W1AW", "1", "80", freq=3_520_000)) is None
    assert c.segment_problem(qso(1, "W1AW", "1", "40", freq=7_010_000)) is None
    assert "contestfreien" in c.segment_problem(qso(1, "W1AW", "1", "80", freq=3_600_000))
    assert "contestfreien" in c.segment_problem(qso(1, "W1AW", "1", "20", freq=14_070_000))
    c, _s = make("wae-rtty", cty)
    assert "contestfreien" in c.segment_problem(qso(1, "W1AW", "1", "20", "RTTY",
                                                    freq=14_100_000))
    assert c.segment_problem(qso(1, "W1AW", "1", "20", "RTTY", freq=14_085_000)) is None


def test_okom_district_list():
    host = CONTESTS["okom-cw"].host
    assert len(host["codes"]) == 165
    assert normalize_district("zvo", host) == "ZVO"
    assert normalize_district("XYZ", host) == ""


def test_okom_blocked_and_maritime(cty):
    c, s = make("okom-cw", cty)
    ev = s.evaluate(qso(1, "UA3AAA", "5"), commit=True)
    assert not ev.valid or ev.points == 0
    ev = s.evaluate(qso(2, "EU1AA", "7"), commit=True)
    assert not ev.valid or ev.points == 0
    ev = s.evaluate(qso(3, "DL2XX/MM", "9"), commit=True)
    assert ev.points == 5 and not ev.new_mults
    c, s = make("okom-ssb", cty, call="OK1A", district="APA")
    ev = s.evaluate(qso(1, "K1AB/MM", "3", mode="USB", t="2027-04-10 13:00:00"), commit=True)
    assert ev.points == 5 and not ev.new_mults


def test_qrp_party_dxcc_only(cty):
    c, s = make("agcw-qrp-party", cty, pclass="A")
    ev = s.evaluate(qso(1, "GM4ABC", "001 A", "40"), commit=True)
    assert len(ev.new_mults) == 1
    ev = s.evaluate(qso(2, "GM3ZET", "002 A", "40"), commit=True)       # Shetland = WAE-Gebiet
    assert ev.points == 2 and ev.new_mults == []


def test_cabrillo_names():
    names = {cid: CONTESTS[cid].cabrillo_name
             for cid in ("darc-easter", "darc-xmas", "darc-ft4", "yodx", "darc-ac",
                         "agcw-qrp-party")}
    assert names == {"darc-easter": "EASTER", "darc-xmas": "XMAS", "darc-ft4": "FT4",
                     "yodx": "YO-DX-HF", "darc-ac": "WAG", "agcw-qrp-party": "AGCW QRP"}


# ------------------------------------------------------------ Format 16
FRANCE = """France:                   14:  27:  EU:   46.00:    -2.00:    -1.0:  F:
    F,TM;
Guadeloupe:               08:  11:  NA:   16.13:    61.67:     4.0:  FG:
    FG;
"""


@pytest.fixture(scope="module")
def cty_f(tmp_path_factory):
    p = tmp_path_factory.mktemp("cty") / "cty.dat"
    p.write_text((HERE / "cty_sample.dat").read_text(encoding="utf-8") + FRANCE,
                 encoding="utf-8")
    return CtyDB.from_file(p)


def test_ref_french_station(cty_f):
    # Règlement Coupe du REF 13/5/2026 §6(a): F gleicher Kontinent 6, F anderer Kontinent 15,
    # Ausland gleicher Kontinent 1, anderer Kontinent 2, /MM 3; Multis DXCC ohne WAE
    c, s = make("ref-cw", cty_f, call="F5ABC", district="75")
    t = "2027-01-30 10:00:00"
    evs = [s.evaluate(qso(i, cl, ex, "40", t=t), commit=True) for i, (cl, ex) in enumerate([
        ("F6XYZ", "69"), ("FG5AA", "FG"), ("DL1AA", "001"), ("K1AB", "002"),
        ("DL2XX/MM", "003"), ("GM3ZET", "004"), ("GM4ABC", "005")], 1)]
    assert [e.points for e in evs] == [6, 15, 1, 2, 3, 1, 1]
    assert ("country", "DL") in evs[2].new_mults and not evs[4].new_mults
    assert len([m for m in evs[5].new_mults if m[0] == "country"]) == 1   # Shetland = GM
    assert not [m for m in evs[6].new_mults if m[0] == "country"]


def test_ref_foreign_station(cty_f):
    # §6(b): Ausland ↔ F gleicher Kontinent 1, anderer Kontinent 3, /MM 3
    c, s = make("ref-cw", cty_f, call="DL1ABC")
    t = "2027-01-30 10:00:00"
    evs = [s.evaluate(qso(i, cl, ex, "40", t=t), commit=True) for i, (cl, ex) in enumerate([
        ("F6XYZ", "69"), ("FG5AA", "FG"), ("K1AB/MM", "001"), ("OK1AA", "002")], 1)]
    assert [e.points for e in evs[:3]] == [1, 3, 3]
    assert evs[2].valid and not evs[2].new_mults
    assert evs[3].points == 0                                # Ausland untereinander


def test_pacc_canadian_areas(cty):
    c, s = make("pacc", cty, call="PA1A", district="NH")
    t = "2027-02-13 13:00:00"
    evs = [s.evaluate(qso(i, cl, "1", t=t), commit=True)
           for i, cl in enumerate(["VE1AA", "VO1AA", "VY1AA", "VA2AA", "VE2BB", "VY0A"], 1)]
    areas = [[m[1] for m in e.new_mults if m[0] == "area"] for e in evs]
    assert areas == [["VE1"], ["VO1"], ["VY1"], ["VE2"], [], ["VY0"]]


def test_wae_canadian_areas_unchanged(cty):
    from gogoham.contests.rulebased import call_area
    areas = CONTESTS["wae-cw"].rules["multipliers"]
    a = next(m for m in areas if m["type"] == "call_area")["areas"]
    assert call_area("VO1AA", cty.lookup("VO1AA"), a) == "VE1"      # WAE: VO1 zählt als VE1


def test_all_asian_maritime(cty):
    # JARL-Regel 7(4): /MM zählt für Asiaten wie ein QSO in Asien, ohne Multi
    c, s = make("aa-cw", cty, call="JA1ABC")
    t = "2027-06-19 10:00:00"
    evs = [s.evaluate(qso(i, "DL2XX/MM", "50", band, t=t), commit=True)
           for i, band in enumerate(["20", "80", "160"], 1)]
    assert [e.points for e in evs] == [1, 2, 3] and not any(e.new_mults for e in evs)
    c, s = make("aa-cw", cty, call="DL1ABC")
    assert not s.evaluate(qso(1, "JA2XX/MM", "50", t=t)).valid       # Nicht-Asiaten: nein


# ------------------------------------------------------------ Russian DX: RI1AN
ANTARCTICA = """Antarctica:               13:  74:  SA:  -90.00:     0.00:     0.0:  CE9:
    CE9,KC4,RI1AN,VP8,=RI1ANC;
"""


@pytest.fixture(scope="module")
def cty_an(tmp_path_factory):
    p = tmp_path_factory.mktemp("cty") / "cty.dat"
    p.write_text((HERE / "cty_sample.dat").read_text(encoding="utf-8") + ANTARCTICA,
                 encoding="utf-8")
    return CtyDB.from_file(p)


def test_ri1an_lookup(cty_an):
    assert cty_an.lookup("RI1ANC").ru_antarctic and cty_an.lookup("RI1ANZ").ru_antarctic
    assert cty_an.lookup("RI1ANC").country == "CE9"              # Land bleibt Antarktis
    assert not cty_an.lookup("KC4AAA").ru_antarctic
    assert not cty_an.lookup("UA1AAA").ru_antarctic


def test_rdxc_ri1an(cty_an):
    # Reglement RDXC 2026, 7.3: RI1AN zählt wie das europäische Russland, ist eigenes
    # DXCC-Gebiet und eigene Oblast „AN“ (doppelter Multi)
    t = "2027-03-20 12:00:00"
    c, s = make("rdxc", cty_an, call="DO2GGH")
    assert c.expected_kind(cty_an.lookup("RI1ANC")) == "oblast"
    ev = s.evaluate(qso(1, "RI1ANC", "AN", t=t), commit=True)
    assert ev.points == 10
    assert sorted(ev.new_mults) == [("country", "CE9"), ("oblast", "AN")]
    ev = s.evaluate(qso(2, "KC4AAA", "5", t=t), commit=True)    # US-Station: Antarktis = DX
    assert ev.points == 5
    c, s = make("rdxc", cty_an, call="UA3AAA", oblast="MA")
    assert s.evaluate(qso(1, "RI1ANC", "AN", t=t), commit=True).points == 2   # wie EU-Russland
    c, s = make("rdxc", cty_an, call="UA9AA", oblast="SV")
    assert s.evaluate(qso(1, "RI1ANC", "AN", t=t), commit=True).points == 5


# ------------------------------------------------------------ 0.10.28.2: Frankencontest
def test_franken_nm_abroad(cty):
    # Ausschreibung 2026: „Teilnehmer außerhalb Deutschlands, auch wenn diese selbst Mitglied
    # im DARC sind, geben anstatt des DOKs die Kontrollziffer ‚NM‘“
    for cid, dl, abroad in (("franken-a", "B26", "NM"), ("franken-k", "B26 JN59NO", "NM JN59NO")):
        c, _s = make(cid, cty, call="DL1ABC", dok="B26", grid="JN59NO")
        assert c.sent_exchange(1) == dl
        c, _s = make(cid, cty, call="OE1ABC", dok="B26", grid="JN59NO")
        assert c.sent_exchange(1) == abroad
    seg = CONTESTS["franken-l"].rules["band_segments"]
    assert [433050, 433987] in seg["PH"]["allowed"]          # FM zählt als Phone
