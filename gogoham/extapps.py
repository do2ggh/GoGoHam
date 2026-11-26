"""Zusatzprogramme (ab 0.10.4): WS (DG2YCB) und fldigi (JTDX bis 0.10.16, Nutzer: raus).

Ab 0.10.13 (Nutzer): das Original-WSJT-X ist nicht mehr dabei. WS (früher „WSJT-X Improved“)
kommt direkt von DG2YCB in der neuesten Version (siehe wsdl.py) – Debian & Co. haben es nicht.
Der interne Schlüssel bleibt „wsjtx_improved“, damit gespeicherte Einstellungen weiter gelten.

GoGoHam schaut nach, ob ein Programm installiert ist, installiert es auf Wunsch über die
Paketverwaltung der Distribution (pkexec fragt nach dem Passwort) oder öffnet die offizielle
Downloadseite, wenn es kein Paket gibt. Für die FT8-Programme trägt es auf Wunsch nur die
Verbindung zu GoGoHam ein (Funkgerät über rigctld, PTT über CAT, UDP für geloggte QSOs) –
mit Sicherungskopie und nur bei geschlossenem Programm. Alles andere bleibt unangetastet.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .i18n import tr


@dataclass(frozen=True)
class App:
    key: str
    name: str
    binaries: tuple[str, ...]          # Programmnamen im Suchpfad
    packages: tuple[str, ...]          # Paketnamen (der erste vorhandene wird genommen)
    url: str                           # offizielle Downloadseite
    ini_names: tuple[str, ...] = ()    # Einstellungsdatei in ~/.config (erste = für neue Datei)
    ft8: bool = False
    improved: bool | None = None       # WSJT-X: True = nur Improved, False = nur Original
    flatpak: str = ""                  # 0.10.14: Flathub-Kennung – dann immer die neueste von dort
    sf: str = ""                       # 0.10.16: Projekt in wsdl.PROJECTS (Pakete von SourceForge)
    notes: tuple[str, ...] = field(default_factory=tuple)


APPS: tuple[App, ...] = (
    App("wsjtx_improved", "WS (DG2YCB)", ("ws", "wsjtx"), ("wsjtx-improved",),
        "https://sourceforge.net/projects/wsjt-x-improved/", ("WS.ini", "WSJT-X.ini"),
        ft8=True, improved=True, sf="ws"),
    # 0.10.17: JTDX nicht mehr dabei – keine Quelle, die auf allen Systemen sicher funktioniert
    App("fldigi", "fldigi", ("fldigi",), ("fldigi",), "https://flathub.org/apps/com.w1hkj.fldigi",
        flatpak="com.w1hkj.fldigi"),
)
BY_KEY = {a.key: a for a in APPS}

# Paketverwaltung -> (Installieren, Prüfen ob vorhanden, Besitzer-Paket einer Datei)
_PM = {
    "pacman": ("pacman -S --needed --noconfirm", ["pacman", "-Si"], ["pacman", "-Qoq"]),
    "apt-get": ("apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y",
                ["apt-cache", "show"], ["dpkg-query", "-S"]),
    "dnf": ("dnf install -y", ["dnf", "-q", "info"], ["rpm", "-qf", "--qf", "%{NAME}\\n"]),
    "zypper": ("zypper --non-interactive install", ["zypper", "--no-refresh", "-q", "info"],
               ["rpm", "-qf", "--qf", "%{NAME}\\n"]),
}


def package_manager(which=shutil.which) -> str:
    for pm in _PM:
        if which(pm):
            return pm
    return ""


def _run(args: list[str], timeout: float = 30) -> tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return -1, ""


def owner_package(path: str, pm: str | None = None, run=_run) -> str:
    """Name des Pakets, zu dem eine Datei gehört ("" = unbekannt, z. B. selbst installiert)."""
    pm = package_manager() if pm is None else pm
    if pm not in _PM:
        return ""
    code, out = run(_PM[pm][2] + [path], 10)
    if code != 0 or not out.strip():
        return ""
    line = out.strip().splitlines()[0]
    return line.split(":")[0].strip() if pm == "apt-get" else line.strip()


FLATPAK = "flatpak:"                  # find(): Programm ist als Flatpak installiert
FLATHUB = "flathub:"                  # available_package(): von Flathub installieren
FLATHUB_REPO = "https://dl.flathub.org/repo/flathub.flatpakrepo"


def flatpak_installed(app_id: str, home: str | None = None) -> bool:
    """Ist die Flatpak-App installiert (für alle oder nur für diesen Benutzer)?"""
    h = Path(home or os.path.expanduser("~"))
    return any(Path(d, app_id, "current").exists()
               for d in ("/var/lib/flatpak/app", h / ".local/share/flatpak/app"))


def launch_cmd(path: str, env: dict | None = None) -> list[str]:
    """Aufruf zum Starten – bei Flatpak über „flatpak run“ (Umgebung ausdrücklich mitgeben:
    Soundkarte über PULSE_SINK/PULSE_SOURCE, Zahlenformat)."""
    if path.startswith(FLATPAK):
        args = ["flatpak", "run"]
        for k in ("PULSE_SINK", "PULSE_SOURCE", "LC_NUMERIC"):
            if env and env.get(k):
                args.append(f"--env={k}={env[k]}")
        return args + [path[len(FLATPAK):]]
    return [path]


def find(key: str, which=shutil.which, owner=owner_package,
         flatpak=flatpak_installed) -> str | None:
    """Pfad des installierten Programms oder None. WSJT-X und WSJT-X Improved liefern oft
    dasselbe Programm „wsjtx“ – dann entscheidet das Paket, zu dem es gehört.
    Flathub-Programme (0.10.14): ist das Flatpak da, wird es genommen („flatpak:<Kennung>“)."""
    app = BY_KEY[key]
    if app.flatpak and flatpak(app.flatpak):
        return FLATPAK + app.flatpak
    for b in app.binaries:
        path = which(b)
        if not path:
            continue
        if app.improved is None:
            return path
        pkg = owner(os.path.realpath(path)).lower()
        if b == "ws":
            # Debian/Ubuntu-Paket von DG2YCB heißt „ws“, AUR „wsjtx-improved“
            if pkg and pkg != "ws" and "improved" not in pkg:
                continue                   # ein anderes Programm namens „ws“
            is_improved = True
        else:
            is_improved = "improved" in pkg
        if is_improved == app.improved:
            return path
    return None


SF = "sf:"                            # Paket von SourceForge: "sf:deb", "sf:deb-old", "sf:rpm"
WS_DEB, WS_RPM, WS_AUR = "sf:deb", "sf:rpm", "aur:"


def sf_kind(key: str, pm: str, run=_run) -> str:
    """Welche Paketart von SourceForge passt zu diesem System ("" = keine)."""
    from . import wsdl
    kind = wsdl.kind_for(pm)
    app = BY_KEY[key]
    if kind == "deb" and app.sf and any(k == "deb-old" for k, _ in
                                        wsdl.PROJECTS[app.sf].patterns) and wsdl.old_debian(run):
        return "deb-old"
    return kind


def available_package(key: str, pm: str | None = None, run=_run, which=shutil.which,
                      latest=None) -> str:
    """Paketname, den die Paketverwaltung dieses Systems anbietet ("" = keins).

    WS (0.10.13): "sf:deb"/"sf:deb-old"/"sf:rpm" = Paket direkt vom Entwickler auf
    SourceForge, "aur:paru" bzw. "aur:yay" = AUR über diesen Helfer; fldigi: "flathub:<Kennung>".
    Gibt es dort nichts Passendes, das Paket der Distribution."""
    pm = package_manager() if pm is None else pm
    if pm not in _PM:
        return ""
    app = BY_KEY[key]
    if app.flatpak:                       # 0.10.14: immer die neueste von Flathub
        return FLATHUB + app.flatpak
    if app.sf:                            # 0.10.13: WS direkt von SourceForge
        from . import wsdl
        if pm == "pacman":
            h = wsdl.aur_helper(which)
            if h:
                return WS_AUR + h
        kind = sf_kind(key, pm, run) if pm != "pacman" else ""
        offered = {k for k, _ in wsdl.PROJECTS[app.sf].patterns}
        if kind in offered:
            find_latest = latest or (lambda k: wsdl.latest(k, project=app.sf))
            if find_latest(kind) is not None:
                return SF + kind
        # sonst wie bisher: Paket der Distribution
    for pkg in BY_KEY[key].packages:
        code, out = run(_PM[pm][1] + [pkg], 60)
        if code == 0 and out.strip():
            return pkg
    return ""


def install_command(pkg: str, pm: str | None = None, which=shutil.which) -> list[str] | None:
    """Aufruf zum Installieren (pkexec fragt nach dem Passwort) – None, wenn das nicht geht.
    "flathub:<Kennung>" (0.10.14): flatpak bei Bedarf über die Paketverwaltung nachinstallieren,
    Flathub eintragen, App installieren oder aktualisieren (für alle Benutzer)."""
    pm = package_manager(which) if pm is None else pm
    if pm not in _PM or not which("pkexec"):
        return None
    if pkg.startswith(FLATHUB):
        app_id = pkg[len(FLATHUB):]
        pre = "" if which("flatpak") else f"{_PM[pm][0]} flatpak && "
        return ["pkexec", "/bin/sh", "-c",
                f"{pre}flatpak remote-add --if-not-exists flathub {FLATHUB_REPO} && "
                f"flatpak install --or-update -y --noninteractive flathub {app_id}"]
    return ["pkexec", "/bin/sh", "-c", f"{_PM[pm][0]} {pkg}"]


# ------------------------------------------------------------------ Deinstallieren (0.10.17)
# Nur das Paket selbst entfernen – die Befehle brechen ab, wenn ein anderes Paket es noch braucht
# (pacman -R, dpkg -r, rpm -e tun das; apt-get/dnf remove würden Abhängige still mitnehmen).
# Einstellungen und Logs im Benutzerordner bleiben immer erhalten.
_REMOVE = {"pacman": "pacman -R --noconfirm", "apt-get": "dpkg -r",
           "dnf": "rpm -e", "zypper": "rpm -e"}


def flatpak_user_only(app_id: str, home: str | None = None) -> bool:
    """Liegt das Flatpak nur im Benutzerordner (dann ohne pkexec und mit --user entfernen)?"""
    h = Path(home or os.path.expanduser("~"))
    return (not Path("/var/lib/flatpak/app", app_id, "current").exists()
            and Path(h, ".local/share/flatpak/app", app_id, "current").exists())


def removable_package(key: str, path: str | None, pm: str | None = None, run=_run) -> str:
    """Paket, das GoGoHam für dieses Programm entfernen darf ("" = keins, z. B. selbst gebaut
    oder das Programm gehört zu einem fremden Paket)."""
    if not path:
        return ""
    if path.startswith(FLATPAK):
        return FLATPAK + path[len(FLATPAK):]
    pm = package_manager() if pm is None else pm
    pkg = owner_package(os.path.realpath(path), pm, run)
    app = BY_KEY[key]
    allowed = set(app.packages) | set(app.binaries)
    if app.sf:
        from . import wsdl
        allowed.add(wsdl.PROJECTS[app.sf].aur)
    return pkg if pkg in allowed else ""


# ---------------------------------------------------------- Desktop-Verknüpfung (0.10.19)
APP_DIRS = ("/usr/share/applications", "/usr/local/share/applications")
FLATPAK_EXPORTS = ("/var/lib/flatpak/exports/share/applications",
                   ".local/share/flatpak/exports/share/applications")     # zweites: im Home


def _exec_name(desktop: Path) -> str:
    """Programmname aus der Exec-Zeile einer .desktop-Datei ("" = keiner/versteckt)."""
    try:
        text = desktop.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if re.search(r"^NoDisplay\s*=\s*true", text, re.M | re.I):
        return ""
    m = re.search(r"^Exec\s*=\s*(\S+)", text, re.M)
    return os.path.basename(m.group(1).strip('"')) if m else ""


def desktop_file(key: str, path: str | None, home: str | None = None,
                 app_dirs=APP_DIRS) -> Path | None:
    """Die Startmenü-Datei (.desktop) des installierten Programms – None, wenn keine da ist."""
    if not path:
        return None
    h = Path(home or os.path.expanduser("~"))
    if path.startswith(FLATPAK):
        app_id = path[len(FLATPAK):]
        for d in FLATPAK_EXPORTS:
            f = (h / d if not d.startswith("/") else Path(d)) / f"{app_id}.desktop"
            if f.is_file():
                return f
        return None
    names = {os.path.basename(path), os.path.basename(os.path.realpath(path))} | \
        set(BY_KEY[key].binaries)
    for d in app_dirs:
        try:
            files = sorted(Path(d).glob("*.desktop"))
        except OSError:
            continue
        for f in files:
            if _exec_name(f) in names:
                return f
    return None


def desktop_link_path(key: str, home: str | None = None) -> Path:
    return Path(home or os.path.expanduser("~"), "Desktop", f"gogoham-{key}.desktop")


def add_desktop_link(key: str, path: str | None, home: str | None = None,
                     app_dirs=APP_DIRS) -> Path | None:
    """Verknüpfung auf den Desktop legen (Live-Stick) – ausführbar, damit Plasma ihr traut."""
    src = desktop_file(key, path, home, app_dirs)
    if src is None:
        return None
    dst = desktop_link_path(key, home)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        dst.chmod(0o755)
    except OSError:
        return None
    return dst


def remove_desktop_link(key: str, home: str | None = None) -> None:
    try:
        desktop_link_path(key, home).unlink()
    except OSError:
        pass


def uninstall_command(pkg: str, pm: str | None = None, which=shutil.which,
                      user_only=flatpak_user_only) -> list[str] | None:
    """Aufruf zum Deinstallieren (pkexec fragt nach dem Passwort) – None, wenn das nicht geht.
    Flatpak: danach auch nicht mehr gebrauchte Laufzeiten entfernen (bei fldigi gut 1 GB)."""
    if pkg.startswith(FLATPAK):
        app_id = pkg[len(FLATPAK):]
        if not which("flatpak"):
            return None
        if user_only(app_id):
            return ["/bin/sh", "-c", f"flatpak uninstall --user -y --noninteractive {app_id} && "
                    "flatpak uninstall --user -y --noninteractive --unused"]
        if not which("pkexec"):
            return None
        return ["pkexec", "/bin/sh", "-c", f"flatpak uninstall --system -y --noninteractive "
                f"{app_id} && flatpak uninstall --system -y --noninteractive --unused"]
    pm = package_manager(which) if pm is None else pm
    if pm not in _REMOVE or not pkg or not which("pkexec"):
        return None
    return ["pkexec", "/bin/sh", "-c", f"{_REMOVE[pm]} {pkg}"]


# ------------------------------------------------------------------ Versionen (0.10.14)
def vtuple(v: str) -> tuple[int, ...]:
    """„3.2.1.261010-1“ → (3, 2, 1, 261010); Paket-Revision (nach „-“) zählt nicht."""
    v = (v or "").split(":")[-1].split("-")[0]
    return tuple(int(x) for x in re.findall(r"\d+", v))


def _field(out: str, name: str) -> str:
    for ln in out.splitlines():
        if ln.strip().lower().startswith(name.lower() + ":"):
            return ln.split(":", 1)[1].strip()
    return ""


def installed_version(key: str, path: str | None, pm: str | None = None, run=_run) -> str:
    """Installierte Version ("" = unbekannt)."""
    if not path:
        return ""
    if path.startswith(FLATPAK):
        code, out = run(["flatpak", "info", path[len(FLATPAK):]], 20)
        return _field(out, "Version") if code == 0 else ""
    pm = package_manager() if pm is None else pm
    pkg = owner_package(os.path.realpath(path), pm, run)
    if not pkg:
        return ""
    if pm == "apt-get":
        code, out = run(["dpkg-query", "-W", "-f=${Version}", pkg], 10)
    elif pm in ("dnf", "zypper"):
        code, out = run(["rpm", "-q", "--qf", "%{VERSION}", pkg], 10)
    elif pm == "pacman":
        code, out = run(["pacman", "-Q", pkg], 10)
        out = out.split()[-1] if code == 0 and out.split() else ""
    else:
        return ""
    return out.strip() if code == 0 else ""


def _aur_version(name: str, timeout: float = 20) -> str:
    import json
    import urllib.request
    url = f"https://aur.archlinux.org/rpc/v5/info?arg[]={name}"
    req = urllib.request.Request(url, headers={"User-Agent": "GoGoHam"})
    with urllib.request.urlopen(req, timeout=timeout) as r:     # noqa: S310 – feste https-Adresse
        res = json.loads(r.read().decode()).get("results") or []
    return res[0].get("Version", "") if res else ""


def _flathub_version(app_id: str, timeout: float = 20) -> str:
    """Version bei Flathub – über die Flathub-Seite, geht auch ohne installiertes flatpak."""
    import json
    import urllib.request
    url = f"https://flathub.org/api/v2/appstream/{app_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "GoGoHam"})
    with urllib.request.urlopen(req, timeout=timeout) as r:     # noqa: S310 – feste https-Adresse
        rel = json.loads(r.read().decode()).get("releases") or []
    return str(rel[0].get("version", "")) if rel else ""


def newest_version(key: str, path: str | None, pm: str | None = None, run=_run,
                   latest=None, aur=None, flathub=None) -> str:
    """Neueste Version an der Quelle, aus der GoGoHam installiert ("" = unbekannt/offline).
    Nur für Programme, die GoGoHam selbst aktuell hält: WS (DG2YCB/AUR) und Flatpaks."""
    app = BY_KEY[key]
    try:
        if app.flatpak:                   # auch wenn noch die alte aus den Paketquellen da ist
            return (flathub or _flathub_version)(app.flatpak)
        if not app.sf:
            return ""
        from . import wsdl
        pm = package_manager() if pm is None else pm
        if pm == "pacman":
            return (aur or _aur_version)(wsdl.PROJECTS[app.sf].aur)
        kind = sf_kind(key, pm, run)
        if kind not in {k for k, _ in wsdl.PROJECTS[app.sf].patterns}:
            return ""                     # Paket der Distribution: kommt mit dem Systemupdate
        p = (latest or (lambda k: wsdl.latest(k, project=app.sf)))(kind)
        return p.version if p else ""
    except Exception:  # noqa: BLE001 – kein Internet
        return ""


def nice_version(v: str) -> str:
    """Zum Anzeigen: „4.2.06-1+deb13u1“ → „4.2.06“, „3.2.1.261010-1“ → „3.2.1“."""
    v = (v or "").split(":")[-1].split("-")[0].split("+")[0]
    parts = v.split(".")
    return ".".join(parts[:3]) if len(parts) > 3 and len(parts[3]) >= 6 else v


def update_available(installed: str, newest: str) -> bool:
    a, b = vtuple(installed), vtuple(newest)
    if not a or not b:
        return False
    n = min(len(a), len(b), 3) if len(a) != len(b) else len(a)
    return b[:n] > a[:n]


def running(key: str, run=_run) -> bool:
    """Läuft das Programm gerade? (Dann würde es geänderte Einstellungen beim Beenden
    wieder überschreiben.)"""
    for b in BY_KEY[key].binaries:
        code, _out = run(["pgrep", "-x", b], 5)
        if code == 0:
            return True
    return False


# ------------------------------------------------------------------ Verbindung einrichten
# Diese Werte schreibt WSJT-X selbst so in seine Einstellungsdatei (Qt-Format für die
# Auswahl „PTT über CAT“).
PTT_CAT = r"@Variant(\0\0\0\x7f\0\0\0\x1eTransceiverFactory::PTTMethod\0\0\0\0\xfPTT_method_CAT\0)"
RIG_NET = "Hamlib NET rigctl"


def ini_path(key: str, home: str | None = None, binary: str | None = None) -> Path:
    """Einstellungsdatei des Programms: die vorhandene, sonst die zum Programmnamen passende."""
    cfgdir = Path(home or os.path.expanduser("~")) / ".config"
    names = BY_KEY[key].ini_names
    for n in names:
        if (cfgdir / n).is_file():
            return cfgdir / n
    if key == "wsjtx_improved" and binary and Path(binary).name == "wsjtx":
        return cfgdir / "WSJT-X.ini"
    return cfgdir / names[0]


def wanted(host: str, port: int, udp_host: str, udp_port: int,
           station: dict | None = None) -> list[tuple[str, str, str]]:
    """(Schlüssel, Wert, Beschreibung) – genau das, was GoGoHam einträgt.

    station (ab 0.10.9, alles freiwillig): mycall, grid, sound_out, sound_in – eigenes
    Rufzeichen, Locator und die Soundkarte des Funkgeräts (PulseAudio/PipeWire-Namen)."""
    st = station or {}
    extra = []
    if st.get("mycall"):
        v = st["mycall"].strip().upper()
        extra.append(("MyCall", v, tr("Rufzeichen: {v}", v=v)))
    if st.get("grid"):
        v = st["grid"].strip().upper()[:6]
        extra.append(("MyGrid", v, tr("Locator: {v}", v=v)))
    if st.get("sound_in"):
        extra.append(("SoundInName", st["sound_in"],
                      tr("Soundkarte Empfang: {v}", v=nice_sound(st["sound_in"]))))
    if st.get("sound_out"):
        extra.append(("SoundOutName", st["sound_out"],
                      tr("Soundkarte Senden: {v}", v=nice_sound(st["sound_out"]))))
    return [
        ("Rig", RIG_NET, tr("Funkgerät: {v}", v=RIG_NET)),
        ("CATNetworkPort", f"{host}:{port}", tr("Verbindung zum Funkgerät: {v}",
                                                v=f"{host}:{port}")),
        ("PTTMethod", PTT_CAT, tr("PTT (Senden): über CAT")),
        ("UDPServer", udp_host, tr("Geloggte QSOs an GoGoHam: UDP {v}",
                                   v=f"{udp_host}:{udp_port}")),
        ("UDPServerPort", str(udp_port), ""),
    ] + _multicast(udp_host) + extra


def _multicast(udp_host: str) -> list[tuple[str, str, str]]:
    """Gruppe (z. B. 224.0.0.1, 0.10.43): über die interne Verbindung „lo“ senden – dann kommen
    die QSOs auch ohne Netzwerk an, und alle Programme in der Gruppe bekommen sie."""
    try:
        import ipaddress
        if not ipaddress.ip_address(udp_host).is_multicast:
            return []
    except ValueError:
        return []
    return [("UDPInterface", "lo", tr("Senden an die Gruppe über: lo (diesen Rechner)")),
            ("UDPTTL", "1", "")]


def nice_sound(name: str) -> str:
    """„alsa_output.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo“ → „Burr-Brown from
    TI USB Audio CODEC“ – lesbarer für Rückfragen."""
    n = name
    for pre in ("alsa_output.", "alsa_input."):
        if n.startswith(pre):
            n = n[len(pre):]
    n = n.rsplit(".", 1)[0] if "." in n else n
    for pre in ("usb-", "pci-"):
        if n.startswith(pre):
            n = n[len(pre):]
    n = re.sub(r"-\d\d$", "", n)
    return n.replace("_", " ").strip() or name


def _section(lines: list[str], name: str) -> tuple[int, int]:
    """Anfang (Zeile nach der Überschrift) und Ende eines Abschnitts; (-1, -1) = fehlt."""
    start = -1
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("[") and s.endswith("]"):
            if start >= 0:
                return start, i
            if s == f"[{name}]":
                start = i + 1
    return (start, len(lines)) if start >= 0 else (-1, -1)


def current(path: Path, section: str = "Configuration") -> dict[str, str]:
    """Werte in einem Abschnitt (sonst [Configuration]) der Einstellungsdatei."""
    try:
        lines = path.read_text(encoding="utf-8", errors="surrogateescape").splitlines()
    except OSError:
        return {}
    a, b = _section(lines, section)
    vals = {}
    for ln in lines[a:b] if a >= 0 else []:
        if "=" in ln:
            k, v = ln.split("=", 1)
            vals[k.strip()] = v
    return vals


def changes(path: Path, host: str, port: int, udp_host: str,
            udp_port: int, station: dict | None = None) -> list[tuple[str, str]]:
    """Was sich ändern würde: (Beschreibung, bisheriger Wert). Leer = schon eingerichtet."""
    cur = current(path)
    out = []
    want = wanted(host, port, udp_host, udp_port, station)
    for k, v, label in want:
        if cur.get(k) == v:
            continue
        if k == "UDPServerPort":            # gehört zur Zeile „UDP …“
            label = want[3][2]
            k = "UDPServer"
        if k == "UDPTTL":                   # gehört zur Zeile „Senden an die Gruppe …“
            label = next(lb for kk, _v, lb in want if kk == "UDPInterface")
            k = "UDPInterface"
        old = cur.get(k, "")
        if k == "PTTMethod" and "PTT_method_" in old:
            old = old.split("PTT_method_")[1].split("\\")[0]     # „VOX“, „DTR“ …
        if k in ("SoundInName", "SoundOutName") and old:
            old = nice_sound(old)
        if (label, old) not in out:
            out.append((label, old))
    for _k, _v, label in _language_wanted(path, station):
        out.append((label, ""))
    return out


LANG_SECTION, LANG_KEY = "MultiSettings", "UILanguage"


def _language_wanted(path: Path, station: dict | None) -> list[tuple[str, str, str]]:
    """WSJT-X Improved (0.10.12): Sprache der Oberfläche = Systemsprache – nur wenn dort noch
    keine gewählt ist (eine eigene Wahl im Menü „Language“ bleibt). station["ui_language"]
    setzt nur, wer Improved einrichtet; das Original-WSJT-X nimmt die Systemsprache selbst."""
    lang = ((station or {}).get("ui_language") or "").strip()
    if not lang or lang == "en" or current(path, LANG_SECTION).get(LANG_KEY):
        return []
    return [(LANG_KEY, lang, tr("Sprache der Oberfläche: {v}", v=lang))]


def apply(path: Path, host: str, port: int, udp_host: str, udp_port: int,
          station: dict | None = None, now: float | None = None) -> Path | None:
    """Verbindung eintragen; vorher Sicherungskopie (deren Pfad kommt zurück, None = es gab
    noch keine Datei). Nur diese Schlüssel in [Configuration] werden geändert."""
    backup = None
    if path.is_file():
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
        backup = path.with_name(f"{path.name}.gogoham-{stamp}.bak")
        shutil.copy2(path, backup)
        text = path.read_bytes().decode("utf-8", "surrogateescape")   # Zeilenenden behalten
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = ""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    a, b = _section(lines, "Configuration")
    if a < 0:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("[Configuration]")
        a = b = len(lines)
    todo = {k: v for k, v, _l in wanted(host, port, udp_host, udp_port, station)}
    for i in range(a, b):
        if "=" in lines[i]:
            k = lines[i].split("=", 1)[0].strip()
            if k in todo:
                lines[i] = f"{k}={todo.pop(k)}"
    # fehlende Schlüssel ans Ende des Abschnitts (vor eventuelle Leerzeilen)
    ins = b
    while ins > a and not lines[ins - 1].strip():
        ins -= 1
    lines[ins:ins] = [f"{k}={v}" for k, v in todo.items()]
    lang = _language_wanted(path, station)
    if lang:
        k, v, _l = lang[0]
        a, b = _section(lines, LANG_SECTION)
        if a < 0:
            if lines and lines[-1].strip():
                lines.append("")
            lines += [f"[{LANG_SECTION}]", f"{k}={v}"]
        else:
            lines[a:a] = [f"{k}={v}"]
    tmp = path.with_name(path.name + ".gogoham-tmp")
    tmp.write_bytes((nl.join(lines) + nl).encode("utf-8", "surrogateescape"))
    os.replace(tmp, path)
    return backup


def station_settings(cfg: dict, meta: dict | None, prof: dict | None,
                     audio=None, key: str = "") -> tuple[dict, str]:
    """Rufzeichen, Locator und Soundkarte für WS/fldigi (ab 0.10.9).

    Rufzeichen/Locator aus dem offenen Log, sonst aus den gemerkten Stationsangaben.
    Soundkarte: im Profil gewählt, sonst über USB gefunden; die Soundkarte des Sprachspeichers
    nur, wenn es genau ein Funkgerät gibt (bei mehreren könnte sie zum falschen gehören).
    Zweiter Wert = Herkunft der Soundkarte ("profile", "auto", "fallback" oder "" = keine)."""
    from . import rigaudio
    meta = meta or {}
    sd = cfg.get("station_defaults") or {}
    profs = [p for p in (cfg.get("rig_profiles") or []) if isinstance(p, dict)]
    fallback = cfg.get("voice_rig_out", "") if len(profs) <= 1 else ""
    find = audio or rigaudio.for_profile
    out, inp, origin = find(prof, fallback)
    st = {"mycall": (meta.get("mycall") or sd.get("mycall") or "").strip(),
          "grid": (meta.get("my_grid") or sd.get("my_grid") or "").strip(),
          "sound_out": out, "sound_in": inp}
    if key in BY_KEY and BY_KEY[key].improved:          # 0.10.12: Sprache = Systemsprache
        from .i18n import system_language
        st["ui_language"] = system_language()
    return st, origin
