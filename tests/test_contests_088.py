"""0.8.8: UKW – IARU Region 1 VHF/UHF, Kilometer-Wertung, Nummer je Band, EDI-Export."""

import json
import shutil
from pathlib import Path

import pytest

from conftest import builtin_newer_than
from gogoham import rulefiles, schedule
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.contests.rulebased import split_serial_grid, station_fields
from gogoham.cty import CtyDB
from gogoham.export import _edi_text, edi, edi_filename
from gogoham.locator import iaru_km, iaru_points

HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def test_files_format_8_and_valid():
    assert rulefiles.FORMAT_VERSION >= 8
    for cid in ("iaru-vhf", "iaru-uhf"):
        d = json.loads((rulefiles.BUILTIN_DIR / f"{cid}.json").read_text(encoding="utf-8"))
        assert d["format"] == 8 and rulefiles.validate(d) == []
        cls = CONTESTS[cid]
        assert cls.log_format == "edi" and cls.serial_per_band and cls.score_rule == "points_sum"
        assert station_fields(cls) == {"edi"}
    assert CONTESTS["iaru-vhf"].bands == ["2"]
    assert CONTESTS["iaru-uhf"].bands[0] == "70cm"


def test_087_skips_format_8(tmp_path, monkeypatch):
    """Die installierte 0.8.7 (Format 7) überspringt die UKW-Dateien sauber."""
    from gogoham import rulesupdate
    src = tmp_path / "gh"
    src.mkdir()
    for p in rulefiles.BUILTIN_DIR.glob("*.json"):
        shutil.copy(p, src / p.name)
    (src / "index.json").write_text(json.dumps(rulesupdate.make_index(src)), encoding="utf-8")
    monkeypatch.setattr(rulefiles, "FORMAT_VERSION", 7)
    monkeypatch.setattr(rulefiles, "BUILTIN_DIR", tmp_path / "leer")
    (tmp_path / "leer").mkdir()
    res = rulesupdate.check_and_download(src.as_uri() + "/", tmp_path / "data")
    want, rest = builtin_newer_than(7)
    assert sorted(res.skipped) == want and "IARU Region 1 VHF (145 MHz)" in want
    assert not res.errors and len(res.new) == rest


def test_bad_ukw_blocks_are_reported():
    d = json.loads((rulefiles.BUILTIN_DIR / "iaru-vhf.json").read_text(encoding="utf-8"))
    d["serial_per_band"] = "ja"
    d["multipliers"] = [{"type": "country", "per": "band"}]
    errs = " ".join(rulefiles.validate(d))
    assert "serial_per_band" in errs and "points_sum" in errs
    d = json.loads((rulefiles.BUILTIN_DIR / "iaru-vhf.json").read_text(encoding="utf-8"))
    d["exchange"] = [{"field": "rst"}, {"field": "serial"}]
    assert "serial_grid6" in " ".join(rulefiles.validate(d))


def test_schedules():
    s, e = schedule.period(CONTESTS["iaru-vhf"].schedule, 2026)
    assert str(s) == "2026-09-05 14:00:00" and (e - s).total_seconds() == 24 * 3600
    assert str(schedule.period(CONTESTS["iaru-uhf"].schedule, 2026)[0]) == "2026-10-03 14:00:00"


def test_iaru_km_matches_edi_example():
    """Werte aus dem offiziellen EDI-Beispiel (OZ1FDJ, JO65FR)."""
    assert iaru_points("JO65FR", "JO65ER") == 6
    assert iaru_points("JO65FR", "JO42LT") == 396
    assert iaru_points("JO65FR", "IP62OA") == 1302
    assert iaru_points("JO65FR", "JO65FR") == 1          # gleicher Locator: 1 Punkt
    assert 5 < iaru_km("JO65FR", "JO65ER") < 6


def test_exchange_parsing_and_check():
    assert split_serial_grid("12 jo20db") == ("12", "JO20DB")
    assert split_serial_grid("JO20DB 12") == ("12", "JO20DB")
    c = CONTESTS["iaru-vhf"](None, Station(call="DO2GGH", grid="JN59ME"))
    assert c.validate_exchange("12 JO20DB") is None
    assert c.validate_exchange("12 JO20")                  # 6 Stellen nötig
    assert c.validate_exchange("JO20DB")                   # Nummer fehlt
    assert c.sent_exchange(7) == "007 JN59ME" and c.uses_serial


def run(cty):
    c = CONTESTS["iaru-vhf"](cty, Station(call="OZ1FDJ", grid="JO65FR"))
    s = Scorer(c)
    qs = [("OZ9SIG", "USB", "006 JO65ER"), ("DL5BBF", "USB", "023 JO42LT"),
          ("OZ9SIG", "USB", "006 JO65ER"), ("DL1A", "CW", "7 JO50AA")]
    out = []
    for i, (call, mode, ex) in enumerate(qs, 1):
        q = Qso(id=i, time=f"2026-09-05 14:{i:02d}:00", call=call, band="2", mode=mode,
                rst_s="59", rst_r="59", exch_s=c.sent_exchange(i), exch_r=ex)
        s.evaluate(q, commit=True)
        out.append(q)
    return c, s, out


def test_scoring_points_sum(cty):
    c, s, qsos = run(cty)
    pts = [s.evals[q.id].points for q in qsos]
    assert pts[:3] == [6, 396, 0] and s.evals[3].dupe
    assert s.score == sum(pts)                             # keine Multis, nur Kilometer
    assert s.evals[2].gain == 396
    assert "km" in c.describe(qsos[1], s.evals[2].lookup)


def test_edi_export(cty):
    c, s, qsos = run(cty)
    meta = {"mycall": "OZ1FDJ", "my_grid": "JO65fr", "name": "Bo Hansen", "email": "a@b",
            "my_power_w": "90", "my_antenna": "9 el", "edi_section": "MO",
            "address": "Gade 1\nKøbenhavn", "operators": "OZ1FDJ OZ1FTU", "soapbox": "Schön"}
    raw = edi(c, meta, qsos, s, "2")
    raw.decode("ascii")                                    # nur 7-Bit-ASCII
    assert b"\r\n" in raw and raw.endswith(b"\r\n")
    text = raw.decode("ascii").split("\r\n")
    assert text[0] == "[REG1TEST;1]"
    assert "PBand=144 MHz" in text and "PWWLo=JO65FR" in text and "PSect=MULTI" in text
    assert "MOpe1=OZ1FTU" in text and "RCall=OZ1FDJ" in text and "PAdr2=Kobenhavn" in text
    assert f"CQSOP={s.score}" in text
    assert any(t.startswith("CODXC=DL1A;JO50AA;") for t in text)          # weitestes QSO
    assert "[QSORecords;4]" in text
    assert any(t.startswith("260905;1401;OZ9SIG;1;59;001;59;006;;JO65ER;6;;N;") for t in text)
    assert "260905;1403;OZ9SIG;1;59;003;59;006;;JO65ER;0;;;;D" in text
    assert any(t.startswith("260905;1404;DL1A;2;") for t in text)          # CW = 2
    assert "[Remarks]" in text and "Schoen" in text


def test_edi_helpers():
    assert edi_filename("/x/log.edi", "2") == "/x/log_2m.edi"
    assert edi_filename("/x/log", "70cm") == "/x/log_70cm.edi"
    assert _edi_text("Łódź – Müller") == "Lodz - Mueller"
