"""GoGoHam aktualisieren per Knopf – für die Installation mit install.sh (ab 0.10.47).

Ablauf (Hilfe → „Nach neuer Version suchen …“):

1. **Vorbereiten** (läuft im Hintergrund, GoGoHam bleibt benutzbar): Quelltext der neuesten
   Versionsmarke von GitHub holen (nur github.com über HTTPS), sicher entpacken
   (``filter="data"``), prüfen, dass wirklich diese Version drin ist, und einmal **zur Probe
   laden** (eigener Prozess, ohne Fenster) – fehlt dem Rechner etwas, das die neue Version
   braucht, wird abgebrochen und es bleibt alles, wie es ist. Ergebnis liegt in
   ``~/.local/share/gogoham/update/<Version>/`` samt Merker ``pending.json``.
2. **Einspielen beim nächsten Start** (``apply_pending`` ganz am Anfang von ``__main__``, bevor
   irgendein anderer Programmteil geladen ist – das laufende Programm lädt so nie Teile der
   neuen Version nach): alter Ordner wird zu ``gogoham.prev``, der neue an seine Stelle.
   Startmenü-Eintrag, Symbole und uninstall.sh werden mit erneuert. Danach startet GoGoHam die
   neue Version.

„Zurück zur vorigen Version“ tauscht ``gogoham.prev`` genauso beim nächsten Start zurück.
Logs und Einstellungen liegen woanders und bleiben unberührt. Installiert werden keine
Systempakete (kein sudo) – braucht eine neue Version mehr, sagt die Probe das vorher.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .i18n import tr

REPO = "do2ggh/GoGoHam"
TARBALL = "https://github.com/{repo}/archive/refs/tags/v{v}.tar.gz"
MAX_BYTES = 80 * 1024 * 1024            # Quelltext ist ~10 MB – mehr ist verdächtig
PENDING = "pending.json"


@dataclass
class Result:
    ok: bool = False
    version: str = ""
    message: str = ""


# ------------------------------------------------------------------------------ Pfade
def data_root() -> Path:
    """Wie install.sh: immer ~/.local/share/gogoham (unabhängig von XDG_DATA_HOME)."""
    return Path.home() / ".local" / "share" / "gogoham"


def app_dir() -> Path:
    """Ordner, in den install.sh das Programm kopiert (enthält den Ordner ``gogoham``)."""
    return data_root() / "app"


def update_root() -> Path:
    return data_root() / "update"


def running_from(app: Path | None = None, module_file: str | None = None) -> bool:
    """Läuft GoGoHam gerade aus dem install.sh-Ordner? (Nur dann gibt es dieses Update.)"""
    here = Path(module_file or __file__).resolve().parent
    return here == (app or app_dir()).resolve() / "gogoham"


def has_previous(app: Path | None = None) -> bool:
    return ((app or app_dir()) / "gogoham.prev" / "__init__.py").is_file()


# ---------------------------------------------------------------------- Vorbereiten
def _version_in(pkg: Path) -> str:
    try:
        text = (pkg / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else ""


def download(version: str, dest: Path, opener=None, progress=None) -> Path:
    """Quelltext-Archiv der Versionsmarke laden (höchstens MAX_BYTES)."""
    url = TARBALL.format(repo=REPO, v=version)
    req = urllib.request.Request(url, headers={"User-Agent": f"GoGoHam/{__version__}"})
    opener = opener or (lambda r: urllib.request.urlopen(r, timeout=30))  # noqa: S310 (feste Adresse)
    dest.parent.mkdir(parents=True, exist_ok=True)
    got = 0
    with opener(req) as r, open(dest, "wb") as f:
        final = getattr(r, "geturl", lambda: url)()
        if not final.startswith(("https://github.com/", "https://codeload.github.com/")):
            raise OSError(tr("Unerwartete Download-Adresse: {u}", u=final))
        while chunk := r.read(256 * 1024):
            got += len(chunk)
            if got > MAX_BYTES:
                raise OSError(tr("Download zu groß – abgebrochen."))
            f.write(chunk)
            if progress:
                progress(tr("Lade GoGoHam {v} … {mb} MB", v=version, mb=f"{got / 1e6:.1f}"))
    return dest


def unpack(tgz: Path, into: Path) -> Path:
    """Sicher entpacken; gibt den Quelltext-Ordner zurück (der mit ``gogoham/`` drin)."""
    shutil.rmtree(into, ignore_errors=True)
    into.mkdir(parents=True)
    with tarfile.open(tgz) as t:
        t.extractall(into, filter="data")         # nichts außerhalb, keine Geräte/Verweise raus
    tops = [p for p in into.iterdir() if p.is_dir()]
    for top in tops:
        if (top / "gogoham" / "__init__.py").is_file():
            return top
    raise ValueError(tr("Im Archiv fehlt das Programm."))


PROBE = ("import os, sys; os.environ['QT_QPA_PLATFORM'] = 'offscreen'; "
         "sys.path.insert(0, sys.argv[1]); import gogoham.gui.main_window, gogoham.__main__; "
         "print('PROBE-OK')")


def probe(src: Path, run=subprocess.run) -> str:
    """Neue Version zur Probe laden (eigener Prozess, ohne Fenster). "" = in Ordnung, sonst
    die letzte Fehlerzeile (z. B. „No module named …“ – dann fehlt ein Systempaket)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["HOME"] = os.environ.get("HOME", "")
    try:
        r = run([sys.executable, "-I", "-c", PROBE, str(src)], capture_output=True, text=True,
                timeout=120, env=env, cwd=str(src))
    except (OSError, subprocess.TimeoutExpired) as e:
        return str(e)
    if r.returncode == 0 and "PROBE-OK" in (r.stdout or ""):
        return ""
    lines = [ln for ln in (r.stderr or r.stdout or "").strip().splitlines() if ln.strip()]
    return lines[-1] if lines else "?"


