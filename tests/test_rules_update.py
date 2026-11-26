"""0.6.5: Regeln von GitHub holen (hier aus einem lokalen Ordner), Log merkt sich Regeln."""

import json
import shutil
import sys
from pathlib import Path

import pytest

from gogoham import rulefiles, rulesupdate
from gogoham.contests import Qso, Scorer, Station, build_contests, class_from_log
from gogoham.cty import CtyDB

HERE = Path(__file__).parent


@pytest.fixture()
def github(tmp_path):
    """Nachgebautes GitHub-Verzeichnis rules/ mit den eingebauten Dateien + index.json."""
    src = tmp_path / "github" / "rules"
    src.mkdir(parents=True)
    for p in rulefiles.BUILTIN_DIR.glob("*.json"):
        shutil.copy(p, src / p.name)
    data = tmp_path / "data"

    def publish():
        (src / "index.json").write_text(json.dumps(rulesupdate.make_index(src)), encoding="utf-8")
    publish()
    return src, data, publish, src.as_uri() + "/"


def bump(src, cid, **changes):
    p = src / f"{cid}.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["revision"] += 1
    for k, v in changes.items():
        d[k] = v
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    return d


def test_make_index_matches_builtin():
    idx = rulesupdate.make_index(rulefiles.BUILTIN_DIR)
    assert idx["format"] == 1
    assert {e["id"] for e in idx["rules"]} == {"cqww-ssb", "cqww-cw", "wpx-ssb", "wpx-cw",
                                               "cqww-rtty", "wpx-rtty", "arrl-rtty", "wae-rtty",
                                               "ww-digi", "cq160-cw", "cq160-ssb",
                                               "arrl-dx-cw", "arrl-dx-ssb", "arrl-10",
                                               "iaru-hf", "euhfc", "wag", "darc-10m",
                                               "darc-xmas", "darc-easter", "darc-fd-cw",
                                               "darc-fd-ssb", "darc-ft4", "darc-cwa",
                                               "darc-ac", "wae-cw",
                                               "wae-ssb", "rdxc", "iota", "aa-cw",
                                               "aa-ssb", "okom-cw", "okom-ssb", "hadx",
                                               "uba-cw", "uba-ssb", "pacc", "spdx",
                                               "iaru-vhf", "iaru-uhf", "darc-vhf", "darc-ukw-spring", "darc-microwave", "marconi-vhf", "darc-ukw-fd-winter", "darc-ukw-fd-summer",
                                               "lzdx", "9adx", "agcw-hny",
                                               "yodx", "ea-majestad-cw", "ea-majestad-ssb",
                                               "agcw-qrp", "agcw-qrp-party", "bbt-summer-1", "bbt-summer-2", "bbt-winter-1", "bbt-winter-2", "franken-a", "franken-b", "franken-c", "franken-d", "franken-e", "franken-f", "franken-k", "franken-l",
                                               "hsc", "schwaben-kw", "schwaben-ukw",
                                               "arrl-160", "stew-perry",
                                               "jidx-cw", "jidx-ph", "sac-cw", "sac-ssb", "canada-day", "naqp-cw", "naqp-ssb", "naqp-rtty", "alpe-adria-vhf", "arrl-digi", "bartg-rtty", "dig-ssb", "dig-cw", "dtc", "aoec-160",
                                               "arrl-ss-cw", "arrl-ss-ssb", "af-all-mode", "baltic", "sartg-rtty", "sartg-ny-rtty", "makrothen", "arrl-vhf-jun", "arrl-vhf-sep", "cqww-vhf", "cqww-vhf-digi", "iaru-50", "iaru-70", "alpe-adria-uhf",
                                               "ea-rtty", "ea-psk63", "jarl-ww-rtty", "volta-rtty", "neqp", "7qp",
                                               "ohqp", "miqp", "inqp", "txqp", "nyqp", "rsgb-160-feb", "rsgb-160-nov", "ocdx-ssb", "ocdx-cw", "ukei-cw", "pskfest",
                                               "ncqp", "wa-salmon-run", "undx", "podxs-stpat", "podxs-nmj", "podxs-pumpkin", "podxs-tp-nov", "podxs-tp-dec",
                                               "vfdb-dlpx-cw", "vfdb-dlpx-ssb", "agcw-htp-80", "agcw-htp-40", "agcw-sta"}
    multi = {"cqww-cw", "cqww-ssb", "wpx-cw", "wpx-ssb", "arrl-dx-cw", "arrl-dx-ssb", "iaru-hf"}
    # 0.10.28: Korrekturen aus der Regel-Prüfung → Revision 2
    multi |= {"cq160-cw", "wae-cw", "wae-ssb", "wae-rtty", "okom-cw", "okom-ssb",
              "agcw-qrp-party", "darc-easter", "darc-xmas", "darc-ft4", "yodx", "ref-cw",
              "ref-ssb", "pacc", "aa-cw", "aa-ssb"} | {f"franken-{k}" for k in "abcdefkl"}
    multi |= {"arrl-160", "uba-cw", "uba-ssb"}    # 0.10.32: KH8/S bzw. SV/A großgeschrieben
    # 0.10.41: Einsendeweg „submit“ → Revision + 1
    import json as _json
    rules_dir = Path(rulefiles.__file__).parent / "rules"
    with_submit = {e["id"] for e in idx["rules"]
                   if "submit" in _json.loads((rules_dir / f"{e['id']}.json").read_text())}
    assert len(with_submit) == 121
    bbt = {"bbt-summer-1", "bbt-summer-2", "bbt-winter-1", "bbt-winter-2"}   # 0.10.42: Deckblatt
    assert all(e["revision"] == (2 if e["id"] in multi else 1) + (e["id"] in with_submit)
               + (e["id"] in bbt)
               and len(e["sha256"]) == 64 for e in idx["rules"])


