"""0.7.2: passende Felder im Log-Fenster, IARU-Verbandsstationen, Erfrage-Hinweise,
Angebot „aufs Contest-Band wechseln“."""

from pathlib import Path

import pytest

from gogoham.contests import CONTESTS, Qso, Station
from gogoham.contests.rulebased import is_hq_call, station_fields
from gogoham.cty import CtyDB

HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


@pytest.mark.parametrize("cid, want", [
    ("cqww-ssb", {"zone"}), ("cqww-cw", {"zone"}), ("wpx-ssb", set()), ("ww-digi", set()),
    ("cq160-cw", {"zone", "state"}), ("arrl-dx-ssb", {"power", "state"}),
    ("arrl-10", {"state"}), ("iaru-hf", {"itu"}), ("euhfc", {"licyear"}),
])
def test_station_fields(cid, want):
    assert station_fields(CONTESTS[cid]) == want


def test_hq_calls(cty):
    assert is_hq_call("DA0HQ") and is_hq_call("OL9HQ") and is_hq_call("9A0HQ/P")
    assert not is_hq_call("DL1HQA") and not is_hq_call("W1AW") and not is_hq_call("")
    c = CONTESTS["iaru-hf"](cty, Station(call="DL1ABC"))
    assert c.default_rcvd_exchange(cty.lookup("DA0HQ"), "DA0HQ") == ""
    assert c.default_rcvd_exchange(cty.lookup("DL2XX"), "DL2XX") == "28"
    assert "Kürzel erfragen" in c.ask_text(Qso(call="DA0HQ"), cty.lookup("DA0HQ"))
    assert c.ask_text(Qso(call="DL2XX"), cty.lookup("DL2XX")) is None


def test_ask_texts(cty):
    def ask(cid, call, **st):
        c = CONTESTS[cid](cty, Station(call=st.pop("me", "DL1ABC"), **st))
        return c.ask_text(Qso(call=call), cty.lookup(call))
    assert ask("cq160-cw", "W1AW") == "State: erfragen"
    assert ask("cq160-cw", "VE1ABC") == "Provinz: erfragen"
    assert ask("cq160-cw", "DL2XX") is None                  # Zone hat eigene Zeile
    assert ask("arrl-10", "OE1XX") == "Nummer: erfragen"
    assert ask("arrl-10", "K1ABC/MM") == "ITU-Region: erfragen"
    assert ask("euhfc", "OE1XX") == "Jahr der ersten Lizenz: erfragen"
    assert ask("arrl-dx-cw", "DL2XX", me="W1AW", state="CT") == "Leistung: erfragen"
    assert ask("cqww-ssb", "W1AW") is None


def test_infobox_shows_ask_line(cty):
    from gogoham import infobox
    from gogoham.contests import Scorer
    c = CONTESTS["cq160-cw"](cty, Station(call="DL1ABC"))
    s = Scorer(c)
    q = Qso(call="W1AW", band="160", mode="CW")
    box = infobox.build(c, s, q, s.evaluate(q), "JN59")
    assert any(t == "State: erfragen" for t, _c in box.lines)
    q.exch_r = "CT"                                          # eingetragen: kein Hinweis mehr
    box = infobox.build(c, s, q, s.evaluate(q), "JN59")
    assert not any("erfragen" in t for t, _c in box.lines)
