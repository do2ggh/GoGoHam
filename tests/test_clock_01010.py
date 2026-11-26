"""0.10.10: Zeitzone aus dem Locator (Live-Stick), ruhiger Uhrzeit-Hinweis, chrony-Abfrage."""
import json

from gogoham import livestick as ls
from gogoham import tzfind

ZONES = [(52.5, 13.3667, "Europe/Berlin"), (50.0833, 14.4333, "Europe/Prague"),
         (51.5083, -0.125, "Europe/London"), (40.7142, -74.0064, "America/New_York")]


def test_parse_coords():
    assert tzfind.parse_coords("+5230+01322") == (52.5, 13 + 22 / 60)
    lat, lon = tzfind.parse_coords("+404251-0740023")
    assert round(lat, 3) == 40.714 and round(lon, 3) == -74.006


def test_suggest_only_when_time_differs():
    # Nürnberg: am nächsten liegt Prag – gleiche Uhrzeit wie Berlin → nichts ändern
    assert tzfind.suggest("JN59me", "Europe/Berlin", ZONES) is None
    assert tzfind.suggest("JN59me", "Etc/UTC", ZONES) == "Europe/Prague"
    assert tzfind.suggest("IO91wm", "Europe/Berlin", ZONES) == "Europe/London"
    assert tzfind.suggest("FN31pr", "Europe/Berlin", ZONES) == "America/New_York"
    assert tzfind.suggest("", "Europe/Berlin", ZONES) is None
    assert tzfind.suggest("XYZ", "Europe/Berlin", ZONES) is None
    assert tzfind.same_time("Europe/Berlin", "Europe/Paris", 2026)
    assert not tzfind.same_time("Europe/Berlin", "Europe/London", 2026)


def test_real_table_if_present():
    zones = tzfind.load()
    if zones:                                   # jedes Linux mit tzdata
        assert tzfind.suggest("IO91wm", "Europe/Berlin") == "Europe/London"


def test_current_zone(tmp_path):
    (tmp_path / "timezone").write_text("Europe/London\n")
    assert tzfind.current_zone(str(tmp_path)) == "Europe/London"
    (tmp_path / "timezone").unlink()
    (tmp_path / "localtime").symlink_to("/usr/share/zoneinfo/Europe/Vienna")
    assert tzfind.current_zone(str(tmp_path)) == "Europe/Vienna"


def test_timezone_command(tmp_path):
    helper = tmp_path / "gogoham-stick-zeitzone"
    helper.write_text("#!/bin/sh\n")
    m = tmp_path / "livestick.json"
    m.write_text(json.dumps({"timezone": str(helper)}))
    which = lambda n: "/usr/bin/" + n                        # noqa: E731
    assert ls.timezone_command("Europe/London", m, which) == ["pkexec", str(helper), "Europe/London"]
    assert ls.timezone_command("../etc/passwd", m, which) is None
    assert ls.timezone_command("Europe/London; rm", m, which) is None
    m.write_text("{}")
    assert ls.timezone_command("Europe/London", m, which) is None      # älterer Stick


def test_clock_synced_chrony():
    class R:
        def __init__(self, out, code=0):
            self.stdout, self.returncode = out, code

    def run(args, **k):
        if args[0] == "chronyc":
            return R("Reference ID    : C0A80001 (x)\nLeap status     : Normal\n")
        raise AssertionError("timedatectl darf nicht gefragt werden")
    assert ls.clock_synced(run=run) is True

    def run2(args, **k):
        if args[0] == "chronyc":
            return R("Reference ID    : 00000000 ()\nLeap status     : Not synchronised\n")
        return R("yes\n")
    assert ls.clock_synced(run=run2) is False
