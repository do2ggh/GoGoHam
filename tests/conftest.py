"""Gemeinsame Test-Einstellungen."""

import os

import pytest
from pathlib import Path

DOK_SAMPLE = Path(__file__).with_name("dok_sample.txt")


# Stationslog (0.10): in den Tests nicht im echten Netzwerk nach Hauptplätzen suchen
os.environ.setdefault("GOGOHAM_NO_DISCOVERY", "1")


@pytest.fixture(autouse=True)
def no_time_server(monkeypatch):
    """Keine Zeitserver-Abfrage in den Tests (0.8.18.3) – die Tests geben Abweichungen selbst vor."""
    from gogoham import clockcheck
    monkeypatch.setattr(clockcheck.Checker, "run", lambda self: None)


@pytest.fixture(autouse=True)
def no_internet_for_rules(monkeypatch, tmp_path_factory):
    """Tests gehen nie ins Internet: Regel-Updates zeigen auf einen leeren Ordner."""
    from gogoham import rulesupdate
    empty = tmp_path_factory.mktemp("kein-github")
    monkeypatch.setattr(rulesupdate, "BASE_URL", empty.as_uri() + "/")


@pytest.fixture(autouse=True, scope="session")
def german_ui():
    """Die Tests prüfen die deutschen Texte – unabhängig von der Sprache des Rechners."""
    from gogoham import i18n
    i18n.set_language("de")


@pytest.fixture(autouse=True)
def builtin_doks_only(monkeypatch):
    """DOK-Prüfung in Tests nur mit der eingebauten OV-Liste – nie mit einer
    heruntergeladenen Sonder-DOK-Liste des Rechners."""
    from gogoham import dok
    from gogoham.contests import rulebased
    db = dok.DokDB()
    # Die vollständige Liste liegt (noch) nicht im öffentlichen Projekt (Erlaubnis DARC/VFDB
    # offen) – ohne sie, z. B. auf GitHub, prüfen die Tests mit einer kleinen Beispielliste.
    src = dok.BUILTIN_OV if dok.BUILTIN_OV.is_file() else DOK_SAMPLE
    db.load_ov(src.read_text(encoding="utf-8"))
    monkeypatch.setattr(rulebased, "_DOKDB", db)


def builtin_newer_than(fmt: int) -> tuple[list[str], int]:
    """Namen der eingebauten Regel-Dateien mit Format > fmt (sortiert) und Anzahl der übrigen –
    so bleiben die „ältere Version überspringt neue Dateien“-Tests bei neuen Contests gültig."""
    import json
    from gogoham import rulefiles
    from pathlib import Path
    newer, older = [], 0
    for p in (Path(rulefiles.__file__).parent / "rules").glob("*.json"):   # auch bei monkeypatch
        d = json.loads(p.read_text(encoding="utf-8"))
        if d["format"] > fmt:
            newer.append(d["name"])
        else:
            older += 1
    return sorted(newer), older


@pytest.fixture(autouse=True)
def own_call_history(monkeypatch, tmp_path_factory):
    """Call-History in Tests (0.9.1): ohne mitgelieferten Grundstock und nie in die echte
    gelernt.sqlite des Rechners schreiben."""
    from gogoham import callhistory
    d = tmp_path_factory.mktemp("callhistory")
    monkeypatch.setattr(callhistory, "history_dir", lambda: d)
    monkeypatch.setattr(callhistory, "BASE_FILE", d / "kein-grundstock.csv")


@pytest.fixture(autouse=True)
def no_internet_for_version_check(monkeypatch, tmp_path_factory):
    """Versionsprüfung (0.9.4) in Tests nie bei GitHub – leere Liste von Versionsmarken."""
    from gogoham import versioncheck
    f = tmp_path_factory.mktemp("kein-github-tags") / "tags.json"
    f.write_text("[]")
    monkeypatch.setattr(versioncheck, "TAGS_URL", f.as_uri())


@pytest.fixture(autouse=True)
def not_on_live_stick(monkeypatch, tmp_path_factory):
    """Tests laufen nie „vom Live-Stick“ (0.10.8) – außer ein Test legt die Markierung selbst an."""
    from gogoham import livestick
    monkeypatch.setattr(livestick, "MARKER", tmp_path_factory.mktemp("kein-stick") / "fehlt.json")
