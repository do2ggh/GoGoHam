"""Fertige Pakete direkt beim Entwickler auf SourceForge holen (ab 0.10.13 WS; JTDX war 0.10.16 kurz dabei).

WS („WS – Digital Mode Suite“, früher WSJT-X Improved, von Uwe Risse DG2YCB) gibt es nicht in
den Paketquellen von Debian, Ubuntu oder Fedora. DG2YCB bietet aber fertige Pakete auf
SourceForge an: `.deb` (Debian/Ubuntu) und `.rpm` (Fedora/openSUSE), immer in der neuesten
Version. Arch/Garuda: AUR-Paket `wsjtx-improved` (wird auf dem Rechner gebaut).

Die neueste Version steht im RSS-Feed des Projekts, mit MD5-Prüfsumme je Datei. Genommen wird
das normale Paket – nicht die Varianten „AL“, „widescreen“ oder „boost1.74“ (ältere Systeme).
"""

from __future__ import annotations

import hashlib
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

FEED = "https://sourceforge.net/projects/wsjt-x-improved/rss?path=/"
PAGE = "https://sourceforge.net/projects/wsjt-x-improved/"
AUR_PACKAGE = "wsjtx-improved"
AGENT = "GoGoHam"

# Gruppen: f = Ordner-Version, v = Version, b = Build 
_DEB = re.compile(r"/files/WS_v(?P<f>[\d.]+)/Linux/ws_(?P<v>[\d.]+)_(?P<b>\d+)_amd64\.deb/download$")
_RPM = re.compile(r"/files/WS_v(?P<f>[\d.]+)/Linux/ws-(?P<v>[\d.]+)_(?P<b>\d+)\.x86_64\.rpm/download$")
# ältere Systeme (Debian 12, Ubuntu 22.04 …): Boost 1.74 – bei DG2YCB nur als „AL“-Oberfläche
_DEB_OLD = re.compile(r"/files/WS_v(?P<f>[\d.]+)/Linux/ws_(?P<v>[\d.]+)_AL_(?P<b>\d+)_boost1\.74"
                      r"_amd64\.deb/download$")


@dataclass(frozen=True)
class Project:
    """Ein Programm, dessen fertige Pakete auf SourceForge liegen (WS)."""
    feed: str
    page: str
    aur: str                    # Paket im AUR (Arch/Garuda)
    patterns: tuple             # (Art, Muster) – Art "deb", "rpm", "deb-old"


PROJECTS = {
    "ws": Project(FEED, PAGE, AUR_PACKAGE, (("deb", _DEB), ("rpm", _RPM), ("deb-old", _DEB_OLD))),
}


@dataclass
class Package:
    version: str           # „3.2.1“
    build: str             # „261010“ („0“, wenn es keinen gibt)
    url: str
    md5: str
    kind: str              # "deb", "deb-old" oder "rpm"

    @property
    def filename(self) -> str:
        return self.url.rstrip("/").split("/")[-2] if self.url.endswith("/download") \
            else self.url.rstrip("/").split("/")[-1]


def _vkey(v: str, build: str) -> tuple:
    return tuple(int(x) for x in v.split(".") if x.isdigit()) + (int(build or 0),)


def parse_feed(text: str, project: str = "ws") -> dict[str, Package]:
    """Neueste Pakete je Art aus dem RSS-Feed – {"deb": …, "rpm": …} (fehlt = nichts da)."""
    best: dict[str, Package] = {}
    pats = PROJECTS[project].patterns
    for item in re.findall(r"<item>(.*?)</item>", text, re.S):
        m_link = re.search(r"<link>([^<]+)</link>", item)
        if not m_link:
            continue
        link = m_link.group(1).strip()
        m_md5 = re.search(r'<media:hash algo="md5">\s*([0-9a-fA-F]{32})', item)
        for kind, rx in pats:
            m = rx.search(link)
            if not m or m.group("f") != m.group("v") or not m_md5:
                continue
            build = (m.groupdict().get("b") or "0")
            p = Package(m.group("v"), build, link, m_md5.group(1).lower(), kind)
            cur = best.get(kind)
            if cur is None or _vkey(p.version, p.build) > _vkey(cur.version, cur.build):
                best[kind] = p
    return best


