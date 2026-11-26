"""Tests für den Regel-Baukasten (0.6.1): Laden, Prüfen, Vorrang, Export-Vorgabe."""

import copy
import json
from pathlib import Path

import pytest

from gogoham import rulefiles
from gogoham.contests import CONTESTS, Qso, Scorer, Station, build_contests
from gogoham.contests.rulebased import make_contest_class
from gogoham.cty import CtyDB

HERE = Path(__file__).parent
BUILTIN = rulefiles.BUILTIN_DIR


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def builtin(cid):
    return json.loads((BUILTIN / f"{cid}.json").read_text(encoding="utf-8"))


UKW_DARC = {"darc-vhf", "darc-ukw-spring", "darc-microwave", "marconi-vhf", "darc-ukw-fd-winter", "darc-ukw-fd-summer",
            "bbt-winter-1", "bbt-winter-2", "bbt-summer-1", "bbt-summer-2",   # BBT: EDI
            "alpe-adria-vhf", "alpe-adria-uhf"}


def test_all_builtin_files_valid():
    files = sorted(p.stem for p in BUILTIN.glob("*.json"))
    assert files == ["7qp", "9adx", "aa-cw", "aa-ssb", "af-all-mode", "agcw-hny",
                    "agcw-htp-40", "agcw-htp-80", "agcw-qrp", "agcw-qrp-party", "agcw-sta",
                    "alpe-adria-uhf", "alpe-adria-vhf", "aoec-160", "arrl-10", "arrl-160",
                    "arrl-digi", "arrl-dx-cw", "arrl-dx-ssb", "arrl-rtty", "arrl-ss-cw",
                    "arrl-ss-ssb", "arrl-vhf-jun", "arrl-vhf-sep", "baltic", "bartg-rtty",
                    "bbt-summer-1", "bbt-summer-2", "bbt-winter-1", "bbt-winter-2",
                    "canada-day", "cq160-cw", "cq160-ssb", "cqww-cw", "cqww-rtty", "cqww-ssb",
                    "cqww-vhf", "cqww-vhf-digi", "darc-10m", "darc-ac", "darc-cwa",
                    "darc-easter", "darc-fd-cw", "darc-fd-ssb", "darc-ft4", "darc-microwave",
                    "darc-ukw-fd-summer", "darc-ukw-fd-winter", "darc-ukw-spring", "darc-vhf",
                    "darc-xmas", "dig-cw", "dig-ssb", "dtc", "ea-majestad-cw",
                    "ea-majestad-ssb", "ea-psk63", "ea-rtty", "euhfc", "franken-a",
                    "franken-b", "franken-c", "franken-d", "franken-e", "franken-f",
                    "franken-k", "franken-l", "hadx", "hsc", "iaru-50", "iaru-70", "iaru-hf",
                    "iaru-uhf", "iaru-vhf", "inqp", "iota", "jarl-ww-rtty", "jidx-cw",
                    "jidx-ph", "lzdx", "makrothen", "marconi-vhf", "miqp", "naqp-cw",
                    "naqp-rtty", "naqp-ssb", "ncqp", "neqp", "nyqp", "ocdx-cw", "ocdx-ssb",
                    "ohqp", "okom-cw", "okom-ssb", "pacc", "podxs-nmj", "podxs-pumpkin",
                    "podxs-stpat", "podxs-tp-dec", "podxs-tp-nov", "pskfest", "rdxc",
                    "rsgb-160-feb", "rsgb-160-nov", "sac-cw", "sac-ssb",
                    "sartg-ny-rtty", "sartg-rtty", "schwaben-kw", "schwaben-ukw", "spdx",
                    "stew-perry", "txqp", "uba-cw", "uba-ssb", "ukei-cw", "undx",
                    "vfdb-dlpx-cw", "vfdb-dlpx-ssb", "volta-rtty", "wa-salmon-run", "wae-cw",
                    "wae-rtty", "wae-ssb", "wag", "wpx-cw", "wpx-rtty", "wpx-ssb", "ww-digi",
                    "yodx"]
    for cid in files:
        d = builtin(cid)
        assert rulefiles.validate(d) == [], cid
        assert d["id"] == cid                     # Dateiname = id
    assert set(CONTESTS) == set(files) | {"freies-log"}     # 0.10.18: freies Log eingebaut


def test_contest_list_sorted_by_name():
    assert next(iter(CONTESTS)) == "freies-log"            # 0.10.18: freies Log ganz oben
    names = [c.name for cid, c in CONTESTS.items() if cid != "freies-log"]
    assert names == sorted(names, key=str.lower)


def test_attributes_from_rules():
    c = CONTESTS["wpx-ssb"]
    assert c.mults_per_band is False and c.uses_serial and c.exchange_label == "Nr"
    assert c.max_hours_single == 36 and c.max_hours_classic == 24 and c.min_break_minutes == 60
    assert c.schedule == {"month": 3, "start_hour": 0, "hours": 48}
    d = CONTESTS["ww-digi"]
    assert not d.uses_rst and d.exchange_kind == "grid4" and d.modes == {"DG"}
    w = CONTESTS["cqww-cw"]
    assert w.modes == {"CW"} and w.mult_types == [("zone", "Zonen"), ("country", "Länder")]
    assert all(c.log_format == ("edi" if (cid.startswith("iaru-") and cid != "iaru-hf") or cid in UKW_DARC
                                else "adif" if cid == "pskfest" or cid.startswith("podxs-") else "cabrillo")
               for cid, c in CONTESTS.items() if cid != "freies-log")


