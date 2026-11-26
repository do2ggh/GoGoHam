"""Regel-Dateien laden und prüfen (Regel-Baukasten, ab 0.6.1).

Jeder Contest ist eine JSON-Datei. Es gibt drei Quellen:

1. **Eigene Regeln** im Daten-Ordner (~/.local/share/gogoham/rules/*.json) – haben
   immer Vorrang (für eigene Contests oder schnelle Korrekturen).
2. **Von GitHub geladene Regeln** (~/.local/share/gogoham/rules/download/).
3. **Eingebaute Regeln** (gogoham/rules/) – damit GoGoHam auch ohne Internet läuft.

Zwischen 2 und 3 gilt die höhere ``revision``. Fehlerhafte Dateien werden nicht
benutzt; GoGoHam meldet das in verständlichen Worten.

Die Datei beschreibt nur, *welche* Bausteine ein Contest benutzt und *mit
welchen Zahlen*. Die Rechenwege (WPX-Präfix, Entfernung, CQ-Zonen-Hinweise …)
stehen im Programm (gogoham/contests/rulebased.py).
"""

from __future__ import annotations

from .i18n import tr

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .bands import BAND_NAMES

# 1 = bis 0.6.5 · 2 = ab 0.7.0 (Austausch je Herkunft, States/Provinzen …)
# 3 = ab 0.7.1 (Punkte/Multis je Mode, IARU, Lizenzjahr, Mexiko, mode_limits …)
# 4 = ab 0.8.4 (DARC: DOK, Herkunft „dl“, Punkte je eigener Herkunft, band_mode,
#     Dupe je Mode, Termin Sonntag/Datum/Ostern, Wechsel im ganzen Contest, Bandbereiche)
# 5 = ab 0.8.5 (WAE: Rufzeichengebiete, Herkunft „eu“/„non_eu“, Kontakte „eu_dx“,
#     Multi-Gewichtung je Band, QTC)
# 6 = ab 0.8.6 (Russian DX: Oblaste, Herkunft „ru“, Punkte „ru“; IOTA: Nummer + IOTA-Referenz,
#     Punkte „iota“, Multi „iota_ref“; All Asian: Alter, Herkunft „as“/„non_as“, Kontakte
#     „asia“, Multi nur von einem Kontinent („cont“))
# 7 = ab 0.8.7 (Länder-Contests: Gastgeberland „host“ mit Kürzel-Liste, Herkunft „host“,
#     Austausch „district“/„serial_district“, Multi „district“, Punkte „host“/„host_host“/
#     „group“, Kontakte „host_only“, „blocked_countries“, Multi-Filter „countries“)
# 8 = ab 0.8.8 (UKW: Austausch „serial_grid6“ = Nummer + 6-stelliger Locator, Punkte „km“,
#     Wertung „points_sum“ ohne Multis, Nummer je Band „serial_per_band“, EDI-Export)
# 9 = ab 0.8.24 (DARC-Paket: Termin „weekday“ + „months“ = n-ter Wochentag in mehreren
#     Monaten, Punkte „portable“ = fest/portabel × Europa/außerhalb (Fieldday),
#     Punkte „fixed“ mit „trainee“ = eigene Punktzahl für Einsteiger-Rufzeichen DN1–8/DO)
# 10 = ab 0.8.25 (DARC-UKW-Paket: Bänder ab 24 GHz („1.25cm“ … „submm“), Zeitfenster je Band
#     „band_windows“ (UKW-Fieldday), Pflicht „/p“ am eigenen Rufzeichen „require_portable“)
# 11 = ab 0.8.31 (Contest-Paket LZ/9A/AGCW/REF: Austausch-Art „itu_zone“ je Herkunft,
#     Austausch „serial_member“ = Nummer + Mitgliedsnummer (AGCW), Multi „member“,
#     Zeitbonus „time_bonus“ = Zusatzpunkte in einem Zeitfenster (9A DX: Nacht))
# 12 = ab 0.10.2 (Multi-OP: „multi“ je Kategorie MS/M2/MM – Sendernummer, 10-Minuten-Regel,
#     Bandwechsel je Stunde, Multi-Signal, Nummern je Band)
# 13 = ab 0.10.7 (QTC in beide Richtungen „both_ways“, Termin „skip_day“)
# 14 = ab 0.10.23 (AGCW QRP / QRP-Party / Frankencontest: Austausch „serial_class“ und
#     „serial_class_member“ mit Leistungsklassen „classes“/„own_classes“, Punkte „class“ =
#     Tabelle eigene Klasse × Klasse der Gegenstation, Austausch „dok_grid6“ = DOK + Locator,
#     Punkte „km“ mit „add“, „same_dok_zero“, Multi-Filter „classes“, „dok_pattern“,
#     „special_doks“, Wertung „band_sum“ und „points_x_mults_or_points“)
# 15 = ab 0.10.26 (HSC / Schwaben-Contest: Austausch „member“ = Mitgliedsnummer oder „NM“,
#     Punkte „member“ (Mitglied / Nicht-Mitglied), Punkte „dok“ = Bonus für DOKs nach Muster mit
#     eigener Zahl für Klub- und Ausbildungsstationen, Austausch-Art „dok_or_serial“ (DOK, sonst
#     Nummer), „dok_grid6“ mit „no_dok“: „serial“, Dupe „band_opmode“ (SSB und FM getrennt),
#     „band_windows“ mit „modes“, Termin mit weiteren Terminen „also“, „skip_day“ auch bei
#     „saturday“)
# 16 = ab 0.10.28 (Regel-Prüfung: Punkte „host_host_other“ = Gastgeber untereinander auf
#     verschiedenen Kontinenten (REF: F ↔ DOM/TOM), Rufzeichengebiet mit „keep“ = eigene
#     Präfixe behalten (PACC: VO1, VY1 getrennt von VE1), „dok_only_dl“ = außerhalb
#     Deutschlands „NM“ statt DOK (Frankencontest, ab 0.10.28.2))
# 17 = ab 0.10.31 (ARRL 160 / Stew Perry: Austausch-Art „arrl_section“ (ARRL/RAC-Section) und
#     „none“ (nur RST), Multi „arrl_section“, Punkte „w_ve“ (W/VE untereinander / mit DX),
#     Kontakt-Regel „w_ve_any“ (W/VE mit allen, DX nur mit W/VE), „power_factor“ = Endergebnis
#     mal Faktor je eigener Leistungsklasse)
# 18 = ab 0.10.32 (15 neue Contests: Kontakt-Regel „host_dx“ (nur Gastgeber ↔ Rest: JIDX, SAC),
#     Punkte „europe“ (nach Europa / außerhalb, wahlweise der eigenen Station), „call_points“
#     (feste Punkte für bestimmte Rufzeichen: RAC, DTC), Austausch-Arten „district_or_serial“,
#     „name“, „name_qth“ (NAQP), Feld „serial_time“ (BARTG), Feld „member“ mit „empty“ (DIG:
#     Nichtmitglied nur Rapport), Entfernung „round“: „up“ + „min_extra“ (ARRL Digital), Multi
#     „continent“ + Ergebnis „points_x_mults_x_cont“ (BARTG), Rufzeichengebiet „first_digit“
#     (SAC), Provinzen „nl“ (NAQP: Neufundland + Labrador = NL), „per“ je Multi verschieden)
# 20 = ab 0.10.34 (HA DX, EA RTTY/PSK63, JARL WW RTTY, Volta: Austausch „serial_zone“ (Nummer +
#     CQ-Zone), Punkte „zone_table“ (Tabelle eigene Zone × Zone der Gegenstation, „double“ für
#     andere Kontinente auf bestimmten Bändern), Kontakt-Regel „not_same_area“ (nicht im eigenen
#     Land bzw. im eigenen Rufzeichengebiet), Wertung „qsos_x_points_x_mults“, „extra_mult“ =
#     Zusatz-Multi für Länder anderer Kontinente auf vielen Bändern, Länder-Multi „wae_keep“ =
#     nur diese WAE-Gebiete zählen eigen)
# 21 = ab 0.10.35 (QSO-Partys NEQP/7QP: Austausch „qso_party“ = County-Kürzel der Stationen im
#     Gebiet, Angabe „qso_party“ (Gebiet, Staaten, County-Liste, County-Grenzen), Multi „county“,
#     Dupe „band_mode_county“ = je Band, Mode und County (Mobilstationen))
# 22 = ab 0.10.36 (Contest-Paket: QSO-Party-Kürzel beliebiger Länge und „max_counties“,
#     „mobile_bonus“ (Texas), Punkte „region_table“ (Gastgeber/Europa/DX × Gastgeber/Europa/DX,
#     UK/EI DX) mit „double_window“, Kontakt-Regel „cont_only“ + „contacts_cont“ (Oceania),
#     Wertung „points_plus_bonus“ + „mult_bonus“ (RSGB 1.8 MHz), Austausch-Art „country“
#     (eigenes Land), Multi us_state mit „dc_md“ (PSKFest: DC zählt als MD))
# 23 = ab 0.10.37 (Contest-Paket: „bonus_calls“ = Bonus für bestimmte Rufzeichen (NCQP, Salmon
#     Run), „suffix_bonus“ = Wörter aus den Anfangsbuchstaben der Suffixe (St. Patrick's Day),
#     Austausch „member_year“ = Mitgliedsnummer + Beitrittsjahr, Punkte „member_range“ und
#     Multi „join_year“ (PODXS New Member Jamboree))
# 24 = ab 0.10.38 (deutsche Vereins-Contests: Austausch „serial_class_name“ = Nummer, Klasse,
#     Name, Alter (AGCW Handtastenparty), Multi „calls“ = feste Liste von Sonderstationen
#     (VFDB DLPX))
# 25 = ab 0.10.41 (Block „submit“ = Einsendeweg: E-Mail, Upload-Seite, Betreff, Frist,
#     Hinweise – nur Anzeige; die Dateien behalten ihre Nummer, weil ältere Versionen
#     unbekannte Angaben einfach übergehen)
# 26 = ab 0.10.42 („cover_sheet“: "bbt" = BBT-Deckblatt + Logblatt als Textdatei je Band statt
#     EDI einreichen; ältere Versionen übergehen die Angabe und bieten weiter EDI an)
# Regel: Wer neue Bausteine einführt, erhöht die Nummer – ältere Versionen überspringen
# solche Dateien dann sauber („braucht neueres GoGoHam“), statt Fehler zu melden.
FORMAT_VERSION = 26
BUILTIN_DIR = Path(__file__).parent / "rules"

