"""Protokolldatei von GoGoHam (ab 0.8.18.3) – für den Fehlerbericht.

Hier landen die Hinweise der Hinweisleiste, Verbindungsmeldungen und Abstürze (mit
Python-Fehlertext). Keine QSOs, keine Passwörter. Die Datei bleibt klein: höchstens
3 × 512 KB, ältere Teile werden überschrieben.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

LOG = logging.getLogger("gogoham")
MAX_BYTES = 512 * 1024
_last = ""


def log_path() -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state / "gogoham" / "gogoham.log"


def setup(path: Path | None = None) -> Path | None:
    """Protokoll einschalten und Abstürze mitschreiben. Klappt das nicht, läuft GoGoHam ohne."""
    path = path or log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=2,
                                                 encoding="utf-8")
    except OSError:
        return None
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s",
                                     "%Y-%m-%d %H:%M:%S"))
    for old in list(LOG.handlers):
        LOG.removeHandler(old)
        old.close()
    LOG.addHandler(h)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False

    old_hook = sys.excepthook

    def hook(etype, value, tb):
        LOG.critical("Absturz", exc_info=(etype, value, tb))
        old_hook(etype, value, tb)
    sys.excepthook = hook

    old_thread_hook = threading.excepthook

    def thread_hook(args):
        LOG.error("Fehler im Hintergrund (%s)", getattr(args.thread, "name", "?"),
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        old_thread_hook(args)
    threading.excepthook = thread_hook
    return path


def message(text: str, level: str = "info") -> None:
    """Eine Meldung mitschreiben (gleiche Meldung direkt hintereinander nur einmal)."""
    global _last
    text = (text or "").strip()
    if not text or text == _last:
        return
    _last = text
    lv = {"error": logging.ERROR, "warn": logging.WARNING}.get(level, logging.INFO)
    LOG.log(lv, "%s", text.replace("\n", " | "))


def tail(lines: int = 200, path: Path | None = None) -> list[str]:
    """Die letzten Zeilen des Protokolls (auch aus der vorigen Datei, wenn die neue kurz ist)."""
    path = path or log_path()
    out: list[str] = []
    for p in (path, Path(str(path) + ".1")):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                out = f.read().splitlines() + out          # ältere Datei kommt davor
        except OSError:
            continue
        if len(out) >= lines:
            break
    return out[-lines:]
