"""0.9: GitHub-Startseite DE/EN, Changelog, Bildschirmfotos."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _links(text):
    return [l for l in re.findall(r"\]\(([^)#]+)\)", text) if not l.startswith("http")]


def test_readme_de_en_match():
    de = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    assert de.count("\n## ") == en.count("\n## ")          # gleiche Gliederung
    assert sorted(set(_links(de)) - {"README.en.md", "docs/images/gogoham-de.png"}) == \
        sorted(set(_links(en)) - {"README.md", "docs/images/gogoham-en.png"})
    for text in (de, en):
        for link in _links(text):
            assert (ROOT / link).exists(), link
        assert "© 2026 Franz, DO2GGH" in text
        assert not re.search(r"Franz [A-ZÄÖÜ][a-zäöüß]{2,}", text)   # kein Nachname


def test_changelog_has_current_version():
    from gogoham import __version__
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## Neu in (\S+)", log, re.M).group(1)
    assert first == __version__
    assert "## Neu in" not in (ROOT / "README.md").read_text(encoding="utf-8")


def test_contributing_and_github_templates():
    import yaml
    c = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "fremden Programmcode nehme ich nicht an" in c and "do not accept code from others" in c
    gh = ROOT / ".github"
    forms = {f.name: yaml.safe_load(f.read_text(encoding="utf-8"))
             for f in (gh / "ISSUE_TEMPLATE").glob("*.yml")}
    assert forms["config.yml"]["blank_issues_enabled"] is False
    for name in ("fehler.yml", "idee.yml"):
        assert forms[name]["name"].split(" · ")[0] in c          # Name steht so in CONTRIBUTING
    wf = yaml.safe_load((gh / "workflows" / "pull-requests.yml").read_text(encoding="utf-8"))
    assert "checkout" not in str(wf)                              # nie fremden Code ausführen