# --- Bausteine, die diese Programmversion kennt ------------------------------
EXCHANGE_FIELDS = {"rst", "cq_zone", "serial", "grid4", "location", "iaru", "lic_year", "age", "serial_grid6",
                   "serial_member", "serial_class", "serial_class_member", "dok_grid6", "member",
                   "serial_time", "ss", "serial_name", "serial_zone", "qso_party", "member_year", "serial_class_name"}
CLASS_FIELDS = {"serial_class", "serial_class_member", "serial_class_name"}
PREFILL = {"country"}                       # nur für cq_zone (auch in „location“)
# „location“: was eine Station je nach Herkunft sendet (us/ve/dx/mm -> Art)
REGIONS = {"us", "ve", "xe", "dl", "ru", "host", "dx", "mm"}
LOCATION_KINDS = {"state", "province", "cq_zone", "power", "serial", "xe_state", "itu_region",
                  "dok", "serial_dok", "oblast", "serial_iota", "district", "serial_district",
                  "itu_zone", "zone_state", "zone_province", "dok_or_serial",
                  "arrl_section", "none", "district_or_serial", "name", "name_qth", "country"}
POINT_TYPES = {"fixed", "continent", "distance", "mode", "iaru", "by_region", "iota", "km",
               "portable", "class", "member", "dok", "w_ve", "europe", "grid_km", "zone_table", "region_table", "member_range"}
# „portable“ (Fieldday): Gegenstation fest/portabel in bzw. außerhalb Europas; fest–fest
PORTABLE_KEYS = ("fixed_eu", "fixed_dx", "portable_eu", "portable_dx", "fixed_fixed")
# „by_region“-Punkte: eigene Station in DL / sonst – oder in Asien / sonst (All Asian)
OWN_REGION_PAIRS = (("dl", "dx"), ("as", "non_as"), ("host", "dx"), ("host", "eu", "non_eu"))
IOTA_KEYS = ("island_world", "island_same", "island_island", "world_world", "world_island")
IARU_KEYS = ("same_zone", "hq", "same_continent", "other")
CONTINENT_KEYS = ("own_country", "same_continent", "same_continent_na", "other_continent")
# Maritime Mobile (Standard 0), Russland (RDXC), Gastgeberland (Format 7): „host“ = QSO mit dem
# Gastgeberland, „host_host“ = Gastgeber untereinander, „host_host_other“ = Gastgeber
# untereinander auf verschiedenen Kontinenten (Format 16, REF)
CONTINENT_OPTIONAL = ("maritime", "ru", "host", "host_host", "host_host_other")
MULT_TYPES = {"cq_zone", "country", "wpx_prefix", "grid_field", "us_state", "ve_province",
              "xe_state", "itu_region", "itu_zone", "iaru_hq", "lic_year", "dok", "dok_district",
              "call_area", "ru_oblast", "iota_ref", "district", "member", "arrl_section",
              "continent", "grid_square", "county", "join_year", "calls"}
CONTINENTS = {"AF", "AN", "AS", "EU", "NA", "OC", "SA"}
# Multi zählt nur für die eigene W/VE- bzw. DX-Station (ARRL DX) oder DL / nicht-DL (WAG)
MULT_WHEN = {"w_ve", "dx", "dl", "non_dl", "eu", "non_eu", "as", "non_as", "host", "non_host"}
# w_ve_dx: DX nur mit W/VE; eu_only: nur EU–EU; dl_dx: Stationen außerhalb DL nur mit DL;
# eu_dx: nur Europa ↔ außerhalb Europas (WAE); asia: außerhalb Asiens nur mit Asien, nie im
# eigenen Land (All Asian)
# host_only: Stationen außerhalb des Gastgeberlands werten nur QSOs mit dem Gastgeberland
# w_ve_any: W/VE mit allen, DX nur mit W/VE (ARRL 160, Format 17)
# host_dx: nur QSOs zwischen Gastgeberland und Rest zählen (JIDX, SAC; Format 18)
# w_ve_only: nur W/VE untereinander (ARRL Sweepstakes, Format 19)
CONTACT_RULES = {"all", "w_ve_dx", "eu_only", "dl_dx", "eu_dx", "asia", "host_only", "w_ve_any",
                 "host_dx", "w_ve_only", "not_same_area", "cont_only"}
# „power_factor“ (Format 17, Stew Perry): Endergebnis mal Faktor je eigener Leistungsklasse
POWER_CATEGORIES = {"HIGH", "LOW", "QRP"}
MULT_PER = {"band", "once", "mode", "band_mode"}
# „once“: jede Station nur einmal, egal auf welchem Band (ARRL Sweepstakes, Format 19)
DUPE_RULES = {"band", "band_mode", "mode", "band_opmode", "once", "band_mode_county"}
# Betriebsarten für „band_windows“ / „band_opmode“ (Format 15): SSB und FM getrennt
OP_MODES = {"CW", "SSB", "FM", "AM", "RY", "DG"}
SCORE_RULES = {"points_x_mults", "points_sum", "band_sum", "points_x_mults_or_points",
               "points_x_mults_x_cont", "qsos_x_points_x_mults", "points_plus_bonus"}
LOG_FORMATS = {"cabrillo", "adif", "edi"}
CABRILLO_MODES = {"PH", "CW", "RY", "DG"}
WEEKENDS = {"last_full", "full", "saturday", "sunday", "date", "easter", "weekday"}

REQUIRED = ("format", "id", "name", "bands", "modes", "exchange", "points", "multipliers")

# Bausteine, die geplant, aber noch nicht gebaut sind – für eine freundlichere Meldung
PLANNED = {"grid6", "state", "locator", "km_sum", "per_band"}


def user_dir() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "gogoham" / "rules"


def download_dir() -> Path:
    return user_dir() / "download"


@dataclass
class RuleSet:
    data: dict
    path: Path
    builtin: bool
    source: str = "builtin"        # builtin / download / user

    @property
    def revision(self) -> int:
        return revision(self.data)


def revision(d: dict) -> int:
    r = d.get("revision", 1)
    return r if isinstance(r, int) and not isinstance(r, bool) else 1


