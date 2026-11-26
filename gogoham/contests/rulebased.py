"""Contest aus einer Regel-Datei (siehe gogoham/rulefiles.py).

Die Regel-Datei sagt, welche Bausteine benutzt werden und mit welchen Zahlen.
Die Rechenwege dafür stehen hier – übernommen aus den früheren Klassen
CqWw, Wpx und WwDigi (bis 0.6.0), damit die Punkte exakt gleich bleiben.
"""

from __future__ import annotations

from ..i18n import tr

from pathlib import Path

import re
from datetime import datetime

from .. import dok as dokmod
from .. import regions
from ..rulefiles import _hhmm
from ..bands import band_label, cabrillo_mode
from ..cty import WAE_PARENT, Lookup
from ..locator import (center4, grid_distance_km, iaru_km, is_grid4, is_grid6,
                       normalize)
from .base import Contest, Qso
from .wpx import wpx_prefix

# Interne Multi-Schlüssel (werden in Infobox, Übersicht, Live-Score benutzt)
MULT_KEY = {"cq_zone": "zone", "country": "country", "wpx_prefix": "prefix",
            "grid_field": "field", "us_state": "state", "ve_province": "province",
            "xe_state": "xe", "itu_region": "region", "itu_zone": "itu", "iaru_hq": "hq",
            "lic_year": "year", "dok": "dok", "dok_district": "district",
            "call_area": "area", "ru_oblast": "oblast", "iota_ref": "iota",
            "district": "subdiv", "member": "member", "arrl_section": "section",
            "continent": "cont", "grid_square": "square", "county": "county",
            "join_year": "joinyear", "calls": "call"}
MULT_LABEL = {"zone": tr("Zonen"), "country": tr("Länder"), "prefix": tr("Präfixe"),
              "field": tr("Großfelder"), "state": tr("States"), "province": tr("Provinzen"),
              "xe": tr("XE-States"), "region": tr("ITU-Regionen"), "itu": tr("ITU-Zonen"),
              "hq": tr("Verbände"), "year": tr("Jahrgänge"), "dok": tr("DOKs"),
              "district": tr("Distrikte"), "area": tr("Rufzeichengebiete"),
              "oblast": tr("Oblaste"), "iota": tr("IOTA-Referenzen"),
              "subdiv": tr("Provinzen/Bezirke"), "member": tr("Mitglieder"),
              "section": tr("Sections"), "cont": tr("Kontinente"),
              "square": tr("Locator-Quadrate"), "county": tr("Countys"),
              "joinyear": tr("Beitrittsjahre"), "call": tr("Sonderstationen")}
EXCHANGE_LABEL = {"cq_zone": tr("Zone"), "serial": tr("Nr"), "grid4": tr("Loc"),
                  "location": tr("Austausch"),
                  "iaru": tr("Zone"), "lic_year": tr("Jahr"),
                  "age": tr("Alter"), "serial_grid6": tr("Nr/Loc"),
                  "serial_member": tr("Nr/Mitgl"), "serial_class": tr("Nr/Klasse"),
                  "serial_class_member": tr("Nr/Kl/Mitgl"), "dok_grid6": tr("DOK/Loc"),
                  "member": tr("Mitgl"), "serial_time": tr("Nr/Zeit"),
                  "ss": tr("Nr/Prec/Ck/Sec"), "serial_name": tr("Nr/Name"),
                  "serial_zone": tr("Nr/Zone"), "qso_party": tr("County"),
                  "member_year": tr("Nr/Jahr"), "serial_class_name": tr("Nr/Kl/Name/Alter")}
KIND_LABEL = {"state": tr("State"), "province": tr("Provinz"), "cq_zone": tr("CQ-Zone"),
              "power": tr("Leistung"), "serial": tr("Nummer"), "xe_state": tr("XE-State"),
              "itu_region": tr("ITU-Region"), "dok": tr("DOK"), "serial_dok": tr("Nummer + DOK"),
              "oblast": tr("Oblast"), "serial_iota": tr("Nummer + IOTA"),
              "district": tr("Kürzel"), "serial_district": tr("Nummer + Kürzel"),
              "itu_zone": tr("ITU-Zone"), "zone_state": tr("Zone + State"),
              "zone_province": tr("Zone + Provinz"), "dok_or_serial": tr("DOK oder Nummer"),
              "arrl_section": tr("Section"), "district_or_serial": tr("Kürzel oder Nummer"),
              "name": tr("Name"), "name_qth": tr("Name + QTH"), "country": tr("Land")}
# „none“ (Format 17): die Gegenstation sendet nur den Rapport (ARRL 160: DX-Stationen) –
# steht bewusst nicht in KIND_LABEL, damit nichts „erfragt“ werden soll
# Beschriftungen, die in den eingebauten Regel-Dateien stehen (für die Übersetzung)
_RULE_LABELS = (tr("Jahr"), tr("Zone"), tr("St/Zone"), tr("St/Pwr"), tr("St/Nr"),
                tr("DOK/Nr"), tr("Nr/DOK"), tr("Nr/Oblast"), tr("Nr/IOTA"),
                tr("Nr/Prov"), tr("Nr/Kom"), tr("Nr/Bez"), tr("Nr/Sek"), tr("Zone/Bez"),
                tr("Zone/Kürz"), tr("Nr/Dép"), tr("Nr/Kreis"), tr("Zone/St"))
# Contest-Namen aus eingebauten Regel-Dateien, die übersetzt werden (für die Übersetzung)
_NAMES = (tr("DIG-QSO-Party Kurzwelle SSB"), tr("DIG-QSO-Party Kurzwelle CW"),
          tr("Deutscher Telegrafie Contest (DTC)"),
          tr("DARC VHF-/UHF-/SHF-Wettbewerb (März, Mai, Juli)"), tr("DARC UKW-Frühlingswettbewerb"),
          tr("DARC Mikrowellen-Wettbewerb (Juni)"), tr("DARC UKW-Winter-Fieldday"),
          tr("DARC UKW-Sommer-Fieldday"),
          tr("Bayerischer Bergtag – Sommer (Mai), 10 GHz und ab 24 GHz"),
          tr("Bayerischer Bergtag – Sommer (August), 2 m bis 6 cm"),
          tr("Bayerischer Bergtag – Winter, 2 m bis 6 cm"),
          tr("Bayerischer Bergtag – Winter, 10 GHz und ab 24 GHz"),
          tr("Frankencontest – Klasse A: 80/40 m CW"),
          tr("Frankencontest – Klasse B: 80/40 m SSB"),
          tr("Frankencontest – Klasse C: 80 m CW, 100 Watt"),
          tr("Frankencontest – Klasse D: 80 m SSB, 100 Watt"),
          tr("Frankencontest – Klasse E: 10 m CW"),
          tr("Frankencontest – Klasse F: 10 m SSB"),
          tr("Frankencontest – Klasse K: 2 m"),
          tr("Schwaben-Contest – Kurzwelle (80/40 m)"), tr("Schwaben-Contest – UKW (2 m/70 cm)"),
          tr("Frankencontest – Klasse L: 70 cm"),
          tr("AGCW QRP/QRP-Party"),
          tr("VFDB DLPX-Contest – CW (Januar)"), tr("VFDB DLPX-Contest – SSB (März)"),
          tr("AGCW Handtastenparty 80 m (Februar)"), tr("AGCW Handtastenparty 40 m (September)"),
          tr("AGCW Schlackertasten-Abend (STA)"),
          tr("RSGB 1st 1.8 MHz Contest (Februar, CW + SSB)"), tr("RSGB 2nd 1.8 MHz Contest (November, CW)"),
          tr("PODXS 070 Club Triple Play DOUBLEHEADER (Dezember)"), tr("UN DX Contest (Kasachstan)"))
CONT_NAME = {"AF": tr("Afrika"), "AN": tr("Antarktis"), "AS": tr("Asien"), "EU": tr("Europa"),
             "NA": tr("Nordamerika"), "OC": tr("Ozeanien"), "SA": tr("Südamerika")}
# Gebiete der QSO-Partys aus den eingebauten Regel-Dateien (für die Übersetzung)
_AREAS = (tr("in Neuengland"), tr("im 7. US-Rufzeichengebiet"))
_DOKDB: "dokmod.DokDB | None" = None


def dok_db() -> "dokmod.DokDB":
    """DOK-Liste (einmal geladen; nach dem Herunterladen mit reload_doks() neu lesen)."""
    global _DOKDB
    if _DOKDB is None:
        _DOKDB = dokmod.DokDB.load_default()
    return _DOKDB


def reload_doks() -> None:
    global _DOKDB
    _DOKDB = None


def split_serial_dok(exch: str) -> tuple[str, str]:
    """„12 B36“ -> ("12", "B36"); auch „B36 12“; nur „12“ -> ("12", "")."""
    serial, dok = "", ""
    for part in (exch or "").strip().upper().split():
        if part.isdigit() and not serial:
            serial = part
        elif not dok:
            dok = part
    return serial, dok


IOTA_RE = re.compile(r"(AF|AN|AS|EU|NA|OC|SA)-?(\d{1,3})")


def normalize_iota(s: str) -> str:
    """IOTA-Referenz vereinheitlichen: „eu5“, „EU005“, „EU-005“ -> „EU-005“ (sonst "")."""
    m = IOTA_RE.fullmatch((s or "").strip().upper())
    return f"{m.group(1)}-{int(m.group(2)):03d}" if m else ""


def split_serial_grid(exch: str) -> tuple[str, str]:
    """„12 JO20DB“ (auch „JO20DB 12“) -> ("12", "JO20DB"); fehlende Teile = ""."""
    serial, grid = "", ""
    for part in (exch or "").strip().upper().split():
        if part.isdigit() and not serial:
            serial = part
        elif not grid:
            grid = part
    return serial, grid


def split_name_qth(exch: str) -> tuple[str, str]:
    """NAQP: „BOB CT“ -> ("BOB", "CT"); nur ein Wort -> (Wort, "")."""
    parts = (exch or "").strip().upper().split()
    if not parts:
        return "", ""
    return parts[0], (parts[-1] if len(parts) > 1 else "")


def split_serial_time(exch: str) -> tuple[str, str]:
    """BARTG: „156 1749“ -> ("156", "1749"); fehlende Teile = ""."""
    parts = (exch or "").strip().split()
    serial = parts[0] if parts and parts[0].isdigit() else ""
    t = parts[1] if len(parts) > 1 else ""
    return serial, t


SS_PRECEDENCE = ("Q", "A", "B", "U", "M", "S")


def split_ss(exch: str) -> tuple[str, str, str, str]:
    """ARRL Sweepstakes: „43 M W1AW 31 CT“ oder „43 M 31 CT“ -> („43“, „M“, „31“, „CT“).
    Reihenfolge wie in der Ausschreibung: Nummer, Precedence, (Rufzeichen), Check, Section.
    Fehlende oder unpassende Teile = ""."""
    parts = (exch or "").strip().upper().split()
    serial = prec = check = sec = ""
    i = 0
    if i < len(parts) and parts[i].isdigit():
        serial, i = parts[i], i + 1
    elif i < len(parts) and re.fullmatch(r"(\d+)([QABUMS])", parts[i]):   # „43M“
        m = re.fullmatch(r"(\d+)([QABUMS])", parts[i])
        serial, prec, i = m.group(1), m.group(2), i + 1
    if not prec and i < len(parts) and parts[i] in SS_PRECEDENCE:
        prec, i = parts[i], i + 1
    rest = parts[i:]
    if rest and regions.normalize_section(rest[-1]):
        sec = regions.normalize_section(rest[-1])
        rest = rest[:-1]
    digits = [x for x in rest if re.fullmatch(r"\d\d", x)]
    if digits:
        check = digits[-1]
    return serial, prec, check, sec


def split_serial_name(exch: str) -> tuple[str, str]:
    """SARTG Neujahr: „049 VLAD“ -> („049“, „VLAD“); fehlende Teile = ""."""
    parts = (exch or "").strip().upper().split()
    serial = parts[0] if parts and parts[0].isdigit() else ""
    name = " ".join(parts[1:] if serial else parts)
    return serial, name


def split_serial_zone(exch: str) -> tuple[str, str]:
    """„001 14“ -> ("001", "14") – Nummer und CQ-Zone (Volta); fehlt etwas: ""."""
    parts = re.findall(r"\d+", exch or "")
    if len(parts) != 2:
        return (parts[0] if parts else ""), ""
    zone = parts[1]
    return parts[0], (str(int(zone)) if 1 <= int(zone) <= 40 else "")


