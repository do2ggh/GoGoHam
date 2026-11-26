"""0.10.2: Multi-OP-Kategorien – Bandwechsel-Regeln, Sendernummer, Nummern je Band,
Operator-Liste, Regel-Format 12."""

import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from conftest import builtin_newer_than
from gogoham import logcheck, multiop, rulefiles
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.cty import CtyDB
from gogoham.export import cabrillo

HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def q(t, band, tx="0", call="DL1ABC", mode="CW", nr="001", i=None):
    return Qso(id=i, time=f"2026-11-28 {t}:00", call=call, band=band, mode=mode,
               freq=14020000, rst_s="599", rst_r="599", exch_s=nr, exch_r="14", tx=tx)


def at(t):
    return datetime.strptime(f"2026-11-28 {t}:00", "%Y-%m-%d %H:%M:%S")


def test_category_from_meta_and_rules():
    assert multiop.category({"cat_operator": "SINGLE-OP"}) is None
    assert multiop.category({"cat_operator": "MULTI-OP", "cat_transmitter": "ONE"}) == "MS"
    assert multiop.category({"cat_operator": "MULTI-OP", "cat_transmitter": "TWO"}) == "M2"
    assert multiop.category({"cat_operator": "MULTI-OP", "cat_transmitter": "UNLIMITED"}) == "MM"
    ww = CONTESTS["cqww-cw"]
    assert multiop.rules(ww, "MS")["dwell"]["minutes"] == 10
    assert multiop.needs_tx_id(ww, "MS") and multiop.needs_tx_id(ww, "M2")
    assert not multiop.needs_tx_id(ww, "MM")
    assert multiop.serial_mode(CONTESTS["wpx-cw"], "M2") == "band"
    assert multiop.serial_mode(CONTESTS["wpx-cw"], "MS") == "station"
    assert [v for v, _t in multiop.tx_roles(ww, "MS")] == ["0", "1"]
    assert [v for v, _t in multiop.tx_roles(CONTESTS["wpx-cw"], "MS")] == ["0"]
    assert multiop.rules(CONTESTS["iaru-hf"], "MS")["dwell"]["mode"] is True
    assert multiop.rules(CONTESTS["arrl-dx-cw"], "M2")["per_hour"] == 6


def test_ten_minute_rule_per_transmitter():
    ww = CONTESTS["cqww-cw"]
    log = [q("10:00", "20"), q("10:05", "20"), q("10:02", "40", tx="1")]
    notes = multiop.band_notes(ww, "MS", log, "15", "CW", "0", at("10:08"))
    assert notes and "10-Minuten-Regel" in notes[0] and "10:10" in notes[0]
    assert multiop.band_notes(ww, "MS", log, "15", "CW", "0", at("10:11")) == []
    assert multiop.band_notes(ww, "MS", log, "20", "CW", "0", at("10:08")) == []
    # Multi-Signal hat seine eigene Regel – und darf nicht aufs Run-Band
    n1 = multiop.band_notes(ww, "MS", log, "20", "CW", "1", at("10:15"), is_new_mult=False)
    assert any("Run-Senders" in n for n in n1) and any("neue Multis" in n for n in n1)
    assert multiop.band_notes(ww, "MS", log, "15", "CW", "1", at("10:15"),
                              is_new_mult=True) == []


def test_iaru_dwell_includes_mode():
    ia = CONTESTS["iaru-hf"]
    log = [q("10:00", "20", mode="CW")]
    assert multiop.band_notes(ia, "MS", log, "20", "USB", "0", at("10:03"))
    assert multiop.band_notes(CONTESTS["cqww-cw"], "MS", log, "20", "USB", "0",
                              at("10:03")) == []


def test_band_changes_per_hour():
    wpx = CONTESTS["wpx-cw"]
    bands = ["20", "40"] * 6
    log = [q(f"10:{i * 4:02d}", b, nr=str(i + 1)) for i, b in enumerate(bands)]   # 11 Wechsel
    # bis 10:40 sind es 10 Wechsel (Grenze im Multi-One: 10)
    upto = log[:11]
    n = multiop.band_notes(wpx, "MS", upto, "40" if upto[-1].band == "20" else "20", "CW", "0",
                           at("10:45"))
    assert n and "darf nur 10" in n[0] and "11:00" in n[0]
    assert multiop.band_notes(wpx, "MS", upto, upto[-1].band, "CW", "0", at("10:45")) == []
    # neue Stunde: wieder frei
    assert multiop.band_notes(wpx, "MS", upto, "15", "CW", "0", at("11:01")) == []
    # Log-Prüfung findet den Verstoß im Log
    found = multiop.check_log(wpx, "MS", log)
    assert len(found) == 1 and "darf nur 10" in found[0]


