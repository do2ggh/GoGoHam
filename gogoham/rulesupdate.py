"""Contest-Regeln von GitHub holen (ab 0.6.5).

Auf GitHub (öffentliches Projekt do2ggh/GoGoHam-rules) liegt je Contest eine
Regel-Datei und ein Inhaltsverzeichnis ``index.json``::

    {"format": 1,
     "rules": [{"id": "cqww-ssb", "file": "cqww-ssb.json", "revision": 1,
                "rules_checked": "2026-11", "sha256": "…"}, …]}

GoGoHam lädt zuerst nur das Inhaltsverzeichnis und danach nur Dateien, die neu
sind oder eine höhere Revision haben als das, was schon da ist. Jede Datei wird
geprüft (Prüfsumme, Regel-Prüfung, id, Format-Version), bevor sie gespeichert
wird. Gespeichert wird in ~/.local/share/gogoham/rules/download/. Ohne Internet
passiert nichts – GoGoHam nimmt dann einfach, was schon da ist.

Es wird nur gelesen (HTTP GET), es werden keine Daten über den Nutzer verschickt.
"""

from __future__ import annotations

from .i18n import tr

import hashlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__, rulefiles

BASE_URL = "https://raw.githubusercontent.com/do2ggh/GoGoHam-rules/main/"
INDEX_FORMAT = 1


@dataclass
class UpdateResult:
    new: list[str] = field(default_factory=list)          # Namen neuer Contests
    updated: list[str] = field(default_factory=list)      # Namen geänderter Contests
    skipped: list[str] = field(default_factory=list)      # brauchen neuere GoGoHam-Version
    removed: list[str] = field(default_factory=list)      # nicht mehr im Regel-Projekt (0.10.41.1)
    errors: list[str] = field(default_factory=list)
    offline: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.new or self.updated or self.removed)

    def summary(self) -> str:
        if self.offline:
            return tr("Contest-Regeln: kein Internet – es gelten die vorhandenen Regeln")
        parts = []
        if self.new:
            parts.append(tr("neu: ") + ", ".join(self.new))
        if self.updated:
            parts.append(tr("aktualisiert: ") + ", ".join(self.updated))
        if self.removed:
            parts.append(tr("entfernt: ") + ", ".join(self.removed))
        if self.skipped:
            parts.append(tr("brauchen neueres GoGoHam: ") + ", ".join(self.skipped))
        if self.errors:
            parts.append(tr("Fehler: ") + "; ".join(self.errors))
        return tr("Contest-Regeln ") + (" · ".join(parts) if parts else tr("sind aktuell"))


def _get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"GoGoHam/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (feste Adresse)
        return r.read(2_000_000)


def check_and_download(base_url: str | None = None, data_dir: Path | None = None,
                       timeout: float = 5.0) -> UpdateResult:
    base_url = base_url or BASE_URL
    res = UpdateResult()
    try:
        raw = _get(base_url + "index.json", timeout)
    except urllib.error.HTTPError as ex:
        res.errors.append(tr("Inhaltsverzeichnis auf GitHub nicht gefunden (HTTP {code})", code=ex.code))
        return res
    except (urllib.error.URLError, OSError, TimeoutError):
        res.offline = True
        return res
    try:
        index = json.loads(raw)
        entries = index["rules"]
        if int(index.get("format", 1)) > INDEX_FORMAT:
            res.errors.append(tr("Inhaltsverzeichnis braucht eine neuere GoGoHam-Version"))
            return res
    except (ValueError, KeyError, TypeError):
        res.errors.append(tr("Inhaltsverzeichnis auf GitHub ist fehlerhaft"))
        return res

    current = rulefiles.load_all(data_dir=data_dir).rules
    ddir = (data_dir if data_dir is not None else rulefiles.user_dir()) / "download"
    for e in entries:
        try:
            cid, fname, rev = e["id"], e["file"], int(e.get("revision", 1))
        except (KeyError, TypeError, ValueError):
            res.errors.append(tr("Eintrag im Inhaltsverzeichnis unvollständig"))
            continue
        if "/" in fname or "\\" in fname or not fname.endswith(".json"):
            res.errors.append(tr("ungültiger Dateiname {fname!r}", fname=fname))
            continue
        have = current.get(cid)
        if have is not None and have.source != "user" and have.revision >= rev:
            continue                                   # schon aktuell
        if have is not None and have.source == "user":
            continue                                   # eigene Datei hat Vorrang
        try:
            body = _get(base_url + fname, timeout)
        except (urllib.error.URLError, OSError, TimeoutError) as ex:
            res.errors.append(f"{fname}: {ex}")
            continue
        if e.get("sha256") and hashlib.sha256(body).hexdigest() != e["sha256"]:
            res.errors.append(tr("{fname}: Prüfsumme stimmt nicht", fname=fname))
            continue
        try:
            d = json.loads(body)
        except ValueError:
            res.errors.append(tr("{fname}: kein gültiges JSON", fname=fname))
            continue
        if isinstance(d, dict) and isinstance(d.get("format"), int) \
                and d["format"] > rulefiles.FORMAT_VERSION:
            res.skipped.append(d.get("name", cid))
            continue
        errs = rulefiles.validate(d)
        if errs or d.get("id") != cid or rulefiles.revision(d) != rev:
            res.errors.append(f"{fname}: " + (errs[0] if errs else tr("id/Revision passt nicht")))
            continue
        ddir.mkdir(parents=True, exist_ok=True)
        tmp = ddir / (fname + ".tmp")
        tmp.write_bytes(body)
        os.replace(tmp, ddir / fname)
        (res.updated if have is not None else res.new).append(d["name"])
    _remove_dropped(entries, ddir, res)
    return res


def _remove_dropped(entries, ddir: Path, res: UpdateResult) -> None:
    """Heruntergeladene Contests, die das Regel-Projekt nicht mehr führt, löschen (z. B. REF in
    0.10.41.1). Nur im Download-Ordner – eigene Regeln bleiben immer. Leeres Verzeichnis = nichts
    löschen (lieber ein Contest zu viel als alle weg)."""
    ids = {e.get("id") for e in entries if isinstance(e, dict)}
    if not ids or not ddir.is_dir():
        return
    for p in sorted(ddir.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            cid = d.get("id")
        except (OSError, ValueError, AttributeError):
            continue
        if cid and cid not in ids:
            try:
                p.unlink()
            except OSError:
                continue
            res.removed.append(d.get("name") or cid)


def make_index(rules_dir: Path) -> dict:
    """Inhaltsverzeichnis für GitHub erzeugen (für den Upload, siehe tools/)."""
    out = []
    for p in sorted(Path(rules_dir).glob("*.json")):
        if p.name == "index.json":
            continue
        body = p.read_bytes()
        d = json.loads(body)
        errs = rulefiles.validate(d)
        if errs:
            raise ValueError(f"{p.name}: {errs}")
        out.append({"id": d["id"], "file": p.name, "name": d["name"],
                    "revision": rulefiles.revision(d),
                    "rules_checked": d.get("rules_checked", ""),
                    "format": d["format"],
                    "sha256": hashlib.sha256(body).hexdigest()})
    return {"format": INDEX_FORMAT, "rules": out}