def split_member_year(exch: str) -> tuple[str, str]:
    """PODXS NMJ: „483 2006“ -> ("483", "2006"); Nichtmitglieder senden irgendetwas -> ("", "")."""
    m = re.fullmatch(r"\s*(\d{1,5})\s+((?:19|20)\d\d)\s*", exch or "")
    return (str(int(m.group(1))), m.group(2)) if m else ("", "")


def call_suffix(call: str) -> str:
    """Suffix eines Rufzeichens: die Buchstaben nach der letzten Ziffer des Grundrufzeichens
    (W4KRN -> KRN, DL/W4KRN/P -> KRN); leer, wenn es keins gibt."""
    parts = [p for p in (call or "").upper().split("/") if re.search(r"\d", p)]
    if not parts:
        return ""
    m = re.search(r"\d([A-Z]+)$", max(parts, key=len))
    return m.group(1) if m else ""


def _is_hhmm(t: str) -> bool:
    return bool(re.fullmatch(r"([01]\d|2[0-3])[0-5]\d", t or ""))


def split_serial_iota(exch: str) -> tuple[str, str]:
    """„12 EU005“ -> ("12", "EU-005"); nur „12“ -> ("12", ""); unbekannter Rest -> ("12", "?")."""
    serial, ref = "", ""
    for part in (exch or "").strip().upper().split():
        if part.isdigit() and not serial:
            serial = part
        elif not ref:
            ref = normalize_iota(part) or "?"
    return serial, ref


def normalize_district(code: str, host: dict | None) -> str:
    """Kürzel im Gastgeberland prüfen ("bp" -> "BP"); "" wenn es nicht passt."""
    t = (code or "").strip().upper()
    if not t or not host:
        return ""
    if host.get("pattern"):                   # DTC: Kfz-Kennzeichen mit Umlaut (PLÖ = PLOE)
        t = t.replace("Ä", "AE").replace("Ö", "OE").replace("Ü", "UE")
    codes = host.get("codes")
    if codes is not None:
        if t not in codes and t.isdigit() and len(t) == 1 and "0" + t in codes:
            t = "0" + t                           # REF: Departement „1“ = „01“
        return t if t in codes else ""
    pat = host.get("pattern")
    return t if pat and re.fullmatch(pat, t) else ""


def _codes_hint(host: dict | None) -> str:
    codes = (host or {}).get("codes") or []
    return ", ".join(codes[:4]) if codes else "ABC"


def split_zone_qth(exch: str) -> tuple[str, str]:
    """„05 MA“ -> („5“, „MA“); ohne gültige Zone („“, …)."""
    parts = (exch or "").strip().upper().split()
    if len(parts) >= 2 and parts[0].isdigit() and 1 <= int(parts[0]) <= 40:
        return str(int(parts[0])), " ".join(parts[1:])
    return "", " ".join(parts)


def _check_kind(kind: str, exch: str, host: dict | None = None) -> str | None:
    """Fehlertext, wenn der empfangene Austausch nicht zur Art passt (sonst None)."""
    e = (exch or "").strip().upper()
    if kind == "district":
        return None if normalize_district(e, host) else \
            tr("Kürzel nötig (z. B. {codes})", codes=_codes_hint(host))
    if kind == "serial_district":
        serial, code = split_serial_dok(e)
        if not serial:
            return tr("Nummer und Kürzel nötig, z. B. „12 {code}“", code=_codes_hint(host).split(",")[0])
        if not normalize_district(code, host):
            return tr("Kürzel fehlt oder passt nicht (z. B. {codes})", codes=_codes_hint(host))
        return None
    if kind in ("zone_state", "zone_province"):        # CQ WW RTTY: „05 MA“, „04 ON“
        zone, rest = split_zone_qth(e)
        if not zone:
            return tr("Zone (1–40) und State/Provinz nötig, z. B. „05 MA“")
        ok = regions.normalize_state(rest) if kind == "zone_state" else \
            regions.normalize_province(rest)
        if not ok:
            return tr("Nach der Zone fehlt der US-State (z. B. 05 MA)") if kind == "zone_state" \
                else tr("Nach der Zone fehlt die Provinz (z. B. 04 ON)")
        return None
    if kind in ("none", "country"):                    # nur Rapport bzw. Land (aus dem Rufzeichen)
        return None
    if kind == "district_or_serial":                   # RAC: Provinz, VE0 eine Nummer
        return None if e.isdigit() or normalize_district(e, host) else \
            tr("Kürzel (z. B. {codes}) oder Nummer nötig", codes=_codes_hint(host))
    if kind == "name":                                 # NAQP: nur der Vorname
        return None if re.fullmatch(r"[A-Z][A-Z0-9-]{0,11}", e) else \
            tr("Vorname nötig (ein Wort, z. B. BOB)")
    if kind == "name_qth":                             # NAQP: Name + State/Provinz/Präfix
        name, qth = split_name_qth(e)
        if not (name and qth and re.fullmatch(r"[A-Z][A-Z0-9-]{0,11}", name)
                and re.fullmatch(r"[A-Z0-9]{1,5}", qth)):
            return tr("Name und State/Provinz/Präfix nötig, z. B. „BOB CT“")
        return None
    if kind == "serial_time":                          # BARTG HF: Nummer + Uhrzeit
        serial, t = split_serial_time(e)
        if not serial or not _is_hhmm(t):
            return tr("Nummer und Uhrzeit (UTC, vierstellig) nötig, z. B. „156 1749“")
        return None
    if kind == "ss":                                   # ARRL Sweepstakes (Format 19)
        serial, prec, check, sec = split_ss(e)
        if not (serial and prec and check and sec):
            miss = [lab for ok, lab in ((serial, tr("Nummer")), (prec, tr("Precedence")),
                                        (check, tr("Check")), (sec, tr("Section"))) if not ok]
            return tr("Nummer, Precedence (Q/A/B/U/M/S), Check und Section nötig, z. B. "
                      "„43 M 31 CT“ – es fehlt: {miss}", miss=", ".join(miss))
        return None
    if kind == "serial_zone":                          # Volta: Nummer + CQ-Zone
        serial, zone = split_serial_zone(e)
        if not serial or not zone or not re.fullmatch(r"\d+\s+\d+", e):
            return tr("Nummer und CQ-Zone (1–40) nötig, z. B. „001 14“")
        return None
    if kind == "serial_name":                          # SARTG Neujahr: Nummer + Name
        serial, name = split_serial_name(e)
        if not serial or not name:
            return tr("Nummer und Name nötig, z. B. „049 VLAD“")
        return None
    if kind == "arrl_section":
        return None if regions.normalize_section(e) else \
            tr("ARRL/RAC-Section nötig (z. B. EMA, NTX, ONS)")
    if kind == "state":
        return None if regions.normalize_state(e) else tr("US-State nötig (z. B. CT, TX)")
    if kind == "province":
        return None if regions.normalize_province(e) else tr("Kanadische Provinz nötig (z. B. ON, QC)")
    if kind == "cq_zone":
        return None if e.isdigit() and 1 <= int(e) <= 40 else tr("Zone muss zwischen 1 und 40 liegen")
    if kind == "power":
        return None if re.fullmatch(r"[0-9A-Z]{1,5}", e) else tr("Leistung nötig (z. B. 100 oder KW)")
    if kind == "serial":
        return None if e.isdigit() else tr("Bitte die empfangene Nummer eingeben")
    if kind == "xe_state":
        return None if regions.normalize_xe_state(e) else tr("Mexikanischer State nötig (z. B. JAL)")
    if kind == "itu_region":
        return None if e in ("1", "2", "3") else tr("ITU-Region 1, 2 oder 3 nötig")
    if kind == "itu_zone":
        return None if e.isdigit() and 1 <= int(e) <= 90 else \
            tr("ITU-Zone muss zwischen 1 und 90 liegen")
    if kind == "serial_member":
        serial, member = split_serial_member(e)
        if not serial:
            return tr("Nummer nötig, bei Mitgliedern dazu die Mitgliedsnummer, z. B. „067/2583“")
        if member and not member.isdigit():
            return tr("Mitgliedsnummer besteht nur aus Ziffern, z. B. „067/2583“")
        return None
    if kind == "iaru":
        if e.isdigit():
            return None if 1 <= int(e) <= 90 else tr("ITU-Zone muss zwischen 1 und 90 liegen")
        return None if re.fullmatch(r"[A-Z][A-Z0-9]{1,5}", e) else \
            tr("ITU-Zone (z. B. 28) oder Verbandskürzel (z. B. DARC) nötig")
    if kind == "lic_year":
        return None if re.fullmatch(r"\d\d", e) else \
            tr("Zwei Ziffern nötig – Jahr der ersten Lizenz (z. B. 82)")
    if kind == "serial_grid6":
        serial, grid = split_serial_grid(e)
        if not serial:
            return tr("Nummer und 6-stelliger Locator nötig, z. B. „12 JO20DB“")
        if not is_grid6(grid):
            return tr("6-stelliger Locator nötig (z. B. JO20DB)")
        return None
    if kind == "age":
        return None if re.fullmatch(r"\d\d", e) else \
            tr("Zwei Ziffern nötig – Alter des Operators (z. B. 59)")
    if kind == "oblast":
        return None if regions.normalize_oblast(e) else tr("Oblast-Kürzel nötig (z. B. MA, SP)")
    if kind == "serial_iota":
        serial, ref = split_serial_iota(e)
        if not serial:
            return tr("Nummer nötig, bei Inseln dazu die IOTA-Nummer, z. B. „12 EU005“")
        if ref == "?":
            return tr("IOTA-Nummer ungültig – z. B. EU005 oder EU-005")
        return None
    if kind == "dok":
        return dokmod.form_error(e)
    if kind == "dok_or_serial":               # Schwaben: DOK – ohne DOK die laufende Nummer
        return None if e.isdigit() else dokmod.form_error(e)
    if kind == "member":                      # HSC: Mitgliedsnummer oder „NM“
        return None if e.isdigit() or e == dokmod.NO_MEMBER else \
            tr("Mitgliedsnummer oder „NM“ nötig, z. B. „1688“ oder „NM“")
    if kind == "serial_dok":
        serial, d = split_serial_dok(e)
        if not serial:
            return tr("Nummer und DOK nötig, z. B. „12 B36“")
        if not d:
            return tr("DOK fehlt – Nummer und DOK mit Leerzeichen, z. B. „12 B36“")
        return dokmod.form_error(d)
    return None


def split_serial_class(exch: str) -> tuple[str, str, str]:
    """AGCW QRP: „001 QRP 1537“ → ("001", "QRP", "1537"), „027 MP NM“ → ("027", "MP", "NM");
    QRP-Party: „001 A“ (auch „001A“) → ("001", "A", ""). Passt nichts: ("", "", "")."""
    e = " ".join((exch or "").strip().upper().replace("/", " ").split())
    m = re.fullmatch(r"(\d+) ?([A-Z][A-Z0-9]{0,4})?(?: (\d+|NM))?", e)
    if not m:
        return "", "", ""
    return m.group(1), m.group(2) or "", m.group(3) or ""


def split_serial_class_name(exch: str) -> tuple[str, str, str, str]:
    """AGCW Handtastenparty: „001/B/HEINZ/84“ oder „001 A TOM XX“ → (Nr, Klasse, Name, Alter);
    das Alter ist freiwillig. Passt nichts: ("", "", "", "")."""
    e = " ".join((exch or "").strip().upper().replace("/", " ").split())
    m = re.fullmatch(r"(\d+) ([A-Z]) ([A-ZÄÖÜ][A-ZÄÖÜ-]*)(?: (\d{1,3}|XX))?", e)
    if not m:
        return "", "", "", ""
    return m.group(1), m.group(2), m.group(3), m.group(4) or ""


def split_dok_grid(exch: str) -> tuple[str, str]:
    """Frankencontest UKW: „B26 JN59NO“ → ("B26", "JN59NO"), „NM JN59NO“ → ("NM", "JN59NO")."""
    parts = (exch or "").strip().upper().split()
    if parts and is_grid6(parts[-1]):
        return dokmod.normalize(" ".join(parts[:-1])), parts[-1]
    return dokmod.normalize(" ".join(parts)), ""


