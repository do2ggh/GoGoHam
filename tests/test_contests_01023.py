"""0.10.23: AGCW QRP-Contest, AGCW QRP/QRP-Party, Frankencontest (Klassen A–L) und
Bayerischer Bergtag (4 Termine). Neu (Format 14): Leistungsklassen im Austausch, Punkte nach
Klassen, DOK + Locator, Kilometer ohne +1, eigener DOK = 0 Punkte, DOK-Auswahl als Multi,
Wertung je Band und „ohne Multi zählen die Punkte“."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from gogoham import rulefiles, schedule
from gogoham.bands import DEFAULT_FREQ
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.contests.rulebased import split_dok_grid, split_serial_class, station_fields
from gogoham.cty import CtyDB
from gogoham.export import cabrillo_qso_line

HERE = Path(__file__).parent
FMT14 = ("agcw-qrp", "agcw-qrp-party") + tuple(f"franken-{k}" for k in "abcdefkl")
BBT = ("bbt-winter-1", "bbt-winter-2", "bbt-summer-1", "bbt-summer-2")


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def make(cid, cty, call="DL1ABC", **st):
    c = CONTESTS[cid](cty, Station(call=call, lookup=cty.lookup(call), **st))
    return c, Scorer(c)


def qso(i, call, ex, band="40", mode="CW", t="2027-03-13 14:10:00", ex_s=""):
    return Qso(id=i, time=t, call=call, band=band, mode=mode, freq=DEFAULT_FREQ[band],
               rst_s="599", rst_r="599", exch_r=ex, exch_s=ex_s)


def first(cid, n=1):
    return [s for s, _ in schedule.upcoming(CONTESTS[cid].rules["schedule"],
                                            datetime(2026, 11, 14), n)]


# ------------------------------------------------------------ Dateien und Termine
def test_files_need_format_14(monkeypatch):
    for cid in FMT14:
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        want = 16 if cid.startswith("franken-") else 14     # Franken: „dok_only_dl“ (0.10.28.2)
        assert d["format"] == want and rulefiles.validate(d) == []
        monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 13)
        assert "neuere GoGoHam-Version" in rulefiles.validate(d)[0]
        monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 16)
    for cid in BBT:                                # BBT läuft schon mit älteren Versionen
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert d["format"] == 10 and rulefiles.validate(d) == []


def test_dates_2027():
    assert first("agcw-qrp") == [datetime(2027, 3, 13, 14)]          # 2. Samstag im März
    assert first("agcw-qrp-party", 2) == [datetime(2027, 5, 1, 13), datetime(2028, 5, 1, 13)]
    # Frankencontest: 2. volles Wochenende im Mai (2021–2026 so belegt)
    assert first("franken-e") == [datetime(2027, 5, 8, 15)]
    assert first("franken-k") == [datetime(2027, 5, 8, 16)]
    assert first("franken-l") == [datetime(2027, 5, 8, 18)]
    assert first("franken-a") == [datetime(2027, 5, 9, 7)]
    got = [s for s, _ in schedule.upcoming(CONTESTS["franken-b"].rules["schedule"],
                                           datetime(2025, 1, 1), 2)]
    assert got == [datetime(2025, 5, 11, 7), datetime(2026, 5, 10, 7)]   # wie ausgeschrieben
    # BBT – Terminliste bergtag.de 2027
    assert first("bbt-winter-1") == [datetime(2027, 2, 6, 9)]
    assert first("bbt-winter-2") == [datetime(2027, 2, 27, 9)]
    assert first("bbt-summer-1") == [datetime(2027, 5, 29, 7)]
    assert first("bbt-summer-2") == [datetime(2027, 8, 7, 7)]


def test_validate_new_blocks():
    base = json.loads((rulefiles.BUILTIN_DIR / "agcw-qrp.json").read_text(encoding="utf-8"))
    bad = dict(base, classes=[])
    assert any("classes" in e for e in rulefiles.validate(bad))
    bad = dict(base, own_classes=["XYZ"])
    assert any("own_classes" in e for e in rulefiles.validate(bad))
    bad = dict(base, points={"type": "class", "table": {}})
    assert any("table" in e for e in rulefiles.validate(bad))
    fr = json.loads((rulefiles.BUILTIN_DIR / "franken-k.json").read_text(encoding="utf-8"))
    bad = dict(fr, points={"type": "km", "add": -1})
    assert any("add" in e for e in rulefiles.validate(bad))
    bad = dict(fr, multipliers=[dict(fr["multipliers"][0], dok_pattern="B(")])
    assert any("dok_pattern" in e for e in rulefiles.validate(bad))
    bad = dict(fr, same_dok_zero="ja")
    assert any("same_dok_zero" in e for e in rulefiles.validate(bad))


# ------------------------------------------------------------ AGCW QRP-Contest
def test_split_serial_class():
    assert split_serial_class("001 QRP 1537") == ("001", "QRP", "1537")
    assert split_serial_class("027 mp nm") == ("027", "MP", "NM")
    assert split_serial_class("001/A") == ("001", "A", "")
    assert split_serial_class("001A") == ("001", "A", "")
    assert split_serial_class("QRP") == ("", "", "")


def test_agcw_qrp_points_and_members(cty):
    c, s = make("agcw-qrp", cty, member="2583", pclass="QRP")
    assert c.sent_exchange(1) == "001 QRP 2583"
    assert station_fields(type(c)) >= {"member", "pclass"}
    assert c.validate_exchange("012 QRP") and "NM" in c.validate_exchange("012 QRP")
    assert "Klasse" in c.validate_exchange("012 XYZ 12")
    assert c.validate_exchange("012 VLP 1537") is None
    s.evaluate(qso(1, "DK5XY", "012 QRP 1537"), commit=True)         # QRP–QRP 3, Mitglied
    s.evaluate(qso(2, "OE1ABC", "005 QRO NM"), commit=True)          # QRP–QRO 2, kein Multi
    s.evaluate(qso(3, "OK1AB", "009 MP 811"), commit=True)           # QRP–MP 2, Mitglied
    s.evaluate(qso(4, "DK5XY", "020 QRP 1537", band="80"), commit=True)  # anderes Band: neu
    ev = s.evaluate(qso(5, "DK5XY", "021 QRP 1537"))                 # Dupe auf 40 m
    assert ev.dupe
    assert s.total_points == 3 + 2 + 2 + 3 and s.mult_count() == 3
    assert s.score == 10 * 3
    # QRO-Station: QRO–QRO zählt 0
    c2, s2 = make("agcw-qrp", cty, pclass="QRO")
    assert c2.sent_exchange(7) == "007 QRO NM"
    assert s2.evaluate(qso(1, "OE1ABC", "005 QRO NM")).points == 0
    assert s2.evaluate(qso(1, "OE1ABC", "005 VLP NM")).points == 2


def test_agcw_qrp_cabrillo(cty):
    c, _ = make("agcw-qrp", cty, member="2583", pclass="QRP")
    q = qso(1, "DK5XY", "12 qrp 1537", ex_s="001 QRP 2583")
    line = cabrillo_qso_line(c, q, "DL1ABC")
    assert "599 001 QRP 2583" in line and "599 12 QRP 1537" in line


# ------------------------------------------------------------ QRP/QRP-Party
def test_qrp_party_band_sum(cty):
    c, s = make("agcw-qrp-party", cty, pclass="A")
    assert c.sent_exchange(1) == "001/A"
    assert c.own_classes == ("A", "B")
    s.evaluate(qso(1, "DK5XY", "003 A"), commit=True)                # 2 Punkte, DL
    s.evaluate(qso(2, "OE1ABC", "010/B"), commit=True)               # 1 Punkt, OE
    ev = s.evaluate(qso(3, "OK1AB", "004 QRO"), commit=True)         # QRO: 0, kein Multi
    assert ev.points == 0 and not ev.mults
    s.evaluate(qso(4, "OK1AB", "005 A", band="80"), commit=True)     # 80 m: 2 Punkte, OK
    # 40 m: 3 Punkte × 2 Länder = 6; 80 m: 2 × 1 = 2 → 8
    assert s.score == 8
    ev = s.evaluate(qso(5, "OE2XX", "007 A", band="80"))            # 80 m: +2 Punkte, +1 Land
    assert ev.gain == (2 + 2) * 2 - 2
    q = qso(1, "DK5XY", "3 a", ex_s="001/A")
    assert "599 3/A" in cabrillo_qso_line(c, q, "DL1ABC")
    # Klasse B darf man sein, QRO nicht
    assert make("agcw-qrp-party", cty, pclass="QRO")[0].own_class() == ""


# ------------------------------------------------------------ Frankencontest
def test_split_dok_grid():
    assert split_dok_grid("B26 JN59NO") == ("B26", "JN59NO")
    assert split_dok_grid("nm jn59no") == ("NM", "JN59NO")
    assert split_dok_grid("B26") == ("B26", "")


def test_franken_hf(cty):
    c, s = make("franken-a", cty, dok="B37")
    assert c.sent_exchange(1) == "B37" and "dok" in station_fields(type(c))
    s.evaluate(qso(1, "DK5XY", "B26", t="2027-05-09 07:10:00"), commit=True)   # Multi
    s.evaluate(qso(2, "DL2AB", "C01", t="2027-05-09 07:11:00"), commit=True)   # kein Franke
    s.evaluate(qso(3, "DL3CD", "DVB", t="2027-05-09 07:12:00"), commit=True)   # Sonder-DOK
    s.evaluate(qso(4, "DL4EF", "Z51", t="2027-05-09 07:13:00"), commit=True)   # fränk. Z-DOK
    s.evaluate(qso(5, "DL5GH", "Z12", t="2027-05-09 07:14:00"), commit=True)   # anderer Z-DOK
    ev = s.evaluate(qso(6, "DL6IJ", "B37", t="2027-05-09 07:15:00"), commit=True)  # eigener
    assert ev.points == 0 and ev.new_mults == [("dok", "B37")]
    s.evaluate(qso(7, "OE1ABC", "NM", t="2027-05-09 07:16:00"), commit=True)
    s.evaluate(qso(8, "DK5XY", "B26", band="80", t="2027-05-09 07:20:00"), commit=True)
    assert s.total_points == 7                     # 8 QSOs, eigener DOK zählt 0
    assert s.mult_count() == 5                     # B26, DVB, Z51, B37 (40 m) + B26 (80 m)
    assert s.score == 7 * 5
    assert s.evaluate(qso(9, "DK5XY", "B26", t="2027-05-09 07:30:00")).dupe
    assert c.rcvd_dok(qso(1, "DL1X", "b45"), cty.lookup("DL1X")) == "B45"
    assert not s.evaluate(qso(10, "DL7KL", "B45", band="80")).mults   # B45 gehört nicht dazu


def test_franken_no_mult_counts_points(cty):
    c, s = make("franken-b", cty, dok="B37")
    s.evaluate(qso(1, "DL2AB", "C01", mode="USB"), commit=True)
    s.evaluate(qso(2, "OE1ABC", "NM", mode="USB"), commit=True)
    assert s.mult_count() == 0 and s.score == 2    # ohne Multi: reine QSO-Punkte
    ev = s.evaluate(qso(3, "DK5XY", "B26", mode="USB"))
    assert ev.gain == 3 * 1 - 2


def test_franken_ukw_km(cty):
    c, s = make("franken-k", cty, dok="B37", grid="JN59ME")
    assert c.sent_exchange(1) == "B37 JN59ME"
    assert c.validate_exchange("B26") and c.validate_exchange("B26 JN59NO") is None
    assert c.validate_exchange("NM JN59NO") is None
    q = qso(1, "DK5XY", "B26 JN59NO", band="2", mode="USB", t="2027-05-08 16:10:00")
    km = c.qso_km(q)
    ev = s.evaluate(q, commit=True)
    assert km and ev.points == int(km)             # jeder Kilometer ein Punkt, ohne +1
    assert ev.new_mults == [("dok", "B26")]
    q2 = qso(2, "DL6IJ", "B37 JO50AA", band="2", mode="CW", t="2027-05-08 16:20:00")
    assert s.evaluate(q2).points == 0              # eigener DOK
    assert s.evaluate(qso(3, "DK5XY", "B26 JN59NO", band="2", mode="CW")).dupe  # je Band


def test_franken_bands_and_modes(cty):
    assert CONTESTS["franken-c"].bands == ["80"] and CONTESTS["franken-c"].modes == {"CW"}
    assert CONTESTS["franken-f"].bands == ["10"] and CONTESTS["franken-f"].modes == {"PH"}
    assert CONTESTS["franken-l"].bands == ["70cm"]
    c, s = make("franken-a", cty, dok="B37")
    ev = s.evaluate(qso(1, "DK5XY", "B26", band="20"))
    assert not ev.valid                            # 20 m gehört nicht zur Klasse A


# ------------------------------------------------------------ Bergtag
def test_bbt_km_and_windows(cty):
    c, s = make("bbt-winter-1", cty, grid="JN57MO")
    assert c.sent_exchange(4) == "004 JN57MO" and c.log_format == "edi"
    q = qso(1, "DL5XY", "007 JN58TD", band="2", mode="USB", t="2027-02-07 11:15:00")
    ev = s.evaluate(q, commit=True)
    assert ev.points == int(c.qso_km(q)) + 1       # IARU: Kilometer + 1
    assert c.window_problem(q) is None
    late = qso(2, "DL6AB", "003 JN58TD", band="2", mode="USB", t="2027-02-07 13:05:00")
    assert c.window_problem(late)                  # 2 m nur 11:00–13:00 UTC
    assert not c.require_portable                  # BBT: /p nicht nötig (Regel 7.4)
    assert CONTESTS["bbt-winter-2"].bands[0] == "3cm"
