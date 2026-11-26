"""0.8.0: Sprache der Oberfläche (Deutsch/Englisch)."""

import json
import string
import subprocess
import sys
from pathlib import Path

import pytest

from gogoham import i18n

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


@pytest.fixture()
def english():
    i18n.set_language("en")
    yield
    i18n.set_language("de")


def test_tr_german_is_identity():
    assert i18n.language() == "de"
    assert i18n.tr("Log speichern unter") == "Log speichern unter"
    assert i18n.tr("DUPE auf {band}", band="20 m") == "DUPE auf 20 m"


def test_tr_english(english):
    assert i18n.tr("Log speichern unter") == "Save log as"
    assert i18n.tr("DUPE auf {band}", band="20 m") == "DUPE on 20 m"
    assert i18n.tr("Gibt es nicht in der Liste") == "Gibt es nicht in der Liste"   # Rückfall


def test_broken_translation_falls_back(english, monkeypatch):
    monkeypatch.setitem(i18n._table, "Test {a}", "kaputt {b}")
    assert i18n.tr("Test {a}", a=1) == "Test 1"


@pytest.mark.parametrize("env, want", [("de_DE.UTF-8", "de"), ("en_US.UTF-8", "en"),
                                       ("fr_FR.UTF-8", "fr"), ("ja_JP.UTF-8", "en"), ("C", None)])
def test_system_language(monkeypatch, env, want):
    for v in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("LANG", env)
    if want:
        assert i18n.resolve("auto") == want
    assert i18n.resolve("de") == "de" and i18n.resolve("en") == "en"
    assert i18n.resolve("xx") == "en"


def test_available_languages():
    langs = i18n.available()
    assert langs["de"] == "Deutsch" and langs["en"] == "English"


def test_english_file_complete_and_consistent():
    """Jeder Text im Programm ist übersetzt, und die Platzhalter stimmen überein."""
    from i18n_check import collect
    keys = collect()
    data = json.loads((ROOT / "gogoham" / "i18n" / "en.json").read_text(encoding="utf-8"))
    data.pop("_meta")
    missing = [k for k in keys if not data.get(k)]
    assert not missing, missing[:5]
    fmt = string.Formatter()
    for k, v in data.items():
        ph = lambda s: sorted(f for _l, f, _s, _c in fmt.parse(s) if f is not None)
        assert ph(k) == ph(v), (k, v)


def test_numbers():
    assert i18n.num(28450.5, 2) == "28.450,50"
    i18n.set_language("en")
    try:
        assert i18n.num(28450.5, 2) == "28,450.50" and i18n.num(1234567) == "1,234,567"
    finally:
        i18n.set_language("de")


def test_country_names(english):
    from gogoham.countries import german_name
    assert german_name("OE", "Austria") == "Austria"
    i18n.set_language("de")
    assert german_name("OE", "Austria") == "Österreich"


def test_program_in_english_subprocess(tmp_path):
    """Frisch gestartet auf Englisch: auch beim Laden festgelegte Texte sind englisch."""
    code = """
from gogoham import i18n
i18n.set_language("en")
from pathlib import Path
from gogoham.cty import CtyDB
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham import columns
cty = CtyDB.from_file(Path(%r))
c = CONTESTS["arrl-dx-ssb"](cty, Station(call="DL1ABC"))
ev = Scorer(c).evaluate(Qso(call="OE1XX", band="20", mode="USB", exch_r="KW"))
print(ev.warning)
print(columns.header_label("call", "x"), "|", c.mult_types[0][1])
""" % str(ROOT / "tests" / "cty_sample.dat")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    lines = out.stdout.splitlines()
    assert lines[0] == "DX works W/VE only (USA/Canada)"
    assert lines[1] == "Call | States"


