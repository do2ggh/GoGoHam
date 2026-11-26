"""Neuen Stick erstellen (ab 0.10.20): der Live-Stick schreibt sich selbst auf einen anderen Stick.

Nutzerwunsch: Ein Freund bringt seinen eigenen Stick mit – ohne Internet, ohne PC mit Bauprojekt.
GoGoHam liest das ursprüngliche System vom laufenden Stick und schreibt es auf den neuen; dann
Datenteil und Austausch-Ordner passend zur Größe (wie schreiben.sh). Der neue Stick ist FRISCH:
keine Logs, Einstellungen oder Passwörter.

Das Schreiben selbst macht das Hilfsprogramm des Sticks (MARKER-Eintrag „copy“, über pkexec).
Es prüft das Ziel noch einmal selbst. Hier: welche Sticks in Frage kommen, und was das
Hilfsprogramm meldet.

Sicherheit: Angeboten werden nur USB-Laufwerke – nie eingebaute Platten und nie der Stick, von
dem gerade gestartet wurde. Unter 16 GB lehnt GoGoHam ab.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import livestick
from .i18n import tr

# wie aufteilung.sh im Stick-Projekt
GIB = 1024 ** 3
DATA_START = 8 * GIB             # der Datenteil beginnt fest bei 8 GiB
DATA_MIN = 4 * GIB
EXCH_MIN, EXCH_MAX = 2 * GIB, 16 * GIB
EDGE = 8 * 1024 * 1024
SLOW_MBS, SLOW_SMALL = 15, 20     # darunter: „Dieser Stick ist langsam“


def exchange_size(size: int) -> int:
    t = (size - DATA_START - EDGE) // 4
    t = max(EXCH_MIN, min(EXCH_MAX, t))
    return t // (1024 * 1024) * 1024 * 1024


def fits(size: int) -> bool:
    """Groß genug (Stick „16 GB“)?"""
    return size - DATA_START - EDGE - exchange_size(size) >= DATA_MIN


def data_size(size: int) -> int:
    return max(0, size - DATA_START - EDGE - exchange_size(size))


@dataclass
class Stick:
    path: str
    size: int
    model: str = ""
    vendor: str = ""
    serial: str = ""
    labels: list[str] = field(default_factory=list)
    mounted: list[str] = field(default_factory=list)

    @property
    def fits(self) -> bool:
        return fits(self.size)

    @property
    def gogoham(self) -> bool:
        return "GGH-DATEN" in self.labels

    @property
    def name(self) -> str:
        words = []
        for w in (self.vendor + " " + self.model).split():
            if w.lower() not in (x.lower() for x in words):
                words.append(w)
        return " ".join(words) or tr("USB-Stick")

    def key(self) -> tuple:
        return (self.path, self.serial, self.size)


def _run(args: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return r.returncode, r.stdout


def _backing(loop: str) -> str:
    try:
        return Path(f"/sys/block/{Path(loop).name}/loop/backing_file").read_text().strip()
    except OSError:
        return ""


def boot_disk(run=_run, backing=_backing) -> str:
    """Das Laufwerk, von dem der Stick gerade läuft ("" = unbekannt). live-boot hängt das System
    oft über /dev/loopN ein – dahinter steckt dann der ganze Stick (VM-Test 0.10.20)."""
    code, out = run(["findmnt", "-nro", "SOURCE", "/run/live/medium"])
    src = out.strip().splitlines()[0] if code == 0 and out.strip() else ""
    if src.startswith("/dev/loop"):
        src = backing(src)
    if not src:
        return ""
    code, out = run(["lsblk", "-nro", "PKNAME", src])
    parent = out.strip().splitlines()[0] if code == 0 and out.strip() else ""
    return "/dev/" + parent if parent else src


def _mounts(d: dict) -> list[str]:
    m = d.get("mountpoints")
    if m is None:
        m = [d.get("mountpoint")]
    return [x for x in m if x]


SYSTEM_MOUNTS = ("/", "/home", "/boot", "/boot/efi")


def usb_sticks(run=_run, boot: str | None = None) -> list[Stick]:
    """Alle USB-Laufwerke, die beschrieben werden dürften – ohne den laufenden Stick."""
    boot = boot_disk(run) if boot is None else boot
    code, out = run(["lsblk", "-J", "-b", "-o",
                     "NAME,PATH,SIZE,TYPE,TRAN,MODEL,VENDOR,SERIAL,LABEL,MOUNTPOINTS"])
    if code != 0:
        return []
    try:
        devs = json.loads(out).get("blockdevices", [])
    except ValueError:
        return []
    found = []
    for d in devs:
        if d.get("type") != "disk" or (d.get("tran") or "") != "usb":
            continue
        path = d.get("path") or "/dev/" + (d.get("name") or "")
        if boot and path == boot:
            continue
        size = int(d.get("size") or 0)
        if size <= 0:                              # Kartenleser ohne Karte
            continue
        parts = [d] + list(d.get("children") or [])
        mounted = [m for p in parts for m in _mounts(p)]
        if any(m in SYSTEM_MOUNTS or m.startswith("/run/live") for m in mounted):
            continue                               # trägt ein laufendes System
        labels = [p.get("label") for p in parts if p.get("label")]
        found.append(Stick(path=path, size=size, model=(d.get("model") or "").strip(),
                           vendor=(d.get("vendor") or "").strip(),
                           serial=(d.get("serial") or "").strip(), labels=labels,
                           mounted=mounted))
    return found


def describe(s: Stick) -> str:
    """„Intenso Rainbow · 16,0 GB · /dev/sdc · enthält: INTENSO“."""
    parts = [s.name, livestick.size_text(s.size), s.path]
    if s.gogoham:
        parts.append(tr("schon ein GoGoHam-Stick"))
    elif s.labels:
        parts.append(tr("enthält: {names}", names=", ".join(s.labels)))
    else:
        parts.append(tr("ohne erkennbaren Inhalt"))
    if not s.fits:
        parts.append(tr("zu klein – mindestens 16 GB"))
    return " · ".join(parts)


def command(dev: str, marker: Path | None = None, which=shutil.which) -> list[str] | None:
    """Aufruf des Hilfsprogramms (über pkexec) – None, wenn das hier nicht geht."""
    helper = available(marker, which)
    if helper is None or not dev.startswith("/dev/") or not dev[5:].isalnum():
        return None
    return ["pkexec", helper, dev]


def available(marker: Path | None = None, which=shutil.which) -> str | None:
    helper = (livestick.info(marker) or {}).get("copy")
    if not helper or not Path(helper).is_file() or not which("pkexec"):
        return None
    return str(helper)


# ------------------------------------------------------------ Meldungen des Hilfsprogramms
def parse(line: str) -> tuple | None:
    """Eine Zeile des Hilfsprogramms → ("step", key) / ("progress", done, total) /
    ("speed", mb_s, small) / ("error", key, detail) – None für alles andere."""
    w = line.strip().split(None, 2)
    if not w:
        return None
    try:
        if w[0] == "SCHRITT" and len(w) >= 2:
            return ("step", w[1])
        if w[0] == "FORTSCHRITT" and len(w) >= 3:
            return ("progress", int(w[1]), int(w[2]))
        if w[0] == "TEMPO" and len(w) >= 3:
            return ("speed", int(w[1]), int(w[2]))
    except ValueError:
        return None
    if w[0] == "FEHLER" and len(w) >= 2:
        return ("error", w[1], w[2] if len(w) > 2 else "")
    return None


def step_text(key: str) -> str:
    return {
        "aushaengen": tr("Stick wird vorbereitet …"),
        "schreiben": tr("System wird geschrieben …"),
        "pruefen": tr("Geschriebenes wird geprüft …"),
        "aufteilen": tr("Datenteil und Austausch-Ordner werden angelegt …"),
        "einrichten": tr("Datenteil wird eingerichtet …"),
        "fertig": tr("Fertig."),
    }.get(key, key)


def error_text(key: str, detail: str = "") -> str:
    return {
        "rechte": tr("Keine Berechtigung zum Schreiben."),
        "ziel": tr("Dieses Laufwerk gibt es nicht (mehr) – Stick abgezogen?"),
        "quelle": tr("Das System des laufenden Sticks ließ sich nicht lesen."),
        "eigener": tr("Das ist der Stick, von dem GoGoHam gerade läuft – der wird nie beschrieben."),
        "kein_usb": tr("Das ist kein USB-Laufwerk – GoGoHam beschreibt nur USB-Sticks."),
        "zu_klein": tr("Der Stick ist zu klein – er braucht mindestens 16 GB."),
        "belegt": tr("Der Stick ist noch in Benutzung (ein Ordner darauf ist offen). Bitte "
                     "schließen und noch einmal versuchen."),
        "schreiben": tr("Beim Schreiben ging etwas schief – Stick abgezogen oder defekt?"),
        "pruefen": tr("Die Prüfung hat Fehler gefunden: Der Stick hat nicht alles richtig "
                      "gespeichert. Bitte einen anderen Stick nehmen."),
        "aufteilen": tr("Datenteil und Austausch-Ordner ließen sich nicht anlegen."),
        "einrichten": tr("Der Datenteil ließ sich nicht einrichten."),
    }.get(key, (key + " " + detail).strip())


def is_slow(mb_s: int, small: int) -> bool:
    return mb_s < SLOW_MBS or small < SLOW_SMALL
