"""Fehlerbericht (ab 0.8.18.3): alles Wichtige für die Fehlersuche in einem Text.

Hinein kommen Version, System, Schnittstellen, Funkgeräte-Einstellungen und die letzten
Protokollzeilen. **Nicht** hinein: Passwörter/Zugangsdaten und die geloggten QSOs.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
import time
from urllib.parse import quote

from . import APP_NAME, CONTACT_EMAIL, __version__
from .i18n import tr

SECRET = re.compile(r"pass|token|secret|api_?key|session|net_user", re.I)
HIDDEN = tr("(ausgeblendet)")
# Diese Einstellungen helfen bei der Fehlersuche (keine persönlichen Daten außer dem Rufzeichen)
CFG_KEYS = re.compile(r"^(rig_|wsjtx_|cluster_|language|theme|font_size|voice_|cw_|esm|"
                      r"backup_|rules_|daily_|autocq_|open_|map_|callbook_enabled|livescore_enabled)")


def clean(value, key: str = ""):
    """Zugangsdaten in Einstellungen ausblenden (auch verschachtelt)."""
    if key and SECRET.search(key):
        return HIDDEN if value else value
    if isinstance(value, dict):
        return {k: clean(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def os_name(path: str = "/etc/os-release") -> str:
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.system()


def _cmd(args: list[str]) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=5)
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr) else ""
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return ""


def system_lines() -> list[str]:
    lines = [f"{APP_NAME} {__version__}" + (" (Beta-AppImage)" if os.environ.get("APPIMAGE") else ""),
             tr("Zeit (UTC): {t}", t=time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())),
             f"System: {os_name()} · Kernel {platform.release()} · {platform.machine()}",
             f"Desktop: {os.environ.get('XDG_CURRENT_DESKTOP', '?')} · "
             f"{os.environ.get('XDG_SESSION_TYPE', '?')}",
             f"Python {platform.python_version()}"]
    try:
        import PySide6
        from PySide6 import QtCore
        lines.append(f"PySide6 {PySide6.__version__} · Qt {QtCore.qVersion()}")
    except Exception:  # noqa: BLE001
        lines.append("PySide6: ?")
    import shutil
    exe = shutil.which("rigctld")
    lines.append(f"rigctld: {exe or tr('nicht gefunden')}"
                 + (f" · {_cmd([exe, '--version'])}" if exe else ""))
    try:
        from . import rigservice
        sysd = rigservice.system_rigctld()
        if sysd and sysd != exe:
            lines.append(tr("rigctld vom System: {p}", p=sysd))
    except Exception:  # noqa: BLE001
        pass
    return lines


def port_lines(ports=None, sysfs: str = "/sys", proc: str = "/proc") -> list[str]:
    from . import dxp, hamlib
    ports = hamlib.serial_ports() if ports is None else ports
    if not ports:
        return [tr("keine seriellen/USB-Schnittstellen gefunden")]
    out = []
    for p in ports:
        i = dxp.usb_info(p, sysfs)
        real = os.path.realpath(p)
        usb = f"USB {i.get('vid', '?')}:{i.get('pid', '?')}" if i else "USB ?"
        if i.get("name"):
            usb += f" „{i['name']}“"
        if i and "iface" in i:
            usb += f" Nr. {i['iface']}"
        access = "" if os.access(real, os.R_OK | os.W_OK) else " · " + tr("kein Zugriff")
        out.append(f"{p} → {real} · {usb}{access}")
    if dxp.modemmanager_running(proc):
        out.append(tr("ModemManager läuft"))
    return out


def config_lines(cfg: dict) -> list[str]:
    out = []
    for k in sorted(cfg):
        if CFG_KEYS.match(k) and k != "rig_profiles":
            out.append(f"{k} = {clean(cfg[k], k)!r}")
    for n, p in enumerate(cfg.get("rig_profiles") or [], 1):
        out.append(tr("Profil {n}: {p}", n=n, p=clean(p)))
    return out


def build(cfg: dict, log_lines: list[str] | None = None, ports=None) -> str:
    """Den ganzen Bericht als Text."""
    if log_lines is None:
        from . import applog
        log_lines = applog.tail(150)

    def section(title, lines):
        return [f"== {title} ==", *lines, ""]
    try:
        ports_part = port_lines(ports)
    except Exception as e:  # noqa: BLE001
        ports_part = [f"? ({e})"]
    text = [tr("GoGoHam-Fehlerbericht – bitte an {mail} schicken", mail=CONTACT_EMAIL), ""]
    text += section(tr("Programm und System"), system_lines())
    text += section(tr("Schnittstellen"), ports_part)
    text += section(tr("Einstellungen (ohne Passwörter)"), config_lines(cfg))
    text += section(tr("Letzte Meldungen"), log_lines or [tr("(noch keine)")])
    return "\n".join(text)


def mailto(subject: str, body: str = "") -> str:
    url = f"mailto:{CONTACT_EMAIL}?subject={quote(subject)}"
    return url + (f"&body={quote(body)}" if body else "")


def subject(kind: str, call: str = "") -> str:
    base = f"{APP_NAME} {__version__}" + (f" – {call}" if call else "")
    return f"{base} – {kind}" if kind else base


def file_name() -> str:
    return time.strftime("gogoham-fehlerbericht-%Y%m%d-%H%M%S.txt")


if __name__ == "__main__":                       # zum Ausprobieren: python -m gogoham.bugreport
    from . import config
    sys.stdout.write(build(config.load()) + "\n")
