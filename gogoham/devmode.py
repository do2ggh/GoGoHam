"""Bereich „Entwicklung“ (ab 0.10.21): Funktionen zum Ausprobieren, die noch nicht für alle sind.

Im Einstellungsfenster öffnet Strg+Umschalt+E eine Passwortabfrage; danach erscheint der Bereich
bis zum Ende von GoGoHam. Eingeschaltete Funktionen bleiben eingeschaltet (Einstellung
„dev_features“) – nur das Ändern braucht das Passwort.

Ehrlich: GoGoHam ist quelloffen. Das Passwort hält normale Nutzer fern, nicht Neugierige mit dem
Quelltext. Gespeichert ist nur eine Prüfsumme (PBKDF2), nie das Passwort selbst.

Prüfsumme erzeugen:  python3 -m gogoham.devmode
"""

from __future__ import annotations

import hashlib
import hmac
import os

from .i18n import tr

# „pbkdf2_sha256$Runden$Salz$Prüfsumme“ – leer = Bereich lässt sich nicht öffnen
PASSWORD_HASH = ("pbkdf2_sha256$200000$9fb18935c005d088763fd05748fa9317$"
                 "7e1010a34b1bb5d78e38aada0d5ef7aff17f2c404c1d89cc3fe604fad62a690d")

_unlocked = False


def features() -> list[tuple[str, str, str]]:
    """(Schlüssel, Name, Erklärung) aller freischaltbaren Funktionen."""
    return [
        ("free_log", tr("Freies Log (kein Contest)"),
         tr("Steht dann ganz oben in „Neues Contest-Log“: Rufzeichen, RST und Bemerkung, keine "
            "Punkte, „schon gearbeitet“, ADIF-Export. Vorhandene freie Logs lassen sich immer "
            "öffnen.")),
    ]


def make_hash(password: str, rounds: int = 200_000, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${dk.hex()}"


def check(password: str, stored: str | None = None) -> bool:
    stored = PASSWORD_HASH if stored is None else stored
    try:
        algo, rounds, salt, want = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), want)


def available(stored: str | None = None) -> bool:
    return bool(PASSWORD_HASH if stored is None else stored)


def unlock(password: str, stored: str | None = None) -> bool:
    global _unlocked
    if check(password, stored):
        _unlocked = True
    return _unlocked


def is_unlocked() -> bool:
    return _unlocked


def lock() -> None:
    global _unlocked
    _unlocked = False


def enabled(name: str, cfg: dict | None = None) -> bool:
    """Ist die Funktion eingeschaltet? (ohne cfg: aus der gespeicherten Einstellung)"""
    if cfg is None:
        from . import config as cfgmod
        cfg = cfgmod.load()
    return bool((cfg.get("dev_features") or {}).get(name))


if __name__ == "__main__":                       # Prüfsumme für PASSWORD_HASH erzeugen
    import getpass
    a = getpass.getpass("Neues Entwickler-Passwort: ")
    b = getpass.getpass("Noch einmal: ")
    if not a or a != b:
        raise SystemExit("Nicht gleich oder leer – nichts erzeugt.")
    print("\nDiese Zeile an Claude geben (sie verrät das Passwort nicht):\n")
    print(make_hash(a))
