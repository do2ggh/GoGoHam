"""US-States, kanadische Provinzen und die Einteilung „W/VE oder DX“ (ab 0.7.0).

Abkürzungen nach der offiziellen ARRL-Liste (contests.arrl.org/contestmultipliers.php,
Version 1.2.0 vom 12.05.2023). Andere übliche Schreibweisen (z. B. VO1 statt NF wie im
CQ 160) werden auf diese Abkürzungen zurückgeführt.
"""

from __future__ import annotations

import re

US_STATES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DC": "District of Columbia", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
# 48 zusammenhängende Staaten + DC (ARRL DX, CQ 160): ohne Alaska und Hawaii
STATES_48_DC = {s for s in US_STATES if s not in ("AK", "HI")}

# Kanada: Abkürzung -> (Name, andere Schreibweisen). VO1 und VO2 zählen getrennt.
VE_PROVINCES: dict[str, tuple[str, tuple[str, ...]]] = {
    "AB": ("Alberta", ("VE6", "ALB", "ALTA")),
    "BC": ("British Columbia", ("VE7",)),
    "LB": ("Labrador", ("VO2", "LAB")),
    "MB": ("Manitoba", ("VE4", "MAN")),
    "NB": ("New Brunswick", ("VE9",)),
    "NF": ("Newfoundland", ("VO1", "NL", "NFL", "NLD")),
    "NS": ("Nova Scotia", ("VE1",)),
    "NT": ("Northwest Territories", ("VE8", "NWT")),
    "NU": ("Nunavut", ("VY0", "NUN")),
    "ON": ("Ontario", ("VE3", "ONT")),
    "PE": ("Prince Edward Island", ("VY2", "PEI")),
    "QC": ("Quebec", ("VE2", "PQ", "QUE")),
    "SK": ("Saskatchewan", ("VE5", "SAS", "SASK")),
    "YT": ("Yukon", ("VY1", "YK", "YUK")),
}
_VE_ALIAS = {a: k for k, (_n, aliases) in VE_PROVINCES.items() for a in aliases}

# Provinz aus dem Rufzeichen-Präfix vorschlagen (nur eindeutige Fälle; VE1/VA1 = NS oder NB)
_VE_PREFIX = {"2": "QC", "3": "ON", "4": "MB", "5": "SK", "6": "AB", "7": "BC", "8": "NT",
              "9": "NB"}
_VO_VY = {"VO1": "NF", "VO2": "LB", "VY0": "NU", "VY1": "YT", "VY2": "PE"}


# Mexiko: 31 Staaten + Ciudad de México (ARRL-Liste, wie im ARRL 10 m)
XE_STATES: dict[str, str] = {
    "AGS": "Aguascalientes", "BAC": "Baja California", "BCS": "Baja California Sur",
    "CAM": "Campeche", "CHI": "Chiapas", "CHH": "Chihuahua", "CMX": "Ciudad de México",
    "COA": "Coahuila", "COL": "Colima", "DGO": "Durango", "EMX": "Estado de México",
    "GTO": "Guanajuato", "GRO": "Guerrero", "HGO": "Hidalgo", "JAL": "Jalisco",
    "MIC": "Michoacán", "MOR": "Morelos", "NAY": "Nayarit", "NLE": "Nuevo León",
    "OAX": "Oaxaca", "PUE": "Puebla", "QRO": "Querétaro", "QUI": "Quintana Roo",
    "SLP": "San Luis Potosí", "SIN": "Sinaloa", "SON": "Sonora", "TAB": "Tabasco",
    "TAM": "Tamaulipas", "TLX": "Tlaxcala", "VER": "Veracruz", "YUC": "Yucatán",
    "ZAC": "Zacatecas",
}
_XE_ALIAS = {"DF": "CMX", "CDMX": "CMX", "MEX": "EMX", "BC": "BAC", "QROO": "QUI",
             "CHIS": "CHI", "CHIH": "CHH", "NL": "NLE", "YUCA": "YUC"}


def normalize_xe_state(s: str) -> str | None:
    """Mexikanischen State prüfen ("jal" -> "JAL", "DF" -> "CMX")."""
    t = (s or "").strip().upper()
    if t in XE_STATES:
        return t
    if t in _XE_ALIAS:
        return _XE_ALIAS[t]
    for k, name in XE_STATES.items():
        if name.upper() == t:
            return k
    return None


def normalize_state(s: str) -> str | None:
    """US-State-Abkürzung prüfen ("ct" -> "CT"); auch ausgeschriebene Namen."""
    t = (s or "").strip().upper()
    if t in US_STATES:
        return t
    for k, name in US_STATES.items():
        if name.upper() == t:
            return k
    return None