def test_cabrillo_transmitter_column_and_serial_per_band(cty):
    c = CONTESTS["cqww-cw"](cty, Station(call="DL0ABC", cq_zone=14))
    s = Scorer(c)
    log = [q("10:00", "20", tx="0", i=1), q("10:01", "40", tx="1", call="W1AW", i=2)]
    s.rebuild(log)
    ms = {"mycall": "DL0ABC", "cat_operator": "MULTI-OP", "cat_transmitter": "ONE"}
    lines = [ln for ln in cabrillo(c, ms, log, s).splitlines() if ln.startswith("QSO:")]
    assert [ln.split()[-1] for ln in lines] == ["0", "1"]
    single = {"mycall": "DL0ABC"}
    lines = [ln for ln in cabrillo(c, single, log, s).splitlines() if ln.startswith("QSO:")]
    assert [ln.split()[-1] for ln in lines] == ["0", "0"]
    # WPX Multi-Two: Nummern je Band – Lücken werden je Band geprüft
    w = CONTESTS["wpx-cw"](cty, Station(call="DL0ABC"))
    ws = Scorer(w)
    wl = [q("10:00", "20", nr="1", i=1), q("10:01", "40", nr="1", call="W1AW", i=2),
          q("10:02", "40", nr="3", call="K1ZZ", i=3)]
    ws.rebuild(wl)
    meta = {"cat_operator": "MULTI-OP", "cat_transmitter": "TWO"}
    texts = [f.text for f in logcheck.check(w, wl, ws, meta=meta)]
    assert any("40 m: 2" in t for t in texts) and not any("20 m" in t for t in texts)


def test_operator_list_in_logcheck(cty):
    c = CONTESTS["cqww-cw"](cty, Station(call="DL0ABC", cq_zone=14))
    s = Scorer(c)
    log = [q("10:00", "20", i=1), q("10:01", "40", call="W1AW", i=2)]
    log[0].operator, log[1].operator = "DO2GGH", "DL1AAA"
    s.rebuild(log)
    texts = [f.text for f in logcheck.check(c, log, s, meta={})]
    assert any("Operatoren im Log (2): DO2GGH, DL1AAA" in t for t in texts)


def test_format_12_and_older_version_skips(tmp_path, monkeypatch):
    assert rulefiles.FORMAT_VERSION >= 12
    for cid in ("cqww-cw", "cqww-ssb", "wpx-cw", "wpx-ssb", "arrl-dx-cw", "arrl-dx-ssb",
                "iaru-hf"):
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert d["format"] == 12 and d["multi"] and rulefiles.validate(d) == []
    bad = json.loads((rulefiles.BUILTIN_DIR / "cqww-cw.json").read_text(encoding="utf-8"))
    bad["multi"] = {"MX": {}, "MS": {"per_hour": 0, "foo": 1}}
    errs = rulefiles.validate(bad)
    assert len(errs) == 3
    from gogoham import rulesupdate
    src = tmp_path / "gh"
    src.mkdir()
    for p in rulefiles.BUILTIN_DIR.glob("*.json"):
        shutil.copy(p, src / p.name)
    (src / "index.json").write_text(json.dumps(rulesupdate.make_index(src)), encoding="utf-8")
    monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 11)
    monkeypatch.setattr(rulefiles, "BUILTIN_DIR", tmp_path / "leer")
    (tmp_path / "leer").mkdir()
    res = rulesupdate.check_and_download(src.as_uri() + "/", tmp_path / "data")
    want, _rest = builtin_newer_than(11)
    # 7 Multi-OP-Dateien (Format 12) + 4 RTTY-Contests (Format 12/13, 0.10.7)
    assert sorted(res.skipped) == want and "CQ WW DX CW" in want and len(want) == 7 + 4 + 10 + 3 + 3 - 2 + 2 + 15 + 14 + 4 + 2 + 11 + 7 + 5   # + REF, PACC (16), ARRL 160, Stew Perry (17), 15 neue (18), 14 neue (19)
