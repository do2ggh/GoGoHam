"""Bänder, Frequenzen und Betriebsarten."""

from __future__ import annotations

# (Band, untere Grenze Hz, obere Grenze Hz, Cabrillo-Frequenz-Bezeichnung)
BANDS = [
    ("160", 1_800_000, 2_000_000),
    ("80", 3_500_000, 4_000_000),
    ("60", 5_250_000, 5_450_000),
    ("40", 7_000_000, 7_300_000),
    ("30", 10_100_000, 10_150_000),
    ("20", 14_000_000, 14_350_000),
    ("17", 18_068_000, 18_168_000),
    ("15", 21_000_000, 21_450_000),
    ("12", 24_890_000, 24_990_000),
    ("10", 28_000_000, 29_700_000),
    ("6", 50_000_000, 54_000_000),
    ("4", 70_000_000, 70_500_000),
    ("2", 144_000_000, 148_000_000),
    ("1.25", 222_000_000, 225_000_000),       # nur Region 2 (ARRL-UKW-Contests, ab 0.10.33)
    # ab 70 cm: Name mit "cm", damit es keine Verwechslung mit Meter-Bändern gibt (6 m / 6 cm)
    ("70cm", 420_000_000, 450_000_000),
    ("33cm", 902_000_000, 928_000_000),       # nur Region 2 (ab 0.10.33)
    ("23cm", 1_240_000_000, 1_300_000_000),
    ("13cm", 2_300_000_000, 2_450_000_000),
    ("9cm", 3_300_000_000, 3_500_000_000),
    ("6cm", 5_650_000_000, 5_925_000_000),
    ("3cm", 10_000_000_000, 10_500_000_000),
    # ab 0.8.25 (DARC-UKW-Wettbewerbe): Namen wie in ADIF; angezeigt wird die Frequenz (GHz)
    ("1.25cm", 24_000_000_000, 24_250_000_000),
    ("6mm", 47_000_000_000, 47_200_000_000),
    ("4mm", 75_500_000_000, 81_000_000_000),
    ("2.5mm", 119_980_000_000, 123_000_000_000),
    ("2mm", 134_000_000_000, 149_000_000_000),
    ("1mm", 241_000_000_000, 250_000_000_000),
    ("submm", 300_000_000_000, 7_500_000_000_000),
]

# Mikrowellen ab 24 GHz: Anzeige als Frequenz, so heißen sie auch in den Ausschreibungen
GHZ_LABEL = {"1.25cm": "24 GHz", "6mm": "47 GHz", "4mm": "76 GHz", "2.5mm": "122 GHz",
             "2mm": "134 GHz", "1mm": "245 GHz", "submm": ">300 GHz"}

BAND_NAMES = [b[0] for b in BANDS]
CONTEST_BANDS = ["160", "80", "40", "20", "15", "10"]

# Standard-Frequenz je Band (Hz), wenn kein CAT vorhanden ist
DEFAULT_FREQ = {
    "160": 1_840_000, "80": 3_700_000, "60": 5_357_000, "40": 7_100_000,
    "30": 10_120_000, "20": 14_200_000, "17": 18_120_000, "15": 21_250_000,
    "12": 24_940_000, "10": 28_500_000, "6": 50_150_000, "4": 70_200_000,
    "2": 144_300_000, "1.25": 222_100_000, "70cm": 432_200_000, "33cm": 903_100_000, "23cm": 1_296_200_000,
    "13cm": 2_320_200_000, "9cm": 3_400_100_000, "6cm": 5_760_100_000,
    "3cm": 10_368_100_000, "1.25cm": 24_048_100_000, "6mm": 47_088_100_000,
    "4mm": 76_032_100_000, "2.5mm": 122_250_100_000, "2mm": 134_928_100_000,
    "1mm": 248_000_100_000, "submm": 300_000_000_000,
}

# Startfrequenz für Ein-Band-Contests (ARRL 10 m, CQ 160) – je nach Mode im passenden Bereich
CONTEST_START_FREQ = {
    "10": {"CW": 28_025_000, "PH": 28_450_000},
    "160": {"CW": 1_825_000, "PH": 1_850_000},
}

# Frequenz für die Cabrillo-Spalte bei VHF/UHF (laut Cabrillo 3.0)
CABRILLO_VHF = {"6": "50", "4": "70", "2": "144", "1.25": "222", "70cm": "432", "33cm": "902", "23cm": "1.2G",
                "13cm": "2.3G", "9cm": "3.4G", "6cm": "5.7G", "3cm": "10G",
                "1.25cm": "24G", "6mm": "47G", "4mm": "75G", "2.5mm": "122G", "2mm": "134G",
                "1mm": "241G", "submm": "LIGHT"}

# Betriebsarten, die das IC-7300 (bzw. Hamlib) liefert, plus digitale Modi aus WSJT-X
RIG_MODES = ["USB", "LSB", "CW", "CWR", "RTTY", "RTTYR", "AM", "FM",
             "PKTUSB", "PKTLSB", "FT8", "FT4", "PSK31", "JT65"]

PHONE = {"USB", "LSB", "AM", "FM", "SSB", "PH"}
CW = {"CW", "CWR", "CW-R"}
RTTY = {"RTTY", "RTTYR", "RTTY-R", "RY"}
DIGI = {"PKTUSB", "PKTLSB", "PKTFM", "FT8", "FT4", "MFSK", "PSK31", "PSK", "PSK63", "BPSK63", "BPSK31",
        "JT65", "JT9", "Q65", "DATA", "DG", "DIGI"}


def has_unit(band: str) -> bool:
    """Bandname mit eigener Einheit ("70cm", "6mm", "submm") statt reiner Meterzahl ("20")?"""
    b = band or ""
    return b.endswith("cm") or b.endswith("mm")


def short_label(band: str) -> str:
    """Kurz: Meter-Bänder ohne Einheit ("20"), sonst mit ("70 cm", "24 GHz")."""
    return band_label(band) if has_unit(band) else (band or "")


def band_label(band: str) -> str:
    """Anzeige: "20" -> "20 m", "70cm" -> "70 cm", "6mm" -> "47 GHz"."""
    b = band or ""
    if b in GHZ_LABEL:
        return GHZ_LABEL[b]
    if b.endswith("cm"):
        return f"{b[:-2]} cm"
    return f"{b} m" if b else ""


def adif_band(band: str) -> str:
    """ADIF-Bandname: "20" -> "20M", "70cm" -> "70CM", "6mm" -> "6MM"."""
    b = (band or "").upper()
    return b if has_unit(band) else f"{b}M"


def band_from_adif(name: str) -> str:
    """ADIF-Bandname -> GoGoHam: "20m" -> "20", "70CM" -> "70cm" ("" wenn unbekannt)."""
    n = (name or "").strip().lower()
    if n.endswith("cm") or n.endswith("mm"):
        b = n
    elif n.endswith("m"):
        b = n[:-1]
    else:
        return ""
    return b if b in BAND_NAMES else ""


def band_for_freq(freq_hz: int | float | None) -> str | None:
    if not freq_hz:
        return None
    for name, lo, hi in BANDS:
        if lo <= freq_hz <= hi:
            return name
    return None


def cabrillo_mode(mode: str) -> str:
    """Rig-/ADIF-Mode -> Cabrillo-Mode (PH, CW, RY, DG)."""
    m = (mode or "").upper()
    if m in PHONE:
        return "PH"
    if m in CW:
        return "CW"
    if m in RTTY:
        return "RY"
    if m in DIGI:
        return "DG"
    return "PH" if not m else "DG"


def op_mode(mode: str) -> str:
    """Betriebsart für Zeitfenster und Dupes „je Betriebsart“ (Format 15): wie Cabrillo, aber
    Sprechfunk getrennt in SSB, FM und AM (Schwaben-Contest: 2 m SSB und 2 m FM)."""
    m = (mode or "").upper()
    if m == "FM":
        return "FM"
    if m == "AM":
        return "AM"
    cm = cabrillo_mode(m)
    return "SSB" if cm == "PH" else cm


def default_rst(mode: str) -> str:
    cm = cabrillo_mode(mode)
    if cm == "PH":
        return "59"
    if cm in ("CW", "RY"):
        return "599"
    return "-10"


def adif_mode(mode: str) -> tuple[str, str]:
    """Rig-Mode -> (ADIF MODE, ADIF SUBMODE)."""
    m = (mode or "").upper()
    if m in ("USB", "LSB"):
        return "SSB", m
    if m in ("CW", "CWR"):
        return "CW", ""
    if m in ("RTTY", "RTTYR"):
        return "RTTY", ""
    if m == "FT4":
        return "MFSK", "FT4"
    if m in ("PKTUSB", "PKTLSB"):
        return "PKT", ""
    if m in ("PSK31", "BPSK31", "PSK63", "BPSK63"):      # ADIF 3: PSK mit Untermodus
        return "PSK", "PSK63" if m.endswith("63") else "PSK31"
    return m, ""