def normalize_province(s: str) -> str | None:
    """Provinz-Abkürzung prüfen ("VE3" -> "ON", "VO1" -> "NF", "pei" -> "PE")."""
    t = (s or "").strip().upper()
    if t in VE_PROVINCES:
        return t
    if t in _VE_ALIAS:
        return _VE_ALIAS[t]
    for k, (name, _a) in VE_PROVINCES.items():
        if name.upper() == t:
            return k
    return None


def province_from_call(call: str) -> str:
    """Provinz aus einem kanadischen Rufzeichen ableiten – nur wenn eindeutig, sonst ""."""
    c = (call or "").strip().upper()
    if "/" in c:
        return ""                         # portabel: Präfix sagt nichts Sicheres
    for p, prov in _VO_VY.items():
        if c.startswith(p):
            return prov
    m = re.match(r"^V[AE](\d)", c)
    if m:
        return _VE_PREFIX.get(m.group(1), "")
    return ""


# ARRL/RAC-Sections (ARRL 160 m, ab 0.10.31) – die 85 Sections nach der offiziellen Liste
# contests.arrl.org/contestmultipliers.php?a=wve (Version 1.2.0 vom 12.05.2023)
ARRL_SECTIONS: tuple[str, ...] = (
    "CO", "IA", "KS", "MN", "MO", "ND", "NE", "SD",
    "CT", "EMA", "ME", "NH", "RI", "VT", "WMA",
    "ENY", "NLI", "NNJ", "NNY", "SNJ", "WNY",
    "DE", "EPA", "MDC", "WPA",
    "AL", "GA", "KY", "NC", "NFL", "PR", "SC", "SFL", "TN", "VA", "VI", "WCF",
    "AR", "LA", "MS", "NM", "NTX", "OK", "STX", "WTX",
    "EB", "LAX", "ORG", "PAC", "SB", "SCV", "SDG", "SF", "SJV", "SV",
    "AK", "AZ", "EWA", "ID", "MT", "NV", "OR", "UT", "WWA", "WY",
    "MI", "OH", "WV",
    "IL", "IN", "WI",
    "AB", "BC", "GH", "MB", "NB", "NL", "NS", "ONE", "ONN", "ONS", "PE", "QC", "SK", "TER",
)
_SECTION_SET = set(ARRL_SECTIONS)
# andere übliche Schreibweisen -> Section (nur eindeutige Fälle)
_SECTION_ALIAS = {"NF": "NL", "LB": "NL", "VO1": "NL", "VO2": "NL", "NFL": "NL", "NLD": "NL",
                  "NT": "TER", "NU": "TER", "YT": "TER", "NWT": "TER", "VE8": "TER",
                  "VY0": "TER", "VY1": "TER", "PEI": "PE", "VY2": "PE", "PQ": "QC",
                  "VE2": "QC", "VE4": "MB", "VE5": "SK", "VE6": "AB", "VE7": "BC",
                  "VE9": "NB"}
# US-Gebiete außerhalb des Festlands: Section aus der Länderdatei (ARRL 160 m, Regel 2.1.1)
_SECTION_FROM_COUNTRY = {"KL": "AK", "KH6": "PAC", "KP4": "PR", "KP2": "VI"}


def normalize_section(s: str) -> str | None:
    """ARRL/RAC-Section prüfen ("ema" -> "EMA", "NF" -> "NL", "YT" -> "TER")."""
    t = (s or "").strip().upper()
    if t in _SECTION_SET:
        return t
    return _SECTION_ALIAS.get(t)


def section_from_call(call: str, country: str = "") -> str:
    """Section aus Rufzeichen bzw. Land ableiten – nur wenn eindeutig, sonst ""."""
    c = (call or "").strip().upper()
    if "/" in c:
        return ""                         # portabel: Präfix sagt nichts Sicheres
    if country in _SECTION_FROM_COUNTRY:
        return _SECTION_FROM_COUNTRY[country]
    if country.startswith("KH"):
        return "PAC"                      # alle Pazifik-Gebiete (KH0–KH9) zählen als PAC
    prov = province_from_call(c)
    return normalize_section(prov) or ""


# Russland im Russian DX: Europäisches und Asiatisches Russland, Kaliningrad, Franz-Josef-Land
RU_ENTITIES = ("UA", "UA9", "UA2", "R1FJ")

