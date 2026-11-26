"""Länderdatei cty.dat (AD1C, country-files.com) einlesen und Rufzeichen auflösen.

Die CQ-Variante der cty.dat enthält auch die WAE-Gebiete (mit * markiert,
z. B. *TA1, *GM/s, *IT9), genau wie es der CQ WW verlangt.
"""

from __future__ import annotations

from .i18n import tr

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path

CTY_URL = "https://www.country-files.com/cty/cty.dat"
CSV_URL = "https://www.country-files.com/cty/cty.csv"

# WAE-Gebiete zählen für DXCC zum „Mutterland“
WAE_PARENT = {"*TA1": "TA", "*GM/S": "GM", "*IT9": "I", "*IG9": "I",
              "*JW/B": "JW", "*4U1V": "OE"}

# Stichproben zur Plausibilitätsprüfung der DXCC-Nummern aus cty.csv
_DXCC_CHECK = {"DL": 230, "K": 291, "JA": 339, "VK": 150, "G": 223}

# Suchorte für eine vorhandene cty.dat (erste gefundene gewinnt)
def candidate_paths() -> list[Path]:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return [
        data_home / "gogoham" / "cty.dat",
        Path(__file__).resolve().parent / "data" / "cty.dat",
        Path("/usr/share/wsjtx/cty.dat"),
        Path("/usr/local/share/wsjtx/cty.dat"),
        Path("/usr/share/tlf/cty.dat"),
        Path("/usr/local/share/tlf/cty.dat"),
    ]


def user_cty_path() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "gogoham" / "cty.dat"


def user_csv_path() -> Path:
    return user_cty_path().with_name("cty.csv")


def parse_dxcc_csv(text: str) -> dict[str, int]:
    """cty.csv: Präfix, Name, DXCC-Nummer, … -> {Präfix: DXCC-Nummer}.

    Gibt ein leeres Dict zurück, wenn die Stichproben nicht passen – lieber
    keine DXCC-Nummer im Export als eine falsche.
    """
    out: dict[str, int] = {}
    for line in text.splitlines():
        cols = [c.strip() for c in line.split(",")]
        if len(cols) > 3 and cols[2].isdigit():
            out[cols[0].upper()] = int(cols[2])
    for pfx, num in _DXCC_CHECK.items():
        if out.get(pfx) != num:
            return {}
    return out


@dataclass(frozen=True)
class Entity:
    name: str
    cq: int
    itu: int
    cont: str
    lat: float
    lon: float      # in der cty.dat ist West positiv – hier schon umgerechnet (Ost positiv)
    tz: float
    prefix: str     # Hauptpräfix, z. B. "DL" oder "*TA1"


@dataclass(frozen=True)
class Lookup:
    entity: Entity | None
    cq: int | None
    itu: int | None
    cont: str | None
    maritime: bool = False
    lat: float | None = None
    lon: float | None = None   # Ost positiv
    # Russische Station in der Antarktis (RI1AN…): Land bleibt Antarktis, im Russian DX zählt
    # sie aber wie das europäische Russland (Reglement 7.3, ab 0.10.28)
    ru_antarctic: bool = False

    @property
    def country(self) -> str | None:
        return self.entity.prefix if self.entity else None

    @property
    def name(self) -> str:
        if self.maritime:
            return "Maritime Mobile"
        return self.entity.name if self.entity else "?"


_ALIAS_RE = re.compile(
    r"^(?P<exact>=)?(?P<pfx>[A-Z0-9/]+)"
    r"(?P<mods>(?:\(\d+\)|\[\d+\]|<[^>]*>|\{[A-Z]{2}\}|~[^~]*~)*)$"
)

# Länder, die sich über mehrere CQ-Zonen erstrecken (WAZ). Die cty.dat enthält
# nicht für alle diese Länder die Zonen-Ausnahmen – z. B. fehlt VK6/VK8 = Zone 29.
# Bei diesen Ländern wird die Zone im CQ WW nie vorbelegt, sondern muss
# gehört und eingetippt werden. Schlüssel = Hauptpräfix aus der cty.dat.
MULTI_ZONE: dict[str, set[int]] = {
    "K": {3, 4, 5},                 # USA
    "VE": {1, 2, 3, 4, 5},          # Kanada
    "VK": {29, 30},                 # Australien (VK6, VK8 = 29; VK1-5, VK7 = 30)
    "UA": {16, 17},                 # Europäisches Russland
    "UA9": {16, 17, 18, 19, 23},    # Asiatisches Russland
    "BY": {23, 24},                 # China
    "CE9": {12, 13, 29, 30, 32, 38, 39},  # Antarktis
}

