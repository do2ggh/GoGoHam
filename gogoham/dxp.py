"""microHAM DXP erkennen (ab 0.8.18.1).

Das DXP meldet sich per USB (VID 0483, PID a2f6 – laut microHAM-Handbuch) mit drei seriellen
Schnittstellen (`/dev/ttyACM…`): CAT, FSK und WinKey. Welche welche ist, verrät
1. der Name der USB-Schnittstelle, falls das Gerät einen meldet (es wird nichts gesendet), sonst
2. die WinKey-Frage „Host Open“ (nur der WinKey antwortet mit seiner Version, sendet kein CW)
   und danach die normale, nur lesende Geräteerkennung an den übrigen Anschlüssen.

**Wichtig:** Der WinKey-Anschluss darf nie die CAT-Fragen (z. B. „;ID;“) bekommen – der WinKey
würde sie als CW senden. Deshalb immer zuerst den WinKey suchen.

Ohne echtes Gerät gebaut (nur nach Handbuch) – Testlauf mit einem DXP steht aus.
"""

from __future__ import annotations

import grp
import os
from dataclasses import dataclass, field

from . import permissions
from .i18n import tr

DXP_VID, DXP_PID = "0483", "a2f6"


def usb_info(path: str, sysfs: str = "/sys") -> dict:
    """USB-Angaben zu einer Schnittstelle aus /sys: vid, pid, iface (Nummer), name, serial, usb."""
    tty = os.path.basename(os.path.realpath(path))
    d = os.path.realpath(os.path.join(sysfs, "class", "tty", tty, "device"))
    info = {}

    def read(p, name):
        try:
            with open(os.path.join(p, name)) as f:
                return f.read().strip()
        except OSError:
            return ""
    for _ in range(4):                       # ttyACM: device = Schnittstelle; ttyUSB: eins höher
        if os.path.exists(os.path.join(d, "bInterfaceNumber")):
            info["iface"] = int(read(d, "bInterfaceNumber") or "0", 16)
            info["name"] = read(d, "interface")
            usb = os.path.dirname(d)
            info.update(vid=read(usb, "idVendor").lower(), pid=read(usb, "idProduct").lower(),
                        serial=read(usb, "serial"), usb=usb)
            return info
        d = os.path.dirname(d)
    return {}


def is_dxp(path: str, sysfs: str = "/sys") -> bool:
    i = usb_info(path, sysfs)
    return i.get("vid") == DXP_VID and i.get("pid") == DXP_PID


def maybe_winkey(path: str, sysfs: str = "/sys") -> bool:
    """Könnte an der Schnittstelle ein WinKey hängen? (DXP oder Name mit WinKey/K1EL)"""
    if is_dxp(path, sysfs):
        return True
    low = (os.path.basename(path) + " " + usb_info(path, sysfs).get("name", "")).lower()
    return "winkey" in low or "k1el" in low


def find_units(ports: list[str], sysfs: str = "/sys") -> list[list[tuple[int, str, str]]]:
    """Alle angeschlossenen DXP: je Gerät eine Liste (Schnittstellen-Nr., Pfad, USB-Name)."""
    units: dict[str, list] = {}
    seen = set()
    for p in ports:
        real = os.path.realpath(p)
        if real in seen:
            continue
        i = usb_info(p, sysfs)
        if i.get("vid") == DXP_VID and i.get("pid") == DXP_PID:
            seen.add(real)
            units.setdefault(i["usb"], []).append((i["iface"], p, i.get("name", "")))
    return [sorted(u) for u in units.values()]


def roles_from_names(unit) -> dict:
    """Rollen aus den USB-Namen („… CAT“, „… FSK“, „… WinKey“) – nur, wenn alle eindeutig."""
    roles = {}
    for _n, path, name in unit:
        low = name.lower()
        role = "winkey" if ("wink" in low or "wk" in low.split()) else \
            "fsk" if "fsk" in low else "cat" if "cat" in low else ""
        if not role or role in roles:
            return {}
        roles[role] = path
    return roles if "winkey" in roles and "cat" in roles else {}


