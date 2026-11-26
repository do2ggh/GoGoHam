"""0.8.7: Länder-Contests (OK/OM DX, HA DX, UBA DX, PACC, SP DX), IOTA-Angaben, nur ein
GoGoHam gleichzeitig."""

import json
import shutil
from pathlib import Path

import pytest

from conftest import builtin_newer_than
from gogoham import rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.contests.rulebased import normalize_district, station_fields
from gogoham.cty import CtyDB
from gogoham.export import cabrillo, cabrillo_qso_line

HERE = Path(__file__).parent
NEW = ("okom-cw", "okom-ssb", "hadx", "uba-cw", "uba-ssb", "pacc", "spdx")


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def run(cty, cid, call, qsos, **st):
    c = CONTESTS[cid](cty, Station(call=call, **st))
    s = Scorer(c)
    evs = []
    for i, (cl, band, mode, ex) in enumerate(qsos, 1):
        q = Qso(id=i, time="2027-01-16 12:00:00", call=cl, band=band, mode=mode,
                rst_s="59", rst_r="59", exch_s=c.sent_exchange(i), exch_r=ex)
        evs.append(s.evaluate(q, commit=True))
    return c, s, evs


# ------------------------------------------------------------ Regel-Dateien
def test_files_format_7_and_valid():
    assert rulefiles.FORMAT_VERSION >= 7
    for cid in NEW:
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert d["format"] == (16 if cid == "pacc" else 7) and rulefiles.validate(d) == [], cid
        assert station_fields(CONTESTS[cid]) == {"district"}
    names = {cid: CONTESTS[cid].cabrillo_name for cid in NEW}
    assert names == {"okom-cw": "OK-OM-DX", "okom-ssb": "OK-OM-DX", "hadx": "HA-DX",
                     "uba-cw": "UBA-DX-CW", "uba-ssb": "UBA-DX-SSB", "pacc": "PACC",
                     "spdx": "SPDX"}


def test_086_skips_format_7(tmp_path, monkeypatch):
    """Die installierte 0.8.6 (Format 6) überspringt die neuen Dateien sauber."""
    from gogoham import rulesupdate
    src = tmp_path / "gh"
    src.mkdir()
    for p in rulefiles.BUILTIN_DIR.glob("*.json"):
        shutil.copy(p, src / p.name)
    (src / "index.json").write_text(json.dumps(rulesupdate.make_index(src)), encoding="utf-8")
    monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 6)
    monkeypatch.setattr(rulefiles, "BUILTIN_DIR", tmp_path / "leer")
    (tmp_path / "leer").mkdir()
    res = rulesupdate.check_and_download(src.as_uri() + "/", tmp_path / "data")
    want, rest = builtin_newer_than(6)
    assert len(want) >= 7 and sorted(res.skipped) == want
    assert not res.errors and len(res.new) == rest


def test_bad_host_blocks_are_reported():
    d = json.loads((rulefiles.BUILTIN_DIR / "hadx.json").read_text(encoding="utf-8"))
    del d["host"]
    assert "host" in " ".join(rulefiles.validate(d))
    d = json.loads((rulefiles.BUILTIN_DIR / "uba-ssb.json").read_text(encoding="utf-8"))
    d["host"]["pattern"] = "[A-Z"
    d["host"]["codes"] = "ACC"
    d["blocked_countries"] = "UA"
    d["points"]["dx"]["group"] = {"points": 3}
    errs = " ".join(rulefiles.validate(d))
    assert "pattern" in errs and "codes" in errs and "blocked_countries" in errs
    assert "group" in errs


def test_schedules():
    def start(cid, y):
        return str(schedule.period(CONTESTS[cid].schedule, y)[0])
    assert start("okom-cw", 2026) == "2026-11-14 12:00:00"
    assert start("okom-ssb", 2027) == "2027-04-10 12:00:00"
    assert start("hadx", 2026) == "2026-01-17 12:00:00"
    assert start("uba-ssb", 2027) == "2027-01-30 13:00:00"
    assert start("uba-cw", 2027) == "2027-02-27 13:00:00"
    assert start("pacc", 2027) == "2027-02-13 12:00:00"
    assert start("spdx", 2026) == "2026-04-04 15:00:00"


