"""E-Mail-Programm öffnen (ab 0.10.42.1).

Unter KDE reicht Qt einen ``mailto:``-Link an KDE weiter. KDE baut daraus selbst einen Startbefehl
für das eingestellte Programm – mit Thunderbird aus Flatpak geht das schief („… ist kein
Flatpak-Befehl“), und es passiert gar nichts. ``xdg-open`` fragt dagegen nur, welches Programm für
E-Mail-Links eingestellt ist, und startet es so, wie es installiert ist (Paket, Flatpak, Snap).
Deshalb geht GoGoHam unter Linux über ``xdg-open``; fehlt es, bleibt der Weg über Qt.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading


def open_mail(url: str, fallback=None, run=subprocess.Popen, which=shutil.which,
              platform: str | None = None) -> bool:
    """``url`` (mailto:…) öffnen. ``fallback(url) -> bool`` = bisheriger Weg (Qt)."""
    if (platform or sys.platform).startswith("linux"):
        exe = which("xdg-open")
        if exe:
            try:
                p = run([exe, url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError:
                p = None
            if p is not None:
                if hasattr(p, "wait"):            # Prozess abholen, damit kein Zombie bleibt
                    threading.Thread(target=p.wait, daemon=True).start()
                return True
    return bool(fallback(url)) if fallback else False


def qt_open(url: str) -> bool:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    return QDesktopServices.openUrl(QUrl(url))
