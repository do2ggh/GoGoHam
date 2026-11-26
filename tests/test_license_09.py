"""0.9: Lizenz – GPL-3.0-only, Zusatzbedingungen nach § 7, Liste fremder Teile."""
import re
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ATTR = "GoGoHam by DO2GGH · © 2026 Franz, DO2GGH"


def test_license_is_unchanged_gpl3():
    data = (ROOT / "LICENSE").read_bytes()
    # Prüfsumme des Originaltexts von gnu.org/licenses/gpl-3.0.txt
    assert hashlib.sha256(data).hexdigest() == \
        "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"


def test_additional_terms_and_notices():
    terms = (ROOT / "ADDITIONAL-TERMS.md").read_text(encoding="utf-8")
    assert terms.count(ATTR) == 2 and "GPL-3.0-only" in terms
    assert "THIRD-PARTY.md" in terms and (ROOT / "THIRD-PARTY.md").exists()
    for f in ("gogoham/gui/dialogs.py", "gogoham/help/handbuch.html", "gogoham/help/handbook.en.html"):
        src = (ROOT / f).read_text(encoding="utf-8")
        assert "© 2026 Franz, DO2GGH" in src and "GPL-3.0" in src, f
    assert "GPL-3.0-only" in (ROOT / "gogoham/__init__.py").read_text(encoding="utf-8")
    # Urhebervermerk nur „Franz, DO2GGH“ – nie ein Nachname dahinter (ohne ihn hier zu nennen)
    text = "".join((ROOT / f).read_text(encoding="utf-8")
                   for f in ("README.md", "ADDITIONAL-TERMS.md", "THIRD-PARTY.md"))
    assert not re.search(r"Franz [A-ZÄÖÜ][a-zäöüß]{2,}", text)