@dataclass
class LoadResult:
    rules: dict[str, RuleSet] = field(default_factory=dict)     # id -> Regeln
    problems: list[str] = field(default_factory=list)           # verständliche Meldungen
    overrides: list[str] = field(default_factory=list)          # ids aus dem Daten-Ordner


def _unknown(kind: str, value) -> str:
    if value in PLANNED:
        return tr("{kind} „{value}“ ist geplant, kann diese GoGoHam-Version aber noch nicht", kind=kind, value=value)
    return tr("{kind} „{value}“ kennt GoGoHam nicht (Tippfehler?)", kind=kind, value=value)


def _check_points_value(name: str, v, errs: list[str]) -> None:
    if isinstance(v, bool):
        errs.append(tr("Punkte „{name}“: Zahl erwartet", name=name))
    elif isinstance(v, int):
        if v < 0:
            errs.append(tr("Punkte „{name}“ darf nicht negativ sein", name=name))
    elif isinstance(v, dict):
        if "default" not in v:
            errs.append(tr("Punkte „{name}“: Eintrag „default“ fehlt", name=name))
        for k, x in v.items():
            if k != "default" and k not in BAND_NAMES:
                errs.append(tr("Punkte „{name}“: Band „{k}“ unbekannt", name=name, k=k))
            if not isinstance(x, int) or isinstance(x, bool) or x < 0:
                errs.append(tr("Punkte „{name}“ / „{k}“: ganze Zahl ≥ 0 erwartet", name=name, k=k))
    else:
        errs.append(tr("Punkte „{name}“: Zahl oder Tabelle je Band erwartet", name=name))


