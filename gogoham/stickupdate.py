"""GoGoHam auf dem Live-Stick aktualisieren – per Knopf, ohne neues Stick-Abbild (ab 0.10.24).

So geht es:
1. apt fragt nur die GoGoHam-Paketquelle (OBS) ab – mit eigener Quellen-Datei und eigenen
   Ordnern unter ~/.cache, ohne Admin-Rechte und ohne die Paketverwaltung des Systems
   anzufassen. apt prüft dabei wie immer die Unterschrift der Quelle (Schlüssel in
   gogoham/assets/gogoham-obs.asc) und die Prüfsumme des Pakets.
2. Das Paket wird nur ausgepackt (dpkg-deb -x); das Programm landet im Update-Ordner
   ~/.local/share/gogoham/stick-update/<Version>/ – auf dem Stick liegt das im Datenteil und
   bleibt über Neustarts erhalten.
3. Beim Start nimmt GoGoHam die neuere der beiden Fassungen: die aus dem Stick-Abbild oder
   die aus dem Update-Ordner (switch_if_newer). Ein späteres neueres Abbild gewinnt also von
   selbst; ältere Updates werden dann weggeräumt.

Braucht eine neue Version Systempakete, die auf dem Stick fehlen, wird nichts eingespielt –
dann ist ein neues Stick-Abbild nötig.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .i18n import tr
from .versioncheck import parse

OBS_URL = "https://download.opensuse.org/repositories/home:/Franz/Debian_{rel}/"
KEY_FILE = Path(__file__).parent / "assets" / "gogoham-obs.asc"
ENV_ACTIVE = "GOGOHAM_STICK_UPDATE"      # gesetzt, wenn die Update-Fassung läuft
ENV_OFF = "GOGOHAM_NO_STICK_UPDATE"     # Notweg: immer die Fassung aus dem Abbild starten
KEEP = 1                                # nur die neueste Aktualisierung bleibt liegen – der
                                        # Rückweg ist die Fassung aus dem Stick-Abbild


def update_root() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "gogoham" / "stick-update"


def apt_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "gogoham" / "apt"


def debian_release(os_release: str | None = None) -> str | None:
    """„13“ auf Debian 13 (trixie), sonst None (kein Debian → kein Stick-Update)."""
    if os_release is None:
        try:
            os_release = Path("/etc/os-release").read_text(encoding="utf-8")
        except OSError:
            return None
    vals = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', os_release, re.M))
    if vals.get("ID") != "debian":
        return None
    rel = vals.get("VERSION_ID", "")
    return rel if rel.isdigit() else None


def upstream(deb_version: str) -> str:
    """Debian-Version „0.10.24-1.1“ → „0.10.24“."""
    v = (deb_version or "").split(":")[-1]
    return v.rsplit("-", 1)[0] if "-" in v else v


def newer(a: str, b: str) -> bool:
    """Ist Version a neuer als b? (ungültige Angaben: nein)"""
    pa, pb = parse(a), parse(b)
    return bool(pa and pb and pa > pb)


# ------------------------------------------------------------------ Update-Ordner
def installed_updates(root: Path | None = None) -> list[str]:
    """Versionen im Update-Ordner, neueste zuerst (nur vollständige: mit gogoham/__init__.py)."""
    root = root or update_root()
    out = []
    if root.is_dir():
        for d in root.iterdir():
            if d.is_dir() and parse(d.name) and (d / "gogoham" / "__init__.py").is_file():
                out.append(d.name)
    return sorted(out, key=lambda v: parse(v), reverse=True)


def active_update(root: Path | None = None, base: str = __version__) -> str | None:
    """Neueste Update-Fassung, die neuer ist als base (sonst None)."""
    for v in installed_updates(root):
        if newer(v, base):
            return v
    return None


def cleanup(root: Path | None = None, base: str = __version__, keep: int = KEEP,
            protect: str | None = None) -> list[str]:
    """Update-Fassungen wegräumen, die nicht neuer als base sind, und alle bis auf die
    neuesten keep. protect = die gerade laufende Fassung – bleibt bis zum nächsten Start
    liegen (sonst fehlen ihr Dateien). Gibt die entfernten Versionen zurück."""
    root = root or update_root()
    gone = []
    for i, v in enumerate(installed_updates(root)):
        if v == protect:
            continue
        if not newer(v, base) or i >= keep:
            shutil.rmtree(root / v, ignore_errors=True)
            gone.append(v)
    for d in root.glob(".neu-*") if root.is_dir() else ():
        shutil.rmtree(d, ignore_errors=True)         # abgebrochene Downloads
    return gone


BACK_MARK = ".zurueck"                  # „Zurück zur Fassung des Sticks“ beim nächsten Start


def remove_all(root: Path | None = None, protect: str | None = None) -> None:
    """„Zurück zur Fassung des Sticks“: alle Updates löschen. Läuft gerade eine davon
    (protect), bleibt sie bis zum nächsten Start liegen und wird dann gelöscht."""
    root = root or update_root()
    if not protect:
        shutil.rmtree(root, ignore_errors=True)
        return
    for v in installed_updates(root):
        if v != protect:
            shutil.rmtree(root / v, ignore_errors=True)
    (root / BACK_MARK).touch()


def switch_if_newer(argv: list[str] | None = None, root: Path | None = None,
                    execv=os.execv) -> bool:
    """Beim Start: liegt im Update-Ordner eine neuere Fassung, diese starten (ersetzt den
    laufenden Prozess). Nur auf dem Live-Stick, nicht, wenn sie schon läuft. False = weiter
    mit dieser Fassung."""
    from . import livestick
    if os.environ.get(ENV_ACTIVE) or os.environ.get(ENV_OFF) or not livestick.is_live():
        return False
    root = root or update_root()
    try:
        if (root / BACK_MARK).exists():            # „Zurück zur Fassung des Sticks“ gewählt
            remove_all(root)
            return False
        cleanup(root)                              # ein neueres Abbild macht alte Updates überflüssig
        v = active_update(root)
    except OSError:
        return False
    if not v:
        return False
    env = os.environ
    env[ENV_ACTIVE] = v
    env["PYTHONPATH"] = os.pathsep.join(x for x in (str(root / v), env.get("PYTHONPATH")) if x)
    args = [sys.executable, "-m", "gogoham", *(sys.argv[1:] if argv is None else argv)]
    execv(sys.executable, args)
    return True                                    # nur im Test (execv ersetzt sonst alles)


def clean_env(env=None, root: Path | None = None) -> None:
    """Vor einem Neustart: Spuren der laufenden Update-Fassung entfernen, damit der Start
    wieder frei die neueste Fassung wählt."""
    env = os.environ if env is None else env
    root = str(root or update_root())
    env.pop(ENV_ACTIVE, None)
    parts = [x for x in env.get("PYTHONPATH", "").split(os.pathsep) if x and not x.startswith(root)]
    if parts:
        env["PYTHONPATH"] = os.pathsep.join(parts)
    else:
        env.pop("PYTHONPATH", None)


# ------------------------------------------------------------------ apt
def _apt_opts(root: Path, sources: Path) -> list[str]:
    return ["-o", f"Dir::Etc::sourcelist={sources}",
            "-o", f"Dir::Etc::sourceparts={root / 'leer'}",
            "-o", f"Dir::State::Lists={root / 'lists'}",
            "-o", f"Dir::Cache={root / 'cache'}",
            "-o", "Dir::Etc::preferencesparts=" + str(root / "leer"),
            "-o", "APT::Get::List-Cleanup=0",
            "-o", "Debug::NoLocking=1"]


def prepare_apt(rel: str, root: Path | None = None, key: Path | None = None,
                url: str | None = None) -> tuple[Path, list[str]]:
    """Ordner und Quellen-Datei für apt anlegen. Gibt (Ordner, apt-Optionen) zurück."""
    root = root or apt_root()
    for d in ("leer", "lists/partial", "cache/archives/partial"):
        (root / d).mkdir(parents=True, exist_ok=True)
    k = root / "gogoham-obs.asc"
    shutil.copyfile(key or KEY_FILE, k)
    sources = root / "gogoham.list"
    sources.write_text(f"deb [signed-by={k}] {url or OBS_URL.format(rel=rel)} /\n",
                       encoding="utf-8")
    return root, _apt_opts(root, sources)


def candidate(madison: str) -> str | None:
    """Neueste Version aus „apt-cache madison gogoham“ (Debian-Schreibweise)."""
    best, best_v = None, None
    for line in madison.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3 and parts[0] == "gogoham" and "Packages" in parts[2]:
            v = parse(upstream(parts[1]))
            if v and (best_v is None or v > best_v):
                best, best_v = parts[1], v
    return best


def missing_depends(depends: str, installed) -> list[str]:
    """Abhängigkeiten aus „Depends:“, die fehlen. Bei „a | b“ reicht eine; Versionsangaben
    in Klammern werden nicht geprüft (das Abbild bringt aktuelle Pakete mit)."""
    out = []
    for item in (depends or "").split(","):
        alts = [re.sub(r"\(.*?\)|:\w+", "", a).strip() for a in item.split("|")]
        alts = [a for a in alts if a]
        if alts and not any(installed(a) for a in alts):
            out.append(" | ".join(alts))
    return out


def dpkg_installed(name: str) -> bool:
    r = subprocess.run(["dpkg-query", "-W", "-f=${Status}", name], capture_output=True,
                       text=True)
    return r.returncode == 0 and "install ok installed" in r.stdout


@dataclass
class Result:
    ok: bool = False
    version: str = ""                 # Programmversion (ohne Debian-Zusatz)
    message: str = ""
    log: list[str] = field(default_factory=list)


def check(run=subprocess.run, rel: str | None = None, apt_dir: Path | None = None,
          url: str | None = None) -> Result:
    """Paketquelle abfragen: gibt es eine neuere Version als die laufende?"""
    res = Result()
    rel = rel or debian_release()
    if not rel:
        res.message = tr("Das Aktualisieren per Knopf gibt es nur auf dem GoGoHam-Stick (Debian).")
        return res
    root, opts = prepare_apt(rel, apt_dir, url=url)
    r = run(["apt-get", *opts, "update"], capture_output=True, text=True)
    res.log.append((r.stdout or "") + (r.stderr or ""))
    out = (r.stdout or "") + (r.stderr or "")
    if re.search(r"NO_PUBKEY|not signed|BADSIG|Signature|signiert|Signatur", out):
        res.message = tr("Die GoGoHam-Paketquelle ist nicht richtig unterschrieben – aus "
                         "Sicherheitsgründen wird nichts geladen.")
        return res
    if r.returncode != 0 or re.search(r"^(E|Err):", out, re.M):
        res.message = tr("Die GoGoHam-Paketquelle ist nicht erreichbar (kein Internet oder "
                         "noch keine veröffentlichte Version).")
        return res
    m = run(["apt-cache", *opts, "madison", "gogoham"], capture_output=True, text=True)
    deb = candidate(m.stdout or "")
    if not deb:
        res.message = tr("In der Paketquelle ist noch keine GoGoHam-Version.")
        return res
    res.version = upstream(deb)
    res.ok = True
    return res


def install(deb_version: str | None = None, run=subprocess.run, rel: str | None = None,
            apt_dir: Path | None = None, root: Path | None = None, installed=dpkg_installed,
            url: str | None = None, progress=lambda text: None) -> Result:
    """Neueste (oder die genannte) Version holen und in den Update-Ordner auspacken."""
    progress(tr("Paketquelle wird abgefragt …"))
    res = check(run=run, rel=rel, apt_dir=apt_dir, url=url)
    if not res.ok:
        return res
    ok = res
    res = Result(version=ok.version, log=ok.log)
    if not newer(res.version, __version__):
        res.ok = True
        res.message = tr("Du hast schon die neueste Version ({v}).", v=__version__)
        return res
    root = root or update_root()
    if res.version in installed_updates(root):
        res.ok = True
        res.message = tr("GoGoHam {v} ist schon eingespielt – es startet nach einem Neustart "
                         "von GoGoHam.", v=res.version)
        return res
    root.mkdir(parents=True, exist_ok=True)
    (root / BACK_MARK).unlink(missing_ok=True)     # wieder aktualisiert: Zurück-Wunsch gilt nicht mehr
    rel = rel or debian_release()
    aroot, opts = prepare_apt(rel, apt_dir, url=url)
    progress(tr("GoGoHam {v} wird heruntergeladen …", v=res.version))
    with tempfile.TemporaryDirectory(dir=root, prefix=".neu-") as tmp:
        t = Path(tmp)
        r = run(["apt-get", *opts, "download", "gogoham"], capture_output=True, text=True,
                cwd=t)
        res.log.append((r.stdout or "") + (r.stderr or ""))
        debs = sorted(t.glob("gogoham_*.deb"))
        if r.returncode != 0 or not debs:
            res.message = tr("Das Herunterladen hat nicht geklappt – bitte später noch einmal "
                             "versuchen.")
            return res
        deb = debs[-1]
        progress(tr("Paket wird geprüft …"))
        f = run(["dpkg-deb", "-f", str(deb), "Depends"], capture_output=True, text=True)
        miss = missing_depends(f.stdout or "", installed)
        if miss:
            res.message = tr("GoGoHam {v} braucht Programme, die auf diesem Stick fehlen ({m}). "
                             "Dafür ist ein neues Stick-Abbild nötig.", v=res.version,
                             m=", ".join(miss))
            return res
        x = t / "x"
        e = run(["dpkg-deb", "-x", str(deb), str(x)], capture_output=True, text=True)
        pkgs = list(x.glob("usr/lib/python3*/dist-packages/gogoham"))
        if e.returncode != 0 or not pkgs or not (pkgs[0] / "__init__.py").is_file():
            res.message = tr("Das Paket ist unvollständig – nichts wurde verändert.")
            return res
        got = re.search(r'__version__\s*=\s*"([^"]+)"',
                        (pkgs[0] / "__init__.py").read_text(encoding="utf-8"))
        if not got or got.group(1) != res.version:
            res.message = tr("Die Version im Paket passt nicht – nichts wurde verändert.")
            return res
        progress(tr("GoGoHam {v} wird eingerichtet …", v=res.version))
        target = root / res.version
        stage = t / "fertig"
        stage.mkdir()
        shutil.move(str(pkgs[0]), str(stage / "gogoham"))
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(stage), str(target))
    cleanup(root, protect=os.environ.get(ENV_ACTIVE))
    res.ok = True
    res.message = tr("GoGoHam {v} ist eingespielt. Es startet nach einem Neustart von GoGoHam.",
                     v=res.version)
    return res
