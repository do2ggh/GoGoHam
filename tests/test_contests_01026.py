"""0.10.26: HSC CW Contest und Schwaben-Contest (KW und UKW). Neu (Format 15): Austausch
„member“ (Mitgliedsnummer oder NM), Punkte „member“ und „dok“ (DOK-Bonus mit Klub- und
Ausbildungsstationen), „dok_or_serial“, „dok_grid6“ mit Nummer statt DOK, Dupe „band_opmode“
(SSB und FM getrennt), Zeitfenster je Betriebsart, Termin mit weiteren Terminen „also“."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from gogoham import rulefiles, schedule
from gogoham.bands import DEFAULT_FREQ, op_mode
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.contests.rulebased import is_club_call, is_training_call, station_fields
from gogoham.cty import CtyDB
from gogoham.export import cabrillo_qso_line

HERE = Path(__file__).parent
NEW = ("hsc", "schwaben-kw", "schwaben-ukw")


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def make(cid, cty, call="DL1ABC", **st):
    c = CONTESTS[cid](cty, Station(call=call, lookup=cty.lookup(call), **st))
    return c, Scorer(c)


def qso(i, call, ex, band="40", mode="CW", t="2027-02-28 14:10:00"):
    return Qso(id=i, time=t, call=call, band=band, mode=mode, freq=DEFAULT_FREQ[band],
               rst_s="599" if mode == "CW" else "59", rst_r="599" if mode == "CW" else "59",
               exch_r=ex)


def first(cid, n=1):
    return [s for s, _ in schedule.upcoming(CONTESTS[cid].rules["schedule"],
                                            datetime(2026, 11, 14), n)]


# ------------------------------------------------------------ Dateien und Termine
def test_files_need_format_15(monkeypatch):
    for cid in NEW:
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert d["format"] == 15 and rulefiles.validate(d) == []
        monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 14)
        assert "neuere GoGoHam-Version" in rulefiles.validate(d)[0]
        monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 15)


def test_validate_new_blocks():
    d = json.loads((rulefiles.BUILTIN_DIR / "schwaben-ukw.json").read_text(encoding="utf-8"))
    bad = dict(d, points={"type": "dok", "default": 1, "match": 5})
    assert any("dok_pattern" in e for e in rulefiles.validate(bad))
    bad = dict(d, band_windows=[{"weekday": 5, "from": "1200", "to": "1300", "bands": ["2"],
                                 "modes": ["PSK"]}])
    assert any("band_windows" in e for e in rulefiles.validate(bad))
    h = json.loads((rulefiles.BUILTIN_DIR / "hsc.json").read_text(encoding="utf-8"))
    assert any("non_member" in e for e in rulefiles.validate(
        dict(h, points={"type": "member", "member": 5})))
    assert any("also" in e for e in rulefiles.validate(
        dict(h, schedule=dict(h["schedule"], also=[]))))
    assert any("Mitgliedsnummer" in e for e in rulefiles.validate(
        dict(h, exchange=[{"field": "rst"}, {"field": "serial"}])))


def test_dates():
    # HSC: letzter Sonntag im Februar und erster Sonntag im November, 14–17 UTC
    got = [s for s, _ in schedule.upcoming(CONTESTS["hsc"].rules["schedule"],
                                           datetime(2026, 1, 1), 2)]
    assert got == [datetime(2026, 2, 22, 14), datetime(2026, 11, 1, 14)]   # wie ausgeschrieben
    assert first("hsc", 2) == [datetime(2027, 2, 28, 14), datetime(2027, 11, 7, 14)]
    # Schwaben: Samstag, 2. Januar 2027 – KW 07–11, UKW 12–16 UTC
    assert schedule.next_period(CONTESTS["schwaben-kw"].rules["schedule"],
                                datetime(2026, 11, 14)) == (datetime(2027, 1, 2, 7),
                                                            datetime(2027, 1, 2, 11))
    assert first("schwaben-ukw") == [datetime(2027, 1, 2, 12)]
    # nie am Neujahrstag: Chronik OV T01 – 2005, 2011, 2022 je am 8. Januar, sonst 1. Samstag
    rule = CONTESTS["schwaben-kw"].rules["schedule"]
    for y, day in ((2005, 8), (2011, 8), (2016, 2), (2020, 4), (2022, 8), (2023, 7),
                   (2024, 6), (2025, 4), (2028, 8)):
        assert schedule.periods(rule, y)[0][0] == datetime(y, 1, day, 7), y


def test_calls_and_op_mode():
    assert is_club_call("DL0T") and is_club_call("DF0XX/P") and is_club_call("DA0HQ")
    assert not is_club_call("DL1ABC") and not is_club_call("OE0ABC")
    assert is_training_call("DN1ABC") and not is_training_call("DO1ABC")
    assert [op_mode(m) for m in ("USB", "LSB", "FM", "CW", "AM", "RTTY")] == \
        ["SSB", "SSB", "FM", "CW", "AM", "RY"]


# ------------------------------------------------------------ HSC
def test_hsc_points_mults_and_dupes(cty):
    c, s = make("hsc", cty, member="1688")
    assert c.sent_exchange(1) == "1688"
    assert make("hsc", cty)[0].sent_exchange(7) == "NM"           # Nicht-Mitglied
    assert "member" in station_fields(CONTESTS["hsc"]) and not c.uses_serial
    s.evaluate(qso(1, "DK5XY", "1537"), commit=True)              # Mitglied 5, DL
    s.evaluate(qso(2, "OE1ABC", "NM"), commit=True)               # Nicht-Mitglied 2, OE
    s.evaluate(qso(3, "OK1AB", "811"), commit=True)               # 5, OK
    s.evaluate(qso(4, "DK5XY", "1537", band="80"), commit=True)   # anderes Band: neu, DL auf 80
    ev = s.evaluate(qso(5, "DK5XY", "1537"))                      # Dupe auf 40 m
    assert ev.dupe
    assert s.total_points == 17 and s.score == 17 * 4             # 3 Länder auf 40 + 1 auf 80
    assert c.validate_exchange("NM") is None and c.validate_exchange("1688") is None
    assert c.validate_exchange("12A")
    line = cabrillo_qso_line(c, qso(9, "OE1ABC", "NM"), "DL1ABC")
    assert "599 NM" in line and line.split()[2] == "CW"


# ------------------------------------------------------------ Schwaben KW
def test_schwaben_kw_points(cty):
    c, s = make("schwaben-kw", cty, dok="B37")
    assert c.sent_exchange(3) == "B37"
    t = "2027-01-02 07:10:00"
    cases = [("DL2AB", "C01", 1),          # irgendein DOK: 1
             ("DK5XY", "T05", 5),          # Schwaben-DOK: 5
             ("DL4EF", "Z30", 5),          # Z30: 5
             ("DL0T", "T18", 10),          # Klubstation aus T: 10
             ("DN1ABC", "T05", 10),        # Ausbildungsrufzeichen aus T: 10
             ("DO1XYZ", "T05", 5),         # DO ist keine Ausbildungsstation
             ("DL0ABC", "B36", 1),         # Klubstation, aber nicht aus T: 1
             ("DL7XX", "012", 1),          # DL ohne DOK: laufende Nummer
             ("OE1ABC", "023", 1)]         # Ausland: Nummer
    for i, (call, ex, pts) in enumerate(cases, 1):
        q = qso(i, call, ex, band="80", t=t)
        assert c.validate_exchange(ex, cty.lookup(call)) is None, call
        assert s.evaluate(q, commit=True).points == pts, call
    assert s.score == sum(p for *_, p in cases)                   # nur Summe, keine Multis
    assert c.validate_exchange("T5", cty.lookup("DK5XY"))         # Null vergessen


def test_schwaben_kw_without_dok_sends_serial(cty):
    c, _s = make("schwaben-kw", cty)
    assert c.sent_exchange(4) == "004" and c.uses_serial


def test_schwaben_kw_windows_and_dupes(cty):
    c, s = make("schwaben-kw", cty, dok="T01")
    assert c.window_problem(qso(1, "DK5XY", "T05", band="80", t="2027-01-02 07:30:00")) is None
    msg = c.window_problem(qso(1, "DK5XY", "T05", band="80", t="2027-01-02 08:30:00"))
    assert msg and "07:00" in msg                                 # 80 m CW nur 07–08
    assert c.window_problem(qso(1, "DK5XY", "T05", band="80", mode="LSB",
                                t="2027-01-02 08:30:00")) is None # 80 m SSB 08–09
    assert c.window_problem(qso(1, "DK5XY", "T05", band="40", mode="USB",
                                t="2027-01-02 10:59:00")) is None
    s.evaluate(qso(1, "DK5XY", "T05", band="80", t="2027-01-02 07:30:00"), commit=True)
    ev = s.evaluate(qso(2, "DK5XY", "T05", band="80", mode="LSB", t="2027-01-02 08:10:00"))
    assert not ev.dupe                                            # je Band und Betriebsart
    ev = s.evaluate(qso(3, "DK5XY", "T05", band="80", t="2027-01-02 07:40:00"))
    assert ev.dupe


def test_schwaben_kw_cabrillo(cty):
    c, _s = make("schwaben-kw", cty, dok="T99")
    q = qso(1, "DL0T", "T18", band="80", mode="LSB", t="2027-01-02 08:12:00")
    q.exch_s = "T99"
    line = cabrillo_qso_line(c, q, "DL1ABC")
    assert line.split()[1:5] == [str(int(DEFAULT_FREQ["80"] // 1000)), "PH", "2027-01-02", "0812"]
    assert "59 T99" in " ".join(line.split()) and "59 T18" in " ".join(line.split())
    assert c.cabrillo_name == "Schwaben Contest"


# ------------------------------------------------------------ Schwaben UKW
def test_schwaben_ukw(cty):
    c, s = make("schwaben-ukw", cty, dok="T01", grid="JN58AA")
    assert c.sent_exchange(1) == "T01 JN58AA"
    c2, _ = make("schwaben-ukw", cty, grid="JN58AA")
    assert c2.sent_exchange(5) == "005 JN58AA" and c2.uses_serial  # ohne DOK: Nummer
    assert c.validate_exchange("012 JN58XX") is None
    assert c.validate_exchange("T02") and c.validate_exchange("JN58XX")
    t = "2027-01-02 12:30:00"
    assert s.evaluate(qso(1, "DL0T", "T02 JN58XX", band="2", mode="USB", t=t),
                      commit=True).points == 10
    assert s.evaluate(qso(2, "DL2AB", "012 JO40AA", band="2", mode="USB", t=t),
                      commit=True).points == 1
    # 2 m FM ist eine eigene Betriebsart (13:30–14:30) – kein Dupe zu SSB
    fm = qso(3, "DL0T", "T02 JN58XX", band="2", mode="FM", t="2027-01-02 13:40:00")
    assert c.window_problem(fm) is None
    assert not s.evaluate(fm, commit=True).dupe
    assert s.evaluate(qso(4, "DL0T", "T02 JN58XX", band="2", mode="FM",
                          t="2027-01-02 13:50:00")).dupe
    late = qso(5, "DK5XY", "T05 JN58BB", band="2", mode="FM", t="2027-01-02 12:30:00")
    assert "13:30" in (c.window_problem(late) or "")              # FM erst ab 13:30
    assert c.window_problem(qso(6, "DK5XY", "T05 JN58BB", band="70cm", mode="FM",
                                t="2027-01-02 15:45:00")) is None
    assert s.score == 10 + 1 + 10
    q = qso(7, "DL0T", "T02 JN58XX", band="2", mode="USB", t=t)
    q.exch_s = "T01 JN58AA"
    assert "59 T01 JN58AA" in " ".join(cabrillo_qso_line(c, q, "DL1ABC").split())
