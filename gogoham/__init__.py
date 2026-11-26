"""GoGoHam – ein schlanker Contest-Logger für Linux.

© 2026 Franz, DO2GGH · SPDX-License-Identifier: GPL-3.0-only
Zusatzbedingungen nach § 7 GPL-3.0: ADDITIONAL-TERMS.md · Fremde Teile: THIRD-PARTY.md
"""

__version__ = "0.10.47.4"
APP_NAME = "GoGoHam"
APP_TITLE = "GoGoHam by DO2GGH"
CONTACT_EMAIL = "do2ggh.de@gmail.com"     # Kontakt-Knopf und Fehlerbericht (nur vor 1.0)
DONATE_URL = "https://paypal.me/GoGoHam"      # Hilfe → „Spendier DO2GGH einen Kaffee“ (0.8.28.4)


def is_prerelease(version: str | None = None) -> bool:
    """Vor 1.0? Dann gibt es den Knopf „Kontakt zu DO2GGH“."""
    try:
        return int((version or __version__).split(".")[0]) < 1
    except ValueError:
        return True