def validate(d) -> list[str]:
    """Fehlerliste (leer = in Ordnung)."""
    if not isinstance(d, dict):
        return [tr("Die Datei enthält kein JSON-Objekt { … }")]
    errs: list[str] = []
    for k in REQUIRED:
        if k not in d:
            errs.append(tr("Pflichtangabe „{k}“ fehlt", k=k))
    if errs:
        return errs
    fmt = d["format"]
    if not isinstance(fmt, int) or isinstance(fmt, bool):
        return [tr("„format“ muss eine Zahl sein")]
    if fmt > FORMAT_VERSION:
        return [tr("Die Datei braucht eine neuere GoGoHam-Version (Format {fmt}, "
                   "dieses GoGoHam kann Format {FORMAT_VERSION})", fmt=fmt, FORMAT_VERSION=FORMAT_VERSION)]
    if not isinstance(d["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", d["id"]):
        errs.append(tr("„id“: nur Kleinbuchstaben, Ziffern und Bindestrich (z. B. cqww-ssb)"))
    if not isinstance(d["name"], str) or not d["name"].strip():
        errs.append(tr("„name“ fehlt oder ist leer"))
    rev = d.get("revision", 1)
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 1:
        errs.append(tr("„revision“ muss eine ganze Zahl ab 1 sein"))

    bands = d["bands"]
    if not isinstance(bands, list) or not bands:
        errs.append(tr("„bands“: Liste der Bänder erwartet, z. B. [\"80\", \"40\"]"))
    else:
        for b in bands:
            if b not in BAND_NAMES:
                errs.append(tr("Band „{b}“ kennt GoGoHam nicht (bekannt: {join})", b=b, join=', '.join(BAND_NAMES)))
    modes = d["modes"]
    if not isinstance(modes, list) or not modes:
        errs.append(tr("„modes“: Liste erwartet, z. B. [\"PH\"]"))
    else:
        for m in modes:
            if m not in CABRILLO_MODES:
                errs.append(tr("Mode „{m}“ unbekannt (erlaubt: PH, CW, RY, DG)", m=m))
    rm = d.get("rig_modes")
    if rm is not None and (not isinstance(rm, list) or not all(isinstance(x, str) for x in rm)):
        errs.append(tr("„rig_modes“: Liste von Betriebsarten erwartet, z. B. [\"FT8\", \"FT4\"]"))

    if d.get("dupe", "band") not in DUPE_RULES:
        errs.append(_unknown(tr("Dupe-Regel"), d.get("dupe")))
    if d.get("score", "points_x_mults") not in SCORE_RULES:
        errs.append(_unknown("Wertung", d.get("score")))
    if d.get("log_format", "cabrillo") not in LOG_FORMATS:
        errs.append(_unknown("Log-Format", d.get("log_format")))

    # --- Austausch
    ex = d["exchange"]
    main: list[str] = []
    if not isinstance(ex, list) or not ex:
        errs.append(tr("„exchange“: Liste der Austausch-Felder erwartet"))
    else:
        for i, f in enumerate(ex):
            if not isinstance(f, dict) or "field" not in f:
                errs.append(tr('Austausch Nr. {p1}: {{"field": …}} erwartet', p1=i + 1))
                continue
            name = f["field"]
            if name not in EXCHANGE_FIELDS:
                errs.append(_unknown(tr("Austausch-Feld"), name))
                continue
            if name != "rst":
                main.append(name)
            if name == "location":
                br = f.get("by_region")
                if not isinstance(br, dict) or "dx" not in br:
                    errs.append(tr("Austausch „location“: „by_region“ mit mindestens „dx“ nötig, "
                                "z. B. {\"us\": \"state\", \"ve\": \"province\", \"dx\": \"cq_zone\"}"))
                else:
                    for reg, kind in br.items():
                        if reg not in REGIONS:
                            errs.append(_unknown("Herkunft", reg))
                        if kind not in LOCATION_KINDS:
                            errs.append(_unknown(tr("Austausch-Art"), kind))
                    if "cq_zone" in br.values():
                        main.append("cq_zone")
                    for kd in ("serial_iota", "oblast", "district", "serial_district", "itu_zone",
                               "district_or_serial"):
                        if kd in br.values():
                            main.append(kd)
                ue = f.get("us_entities")
                if ue is not None and (not isinstance(ue, list)
                                       or not all(isinstance(x, str) for x in ue)):
                    errs.append(tr("„us_entities“: Liste von Länder-Präfixen erwartet, z. B. [\"K\", \"KL\", \"KH6\"]"))
            pf = f.get("prefill")
            if pf is not None and (name not in ("cq_zone", "location") or pf not in PREFILL):
                errs.append(tr("Austausch „{name}“: Vorbelegung „{pf}“ nicht möglich", name=name, pf=pf))
        if len([m for m in main if not (m in ("cq_zone", "serial_iota", "oblast", "district",
                                                 "serial_district", "itu_zone",
                                                 "district_or_serial")
                                        and "location" in main)]) != 1:
            errs.append(tr("Austausch: genau ein Feld neben RST nötig "
                        "(mehrere Felder kann diese GoGoHam-Version noch nicht)"))

    # --- Leistungsklassen (Format 14)
    if CLASS_FIELDS & set(main):
        cl, own = d.get("classes"), d.get("own_classes")
        if not _str_list(cl) or not all(re.fullmatch(r"[A-Z0-9]{1,5}", c) for c in cl):
            errs.append(tr("„classes“: Liste der Leistungsklassen nötig, z. B. "
                           "[\"QRP\", \"QRO\"] (Großbuchstaben/Ziffern)"))
        elif own is not None and (not _str_list(own) or not set(own) <= set(cl)):
            errs.append(tr("„own_classes“: Teil-Liste von „classes“ erwartet"))
    if not isinstance(d.get("same_dok_zero", False), bool):
        errs.append(tr("„same_dok_zero“: true oder false erwartet"))
    if not isinstance(d.get("dok_only_dl", False), bool):
        errs.append(tr("„dok_only_dl“: true oder false erwartet"))

    # --- Punkte
    _check_points(d["points"], main, errs)

    # --- Multis
    _check_mults(d, main, errs)
    _check_host(d, main, errs)
    _check_extras(d, errs)
    return errs


def _check_points(p, main: list[str], errs: list[str], nested: bool = False) -> None:
    if isinstance(p, dict) and p.get("type") == "by_region" and not nested:
        keys = set(p) - {"type"}
        pair = next((pr for pr in OWN_REGION_PAIRS if set(pr) == keys),
                    next((pr for pr in OWN_REGION_PAIRS if pr[0] in p),
                         next((pr for pr in OWN_REGION_PAIRS if pr[1] in p), OWN_REGION_PAIRS[0])))
        for reg in pair:
            if reg not in p:
                errs.append(tr("Punkte „by_region“: Angabe für „{reg}“ fehlt", reg=reg))
        for reg, sub in p.items():
            if reg == "type":
                continue
            if reg not in pair:
                errs.append(_unknown("Herkunft", reg))
            else:
                _check_points(sub, main, errs, nested=True)
        return
    if not isinstance(p, dict) or "type" not in p:
        errs.append(tr("„points“: {\"type\": …} erwartet"))
    elif p["type"] not in POINT_TYPES:
        errs.append(_unknown(tr("Punkte-Art"), p["type"]))
    elif p["type"] == "fixed":
        _check_points_value("value", p.get("value"), errs)
        if "trainee" in p:                       # Format 9: Einsteiger-Rufzeichen
            _check_points_value("trainee", p["trainee"], errs)
    elif p["type"] == "portable":
        for k in PORTABLE_KEYS:
            if k not in p:
                errs.append(tr("Punkte: „{k}“ fehlt", k=k))
            else:
                _check_points_value(k, p[k], errs)
    elif p["type"] == "continent":
        for k in CONTINENT_KEYS:
            if k not in p:
                errs.append(tr("Punkte: „{k}“ fehlt", k=k))
            else:
                _check_points_value(k, p[k], errs)
        for k in CONTINENT_OPTIONAL:
            if k in p:
                _check_points_value(k, p[k], errs)
        g = p.get("group")
        if g is not None:
            if not isinstance(g, dict) or not _str_list(g.get("countries")):
                errs.append(tr("Punkte „group“: {\"countries\": [Länder-Präfixe], \"points\": …} erwartet"))
            else:
                _check_points_value("group", g.get("points"), errs)
    elif p["type"] == "mode":
        if not any(k in p for k in CABRILLO_MODES):
            errs.append(tr("Punkte je Mode: mindestens einer von PH, CW, RY, DG nötig"))
        for k in CABRILLO_MODES:
            if k in p:
                _check_points_value(k, p[k], errs)
    elif p["type"] == "iaru":
        for k in IARU_KEYS:
            if k not in p:
                errs.append(tr("Punkte: „{k}“ fehlt", k=k))
            else:
                _check_points_value(k, p[k], errs)
        if "iaru" not in main:
            errs.append(tr("IARU-Punkte brauchen „iaru“ im Austausch"))
    elif p["type"] == "iota":
        for k in IOTA_KEYS:
            if k not in p:
                errs.append(tr("Punkte: „{k}“ fehlt", k=k))
            else:
                _check_points_value(k, p[k], errs)
        if "serial_iota" not in main:
            errs.append(tr("IOTA-Punkte brauchen „serial_iota“ im Austausch"))
    elif p["type"] == "km":
        if not {"serial_grid6", "dok_grid6"} & set(main):
            errs.append(tr("Kilometer-Punkte brauchen „serial_grid6“ oder „dok_grid6“ im Austausch"))
        add = p.get("add", 1)
        if not isinstance(add, int) or isinstance(add, bool) or add < 0:
            errs.append(tr("Punkte „km“: „add“ muss eine ganze Zahl ≥ 0 sein"))
    elif p["type"] == "class":
        if not CLASS_FIELDS & set(main):
            errs.append(tr("Punkte „class“ brauchen „serial_class“ oder „serial_class_member“ "
                           "im Austausch"))
        tb = p.get("table")
        if not isinstance(tb, dict) or not tb or not all(
                isinstance(k, str) and isinstance(v, dict) and v for k, v in tb.items()):
            errs.append(tr("Punkte „class“: „table“ erwartet, z. B. "
                           "{\"QRP\": {\"QRP\": 3, \"QRO\": 2}} (eigene Klasse → Gegenstation)"))
        else:
            for row in tb.values():
                for k, v in row.items():
                    _check_points_value(k, v, errs)
    elif p["type"] == "distance":
        for k in ("base", "per_km"):
            v = p.get(k)
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                errs.append(tr("Punkte: „{k}“ muss eine ganze Zahl ≥ 0 sein", k=k))
        if p.get("per_km") == 0:
            errs.append(tr("Punkte: „per_km“ darf nicht 0 sein"))
        if "grid4" not in main:
            errs.append(tr("Punkte nach Entfernung brauchen den Locator im Austausch (grid4)"))
        if p.get("round", "down") not in ("down", "up"):       # Format 18 (ARRL Digital)
            errs.append(tr("Punkte: „round“ muss „down“ oder „up“ sein"))
        me = p.get("min_extra", 0)
        if not isinstance(me, int) or isinstance(me, bool) or me < 0:
            errs.append(tr("Punkte: „{k}“ muss eine ganze Zahl ≥ 0 sein", k="min_extra"))
    elif p["type"] == "grid_km":               # Format 19 (Makrothen): km × Bandfaktor
        if "grid4" not in main:
            errs.append(tr("Punkte nach Entfernung brauchen den Locator im Austausch (grid4)"))
        r = p.get("radius", 6371)
        if not isinstance(r, (int, float)) or isinstance(r, bool) or r <= 0:
            errs.append(tr("Punkte „grid_km“: „radius“ (Erdradius in km) muss größer 0 sein"))
        fa = p.get("factor", {})
        if not isinstance(fa, dict) or not all(
                (k == "default" or k in BAND_NAMES) and isinstance(v, (int, float))
                and not isinstance(v, bool) and v > 0 for k, v in fa.items()):
            errs.append(tr("Punkte „grid_km“: „factor“ = Tabelle je Band, z. B. "
                           "{\"80\": 2.0, \"40\": 1.5, \"default\": 1}"))
        if "same_grid" in p:
            _check_points_value("same_grid", p["same_grid"], errs)
    elif p["type"] == "europe":                # Format 18 (SAC): Europa / außerhalb Europas
        for k in ("eu", "non_eu"):
            if k not in p:
                errs.append(tr("Punkte: „{k}“ fehlt", k=k))
            else:
                _check_points_value(k, p[k], errs)
        if p.get("of", "worked") not in ("worked", "own"):
            errs.append(tr("Punkte „europe“: „of“ muss „worked“ (Gegenstation) oder „own“ "
                           "(eigene Station) sein"))
    elif p["type"] == "w_ve":                  # Format 17 (ARRL 160): W/VE untereinander / mit DX
        for k in ("w_ve_w_ve", "dx"):
            if k not in p:
                errs.append(tr("Punkte: „{k}“ fehlt", k=k))
            else:
                _check_points_value(k, p[k], errs)
    elif p["type"] == "member":                # Format 15 (HSC): Mitglied / Nicht-Mitglied
        for k in ("member", "non_member"):
            if k not in p:
                errs.append(tr("Punkte: „{k}“ fehlt", k=k))
            else:
                _check_points_value(k, p[k], errs)
        if not {"member", "serial_member", "serial_class_member"} & set(main):
            errs.append(tr("Punkte „member“ brauchen die Mitgliedsnummer im Austausch"))
    elif p["type"] == "dok":                   # Format 15 (Schwaben): Bonus für DOKs nach Muster
        for k in ("default", "match"):
            if k not in p:
                errs.append(tr("Punkte: „{k}“ fehlt", k=k))
            else:
                _check_points_value(k, p[k], errs)
        for k in ("club", "trainee"):
            if k in p:
                _check_points_value(k, p[k], errs)
        pat = p.get("dok_pattern")
        try:
            ok = isinstance(pat, str) and re.compile(pat) is not None
        except re.error:
            ok = False
        if not ok:
            errs.append(tr("Punkte „dok“: „dok_pattern“ (Suchmuster) nötig, z. B. \"T\\d\\d|Z30\""))
    elif p["type"] == "zone_table":            # Format 20 (Volta): Zone × Zone
        if "serial_zone" not in main:
            errs.append(tr("Punkte „zone_table“ brauchen „serial_zone“ im Austausch"))
        tb = p.get("table")
        if not (isinstance(tb, list) and len(tb) == 40 and all(
                isinstance(r, list) and len(r) == 40 and all(
                    isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in r)
                for r in tb)):
            errs.append(tr("Punkte „zone_table“: „table“ = 40 Zeilen mit je 40 ganzen Zahlen "
                           "(eigene Zone → Zone der Gegenstation)"))
        db = p.get("double")
        if db is not None and not (isinstance(db, dict) and set(db) == {"bands"}
                                   and _str_list(db["bands"])
                                   and all(b in BAND_NAMES for b in db["bands"])):
            errs.append(tr("Punkte „zone_table“: „double“ = {\"bands\": [\"80\", \"10\"]} "
                           "(doppelte Punkte für andere Kontinente auf diesen Bändern)"))
    elif p["type"] == "member_range":          # Format 23 (PODXS NMJ): Punkte nach Mitgliedsnummer
        if "member_year" not in main:
            errs.append(tr("Punkte „member_range“ brauchen „member_year“ im Austausch"))
        rg = p.get("ranges")
        ok = isinstance(rg, list) and bool(rg) and all(
            isinstance(r, list) and len(r) == 3
            and all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in (r[0], r[2]))
            and (r[1] is None or (isinstance(r[1], int) and not isinstance(r[1], bool) and r[1] >= r[0]))
            for r in rg)
        if not ok:
            errs.append(tr("Punkte „member_range“: „ranges“ = [[von, bis, Punkte], …], „bis“ "
                           "darf null sein (= ohne Grenze)"))
        _check_points_value("non_member", p.get("non_member"), errs)
    elif p["type"] == "region_table":          # Format 22 (UK/EI DX)
        tb = p.get("table")
        regs = ("host", "eu", "dx")
        if not (isinstance(tb, dict) and set(tb) == set(regs)
                and all(isinstance(r, dict) and set(r) == set(regs) for r in tb.values())):
            errs.append(tr("Punkte „region_table“: „table“ = {\"host\": {\"host\": …, \"eu\": …, "
                           "\"dx\": …}, \"eu\": {…}, \"dx\": {…}} (eigene Herkunft → Gegenstation)"))
        else:
            for row in tb.values():
                for k, v in row.items():
                    _check_points_value(k, v, errs)
        dw = p.get("double_window")
        if dw is not None and not (isinstance(dw, dict) and set(dw) == {"from", "to"}
                                   and _hhmm(dw["from"]) is not None and _hhmm(dw["to"]) is not None):
            errs.append(tr("Punkte „region_table“: „double_window“ = {\"from\": \"0100\", "
                           "\"to\": \"0500\"} (doppelte Punkte für das Gastgeberland, UTC)"))
    elif p["type"] == "by_region":
        errs.append(tr("Punkte „by_region“ darf nicht verschachtelt werden"))


