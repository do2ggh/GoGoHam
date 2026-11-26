"""0.10.42: Bayerischer Bergtag – BBT-Deckblatt + Logblatt als Textdatei je Band."""

import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from gogoham import bbt, rulefiles
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.contests.rulebased import make_contest_class
from gogoham.cty import CtyDB

HERE = Path(__file__).parent
BBT = ("bbt-winter-1", "bbt-winter-2", "bbt-summer-1", "bbt-summer-2")


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def logged(cty):
    c = CONTESTS["bbt-summer-2"](cty, Station(call="DL1ABC/P", lookup=cty.lookup("DL1ABC/P"),
                                               grid="JN59ME"))
    s = Scorer(c)
    rows = [("DL5XY", "007 JN58TD", "2", "2027-08-08 09:40:00"),
            ("OE5ABC", "012 JN78DD", "2", "2027-08-08 09:45:00"),
            ("DL5XY", "008 JN58TD", "2", "2027-08-08 09:50:00"),      # Dupe
            ("DK2AA", "003 JO62QM", "70cm", "2027-08-08 07:20:00")]
    qs = []
    for i, (call, ex, band, t) in enumerate(rows, 1):
        q = Qso(id=i, time=t, call=call, band=band, mode="USB", rst_s="59", rst_r="59",
                exch_s=f"{i:03d} JN59ME", exch_r=ex)
        s.evaluate(q, commit=True)
        qs.append(q)
    return c, s, qs


META = {"mycall": "DL1ABC/P", "my_grid": "JN59ME", "name": "Max Muster",
        "address": "Musterstraße 1\n12345 Musterstadt", "my_dok": "b19",
        "bbt": json.dumps({"site": "Hesselberg", "asl": "689", "phone": "0911 123",
                           "combi": "nein", "remarks": "sonnig, gute Cond.",
                           "bands": {"2": {"tx": "FT-817", "pout": "5", "rx": "FT-817",
                                           "stage": "BF998", "ant": "9-El. Yagi", "code": "Ya9",
                                           "agl": "4", "kg_tx": "1,2", "kg_rx": "0",
                                           "kg_ant": "1.5"}}})}


def test_rule_files_and_format():
    assert rulefiles.FORMAT_VERSION >= 26
    for cid in BBT:
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert d["cover_sheet"] == "bbt" and d["log_format"] == "edi" and rulefiles.validate(d) == []
        assert bbt.is_bbt(CONTESTS[cid])
    bad = dict(d, cover_sheet="xyz")
    assert rulefiles.validate(bad)
    assert not bbt.is_bbt(CONTESTS["darc-vhf"])
    old = dict(CONTESTS["bbt-winter-1"].rules)
    old.pop("cover_sheet")                                  # Log von vor 0.10.42
    assert bbt.is_bbt(make_contest_class(old))


def test_helpers():
    assert bbt.home_call("DL1ABC/P") == "DL1ABC" and bbt.home_call("OE/DL1ABC/P") == "DL1ABC"
    assert bbt.SECTIONS["2"][0] == "A" and bbt.SECTIONS["3cm"][0] == "G" and bbt.SECTIONS["submm"][0] == "L"
    assert bbt.season(datetime(2027, 2, 6)) == "Winter" and bbt.season(datetime(2027, 8, 7)) == "Sommer"
    assert bbt.filename("/x/log.txt", "DL1ABC/P", "2") == "/x/DL1ABC_A_2m.txt"
    assert bbt.filename("/x/log.txt", "DL1ABC/P", "70cm") == "/x/DL1ABC_B_70cm.txt"
    assert bbt.total_kg({"kg_tx": "1,2", "kg_ant": "1.5", "kg_rx": ""}) == pytest.approx(2.7)
    d = {"bands": {"2": {"kg_tx": "8", "kg_ant": "3", "pout": "25"}}}
    w = bbt.warnings(d, ["2"])
    assert len(w) == 2 and "11 kg" in w[0] and "25 W" in w[1]
    assert bbt.warnings({"bands": {"2": {"kg_tx": "2", "pout": "10"}}}, ["2"]) == []
    assert bbt.load({"bbt": "kaputt"}) == {"bands": {}}


