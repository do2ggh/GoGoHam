"""0.10.7: Sendepegel für fldigi einmessen – mit Attrappen, gesendet wird nichts."""

from gogoham import fldigi, levelcal


class FakeProxy:
    def __init__(self, log):
        self.log = log
        self.main = self

    def run_macro(self, n):
        self.log.append(("macro", n))

    def tune(self):
        self.log.append(("tune",))

    def abort(self):
        self.log.append(("abort",))

    def rx(self):
        self.log.append(("rx",))


class FakeClient:
    def __init__(self):
        self.log = []
        self.proxy = FakeProxy(self.log)


def test_macros_and_choose(tmp_path):
    m = levelcal.level_macros()
    assert m[0] == (36, "TX -30 dB", "<TXATTEN:-30.0>") and m[-1] == (46, "TX 0 dB", "<TXATTEN:0.0>")
    assert levelcal.macro_for(-30) == 36 and levelcal.macro_for(-9) == 43 == levelcal.macro_for(-10)
    p = tmp_path / "macros.mdf"
    fldigi.write_macros(p, "<CNTR>")
    t = p.read_text()
    assert "\n/$ 36 TX -30 dB\n<TXATTEN:-30.0>\n" in t and "/$ 46 TX 0 dB" in t
    assert levelcal.choose([(-30, 0.0), (-27, 0.0), (-24, 0.3)]) == (-27, "ok")
    assert levelcal.choose([(-30, 0.5)]) == (-30, "too_loud")
    assert levelcal.choose([(d, 0.0) for d in levelcal.STEPS]) == (0, "no_alc")
    w = fldigi.wanted("127.0.0.1", 4532, txatten=-12)
    assert w["TXATTEN"] == "-12" and w["TXLEVEL_BY_MODE"] == "0"
    assert "TXATTEN" not in fldigi.wanted("127.0.0.1", 4532)


def test_calibration_run_stops_tx():
    c = FakeClient()
    alc = {"v": 0.0}
    steps_seen = []

    def read(host, port):
        # ALC steigt ab der dritten Stufe
        return alc["v"]

    def progress(text):
        steps_seen.append(text)
        if len(steps_seen) >= 3:
            alc["v"] = 0.5
    cal = levelcal.Calibration(c, "127.0.0.1", 4532, read=read, settle=0, progress=progress)
    cal.run()
    assert cal.error == "" and cal.result[0] == -24 and cal.result[1] == "ok"
    assert ("tune",) in c.log and c.log.index(("tune",)) < c.log.index(("abort",))
    assert c.log[-1] == ("macro", levelcal.macro_for(-24))     # gewählte Stufe eingestellt
    assert ("rx",) in c.log
    # ohne ALC-Anzeige: gar nicht erst senden
    c2 = FakeClient()
    cal2 = levelcal.Calibration(c2, "h", 1, read=lambda h, p: None, settle=0)
    cal2.run()
    assert cal2.error == "no_meter" and ("tune",) not in c2.log
    # Abbrechen: sofort Empfang
    c3 = FakeClient()
    cal3 = levelcal.Calibration(c3, "h", 1, read=lambda h, p: 0.0, settle=0)
    cal3.cancel.set()
    cal3.run()
    assert cal3.error == "cancelled" and ("abort",) in c3.log and cal3.result is None


def test_read_meter():
    class R:
        def __init__(self, code, out):
            self.returncode, self.stdout = code, out
    assert levelcal.read_meter("h", 1, run=lambda *a, **k: R(0, "0.850000\n")) == 0.85
    assert levelcal.read_meter("h", 1, run=lambda *a, **k: R(1, "")) is None
    assert levelcal.read_meter("h", 1, run=lambda *a, **k: R(0, "Feature not available")) is None