# ------------------------------------------------------------ 0.10.27: weitere Sprachen
def test_fallback_english_for_new_language(tmp_path, monkeypatch):
    """Fehlt in einer neuen Sprache ein Text, erscheint Englisch (nicht Deutsch); „(Beta)“."""
    d = tmp_path / "i18n"
    d.mkdir()
    for f in ("en.json",):
        (d / f).write_text((i18n.LANG_DIR / f).read_text(encoding="utf-8"), encoding="utf-8")
    (d / "xx.json").write_text(json.dumps({"_meta": {"name": "Testisch", "beta": True},
                                           "Log speichern unter": "Tallenna loki",
                                           "DUPE auf {band}": "kaputt {falsch}"}),
                               encoding="utf-8")
    monkeypatch.setattr(i18n, "LANG_DIR", d)
    assert i18n.available()["xx"] == "Testisch (Beta)"
    try:
        assert i18n.set_language("xx") == "xx"
        assert i18n.tr("Log speichern unter") == "Tallenna loki"
        assert i18n.tr("Gibt es nicht in der Liste") == "Gibt es nicht in der Liste"
        assert i18n.tr("DUPE auf {band}", band="20 m") == "DUPE on 20 m"   # kaputt → Englisch
        en = json.loads((d / "en.json").read_text(encoding="utf-8"))
        k = next(k for k in en if k != "_meta" and "{" not in k and en[k] != k)
        assert i18n.tr(k) == en[k]                                         # fehlt → Englisch
    finally:
        monkeypatch.undo()
        i18n.set_language("de")


def test_handbook_english_for_other_languages():
    from gogoham.gui.help import handbook_path
    assert handbook_path("de").name == "handbuch.html"
    assert handbook_path("en").name == "handbook.en.html"
    assert handbook_path("es").name == "handbook.en.html"      # nur DE + EN (Nutzer 2026-11-14)


def test_all_language_files_consistent():
    """Jede Sprachdatei: nur bekannte Texte, gleiche Platzhalter, Name im Kopf."""
    from i18n_check import collect
    keys = set(collect())
    fmt = string.Formatter()
    ph = lambda s: sorted(f for _l, f, _s, _c in fmt.parse(s) if f is not None)
    for p in sorted(i18n.LANG_DIR.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data.pop("_meta").get("name"), p.name
        for k, v in data.items():
            if not v:
                continue
            assert ph(k) == ph(v), (p.name, k, v)
        stale = [k for k in data if k not in keys]
        assert not stale, (p.name, stale[:5])


def test_qt_own_texts_translated(tmp_path):
    """0.10.27: Qts Standardknöpfe (OK/Abbrechen) in der eingestellten Sprache."""
    code = """
import sys
sys.path.insert(0, %r)
from PySide6.QtWidgets import QApplication, QDialogButtonBox
app = QApplication([])
from gogoham.gui.app import install_qt_translation
t = install_qt_translation(app, "de")
b = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
print(bool(t), b.buttons()[0].text().replace("&", ""))
assert install_qt_translation(app, "en") is None
""" % str(ROOT)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={"QT_QPA_PLATFORM": "offscreen", "PATH": "/usr/bin:/bin",
                              "HOME": str(tmp_path)}, timeout=60)
    assert out.returncode == 0, out.stderr
    found, text = out.stdout.split()
    if found == "True":                      # Qt-Übersetzung auf diesem System vorhanden
        assert text == "Abbrechen"


def test_language_list_sorted():
    """0.10.29: Sprachen alphabetisch nach Namen, Akzente zählen nicht."""
    names = list(i18n.available().values())
    assert names == sorted(names, key=i18n._sort_key)
    assert i18n._sort_key("Čeština") < i18n._sort_key("Dansk")


def test_language_combo_scrolls(tmp_path):
    """0.10.29: die Sprachauswahl klappt als kurze, scrollbare Liste auf."""
    code = """
import sys
sys.path.insert(0, %r)
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham.gui.dialogs import DisplayPage
p = DisplayPage({})
c = p.language
print(c.maxVisibleItems(), "combobox-popup: 0" in c.styleSheet(), c.itemData(0), c.count())
""" % str(ROOT)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen",
                              "HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "c"),
                              "XDG_DATA_HOME": str(tmp_path / "d")}, timeout=60)
    assert out.returncode == 0, out.stderr
    vis, style, first, count = out.stdout.split()[-4:]
    assert (vis, style, first) == ("10", "True", "auto")
    assert int(count) == len(i18n.available()) + 1