def test_stats_and_sheet(cty):
    c, s, qs = logged(cty)
    st = bbt.stats(c, s, qs, "2")
    kms = [r["km"] for r in st["rows"]]
    assert kms[2] == 0 and st["rows"][2]["rem"] == "Dupe"
    assert st["qsos"] == 2 and st["km"] == kms[0] + kms[1] and st["odx"][1] == "OE5ABC"
    assert st["countries"] == ["DL", "OE"] and st["rows"][0]["sent"] == "59001"
    assert st["rows"][0]["rcvd"] == "59007" and st["rows"][0]["grid"] == "JN58TD"
    raw = bbt.sheet(c, META, qs, s, "2", datetime(2027, 8, 7, 7), today=date(2027, 8, 9))
    assert b"\r\n" in raw
    txt = raw.decode("cp1252")
    for want in ("DARC/BBT - VHF - UHF - SHF - CONTEST", "vom Auswerter auszufüllen",
                 "BBT-Call:           DL1ABC/P", "[ ] Winter  [X] Sommer", "BBT vom: 08.08.2027",
                 "Sektion:            A  144 MHz", "Max Muster", "Telefon: 0911 123",
                 "Call:               DL1ABC", "Musterstraße 1, 12345 Musterstadt", "DOK:                B19",
                 "BBT-Standort:       Hesselberg", "Locator: JN59ME", "Höhe ASL:           689 m",
                 "Kombistation:       nein", "FT-817   Pout: 5 W", "Eing.st.: BF998",
                 "Code: Ya9", "über Grund: 4 m", "2,7 kg", f"Gesamtkilometerzahl: {st['km']} km",
                 "Anzahl der Verbindungen: 2", "Call: OE5ABC  Locator: JN78DD",
                 "gearbeitete Länder: DL, OE", "Anzahl: 2", "Ich bestätige die Richtigkeit",
                 "Datum: 09.08.2027   DL1ABC", "sonnig, gute Cond.",
                 "Sommer-BBT   BBT-Log für Sektion A (144 MHz)", "Bl: 1/1", "Dupe",
                 f"{st['km']:>6} km"):
        assert want in txt, want
    assert "EDI" not in txt


def test_many_qsos_make_several_sheets(cty):
    c, s, _ = logged(cty)
    qs = []
    for i in range(1, 121):
        q = Qso(id=100 + i, time=f"2027-08-08 10:{i % 60:02d}:00", call=f"DL{i}AA", band="23cm",
                mode="USB", rst_s="59", rst_r="59", exch_s=f"{i:03d}", exch_r=f"{i:03d} JO50AA")
        s.evaluate(q, commit=True)
        qs.append(q)
    txt = bbt.sheet(c, META, qs, s, "23cm", datetime(2027, 8, 7, 7)).decode("cp1252")
    assert "Bl: 3/3" in txt and txt.count("Zwischensumme Blatt") == 3 and txt.count("\f") == 3
    assert "Sektion:            C  1296 MHz" in txt


def test_export_dialog_prefers_bbt(monkeypatch):
    sys.path.insert(0, str(HERE))
    import fake_qt
    fake_qt.install()
    for m in [m for m in sys.modules if m.startswith("gogoham.gui")]:
        del sys.modules[m]
    from gogoham.gui.dialogs import ExportDialog
    d = ExportDialog(CONTESTS["bbt-summer-2"])
    assert d.choice() == "bbt"
    assert ExportDialog(CONTESTS["darc-vhf"]).choice() == "edi"


def test_bbt_dialog_collects_and_warns(monkeypatch):
    sys.path.insert(0, str(HERE))
    import fake_qt
    fake_qt.install()
    for m in [m for m in sys.modules if m.startswith("gogoham.gui")]:
        del sys.modules[m]
    from gogoham.gui import bbt_dialog as bd
    dlg = bd.BbtDialog(META, ["2", "70cm"])
    assert dlg.site.text() == "Hesselberg" and dlg.tabs.count() == 2
    assert dlg.fields["2"]["code"].text() == "Ya9"
    dlg.fields["70cm"]["kg_ant"].setText("12")
    asked = []
    monkeypatch.setattr(bd.QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or bd.QMessageBox.StandardButton.No,
                        raising=False)
    dlg.accept()
    assert asked and "70cm" in asked[0] and "bands" in dlg.data
    assert dlg.data["bands"].get("70cm", {}).get("kg_ant") != "12"      # nicht übernommen
    dlg.fields["70cm"]["kg_ant"].setText("2")
    dlg.accept()
    assert dlg.data["bands"]["70cm"]["kg_ant"] == "2" and dlg.data["site"] == "Hesselberg"
