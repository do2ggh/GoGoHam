"""GoGoHam läuft vom Live-Stick (ab 0.10.8).

Der Stick legt beim Bauen die Datei MARKER an (JSON). Nur wenn es sie gibt, zeigt GoGoHam den
Einstellungsbereich „USB-Stick“ und die Stick-Hinweise. Auf einem normal installierten PC
ändert sich nichts.

Inhalt von MARKER (alle Einträge freiwillig):
    "data":      Ordner des Datenteils (alles Geänderte liegt dort) – für die Platzanzeige
    "exchange":  Austausch-Ordner (auch unter Windows lesbar)
    "reset":     Hilfsprogramm, das den Datenteil beim nächsten Start leert und neu startet
                 (läuft über pkexec; der Stick erlaubt das ohne Passwort)
    "timezone":  Hilfsprogramm, das die Zeitzone stellt und die Uhr danach neu aus der
                 eingebauten Uhr liest – ohne diese zu verändern (ab 0.10.10, über pkexec)
    "copy":      Hilfsprogramm, das den laufenden Stick frisch auf einen anderen USB-Stick
                 schreibt (ab 0.10.20, über pkexec – siehe stickcopy.py)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .i18n import num, tr

MARKER = Path("/etc/gogoham/livestick.json")
BACKUP_FOLDER = "GoGoHam-Sicherung"
EXPORT_FOLDER = "Export"             # eigene Exporte (Cabrillo, ADIF, EDI) – ab 0.10.8.1
LOW_BYTES = 1024 ** 3            # unter 1 GB frei → warnen …
LOW_SHARE = 0.05                 # … oder unter 5 %


def info(marker: Path | None = None) -> dict | None:
    """Angaben des Sticks – None, wenn GoGoHam nicht vom Stick läuft."""
    p = Path(marker or MARKER)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else {}


def is_live(marker: Path | None = None) -> bool:
    return info(marker) is not None


def persistent(mounts: str | None = None) -> bool:
    """Speichert der Stick? (Datenteil GGH-DATEN von live-boot eingehängt – ab 0.10.22)"""
    if mounts is None:
        try:
            mounts = Path("/proc/mounts").read_text()
        except OSError:
            return True                  # unklar: lieber nicht warnen
    return any(len(f) > 1 and f[1].startswith("/run/live/persistence/")
               for f in (line.split() for line in mounts.splitlines()))


def _dir(key: str, marker: Path | None = None) -> Path | None:
    d = (info(marker) or {}).get(key)
    if not d:
        return None
    p = Path(d)
    return p if p.is_dir() else None


def data_dir(marker: Path | None = None) -> Path | None:
    return _dir("data", marker)


def exchange_dir(marker: Path | None = None) -> Path | None:
    return _dir("exchange", marker)


def export_path(log_path: str | Path, suffix: str, marker: Path | None = None) -> Path | None:
    """Vorschlag zum Speichern eines Exports: Austausch-Ordner/Export/<Log>.<suffix>.
    None, wenn GoGoHam nicht vom Stick läuft oder der Ordner nicht angelegt werden kann."""
    exch = exchange_dir(marker)
    if exch is None:
        return None
    target = exch / EXPORT_FOLDER
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return target / Path(log_path).with_suffix(suffix).name


def _backup_readme(target: Path) -> None:
    """Kurze Erklärung im Sicherungsordner (einmal anlegen, nie überschreiben)."""
    readme = target / tr("LIESMICH.txt")
    if readme.exists():
        return
    readme.write_text(tr(
        "Automatische Sicherung von GoGoHam – bitte hier nichts ändern.\n\n"
        "Wiederherstellen: eine .ggh-Datei in GoGoHam öffnen (Log & Contest → „Log öffnen …“).\n"
        "Die .adi-Dateien (ADIF) lassen sich in jedes Log-Programm einlesen.\n\n"
        "Eigene Exporte (Cabrillo, ADIF, EDI) liegen im Ordner „{folder}“.",
        folder=EXPORT_FOLDER) + "\n", encoding="utf-8")


def space(path: Path | None) -> tuple[int, int] | None:
    """(frei, gesamt) in Bytes – None, wenn der Ordner fehlt."""
    if path is None:
        return None
    try:
        u = shutil.disk_usage(path)
    except OSError:
        return None
    return u.free, u.total


def is_low(free: int, total: int) -> bool:
    return free < LOW_BYTES or (total > 0 and free / total < LOW_SHARE)


def size_text(n: int) -> str:
    gb = n / 1024 ** 3
    if gb >= 1:
        return tr("{n} GB", n=num(gb, 1))
    return tr("{n} MB", n=num(n / 1024 ** 2))


def space_text(sp: tuple[int, int] | None) -> str:
    if sp is None:
        return tr("unbekannt")
    free, total = sp
    return tr("{free} frei von {total}", free=size_text(free), total=size_text(total))


# ------------------------------------------------------------------ Befehle
def reset_command(marker: Path | None = None, which=shutil.which) -> list[str] | None:
    """Zurücksetzen (Hilfsprogramm des Sticks über pkexec) – None, wenn das nicht geht."""
    helper = (info(marker) or {}).get("reset")
    if not helper or not Path(helper).is_file() or not which("pkexec"):
        return None
    return ["pkexec", str(helper)]


def poweroff_command(which=shutil.which) -> list[str] | None:
    return ["systemctl", "poweroff"] if which("systemctl") else None


def set_time_command(utc_epoch: float, which=shutil.which) -> list[str] | None:
    """Systemuhr auf eine UTC-Zeit stellen. Die eingebaute Uhr des Rechners bleibt
    unangetastet – der Rechner gehört ja oft jemand anderem."""
    if not which("pkexec") or not which("date"):
        return None
    return ["pkexec", "date", "-u", "-s", f"@{int(utc_epoch)}"]


def timezone_command(zone: str, marker: Path | None = None,
                     which=shutil.which) -> list[str] | None:
    """Zeitzone des Sticks stellen (ab 0.10.10) – None, wenn das hier nicht geht."""
    helper = (info(marker) or {}).get("timezone")
    if not helper or not Path(helper).is_file() or not which("pkexec"):
        return None
    if not zone or ".." in zone or not all(c.isalnum() or c in "/_+-" for c in zone):
        return None
    return ["pkexec", helper, zone]


def clock_synced(run=subprocess.run) -> bool | None:
    """Hat Linux die Uhr mit einem Zeitserver abgeglichen? None = nicht feststellbar.
    Der Stick nimmt chrony (schreibt nie in die eingebaute Uhr des fremden Rechners); chrony
    meldet den Abgleich nicht über timedatectl – deshalb zuerst chronyc fragen."""
    try:
        r = run(["chronyc", "-n", "tracking"], capture_output=True, text=True, timeout=5)
        out = r.stdout or ""
        if getattr(r, "returncode", 1) == 0 and "Leap status" in out:
            return "Not synchronised" not in out and "Reference ID    : 00000000" not in out
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        r = run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    v = (r.stdout or "").strip().lower()
    return True if v == "yes" else False if v == "no" else None


# ------------------------------------------------------------------ Sicherung
def backup_to_exchange(exchange: Path, log_path: str | Path, adif_text: str,
                       backup_file: Path | None = None) -> Path:
    """Kopie des Logs in den Austausch-Ordner: ADIF (für jedes Programm, auch unter Windows)
    und – wenn vorhanden – die GoGoHam-Sicherung (.ggh). Gibt den Ordner zurück."""
    target = Path(exchange) / BACKUP_FOLDER
    target.mkdir(parents=True, exist_ok=True)
    try:
        _backup_readme(target)
    except OSError:
        pass
    stem = Path(log_path).stem
    tmp = target / f".{stem}.adi.tmp"
    tmp.write_text(adif_text, encoding="utf-8")
    tmp.replace(target / f"{stem}.adi")
    if backup_file is not None and Path(backup_file).is_file():
        tmp = target / f".{stem}.ggh.tmp"
        shutil.copyfile(backup_file, tmp)
        tmp.replace(target / f"{stem}.ggh")
    return target

