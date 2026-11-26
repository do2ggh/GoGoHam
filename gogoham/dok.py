"""DOK (Deutscher Ortsverbands-Kenner) – Form, Liste und Prüfung (ab 0.8.4).

DARC-Conteste (WAG, 10 m, Weihnachten, Ostern …): DL-Stationen senden ihren DOK, z. B.
„B36“ (Distrikt B, Ortsverband 36), einen Sonder-DOK (z. B. „750UEM“) oder „NM“
(kein Mitglied). Quellen:

* **Ortsverbände** (DARC A–Y, VFDB Z): eingebaut in ``gogoham/dok_ov.txt``; eine neuere
  Fassung kann heruntergeladen werden (``~/.local/share/gogoham/dok_ov.txt``).
* **Sonder-DOKs**: Liste des DARC-Referats S-DOK (``SDOK_List.csv``) mit Rufzeichen und
  Gültigkeitszeitraum – nur nach dem Herunterladen vorhanden.

Ein unbekannter DOK ist nie ein Fehler, sondern nur ein Hinweis („bitte gegenhören“):
Listen können veraltet sein, und neue Sonder-DOKs kommen ständig dazu.
"""

from __future__ import annotations

from .i18n import tr

import html
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

BUILTIN_OV = Path(__file__).with_name("dok_ov.txt")
SDOK_URL = "https://www.darc.de/fileadmin/filemounts/referate/sdok/SDOK_List.csv"
DISTRICTS_URL = "https://www.darc.de/der-club/distrikte/"
VFDB_URL = "https://www.vfdb.org/aktuell/organisation/bezirks-ortsverbaende/"
NO_MEMBER = "NM"

_OV_RE = re.compile(r"[A-Z]\d\d")
_SDOK_RE = re.compile(r"(?=.*[A-Z])[A-Z0-9]{2,8}")


def data_dir() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "gogoham"


def user_ov_path() -> Path:
    return data_dir() / "dok_ov.txt"


def user_sdok_path() -> Path:
    return data_dir() / "SDOK_List.csv"


def normalize(s: str) -> str:
    return (s or "").strip().upper()


def is_ov(dok: str) -> bool:
    """Regulärer DOK eines Ortsverbands: Buchstabe + zwei Ziffern (B36, Z12)."""
    return bool(_OV_RE.fullmatch(normalize(dok)))


def form_error(dok: str) -> str | None:
    """Fehlertext, wenn der Text nicht wie ein DOK aussieht (sonst None)."""
    d = normalize(dok)
    if re.fullmatch(r"[A-Z]\d", d):            # „B6“: Null vergessen – kein Sonder-DOK
        return tr("DOK hat drei Zeichen – „{d}“ bitte mit Null: {fixed}", d=d, fixed=d[0] + "0" + d[1])
    if d == NO_MEMBER or is_ov(d) or _SDOK_RE.fullmatch(d):
        return None
    return tr("DOK nötig (z. B. B36, Sonder-DOK oder NM)")


def counts(dok: str) -> bool:
    """Zählt der DOK als Multi? „NM“ nie."""
    d = normalize(dok)
    return bool(d) and d != NO_MEMBER and form_error(d) is None


def district(dok: str) -> str:
    """Distrikt = erster Buchstabe des DOK (auch bei Sonder-DOKs, z. B. 750UEM -> U)."""
    for ch in normalize(dok):
        if ch.isalpha():
            return ch
    return ""


def _date(s: str) -> date | None:
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})", (s or "").strip())
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    if y < 100:
        y += 2000 if y < 70 else 1900
    try:
        return date(y, mo, d)
    except ValueError:
        return None


@dataclass
class SpecialDok:
    call: str
    start: date | None
    end: date | None
    parent: str = ""


