"""0.8.25: DARC-UKW-Paket – VHF/UHF/SHF-Wettbewerb (März/Mai/Juli), Frühling, Mikrowellen,
Marconi, UKW-Winter-/Sommer-Fieldday. Neu (Format 10): Bänder ab 24 GHz, „band_windows“,
„require_portable“."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from gogoham import rulefiles, schedule
from gogoham.bands import (BAND_NAMES, CABRILLO_VHF, DEFAULT_FREQ, adif_band, band_for_freq,
                           band_from_adif, band_label, short_label)
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.cty import CtyDB
from gogoham.export import EDI_BAND, edi, edi_filename

HERE = Path(__file__).parent
NEW = ("darc-vhf", "darc-ukw-spring", "darc-microwave", "marconi-vhf",
       "darc-ukw-fd-winter", "darc-ukw-fd-summer")
MW = ["1.25cm", "6mm", "4mm", "2.5mm", "2mm", "1mm", "submm"]


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def make(cid, cty, call="DL1ABC/P"):
    c = CONTESTS[cid](cty, Station(call=call, lookup=cty.lookup(call), grid="JN59ME"))
    return c, Scorer(c)


def qso(i, t, band, call="DK5XY", ex="001 JO62QM"):
    return Qso(id=i, time=t, call=call, band=band, mode="USB", rst_s="59", rst_r="59",
               exch_s=f"{i:03d}", exch_r=ex, freq=DEFAULT_FREQ[band])


# ------------------------------------------------------------ Bänder
def test_microwave_bands():
    assert BAND_NAMES[-7:] == MW
    for b in MW:
        assert band_for_freq(DEFAULT_FREQ[b]) == b
        assert b in CABRILLO_VHF and b in EDI_BAND
        assert band_from_adif(adif_band(b)) == b
    assert band_label("6mm") == "47 GHz" and band_label("submm") == ">300 GHz"
    assert short_label("20") == "20" and short_label("70cm") == "70 cm"
    assert adif_band("6mm") == "6MM" and adif_band("6") == "6M"
    assert band_from_adif("6m") == "6" and band_from_adif("6MM") == "6mm"
    assert edi_filename("/x/cq.edi", "6mm") == "/x/cq_6mm.edi"
    assert edi_filename("/x/cq.edi", "2") == "/x/cq_2m.edi"


# ------------------------------------------------------------ Termine und Dateien
def test_dates_2026_match_darc_calendar():
    def starts(cid, n):
        return [s for s, _ in schedule.upcoming(CONTESTS[cid].rules["schedule"],
                                                datetime(2026, 1, 1), n)]
    assert starts("darc-vhf", 3) == [datetime(2026, 3, 7, 14), datetime(2026, 5, 2, 14),
                                     datetime(2026, 7, 4, 14)]
    assert starts("darc-ukw-spring", 1) == [datetime(2026, 4, 4, 12)]
    assert starts("darc-microwave", 1) == [datetime(2026, 6, 6, 14)]
    assert starts("marconi-vhf", 1) == [datetime(2026, 11, 7, 14)]
    assert starts("darc-ukw-fd-winter", 1) == [datetime(2026, 2, 7, 9)]
    assert starts("darc-ukw-fd-summer", 1) == [datetime(2026, 8, 1, 7)]
    s, e = schedule.next_period(CONTESTS["darc-ukw-spring"].rules["schedule"],
                                datetime(2026, 1, 1))
    assert (e - s).total_seconds() == 4 * 3600


def test_new_files_need_format_10(monkeypatch):
    for cid in NEW:
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert d["format"] == 10 and rulefiles.validate(d) == []
        monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 9)
        assert "neuere GoGoHam-Version" in rulefiles.validate(d)[0]
        monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 10)


def test_validate_band_windows():
    d = json.loads((rulefiles.BUILTIN_DIR / "darc-ukw-fd-summer.json").read_text("utf-8"))
    for bad in ([], [{"weekday": 7, "from": "0700", "to": "0929", "bands": ["2"]}],
                [{"weekday": 5, "from": "0930", "to": "0700", "bands": ["2"]}],
                [{"weekday": 5, "from": "2460", "to": "2500", "bands": ["2"]}],
                [{"weekday": 5, "from": "0700", "to": "0929", "bands": []}]):
        assert any("band_windows" in e for e in rulefiles.validate({**d, "band_windows": bad}))
    errs = rulefiles.validate({**d, "band_windows": [
        {"weekday": 5, "from": "0700", "to": "0929", "bands": ["0.5mm"]}]})
    assert any("0.5mm" in e for e in errs)
    assert rulefiles.validate({**d, "require_portable": "ja"})


# ------------------------------------------------------------ Fieldday
def test_fieldday_band_windows(cty):
    c, sc = make("darc-ukw-fd-summer", cty)
    ok = [qso(1, "2026-08-01 07:00:00", "23cm"), qso(2, "2026-08-01 12:29:00", "6cm"),
          qso(3, "2026-08-02 09:29:00", "70cm"), qso(4, "2026-08-02 11:59:00", "2")]
    bad = [qso(5, "2026-08-01 09:30:00", "23cm"),      # 23 cm nur bis 09:29
           qso(6, "2026-08-01 10:00:00", "2"),         # 2 m erst am Sonntag
           qso(7, "2026-08-02 12:00:00", "2")]         # nach dem Ende
    for q in ok + bad:
        sc.evaluate(q, commit=True)
    for q in ok:
        assert sc.evals[q.id].valid and sc.evals[q.id].points > 0, q
        assert c.window_problem(q) is None
    for q in bad:
        assert not sc.evals[q.id].valid or sc.evals[q.id].points == 0, q
    msg = c.window_problem(bad[1])
    assert "2 m" in msg and "So 09:30–11:59" in msg


def test_fieldday_needs_portable_call(cty):
    c, _ = make("darc-ukw-fd-winter", cty, call="DL1ABC")
    q = qso(1, "2026-02-08 11:30:00", "2")
    assert any("/p" in n for n in c.notes(q, None))
    c2, _ = make("darc-ukw-fd-winter", cty, call="DL1ABC/P")
    assert not any("/p" in n for n in c2.notes(q, None))
    c3, _ = make("darc-vhf", cty, call="DL1ABC")          # kein Fieldday: kein Hinweis
    assert c3.portable_problem() is None and c3.window_problem(q) is None


def test_marconi_cw_only_2m(cty):
    c, _ = make("marconi-vhf", cty)
    assert c.bands == ["2"] and c.modes == {"CW"} and c.log_format == "edi"


def test_edi_microwave_band(cty):
    c, sc = make("darc-microwave", cty)
    q = qso(1, "2026-06-06 15:00:00", "1.25cm")
    sc.evaluate(q, commit=True)
    txt = edi(c, {"mycall": "DL1ABC/P", "my_grid": "JN59ME", "edi_section": "TR"},
              [q], sc, "1.25cm").decode("ascii")
    assert "PBand=24 GHz" in txt and "PSect=TRAINEE" in txt and "[QSORecords;1]" in txt
