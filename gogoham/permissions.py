"""Zugriff auf Schnittstellen (USB-Seriell) unter Linux (ab 0.10.1).

Linux erlaubt /dev/ttyUSB* & Co. nur Mitgliedern einer Gruppe (Arch: uucp, Debian/Ubuntu:
dialout). GoGoHam nennt den Befehl mit dem echten Benutzernamen (ohne „$USER“) und kann ihn
per pkexec selbst ausführen – nach dem Systempasswort. Wirksam wird es erst nach dem
nächsten Anmelden.
"""

from __future__ import annotations

import getpass
import grp
import os


def user() -> str:
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return os.environ.get("USER", "")


def group_of(path: str) -> str:
    try:
        return grp.getgrgid(os.stat(path).st_gid).gr_name
    except (KeyError, OSError):
        return "uucp"


def blocked(paths) -> list[str]:
    """Schnittstellen, die es gibt, die wir aber nicht öffnen dürfen."""
    return [p for p in paths if p and p.startswith("/dev/") and os.path.exists(p)
            and not os.access(p, os.R_OK | os.W_OK)]


def member_not_active(group: str) -> bool:
    """Schon in der Gruppe eingetragen, aber die Anmeldung ist älter (Gruppe noch nicht aktiv)."""
    try:
        g = grp.getgrnam(group)
    except KeyError:
        return False
    return user() in g.gr_mem and g.gr_gid not in os.getgroups()


def command(group: str) -> str:
    return f"sudo usermod -aG {group} {user()}"


def fix_command(group: str) -> list[str]:
    return ["pkexec", "usermod", "-aG", group, user()]


# --- Freigabe-Regel (ab 0.10.25) ----------------------------------------------------------
# Statt Gruppe: eine udev-Regel mit „uaccess“ gibt USB-Seriell-Geräte dem angemeldeten
# Benutzer – sofort, ohne neu anmelden. Die Pakete bringen sie mit (/usr/lib/udev/rules.d);
# ohne Paket (AppImage, install.sh) spielt GoGoHam sie nach dem Systempasswort selbst ein.
RULE_NAME = "70-gogoham.rules"
RULE_DIRS = ("/etc/udev/rules.d", "/usr/lib/udev/rules.d", "/lib/udev/rules.d")
RULE_TARGET = "/etc/udev/rules.d/" + RULE_NAME
SERIAL_GROUPS = ("uucp", "dialout")


def rule_text() -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parent / "assets" / RULE_NAME).read_text(encoding="utf-8")


def rule_installed(dirs=RULE_DIRS) -> bool:
    return any(os.path.isfile(os.path.join(d, RULE_NAME)) for d in dirs)


def uaccess_supported(seats: str = "/run/systemd/seats", which=None) -> bool:
    """Hat das System die Freigabe für den angemeldeten Benutzer (systemd-logind + udev)?"""
    import shutil
    which = which or shutil.which
    return os.path.isdir(seats) and bool(which("udevadm")) and bool(which("pkexec"))


def in_serial_group() -> bool:
    """In uucp/dialout – und das gilt in dieser Anmeldung auch schon."""
    gids = set(os.getgroups())
    for name in SERIAL_GROUPS:
        try:
            if grp.getgrnam(name).gr_gid in gids:
                return True
        except KeyError:
            continue
    return False


def access_ok(dirs=RULE_DIRS) -> bool:
    """Darf GoGoHam (voraussichtlich) USB-Seriell-Geräte öffnen?"""
    return os.geteuid() == 0 or rule_installed(dirs) or in_serial_group()


RULE_SCRIPT = ('umask 022; mkdir -p /etc/udev/rules.d && printf "%s" "$1" > ' + RULE_TARGET +
               ' && udevadm control --reload-rules && udevadm trigger --action=change '
               "--subsystem-match=tty --sysname-match='ttyUSB*' --sysname-match='ttyACM*'")


def rule_command(text: str | None = None) -> list[str]:
    """Regel einspielen (pkexec: Systempasswort). Der Inhalt geht als Argument mit – root kann
    eine Datei im AppImage (FUSE) oft nicht lesen."""
    return ["pkexec", "/bin/sh", "-c", RULE_SCRIPT, "sh", text if text is not None else rule_text()]
