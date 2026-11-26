"""0.8.24.1: FT-991A – antwortet auf „;ID;“ nur „?;“ und meldet sich mit ID0670 (am Gerät des
Nutzers so gemessen: erster CP2105-Anschluss, 38400 Baud)."""

from gogoham import rigdetect as d
from gogoham.hamlib import RigModel as Rig


RIGS = [Rig(1035, "Yaesu", "FT-991"), Rig(1036, "Yaesu", "FT-891")]


def _ft991a(path, baud, data, wait, rts=False):
    if baud != 38400:
        return b""
    if data == d.CAT_QUERY:
        return b"?;"
    if data == d.CAT_QUERY_PLAIN:
        return b"ID0670;"
    return b""


def test_ft991a_detected_after_plain_retry():
    r = d.probe("/x", _ft991a)
    assert r.ok and r.name == "FT-991A" and r.baud == 38400
    assert d.hamlib_model("FT-991A", RIGS) == 1035      # Hamlib-Modell „FT-991“
    assert d.hamlib_model("FT-991", RIGS) == 1035


def test_no_plain_retry_without_question_mark():
    calls = []

    def ex(path, baud, data, wait, rts=False):
        calls.append(data)
        return b""
    assert not d.probe("/x", ex).ok
    assert d.CAT_QUERY_PLAIN not in calls               # andere Geräte: alles wie bisher