# Länder mit mehreren ITU-Zonen, die die cty.dat (wie bei den CQ-Zonen) nicht vollständig
# kennt – z. B. führt sie die USA nur mit Zone 8. Dort wird die ITU-Zone nie vorbelegt
# (IARU HF) und im ADIF nur geschrieben, wenn sie gehört wurde.
MULTI_ITU: dict[str, set[int]] = {
    "K": {6, 7, 8},                 # USA
    "KL": {1, 2}, "KL7": {1, 2},    # Alaska
    "VE": {2, 3, 4, 9, 75},         # Kanada
    "UA": {19, 20, 29, 30},         # Europäisches Russland
    "UA9": {20, 21, 22, 23, 24, 25, 26, 30, 31, 32, 33, 34, 35, 75},  # Asiatisches Russland
    "BY": {33, 42, 43, 44},         # China
    "VK": {55, 58, 59},             # Australien
    "PY": {12, 13, 15},             # Brasilien
    "LU": {14, 16},                 # Argentinien
    "CE": {14, 16},                 # Chile
    "UN": {29, 30, 31},             # Kasachstan
    "OX": {5, 75},                  # Grönland
    "CE9": {67, 69, 70, 71, 72, 73, 74},  # Antarktis
}

# Suffixe, die das Land nicht verändern
IGNORE_SUFFIXES = {"P", "M", "QRP", "QRPP", "A", "B", "LH", "J", "R", "T", "X",
                   "AE", "AG", "KT", "N", "E", "PM", "QRO", "EMCOM"}
MARITIME = {"MM", "AM"}