@pytest.mark.parametrize("change, expect", [
    (lambda d: d.pop("bands"), "„bands“ fehlt"),
    (lambda d: d.update(bands=["160", "0.5mm"]), "Band „0.5mm“"),
    (lambda d: d.update(modes=["SSB"]), "Mode „SSB“"),
    (lambda d: d.update(format=rulefiles.FORMAT_VERSION + 1), "neuere GoGoHam-Version"),
    (lambda d: d["points"].update(type="km_sum"), "geplant"),
    (lambda d: d["points"].update(own_country=-1), "negativ"),
    (lambda d: d["points"].pop("other_continent"), "„other_continent“ fehlt"),
    (lambda d: d["multipliers"].append({"type": "doks"}), "Multi-Art „doks“"),
    (lambda d: d["multipliers"].append({"type": "dok"}), "„dok“ braucht „location“"),
    (lambda d: d["multipliers"][0].update(per="once"), "gleich zählen"),
    (lambda d: d.update(exchange=[{"field": "rst"}]), "genau ein Feld"),
    (lambda d: d.update(exchange=[{"field": "rst"}, {"field": "serial"}]), "Zone im Austausch"),
    (lambda d: d.update(id="CQ WW"), "„id“"),
    (lambda d: d.update(rules_checked="11/2026"), "JJJJ-MM"),
    (lambda d: d["schedule"].update(month=13), "1 bis 12"),
    (lambda d: d.update(log_format="pdf"), "Log-Format „pdf“"),
])
def test_validate_finds_errors(change, expect):
    d = copy.deepcopy(builtin("cqww-ssb"))
    change(d)
    errs = rulefiles.validate(d)
    assert any(expect in e for e in errs), errs


def test_user_file_overrides_builtin(tmp_path, cty):
    d = builtin("cqww-ssb")
    d["points"]["other_continent"] = 5                      # z. B. geänderte Ausschreibung
    d["rules_checked"] = "2027-09"
    (tmp_path / "mein-cqww.json").write_text(json.dumps(d), encoding="utf-8")
    res = rulefiles.load_all(data_dir=tmp_path)
    assert res.problems == [] and res.overrides == ["cqww-ssb"]
    assert not res.rules["cqww-ssb"].builtin
    contests = build_contests(res)
    cls = contests["cqww-ssb"]
    assert cls.rules_checked == "2027-09" and not cls.rules_builtin
    c = cls(cty, Station(call="DL1ABC", cq_zone=14))
    lk = c.lookup("W1AW")
    assert c.qso_points(Qso(call="W1AW", band="20", mode="USB", exch_r="05"), lk) == 5
    # die anderen Contests bleiben die eingebauten
    assert contests["wpx-ssb"].rules_builtin


def test_broken_user_file_falls_back(tmp_path):
    (tmp_path / "kaputt.json").write_text('{"id": "cqww-ssb", ', encoding="utf-8")
    bad = builtin("wpx-ssb")
    bad["points"]["type"] = "dok_punkte"
    (tmp_path / "wpx.json").write_text(json.dumps(bad), encoding="utf-8")
    res = rulefiles.load_all(data_dir=tmp_path)
    assert len(res.problems) == 2
    assert any("kein gültiges JSON" in p and "Zeile" in p for p in res.problems)
    assert any("Punkte-Art „dok_punkte“" in p for p in res.problems)
    assert all("nicht benutzt" in p for p in res.problems)
    assert res.rules["cqww-ssb"].builtin and res.rules["wpx-ssb"].builtin
    assert res.overrides == []


def test_missing_user_dir_is_fine(tmp_path):
    res = rulefiles.load_all(data_dir=tmp_path / "gibt-es-nicht")
    assert res.problems == [] and len(res.rules) == 130


def test_user_dir_follows_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert rulefiles.user_dir() == tmp_path / "gogoham" / "rules"


def test_new_contest_from_building_blocks(cty):
    """Ein neuer Contest nur aus vorhandenen Bausteinen – ohne Programmänderung."""
    d = {
        "format": 1, "id": "test-sprint", "name": "Test-Sprint", "bands": ["80", "40"],
        "modes": ["CW"], "dupe": "band_mode",
        "exchange": [{"field": "rst"}, {"field": "serial"}],
        "points": {"type": "fixed", "value": {"default": 1, "80": 2}},
        "multipliers": [{"type": "country", "per": "once"}],
        "log_format": "adif",
    }
    assert rulefiles.validate(d) == []
    cls = make_contest_class(d)
    c = cls(cty, Station(call="DL1ABC"))
    s = Scorer(c)
    log = [Qso(id=1, call="OE1XYZ", band="80", mode="CW", exch_r="001"),
           Qso(id=2, call="W1AW", band="40", mode="CW", exch_r="012"),
           Qso(id=3, call="OE1XYZ", band="40", mode="CW", exch_r="002")]
    s.rebuild(log)
    assert s.total_points == 2 + 1 + 1
    assert s.mult_count() == 2                       # OE und W, einmal im Contest
    assert s.score == 8
    assert c.exchange_label == "Nr" and c.uses_serial and c.dupe_per_mode
    assert c.log_format == "adif"


def test_export_hint_texts():
    import sys
    sys.path.insert(0, str(HERE))
    import fake_qt
    fake_qt.install()
    from gogoham.gui.dialogs import ExportDialog, export_hint
    assert "Cabrillo" in export_hint("CQ WW DX SSB", "cabrillo")
    assert "eine Datei je Band" in export_hint("Test-UKW", "edi")
    dlg = ExportDialog(CONTESTS["cqww-ssb"](None, Station(call="DL1ABC")))
    assert dlg.choice() == "cabrillo"
