"""0.8.13: Funkwetter – NOAA-Daten lesen, Farben je Band, kein Absturz ohne Internet."""

import json

from gogoham import spaceweather as sw

SFI = json.dumps([
    {"time_tag": "2026-11-04T17:00:00", "frequency": 2800, "flux": 1.11e2,
     "reporting_schedule": "Morning", "ninety_day_mean": None},
    {"time_tag": "2026-11-03T22:00:00", "frequency": 2800, "flux": 1.01e2,
     "reporting_schedule": "Afternoon", "ninety_day_mean": None},
    {"time_tag": "2026-11-03T20:00:00", "frequency": 2800, "flux": 1.0e2,
     "reporting_schedule": "Noon", "ninety_day_mean": 1.24e2}])
K_NEW = json.dumps([
    {"time_tag": "2026-11-04T12:00:00", "Kp": 3.00, "a_running": 15, "station_count": 6},
    {"time_tag": "2026-11-04T15:00:00", "Kp": 1.00, "a_running": 4, "station_count": 6}])
K_OLD = json.dumps([["time_tag", "Kp", "a_running", "station_count"],
                    ["2026-11-04 12:00:00.000", "3.00", "15", "6"],
                    ["2026-11-04 15:00:00.000", "4.67", "39", "6"]])
DGD = """:Product: Daily Geomagnetic Data          DGD.txt
:Issued: 1830 UT 04 Nov 2026
#                Middle Latitude        High Latitude            Estimated
2026 11 02     8  2 2 2 2 2 1 2 2    14  0 2 5 5 2 0 0 0     7   1.00  2.00  3.00  2.33  1.67  1.67  1.00  0.33
2026 11 03    -1 -1-1-1-1-1-1-1-1    -1 -1-1-1-1-1-1-1-1     5   0.67  1.67  2.00  1.67  0.67  1.33  1.67  1.33
2026 11 04    -1 -1-1-1-1-1-1-1-1    -1 -1-1-1-1-1-1-1-1    10   2.33  2.67  3.33  2.33  3.00  1.00 -1.00 -1.00
"""


def test_parse_noaa_files():
    assert sw.parse_sfi(SFI) == (111, "2026-11-04 17:00")
    assert sw.parse_k(K_NEW) == (1, "2026-11-04 15:00")
    assert sw.parse_k(K_OLD) == (5, "2026-11-04 15:00")      # alte Tabellenform, 4,67 → 5
    assert sw.parse_a(DGD) == (10, "2026-11-04")
    assert sw.parse_a(DGD.replace("    10   2.33", "    -1   2.33")) == (5, "2026-11-03")
    assert sw.parse_sfi("[]") == (None, "")


def test_levels_depend_on_band():
    assert sw.sfi_level(111, "20") == sw.GOOD
    assert sw.sfi_level(111, "10") == sw.FAIR
    assert sw.sfi_level(90, "15") == sw.POOR
    assert sw.sfi_level(85, "17") == sw.FAIR
    assert sw.sfi_level(70, "20") == sw.POOR
    for band in ("40", "80", "160", "30", "2m", "70cm"):
        assert sw.sfi_level(250, band) == sw.NEUTRAL
    assert [sw.k_level(k) for k in (0, 2, 3, 4, 5, 9)] == ["good", "good", "fair", "fair",
                                                           "poor", "poor"]
    assert [sw.a_level(a) for a in (0, 9, 10, 29, 30)] == ["good", "good", "fair", "fair", "poor"]
    assert sw.k_level(None) == sw.NEUTRAL


def test_no_internet_gives_empty_result(monkeypatch):
    def boom(url, timeout):
        raise OSError("Netz ist weg")
    monkeypatch.setattr(sw, "_get", boom)
    w = sw.fetch(0.1)
    assert w.empty
    f = sw.Fetcher(0.1)
    f.start()
    f.join(5)
    assert f.result is not None and f.result.empty


def test_partial_data(monkeypatch):
    """Fällt eine der drei Quellen aus, kommen die anderen trotzdem."""
    def get(url, timeout):
        if url == sw.K_URL:
            raise OSError("weg")
        return SFI if url == sw.SFI_URL else DGD
    monkeypatch.setattr(sw, "_get", get)
    w = sw.fetch(0.1)
    assert (w.sfi, w.a, w.k) == (111, 10, None) and not w.empty