def split_serial_member(exch: str) -> tuple[str, str]:
    """AGCW: „067/2583“ oder „067 2583“ → ("067", "2583"); ohne Mitgliedsnummer ("067", "")."""
    parts = (exch or "").strip().upper().replace("/", " ").split()
    serial = parts[0] if parts and parts[0].isdigit() else ""
    member = parts[1] if len(parts) > 1 and serial else ""
    return serial, member


def is_hq_call(call: str) -> bool:
    """Rufzeichen einer IARU-Verbandsstation? Fast alle enden auf „HQ“ (DA0HQ, OL9HQ …)."""
    parts = [p for p in (call or "").strip().upper().split("/") if p]
    return bool(parts) and max(parts, key=len).endswith("HQ")


PORTABLE_SUFFIXES = {"P", "M", "MM", "AM"}


def is_portable_call(call: str) -> bool:
    """Portabel-/Mobilstation nach Fieldday-Regel: Zusatz /P, /M, /MM oder /AM."""
    parts = [p for p in (call or "").strip().upper().split("/") if p]
    return len(parts) > 1 and any(p in PORTABLE_SUFFIXES for p in parts[1:])


def is_trainee_call(call: str) -> bool:
    """Einsteiger-Station (DARC Ausbildungscontest): Ausbildungsrufzeichen DN1–DN8 oder
    Einsteiger-Lizenz DO."""
    parts = [p for p in (call or "").strip().upper().split("/") if p]
    if not parts:
        return False
    base = max(parts, key=len)
    return bool(re.match(r"DN[1-8][A-Z]", base) or re.match(r"DO\d[A-Z]", base))


def is_club_call(call: str) -> bool:
    """Deutsche Klubstation: Ziffer 0 nach dem Präfix (DL0…, DK0…, DA0…, DF0 …)."""
    parts = [p for p in (call or "").strip().upper().split("/") if p]
    return bool(parts) and bool(re.match(r"D[A-R]0[A-Z]", max(parts, key=len)))


def is_training_call(call: str) -> bool:
    """Ausbildungsrufzeichen (DN1–DN8) – ohne Einsteiger-Lizenz DO (anders als is_trainee_call)."""
    parts = [p for p in (call or "").strip().upper().split("/") if p]
    return bool(parts) and bool(re.match(r"DN[1-8][A-Z]", max(parts, key=len)))


def in_window(when: str, start: str, end: str) -> bool:
    """Liegt die QSO-Zeit („YYYY-MM-DD HH:MM:SS“) im Fenster start–end (UTC „HHMM“, end
    gehört nicht mehr dazu; über Mitternacht möglich, z. B. 2300–0500)?"""
    t = (when or "")[11:16].replace(":", "")
    if len(t) != 4 or not t.isdigit():
        return False
    return start <= t < end if start <= end else (t >= start or t < end)


def _value(v, band: str) -> int:
    """Punktzahl: feste Zahl oder Tabelle je Band mit „default“."""
    if isinstance(v, dict):
        return int(v.get(band, v["default"]))
    return int(v)


