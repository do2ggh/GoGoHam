"""Gibt es eine neuere GoGoHam-Version? (ab 0.9.4)

Einmal am Tag beim Start fragt GoGoHam bei GitHub nach den Versionsmarken (v0.9.4 …) des
Projekts. Es wird nur gelesen; ohne Internet passiert nichts. Der Hinweis erscheint je
Version nur einmal und nicht, während der Contest des geöffneten Logs läuft.
"""

from __future__ import annotations

from .i18n import tr

import json
import os
import re
import threading
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from . import __version__

TAGS_URL = "https://api.github.com/repos/do2ggh/GoGoHam/tags?per_page=100"
RELEASES_PAGE = "https://github.com/do2ggh/GoGoHam/blob/main/CHANGELOG.md"

_VER = re.compile(r"v?(\d+(?:\.\d+){0,3})")


def parse(v: str) -> tuple[int, ...] | None:
    """„v0.9.4“ / „0.9.4“ -> (0, 9, 4); alles andere -> None."""
    m = _VER.fullmatch((v or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def is_newer(remote: str, local: str = __version__) -> bool:
    r, loc = parse(remote), parse(local)
    return bool(r and loc and r > loc)


def latest(timeout: float = 8.0, url: str | None = None) -> str:
    """Höchste Versionsmarke auf GitHub ("" wenn keine). Kein Internet -> OSError."""
    req = urllib.request.Request(url or TAGS_URL, headers={"User-Agent": f"GoGoHam/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (feste Adresse)
        data = json.loads(r.read().decode("utf-8"))
    best, best_v = "", None
    for tag in data if isinstance(data, list) else []:
        name = (tag or {}).get("name", "")
        v = parse(name)
        if v and (best_v is None or v > best_v):
            best, best_v = name.lstrip("v"), v
    return best


def install_kind(module_file: str | None = None) -> str:
    """Wie GoGoHam installiert ist: appimage, stick (GoGoHam-Live-Stick, ab 0.10.24),
    package (Paket der Distribution), script (install.sh) oder source (Quelltext-Ordner)."""
    if os.environ.get("APPIMAGE"):
        return "appimage"
    if module_file is None:
        from . import livestick
        if livestick.is_live():
            return "stick"
    p = str(Path(module_file or __file__).resolve())
    if p.startswith("/usr/"):
        return "package"
    if "/.local/share/gogoham/app/" in p:
        return "script"
    return "source"


def hint_text(version: str, kind: str | None = None) -> str:
    kind = kind or install_kind()
    head = tr("GoGoHam {v} ist erschienen (du hast {mine}).", v=version, mine=__version__)
    if kind in ("stick", "script"):
        how = tr("Zum Aktualisieren: Hilfe → „Nach neuer Version suchen …“ – ein Klick genügt.")
    elif kind == "package":
        how = tr("Sie kommt mit dem nächsten Systemupdate.")
    elif kind == "appimage":
        how = tr("Das neue Beta-AppImage bekommst du von DO2GGH.")
    else:
        how = tr("Neuen Quelltext holen und install.sh noch einmal ausführen.")
    return head + " " + how


def is_due(cfg: dict, today: date | None = None) -> bool:
    """Heute schon nachgesehen? (Häkchen aus = nie)"""
    if not cfg.get("version_check", True):
        return False
    return cfg.get("version_check_last", "") != (today or date.today()).isoformat()


def should_show(cfg: dict, version: str) -> bool:
    """Hinweis für diese Version noch nicht gezeigt und wirklich neuer?"""
    return bool(version) and is_newer(version) and cfg.get("version_hint_shown") != version


class VersionChecker(threading.Thread):
    """Fragt im Hintergrund; Ergebnis danach in .version ("" = nichts) bzw. .error."""

    def __init__(self, timeout: float = 8.0, url: str | None = None):
        super().__init__(daemon=True, name="version-check")
        self.timeout, self.url = timeout, url
        self.version = ""
        self.error = ""

    def run(self) -> None:  # noqa: D401 (Thread-Methode)
        try:
            self.version = latest(self.timeout, self.url)
        except (OSError, ValueError, urllib.error.URLError) as e:   # kein Internet usw.
            self.error = str(e) or type(e).__name__
        except Exception as e:  # noqa: BLE001 – darf GoGoHam nie stören
            self.error = str(e)