def test_nothing_to_do_when_same_revision(github):
    src, data, _pub, url = github
    res = rulesupdate.check_and_download(url, data)
    assert not res.changed and not res.errors and not res.offline
    assert "sind aktuell" in res.summary()
    assert not (data / "download").exists()


def test_newer_revision_is_downloaded_and_used(github):
    src, data, pub, url = github
    d = bump(src, "cqww-ssb", rules_checked="2027-09")
    pub()
    res = rulesupdate.check_and_download(url, data)
    assert res.updated == ["CQ WW DX SSB"] and not res.new
    assert (data / "download" / "cqww-ssb.json").is_file()
    loaded = rulefiles.load_all(data_dir=data).rules["cqww-ssb"]
    assert loaded.source == "download" and loaded.revision == d["revision"]
    assert build_contests(rulefiles.load_all(data_dir=data))["cqww-ssb"].rules_checked == "2027-09"
    # zweiter Lauf: nichts mehr zu tun
    assert not rulesupdate.check_and_download(url, data).changed


def test_new_contest_without_program_update(github):
    src, data, pub, url = github
    d = json.loads((src / "wpx-cw.json").read_text(encoding="utf-8"))
    d.update(id="test-sprint", name="Test-Sprint", revision=1)
    (src / "test-sprint.json").write_text(json.dumps(d), encoding="utf-8")
    pub()
    res = rulesupdate.check_and_download(url, data)
    assert res.new == ["Test-Sprint"]
    assert "test-sprint" in build_contests(rulefiles.load_all(data_dir=data))


def test_bad_downloads_are_rejected(github):
    src, data, pub, url = github
    bump(src, "wpx-ssb")
    pub()
    # Datei nach dem Erstellen des Inhaltsverzeichnisses verändert -> Prüfsumme falsch
    p = src / "wpx-ssb.json"
    p.write_text(p.read_text(encoding="utf-8").replace('"own_country": 1', '"own_country": 9'),
                 encoding="utf-8")
    res = rulesupdate.check_and_download(url, data)
    assert any("Prüfsumme" in e for e in res.errors) and not res.changed
    assert rulefiles.load_all(data_dir=data).rules["wpx-ssb"].source == "builtin"


def test_newer_format_is_skipped(github):
    src, data, pub, url = github
    bump(src, "ww-digi", format=99)
    pub_index = rulesupdate.make_index           # make_index prüft – hier von Hand schreiben
    idx = json.loads((src / "index.json").read_text(encoding="utf-8"))
    import hashlib
    for e in idx["rules"]:
        if e["id"] == "ww-digi":
            e["revision"] += 1                   # neuer als die eingebaute Datei
            e["sha256"] = hashlib.sha256((src / "ww-digi.json").read_bytes()).hexdigest()
    (src / "index.json").write_text(json.dumps(idx), encoding="utf-8")
    res = rulesupdate.check_and_download(url, data)
    assert res.skipped == ["WW Digi DX (FT4/FT8)"] and not res.changed
    assert pub_index


def test_own_rules_are_never_overwritten(github):
    src, data, pub, url = github
    data.mkdir()
    mine = json.loads((src / "cqww-cw.json").read_text(encoding="utf-8"))
    mine["points"]["other_continent"] = 7
    (data / "mein-cqww-cw.json").write_text(json.dumps(mine), encoding="utf-8")
    bump(src, "cqww-cw")
    pub()
    res = rulesupdate.check_and_download(url, data)
    assert not res.changed
    assert rulefiles.load_all(data_dir=data).rules["cqww-cw"].source == "user"


