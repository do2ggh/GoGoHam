"""0.9.4: Hinweis auf eine neue GoGoHam-Version."""

import json
import sys
from datetime import date
from pathlib import Path

import pytest

from gogoham import __version__
from gogoham import versioncheck as vc

HERE = Path(__file__).parent


def tags(tmp_path, names):
    f = tmp_path / "tags.json"
    f.write_text(json.dumps([{"name": n} for n in names]))
    return f.as_uri()


def test_parse_and_compare():
    assert vc.parse("v0.9.4") == (0, 9, 4) and vc.parse("0.10") == (0, 10)
    assert vc.parse("beta") is None and vc.parse("v1.0-rc1") is None
    assert vc.is_newer("0.10", "0.9.4") and vc.is_newer("v0.9.4.1", "0.9.4")
    assert not vc.is_newer("0.9.4", "0.9.4") and not vc.is_newer("0.9.3", "0.9.4")


def test_latest_picks_highest_tag(tmp_path):
    url = tags(tmp_path, ["v0.9.2", "v0.10", "v0.9.10", "test", "v0.9.4"])
    assert vc.latest(url=url) == "0.10"
    assert vc.latest(url=tags(tmp_path, [])) == ""
    with pytest.raises(OSError):
        vc.latest(url=(tmp_path / "fehlt.json").as_uri())


def test_install_kind_and_text(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    assert vc.install_kind("/usr/lib/python3.13/site-packages/gogoham/versioncheck.py") == "package"
    assert vc.install_kind("/home/x/.local/share/gogoham/app/gogoham/versioncheck.py") == "script"
    assert vc.install_kind("/home/x/Projekte/gogoham/gogoham/versioncheck.py") == "source"
    monkeypatch.setenv("APPIMAGE", "/tmp/GoGoHam.AppImage")
    assert vc.install_kind("/usr/lib/x.py") == "appimage"
    assert "Systemupdate" in vc.hint_text("9.9", "package")
    assert "ein Klick" in vc.hint_text("9.9", "script")          # 0.10.47: per Knopf
    assert "install.sh" in vc.hint_text("9.9", "source")
    assert vc.hint_text("9.9", "package").startswith("GoGoHam 9.9 ist erschienen")


def test_due_and_once_per_version():
    assert vc.is_due({}, date(2026, 11, 8))
    assert not vc.is_due({"version_check_last": "2026-11-08"}, date(2026, 11, 8))
    assert not vc.is_due({"version_check": False}, date(2026, 11, 8))
    assert vc.should_show({}, "99.0")
    assert not vc.should_show({"version_hint_shown": "99.0"}, "99.0")
    assert not vc.should_show({}, __version__) and not vc.should_show({}, "")


def test_checker_thread(tmp_path):
    t = vc.VersionChecker(url=tags(tmp_path, ["v99.0"]))
    t.start()
    t.join(5)
    assert t.version == "99.0" and not t.error
    t = vc.VersionChecker(url=(tmp_path / "fehlt.json").as_uri())
    t.start()
    t.join(5)
    assert t.error and t.version == ""


def test_main_window_shows_hint_once(tmp_path, monkeypatch):
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
    from gogoham.gui.main_window import MainWindow
    w = MainWindow()

    class Done:
        version, error = "99.0", ""

        def is_alive(self):
            return False
    try:
        new_log(w, fake_qt, tmp_path, "cqww-ssb")
        w.vcheck = Done()
        w._finish_version_check()
        assert w.sb.currentMessage().startswith("GoGoHam 99.0 ist erschienen")
        assert w.cfg["version_hint_shown"] == "99.0" and w.cfg["version_check_last"]
        w.sb.showMessage("")
        w.vcheck = Done()
        w._finish_version_check()                       # gleiche Version: nicht noch einmal
        assert w.sb.currentMessage() == ""
        # Contest läuft gerade: kein Hinweis, auch nicht als „gezeigt“ merken
        w.cfg["version_hint_shown"] = ""
        monkeypatch.setattr(w, "_contest_running_now", lambda: True)
        w.vcheck = Done()
        w._finish_version_check()
        assert w.sb.currentMessage() == "" and w.cfg["version_hint_shown"] == ""
        # kein Internet: nichts merken, morgen wieder
        w.cfg["version_check_last"] = ""
        bad = Done()
        bad.error = "offline"
        w.vcheck = bad
        w._finish_version_check()
        assert w.cfg["version_check_last"] == ""
    finally:
        w.closeEvent(fake_qt.Stub())
