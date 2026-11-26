"""0.10.8.1: Exporte in eigenen Ordner „Export“ im Austausch-Ordner, Liesmich in der Sicherung,
DOK-Liste wird mitgeliefert (Erlaubnis DARC + VFDB)."""
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

from gogoham import livestick as ls
from gogoham.gui.main_window import MainWindow

ROOT = Path(__file__).resolve().parent.parent


def _marker(tmp_path):
    exch = tmp_path / "Austausch"
    exch.mkdir()
    m = tmp_path / "livestick.json"
    m.write_text(json.dumps({"exchange": str(exch)}))
    return m, exch


def test_export_path(tmp_path):
    m, exch = _marker(tmp_path)
    p = ls.export_path("/home/x/GoGoHam/cqww-2026.ggh", ".cbr", m)
    assert p == exch / "Export" / "cqww-2026.cbr" and p.parent.is_dir()
    assert ls.export_path("/a/b.ggh", ".adi", tmp_path / "fehlt.json") is None


def test_export_suggestion(tmp_path, monkeypatch):
    m, exch = _marker(tmp_path)
    fake = SimpleNamespace(db=SimpleNamespace(path=str(tmp_path / "logs" / "wag.ggh")))
    monkeypatch.setattr(ls, "MARKER", tmp_path / "fehlt.json")          # normaler PC
    assert MainWindow._export_suggestion(fake, ".adi") == str(tmp_path / "logs" / "wag.adi")
    monkeypatch.setattr(ls, "MARKER", m)                                 # Live-Stick
    assert MainWindow._export_suggestion(fake, ".edi") == str(exch / "Export" / "wag.edi")


def test_backup_readme_kept(tmp_path):
    exch = tmp_path / "x"
    exch.mkdir()
    d = ls.backup_to_exchange(exch, "/l/wag.ggh", "a", None)
    readme = d / "LIESMICH.txt"
    assert "Log öffnen" in readme.read_text() and "Export" in readme.read_text()
    readme.write_text("eigener Text")
    ls.backup_to_exchange(exch, "/l/wag.ggh", "b", None)
    assert readme.read_text() == "eigener Text"


def test_dok_list_is_shipped():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "dok_ov.txt" in data["tool"]["setuptools"]["package-data"]["gogoham"]
    assert "dok_ov.txt" not in (ROOT / "MANIFEST.in").read_text()
    assert (ROOT / "docs" / "erlaubnisse" / "darc-2026-11-12.txt").is_file()
    assert "darc-2026-11-12" in (ROOT / "THIRD-PARTY.md").read_text()