def test_district_codes():
    host = CONTESTS["hadx"].host
    assert normalize_district("bp", host) == "BP" and normalize_district("XX", host) == ""
    assert normalize_district("apa", CONTESTS["okom-cw"].host) == "APA"
    assert normalize_district("APR", CONTESTS["okom-cw"].host) == ""   # 0.10.28: offizielle Liste
    assert normalize_district("AP", CONTESTS["okom-cw"].host) == ""


# ------------------------------------------------------------ Wertung
def test_hadx(cty):
    c, s, evs = run(cty, "hadx", "DO2GGH", [
        ("HA5X", "20", "USB", "BP"),       # Ungarn: 10, Komitat
        ("HA5X", "20", "CW", "BP"),        # anderer Mode zählt, Multi nur je Band
        ("OE1A", "20", "USB", "5"),        # gleicher Kontinent: 2
        ("K1A", "20", "USB", "4"),         # anderer Kontinent: 5
    ])
    assert [e.points for e in evs] == [10, 10, 2, 5]
    assert evs[0].new_mults == [("subdiv", "BP")] and evs[1].new_mults == []
    assert c.validate_exchange("XX", cty.lookup("HA5X"))
    c, s, evs = run(cty, "hadx", "HA5X", [("HA1Y", "20", "USB", "GY")], district="bp")
    assert evs[0].points == 10 and c.sent_exchange(1) == "BP"
    assert evs[0].new_mults == [("subdiv", "GY")]      # HA zählt nicht als Land


def test_okom(cty):
    _c, _s, evs = run(cty, "okom-cw", "DO2GGH", [
        ("OK1A", "20", "CW", "APA"), ("OM3B", "20", "CW", "BAA"),
        ("DL1A", "20", "CW", "5"), ("K1A", "20", "CW", "4")])
    assert [e.points for e in evs] == [10, 10, 1, 5]
    assert evs[0].new_mults == [("subdiv", "APA"), ("country", "OK")]
    _c, _s, evs = run(cty, "okom-cw", "OK1A", [
        ("OK2B", "20", "CW", "BRA"), ("OM3B", "20", "CW", "BAA"), ("DL1A", "20", "CW", "5")],
        district="APA")
    assert [e.points for e in evs] == [2, 3, 3]


def test_uba_foreign_station(cty):
    c, s, evs = run(cty, "uba-ssb", "DO2GGH", [
        ("ON4A", "20", "USB", "12 ACC"),   # Belgien: 10, Sektion + Präfix
        ("OO5B", "20", "USB", "3 XXX"),    # Nichtmitglied: kein Sektions-Multi
        ("DL1A", "20", "USB", "5"),        # EU-Land: 3, Land-Multi
        ("K1A", "20", "USB", "4"),         # sonst: 1, kein Multi
        ("UA3AAA", "20", "USB", "5"),      # Russland zählt nicht
    ])
    assert [e.points for e in evs] == [10, 10, 3, 1, 0]
    assert evs[0].new_mults == [("subdiv", "ACC"), ("prefix", "ON4")]
    assert evs[1].new_mults == [("prefix", "OO5")]
    assert evs[2].new_mults == [("country", "DL")] and evs[3].new_mults == []
    assert not evs[4].valid
    assert c.validate_exchange("13 FOO", cty.lookup("ON4A"))
    assert c.validate_exchange("13", cty.lookup("DL1A")) is None


def test_uba_belgian_station(cty):
    c, s, evs = run(cty, "uba-ssb", "ON4A", [
        ("ON5B", "20", "USB", "3 ACC"),    # Belgien: 1
        ("DL1A", "20", "USB", "5"),        # EU: 2
        ("K1A", "20", "USB", "4"),         # sonst: 3
        ("EW1A", "20", "USB", "1"),        # Belarus zählt nicht
    ], district="acc")
    assert [e.points for e in evs] == [1, 2, 3, 0]
    assert c.sent_exchange(7) == "007 ACC"
    q = Qso(id=1, time="2027-01-30 13:00:00", call="ON5B", band="20", mode="USB", freq=14200000,
            rst_s="59", rst_r="59", exch_s="001 ACC", exch_r="3 ACC")
    assert cabrillo_qso_line(c, q, "ON4A").endswith("59    3 ACC 0")
    c2 = CONTESTS["uba-ssb"](cty, Station(call="ON6X"))
    assert c2.sent_exchange(1) == "001 XXX"           # ohne Sektion: Nichtmitglied