@dataclass
class DokDB:
    ov: dict[str, str] = field(default_factory=dict)              # DOK -> Name
    sdok: dict[str, list[SpecialDok]] = field(default_factory=dict)

    # ------------------------------------------------------------ laden
    def load_ov(self, text: str) -> int:
        n = 0
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            d, _, name = line.partition(";")
            d = normalize(d)
            if is_ov(d):
                self.ov[d] = name.strip()
                n += 1
        return n

    def load_sdok(self, text: str) -> int:
        n = 0
        for line in text.splitlines():
            parts = [p.strip() for p in line.split(";")]
            if len(parts) < 5:
                continue
            d = normalize(parts[0])
            if not _SDOK_RE.fullmatch(d):
                continue
            self.sdok.setdefault(d, []).append(SpecialDok(
                call=normalize(parts[2]), start=_date(parts[3]), end=_date(parts[4]),
                parent=normalize(parts[5]) if len(parts) > 5 else ""))
            n += 1
        return n

    @classmethod
    def load_default(cls) -> "DokDB":
        db = cls()
        for p in (BUILTIN_OV, user_ov_path()):          # heruntergeladene Fassung ergänzt
            try:
                db.load_ov(p.read_text(encoding="utf-8"))
            except OSError:
                pass
        try:
            db.load_sdok(user_sdok_path().read_bytes().decode("latin-1"))
        except OSError:
            pass
        return db

    @property
    def has_sdok(self) -> bool:
        return bool(self.sdok)

    def name(self, dok: str) -> str:
        return self.ov.get(normalize(dok), "")

    # ------------------------------------------------------------ prüfen
    def hint(self, dok: str, call: str = "", day: date | None = None) -> str | None:
        """Hinweis zu einem empfangenen DOK – oder None, wenn alles passt."""
        d = normalize(dok)
        if not d or d == NO_MEMBER or form_error(d):
            return None
        if is_ov(d):
            if self.ov and d not in self.ov:
                return tr("DOK {d} gibt es laut Liste nicht – bitte gegenhören", d=d)
            return None
        if not self.has_sdok:
            return None                     # ohne Sonder-DOK-Liste nichts sagen
        entries = self.sdok.get(d)
        if not entries:
            return tr("Sonder-DOK {d} ist unbekannt – bitte gegenhören", d=d)
        if day is not None:
            valid = [e for e in entries if (e.start is None or e.start <= day)
                     and (e.end is None or day <= e.end)]
            if not valid:
                last = max((e.end for e in entries if e.end), default=None)
                return (tr("Sonder-DOK {d} galt nur bis {end}", d=d, end=last.strftime("%d.%m.%Y"))
                        if last else tr("Sonder-DOK {d} gilt an diesem Tag nicht", d=d))
            entries = valid
        c = normalize(call).split("/")
        base = max(c, key=len) if c and c[0] else ""
        calls = sorted({e.call for e in entries if e.call})
        if base and calls and base not in calls:
            shown = ", ".join(calls[:3]) + (" …" if len(calls) > 3 else "")
            return tr("Sonder-DOK {d} ist für {calls} vergeben", d=d, calls=shown)
        return None


# ---------------------------------------------------------------- herunterladen
def parse_districts_page(text: str) -> dict[str, str]:
    """Ortsverbände aus der Distrikt-Übersicht des DARC (Links …/distrikte/b/ortsverbaende/36/)."""
    out: dict[str, str] = {}
    for m in re.finditer(r'<a[^>]+href="/der-club/distrikte/([a-z])/ortsverbaende/(\d\d)/"[^>]*>'
                         r'(.*?)</a>', text, re.S):
        d = m.group(1).upper() + m.group(2)
        name = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", m.group(3)))).strip()
        name = re.sub(r"^Ortsverband\s+", "", name)
        name = re.sub(r"\s*\([A-Z]\d\d\)\s*$", "", name)
        out.setdefault(d, name)
    return out


def parse_vfdb_page(text: str) -> list[str]:
    return sorted(set(re.findall(r"\bZ\d\d\b", text)))


def _get(url: str, timeout: float) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "GoGoHam"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def download(timeout: float = 30) -> tuple[int, int]:
    """Ortsverbände und Sonder-DOK-Liste neu laden. Ergebnis: (Anzahl OV-DOKs, Sonder-DOKs).

    Sieht eine Quelle unplausibel aus (Seite umgebaut?), bleibt die alte Liste."""
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    raw = _get(SDOK_URL, timeout)
    test = DokDB()
    n_s = test.load_sdok(raw.decode("latin-1"))
    if n_s < 1000:
        raise ValueError(tr("Die Sonder-DOK-Liste sieht nicht vollständig aus"))
    tmp = user_sdok_path().with_suffix(".tmp")
    tmp.write_bytes(raw)
    tmp.replace(user_sdok_path())
    ov = parse_districts_page(_get(DISTRICTS_URL, timeout).decode("utf-8", "replace"))
    try:
        z = parse_vfdb_page(_get(VFDB_URL, timeout).decode("utf-8", "replace"))
    except OSError:
        z = []
    n_o = 0
    if len(ov) >= 800:                      # sonst Seite umgebaut – eingebaute Liste gilt weiter
        lines = ["# DOK-Liste (heruntergeladen von darc.de und vfdb.org)"]
        lines += [f"{k};{v}" for k, v in sorted(ov.items())]
        lines += [f"{k};VFDB" for k in z]
        tmp = user_ov_path().with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(user_ov_path())
        n_o = len(ov) + len(z)
    return n_o, len(test.sdok)


def age_days(today: date | None = None) -> int | None:
    """Alter der heruntergeladenen Sonder-DOK-Liste in Tagen (None = nicht vorhanden)."""
    p = user_sdok_path()
    if not p.is_file():
        return None
    from datetime import datetime
    mod = datetime.fromtimestamp(p.stat().st_mtime).date()
    return ((today or date.today()) - mod).days