class RuleContest(Contest):
    """Allgemeiner Contest. Unterklassen entstehen aus den Regel-Dateien."""

    rules: dict = {}
    rules_path: Path | None = None
    rules_builtin = True
    rules_source = "builtin"      # builtin / download / user / log
    rules_revision = 1
    exchange_kind = ""            # cq_zone / serial / grid4
    log_format = "cabrillo"
    rig_modes: set[str] | None = None
    min_break_minutes = 60
    location: dict | None = None  # „location“: Austausch-Art je Herkunft (us/ve/xe/dx/mm)
    us_entities: tuple = ("K",)   # welche Länder als „us“ zählen (ARRL 10 m: auch KL, KH6)
    contacts = "all"              # all / w_ve_dx / eu_only / dl_dx / eu_dx
    mode_limits: dict | None = None
    max_changes_per_hour: int | None = None
    max_changes_total: int | None = None
    band_segments: dict | None = None
    band_windows: list | None = None   # UKW-Fieldday: Band nur in seinem Zeitfenster (Format 10)
    require_portable = False           # eigenes Rufzeichen muss „/p“ tragen (Format 10)
    host: dict | None = None      # Gastgeberland (Format 7)
    blocked_countries: tuple = ()  # Länder, deren QSOs nicht zählen (UBA: Russland, Belarus)
    classes: tuple = ()           # Leistungsklassen im Austausch (Format 14, AGCW QRP)
    own_classes: tuple = ()       # Klassen, die die eigene Station wählen darf
    same_dok_zero = False         # QSOs mit dem eigenen DOK zählen 0 Punkte (Frankencontest)
    no_dok_serial = False         # „dok_grid6“: ohne DOK die laufende Nummer senden (Schwaben)
    dok_only_dl = False           # DOK nur in Deutschland, sonst „NM“ (Frankencontest, Format 16)
    call_points: dict | None = None   # feste Punkte für bestimmte Rufzeichen (Format 18)
    member_empty = False              # leerer Austausch = Nichtmitglied (DIG, Format 18)
    not_same_area: tuple = ()         # Volta: Länder, in denen nur das eigene Gebiet gesperrt ist
    extra_mult: dict | None = None    # Volta: {"min_bands": 4} (Format 20)
    qso_party: dict | None = None     # NEQP, 7QP: Gebiet, Staaten, Countys (Format 21)
    contacts_cont = ""                # „cont_only“: nur QSOs mit diesem Kontinent (Oceania)
    mobile_bonus: dict | None = None  # Texas: {"points": 500, "counties": 5} (Format 22)
    mult_bonus = 0                    # RSGB 1.8 MHz: Bonuspunkte je Multi (Format 22)
    bonus_calls: dict | None = None   # NCQP, Salmon Run: Bonus für bestimmte Rufzeichen (Format 23)
    suffix_bonus: dict | None = None  # St. Patrick's Day: Wörter aus Suffix-Buchstaben (Format 23)

    def __init__(self, cty, station) -> None:
        super().__init__(cty, station)
        # Multis, die für die eigene Station gelten (ARRL DX: DX zählt States, W/VE Länder)
        mults = [m for m in self.rules.get("multipliers", []) if self._when_ok(m.get("when"))]
        seen: list[tuple[str, str]] = []
        for m in mults:
            key = MULT_KEY[m["type"]]
            if (key, MULT_LABEL[key]) not in seen:
                seen.append((key, MULT_LABEL[key]))
        self.mult_types = seen
        self._mults = mults
        self.uses_serial = self.sent_kind() in ("serial", "serial_dok", "serial_iota",
                                                "serial_district", "serial_grid6",
                                                "serial_member", "serial_class", "serial_class_name",
                                                "serial_class_member", "serial_time", "ss",
                                                "serial_name", "serial_zone") \
            or (self.sent_kind() == "district_or_serial"
                and not normalize_district(self.station.district, self.host)) \
            or (self.sent_kind() == "dok_or_serial" or (self.sent_kind() == "dok_grid6"
                                                        and self.no_dok_serial)) \
            and not dokmod.normalize(self.station.dok)

    # --- Herkunft ------------------------------------------------------------
    def is_host(self, lk: Lookup | None) -> bool:
        """Station im Gastgeberland des Contests (Format 7)?"""
        h = self.host
        return bool(h) and lk is not None and not lk.maritime and \
            WAE_PARENT.get(lk.country, lk.country) in h["countries"]

    def _region(self, lk: Lookup | None) -> str | None:
        if self.host and self.is_host(lk):
            return "host"
        return regions.region(lk, self.us_entities)

    def own_region(self) -> str | None:
        r = self._region(self.station.lookup)
        return "dx" if r == "mm" else r

    def own_in_europe(self) -> bool:
        """Eigene Station in Europa? Ohne eigenes Rufzeichen: ja (die meisten Nutzer)."""
        me = self.station.lookup
        return me is None or me.cont == "EU"

    def own_in_asia(self) -> bool:
        """Eigene Station in Asien? Ohne eigenes Rufzeichen: nein."""
        me = self.station.lookup
        return me is not None and me.cont == "AS"

    def is_w_ve(self, lk: Lookup | None) -> bool:
        """Station in USA/Kanada – mit den Gebieten, die der Contest dazurechnet."""
        return self._region(lk) in ("us", "ve")

    def role(self) -> str:
        """„w_ve“ für Stationen in USA/Kanada, sonst „dx“."""
        return "w_ve" if self.own_region() in ("us", "ve") else "dx"

    def _when_ok(self, when: str | None) -> bool:
        """Gilt eine Angabe („when“) für die eigene Station?"""
        if when is None:
            return True
        if when in ("dl", "non_dl"):
            return (self.own_region() == "dl") == (when == "dl")
        if when in ("eu", "non_eu"):            # WAE: eigene Station in Europa oder nicht
            return self.own_in_europe() == (when == "eu")
        if when in ("as", "non_as"):            # All Asian: eigene Station in Asien oder nicht
            return self.own_in_asia() == (when == "as")
        if when in ("host", "non_host"):        # Länder-Contests: im Gastgeberland oder nicht
            return self.is_host(self.station.lookup) == (when == "host")
        return when == self.role()

    def _kind_for(self, reg: str | None) -> str | None:
        if self.exchange_kind != "location":
            return self.exchange_kind
        br = self.location or {}
        if reg is None:
            return None
        if reg == "mm":
            return br.get("mm") or br.get("dx")
        return br.get(reg) or br.get("dx")

    def sent_kind(self) -> str | None:
        return self._kind_for(self.own_region() or "dx")

    def expected_kind(self, lk: Lookup | None) -> str | None:
        """Welchen Austausch die Gegenstation sendet (cq_zone, state, province …)."""
        if self.exchange_kind != "location":
            return self.exchange_kind
        return self._kind_for(self._region(lk))

    def exchange_optional(self, lk: Lookup | None) -> bool:
        """Darf der empfangene Austausch leer bleiben? (ARRL 160: DX sendet nur RST;
        DIG: Nichtmitglieder geben nur den Rapport)"""
        kind = self.expected_kind(lk)
        return kind == "none" or (kind == "member" and self.member_empty)

    def contact_problem(self, q: Qso, lk: Lookup | None) -> str | None:
        """Grund, warum das QSO nicht zählt – ohne „zählt nicht:“ davor (das ergänzt die
        Anzeige selbst)."""
        me = self.station.lookup
        if self.contacts == "w_ve_dx" and lk is not None and me is not None:
            mine, theirs = regions.is_w_ve(me), regions.is_w_ve(lk)
            if mine == theirs:
                return (tr("W/VE arbeitet nur DX") if mine
                        else tr("DX arbeitet nur W/VE (USA/Kanada)"))
        if self.contacts == "host_dx" and lk is not None and me is not None \
                and self.is_host(me) == self.is_host(lk):
            hc = self.host["countries"]
            p = "/".join(hc[:4]) + (" …" if len(hc) > 4 else "")
            return (tr("Gastgeber untereinander zählen nicht (nur {p} ↔ Rest)", p=p)
                    if self.is_host(me) else tr("Zählt nur mit Stationen aus {p}", p=p))
        if self.contacts == "w_ve_only" and lk is not None and me is not None:
            if not self.is_w_ve(me):
                return tr("Nur Stationen in USA/Kanada nehmen an diesem Contest teil")
            if not self.is_w_ve(lk):
                return tr("Zählt nur mit Stationen in USA/Kanada (W/VE)")
        if self.contacts == "w_ve_any" and lk is not None and me is not None \
                and not self.is_w_ve(me) and not self.is_w_ve(lk):
            return tr("DX zählt nur mit W/VE (USA/Kanada)")    # ARRL 160: W/VE darf alle
        if self.contacts == "cont_only" and lk is not None and me is not None \
                and me.cont != self.contacts_cont and (lk.maritime or lk.cont != self.contacts_cont):
            c = CONT_NAME.get(self.contacts_cont, self.contacts_cont)
            return tr("Stationen außerhalb von {cont} werten nur QSOs mit {cont}", cont=c)
        if self.qso_party:
            if self.own_in_party_area():
                return tr("Für Stationen {area} rechnet GoGoHam diesen Contest nicht – nur für "
                          "Stationen außerhalb", area=self.party_area())
            if q.exch_r.strip() and not self.party_counties(q.exch_r):
                return tr("Zählt nur mit Stationen {area} (County-Kürzel)",
                          area=self.party_area())
            if q.exch_r.strip():
                bad = self.validate_exchange(q.exch_r, lk)   # zu viele Countys in einer Zeile
                if bad:
                    return bad
        if self.contacts == "not_same_area" and lk is not None and me is not None \
                and not lk.maritime and not me.maritime \
                and WAE_PARENT.get(lk.country, lk.country) == WAE_PARENT.get(me.country, me.country):
            # Volta: nicht im eigenen Land – in K/VE/JA/VK/ZL nur nicht im eigenen Gebiet
            if lk.country not in self.not_same_area:
                return tr("QSOs im eigenen Land zählen nicht")
            areas = {lk.country: lk.country}
            mine = call_area(self.station.call or "", me, areas)
            if not mine or mine == call_area(q.call, lk, areas):
                return tr("QSOs im eigenen Rufzeichengebiet zählen nicht")
        if self.contacts == "dl_dx" and lk is not None and me is not None \
                and self.own_region() != "dl" and regions.region(lk) != "dl":
            return tr("Stationen außerhalb Deutschlands werten nur QSOs mit DL")
        if self.contacts == "eu_only" and lk is not None and me is not None:
            if me.cont != "EU":
                return tr("eigene Station liegt nicht in Europa")
            if lk.maritime or lk.cont != "EU":
                return tr("Gegenstation nicht in Europa (nur EU–EU zählt)")
        if self.contacts == "eu_dx" and lk is not None and not lk.maritime:
            mine, theirs = self.own_in_europe(), lk.cont == "EU"
            if mine and theirs:
                return tr("Europa arbeitet im WAE nur Stationen außerhalb Europas")
            if not mine and not theirs:
                return tr("Stationen außerhalb Europas werten im WAE nur QSOs mit Europa")
        if lk is not None and not lk.maritime and \
                WAE_PARENT.get(lk.country, lk.country) in (self.blocked_countries or ()):
            return tr("QSOs mit {name} zählen in diesem Contest nicht", name=lk.name)
        if self.contacts == "host_only" and lk is not None and me is not None \
                and not self.is_host(me) and not self.is_host(lk) \
                and not (lk.maritime and "maritime" in self._points_block()):
            # (REF: /MM zählt auch für Ausländer – die Regeln geben dafür eigene Punkte)
            hc = self.host["countries"]
            return tr("Zählt nur mit Stationen des Gastgeberlands ({p})",
                      p="/".join(hc[:6]) + (" …" if len(hc) > 6 else ""))
        if self.contacts == "asia" and lk is not None:
            mine = self.own_in_asia()
            if not mine and (lk.maritime or lk.cont != "AS"):
                return tr("Stationen außerhalb Asiens werten nur QSOs mit Asien")
            if me is not None and not lk.maritime and lk.country == me.country:
                return tr("QSOs im eigenen Land zählen im All Asian nicht")
        lim = (self.mode_limits or {}).get(cabrillo_mode(q.mode))
        if lim and q.freq:
            khz = q.freq / 1000
            if "max_khz" in lim and khz >= lim["max_khz"]:
                mhz = f"{lim['max_khz'] / 1000:.3f}".replace(".", ",")
                return tr("{cabrillo_mode} nur unter {mhz} MHz", cabrillo_mode=cabrillo_mode(q.mode), mhz=mhz)
            if "min_khz" in lim and khz < lim["min_khz"]:
                mhz = f"{lim['min_khz'] / 1000:.3f}".replace(".", ",")
                return tr("{mode} erst ab {mhz} MHz", mode=cabrillo_mode(q.mode), mhz=mhz)
        return self.window_problem(q)

    def segment_problem(self, q: Qso) -> str | None:
        """Frequenz außerhalb der erlaubten bzw. in einem contestfreien Bereich?"""
        seg = (self.band_segments or {}).get(cabrillo_mode(q.mode))
        if not seg or not q.freq:
            return None
        khz = q.freq / 1000
        allowed = seg.get("allowed")
        band_ranges = [r for r in allowed or [] if _same_band(r, khz)]
        if allowed and band_ranges and not any(a <= khz <= b for a, b in band_ranges):
            txt = ", ".join(f"{a}–{b}" for a, b in band_ranges)
            return tr("{khz} kHz liegt außerhalb der Contest-Bereiche ({txt} kHz)",
                      khz=f"{khz:.1f}", txt=txt)
        for a, b in seg.get("forbidden") or []:
            if a <= khz <= b:
                return tr("{khz} kHz liegt im contestfreien Bereich {a}–{b} kHz",
                          khz=f"{khz:.1f}", a=a, b=b)
        return None

    def window_problem(self, q: Qso) -> str | None:
        """UKW-Fieldday: QSO auf einem Band außerhalb seines Zeitfensters?"""
        from ..bands import op_mode
        band_wins = [w for w in self.band_windows or [] if q.band in w["bands"]]
        if not band_wins or not q.time:
            return None
        om = op_mode(q.mode)
        wins = [w for w in band_wins if not w.get("modes") or om in w["modes"]]
        days = (tr("Mo"), tr("Di"), tr("Mi"), tr("Do"), tr("Fr"), tr("Sa"), tr("So"))

        def show(ws) -> str:
            return ", ".join(f"{days[w['weekday']]} {w['from'][:2]}:{w['from'][2:]}–"
                             f"{w['to'][:2]}:{w['to'][2:]}"
                             + (" " + "/".join(w["modes"]) if w.get("modes") else "") for w in ws)
        if not wins:                         # Format 15: Fenster gibt es nur für andere Arten
            return tr("{mode} auf {band} gibt es in diesem Contest nicht – nur: {txt} UTC",
                      mode=om, band=band_label(q.band), txt=show(band_wins))
        try:
            t = datetime.strptime(q.time[:16], "%Y-%m-%d %H:%M")
        except ValueError:
            return None
        mins = t.hour * 60 + t.minute
        for w in wins:
            lo, hi = _hhmm(w["from"]), _hhmm(w["to"])
            if t.weekday() == w["weekday"] and lo <= mins <= hi:
                return None
        if any(w.get("modes") for w in wins):
            return tr("{band} {mode} ist nur hier erlaubt: {txt} UTC",
                      band=band_label(q.band), mode=om, txt=show(wins))
        return tr("{band} ist nur hier erlaubt: {txt} UTC",
                  band=band_label(q.band), txt=show(wins))

    def portable_problem(self) -> str | None:
        """Fieldday: eigenes Rufzeichen ohne „/p“?"""
        call = (self.station.call or "").upper()
        if self.require_portable and call and not is_portable_call(call):
            return tr("Im Fieldday muss dein Rufzeichen „/p“ tragen (z. B. {call}/p) – "
                      "bitte in den Log-Einstellungen ändern", call=call)
        return None

    def sent_serial(self, exch_s: str) -> int | None:
        """Gesendete laufende Nummer aus dem gesendeten Austausch („007“, „007 B36“)."""
        if self.sent_kind() in ("ss", "serial_name"):
            serial = (split_ss(exch_s)[0] if self.sent_kind() == "ss"
                      else split_serial_name(exch_s)[0])
            return int(serial) if serial else None
        if self.sent_kind() == "serial_zone":
            serial = split_serial_zone(exch_s)[0]
            return int(serial) if serial else None
        if self.sent_kind() == "serial_time":
            serial = split_serial_time(exch_s)[0]
            return int(serial) if serial else None
        if self.sent_kind() == "serial_grid6":
            serial = split_serial_grid(exch_s)[0]
            return int(serial) if serial else None
        if self.sent_kind() == "serial_class_name":
            serial = split_serial_class_name(exch_s)[0]
            return int(serial) if serial else None
        if self.sent_kind() in ("serial_class", "serial_class_member"):
            serial = split_serial_class(exch_s)[0]
            return int(serial) if serial else None
        if self.sent_kind() in ("serial_dok", "serial_iota", "serial_district"):
            serial = (split_serial_iota if self.sent_kind() == "serial_iota"
                      else split_serial_dok)(exch_s)[0]
            return int(serial) if serial else None
        e = (exch_s or "").strip()
        return int(e) if e.isdigit() else None

    def rcvd_dok(self, q: Qso, lk: Lookup | None) -> str:
        """Empfangener DOK (leer, wenn die Gegenstation keinen sendet)."""
        kind = self.expected_kind(lk)
        if kind == "dok":
            return dokmod.normalize(q.exch_r)
        if kind == "serial_dok":
            return split_serial_dok(q.exch_r)[1]
        if kind == "dok_grid6":
            d = split_dok_grid(q.exch_r)[0]
            return "" if d.isdigit() else d
        if kind == "dok_or_serial":
            d = dokmod.normalize(q.exch_r)
            return "" if d.isdigit() else d
        return ""

    def rcvd_member(self, q: Qso, lk: Lookup | None) -> str:
        """Empfangene Mitgliedsnummer, „NM“ für Nicht-Mitglieder, "" wenn nichts Gültiges."""
        kind = self.expected_kind(lk)
        if kind == "member":
            e = (q.exch_r or "").strip().upper()
            if not e and self.member_empty:
                return dokmod.NO_MEMBER       # DIG: Nichtmitglieder geben nur den Rapport
            return e if e.isdigit() or e == dokmod.NO_MEMBER else ""
        if kind == "serial_member":
            return split_serial_member(q.exch_r)[1] or dokmod.NO_MEMBER
        if kind == "serial_class_member":
            return split_serial_class(q.exch_r)[2]
        return ""

    def rcvd_class(self, q: Qso) -> str:
        """Empfangene Leistungsklasse (leer, wenn keine bekannte Klasse kommt)."""
        if self.exchange_kind == "serial_class_name":
            c = split_serial_class_name(q.exch_r)[1]
            return c if c in self.classes else ""
        if self.exchange_kind not in ("serial_class", "serial_class_member"):
            return ""
        c = split_serial_class(q.exch_r)[1]
        return c if c in self.classes else ""

    def cabrillo_exchange(self, exch: str, kind: str | None) -> str:
        """Austausch für die Cabrillo-Zeile – bei „Nummer + DOK“ immer zwei Spalten
        (ohne DOK steht dort „-“, wie im Beispiel-Log des DARC)."""
        if self._iota:                        # IOTA: Nummer und Referenz („------“ = keine Insel)
            serial, ref = split_serial_iota(exch)
            return f"{int(serial or 0):04d} {ref if ref not in ('', '?') else '------'}"
        cn = (self.host or {}).get("cabrillo_none")
        if cn and kind in ("serial", "serial_district"):   # RSGB, UK/EI: immer Nummer + Bezirk
            serial, code = split_serial_dok(exch) if kind == "serial_district" \
                else ((exch or "").strip(), "")
            return f"{serial or '0':>3} {code or cn}"
        if kind == "ss":                      # Sweepstakes: Nr Prec Check Section (ohne Rufzeichen)
            serial, prec, check, sec = split_ss(exch)
            return " ".join(x or "-" for x in (serial, prec, check, sec))
        if kind == "serial_class":            # QRP-Party: „001/A“ wie im AGCW-Musterlog
            serial, cl, _m = split_serial_class(exch)
            return f"{serial}/{cl}" if serial and cl else exch
        if kind == "serial_class_member":     # AGCW QRP: „001 QRP 1537“
            serial, cl, m = split_serial_class(exch)
            return " ".join(x for x in (serial, cl, m) if x) if serial else exch
        if kind == "serial_zone":             # Volta: Nummer und Zone
            serial, zone = split_serial_zone(exch)
            return f"{int(serial):03d} {int(zone):02d}" if serial and zone else exch
        if kind == "serial_district":         # UBA: Nummer und Sektion
            serial, code = split_serial_dok(exch)
            return f"{serial or '0':>3} {code}".rstrip()
        if kind == "serial_dok" or (kind == "serial" and self._two_columns):
            serial, d = split_serial_dok(exch)
            return f"{serial or '0':>3} {d or '-':<6}"
        return exch

    def rcvd_grid6(self, q: Qso) -> str:
        """Empfangener 6-stelliger Locator (UKW), sonst ""."""
        if self.exchange_kind == "dok_grid6":
            g = split_dok_grid(q.exch_r)[1]
            return g if is_grid6(g) else ""
        if self.exchange_kind != "serial_grid6":
            return ""
        g = split_serial_grid(q.exch_r)[1]
        return g if is_grid6(g) else ""

    def qso_km(self, q: Qso) -> float | None:
        """Entfernung nach IARU-Regel (UKW), None wenn ein Locator fehlt."""
        mine, theirs = (self.station.grid or "").strip().upper(), self.rcvd_grid6(q)
        if not (is_grid6(mine) and theirs):
            return None
        return iaru_km(mine, theirs)

    def rcvd_district(self, q: Qso, lk: Lookup | None) -> str:
        """Empfangenes Kürzel aus dem Gastgeberland (leer, wenn keins kommt)."""
        kind = self.expected_kind(lk)
        if kind == "district":
            return normalize_district(q.exch_r, self.host)
        if kind == "serial_district":
            return normalize_district(split_serial_dok(q.exch_r)[1], self.host)
        if kind == "district_or_serial":
            return normalize_district(q.exch_r, self.host)
        return ""

    def _own_district(self) -> str:
        d = normalize_district(self.station.district, self.host)
        return d or ((self.host or {}).get("none_codes") or [""])[0]

    def rcvd_iota(self, q: Qso) -> str:
        """Empfangene IOTA-Referenz (leer = keine Inselstation)."""
        if not self._iota:
            return ""
        ref = split_serial_iota(q.exch_r)[1]
        return "" if ref == "?" else ref

    def own_itu(self) -> int | None:
        t = (self.station.itu or "").strip()
        if t.isdigit():
            return int(t)
        me = self.station.lookup
        return me.itu if me is not None and me.itu else None

    # --- Austausch -----------------------------------------------------------
    def _own_dok(self) -> str:
        """Eigener DOK zum Senden – im Frankencontest geben Stationen außerhalb Deutschlands
        „NM“, auch wenn sie DARC-Mitglied sind (Ausschreibung 2026)."""
        if self.dok_only_dl and self.own_region() != "dl":
            return ""
        return dokmod.normalize(self.station.dok)

    def sent_exchange(self, serial: int) -> str:
        k = self.sent_kind()
        if k == "dok":
            return self._own_dok() or dokmod.NO_MEMBER
        if k == "serial_dok":
            return f"{serial:03d} {dokmod.normalize(self.station.dok) or dokmod.NO_MEMBER}"
        if k == "serial_grid6":
            return f"{serial:03d} {(self.station.grid or '').strip().upper()}".rstrip()
        if k == "district":
            return self._own_district()
        if k == "serial_district":
            return f"{serial:03d} {self._own_district()}".rstrip()
        if k == "serial_iota":
            ref = normalize_iota(self.station.iota)
            return f"{serial:03d} {ref}" if ref else f"{serial:03d}"
        if k == "oblast":
            return regions.normalize_oblast(self.station.oblast) or ""
        if k == "age":
            a = (self.station.age or "").strip()
            return a[-2:].zfill(2) if a.isdigit() else "01"
        if k in ("state", "province"):
            return (self.station.state or "").upper()
        if k == "arrl_section":
            st = (self.station.state or "").strip().upper()
            return regions.normalize_section(st) or st
        if k == "district_or_serial":
            d = normalize_district(self.station.district, self.host)
            return d or f"{serial:03d}"
        if k == "name":
            return (self.station.name or "").strip().upper()
        if k == "name_qth":
            qth = (self.station.state or "").strip().upper()
            me = self.station.lookup
            if not qth and me is not None and me.country not in ("K", "VE"):
                qth = me.country.split("/")[0]           # andere NA-Länder: ihr DXCC-Präfix
            return f"{(self.station.name or '').strip().upper()} {qth}".strip()
        if k == "ss":                         # Sweepstakes: Nummer, Precedence, Call, Check, Section
            st = (self.station.state or "").strip().upper()
            sec = regions.normalize_section(st) or st
            call = (self.station.call or "").strip().upper()
            return " ".join(x for x in (str(serial), self.ss_precedence(), call,
                                        (self.station.lic_year or "")[-2:], sec) if x)
        if k == "serial_name":
            return f"{serial:03d} {(self.station.name or '').strip().upper()}".strip()
        if k == "serial_zone":
            return f"{serial:03d} {self.station.cq_zone:02d}"
        if k == "member_year":                # NMJ: Mitgliedsnummer + Beitrittsjahr (eingetragen
            return (self.station.member or "").strip().upper() or dokmod.NO_MEMBER  # bei Mitglied)
        if k == "country":                    # PSKFest: das eigene Land (DXCC-Präfix)
            me = self.station.lookup
            c = WAE_PARENT.get(me.country, me.country) if me is not None and me.country else ""
            return c.lstrip("*").split("/")[0]
        if k == "qso_party":                  # außerhalb des Gebiets: State/Provinz oder „DX“
            me = self.station.lookup
            st = (self.station.state or "").strip().upper()
            return st if st and me is not None and me.country in ("K", "KL", "KH6", "VE") \
                else "DX"
        if k == "serial_time":
            from datetime import timezone
            return f"{serial:03d} {datetime.now(timezone.utc):%H%M}"
        if k == "power":
            return (self.station.power or "").upper()
        if k == "serial_member":
            m = (self.station.member or "").strip()
            return f"{serial:03d}/{m}" if m else f"{serial:03d}"
        if k == "serial_class":
            return f"{serial:03d}/{self.own_class()}".rstrip("/")   # wie im AGCW-Musterlog
        if k == "serial_class_name":          # HTP: „001/A/TOM/39“, YLs und ohne Alter „XX“
            name = ((self.station.name or "").strip().upper().split() or [""])[0]
            age = (self.station.age or "").strip()
            age = age if age.isdigit() else "XX"
            return f"{serial:03d}/{self.own_class()}/{name}/{age}"
        if k == "serial_class_member":
            m = (self.station.member or "").strip() or dokmod.NO_MEMBER
            return f"{serial:03d} {self.own_class()} {m}".replace("  ", " ")
        if k == "member":                     # DIG: Nichtmitglieder geben nur den Rapport
            return (self.station.member or "").strip().upper() or (
                "" if self.member_empty else dokmod.NO_MEMBER)
        if k == "dok_or_serial":
            return dokmod.normalize(self.station.dok) or f"{serial:03d}"
        if k == "dok_grid6":
            d = self._own_dok() or (
                f"{serial:03d}" if self.no_dok_serial else dokmod.NO_MEMBER)
            return f"{d} {(self.station.grid or '').strip().upper()}".rstrip()
        if k == "itu_zone":
            t = (self.station.itu or "").strip()
            if t.isdigit():
                return t.zfill(2)
            z = self.own_itu()
            return f"{z:02d}" if z else ""
        if k == "iaru":
            t = (self.station.itu or "").strip().upper()
            if t:
                return t
            z = self.own_itu()
            return f"{z:02d}" if z else ""
        if k == "lic_year":
            return (self.station.lic_year or "")[-2:]
        if k == "cq_zone":
            return f"{self.station.cq_zone:02d}"
        if k == "serial":
            return f"{serial:03d}"
        if k == "grid4":
            return normalize(self.station.grid)
        return ""

    def ss_precedence(self) -> str:
        """Sweepstakes-Precedence aus den Kategorien: Q/A/B (Single-Op nach Leistung),
        U (Single-Op mit Spotting-Hilfe), M (Multi-Op). „S“ (Schulstation) gibt es nicht
        als Kategorie im Log-Fenster."""
        st = self.station
        if (st.cat_operator or "SINGLE-OP") == "MULTI-OP":
            return "M"
        if (st.cat_assisted or "") == "ASSISTED":
            return "U"
        return {"QRP": "Q", "LOW": "A"}.get((st.cat_power or "HIGH").upper(), "B")

    def own_class(self) -> str:
        """Eigene Leistungsklasse (leer, wenn keine gültige gewählt ist)."""
        c = (self.station.pclass or "").strip().upper()
        return c if c in (self.own_classes or self.classes) else ""

    def default_rcvd_exchange(self, lk: Lookup | None, call: str = "") -> str:
        kind = self.expected_kind(lk)
        if kind == "province" and call:
            return regions.province_from_call(call)
        if kind == "arrl_section" and call:
            return regions.section_from_call(call, lk.country if lk is not None else "")
        if kind == "iaru" and is_hq_call(call):
            return ""                       # Verbandsstation: sendet ihr Kürzel, nicht die Zone
        if kind in ("iaru", "itu_zone") and lk is not None and lk.itu and not lk.maritime \
                and self.cty and not self.cty.multi_itu(lk):
            return f"{lk.itu:02d}"
        if kind in ("zone_state", "zone_province") and lk is not None and lk.cq \
                and not (self.cty and self.cty.multi_zone(lk)):
            return f"{lk.cq:02d} "            # Zone vorbelegt, State/Provinz hören und dazuschreiben
        if kind == "cq_zone" and self._prefill == "country":
            # Nur vorbelegen, wenn das Land genau eine CQ-Zone hat (DL, JA, OE …).
            # Bei K, VE, VK, UA9, BY, PY usw. muss die Zone gehört und eingegeben werden.
            if not lk or not lk.cq or (self.cty and self.cty.multi_zone(lk)):
                return ""
            return f"{lk.cq:02d}"
        return ""

    def validate_exchange(self, exch: str, lk: Lookup | None = None) -> str | None:
        k = self.exchange_kind
        if k == "location":
            kinds = [self.expected_kind(lk)] if lk is not None else \
                sorted(set((self.location or {}).values()))
            errs = [_check_kind(kd, exch, self.host) for kd in kinds if kd]
            if errs and all(errs):
                return errs[0] if len(errs) == 1 else \
                    tr("Austausch passt nicht (") + " / ".join(KIND_LABEL.get(kd, kd) for kd in kinds) + ")"
            return None
        if k == "member_year":                # NMJ: Nichtmitglieder senden irgendetwas
            return None
        if k == "qso_party":
            counties = self.party_counties(exch)
            if not counties:
                return tr("County-Kürzel nötig (z. B. {ex})",
                          ex=self.qso_party.get("example") or self.qso_party["counties"][0])
            if len(counties) > 1 and not self.qso_party.get("county_line"):
                return tr("Bitte jedes County als eigenes QSO eintragen")
            mx = self.qso_party.get("max_counties")
            if mx and len(counties) > mx:
                return tr("Höchstens {n} Countys je QSO", n=mx)
            return None
        if k == "member" and self.member_empty and not exch.strip():
            return None                       # DIG: Nichtmitglied gibt nur den Rapport
        if k in ("iaru", "lic_year", "age", "serial_grid6", "serial_member", "member",
                 "serial_time", "ss", "serial_name", "serial_zone"):
            return _check_kind(k, exch)
        if k == "serial_class_name":
            serial, cl, name, _age = split_serial_class_name(exch)
            if not (serial and cl and name):
                return tr("Nummer, Klasse, Name (und Alter oder „XX“) nötig, z. B. „001 A TOM 39“")
            if cl not in self.classes:
                return tr("Klasse „{cl}“ gibt es nicht (erlaubt: {join})", cl=cl,
                          join=", ".join(self.classes))
            return None
        if k in ("serial_class", "serial_class_member"):
            serial, cl, mem = split_serial_class(exch)
            ex = " ".join(("001", self.classes[0] if self.classes else "", "NM"
                           if k == "serial_class_member" else "")).strip()
            if not serial or not cl:
                return tr("Nummer und Klasse nötig, z. B. „{ex}“", ex=ex)
            if cl not in self.classes:
                return tr("Klasse „{cl}“ gibt es nicht (erlaubt: {join})", cl=cl,
                          join=", ".join(self.classes))
            if k == "serial_class_member" and not mem:
                return tr("Nach der Klasse fehlt die Mitgliedsnummer oder „NM“, z. B. „{ex}“",
                          ex=ex)
            return None
        if k == "dok_grid6":
            d, g = split_dok_grid(exch)
            if not g:
                return tr("DOK und 6-stelliger Locator nötig, z. B. „B26 JN59NO“ oder „NM JN59NO“")
            if self.no_dok_serial and d.isdigit():
                return None                   # Schwaben: Station ohne DOK sendet ihre Nummer
            return dokmod.form_error(d) if d else tr("DOK fehlt (oder „NM“), z. B. „B26 JN59NO“")
        if k == "cq_zone":
            e = exch.strip()
            if not e.isdigit() or not 1 <= int(e) <= 40:
                return tr("Zone muss zwischen 1 und 40 liegen")
        elif k == "serial":
            if not exch.strip().isdigit():
                return tr("Bitte die empfangene Nummer eingeben")
        elif k == "grid4":
            if not is_grid4(normalize(exch)):
                return tr("4-stelliger Locator nötig (z. B. JN59)")
            if self.rules.get("points", {}).get("type") == "grid_km" and \
                    len(exch.strip()) != 4:
                # Makrothen: 6-stellige Locatoren zeigen, dass nachgeschlagen wurde
                return tr("Nur die 4 Stellen eintragen, die gesendet wurden (z. B. JN59)")
        return None

    # --- Punkte --------------------------------------------------------------
    def _points_block(self) -> dict:
        """Die Punkte-Regeln, die für die eigene Station gelten (bei „by_region“ der passende Teil)."""
        p = self.rules["points"]
        if p["type"] == "by_region":                 # WAG: DL und Ausland zählen verschieden
            if "as" in p:                            # All Asian: Asien und sonst
                p = p["as"] if self.own_in_asia() else p["non_as"]
            elif "host" in p and "eu" in p:          # Baltic: Gastgeber / Europa / sonst
                p = p["host"] if self.is_host(self.station.lookup) else (
                    p["eu"] if self.own_in_europe() else p["non_eu"])
            elif "host" in p:                        # Länder-Contests: Gastgeber und sonst
                p = p["host"] if self.is_host(self.station.lookup) else p["dx"]
            else:
                p = p["dl"] if self.own_region() == "dl" else p["dx"]
        return p

    def qso_points(self, q: Qso, lk: Lookup | None) -> int:
        pts = self._points(self._points_block(), q, lk)
        if self.qso_party and self.qso_party.get("county_line"):
            pts *= max(1, len(self.party_counties(q.exch_r)))   # 7QP: County-Grenze zählt mehrfach
        cp = self.call_points
        if cp and pts:                                # RAC, DTC: Klub-/Verbandsstationen
            parts = q.call.strip().upper().replace("Ø", "0").split("/")
            hit = [cp[x] for x in parts if x in cp]
            if hit:
                pts = hit[0]
        if self.same_dok_zero and pts:                # Frankencontest: eigener DOK zählt 0
            mine, theirs = dokmod.normalize(self.station.dok), self.rcvd_dok(q, lk)
            if mine and mine != dokmod.NO_MEMBER and theirs == mine:
                return 0
        tb = self.rules.get("time_bonus")
        if tb and pts > 0 and in_window(q.time, tb["from"], tb["to"]):
            pts += int(tb["points"])                 # 9A DX: Nachtbonus
        return pts

    def _points(self, p: dict, q: Qso, lk: Lookup | None) -> int:
        t = p["type"]
        if t == "fixed":
            if "trainee" in p and is_trainee_call(q.call):
                return _value(p["trainee"], q.band)
            return _value(p["value"], q.band)
        if t == "portable":                  # Fieldday: Gegenstation fest/portabel
            theirs = is_portable_call(q.call)
            if not theirs and not is_portable_call(self.station.call):
                return _value(p["fixed_fixed"], q.band)
            if lk is None:
                return 0
            # /MM und /AM: Standort unbekannt -> wie außerhalb Europas
            eu = not lk.maritime and lk.cont == "EU"
            key = ("portable_" if theirs else "fixed_") + ("eu" if eu else "dx")
            return _value(p[key], q.band)
        if t == "mode":
            return _value(p.get(cabrillo_mode(q.mode), 0), q.band)
        if t == "member_range":              # NMJ: Punkte nach Mitgliedsnummer
            num = split_member_year(q.exch_r)[0]
            if not num:
                return _value(p["non_member"], q.band)
            n = int(num)
            for lo, hi, pts in p["ranges"]:
                if n >= lo and (hi is None or n <= hi):
                    return int(pts)
            return _value(p["non_member"], q.band)
        if t == "region_table":              # UK/EI DX: Gastgeber/Europa/DX × Gastgeber/Europa/DX
            if lk is None:
                return 0
            me = self.station.lookup

            def reg(x, own=False):
                if self.is_host(x):
                    return "host"
                if x is None:
                    return "eu" if own and self.own_in_europe() else "dx"
                return "eu" if not x.maritime and x.cont == "EU" else "dx"
            pts = _value(p["table"][reg(me, True)][reg(lk)], q.band)
            dw = p.get("double_window")
            if dw and self.is_host(me) and in_window(q.time, dw["from"], dw["to"]):
                pts *= 2                     # UK/EI-Stationen nachts doppelt
            return pts
        if t == "zone_table":                # Volta: eigene Zone × Zone der Gegenstation
            zone = split_serial_zone(q.exch_r)[1]
            mine = self.station.cq_zone
            if not zone or not (isinstance(mine, int) and 1 <= mine <= 40):
                return 0
            pts = int(p["table"][mine - 1][int(zone) - 1])
            me = self.station.lookup
            if q.band in ((p.get("double") or {}).get("bands") or ()) and lk is not None \
                    and me is not None and not lk.maritime and lk.cont != me.cont:
                pts *= 2                     # anderer Kontinent auf 80/10 m
            return pts
        if t == "iaru":
            e = q.exch_r.strip().upper()
            if e and not e.isdigit():
                return _value(p["hq"], q.band)          # Verbandsstation oder Funktionär
            mine = self.own_itu()
            if not e.isdigit() or mine is None:
                return 0
            if int(e) == mine:
                return _value(p["same_zone"], q.band)   # gleiche Zone (auch anderer Kontinent)
            me = self.station.lookup
            if lk is None or me is None or lk.maritime:
                return 0
            if lk.cont == me.cont:
                return _value(p["same_continent"], q.band)
            return _value(p["other"], q.band)
        if t == "km":                        # UKW: Kilometer + 1 (IARU Region 1)
            km = self.qso_km(q)
            return 0 if km is None else int(km) + int(p.get("add", 1))
        if t == "member":                    # HSC: Mitglied / Nicht-Mitglied (Format 15)
            m = self.rcvd_member(q, lk)
            if not m:
                return 0
            return _value(p["non_member" if m == dokmod.NO_MEMBER else "member"], q.band)
        if t == "dok":                       # Schwaben: Bonus für DOKs nach Muster (Format 15)
            d = self.rcvd_dok(q, lk)
            if not (d and re.fullmatch(p["dok_pattern"], d)):
                return _value(p["default"], q.band)
            if "club" in p and is_club_call(q.call):
                return _value(p["club"], q.band)
            if "trainee" in p and is_training_call(q.call):
                return _value(p["trainee"], q.band)
            return _value(p["match"], q.band)
        if t == "class":                     # AGCW QRP: eigene Klasse × Klasse der Gegenstation
            theirs = self.rcvd_class(q)
            tb = p["table"]
            row = tb.get(self.own_class()) or tb.get("*") or {}
            return _value(row.get(theirs, row.get("*", 0)), q.band) if theirs else 0
        if t == "iota":
            mine, theirs = normalize_iota(self.station.iota), self.rcvd_iota(q)
            if mine:
                if not theirs:
                    return _value(p["island_world"], q.band)
                return _value(p["island_same" if theirs == mine else "island_island"], q.band)
            return _value(p["world_island" if theirs else "world_world"], q.band)
        if t == "continent":
            me = self.station.lookup
            if lk is not None and lk.maritime and "maritime" in p:
                return _value(p["maritime"], q.band)
            if self.host and lk is not None and me is not None and not lk.maritime:
                th, mh = self.is_host(lk), self.is_host(me)
                if th and not mh and "host" in p:
                    return _value(p["host"], q.band)
                if th and mh and "host_host_other" in p and lk.cont != me.cont:
                    return _value(p["host_host_other"], q.band)   # REF: F ↔ DOM/TOM
                if th and mh and "host_host" in p:
                    return _value(p["host_host"], q.band)
            g = p.get("group")
            if g and lk is not None and not lk.maritime \
                    and WAE_PARENT.get(lk.country, lk.country) in g["countries"]:
                return _value(g["points"], q.band)       # UBA: Länder der EU
            if "ru" in p and lk is not None and me is not None and not lk.maritime:
                # Russian DX: QSOs mit Russland 10 Punkte; Russland untereinander zählt als
                # eigenes Land (gleicher Kontinent) bzw. anderer Kontinent
                mine_ru = regions.region(me) == "ru"
                if regions.region(lk) == "ru":
                    if not mine_ru:
                        return _value(p["ru"], q.band)
                    cont = "EU" if lk.ru_antarctic else lk.cont   # RI1AN: wie Europa (7.3)
                    return _value(p["own_country" if cont == me.cont else "other_continent"],
                                  q.band)
            if lk is None or me is None or lk.maritime:
                # Unbekanntes Land oder /MM: Kontinent unklar -> keine Punkte,
                # die Multis (z. B. Zone) zählen trotzdem.
                return 0
            if lk.country == me.country:
                return _value(p["own_country"], q.band)
            if lk.cont != me.cont:
                return _value(p["other_continent"], q.band)
            if me.cont == "NA":
                return _value(p["same_continent_na"], q.band)
            return _value(p["same_continent"], q.band)
        if t == "europe":                    # SAC: Europa / außerhalb Europas (Format 18)
            st = self.station.lookup if p.get("of", "worked") == "own" else lk
            if st is None:
                return 0
            eu = not getattr(st, "maritime", False) and st.cont == "EU"
            return _value(p["eu" if eu else "non_eu"], q.band)
        if t == "w_ve":                      # ARRL 160: W/VE untereinander / mit DX (Format 17)
            if lk is None or self.station.lookup is None:
                return 0
            both = self.is_w_ve(self.station.lookup) and self.is_w_ve(lk)
            return _value(p["w_ve_w_ve" if both else "dx"], q.band)
        if t == "grid_km":                   # Makrothen: km (abgerundet) × Bandfaktor (Format 19)
            mine, theirs = normalize(self.station.grid), normalize(q.exch_r)
            if not (is_grid4(mine) and is_grid4(theirs)):
                return 0
            if mine == theirs and "same_grid" in p:
                return _value(p["same_grid"], q.band)
            km = int(grid_km(mine, theirs, float(p.get("radius", 6371))))
            fa = p.get("factor") or {}
            return int(km * float(fa.get(q.band, fa.get("default", 1))))
        if t == "distance":
            mine, theirs = normalize(self.station.grid), normalize(q.exch_r)
            if not (is_grid4(mine) and is_grid4(theirs)):
                return 0
            km = grid_distance_km(mine, theirs)
            if p.get("round") == "up":       # ARRL Digital: angefangene 500 km (Format 18)
                extra = int(-(-km // p["per_km"]))
            else:
                extra = int(km // p["per_km"])
            return p["base"] + max(int(p.get("min_extra", 0)), extra)
        return 0

    # --- Multis --------------------------------------------------------------
    def qso_mults(self, q: Qso, lk: Lookup | None) -> list[tuple[str, str]]:
        out = []
        for m in self._mults:
            t = m["type"]
            if m.get("classes") and self.rcvd_class(q) not in m["classes"]:
                continue                    # QRP-Party: QSOs mit QRO-Stationen ohne Multi
            if t in ("dok", "dok_district"):
                d = self.rcvd_dok(q, lk)
                if dokmod.counts(d) and (m.get("dok_pattern") or m.get("special_doks")) and not (
                        (m.get("dok_pattern") and re.fullmatch(m["dok_pattern"], d))
                        or (m.get("special_doks") and not dokmod.is_ov(d))):
                    continue                # Frankencontest: nur fränkische und Sonder-DOKs
                if dokmod.counts(d):
                    out.append(("dok", d) if t == "dok" else ("district", dokmod.district(d)))
                continue
            if t == "continent":              # BARTG: Kontinente (Format 18)
                if lk is not None and not lk.maritime and lk.cont:
                    out.append(("cont", lk.cont))
                continue
            if t == "member":
                kind = self.expected_kind(lk)
                if kind == "member":            # DIG: jedes Mitglied (Nummer)
                    mem = self.rcvd_member(q, lk)
                    if mem and mem != dokmod.NO_MEMBER:
                        out.append(("member", mem))
                    continue
                if kind == "serial_member" and split_serial_member(q.exch_r)[1]:
                    out.append(("member", q.call.upper()))     # AGCW: jedes Mitglied je Band
                elif kind == "serial_class_member" and \
                        split_serial_class(q.exch_r)[2] not in ("", dokmod.NO_MEMBER):
                    out.append(("member", q.call.upper()))
                continue
            if t == "itu_zone" and self.exchange_kind == "location" \
                    and self.expected_kind(lk) != "itu_zone":
                continue                    # LZ/9A: Gastgeber senden ein Kürzel, keine Zone
            if t in ("itu_zone", "iaru_hq", "lic_year"):
                e = q.exch_r.strip().upper()
                if t == "itu_zone" and e.isdigit() and 1 <= int(e) <= 90:
                    out.append(("itu", str(int(e))))
                elif t == "iaru_hq" and e and not e.isdigit() and not _check_kind("iaru", e):
                    out.append(("hq", e))
                elif t == "lic_year" and re.fullmatch(r"\d\d", e):
                    out.append(("year", e))
                continue
            if t in ("xe_state", "itu_region"):
                kind = self.expected_kind(lk)
                if t == "xe_state" and kind == "xe_state" and regions.normalize_xe_state(q.exch_r):
                    out.append(("xe", regions.normalize_xe_state(q.exch_r)))
                elif t == "itu_region" and kind == "itu_region" and q.exch_r.strip() in ("1", "2", "3"):
                    out.append(("region", q.exch_r.strip()))
                continue
            if t in ("us_state", "ve_province"):
                kind = self.expected_kind(lk)
                qth = split_zone_qth(q.exch_r)[1] if kind in ("zone_state", "zone_province") \
                    else q.exch_r
                if kind == "name_qth":          # NAQP: QTH steht hinter dem Namen
                    qth = split_name_qth(q.exch_r)[1]
                    kind = "state" if regions.normalize_state(qth) else "province"
                kind = {"zone_state": "state", "zone_province": "province"}.get(kind, kind)
                if t == "us_state" and kind == "state":
                    st = regions.normalize_state(qth)
                    if st == "DC" and m.get("dc_md"):
                        st = "MD"               # PSKFest: Washington DC zählt als Maryland
                    allowed = regions.STATES_48_DC if m.get("states", "48dc") == "48dc" \
                        else set(regions.US_STATES)
                    if st and st in allowed:
                        out.append(("state", st))
                elif t == "ve_province" and kind == "province":
                    pv = regions.normalize_province(qth)
                    if pv and m.get("nl") and pv in ("NF", "LB"):
                        pv = "NL"               # NAQP: Neufundland und Labrador = eine Provinz
                    if pv:
                        out.append(("province", pv))
                continue
            if t == "arrl_section":           # ARRL 160 (Format 17), Sweepstakes (Format 19)
                kind = self.expected_kind(lk)
                if kind == "ss":
                    sec = split_ss(q.exch_r)[3]
                    if sec:
                        out.append(("section", sec))
                elif kind == "arrl_section":
                    sec = regions.normalize_section(q.exch_r)
                    if sec:
                        out.append(("section", sec))
                continue
            if t == "cq_zone" and self.exchange_kind == "location" \
                    and self.expected_kind(lk) not in ("cq_zone", "zone_state", "zone_province"):
                continue
            if t == "ru_oblast":
                if self.expected_kind(lk) == "oblast":
                    ob = regions.normalize_oblast(q.exch_r)
                    if ob:
                        out.append(("oblast", ob))
                continue
            if t == "district":
                dd = self.rcvd_district(q, lk)
                if dd and dd not in ((self.host or {}).get("none_codes") or ()):
                    out.append(("subdiv", dd))
                continue
            if t == "county":
                out.extend(("county", c) for c in self.party_counties(q.exch_r))
                continue
            if t == "calls":                    # DLPX: VFDB-Sonderstationen
                parts = q.call.strip().upper().split("/")
                hit = next((p for p in parts if p in m["calls"]), None)
                if hit:
                    out.append(("call", hit))
                continue
            if t == "join_year":
                y = split_member_year(q.exch_r)[1]
                if y:
                    out.append(("joinyear", y))
                continue
            if t == "iota_ref":
                ref = self.rcvd_iota(q)
                if ref:
                    out.append(("iota", ref))
                continue
            if m.get("cont") and (lk is None or lk.maritime or lk.cont != m["cont"]):
                continue                    # All Asian: nur Präfixe aus Asien
            if m.get("countries") and (lk is None or lk.maritime or
                                       WAE_PARENT.get(lk.country, lk.country) not in m["countries"]):
                continue                    # UBA: nur Länder der EU bzw. nur belgische Präfixe
            if t == "call_area":
                a = call_area(q.call, lk, m.get("areas") or {}, bool(m.get("first_digit")))
                if a:
                    out.append(("area", a))
                continue
            if t == "country" and lk is not None and not lk.maritime and lk.country:
                pfx = lk.country
                if m.get("dxcc_only") and m.get("cont") and pfx in WAE_PARENT:
                    continue                # Africa: IG9 gehört im DXCC zu Italien (Europa)
                if m.get("dxcc_only") or (m.get("wae_keep") is not None
                                          and pfx not in m["wae_keep"]):
                    pfx = WAE_PARENT.get(pfx, pfx)   # EA RTTY: nur 4 WAE-Gebiete zählen eigen
                if pfx not in set(m.get("exclude") or ()):
                    out.append(("country", pfx))
                continue
            if t == "cq_zone":
                zone = split_zone_qth(q.exch_r)[0] or q.exch_r.strip()
                if zone.isdigit() and 1 <= int(zone) <= 40:
                    out.append(("zone", str(int(zone))))
            elif t == "wpx_prefix":
                pfx = wpx_prefix(q.call)
                if pfx:
                    out.append(("prefix", pfx))
            elif t == "grid_field":
                g = normalize(q.exch_r)
                if is_grid4(g):
                    out.append(("field", g[:2]))
            elif t == "grid_square":            # CQ WW VHF, ARRL VHF: 4-stellige Locatoren
                g = normalize(q.exch_r)
                if is_grid4(g):
                    out.append(("square", g[:4]))
        return out

    # --- QSO-Partys (Format 21) ------------------------------------------------
    def party_counties(self, exch: str) -> list[str]:
        """County-Kürzel aus dem empfangenen Austausch: „ORDES“, „MA MID“, „UTRIC/IDBEA“,
        „ORDES/JEF“ (Staat nur einmal). Leer, wenn etwas nicht in der Liste steht."""
        qp = self.qso_party
        if not qp:
            return []
        known = set(qp["counties"])
        # 7QP, Indiana: Kürzel = Staat + 3 Buchstaben – „ORDES/JEF“ (Staat nur einmal)
        prefixed = all(len(c) == 5 and c[:2] in qp["states"] for c in known)
        out: list[str] = []
        state = ""
        for part in re.split(r"[/+,]", (exch or "").upper()):
            p = re.sub(r"[^A-Z]", "", part)
            if not p:
                continue
            if prefixed and len(p) == 3 and state and p not in known:
                p = state + p
            elif prefixed and len(p) == 5 and p not in known and p[3:] + p[:3] in known:
                p = p[3:] + p[:3]                        # „MID MA“ -> MAMID
            if p not in known:
                return []
            state = p[:2]
            if p not in out:
                out.append(p)
        return out

    def own_in_party_area(self) -> bool:
        """Eigene Station im Gebiet der QSO-Party (nach dem eigenen State)?"""
        qp, me = self.qso_party, self.station.lookup
        return bool(qp) and me is not None and me.country in ("K", "KL", "KH6") and \
            (self.station.state or "").strip().upper() in qp["states"]

    def party_area(self) -> str:
        return tr(self.qso_party["area"]) if self.qso_party else ""

    def bonus_call_key(self, q: Qso) -> tuple[str, str] | None:
        """NCQP, Salmon Run: (Rufzeichen, Mode oder "") für eine Bonusstation, sonst None."""
        bc = self.bonus_calls
        if not bc:
            return None
        parts = q.call.strip().upper().split("/")
        hit = next((p for p in parts if p in bc["calls"]), None)
        if not hit:
            return None
        return hit, (cabrillo_mode(q.mode) if bc.get("per") == "mode" else "")

    def bonus_value(self, hits: set) -> int:
        bc = self.bonus_calls
        if not bc:
            return 0
        v = bc["points"] * len(hits)
        if bc.get("all_bonus") and {c for c, _m in hits} >= set(bc["calls"]):
            v += bc["all_bonus"]                 # NCQP: alle sechs Bonusstationen
        return v

    def suffix_value(self, letters: dict) -> int:
        """St. Patrick's Day: höchster Bonus aus den gesammelten Anfangsbuchstaben (jedes QSO
        liefert einen Buchstaben, ein Wort braucht für jeden Buchstaben ein eigenes QSO)."""
        sb = self.suffix_bonus
        if not sb:
            return 0
        from collections import Counter
        from itertools import combinations
        words = sb["words"]
        best = 0
        for k in range(len(words), 0, -1):
            for combo in combinations(words, k):
                need = Counter("".join(combo))
                if all(letters.get(ch, 0) >= n for ch, n in need.items()):
                    v = sb["points"] * k + (sb.get("all_bonus", 0) if k == len(words) else 0)
                    best = max(best, v)
            if best:
                break
        return best

    def mobile_key(self, q: Qso) -> tuple[str, list[str]] | None:
        """Texas: (Rufzeichen ohne /M, Countys) für den Bonus der Mobilstationen."""
        if not self.mobile_bonus:
            return None
        call = re.sub(r"/(M|P|R|MM)$", "", q.call.strip().upper())
        return call, self.party_counties(q.exch_r)

    def extra_mult_key(self, q: Qso, lk: Lookup | None, mults: list) -> str | None:
        """Volta: Land bzw. Rufzeichengebiet eines anderen Kontinents – zählt auf
        „min_bands“ Bändern einen Multi mehr (None = zählt dafür nicht)."""
        me = self.station.lookup
        if not self.extra_mult or lk is None or me is None or lk.maritime or lk.cont == me.cont:
            return None
        return next((v for t, v in mults if t in ("country", "area") and v), None)

    # --- Anzeige -------------------------------------------------------------
    def needs_country(self) -> bool:
        return self._needs_country

    def ask_text(self, q: Qso, lk: Lookup | None) -> str | None:
        """Was man bei dieser Gegenstation erfragen muss – für die Infobox (die CQ-Zone hat
        dort schon eine eigene Zeile)."""
        kind = self.expected_kind(lk)
        if kind == "iaru" and is_hq_call(q.call):
            return tr("Verbandsstation? Kürzel erfragen (z. B. DARC)")
        if self.exchange_kind == "location" and lk is not None and kind in KIND_LABEL \
                and kind != "cq_zone":
            if kind == "province":
                prov = regions.province_from_call(q.call)
                if prov:
                    return tr("Provinz: {prov} (aus dem Rufzeichen – bitte bestätigen lassen)", prov=prov)
            if kind == "arrl_section":
                sec = regions.section_from_call(q.call, lk.country)
                if sec:
                    return tr("Section: {sec} (aus dem Rufzeichen – bitte bestätigen lassen)",
                              sec=sec)
            return tr("{p0}: erfragen", p0=KIND_LABEL[kind])
        if kind == "lic_year" and lk is not None:
            return tr("Jahr der ersten Lizenz: erfragen")
        if kind == "age" and lk is not None:
            return tr("Alter: erfragen")
        return None

    def mode_ok(self, q: Qso) -> bool:
        if self.rig_modes is not None:
            return q.mode.upper() in self.rig_modes
        return super().mode_ok(q)

    def describe(self, q: Qso, lk: Lookup | None) -> str:
        if lk is None and not self.needs_country():
            base = ""
        else:
            base = super().describe(q, lk)
        kind = self.expected_kind(lk)
        if self.exchange_kind == "location" and lk is not None:
            if kind in KIND_LABEL and kind != "cq_zone":
                base += tr(" · {p1} erfragen", p1=KIND_LABEL[kind])
        if kind == "iaru" and is_hq_call(q.call):
            base += tr(" · Verbandsstation? Kürzel erfragen (z. B. DARC)")
        if kind == "cq_zone" and lk is not None and not lk.maritime and self.cty:
            zones = sorted(self.cty.zones_for(lk))
            if len(zones) > 1:
                base = tr("{name} · {cont} · Zone erfragen (möglich: {join})", name=lk.name, cont=lk.cont, join=', '.join(map(str, zones)))
            z = q.exch_r.strip()
            if z.isdigit() and zones and int(z) not in zones:
                base += tr("   ⚠ Zone {int} ist für {name} ungewöhnlich", int=int(z), name=lk.name)
        ref = self.rcvd_iota(q)
        if ref:
            base = tr("{base} · IOTA {ref}", base=base, ref=ref)
        d = self.rcvd_dok(q, lk) if self._has_dok else ""
        if d and dokmod.is_ov(d) and dok_db().name(d):
            base = tr("{base} · DOK {d} = {name}", base=base, d=d, name=dok_db().name(d))
        if self._prefix_shown(lk):
            pfx = wpx_prefix(q.call)
            if pfx:
                base = tr("{base} · Präfix {pfx}", base=base, pfx=pfx)
        if self.exchange_kind == "serial_grid6":
            km = self.qso_km(q)
            if km is not None:
                base = tr("{base} · {km} km", base=base, km=int(km)).strip(" ·")
        if self.exchange_kind == "grid4":
            mine, theirs = normalize(self.station.grid), normalize(q.exch_r)
            if is_grid4(mine) and is_grid4(theirs):
                km = grid_distance_km(mine, theirs)
                base = f"{base} · {km:.0f} km".strip(" ·")
        return base

    def _prefix_shown(self, lk: Lookup | None) -> bool:
        """Präfix in der Infozeile zeigen? Nur, wenn es für die eigene Station ein Multi ist
        (All Asian: nur Präfixe aus Asien, nur für Stationen außerhalb Asiens)."""
        for m in self._mults:
            if m["type"] == "wpx_prefix":
                c, cs = m.get("cont"), m.get("countries")
                ok = lk is not None and not lk.maritime
                if (not c or (ok and lk.cont == c)) and (not cs or (ok and lk.country in cs)):
                    return True
        return False

    def notes(self, q: Qso, lk: Lookup | None) -> list[str]:
        out = []
        for prob in (self.segment_problem(q), self.portable_problem()):
            if prob:
                out.append(prob)
        d = self.rcvd_dok(q, lk) if self._has_dok else ""
        if d:
            day = None
            if q.time:
                from datetime import date as _date
                try:
                    day = _date.fromisoformat(q.time[:10])
                except ValueError:
                    day = None
            h = dok_db().hint(d, q.call, day)
            if h:
                out.append(h)
        return out + self._zone_notes(q, lk)

    def _zone_notes(self, q: Qso, lk: Lookup | None) -> list[str]:
        if self.expected_kind(lk) != "cq_zone" or lk is None or lk.maritime or not self.cty:
            return []
        zones = self.cty.zones_for(lk)
        z = q.exch_r.strip()
        if z.isdigit() and zones and int(z) not in zones:
            from ..countries import german_name
            return [tr("Zone {int} ist für {german_name} ungewöhnlich", int=int(z), german_name=german_name(lk.entity.prefix, lk.name))]
        return []


def call_area(call: str, lk: Lookup | None, areas: dict, first_digit: bool = False) -> str:
    """Rufzeichengebiet im WAE: „W1“, „VE3“, „JA4“, „RA9“ … (leer, wenn das Land nicht
    dazugehört). areas = {Länder-Präfix: Name oder {"name": …, "digits": "890"}}.
    Die Ziffer kommt aus dem Präfix, ein Zusatz zählt mit: K3ABC/1 -> W1, VO1AA -> VE1.
    Mit „keep“ (PACC) bleiben diese Präfixe eigene Gebiete: VO1AA -> VO1, CG2AA -> VE2."""
    if lk is None or lk.maritime or not lk.country:
        return ""
    a = areas.get(lk.country)
    if a is None:
        return ""
    name, digits = (a, "") if isinstance(a, str) else (a.get("name", ""), a.get("digits", ""))
    pfx = wpx_prefix(call) or ""
    for k in ([] if isinstance(a, str) else a.get("keep") or []):
        if pfx.startswith(k):
            name = k
            break
    if first_digit:                       # SAC: OZ150A zählt für OZ1, 7S3AB für SM3
        body = pfx[1:] if pfx[:1].isdigit() else pfx   # 7S, 8S, 5P: Ziffer gehört zum Präfix
        m = re.search(r"\d", body)
        d = m.group(0) if m else ""
    else:
        d = pfx[-1:] if pfx[-1:].isdigit() else ""
    if not d or (digits and d not in digits):
        return ""
    return f"{name}{d}"


def grid_km(g1: str, g2: str, radius: float) -> float:
    """Entfernung zwischen den Mitten zweier 4-stelliger Locatoren auf einer Kugel mit dem
    angegebenen Radius (Makrothen: 6378,16 km, Formel aus der Ausschreibung)."""
    import math
    a1, b1 = (math.radians(x) for x in center4(g1))
    a2, b2 = (math.radians(x) for x in center4(g2))
    c = (math.cos(a1) * math.cos(b1) * math.cos(a2) * math.cos(b2)
         + math.cos(a1) * math.sin(b1) * math.cos(a2) * math.sin(b2)
         + math.sin(a1) * math.sin(a2))
    return math.acos(max(-1.0, min(1.0, c))) * radius


def _same_band(r: list[int], khz: float) -> bool:
    """Liegt der Bereich r (kHz) auf demselben Band wie die Frequenz?"""
    from ..bands import band_for_freq
    return band_for_freq(int(r[0] * 1000)) == band_for_freq(int(khz * 1000))


def make_contest_class(d: dict, path: Path | None = None, builtin: bool = True,
                       source: str | None = None) -> type[RuleContest]:
    """Aus einer (geprüften) Regel-Datei eine Contest-Klasse machen."""
    fields = [f for f in d["exchange"] if f["field"] != "rst"]
    main = fields[0]
    kind = main["field"]
    mults = d["multipliers"]
    ot = d.get("operating_time") or {}
    sched = d.get("schedule")
    attrs = {
        "rules": d,
        "rules_path": path,
        "rules_builtin": builtin,
        "rules_source": source or ("builtin" if builtin else "user"),
        "rules_revision": d.get("revision", 1),
        "id": d["id"],
        # Name aus der Regel-Datei – wird übersetzt, wenn es eine Übersetzung gibt
        "name": tr(d["name"]),
        "cabrillo_name": d.get("cabrillo_name", ""),
        "bands": list(d["bands"]),
        "modes": set(d["modes"]),
        "rig_modes": {m.upper() for m in d["rig_modes"]} if d.get("rig_modes") else None,
        "mult_types": [(MULT_KEY[m["type"]], MULT_LABEL[MULT_KEY[m["type"]]]) for m in mults],
        "mults_per_band": all(m.get("per", "band") == "band" for m in mults),
        "dupe_per_mode": d.get("dupe", "band") == "band_mode",
        "dupe_rule": d.get("dupe", "band"),
        "exchange_kind": kind,
        # Beschriftung aus der Regel-Datei – wird übersetzt, wenn es eine Übersetzung gibt
        "exchange_label": tr(main["label"]) if main.get("label") else EXCHANGE_LABEL[kind],
        "location": dict(main["by_region"]) if kind == "location" else None,
        "us_entities": tuple(main.get("us_entities") or ("K",)),
        "contacts": d.get("contacts", "all"),
        "mode_limits": d.get("mode_limits"),
        "max_changes_per_hour": d.get("max_changes_per_hour"),
        "max_changes_total": d.get("max_changes_total"),
        "band_segments": d.get("band_segments"),
        "band_windows": [dict(w) for w in d["band_windows"]] if d.get("band_windows") else None,
        "require_portable": bool(d.get("require_portable")),
        "mult_factor": dict(d["mult_factor"]) if d.get("mult_factor") else None,
        "power_factor": dict(d["power_factor"]) if d.get("power_factor") else None,
        "call_points": {k.upper().replace("Ø", "0"): v for k, v in d["call_points"].items()}
        if d.get("call_points") else None,
        "member_empty": kind == "member" and bool(main.get("empty")),
        "not_same_area": tuple(d.get("not_same_area") or ()),
        "extra_mult": dict(d["extra_mult"]) if d.get("extra_mult") else None,
        "qso_party": dict(d["qso_party"]) if d.get("qso_party") else None,
        "contacts_cont": d.get("contacts_cont", ""),
        "mobile_bonus": dict(d["mobile_bonus"]) if d.get("mobile_bonus") else None,
        "mult_bonus": int(d.get("mult_bonus") or 0),
        "bonus_calls": dict(d["bonus_calls"]) if d.get("bonus_calls") else None,
        "suffix_bonus": dict(d["suffix_bonus"]) if d.get("suffix_bonus") else None,
        "mult_per_type": {MULT_KEY[m["type"]]: m.get("per", "band") for m in mults},
        "qtc": dict(d["qtc"]) if d.get("qtc") else None,
        "multi": {k: dict(v) for k, v in d["multi"].items()} if d.get("multi") else None,
        "mult_per": (mults[0].get("per", "band") if mults else "band"),
        "uses_rst": any(f["field"] == "rst" for f in d["exchange"]),
        "uses_serial": kind == "serial",   # wird in __init__ je eigener Herkunft gesetzt
        "_has_dok": kind == "dok_grid6" or kind == "location" and bool(
            {"dok", "serial_dok", "dok_or_serial"} & set((main.get("by_region") or {}).values())),
        "_two_columns": kind == "location" and "serial_dok" in (main.get("by_region") or {}).values(),
        "_iota": kind == "location" and "serial_iota" in (main.get("by_region") or {}).values(),
        "host": d.get("host"),
        "serial_per_band": bool(d.get("serial_per_band")),
        "score_rule": d.get("score", "points_x_mults"),
        "blocked_countries": tuple(d.get("blocked_countries") or ()),
        "classes": tuple(d.get("classes") or ()),
        "own_classes": tuple(d.get("own_classes") or d.get("classes") or ()),
        "same_dok_zero": bool(d.get("same_dok_zero")),
        "dok_only_dl": bool(d.get("dok_only_dl")),
        "no_dok_serial": kind == "dok_grid6" and main.get("no_dok") == "serial",
        "columns": list(d["columns"]) if d.get("columns") else None,
        "rules_url": d.get("rules_url", ""),
        "rules_checked": d.get("rules_checked", ""),
        "schedule": ({k: v for k, v in sched.items()
                      if not (k == "weekend" and v == "last_full")} if sched else None),
        "max_hours_single": ot.get("single_op_hours"),
        "max_hours_classic": ot.get("classic_hours"),
        "min_break_minutes": ot.get("min_break_minutes", 60),
        "log_format": d.get("log_format", "cabrillo"),
        "_prefill": main.get("prefill", ""),
        "_has_prefix_mult": any(m["type"] == "wpx_prefix" for m in mults),
        "_needs_country": (d["points"]["type"] in ("continent", "iaru")
                           or kind == "location" or d.get("contacts") in ("eu_only", "eu_dx", "asia")
                           or any(m["type"] == "country" for m in mults)),
    }
    name = "Rule_" + "".join(ch if ch.isalnum() else "_" for ch in d["id"])
    return type(name, (RuleContest,), attrs)


def station_fields(cls) -> set[str]:
    """Welche eigenen Angaben ein Contest im Austausch braucht (für das Fenster Log / Station):
    zone (CQ-Zone), power (Leistung), state (State/Provinz), itu (ITU-Zone/Verband),
    licyear (Jahr der ersten Lizenz)."""
    kind = getattr(cls, "exchange_kind", "")
    kinds = set((getattr(cls, "location", None) or {}).values()) if kind == "location" else {kind}
    out = set()
    if kinds & {"cq_zone", "serial_zone"}:
        out.add("zone")
    if "power" in kinds:
        out.add("power")
    if kinds & {"state", "province", "arrl_section", "ss", "qso_party"}:
        out.add("state")
    if kinds & {"iaru", "itu_zone"}:
        out.add("itu")
    if kinds & {"serial_member", "serial_class_member", "member", "member_year"}:
        out.add("member")
    if kinds & {"serial_class", "serial_class_member", "serial_class_name"}:
        out.add("pclass")
    if "serial_class_name" in kinds:
        out.add("age")
    if kinds & {"lic_year", "ss"}:
        out.add("licyear")
    if kinds & {"dok", "serial_dok", "dok_grid6", "dok_or_serial"}:
        out.add("dok")
    if "oblast" in kinds:
        out.add("oblast")
    if "serial_iota" in kinds:
        out.add("iota")
    if "age" in kinds:
        out.add("age")
    if kinds & {"district", "serial_district"}:
        out.add("district")
    if getattr(cls, "log_format", "") == "edi":
        out.add("edi")                    # Sektion, Leistung, Antenne für den EDI-Kopf
    return out