@dataclass
class DxpResult:
    ok: bool
    text: str = ""
    cat: str = ""              # Schnittstelle CAT ("" = nicht gefunden)
    winkey: str = ""
    fsk: str = ""
    version: int = 0           # WinKey-Version
    detection: object = None   # rigdetect.Detection des CAT-Anschlusses
    hints: list = field(default_factory=list)


def identify(unit, rigs=None, probe_wk=None, detect=None, held=None) -> DxpResult:
    """Rollen der drei Anschlüsse eines DXP bestimmen und das Funkgerät dahinter erkennen."""
    from . import rigdetect, winkey
    probe_wk = probe_wk or winkey.probe
    detect = detect or (lambda p: rigdetect.detect(p, rigs))
    held = held or rigdetect.port_held
    paths = [rigdetect.stable_name(p) for _n, p, _name in unit]
    roles = roles_from_names([(n, rigdetect.stable_name(p), name) for n, p, name in unit])
    version = 0
    if roles:
        if not held(roles["winkey"]):
            version = probe_wk(roles["winkey"])
    else:
        for p in paths:                      # 1. WinKey suchen – vor jeder CAT-Frage!
            if held(p):
                continue
            version = probe_wk(p)
            if version:
                roles["winkey"] = p
                break
        if "winkey" not in roles:
            return DxpResult(False, tr("microHAM DXP gefunden, aber kein Anschluss antwortet als "
                                       "WinKey. Hat ein anderes Programm die Schnittstellen offen?"))
    rest = [p for p in paths if p != roles["winkey"]]
    det = None
    if roles.get("cat"):
        det = detect(roles["cat"])
    else:                                    # 2. am CAT-Anschluss antwortet das Funkgerät
        for p in rest:
            d = detect(p)
            if d.ok or d.rigctld_port or d.search:
                roles["cat"], det = p, d
                break
    if not roles.get("fsk") and roles.get("cat"):
        others = [p for p in rest if p != roles["cat"]]
        roles["fsk"] = others[0] if len(others) == 1 else ""
    res = DxpResult(True, cat=roles.get("cat", ""), winkey=roles["winkey"], fsk=roles.get("fsk", ""),
                    version=version, detection=det)
    if not res.cat:
        res.text = tr("Kein Funkgerät antwortet am DXP – ist es eingeschaltet, das CAT-Kabel "
                      "gesteckt und im DXP-Menü 1.1 CAT TYPE richtig eingestellt? Den CAT-Anschluss "
                      "bitte selbst wählen.")
    return res


# --- Linux-Hinweise -------------------------------------------------------------------------
UDEV_FILE = "/etc/udev/rules.d/99-microham-dxp.rules"
UDEV_RULE = ('ATTRS{idVendor}=="0483", ATTRS{idProduct}=="a2f6", ENV{ID_MM_DEVICE_IGNORE}="1"')


def modemmanager_running(proc: str = "/proc") -> bool:
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return False
    for pid in pids:
        try:
            with open(os.path.join(proc, pid, "comm")) as f:
                if f.read().strip() == "ModemManager":
                    return True
        except OSError:
            continue
    return False


def linux_hints(paths: list[str], proc: str = "/proc") -> list[tuple[str, str]]:
    """Was unter Linux im Weg stehen kann: (Erklärung, Befehl zum Kopieren)."""
    hints = []
    if modemmanager_running(proc):
        hints.append((tr("Der ModemManager läuft. Er greift gern auf neue ttyACM-Geräte zu und stört "
                         "das DXP. Diese Befehle sagen ihm, das DXP in Ruhe zu lassen (einmalig, "
                         "fragt nach deinem Passwort):"),
                      f"echo '{UDEV_RULE}' | sudo tee {UDEV_FILE}\n"
                      "sudo udevadm control --reload-rules && sudo udevadm trigger"))
    no_access = [p for p in paths if p and os.path.exists(p) and not os.access(p, os.R_OK | os.W_OK)]
    if no_access:
        try:
            group = grp.getgrgid(os.stat(no_access[0]).st_gid).gr_name
        except (KeyError, OSError):
            group = "uucp"
        hints.append((tr("Du darfst die Schnittstellen des DXP nicht benutzen. Dieser Befehl nimmt "
                         "dich in die Gruppe „{g}“ auf – danach einmal ab- und wieder anmelden:",
                         g=group),
                      permissions.command(group)))
    return hints
