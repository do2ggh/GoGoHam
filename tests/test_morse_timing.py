import pytest

from gogoham import morse_timing as mt


def test_reihenfolge_ggh():
    kinds = "".join(e.kind for e in mt.schedule())
    assert kinds == "--." "--." "...."


def test_einheit_14_wpm():
    assert mt.unit_ms() == pytest.approx(1200 / 14)


def test_dauer_durchlauf_und_schleife():
    u = mt.unit_ms()
    # G = 3+1+3+1+1 = 9, zweimal 3 Buchstabenpause, H = 7 → 31 Einheiten
    assert mt.pass_ms() == pytest.approx(31 * u)          # ≈ 2,66 s
    assert mt.cycle_ms() == pytest.approx(38 * u)         # ≈ 3,26 s
    assert mt.cycle_ms() > 3000


def test_elemente_nacheinander_strich_dreimal_punkt():
    s = mt.schedule()
    u = mt.unit_ms()
    assert s[0].duration == pytest.approx(3 * u)
    assert s[2].duration == pytest.approx(u)
    for a, b in zip(s, s[1:]):
        assert b.start > a.start + a.duration - 1e-9     # nie gleichzeitig


def test_fuellung():
    u = mt.unit_ms()
    assert mt.fractions(0)[0] == 0
    assert mt.fractions(1.5 * u)[0] == pytest.approx(0.5)  # Strich halb
    assert mt.fractions(1.5 * u)[1] == 0
    fertig = mt.fractions(mt.pass_ms() + 1)
    assert all(f == 1 for f in fertig)
    # neue Runde beginnt wieder leer
    assert mt.fractions(mt.cycle_ms() + 1)[0] < 0.05


def test_mindestens_ein_durchlauf():
    assert mt.close_time(500) == pytest.approx(mt.cycle_ms())
    assert mt.close_time(mt.cycle_ms()) == pytest.approx(mt.cycle_ms())


def test_laufender_durchlauf_wird_beendet():
    c, p = mt.cycle_ms(), mt.pass_ms()
    done = c + 1000                     # mitten im zweiten Durchlauf
    assert mt.close_time(done) == pytest.approx(c + p)


def test_in_wortpause_sofort():
    c, p = mt.cycle_ms(), mt.pass_ms()
    done = 2 * c + p + 100              # dritter Durchlauf schon fertig
    assert mt.close_time(done) == pytest.approx(done)