def _check_mults(d: dict, main: list[str], errs: list[str]) -> None:
    ms = d["multipliers"]
    if not isinstance(ms, list):
        errs.append(tr("„multipliers“: Liste erwartet (darf leer sein)"))
    else:
        pers = set()
        for m in ms:
            if not isinstance(m, dict) or "type" not in m:
                errs.append(tr("Multi: {\"type\": …, \"per\": …} erwartet"))
                continue
            if m["type"] not in MULT_TYPES:
                errs.append(_unknown(tr("Multi-Art"), m["type"]))
            per = m.get("per", "band")
            if per not in MULT_PER:
                errs.append(_unknown(tr("Multi-Zählweise"), per))
            pers.add(per)
            if m["type"] == "cq_zone" and "cq_zone" not in main:
                errs.append(tr("Multi „cq_zone“ braucht die Zone im Austausch"))
            if m["type"] in ("grid_field", "grid_square") and "grid4" not in main:
                errs.append(tr("Multi „{p1}“ braucht den Locator im Austausch", p1=m["type"]))
            if m["type"] == "itu_zone" and not {"iaru", "itu_zone"} & set(main):
                errs.append(tr("Multi „{p1}“ braucht „iaru“ im Austausch", p1=m['type']))
            if m["type"] == "member" and not {"serial_member", "serial_class_member",
                                              "member"} & set(main):
                errs.append(tr("Multi „member“ braucht „serial_member“ im Austausch"))
            if m.get("classes") is not None and (not _str_list(m["classes"])
                                                 or not CLASS_FIELDS & set(main)):
                errs.append(tr("Multi „classes“: Liste von Klassen erwartet (nur mit "
                               "„serial_class“ im Austausch)"))
            if m.get("dok_pattern") is not None or m.get("special_doks") is not None:
                if m["type"] != "dok":
                    errs.append(tr("„dok_pattern“/„special_doks“ gibt es nur beim Multi „dok“"))
                pat = m.get("dok_pattern")
                if pat is not None:
                    try:
                        re.compile(pat) if isinstance(pat, str) else None
                    except re.error:
                        pat = None
                    if not isinstance(pat, str):
                        errs.append(tr("Multi „dok_pattern“: gültiges Suchmuster erwartet, "
                                       "z. B. B(0[1-9]|[1-3][0-9]|4[0-4])"))
                if not isinstance(m.get("special_doks", False), bool):
                    errs.append(tr("Multi „special_doks“: true oder false erwartet"))
            if m["type"] == "iaru_hq" and "iaru" not in main:
                errs.append(tr("Multi „{p1}“ braucht „iaru“ im Austausch", p1=m['type']))
            if m["type"] == "ru_oblast" and "oblast" not in main:
                errs.append(tr("Multi „ru_oblast“ braucht „oblast“ im Austausch (location)"))
            if m["type"] == "iota_ref" and "serial_iota" not in main:
                errs.append(tr("Multi „iota_ref“ braucht „serial_iota“ im Austausch (location)"))
            if m["type"] == "district" and not ({"district", "serial_district",
                                                 "district_or_serial"} & set(main)):
                errs.append(tr("Multi „district“ braucht „district“ oder „serial_district“ im "
                               "Austausch (location)"))
            if m.get("countries") is not None and not _str_list(m["countries"]):
                errs.append(tr("Multi „countries“: Liste von Länder-Präfixen erwartet"))
            if m.get("cont") is not None and m["cont"] not in CONTINENTS:
                errs.append(_unknown(tr("Kontinent"), m["cont"]))
            if m["type"] == "lic_year" and "lic_year" not in main:
                errs.append(tr("Multi „lic_year“ braucht „lic_year“ im Austausch"))
            if m["type"] in ("us_state", "ve_province", "xe_state", "itu_region", "dok",
                             "dok_district", "arrl_section") and "location" not in main \
                    and not (m["type"] in ("dok", "dok_district") and "dok_grid6" in main) \
                    and not (m["type"] == "arrl_section" and "ss" in main):
                errs.append(tr("Multi „{p1}“ braucht „location“ im Austausch", p1=m['type']))
            if m.get("when") is not None and m["when"] not in MULT_WHEN:
                errs.append(_unknown(tr("Multi-Bedingung „when“"), m["when"]))
            if not isinstance(m.get("dc_md", False), bool):
                errs.append(tr("Multi „dc_md“: true oder false erwartet"))
            if m.get("states") is not None and m["states"] not in ("48dc", "50dc"):
                errs.append(_unknown("State-Liste", m["states"]))
            if m["type"] == "call_area":
                ar = m.get("areas")
                ok = isinstance(ar, dict) and bool(ar) and all(
                    isinstance(k, str) and _area_ok(v) for k, v in ar.items())
                if not ok:
                    errs.append(tr("Multi „call_area“: „areas“ erwartet, z. B. "
                                   "{\"K\": \"W\", \"UA9\": {\"name\": \"RA\", \"digits\": \"890\"}}"))
            if not isinstance(m.get("first_digit", False), bool):
                errs.append(tr("Multi „first_digit“: true oder false erwartet"))
            if not isinstance(m.get("nl", False), bool):
                errs.append(tr("Multi „nl“: true oder false erwartet"))
            if m["type"] == "calls" and not _str_list(m.get("calls")):
                errs.append(tr("Multi „calls“: „calls“ = Liste der Rufzeichen, z. B. [\"DL0DBP\"]"))
            if m["type"] == "join_year" and "member_year" not in main:
                errs.append(tr("Multi „join_year“ braucht „member_year“ im Austausch"))
            if m["type"] == "county" and "qso_party" not in main:
                errs.append(tr("Multi „county“ braucht „qso_party“ im Austausch"))
            wk = m.get("wae_keep")                # Format 20 (EA RTTY): nur diese WAE-Gebiete
            if wk is not None and (m["type"] != "country" or not isinstance(wk, list) or not all(
                    isinstance(x, str) and x.startswith("*") for x in wk)):
                errs.append(tr("Multi „wae_keep“: Liste von WAE-Gebieten (mit *) beim Multi "
                               "„country“ erwartet, z. B. [\"*GM/S\", \"*IT9\"]"))
            ex_ = m.get("exclude")
            if ex_ is not None and (not isinstance(ex_, list)
                                    or not all(isinstance(x, str) for x in ex_)):
                errs.append(tr("Multi „exclude“: Liste von Länder-Präfixen erwartet, z. B. [\"K\", \"VE\"]"))
        fmt = d.get("format", 1)
        if len(pers) > 1 and not (isinstance(fmt, int) and fmt >= 18):
            # ab Format 18 darf jeder Multi anders zählen (DIG: Mitglieder einmal, Länder je Band)
            errs.append(tr("Alle Multis müssen gleich zählen (alle „band“ oder alle „once“)"))