def prepare(version: str, opener=None, run=subprocess.run, root: Path | None = None,
            progress=None) -> Result:
    """Neue Version holen, prüfen und für den nächsten Start bereitlegen."""
    root = root or update_root()
    say = progress or (lambda _t: None)
    work = root / version
    try:
        shutil.rmtree(root, ignore_errors=True)          # alte, halbe Versuche weg
        say(tr("Lade GoGoHam {v} …", v=version))
        tgz = download(version, root / f"gogoham-{version}.tar.gz", opener, progress)
        say(tr("Entpacke …"))
        src = unpack(tgz, work)
        tgz.unlink()
        found = _version_in(src / "gogoham")
        if found != version:
            raise ValueError(tr("Im Archiv steckt Version „{f}“ statt {v}.", f=found or "?",
                                v=version))
        say(tr("Prüfe die neue Version …"))
        err = probe(src, run)
        if err:
            shutil.rmtree(root, ignore_errors=True)
            return Result(False, version, tr(
                "GoGoHam {v} lässt sich auf diesem Rechner noch nicht starten ({e}). Wahrscheinlich "
                "braucht es ein zusätzliches Systempaket – bitte die Installationsanleitung der "
                "neuen Version ansehen. Es bleibt alles, wie es ist.", v=version, e=err))
        (root / PENDING).write_text(json.dumps({"action": "install", "version": version,
                                                "src": str(src)}), encoding="utf-8")
    except (OSError, ValueError, tarfile.TarError) as e:
        shutil.rmtree(root, ignore_errors=True)
        return Result(False, version, tr("Aktualisieren fehlgeschlagen: {e}", e=e))
    return Result(True, version, tr("GoGoHam {v} ist bereit. Beim Neustart wird es eingespielt – "
                                    "Logs und Einstellungen bleiben erhalten.", v=version))


def request_rollback(root: Path | None = None) -> None:
    root = root or update_root()
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    (root / PENDING).write_text(json.dumps({"action": "rollback"}), encoding="utf-8")