class CtyDB:
    def __init__(self) -> None:
        # Wert: (Gebiet, CQ, ITU, Kontinent, lat, lon)
        self.prefixes: dict[str, tuple] = {}
        self.exact: dict[str, tuple] = {}
        self.entities: list[Entity] = []
        self.version: str = ""
        self.zones: dict[str, set[int]] = {}   # Hauptpräfix -> mögliche CQ-Zonen
        self.itu_zones: dict[str, set[int]] = {}
        self.dxcc: dict[str, int] = {}          # Hauptpräfix -> DXCC-Nummer (aus cty.csv)
        self.source: str = ""
        self._maxlen = 0

    # ---------------------------------------------------------------- laden
    @classmethod
    def from_file(cls, path: str | Path) -> "CtyDB":
        db = cls()
        db.parse(Path(path).read_text(encoding="latin-1"))
        db.source = str(path)
        db.load_dxcc()
        return db

    def load_dxcc(self, path: Path | None = None) -> bool:
        path = path or user_csv_path()
        if path.is_file():
            try:
                self.dxcc = parse_dxcc_csv(path.read_text(encoding="latin-1"))
            except OSError:
                self.dxcc = {}
        return bool(self.dxcc)

    def name_for_prefix(self, prefix: str) -> str:
        """Englischer Name eines Gebiets aus der Länderdatei (z. B. "DL" -> "Fed. Rep. of Germany")."""
        for e in self.entities:
            if e.prefix == prefix:
                return e.name
        return prefix

    def dxcc_info(self, lk: "Lookup | None") -> tuple[int | None, str]:
        """(DXCC-Nummer, englischer DXCC-Name) – WAE-Gebiete zählen zum Mutterland."""
        if lk is None or lk.entity is None:
            return None, ""
        pfx = lk.entity.prefix
        parent = WAE_PARENT.get(pfx)
        name = lk.entity.name
        if parent:
            for e in self.entities:
                if e.prefix == parent:
                    name = e.name
                    break
            pfx = parent
        return self.dxcc.get(pfx), name

    @classmethod
    def load_default(cls) -> "CtyDB | None":
        for p in candidate_paths():
            if p.is_file():
                try:
                    return cls.from_file(p)
                except Exception:  # noqa: BLE001 – kaputte Datei, nächste probieren
                    continue
        return None

    def parse(self, text: str) -> None:
        # Datensätze enden mit ';'. Kopfzeile: 8 Felder mit ':' getrennt.
        for record in text.split(";"):
            record = record.strip()
            if not record:
                continue
            parts = record.split(":")
            if len(parts) < 9:
                continue
            name = parts[0].strip()
            try:
                cq = int(parts[1])
                itu = int(parts[2])
                cont = parts[3].strip().upper()
                lat = float(parts[4])
                lon = -float(parts[5])
                tz = float(parts[6])
            except ValueError:
                continue
            prefix = parts[7].strip().upper()
            ent = Entity(name, cq, itu, cont, lat, lon, tz, prefix)
            self.entities.append(ent)
            self.zones.setdefault(prefix, set()).add(cq)
            self.itu_zones.setdefault(prefix, set()).add(itu)
            aliases = ":".join(parts[8:])
            for raw in aliases.replace("\n", " ").split(","):
                raw = raw.strip().upper()
                if not raw:
                    continue
                m = _ALIAS_RE.match(raw)
                if not m:
                    continue
                a_cq, a_itu, a_cont, a_lat, a_lon = cq, itu, cont, lat, lon
                mods = m.group("mods") or ""
                for la, lo in re.findall(r"<(-?[\d.]+)/(-?[\d.]+)>", mods):
                    a_lat, a_lon = float(la), -float(lo)
                for z in re.findall(r"\((\d+)\)", mods):
                    a_cq = int(z)
                for z in re.findall(r"\[(\d+)\]", mods):
                    a_itu = int(z)
                for z in re.findall(r"\{([A-Z]{2})\}", mods):
                    a_cont = z
                key = m.group("pfx")
                val = (ent, a_cq, a_itu, a_cont, a_lat, a_lon)
                if m.group("exact"):
                    self.exact[key] = val
                else:
                    self.prefixes[key] = val
                    self.zones.setdefault(prefix, set()).add(a_cq)
                    self.itu_zones.setdefault(prefix, set()).add(a_itu)
                    self._maxlen = max(self._maxlen, len(key))
        # Versions-Eintrag (=VERyyyymmdd)
        for k in self.exact:
            if k.startswith("VER") and k[3:].isdigit():
                self.version = k[3:]
                break

    def zones_for(self, lk: "Lookup | None") -> set[int]:
        """Alle CQ-Zonen, die für das Land dieses Rufzeichens vorkommen."""
        if lk is None or lk.entity is None:
            return set()
        zones = set(self.zones.get(lk.entity.prefix, {lk.entity.cq}))
        zones |= MULTI_ZONE.get(lk.entity.prefix, set())
        return zones

    def multi_zone(self, lk: "Lookup | None") -> bool:
        return len(self.zones_for(lk)) > 1

    def multi_itu(self, lk: "Lookup | None") -> bool:
        if lk is None or lk.entity is None:
            return True
        zones = set(self.itu_zones.get(lk.entity.prefix, {lk.entity.itu}))
        zones |= MULTI_ITU.get(lk.entity.prefix, set())
        return len(zones) > 1

    # -------------------------------------------------------------- auflösen
    def _longest(self, s: str):
        for n in range(min(len(s), self._maxlen), 0, -1):
            v = self.prefixes.get(s[:n])
            if v:
                return v
        return None

    @staticmethod
    def _mk(v) -> Lookup:
        ent, cq, itu, cont, lat, lon = v
        return Lookup(ent, cq, itu, cont, lat=lat, lon=lon)

    def lookup(self, call: str) -> Lookup | None:
        lk = self._lookup(call)
        if lk is not None and lk.country == "CE9" and any(
                p.startswith("RI1AN") for p in (call or "").strip().upper().split("/")):
            return replace(lk, ru_antarctic=True)
        return lk

    def _lookup(self, call: str) -> Lookup | None:
        call = (call or "").strip().upper()
        if not call:
            return None
        if call in self.exact:
            return self._mk(self.exact[call])

        parts = [p for p in call.split("/") if p]
        if any(p in MARITIME for p in parts[1:]):
            return Lookup(None, None, None, None, maritime=True)
        # unwichtige Suffixe entfernen (nur hinten, nicht beim ersten Teil)
        while len(parts) > 1 and parts[-1] in IGNORE_SUFFIXES:
            parts.pop()
        stripped = "/".join(parts)
        if stripped in self.exact:
            return self._mk(self.exact[stripped])
        if not parts:
            return None
        if len(parts) == 1:
            v = self._longest(parts[0])
            return self._mk(v) if v else None

        a, b = parts[0], parts[1]
        # W1ABC/4 oder UA1ABC/9: Rufzeichengebiet wechseln
        if b.isdigit() and len(b) == 1:
            m = re.match(r"^([A-Z0-9]*?[A-Z])(\d+)(.*)$", a)
            if m:
                swapped = m.group(1) + b + m.group(3)
                v = self._longest(swapped)
                if v:
                    return self._mk(v)
            v = self._longest(a)
            return self._mk(v) if v else None
        # Präfix-Teil = der kürzere (DL/W1ABC, W1ABC/KH6); bei Gleichstand der erste
        designator = a if len(a) <= len(b) else b
        if designator in self.prefixes:
            return self._mk(self.prefixes[designator])
        v = self._longest(designator)
        if v:
            return self._mk(v)
        v = self._longest(a)
        return self._mk(v) if v else None


def download(dest: Path | None = None, url: str = CTY_URL, timeout: float = 20) -> Path:
    """Aktuelle cty.dat herunterladen und speichern. Gibt den Pfad zurück."""
    import urllib.request

    dest = dest or user_cty_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "GoGoHam"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    # Plausibilitätsprüfung
    text = data.decode("latin-1")
    test = CtyDB()
    test.parse(text)
    if len(test.entities) < 300:
        raise ValueError(tr("Heruntergeladene Datei sieht nicht wie eine cty.dat aus"))
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    download_csv(dest.with_name("cty.csv"), timeout=timeout)
    return dest


def download_csv(dest: Path | None = None, timeout: float = 20) -> bool:
    """cty.csv (enthält die DXCC-Nummern) – Fehler sind nicht schlimm."""
    import urllib.request

    dest = dest or user_csv_path()
    try:
        req = urllib.request.Request(CSV_URL, headers={"User-Agent": "GoGoHam"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        if not parse_dxcc_csv(data.decode("latin-1")):
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except Exception:  # noqa: BLE001
        return False
