"""Flaggen als PNG-Bilder (flagcdn.com / Flagpedia, frei nutzbar).

Einmalig herunterladen, danach liegen sie dauerhaft unter
~/.local/share/gogoham/flags/ – kein Emoji-Font und kein Internet mehr nötig.
"""

from __future__ import annotations

from .i18n import tr

import os
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .countries import all_flag_codes

FLAG_URL = "https://flagcdn.com/w80/{code}.png"


def flags_dir() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "gogoham" / "flags"


def flag_path(code: str) -> Path | None:
    if not code:
        return None
    p = flags_dir() / f"{code}.png"
    return p if p.is_file() else None


def missing_codes() -> list[str]:
    return [c for c in all_flag_codes() if flag_path(c) is None]


class FlagDownloader(threading.Thread):
    """Lädt fehlende Flaggen im Hintergrund. Fortschritt in .done / .total."""

    def __init__(self, codes: list[str] | None = None, workers: int = 8):
        super().__init__(daemon=True, name="flags")
        self.codes = codes if codes is not None else missing_codes()
        self.total = len(self.codes)
        self.done = 0
        self.failed: list[str] = []
        self.workers = workers
        self._lock = threading.Lock()

    def _one(self, code: str) -> None:
        try:
            req = urllib.request.Request(FLAG_URL.format(code=code),
                                         headers={"User-Agent": "GoGoHam"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read()
            if not data.startswith(b"\x89PNG"):
                raise ValueError(tr("kein PNG"))
            target = flags_dir() / f"{code}.png"
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
        except Exception:  # noqa: BLE001 – einzelne Flagge fehlt, dann Ersatz-Schild
            with self._lock:
                self.failed.append(code)
        finally:
            with self._lock:
                self.done += 1

    def run(self) -> None:
        flags_dir().mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            list(ex.map(self._one, self.codes))