def cancel(root: Path | None = None) -> None:
    shutil.rmtree(root or update_root(), ignore_errors=True)


def pending(root: Path | None = None) -> dict | None:
    try:
        d = json.loads(((root or update_root()) / PENDING).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get("action") in ("install", "rollback") else None


# ---------------------------------------------------------------------- Einspielen
def _refresh_desktop(src: Path, data: Path, home: Path | None = None) -> None:
    """Wie install.sh: Symbole, Startmenü-Eintrag, uninstall.sh (Fehler sind hier egal)."""
    home = home or Path.home()
    bindir = home / ".local" / "bin"
    for d in sorted((src / "data" / "icons" / "hicolor").glob("*/apps")):
        png = d / "gogoham.png"
        if png.is_file():
            out = data / "icons" / "hicolor" / d.parent.name / "apps" / "gogoham.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(png, out)
    desk = src / "data" / "gogoham.desktop"
    if desk.is_file():
        text = re.sub(r"^Exec=.*$", f"Exec={bindir / 'gogoham'}",
                      desk.read_text(encoding="utf-8"), flags=re.M)
        out = data / "applications" / "gogoham.desktop"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    meta = src / "data" / "io.github.do2ggh.GoGoHam.metainfo.xml"      # 0.10.47.1
    if meta.is_file():
        out = data / "metainfo" / meta.name
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(meta, out)
    un = src / "uninstall.sh"
    if un.is_file():
        out = home / ".local" / "share" / "gogoham" / "uninstall.sh"
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(un, out)
        os.chmod(out, 0o755)


def _swap(app: Path, new: Path) -> None:
    """``app/gogoham`` → ``gogoham.prev``, ``new`` → ``app/gogoham`` (je ein rename)."""
    cur, prev = app / "gogoham", app / "gogoham.prev"
    if cur.exists():
        shutil.rmtree(prev, ignore_errors=True)
        cur.rename(prev)
    new.rename(cur)


def apply_pending(app: Path | None = None, root: Path | None = None,
                  data: Path | None = None, home: Path | None = None) -> str:
    """Beim Start: vorbereitetes Update bzw. Zurück einspielen. Rückgabe: was passiert ist
    ("installed:<v>", "rolled-back", "" = nichts). Fehler lassen die alte Fassung stehen."""
    app, root = app or app_dir(), root or update_root()
    job = pending(root)
    if job is None or not (app / "gogoham").is_dir():
        return ""
    xdg = data or Path(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"))
    try:
        if job["action"] == "rollback":
            prev = app / "gogoham.prev"
            if not (prev / "__init__.py").is_file():
                return ""
            tmp = app / "gogoham.back"
            shutil.rmtree(tmp, ignore_errors=True)
            prev.rename(tmp)
            _swap(app, tmp)                        # aktuelle wird zur „vorigen“
            return "rolled-back"
        src = Path(job.get("src", ""))
        if _version_in(src / "gogoham") != job.get("version"):
            return ""
        staged = app / "gogoham.new"
        shutil.rmtree(staged, ignore_errors=True)
        shutil.copytree(src / "gogoham", staged, ignore=shutil.ignore_patterns("__pycache__"))
        _swap(app, staged)
        try:
            _refresh_desktop(src, xdg, home)
        except OSError:
            pass
        return f"installed:{job['version']}"
    except OSError:
        return ""
    finally:
        shutil.rmtree(root, ignore_errors=True)    # nie zweimal versuchen


def start_hook(argv: list[str] | None = None) -> None:
    """Aus ``__main__``: liegt etwas bereit, einspielen und das Programm frisch starten, damit
    nur noch Teile der neuen Fassung geladen werden."""
    if not running_from() or pending() is None:
        return
    if apply_pending():
        os.chdir(app_dir())
        os.execv(sys.executable, [sys.executable, "-m", "gogoham", *(argv or sys.argv[1:])])
