"""0.10.46.1: Hilfe → „Nach neuer Version suchen …“ lief auf einen fehlenden Import (livestick)
und tat nichts. Außerdem: aufgeräumter Code bleibt weg."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = r"""
import sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
from gogoham import livestick
from gogoham.gui import main_window as mw
shown = []
QMessageBox.information = staticmethod(lambda *a, **k: shown.append(("info", a[2])))
QMessageBox.warning = staticmethod(lambda *a, **k: shown.append(("warn", a[2])))
mw.vcheckmod.latest = lambda: "0.0.1"
saved = []
mw.cfgmod.save = lambda cfg: saved.append(1)

class Fake:
    cfg = {}
live = sys.argv[2] == "live"
livestick.is_live = lambda: live
if live:
    import gogoham.gui.stick_update as su
    class Dlg:
        restart_wanted = False
        def __init__(self, parent): shown.append(("stick", ""))
        def exec(self): return 0
    su.StickUpdateDialog = Dlg
mw.MainWindow.check_version_now(Fake())
print("RESULT", shown)
"""


def _run(mode):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT), mode], capture_output=True,
                       text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT")][-1]


def test_version_check_menu_works_on_pc():
    out = _run("pc")
    assert "('info'" in out and "neueste Version" in out


def test_version_check_menu_on_stick_opens_update_dialog():
    assert "('stick'" in _run("live")


def test_removed_code_stays_gone():
    from gogoham import db, handybridge
    from gogoham.contests import base
    assert not hasattr(db, "export_meta_json") and not hasattr(handybridge, "is_bridge_pty")
    assert not hasattr(base, "ExchangeField")
    # am Quelltext prüfen: andere Tests setzen manche Namen als Ersatz auf die Klasse
    src = (ROOT / "gogoham" / "gui" / "main_window.py").read_text(encoding="utf-8")
    for name in ("_ask_station", "_ask_cty", "_ask_flags", "_ask_scp", "wsjtx_settings",
                 "callbook_settings", "macro_settings", "livescore_settings"):
        assert f"def {name}(" not in src, name


def test_runtime_dir_fallback_is_private(tmp_path, monkeypatch):
    """Ohne XDG_RUNTIME_DIR: eigener Ordner unter /tmp nur, wenn er uns gehört und zu ist."""
    import pytest
    from gogoham import icomlan
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    base = tmp_path / f"gogoham-{os.getuid()}"
    d = icomlan.runtime_dir(str(tmp_path))                 # neu: wird mit 0700 angelegt
    assert d == base / "gogoham" and (base.stat().st_mode & 0o777) == 0o700
    base.chmod(0o755)                                       # für andere offen: verweigern
    with pytest.raises(OSError):
        icomlan.runtime_dir(str(tmp_path))
    base.chmod(0o700)
    other = tmp_path / "fremd"
    other.mkdir()
    (base / "gogoham").rmdir()
    base.rmdir()
    base.symlink_to(other)                                  # untergeschobener Verweis
    with pytest.raises(OSError):
        icomlan.runtime_dir(str(tmp_path))
