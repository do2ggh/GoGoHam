"""0.9.1: Call-History schreibt sich selbst (dauerhafte Datei, alte Logs einlesen, Grundstock)."""

from pathlib import Path

import pytest

from gogoham import callhistory as ch
from gogoham.contests import Qso
from gogoham.cty import CtyDB
from gogoham.db import LogDB

HERE = Path(__file__).parent

# Erfundenes Cabrillo-Log – mit Kopf, der nie übernommen werden darf
CBR_CQWW = """START-OF-LOG: 3.0
CONTEST: CQ-WW-SSB
CALLSIGN: DL0XXX
NAME: Max Mustermann
ADDRESS: Musterstrasse 1
EMAIL: max@example.org
QSO:  3500 PH 2025-10-25 0009 DL0XXX        59  14     W1AW          59  05     0
QSO: 14000 PH 2025-10-25 0014 DL0XXX        59  14     VK6ABC        59  29     0
QSO: 14000 PH 2025-10-26 1014 DL0XXX        59  14     W1AW          59  04     0
END-OF-LOG:
"""

CBR_DARC = """START-OF-LOG: 3.0
CONTEST: DARC-10
CALLSIGN: DL0XXX
QSO: 28000 PH 2026-01-11 0901 DL0XXX        59  001 B36    DL1ABC        59  012 C01
QSO: 28000 PH 2026-01-11 0902 DL0XXX        59  002 B36    W1AW          59  044 -
END-OF-LOG:
"""

CBR_WPX = """START-OF-LOG: 3.0
CONTEST: CQ-WPX-SSB
QSO:  3500 PH 2026-03-28 0001 DL0XXX        59  001    IB4X          59  1      0
END-OF-LOG:
"""


@pytest.fixture
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def q(call, exch_r, t):
    return Qso(id=None, time=t, call=call, band="20", mode="USB", freq=14_250_000,
               rst_s="59", exch_s="14", rst_r="59", exch_r=exch_r)


def test_extract_only_fixed_parts():
    assert ch.extract("cq_zone", "05") == [("zone", "5")]
    assert ch.extract("cq_zone", "41") == []
    assert ch.extract("serial", "123") == []                      # Nummern nie
    assert ch.extract("power", "KW") == []                        # Leistung nie
    assert ch.extract("serial_dok", "12 b36") == [("dok", "B36")]
    assert ch.extract("serial_dok", "12 NM") == []
    assert ch.extract("serial_grid6", "007 jn59me") == [("grid", "JN59ME")]
    assert ch.extract("grid4", "jn59") == [("grid", "JN59")]
    assert ch.extract("lic_year", "82") == [("lic_year", "82")]
    assert ch.extract("serial_member", "067/2583") == [("member", "2583")]
    assert ch.extract("serial_iota", "12 EU5") == [("iota", "EU-005")]
    assert ch.extract("iaru", "DARC") == [("iaru", "DARC")]
    assert ch.extract("state", "ct") == [("state", "CT")]


def test_learns_persistently_and_newest_wins():
    h = ch.build(None)
    h.learn_qso("cqww-ssb", "W1AW", "05", "2026-10-24 10:00:00")
    h.learn_qso("cqww-ssb", "W1AW", "04", "2026-10-25 10:00:00")
    h.learn_qso("cqww-ssb", "W1AW", "06", "2025-10-25 10:00:00")   # älter: zählt nicht
    assert h.get("W1AW").zone == "4"
    h2 = ch.build(None)                                            # neuer Start: noch da
    assert h2.get("W1AW").zone == "4"
    assert h2.suggest("W1AW", "cq_zone") == ("04", "zone")
    # QSO gelöscht -> der Wert davor gilt wieder
    h2.forget_qso("W1AW", "2026-10-25 10:00:00")
    assert h2.get("W1AW").zone == "5"
    # von Hand vergessen -> weg, auch nach neuem Start; ein neues QSO lernt wieder
    h2.set_value("W1AW", "zone", "")
    assert h2.get("W1AW") is None and ch.build(None).get("W1AW") is None
    h2.learn_qso("cqww-ssb", "W1AW", "05", "2099-01-01 00:00:00")
    assert ch.build(None).get("W1AW").zone == "5"