# Russische Oblaste (Kürzel nach rdxc.org/info, Stand 2026-11)
RU_OBLASTS: dict[str, str] = {
    "SP": "Saint Petersburg", "LO": "Leningradskaya", "KO": "Komi", "KL": "Karelia",
    "AR": "Arkhangelsk", "NO": "Nenets AO", "VO": "Vologda", "NV": "Novgorod",
    "PS": "Pskov", "MU": "Murmansk", "KA": "Kaliningrad", "MA": "Moscow city",
    "MO": "Moscow oblast", "OR": "Orel", "LP": "Lipetsk", "TV": "Tver", "VR": "Voronezh",
    "SM": "Smolensk", "YR": "Yaroslavl", "KS": "Kostroma", "TL": "Tula", "TB": "Tambov",
    "RA": "Ryazan", "NN": "Nizhny Novgorod", "IV": "Ivanovo", "VL": "Vladimir",
    "KU": "Kursk", "KG": "Kaluga", "BR": "Bryansk", "BO": "Belgorod", "VG": "Volgograd",
    "SA": "Saratov", "PE": "Penza", "SR": "Samara", "UL": "Ulyanovsk", "KI": "Kirov",
    "TA": "Tatarstan", "MR": "Mari El", "MD": "Mordovia", "UD": "Udmurtia",
    "CU": "Chuvashia", "KR": "Krasnodar", "KC": "Karachay-Cherkessia", "ST": "Stavropol",
    "KM": "Kalmykia", "SO": "North Ossetia", "RK": "Crimea", "RO": "Rostov",
    "CN": "Chechnya", "IN": "Ingushetia", "SE": "Sevastopol", "AO": "Astrakhan",
    "DA": "Dagestan", "KB": "Kabardino-Balkaria", "AD": "Adygea", "DO": "Donetsk",
    "HE": "Kherson", "LU": "Luhansk", "ZP": "Zaporozhye", "CB": "Chelyabinsk",
    "SV": "Sverdlovsk", "PM": "Perm", "TO": "Tomsk", "HM": "Khanty-Mansi AO",
    "YN": "Yamalo-Nenets AO", "TN": "Tyumen", "OM": "Omsk", "NS": "Novosibirsk",
    "KN": "Kurgan", "OB": "Orenburg", "KE": "Kemerovo", "BA": "Bashkortostan",
    "AL": "Altai krai", "GA": "Altai Republic", "KK": "Krasnoyarsk", "HK": "Khabarovsk",
    "EA": "Jewish AO", "SL": "Sakhalin", "MG": "Magadan", "AM": "Amur", "CK": "Chukotka",
    "PK": "Primorye", "BU": "Buryatia", "YA": "Sakha", "IR": "Irkutsk",
    "ZK": "Zabaykalsky", "HA": "Khakassia", "TU": "Tuva", "KT": "Kamchatka",
    "FJ": "Franz Josef Land", "AN": "Antarctica",
}
_OBLAST_ALIAS = {"MS": "MA"}            # laut RDXC-FAQ ebenfalls gültig


def normalize_oblast(s: str) -> str | None:
    """Oblast-Kürzel prüfen ("ma" -> "MA")."""
    t = (s or "").strip().upper()
    if t in RU_OBLASTS:
        return t
    return _OBLAST_ALIAS.get(t)


def region(lk, us_entities: tuple[str, ...] = ("K",)) -> str | None:
    """Einteilung einer Station: "us" (USA ohne Alaska/Hawaii), "ve" (Kanada ohne
    Sable/St. Paul), "xe" (Mexiko), "dl" (Deutschland), "ru" (Russland), "mm" (Maritime Mobile), "dx"
    (alle anderen; wo eine Regel „dl“ nicht kennt, gilt für DL die Angabe für „dx“) oder
    None (unbekannt). ``us_entities``: welche Länder als USA zählen – im ARRL 10 m
    gehören Alaska (KL) und Hawaii (KH6) dazu.

    Die Länderdatei führt Alaska (KL7), Hawaii (KH6), Sable (CY0) und St. Paul (CY9)
    als eigene Gebiete – sie sind damit automatisch "dx", so wie es ARRL DX und CQ 160
    verlangen.
    """
    if lk is None:
        return None
    if getattr(lk, "maritime", False):
        return "mm"
    pfx = getattr(lk, "country", None)
    if pfx in us_entities:
        return "us"
    if pfx == "VE":
        return "ve"
    if pfx == "XE":
        return "xe"
    if pfx == "DL":
        return "dl"                      # Deutschland (DARC-Conteste, ab 0.8.4)
    if pfx in RU_ENTITIES or getattr(lk, "ru_antarctic", False):
        return "ru"                      # Russland (Russian DX, ab 0.8.6; RI1AN ab 0.10.28)
    return "dx"


def is_w_ve(lk) -> bool:
    return region(lk) in ("us", "ve")
