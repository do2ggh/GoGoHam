"""GoGoHandy-PC-Brücke mitbenutzen (seit 0.10.40).

Die Brücke von GoGoHandy hält Icom-Geräte dauerhaft und exklusiv offen und verteilt die
CI-V-Befehle von Handy und PC. Für jedes gehaltene Gerät gibt es eine virtuelle Schnittstelle
(pty), über die man ganz normal CI-V spricht:

* fest je Gerät: ``$XDG_RUNTIME_DIR/gogohandy/by-id/<Name aus /dev/serial/by-id/>``
* nach Modell (ältere Brücke, nur Ausweichweg): ``$XDG_RUNTIME_DIR/gogohandy/<modell>``

GoGoHam nimmt diese Schnittstelle überall dort, wo es sonst das echte Gerät öffnen würde
(Erkennen, Verbindung testen, rigctld starten, Hintergrund-Dienste). Die Brücke wird nie
angehalten oder übernommen – sonst wäre die Handy-Verbindung weg.
"""
from __future__ import annotations

import os
import re

COMM = "gogohandy-bruec"           # /proc/<pid>/comm (auf 15 Zeichen gekürzt)
UNIT = "gogohandy-bruecke.service"
BAUD = 115200                      # die Brücke spricht fest mit 115200 Baud zum Gerät


def root(uid: int | None = None) -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") if uid is None else None
    return os.path.join(base or f"/run/user/{os.getuid() if uid is None else uid}", "gogohandy")


def _by_id(path: str) -> str:
    from .rigdetect import stable_name
    s = stable_name(path)
    return s if s.startswith("/dev/serial/by-id/") else ""


def link_name(path: str, base: str | None = None) -> str:
    """Fester Pfad der virtuellen Schnittstelle für dieses Gerät ("" = kein fester Name)."""
    s = _by_id(path)
    return os.path.join(base or root(), "by-id", os.path.basename(s)) if s else ""


def held_by_bridge(path: str, proc: str = "/proc") -> bool:
    """Hält die GoGoHandy-Brücke dieses Gerät offen?"""
    want = os.path.realpath(path)
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return False
    for pid in pids:
        try:
            with open(os.path.join(proc, pid, "comm")) as f:
                if f.read().strip() != COMM:
                    continue
            fd_dir = os.path.join(proc, pid, "fd")
            if any(os.path.realpath(os.path.join(fd_dir, fd)) == want for fd in os.listdir(fd_dir)):
                return True
        except OSError:
            continue
    return False


def pty_for(path: str, base: str | None = None, proc: str = "/proc") -> str:
    """Virtuelle Schnittstelle der Brücke für dieses Gerät – "" = Brücke hält es nicht."""
    if not path or not path.startswith("/dev/") or path.startswith("/dev/pts/"):
        return ""
    base = base or root()
    link = link_name(path, base)
    if link and os.path.exists(link):
        return link
    if not held_by_bridge(path, proc):
        return ""
    from .rigdetect import usb_guess
    name = re.sub(r"[^a-z0-9]", "", usb_guess(path).lower())
    cand = os.path.join(base, name) if name else ""
    return cand if cand and os.path.exists(cand) else ""


def resolve(path: str, **kw) -> str:
    """Pfad, den GoGoHam öffnen soll: die virtuelle Schnittstelle der Brücke oder das Gerät."""
    return pty_for(path, **kw) or path