def test_offline_and_missing_index(tmp_path, monkeypatch):
    res = rulesupdate.check_and_download((tmp_path / "gibt-es-nicht").as_uri() + "/", tmp_path)
    assert res.offline and "kein Internet" in res.summary()
    import urllib.error

    def http404(url, timeout):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    monkeypatch.setattr(rulesupdate, "_get", http404)
    res = rulesupdate.check_and_download("https://example.invalid/", tmp_path)
    assert not res.offline and "HTTP 404" in res.errors[0]


def test_log_keeps_its_rules(github):
    """Ein Log rechnet mit seinen gespeicherten Regeln – auch nach einem Regel-Update."""
    src, data, pub, url = github
    cty = CtyDB.from_file(HERE / "cty_sample.dat")
    old = json.loads((rulefiles.BUILTIN_DIR / "cqww-ssb.json").read_text(encoding="utf-8"))
    meta = {"contest": "cqww-ssb", "rules_json": json.dumps(old)}
    bump(src, "cqww-ssb", points={**old["points"], "other_continent": 5})
    pub()
    rulesupdate.check_and_download(url, data)
    newest = build_contests(rulefiles.load_all(data_dir=data))["cqww-ssb"]
    logcls, note = class_from_log(meta)
    assert note == "" and logcls.rules_source == "log" and \
        logcls.rules_revision == old["revision"]

    def points(cls):
        c = cls(cty, Station(call="DL1ABC", cq_zone=14))
        s = Scorer(c)
        s.rebuild([Qso(id=1, call="W1AW", band="20", mode="USB", exch_r="05")])
        return s.total_points
    assert points(logcls) == 3 and points(newest) == 5
    # beschädigte oder zu neue Regeln im Log -> klare Meldung, dann gelten die aktuellen
    assert class_from_log({"rules_json": "{kaputt"})[0] is None
    cls, note = class_from_log({"rules_json": json.dumps({**old, "format": rulefiles.FORMAT_VERSION + 1})})
    assert cls is None and "neuere GoGoHam-Version" in note
    assert class_from_log({})[0] is None


# ------------------------------------------------------------ Fenster (Attrappe)
@pytest.fixture()
def fq():
    sys.path.insert(0, str(HERE))
    import fake_qt
    fake_qt.install()
    for m in [m for m in sys.modules if m.startswith("gogoham.gui")]:
        del sys.modules[m]
    return fake_qt


def test_log_dialog_offers_newer_rules(fq, monkeypatch):
    from gogoham import contests
    from gogoham.gui import dialogs
    old = json.loads((rulefiles.BUILTIN_DIR / "cqww-ssb.json").read_text(encoding="utf-8"))
    stale = dict(old, revision=1, points={**old["points"], "other_continent": 2})
    meta = {"contest": "cqww-ssb", "mycall": "DL1ABC", "rules_json": json.dumps(stale)}
    dlg = dialogs.LogSettingsDialog(meta)
    assert "im Log gespeichert" in dlg.rules_label.text()
    assert dlg.newer_btn.isVisible() and \
        f"Revision {old['revision']}" in dlg.newer_label.text()
    dlg._take_newer()
    assert json.loads(dlg.meta["rules_json"]) == contests.CONTESTS["cqww-ssb"].rules
    assert not dlg.newer_btn.isVisible()
    # gleiches Log mit aktuellen Regeln: kein Angebot
    meta2 = {"contest": "cqww-ssb", "mycall": "DL1ABC",
             "rules_json": json.dumps(contests.CONTESTS["cqww-ssb"].rules)}
    assert not dialogs.LogSettingsDialog(meta2).newer_btn.isVisible()


def test_dropped_contest_is_removed_from_downloads(github):
    """0.10.41.1: Was das Regel-Projekt nicht mehr führt (REF), verschwindet aus den Downloads –
    eigene Regeln bleiben."""
    src, data, _pub, url = github
    dl = data / "download"
    dl.mkdir(parents=True)
    old = json.loads((Path(__file__).parent / "rule_samples" / "ref-cw.json").read_text(encoding="utf-8"))
    (dl / "ref-cw.json").write_text(json.dumps(old), encoding="utf-8")
    (data / "ref-ssb.json").write_text(json.dumps(dict(old, id="ref-ssb")), encoding="utf-8")
    res = rulesupdate.check_and_download(url, data)
    assert not (dl / "ref-cw.json").exists() and (data / "ref-ssb.json").exists()
    assert res.removed == [old["name"]] and res.changed and "entfernt" in res.summary()
