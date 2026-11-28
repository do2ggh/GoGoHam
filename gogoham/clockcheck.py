"""Geht die PC-Uhr richtig? (ab 0.8.18.3)

Fragt einen Zeitserver (pool.ntp.org, SNTP über UDP 123) und vergleicht mit der PC-Uhr.
Ohne Internet: kein Ergebnis, keine Warnung.

Stellen der Uhr: Linux macht das selbst (Zeitdienst systemd-timesyncd oder chrony). GoGoHam
schaltet ihn nur ein und lässt ihn sofort nachstellen – über `pkexec`, das nach dem Passwort
fragt. Ohne pkexec gibt es die Befehle zum Kopieren.
"""

from __future__ import annotations

import shlex
import shutil
import socket
import struct
import threading
import time

from .i18n import num, tr

SERVER = "pool.ntp.org"
LIMIT_S = 2.0                  # ab so viel Abweichung warnen
INTERVAL_S = 3600              # einmal pro Stunde prüfen
_NTP_EPOCH = 2208988800        # 1900 → 1970


def _ts(data: bytes, pos: int) -> float:
    sec, frac = struct.unpack("!II", data[pos:pos + 8])
    return sec - _NTP_EPOCH + frac / 2 ** 32


def offset(server: str = SERVER, timeout: float = 3.0, sock_factory=None) -> float | None:
    """Abweichung in Sekunden (positiv = PC-Uhr geht nach), None ohne Antwort."""
    factory = sock_factory or (lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
    try:
        s = factory()
        try:
            s.settimeout(timeout)
            packet = b"\x23" + 47 * b"\0"          # Version 4, Client
            t1 = time.time()
            s.sendto(packet, (server, 123))
            data, _addr = s.recvfrom(512)
            t4 = time.time()
        finally:
            s.close()
    except OSError:
        return None
    if len(data) < 48 or data[1] == 0:           # Stratum 0 = „Kiss of death“ / ungültig
        return None
    t2, t3 = _ts(data, 32), _ts(data, 40)
    return ((t2 - t1) + (t3 - t4)) / 2


class Checker(threading.Thread):
    """offset() im Hintergrund; Ergebnis danach in .result (None = keine Antwort)."""

    def __init__(self, server: str = SERVER):
        super().__init__(daemon=True, name="clockcheck")
        self.server = server
        self.result: float | None = None

    def run(self) -> None:
        try:
            self.result = offset(self.server)
        except Exception:  # noqa: BLE001
            self.result = None


def is_wrong(off: float | None, limit: float = LIMIT_S) -> bool:
    return off is not None and abs(off) > limit


def describe(off: float) -> str:
    sec = round(abs(off), 1)           # erst runden: 119,97 s → „2 Minuten“, nicht „120,0 Sekunden“
    amount = tr("{n} Sekunden", n=num(sec, 1)) if sec < 120 else \
        tr("{n} Minuten", n=num(sec / 60))
    return tr("Die Uhr deines PCs geht {amount} nach.", amount=amount) if off > 0 else \
        tr("Die Uhr deines PCs geht {amount} vor.", amount=amount)


def sync_script(which=shutil.which) -> str:
    """Befehle, die den Zeitdienst einschalten und die Uhr sofort stellen ("" = keiner da)."""
    parts = []
    if which("timedatectl"):
        parts.append("timedatectl set-ntp true")
    if which("chronyc"):
        parts += ["sleep 2", "chronyc -a burst 4/4", "sleep 6", "chronyc -a makestep"]
    elif which("timedatectl"):
        parts.append("systemctl restart systemd-timesyncd")
    return "; ".join(parts)


def sync_command(which=shutil.which) -> list[str] | None:
    """Aufruf zum Stellen (fragt über pkexec nach dem Passwort) – None, wenn das nicht geht."""
    script = sync_script(which)
    if not script or not which("pkexec"):
        return None
    return ["pkexec", "/bin/sh", "-c", script]


def manual_commands(which=shutil.which) -> str:
    """Dieselben Befehle zum Kopieren ins Terminal."""
    script = sync_script(which)
    if not script:
        return ""
    return f"sudo sh -c {shlex.quote(script)}"