def fetch_feed(timeout: float = 20, project: str = "ws") -> str:
    req = urllib.request.Request(PROJECTS[project].feed, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 – feste https-Adresse
        return r.read().decode("utf-8", "replace")


def latest(kind: str, fetch=None, project: str = "ws") -> Package | None:
    """Neuestes Paket der Art ("deb"/"rpm"/"deb-old") – None ohne Internet oder ohne Datei."""
    try:
        text = fetch() if fetch else fetch_feed(project=project)
        return parse_feed(text, project).get(kind)
    except Exception:  # noqa: BLE001 – kein Internet, Seite geändert …
        return None


def download(pkg: Package, folder: Path, progress=None, opener=urllib.request.urlopen,
             timeout: float = 60) -> Path:
    """Paket laden und Prüfsumme prüfen; ValueError bei falscher Prüfsumme (Datei wird gelöscht).
    progress(geladen, gesamt) wird zwischendurch aufgerufen."""
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / pkg.filename
    part = dest.with_name(dest.name + ".part")
    md5 = hashlib.md5()                                   # noqa: S324 – Vergleich mit Anbieterwert
    req = urllib.request.Request(pkg.url, headers={"User-Agent": AGENT})
    with opener(req, timeout=timeout) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0) if getattr(r, "headers", None) else 0
        done = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            md5.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if md5.hexdigest() != pkg.md5:
        part.unlink(missing_ok=True)
        raise ValueError("md5")
    part.replace(dest)
    return dest


# 0.10.47.4: Pakete aus Debian/Ubuntu, die dieselben Dateien wie „ws“ vom Entwickler mitbringen
# (z. B. /usr/bin/cablog) – sonst bricht dpkg ab („trying to overwrite …“).
REPLACE_DEBS = ("wsjtx-improved", "wsjtx-improved-data", "wsjtx-improved-doc")  # dasselbe, älter
CONFLICT_DEBS = ("wsjtx", "wsjtx-data", "wsjtx-doc")       # WSJT-X: nur nach Rückfrage entfernen


def installed_debs(names: tuple[str, ...], run=None) -> list[str]:
    """Welche dieser Debian-Pakete sind installiert? (dpkg-query; ohne dpkg: keins)"""
    if run is None:
        from .extapps import _run as run
    _code, out = run(["dpkg-query", "-W", "-f=${Package} ${Status}\n", *names], 10)
    found = set()
    for line in (out or "").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[-1] == "installed" and parts[-2] == "ok":
            found.add(parts[0].split(":")[0])
    return [n for n in names if n in found]


def install_shell(path: Path, pm: str, remove: tuple[str, ...] | list[str] = ()) -> str | None:
    """Befehl (für pkexec sh -c) zum Installieren der geladenen Datei – zieht fehlende
    Bibliotheken aus den Paketquellen mit. remove (nur apt): Pakete, die im selben Schritt
    entfernt werden („name-“) – geht etwas schief, bleibt alles, wie es war."""
    q = "'" + str(path).replace("'", "'\\''") + "'"
    if pm == "apt-get":
        rm = "".join(f" {n}-" for n in remove if re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", n))
        return f"apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y {q}{rm}"
    if pm == "dnf":
        return f"dnf install -y {q}"
    if pm == "zypper":
        return f"zypper --non-interactive install --allow-unsigned-rpm {q}"
    return None


def kind_for(pm: str) -> str:
    return {"apt-get": "deb", "dnf": "rpm", "zypper": "rpm"}.get(pm, "")


def old_debian(run) -> bool:
    """Älteres Debian/Ubuntu (Boost 1.74 statt 1.83: Debian 12, Ubuntu 22.04, Mint 21 …)?"""
    new = run(["apt-cache", "show", "libboost-log1.83.0"], 30)
    if new[0] == 0 and new[1].strip():
        return False
    old = run(["apt-cache", "show", "libboost-log1.74.0"], 30)
    return old[0] == 0 and bool(old[1].strip())


def aur_helper(which) -> str:
    for h in ("paru", "yay"):
        if which(h):
            return h
    return ""


def terminal_command(cmd: list[str], which) -> list[str] | None:
    """Befehl in einem sichtbaren Konsolenfenster, das erst nach dem Ende zurückkehrt
    (das AUR-Paket wird gebaut – das dauert und fragt nach dem Passwort)."""
    if which("konsole"):
        return ["konsole", "--nofork", "-e"] + cmd
    if which("gnome-terminal"):
        return ["gnome-terminal", "--wait", "--"] + cmd
    if which("xfce4-terminal"):
        return ["xfce4-terminal", "--disable-server", "-x"] + cmd
    if which("xterm"):
        return ["xterm", "-e"] + cmd
    return None