def test_log_deleted_history_stays(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    db = LogDB(logs / "a.ggh")
    db.set_meta({"contest": "cqww-ssb"})
    db.add(q("JA1ABC", "25", "2026-10-24 01:00:00"))
    db.close()
    assert ch.build(logs).get("JA1ABC").zone == "25"
    for f in logs.iterdir():
        f.unlink()
    assert ch.build(logs).get("JA1ABC").zone == "25"


def test_cabrillo_learning(tmp_path, cty):
    p = tmp_path / "cq.cbr"
    p.write_text(CBR_CQWW, encoding="latin-1")
    h = ch.build(None)
    n, learned, name = h.learn_file(p, cty)
    assert (n, learned, name) == (3, 3, "CQ-WW-SSB")
    assert h.get("W1AW").zone == "4" and h.get("VK6ABC").zone == "29"
    rows = h.store.rows()
    assert not any("Mustermann" in str(r) or "example" in str(r) for r in rows)
    d = tmp_path / "darc.cbr"
    d.write_text(CBR_DARC)
    h.learn_file(d, cty)
    assert h.get("DL1ABC").dok == "C01"
    assert h.suggest("DL1ABC", "serial_dok") == ("C01", "dok")
    w = tmp_path / "wpx.cbr"
    w.write_text(CBR_WPX)
    assert h.learn_file(w, cty)[:2] == (1, 0)                    # WPX: nur Nummern
    bad = tmp_path / "x.cbr"
    bad.write_text("CONTEST: GIBTS-NICHT\nQSO: 1 2 3 4 5 6 7 8\n")
    with pytest.raises(ValueError):
        h.learn_file(bad, cty)


def test_base_file_has_lowest_rank(tmp_path, monkeypatch):
    base = tmp_path / "base.csv"
    ch.write_base([("W1AW", "zone", "3", "2025-10-25 00:00:00"),
                   ("W1AW", "zone", "5", "2026-10-24 00:00:00"),
                   ("K1ZZ", "zone", "5", "2026-10-24 00:00:00")], base)
    monkeypatch.setattr(ch, "BASE_FILE", base)
    assert "W1AW,zone,5,2026-10-24" in base.read_text()
    h = ch.build(None)
    assert h.get("W1AW").zone == "5" and h.get("W1AW").values["zone"][2] == "base"
    h.learn_qso("cqww-ssb", "W1AW", "04", "2000-01-01 00:00:00")  # eigenes QSO gewinnt immer
    assert h.get("W1AW").zone == "4"
    h.forget_qso("W1AW", "2000-01-01 00:00:00")                    # Grundstock kommt zurück
    assert h.get("W1AW").zone == "5"


def test_shipped_base_file_is_clean():
    """Mitgelieferter Grundstock: nur Rufzeichen und feste Angaben, nichts Persönliches."""
    p = Path(ch.__file__).parent / "assets" / "callhistory-base.csv"
    text = p.read_text(encoding="utf-8")
    rows = ch._base_rows(p)
    assert len(rows) > 300
    assert {r[1] for r in rows} <= set(ch.KEYS)
    import re
    for line in text.splitlines():                # nur Kommentar, Kopf oder Datenzeile
        assert line.startswith("# ") or line == "call,key,value,date" or re.fullmatch(
            r"[A-Z0-9/]{3,12},[a-z_]+,[A-Z0-9-]{1,8},\d{4}-\d\d-\d\d", line), line
    assert "@" not in text


def test_age_grows_with_the_years():
    h = ch.CallHistory()
    h._put("JA1ABC", "age", "59", ch.RANK_OWN, "2024-06-15 01:00:00", "aa-cw")
    assert h.suggest("JA1ABC", "age", year=2026) == ("61", "age")


def test_gui_learns_but_not_in_practice(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(HERE))
    from test_gui_logic import new_log
    import fake_qt
    fake_qt.install()
    for m in [m for m in sys.modules if m.startswith("gogoham.gui")]:
        del sys.modules[m]
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path))
    import gogoham.cty as ctymod
    monkeypatch.setattr(ctymod.CtyDB, "load_default",
                        classmethod(lambda c: c.from_file(HERE / "cty_sample.dat")))
    import gogoham.config as cfgmod
    cfg = cfgmod.load()
    cfg["rig_enabled"] = False
    cfg["wsjtx_enabled"] = False
    cfgmod.save(cfg)
    from gogoham.gui.main_window import MainWindow
    w = MainWindow()
    try:
        new_log(w, fake_qt, tmp_path, "cqww-ssb")
        w.ed_call.type("VK6ABC")
        w.ed_exch.setText("30")
        w.enter_pressed()
        assert ch.build(None).get("VK6ABC").zone == "30"          # sofort in der Datei
        # Bearbeiten: neuer Wert ersetzt den alten
        qso = w.qsos[-1]
        w.history.forget_qso(qso.call, qso.time)
        w.history.learn_qso(w.contest, qso.call, "29", qso.time)
        assert ch.build(None).get("VK6ABC").zone == "29"
        # Übung: erfundene Stationen nicht lernen
        w.practice = object()
        w._store(q("ZZ9ZZZ", "05", "2026-10-24 02:00:00"))
        assert w.history.get("ZZ9ZZZ") is None
    finally:
        w.practice = None
        w.closeEvent(fake_qt.Stub())


def test_base_can_be_removed_and_logs_scanned_once(tmp_path, monkeypatch):
    base = tmp_path / "base.csv"
    ch.write_base([("W1AW", "zone", "5", "2026-10-24"), ("K1ZZ", "zone", "5", "2026-10-24")],
                  base)
    monkeypatch.setattr(ch, "BASE_FILE", base)
    logs = tmp_path / "logs"
    logs.mkdir()
    db = LogDB(logs / "a.ggh")
    db.set_meta({"contest": "cqww-ssb"})
    db.add(q("JA1ABC", "25", "2026-10-24 01:00:00"))
    db.close()
    h = ch.build(logs)
    h.learn_qso("cqww-ssb", "K1ZZ", "04", "2026-10-25 01:00:00")
    assert len(h) == 3 and h.base_enabled()
    h.set_base_enabled(False)                         # nur noch Eigenes
    assert h.get("W1AW") is None and h.get("K1ZZ").zone == "4" and h.get("JA1ABC")
    h2 = ch.build(logs)
    assert h2.get("W1AW") is None and not h2.base_enabled()
    h2.set_base_enabled(True)
    assert h2.get("W1AW").zone == "5"
    # Log-Ordner nur beim ersten Mal: Gelöschtes kommt nicht wieder
    h2.forget_qso("JA1ABC", "2026-10-24 01:00:00")
    assert h2.get("JA1ABC") is None and ch.build(logs).get("JA1ABC") is None
