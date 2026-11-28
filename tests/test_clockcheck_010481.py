"""0.10.48.1: Grenze Sekunden/Minuten erst nach dem Runden (vorher „120,0 Sekunden“ bei 119,95…119,99 s;
ließ test_gps_in_main_window auf GitHub ab und zu scheitern)."""
from gogoham import clockcheck


def test_grenze_sekunden_minuten():
    assert "119,9 Sekunden nach" in clockcheck.describe(119.94)
    for off in (119.95, 119.97, 119.999, 120.0, 121.0):
        assert "2 Minuten nach" in clockcheck.describe(off), off
    assert "2 Minuten vor" in clockcheck.describe(-119.97)
    assert "5,0 Sekunden vor" in clockcheck.describe(-5.0)