def _hhmm(v) -> int | None:
    """„0929“ -> Minuten seit Mitternacht (None, wenn keine gültige Uhrzeit HHMM)."""
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}", v):
        return None
    h, m = int(v[:2]), int(v[2:])
    return h * 60 + m if h <= 23 and m <= 59 else None


def _str_list(v) -> bool:
    return isinstance(v, list) and bool(v) and all(isinstance(x, str) and x for x in v)


def _check_host(d: dict, main: list[str], errs: list[str]) -> None:
    """Gastgeberland (Format 7): {"countries": ["HA"], "codes": [...] oder "pattern": "[A-Z]{3}",
    wahlweise "none_codes": ["XXX"]} – Kürzel, die Stationen im Gastgeberland senden."""
    h = d.get("host")
    needs = {"district", "serial_district"} & set(main) or any(
        isinstance(m, dict) and m.get("when") in ("host", "non_host")
        for m in d.get("multipliers") or []) or d.get("contacts") == "host_only"
    if h is None:
        if needs:
            errs.append(tr("Gastgeberland „host“ fehlt (nötig für Kürzel, „host_only“ oder "
                           "„when“: „host“)"))
        return
    if not isinstance(h, dict) or not _str_list(h.get("countries")):
        errs.append(tr("„host“: {\"countries\": [\"HA\"], \"codes\": […]} erwartet"))
        return
    codes, pat = h.get("codes"), h.get("pattern")
    if codes is not None and not _str_list(codes):
        errs.append(tr("„host“ / „codes“: Liste von Kürzeln erwartet"))
    if pat is not None:
        try:
            re.compile(pat) if isinstance(pat, str) else None
        except re.error:
            pat = None
        if not isinstance(pat, str):
            errs.append(tr("„host“ / „pattern“: gültiges Suchmuster erwartet, z. B. [A-Z]{3}"))
    if codes is None and pat is None and {"district", "serial_district"} & set(main):
        errs.append(tr("„host“: „codes“ oder „pattern“ nötig"))
    nc = h.get("none_codes")
    if nc is not None and not _str_list(nc):
        errs.append(tr("„host“ / „none_codes“: Liste von Kürzeln erwartet"))


def _area_ok(v) -> bool:
    """Rufzeichengebiet: Name („W“) oder {"name": "RA", "digits": "890"}, dazu wahlweise
    „keep“: Präfixe, die als eigenes Gebiet zählen, z. B. ["VO", "VY"] (Format 16, PACC)."""
    if isinstance(v, str):
        return bool(v)
    if not isinstance(v, dict) or not isinstance(v.get("name"), str) or not v["name"]:
        return False
    dg = v.get("digits", "")
    keep = v.get("keep", [])
    return isinstance(dg, str) and (dg == "" or dg.isdigit()) and isinstance(keep, list) \
        and all(isinstance(k, str) and k.isalpha() and k.isupper() for k in keep)


def _ranges_ok(v) -> bool:
    return isinstance(v, list) and all(
        isinstance(r, list) and len(r) == 2
        # ab Format 18 auch Kommazahlen (BARTG: Bake 14100 kHz ± 0,5 kHz)
        and all(isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 for x in r)
        and r[0] < r[1] for r in v)