def test_pacc(cty):
    _c, s, evs = run(cty, "pacc", "DO2GGH", [
        ("PA1A", "20", "USB", "NH"), ("PA1A", "20", "CW", "NH"), ("DL1A", "20", "USB", "5")])
    assert [e.points for e in evs] == [1, 1, 0]
    assert evs[1].new_mults == [("subdiv", "NH")]     # Provinz je Band und Mode
    assert not evs[2].valid
    _c, s, evs = run(cty, "pacc", "PA1A", [
        ("PA2B", "20", "USB", "ZH"), ("DL1A", "20", "USB", "5"), ("K1ABC", "20", "USB", "7"),
        ("W3XX", "20", "USB", "8"), ("UA9AA", "20", "USB", "9")], district="NH")
    assert [e.points for e in evs] == [1, 1, 1, 1, 1]
    assert [e.new_mults for e in evs] == [[("country", "PA")], [("country", "DL")],
                                          [("area", "W1")], [("area", "W3")], [("area", "UA9")]]


def test_spdx(cty):
    _c, s, evs = run(cty, "spdx", "DO2GGH", [
        ("SP5A", "20", "USB", "R"), ("SP9B", "20", "CW", "K"), ("DL1A", "20", "USB", "5")])
    assert [e.points for e in evs] == [3, 3, 0]
    assert s.score == 6 * 2
    _c, s, evs = run(cty, "spdx", "SP5A", [
        ("SP9B", "20", "USB", "K"), ("DL1A", "20", "USB", "5"), ("K1A", "20", "USB", "4")],
        district="R")
    assert [e.points for e in evs] == [0, 1, 3]
    assert evs[0].new_mults == []                      # SP zählt nicht als Land


# ------------------------------------------------------------ IOTA-Angaben im Cabrillo
def test_iota_island_name_and_dxpedition(cty):
    c = CONTESTS["iota"](cty, Station(call="G3B", iota="EU-005"))
    s = Scorer(c)
    out = cabrillo(c, {"mycall": "G3B", "my_iota": "EU-005", "my_iota_dxped": "1",
                       "my_iota_island": "Great Britain"}, [], s)
    assert "CATEGORY-LOCATION: DXPEDITION" in out and "IOTA-ISLAND-NAME: Great Britain" in out
    out = cabrillo(c, {"mycall": "G3B", "my_iota": "EU-005"}, [], s)
    assert "CATEGORY-LOCATION: NON-DXPEDITION" in out and "IOTA-ISLAND-NAME" not in out
    out = cabrillo(c, {"mycall": "DO2GGH", "my_iota_island": "Wo auch immer"}, [], s)
    assert "CATEGORY-LOCATION: WORLD" in out and "IOTA-ISLAND-NAME" not in out


# ------------------------------------------------------------ nur ein GoGoHam
def test_single_instance(tmp_path, monkeypatch):
    import subprocess
    import sys
    import textwrap
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    script = tmp_path / "inst.py"
    script.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(HERE.parent)!r})
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QWidget
        app = QApplication([])
        from gogoham.gui.single import SingleInstance
        s = SingleInstance()
        if not s.lock():
            print("zweiter", flush=True)
            sys.exit(0)
        w = QWidget()
        s.bring_to_front = lambda: print("nach vorne", flush=True)
        s.listen(w)
        print("erster", flush=True)
        QTimer.singleShot(int(sys.argv[1]), app.quit)
        app.exec()
        s.release()
    """), encoding="utf-8")
    first = subprocess.Popen([sys.executable, str(script), "4000"], stdout=subprocess.PIPE,
                             text=True)
    assert first.stdout.readline().strip() == "erster"
    second = subprocess.run([sys.executable, str(script), "100"], capture_output=True,
                            text=True, timeout=30)
    assert second.stdout.strip() == "zweiter"
    first.terminate()
    out = first.communicate(timeout=30)[0]
    assert "nach vorne" in out
    # nach einem Absturz (Sperrdatei bleibt liegen) startet GoGoHam normal
    crashed = subprocess.Popen([sys.executable, str(script), "30000"], stdout=subprocess.PIPE,
                               text=True)
    assert crashed.stdout.readline().strip() == "erster"
    crashed.kill()
    crashed.wait(timeout=30)
    again = subprocess.run([sys.executable, str(script), "100"], capture_output=True,
                           text=True, timeout=30)
    assert again.stdout.strip() == "erster"
