"""0.10.24: GoGoHam auf dem Live-Stick per Knopf aktualisieren (gogoham/stickupdate.py).

Der echte Ablauf mit apt, unterschriebener Paketquelle und dpkg-deb wurde in einem
Debian-13-Container durchgespielt; hier werden die Bausteine ohne apt geprüft."""

import os
import subprocess
import sys
from pathlib import Path


from gogoham import __version__, livestick, stickupdate as su, versioncheck


def fake_update(root: Path, version: str) -> None:
    d = root / version / "gogoham"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")


# ------------------------------------------------------------ kleine Bausteine
def test_release_and_versions():
    assert su.debian_release('ID=debian\nVERSION_ID="13"\n') == "13"
    assert su.debian_release('ID=fedora\nVERSION_ID=44\n') is None
    assert su.debian_release('ID=debian\n') is None              # testing/sid ohne Nummer
    assert su.upstream("0.10.24-1.1") == "0.10.24" and su.upstream("1:0.11") == "0.11"
    assert su.newer("0.10.24", "0.10.23.9") and not su.newer("0.10.23", "0.10.23")
    assert not su.newer("kaputt", "0.10.23")


def test_candidate_from_madison():
    out = (" gogoham | 0.10.23-1.1 | https://download.opensuse.org/repositories/home:/Franz/"
           "Debian_13  Packages\n"
           " gogoham | 0.10.24-1.1 | https://download.opensuse.org/repositories/home:/Franz/"
           "Debian_13  Packages\n")
    assert su.candidate(out) == "0.10.24-1.1"
    assert su.candidate("") is None


def test_missing_depends():
    have = {"python3", "python3-numpy"}.__contains__
    assert su.missing_depends("python3 (>= 3.11), python3-numpy", have) == []
    assert su.missing_depends("python3-gi | python3, libfoo", have) == ["libfoo"]
    assert su.missing_depends("python3:any, a | b", have) == ["a | b"]


def test_sources_file(tmp_path):
    root, opts = su.prepare_apt("13", tmp_path / "apt")
    line = (root / "gogoham.list").read_text(encoding="utf-8")
    assert line.startswith("deb [signed-by=") and "home:/Franz/Debian_13/ /" in line
    assert (root / "gogoham-obs.asc").read_text().startswith("-----BEGIN PGP PUBLIC KEY BLOCK")
    assert f"Dir::State::Lists={root / 'lists'}" in opts     # nie die Listen des Systems


# ------------------------------------------------------------ Update-Ordner und Start
def test_updates_cleanup_and_choice(tmp_path):
    for v in ("0.10.20", "0.10.24", "0.10.25", "0.10.26"):
        fake_update(tmp_path, v)
    (tmp_path / "0.10.27").mkdir()                              # unvollständig: zählt nicht
    (tmp_path / ".neu-abc").mkdir()                             # abgebrochener Download
    assert su.installed_updates(tmp_path) == ["0.10.26", "0.10.25", "0.10.24", "0.10.20"]
    assert su.active_update(tmp_path, base="0.10.23") == "0.10.26"
    gone = su.cleanup(tmp_path, base="0.10.23", keep=2)
    assert sorted(gone) == ["0.10.20", "0.10.24"] and not (tmp_path / ".neu-abc").exists()
    assert su.active_update(tmp_path, base="0.10.30") is None   # neueres Abbild gewinnt
    assert su.cleanup(tmp_path, base="0.10.23") == ["0.10.25"]   # Standard: nur die neueste
    assert su.installed_updates(tmp_path) == ["0.10.26"]
    fake_update(tmp_path, "0.10.27")                           # läuft gerade 0.10.26 …
    assert su.cleanup(tmp_path, base="0.10.23", protect="0.10.26") == []   # … bleibt bis Neustart
    assert su.cleanup(tmp_path, base="0.10.23") == ["0.10.26"]
    su.remove_all(tmp_path)
    assert not tmp_path.exists()


def test_switch_only_on_stick(tmp_path, monkeypatch):
    fake_update(tmp_path, "99.0")
    monkeypatch.delenv(su.ENV_ACTIVE, raising=False)
    monkeypatch.delenv(su.ENV_OFF, raising=False)
    got = {}
    monkeypatch.setattr(livestick, "is_live", lambda *a, **k: False)
    assert not su.switch_if_newer([], tmp_path, execv=lambda *a: got.update(a=a))
    monkeypatch.setattr(livestick, "is_live", lambda *a, **k: True)
    monkeypatch.setenv("PYTHONPATH", "/anderes")
    assert su.switch_if_newer(["--x"], tmp_path, execv=lambda exe, args: got.update(args=args))
    assert got["args"] == [sys.executable, "-m", "gogoham", "--x"]
    assert os.environ[su.ENV_ACTIVE] == "99.0"
    assert os.environ["PYTHONPATH"] == f"{tmp_path / '99.0'}{os.pathsep}/anderes"
    # läuft schon die Update-Fassung: nicht noch einmal umschalten
    assert not su.switch_if_newer([], tmp_path, execv=lambda *a: 1 / 0)
    su.clean_env(root=tmp_path)
    assert su.ENV_ACTIVE not in os.environ and os.environ["PYTHONPATH"] == "/anderes"
    # „Zurück“ während die Update-Fassung läuft: sie bleibt bis zum Neustart, dann ist alles weg
    fake_update(tmp_path, "98.0")
    su.remove_all(tmp_path, protect="99.0")
    assert su.installed_updates(tmp_path) == ["99.0"] and (tmp_path / su.BACK_MARK).exists()
    assert not su.switch_if_newer([], tmp_path, execv=lambda *a: 1 / 0)
    assert not tmp_path.exists()
    fake_update(tmp_path, "99.0")
    # Notweg: GOGOHAM_NO_STICK_UPDATE=1 startet immer die Fassung aus dem Abbild
    monkeypatch.setenv(su.ENV_OFF, "1")
    assert not su.switch_if_newer([], tmp_path, execv=lambda *a: 1 / 0)