def _check_extras(d: dict, errs: list[str]) -> None:
    if d.get("cover_sheet", "bbt") != "bbt":     # 0.10.42
        errs.append(_unknown(tr("Deckblatt"), d.get("cover_sheet")))
    if "submit" in d:                            # 0.10.41: Einsendeweg (ältere übergehen ihn)
        from . import submit
        errs.extend(submit.validate(d["submit"]))
    if d.get("contacts", "all") not in CONTACT_RULES:
        errs.append(_unknown(tr("Kontakt-Regel"), d.get("contacts")))
    if not isinstance(d.get("serial_per_band", False), bool):
        errs.append(tr("„serial_per_band“: true oder false erwartet"))
    if d.get("score") == "band_sum" and any(
            isinstance(m, dict) and m.get("per", "band") != "band" for m in d.get("multipliers") or []):
        errs.append(tr("Wertung „band_sum“ braucht Multis je Band („per“: „band“)"))
    if d.get("score") == "points_sum" and d.get("multipliers"):
        errs.append(tr("Wertung „points_sum“ (nur Punkte) verträgt keine Multis – "
                       "„multipliers“ bitte leer lassen: []"))
    qp = d.get("qso_party")                      # Format 21 (NEQP, 7QP)
    uses_qp = any(isinstance(f, dict) and f.get("field") == "qso_party"
                  for f in d.get("exchange") or [])
    if uses_qp or qp is not None:
        ok = isinstance(qp, dict) and isinstance(qp.get("area"), str) and qp["area"] \
            and _str_list(qp.get("states")) and _str_list(qp.get("counties")) \
            and all(isinstance(c, str) and re.fullmatch(r"[A-Z0-9]{2,6}", c)
                    for c in qp["counties"]) \
            and len(set(qp["counties"])) == len(qp["counties"]) \
            and isinstance(qp.get("county_line", False), bool) \
            and (qp.get("max_counties") is None or (isinstance(qp["max_counties"], int)
                                                    and not isinstance(qp["max_counties"], bool)
                                                    and qp["max_counties"] >= 2)) \
            and isinstance(qp.get("example", ""), str)
        if not ok:
            errs.append(tr("„qso_party“: {\"area\": …, \"states\": [\"OR\", …], \"counties\": "
                           "[\"ORDES\", …], \"county_line\": true} erwartet (Kürzel: 2–6 Buchstaben/Ziffern, "
                           "jedes nur einmal)"))
        if not uses_qp:
            errs.append(tr("„qso_party“ braucht das Austausch-Feld „qso_party“"))
    if d.get("dupe") == "band_mode_county" and not uses_qp:
        errs.append(tr("Dupe „band_mode_county“ braucht „qso_party“ im Austausch"))
    def _pos_int(v, zero=False):
        return isinstance(v, int) and not isinstance(v, bool) and (v >= 0 if zero else v > 0)
    bc = d.get("bonus_calls")                    # Format 23 (NCQP, Salmon Run)
    if bc is not None and not (isinstance(bc, dict) and _str_list(bc.get("calls"))
                               and _pos_int(bc.get("points"))
                               and bc.get("per", "once") in ("once", "mode")
                               and _pos_int(bc.get("all_bonus", 0), zero=True)
                               and set(bc) <= {"calls", "points", "per", "all_bonus"}):
        errs.append(tr("„bonus_calls“: {\"calls\": [\"W7DX\"], \"points\": 500, \"per\": "
                       "\"once\" oder \"mode\", \"all_bonus\": 200} erwartet"))
    sb = d.get("suffix_bonus")                   # Format 23 (St. Patrick's Day)
    if sb is not None and not (isinstance(sb, dict) and _str_list(sb.get("words"))
                               and all(re.fullmatch(r"[A-Z]+", w) for w in sb["words"])
                               and _pos_int(sb.get("points"))
                               and _pos_int(sb.get("all_bonus", 0), zero=True)
                               and set(sb) <= {"words", "points", "all_bonus"}):
        errs.append(tr("„suffix_bonus“: {\"words\": [\"ERIN\", \"GO\"], \"points\": 100, "
                       "\"all_bonus\": 200} erwartet (Großbuchstaben)"))
    mb = d.get("mobile_bonus")                   # Format 22 (Texas)
    if mb is not None and not (uses_qp and isinstance(mb, dict) and set(mb) == {"points", "counties"}
                               and all(isinstance(mb[k], int) and not isinstance(mb[k], bool)
                                       and mb[k] > 0 for k in mb)):
        errs.append(tr("„mobile_bonus“: {\"points\": 500, \"counties\": 5} erwartet (nur bei "
                       "„qso_party“)"))
    if d.get("contacts") == "cont_only" and d.get("contacts_cont") not in CONTINENTS:
        errs.append(tr("Kontakt-Regel „cont_only“: „contacts_cont“ = Kontinent, z. B. \"OC\""))
    if d.get("score") == "points_plus_bonus":
        b = d.get("mult_bonus")
        if not isinstance(b, int) or isinstance(b, bool) or b <= 0:
            errs.append(tr("Wertung „points_plus_bonus“: „mult_bonus“ = Bonuspunkte je Multi, z. B. 5"))
    xm = d.get("extra_mult")                     # Format 20 (Volta)
    if xm is not None and not (isinstance(xm, dict) and set(xm) == {"min_bands"}
                               and isinstance(xm["min_bands"], int)
                               and not isinstance(xm["min_bands"], bool)
                               and 2 <= xm["min_bands"] <= len(BAND_NAMES)):
        errs.append(tr("„extra_mult“: {\"min_bands\": 4} erwartet (Land eines anderen "
                       "Kontinents auf so vielen Bändern = ein Multi mehr)"))
    na = d.get("not_same_area")
    if d.get("contacts") == "not_same_area" and not (
            isinstance(na, list) and all(isinstance(x, str) and x for x in na)):
        errs.append(tr("Kontakt-Regel „not_same_area“: „not_same_area“ = Liste der Länder, in "
                       "denen nur das eigene Rufzeichengebiet gesperrt ist, z. B. [\"K\", \"JA\"]"))
    bc = d.get("blocked_countries")
    if bc is not None and not _str_list(bc):
        errs.append(tr("„blocked_countries“: Liste von Länder-Präfixen erwartet, z. B. [\"UA\", \"EU\"]"))
    ml = d.get("mode_limits")
    if ml is not None:
        if not isinstance(ml, dict) or not all(
                k in CABRILLO_MODES and isinstance(v, dict) for k, v in ml.items()):
            errs.append(tr("„mode_limits“: z. B. {\"CW\": {\"max_khz\": 28300}} erwartet"))
        else:
            for k, v in ml.items():
                for kk, x in v.items():
                    if kk not in ("min_khz", "max_khz") or not isinstance(x, int) or x <= 0:
                        errs.append(tr("„mode_limits“ {k}: nur „min_khz“/„max_khz“ als Zahl", k=k))
    for key in ("max_changes_per_hour", "max_changes_total"):
        mc = d.get(key)
        if mc is not None and (not isinstance(mc, int) or isinstance(mc, bool) or mc < 1):
            errs.append(tr("„{key}“ muss eine ganze Zahl ab 1 sein", key=key))
    bs = d.get("band_segments")
    if bs is not None:
        ok = isinstance(bs, dict) and all(
            k in CABRILLO_MODES and isinstance(v, dict) and v
            and all(kk in ("allowed", "forbidden") and _ranges_ok(x) for kk, x in v.items())
            for k, v in bs.items())
        if not ok:
            errs.append(tr("„band_segments“: z. B. {\"CW\": {\"allowed\": [[3510, 3560]]}} "
                           "oder „forbidden“ erwartet (kHz von–bis)"))

    tb = d.get("time_bonus")
    if tb is not None:
        if not (isinstance(tb, dict) and set(tb) == {"from", "to", "points"}
                and _hhmm(tb["from"]) is not None and _hhmm(tb["to"]) is not None
                and isinstance(tb["points"], int) and not isinstance(tb["points"], bool)
                and tb["points"] > 0):
            errs.append(tr("„time_bonus“: z. B. {\"from\": \"2300\", \"to\": \"0500\", "
                           "\"points\": 2} erwartet (UTC, „to“ gehört nicht mehr dazu)"))

    bw = d.get("band_windows")
    if bw is not None:
        ok = isinstance(bw, list) and bool(bw)
        for w in bw if ok else []:
            if not (isinstance(w, dict) and {"weekday", "from", "to", "bands"} <= set(w)
                    and set(w) <= {"weekday", "from", "to", "bands", "modes"}
                    and (w.get("modes") is None or (_str_list(w["modes"]) and w["modes"]
                                                    and set(w["modes"]) <= OP_MODES))
                    and isinstance(w["weekday"], int) and not isinstance(w["weekday"], bool)
                    and 0 <= w["weekday"] <= 6
                    and _hhmm(w["from"]) is not None and _hhmm(w["to"]) is not None
                    and _hhmm(w["from"]) <= _hhmm(w["to"])
                    and _str_list(w["bands"]) and w["bands"]):
                ok = False
                break
            for b in w["bands"]:
                if b not in BAND_NAMES:
                    errs.append(tr("„band_windows“: Band „{b}“ unbekannt", b=b))
        if not ok:
            errs.append(tr("„band_windows“: Liste wie [{\"weekday\": 6, \"from\": \"0700\", "
                           "\"to\": \"0929\", \"bands\": [\"70cm\"]}] erwartet "
                           "(Wochentag 0 = Montag … 6 = Sonntag, Uhrzeit UTC)"))
    if not isinstance(d.get("require_portable", False), bool):
        errs.append(tr("„require_portable“: true oder false erwartet"))

    mf = d.get("mult_factor")
    if mf is not None:
        if not isinstance(mf, dict) or not mf:
            errs.append(tr("„mult_factor“: Tabelle je Band erwartet, z. B. "
                           "{\"80\": 4, \"40\": 3, \"default\": 2}"))
        else:
            for k, x in mf.items():
                if k != "default" and k not in BAND_NAMES:
                    errs.append(tr("„mult_factor“: Band „{k}“ unbekannt", k=k))
                if not isinstance(x, int) or isinstance(x, bool) or x < 1:
                    errs.append(tr("„mult_factor“ / „{k}“: ganze Zahl ab 1 erwartet", k=k))
    cp = d.get("call_points")                  # Format 18 (RAC, DTC): Punkte für bestimmte Rufzeichen
    if cp is not None and not (isinstance(cp, dict) and cp and all(
            isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v >= 0
            for k, v in cp.items())):
        errs.append(tr("„call_points“: Tabelle Rufzeichen → Punkte erwartet, z. B. "
                       "{\"VE3RHQ\": 20}"))
    pf = d.get("power_factor")                 # Format 17 (Stew Perry)
    if pf is not None:
        if not isinstance(pf, dict) or not pf:
            errs.append(tr("„power_factor“: Tabelle je Leistungsklasse erwartet, z. B. "
                           "{\"LOW\": 1.5, \"QRP\": 3}"))
        else:
            for k, x in pf.items():
                if k not in POWER_CATEGORIES:
                    errs.append(tr("„power_factor“: Leistungsklasse „{k}“ unbekannt "
                                   "(HIGH, LOW, QRP)", k=k))
                if not isinstance(x, (int, float)) or isinstance(x, bool) or x <= 0:
                    errs.append(tr("„power_factor“ / „{k}“: Zahl größer 0 erwartet", k=k))
    qt = d.get("qtc")
    if qt is not None:
        if not isinstance(qt, dict):
            errs.append(tr("„qtc“: {\"max_per_station\": 10, \"points\": 1} erwartet"))
        else:
            for k in ("max_per_station", "points"):
                v = qt.get(k, 1)
                if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                    errs.append(tr("„qtc“: „{k}“ muss eine ganze Zahl ab 1 sein", k=k))
            # Format 13 (WAE RTTY): jeder darf geben und empfangen, nur zwischen Kontinenten
            if not isinstance(qt.get("both_ways", False), bool):
                errs.append(tr("„qtc“: „both_ways“ muss true oder false sein"))
            for k in qt:
                if k not in ("max_per_station", "points", "both_ways"):
                    errs.append(_unknown("QTC-Angabe", k))

    mu = d.get("multi")                      # Multi-OP-Regeln (Format 12, ab 0.10.2)
    if mu is not None:
        if not isinstance(mu, dict):
            errs.append(tr("„multi“: {\"MS\": {…}, \"M2\": {…}, \"MM\": {…}} erwartet"))
        else:
            for cat, r in mu.items():
                if cat not in ("MS", "M2", "MM"):
                    errs.append(_unknown("Multi-OP-Kategorie", cat))
                    continue
                if not isinstance(r, dict):
                    errs.append(tr("„multi“ / „{cat}“: {{…}} erwartet", cat=cat))
                    continue
                for k, v in r.items():
                    if k in ("tx_id", "mult_station"):
                        if not isinstance(v, bool):
                            errs.append(tr("„multi“ / „{cat}“ / „{k}“: true oder false", cat=cat,
                                           k=k))
                    elif k == "per_hour":
                        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                            errs.append(tr("„multi“ / „{cat}“ / „per_hour“: ganze Zahl ab 1",
                                           cat=cat))
                    elif k == "dwell":
                        if not isinstance(v, dict) or not isinstance(v.get("minutes"), int) \
                                or set(v) - {"minutes", "mode"}:
                            errs.append(tr("„multi“ / „{cat}“ / „dwell“: {{\"minutes\": 10}} "
                                           "erwartet", cat=cat))
                    elif k == "serial":
                        if v not in ("station", "band"):
                            errs.append(tr("„multi“ / „{cat}“ / „serial“: „station“ oder „band“",
                                           cat=cat))
                    else:
                        errs.append(_unknown("Multi-OP-Angabe", k))

    # --- Termin und Betriebszeit
    s = d.get("schedule")
    scheds = [s] if s is not None else []
    if isinstance(s, dict) and "also" in s:      # Format 15: weitere Termine (HSC: Feb. + Nov.)
        al = s["also"]
        if not isinstance(al, list) or not al or not all(
                isinstance(x, dict) and "also" not in x for x in al):
            errs.append(tr("Termin: „also“ = Liste weiterer Termine erwartet, z. B. "
                           "[{\"weekend\": \"sunday\", \"nth\": 1, \"month\": 11, …}]"))
        else:
            scheds += al
    for s in scheds:
        if not isinstance(s, dict):
            errs.append(tr("„schedule“: {\"month\": …, \"hours\": …} erwartet"))
        else:
            if s.get("weekend", "last_full") not in WEEKENDS:
                errs.append(_unknown("Termin-Art", s.get("weekend")))
            kind = s.get("weekend", "last_full")
            if kind == "date":
                day = s.get("day")
                if not isinstance(day, int) or isinstance(day, bool) or not 1 <= day <= 31:
                    errs.append(tr("Termin „date“: „day“ (Tag im Monat) muss 1 bis 31 sein"))
            if kind == "easter":
                off = s.get("offset", 0)
                if not isinstance(off, int) or isinstance(off, bool) or not -60 <= off <= 60:
                    errs.append(tr("Termin „easter“: „offset“ (Tage nach Ostersonntag) -60 bis 60"))
            skip = s.get("skip_day")              # Format 13: „nie am 1. Januar“ (ARRL RTTY RU)
            if skip is not None and (not isinstance(skip, int) or isinstance(skip, bool)
                                     or not 1 <= skip <= 31 or kind not in ("full", "saturday")):
                errs.append(tr("Termin: „skip_day“ (1 bis 31) gibt es nur bei „full“ und "
                               "„saturday“"))
            nth = s.get("nth", 1)
            if not isinstance(nth, int) or isinstance(nth, bool) or nth == 0 or not -5 <= nth <= 5:
                errs.append(tr("Termin: „nth“ muss 1 bis 5 sein (oder -1 für das letzte)"))
            sd = s.get("start_day", 0)
            if not isinstance(sd, int) or isinstance(sd, bool) or not -3 <= sd <= 3:
                errs.append(tr("Termin: „start_day“ muss -3 bis 3 sein (-1 = Freitag)"))
            ms = s.get("months")
            if ms is not None:
                if kind == "easter" or not isinstance(ms, list) or not ms or not all(
                        isinstance(m, int) and not isinstance(m, bool) and 1 <= m <= 12
                        for m in ms):
                    errs.append(tr("Termin: „months“ = Liste von Monaten 1 bis 12, "
                                   "z. B. [2, 5, 8, 11]"))
            elif kind != "easter" and (not isinstance(s.get("month"), int)
                                       or not 1 <= s["month"] <= 12):
                errs.append(tr("Termin: „month“ muss 1 bis 12 sein"))
            if kind == "weekday":
                wd = s.get("weekday")
                if not isinstance(wd, int) or isinstance(wd, bool) or not 0 <= wd <= 6:
                    errs.append(tr("Termin „weekday“: „weekday“ muss 0 (Montag) bis "
                                   "6 (Sonntag) sein"))
            if not isinstance(s.get("start_hour", 0), int) or not 0 <= s.get("start_hour", 0) <= 23:
                errs.append(tr("Termin: „start_hour“ muss 0 bis 23 sein"))
            sm, mi = s.get("start_minute", 0), s.get("minutes", 0)
            for k, v in (("start_minute", sm), ("minutes", mi)):
                if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 59:
                    errs.append(tr("Termin: „{k}“ muss 0 bis 59 sein", k=k))
            h = s.get("hours")
            if not isinstance(h, int) or isinstance(h, bool) or not 0 <= h <= 168 \
                    or (h == 0 and not mi):
                errs.append(tr("Termin: „hours“ muss 1 bis 168 sein"))
    ot = d.get("operating_time")
    if ot is not None:
        if not isinstance(ot, dict):
            errs.append(tr("„operating_time“: {\"single_op_hours\": …} erwartet"))
        else:
            for k in ("single_op_hours", "classic_hours", "min_break_minutes"):
                v = ot.get(k)
                if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v <= 0):
                    errs.append(tr("Betriebszeit: „{k}“ muss eine ganze Zahl > 0 sein", k=k))

    rc = d.get("rules_checked", "")
    if rc and not (isinstance(rc, str) and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", rc)):
        errs.append(tr("„rules_checked“: Monat im Format JJJJ-MM erwartet, z. B. 2026-11"))
    cols = d.get("columns")
    if cols is not None and (not isinstance(cols, list) or not all(isinstance(c, str) for c in cols)):
        errs.append(tr("„columns“: Liste von Spalten-Namen erwartet"))
    return errs


class FileProblem(str):
    """Fehlertext, der als ganzer Satz hinter den Dateinamen gehört („… ist kein gültiges
    JSON“) – unabhängig von der Sprache erkennbar."""


def _read(path: Path) -> tuple[dict | None, list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return None, [FileProblem(tr("lässt sich nicht lesen ({e})", e=e))]
    try:
        d = json.loads(text)
    except json.JSONDecodeError as e:
        return None, [FileProblem(tr("ist kein gültiges JSON – Zeile {lineno}, Spalte {colno}: {msg}", lineno=e.lineno, colno=e.colno, msg=e.msg))]
    errs = validate(d)
    return (None, errs) if errs else (d, [])


def _problem(path: Path, errs: list[str], prefix: str = "") -> str:
    if len(errs) == 1 and isinstance(errs[0], FileProblem):
        return f"{prefix}{path} {errs[0]}"
    return f"{prefix}{path}: " + "; ".join(errs)


def load_all(builtin_dir: Path | None = None, data_dir: Path | None = None) -> LoadResult:
    """Alle Regeln laden: eingebaut, von GitHub geladen (höhere Revision gewinnt), eigene."""
    res = LoadResult()
    bdir = builtin_dir or BUILTIN_DIR
    for path in sorted(bdir.glob("*.json")):
        d, errs = _read(path)
        if d is None:
            res.problems.append(_problem(Path(path.name), errs, tr("Eingebaute Regel-Datei ")))
            continue
        res.rules[d["id"]] = RuleSet(d, path, True, "builtin")
    udir = data_dir if data_dir is not None else user_dir()
    ddir = udir / "download"
    if ddir.is_dir():
        for path in sorted(ddir.glob("*.json")):
            d, errs = _read(path)
            if d is None:
                continue        # kaputte Downloads still übergehen – die eingebaute gilt
            old = res.rules.get(d["id"])
            if old is None or revision(d) > old.revision:
                res.rules[d["id"]] = RuleSet(d, path, False, "download")
    if udir.is_dir():
        for path in sorted(udir.glob("*.json")):
            d, errs = _read(path)
            if d is None:
                res.problems.append(_problem(path, errs) + tr(" – die Datei wird nicht benutzt."))
                continue
            res.rules[d["id"]] = RuleSet(d, path, False, "user")
            res.overrides.append(d["id"])
    return res
