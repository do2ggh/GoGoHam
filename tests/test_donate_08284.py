"""0.8.28.4: Hilfe (bis 0.10.3 Info) → „☕ Spendier DO2GGH einen Kaffee“ öffnet nur den PayPal-Link."""
from gogoham import DONATE_URL
import pathlib


def test_url():
    assert DONATE_URL == "https://paypal.me/GoGoHam"


def test_menu_entry_in_source():
    src = pathlib.Path(__file__).parents[1].joinpath("gogoham/gui/main_window.py").read_text()
    i = src.index('addMenu(tr("&Hilfe"))')             # 0.10.4: Info ist in Hilfe aufgegangen
    block = src[i:i + 1000]
    assert 'tr("☕ Spendier DO2GGH einen Kaffee")' in block
    assert "self._open_url(DONATE_URL)" in block


def test_handbooks_mention_link():
    base = pathlib.Path(__file__).parents[1] / "gogoham/help"
    for name in ("handbuch.html", "handbook.en.html"):
        assert "https://paypal.me/GoGoHam" in (base / name).read_text()
