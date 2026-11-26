"""Super Check Partial: Datenbank aktiver Contest-Rufzeichen (MASTER.SCP)."""

from __future__ import annotations

from .i18n import tr

import os
from pathlib import Path

SCP_URL = "https://www.supercheckpartial.com/MASTER.SCP"
MIN_CHARS = 3


def user_scp_path() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "gogoham" / "MASTER.SCP"


class ScpDB:
    def __init__(self, calls: list[str] | None = None) -> None:
        self.calls: list[str] = sorted(set(calls or []))
        self.source = ""

    @classmethod
    def parse(cls, text: str) -> "ScpDB":
        calls = []
        for line in text.splitlines():
            line = line.strip().upper()
            if not line or line.startswith("#"):
                continue
            calls.append(line.split()[0])
        return cls(calls)

    @classmethod
    def from_file(cls, path: str | Path) -> "ScpDB":
        db = cls.parse(Path(path).read_text(encoding="latin-1"))
        db.source = str(path)
        return db

    @classmethod
    def load_default(cls) -> "ScpDB | None":
        p = user_scp_path()
        if p.is_file():
            try:
                return cls.from_file(p)
            except OSError:
                return None
        return None

    def __len__(self) -> int:
        return len(self.calls)

    def search(self, partial: str, extra: set[str] | None = None, limit: int = 300) -> list[str]:
        """Alle Rufzeichen, die den Teilstring enthalten – alphabetisch.

        `extra` sind zusätzliche Rufzeichen (z. B. aus dem eigenen Log).
        """
        partial = (partial or "").strip().upper()
        if len(partial) < MIN_CHARS:
            return []
        hits = {c for c in self.calls if partial in c}
        if extra:
            hits |= {c for c in extra if partial in c}
        return sorted(hits)[:limit]


def download(dest: Path | None = None, url: str = SCP_URL, timeout: float = 30) -> Path:
    import urllib.request

    dest = dest or user_scp_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "GoGoHam"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if len(ScpDB.parse(data.decode("latin-1"))) < 1000:
        raise ValueError(tr("Heruntergeladene Datei sieht nicht wie eine MASTER.SCP aus"))
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest
