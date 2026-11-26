"""Bänder ab 70 cm (0.6.2): Erkennung, Schreibweise, Export, WSJT-X, Regel-Dateien."""

import copy
import json

from gogoham import rulefiles
from gogoham.bands import (BAND_NAMES, CABRILLO_VHF, DEFAULT_FREQ, adif_band, band_for_freq,
                           band_from_adif, band_label)
from gogoham.contests import Qso, Station
from gogoham.contests.rulebased import make_contest_class
from gogoham.export import adif, cabrillo_qso_line
from gogoham.wsjtx import adif_to_qso, parse_packet

UHF = ["70cm", "23cm", "13cm", "9cm", "6cm", "3cm"]


def test_new_bands_present_and_ordered():
    # ab 0.10.33 liegen 222 MHz („1.25“) und 902 MHz („33cm“) dazwischen (nur Region 2)
    assert [b for b in BAND_NAMES[-16:-7] if b not in ("1.25", "33cm")] == ["2"] + UHF
    for b in UHF:
        assert b in DEFAULT_FREQ and b in CABRILLO_VHF
        assert band_for_freq(DEFAULT_FREQ[b]) == b


def test_band_for_freq_uhf():
    assert band_for_freq(432_200_000) == "70cm"
    assert band_for_freq(1_296_200_000) == "23cm"
    assert band_for_freq(10_368_100_000) == "3cm"
    assert band_for_freq(5_760_100_000) == "6cm"
    assert band_for_freq(50_150_000) == "6"                 # 6 m bleibt 6 m
    assert band_for_freq(900_000_000) is None              # kein Amateurband


def test_band_label_and_adif_names():
    assert band_label("20") == "20 m" and band_label("2") == "2 m"
    assert band_label("70cm") == "70 cm" and band_label("3cm") == "3 cm"
    assert band_label("") == ""
    assert adif_band("20") == "20M" and adif_band("70cm") == "70CM"
    assert band_from_adif("20m") == "20" and band_from_adif("70CM") == "70cm"
    assert band_from_adif("23cm") == "23cm" and band_from_adif("1mm") == "1mm" \
        and band_from_adif("0.5mm") == ""
    assert band_from_adif("") == ""


def test_cabrillo_freq_uhf():
    d = {"format": 1, "id": "uhf-test", "name": "UHF-Test", "bands": ["2", "70cm", "23cm"],
         "modes": ["PH", "CW"], "exchange": [{"field": "rst"}, {"field": "serial"}],
         "points": {"type": "fixed", "value": 1}, "multipliers": []}
    assert rulefiles.validate(d) == []
    c = make_contest_class(d)(None, Station(call="DO2GGH"))
    for band, freq, want in [("70cm", 432_200_000, "432"), ("23cm", 1_296_200_000, "1.2G"),
                             ("2", 144_300_000, "144")]:
        q = Qso(time="2026-11-07 14:00:00", call="DL1ABC", band=band, mode="USB", freq=freq,
                rst_s="59", exch_s="001", rst_r="59", exch_r="005")
        line = cabrillo_qso_line(c, q, "DO2GGH")
        assert line.split()[1] == want, line
    out = adif(c, {"mycall": "DO2GGH"}, [Qso(time="2026-11-07 14:00:00", call="DL1ABC",
                                               band="70cm", mode="USB", freq=432_200_000)])
    assert "<BAND:4>70CM" in out and "<FREQ:10>432.200000" in out


def test_wsjtx_uhf_band():
    rec = parse_packet(b"<call:4>W1AW <mode:3>FT8 <qso_date:8>20261107 <time_on:6>120000 "
                       b"<band:4>70cm <freq:10>432.174000 <EOR>")
    assert adif_to_qso(rec).band == "70cm"
    rec = parse_packet(b"<call:4>W1AW <mode:3>FT8 <qso_date:8>20261107 <time_on:6>120000 "
                       b"<band:4>23cm <EOR>")                      # ohne Frequenz
    assert adif_to_qso(rec).band == "23cm"


def test_rule_files_accept_uhf_bands():
    d = json.loads((rulefiles.BUILTIN_DIR / "cqww-ssb.json").read_text(encoding="utf-8"))
    d = copy.deepcopy(d)
    d["bands"] = ["2", "70cm", "23cm", "13cm"]
    assert rulefiles.validate(d) == []
    d["points"]["other_continent"] = {"default": 3, "70cm": 5}
    assert rulefiles.validate(d) == []