def test_update_version_really_starts(tmp_path, monkeypatch):
    """Mit dem Suchpfad aus switch_if_newer lädt Python wirklich die Update-Fassung."""
    fake_update(tmp_path, "99.0")
    env = dict(os.environ, PYTHONPATH=str(tmp_path / "99.0"))
    out = subprocess.run([sys.executable, "-c", "import gogoham; print(gogoham.__version__)"],
                         capture_output=True, text=True, env=env, cwd=tmp_path).stdout.strip()
    assert out == "99.0"


# ------------------------------------------------------------ Paketquelle (ohne apt)
class Run:
    def __init__(self, update=(0, "", ""), madison=""):
        self.update, self.madison = update, madison

    def __call__(self, cmd, **kw):
        if "update" in cmd:
            rc, o, e = self.update
            return subprocess.CompletedProcess(cmd, rc, o, e)
        if "madison" in cmd:
            return subprocess.CompletedProcess(cmd, 0, self.madison, "")
        raise AssertionError(cmd)


def test_check_messages(tmp_path):
    kw = dict(rel="13", apt_dir=tmp_path)
    r = su.check(run=Run(update=(100, "", "E: Failed to fetch … 404 Not Found")), **kw)
    assert not r.ok and "nicht erreichbar" in r.message
    r = su.check(run=Run(update=(0, "", "W: GPG error: … NO_PUBKEY 78AF9B87F520FFB8")), **kw)
    assert not r.ok and "unterschrieben" in r.message
    r = su.check(run=Run(), **kw)
    assert not r.ok and "noch keine GoGoHam-Version" in r.message
    m = " gogoham | 0.10.30-1.1 | https://x/Debian_13  Packages\n"
    r = su.check(run=Run(madison=m), **kw)
    assert r.ok and r.version == "0.10.30"
    r = su.check(rel=None, run=Run(), apt_dir=tmp_path)     # kein Debian (z. B. dieser PC)
    assert r.ok is False or su.debian_release()


def test_install_up_to_date_and_already_there(tmp_path):
    same = f" gogoham | {__version__}-1.1 | https://x/Debian_13  Packages\n"
    r = su.install(run=Run(madison=same), rel="13", apt_dir=tmp_path / "a", root=tmp_path / "u")
    assert r.ok and "schon die neueste" in r.message
    fake_update(tmp_path / "u", "99.0")
    m = " gogoham | 99.0-1.1 | https://x/Debian_13  Packages\n"
    r = su.install(run=Run(madison=m), rel="13", apt_dir=tmp_path / "a", root=tmp_path / "u")
    assert r.ok and "schon eingespielt" in r.message


# ------------------------------------------------------------ Hinweistext
def test_hint_on_stick(monkeypatch):
    monkeypatch.setattr(livestick, "is_live", lambda *a, **k: True)
    assert versioncheck.install_kind() == "stick"
    assert "ein Klick genügt" in versioncheck.hint_text("9.9")
    assert versioncheck.install_kind("/usr/lib/python3/dist-packages/gogoham/x.py") == "package"


# ------------------------------------------------------------ Fenster (echtes Qt, offscreen)
DIALOG = r"""
import os, sys, time
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
from gogoham import stickupdate as su
from gogoham.gui.stick_update import StickUpdateDialog
calls = []
def fake(progress):
    progress("Paketquelle wird abgefragt …")
    calls.append(1)
    return su.Result(ok=True, version="99.0", message="GoGoHam 99.0 ist eingespielt.")
d = StickUpdateDialog(installer=fake)
print("BACK", d.btn_back.isVisibleTo(d))
d.start()
for _ in range(200):
    app.processEvents(); time.sleep(0.01)
    if d.result is not None: break
print("MSG", d.status.text())
print("RESTART", d.btn_restart.isVisibleTo(d), d.btn_update.isVisibleTo(d))
d.btn_restart.click()
print("WANTED", d.restart_wanted)
"""


def test_dialog(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XDG_DATA_HOME=str(tmp_path / "d"),
               XDG_CONFIG_HOME=str(tmp_path / "c"), HOME=str(tmp_path))
    env.pop(su.ENV_ACTIVE, None)
    r = subprocess.run([sys.executable, "-c", DIALOG, str(Path(__file__).parent.parent)],
                       capture_output=True, text=True, env=env, timeout=60)
    out = r.stdout
    assert "BACK False" in out, r.stderr[-2000:]               # noch kein Update: kein Rückweg
    assert "MSG GoGoHam 99.0 ist eingespielt." in out
    assert "RESTART True False" in out and "WANTED True" in out
