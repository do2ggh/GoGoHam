"""0.8.23.5: Andere Programme laufen weiter – rigctld/rotctld-Dienste werden beim Löschen eines
Profils (nach Rückfrage) und beim Deinstallieren ans System übergeben statt entfernt."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham import rigservice, uninstall

HERE = Path(__file__).parent


class R:
    returncode, stdout, stderr = 0, "", ""


def _unit(d: Path, name: str, cmd: str) -> None:
    (d / name).write_text("# Von GoGoHam angelegt – wird beim Speichern …\n# Bitte in GoGoHam ändern\n"
                          "[Unit]\nDescription=GoGoHam rigctld IC-7300 (Port 4532)\n\n"
                          f"[Service]\nExecStart={cmd}\nRestart=always\n")


def test_handover_keeps_command_and_renames(tmp_path):
    calls = []
    _unit(tmp_path, "gogoham-rigctld-4532.service", "/usr/bin/rigctld -m 3073 -t 4532")
    assert rigservice.handover("gogoham-rigctld-4532.service",
                               run=lambda c, t=30: calls.append(c) or R(),
                               directory=str(tmp_path)) == []
    assert not (tmp_path / "gogoham-rigctld-4532.service").exists()
    text = (tmp_path / "rigctld-4532.service").read_text()
    assert "ExecStart=/usr/bin/rigctld -m 3073 -t 4532" in text
    assert "Description=rigctld IC-7300 (Port 4532)" in text and "übergeben" in text
    assert ["systemctl", "--user", "disable", "--now", "gogoham-rigctld-4532.service"] in calls
    assert ["systemctl", "--user", "enable", "--now", "rigctld-4532.service"] in calls
    # GoGoHams sync räumt den übergebenen Dienst nicht weg
    rigservice.sync([], run=lambda c, t=30: R(), directory=str(tmp_path))
    assert (tmp_path / "rigctld-4532.service").exists()


def _fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    for f in (".local/share/gogoham/app/gogoham/__init__.py", ".local/bin/gogoham",
              ".local/share/applications/gogoham.desktop",
              ".local/share/icons/hicolor/64x64/apps/gogoham.png",
              ".local/share/gogoham/uninstall.sh", ".local/share/gogoham/cty.dat",
              ".config/gogoham/config.json", ".local/state/gogoham/gogoham.log",
              "GoGoHam/cqww-cw-2026-DO2GGH.ggh", "GoGoHam/Sicherungen/x.ggh",
              ".local/share/applications/andere.desktop"):
        p = home / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    return home


def test_uninstall_keeps_services_and_logs(tmp_path, monkeypatch):
    for k in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(k, raising=False)
    home = _fake_home(tmp_path)
    units = tmp_path / "units"
    units.mkdir()
    _unit(units, "gogoham-rigctld-4532.service", "/usr/bin/rigctld -m 3073 -t 4532")
    _unit(units, "gogoham-rotctld-4540.service", "/usr/bin/rotctld -m 603 -t 4540")
    res = uninstall.run_uninstall(False, run=lambda c, t=30: R(), home=str(home),
                                  unit_directory=str(units))
    assert res["services"] == ["rigctld-4532.service", "rotctld-4540.service"]
    assert sorted(os.listdir(units)) == ["rigctld-4532.service", "rotctld-4540.service"]
    assert not (home / ".local/share/gogoham/app").exists()
    assert not (home / ".local/bin/gogoham").exists()
    assert not (home / ".local/share/applications/gogoham.desktop").exists()
    assert not (home / ".local/share/icons/hicolor/64x64/apps/gogoham.png").exists()
    assert (home / ".local/share/applications/andere.desktop").exists()
    assert (home / ".config/gogoham/config.json").exists()          # ohne --purge: bleibt
    assert (home / "GoGoHam/cqww-cw-2026-DO2GGH.ggh").exists()


def test_uninstall_purge_never_deletes_logs(tmp_path, monkeypatch):
    for k in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(k, raising=False)
    home = _fake_home(tmp_path)
    units = tmp_path / "units"
    units.mkdir()
    uninstall.run_uninstall(True, run=lambda c, t=30: R(), home=str(home),
                            unit_directory=str(units))
    assert not (home / ".config/gogoham").exists()
    assert not (home / ".local/share/gogoham").exists()
    assert not (home / ".local/state/gogoham").exists()
    assert (home / "GoGoHam/cqww-cw-2026-DO2GGH.ggh").exists()
    assert (home / "GoGoHam/Sicherungen/x.ggh").exists()


def test_uninstall_main_asks_first(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(uninstall, "run_uninstall", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("darf nicht laufen")))
    assert uninstall.main([], answer=lambda q: "") == 1               # Standard: Nein
    assert "Abgebrochen" in capsys.readouterr().out


SCRIPT = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
units = sys.argv[2]
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
from gogoham import rigservice, rotor
rigservice.available = lambda run=None: True
rigservice.unit_dir = lambda: units
handed = []
rigservice.handover = lambda unit, run=None, directory=None: handed.append(unit) or []
from gogoham.gui import dialogs
answers, asked = [], []
def question(parent, title, text, *a, **k):
    asked.append(title); return answers.pop(0)
QMessageBox.question = staticmethod(question)
from gogoham.gui.dialogs import RigDialog
for n in ("gogoham-rigctld-4532.service", "gogoham-rotctld-4540.service"):
    open(os.path.join(units, n), "w").write("x")
def make():
    return {"rig_enabled": True, "rig_autostart": True, "rig_host": "127.0.0.1",
            "rig_port": 4532, "rig_model": 0, "rig_device": "", "rig_baud": 0,
            "rig_extra": "", "rig_profile": 0,
            "rig_profiles": [{"slot": 0, "name": "IC-7300", "model": 3073, "device": "/dev/x",
                              "baud": 115200, "extra": "", "start": False, "service": True,
                              "port": 4532}]}
out = {}
# Profil löschen, Ja -> übergeben
cfg = make(); d = RigDialog(cfg)
answers[:] = [QMessageBox.StandardButton.Yes]
d._delete_profile(); out["del_yes"] = [d.apply(), list(handed), len(asked), cfg["rig_profiles"]]
# Profil löschen, Nein -> nicht übergeben (sync räumt später weg)
handed.clear(); asked.clear()
cfg = make(); d = RigDialog(cfg)
answers[:] = [QMessageBox.StandardButton.No]
d._delete_profile(); d.apply(); out["del_no"] = [list(handed), len(asked)]
# Profil bleibt dauerhaft -> keine Frage
handed.clear(); asked.clear()
cfg = make(); d = RigDialog(cfg); d.apply(); out["keep"] = [list(handed), len(asked)]
# Rotor ausschalten -> fragen, Ja -> übergeben
from gogoham.gui.rotor_page import RotorPage
handed.clear(); asked.clear()
rotor.handover = lambda port, run=None, directory=None: handed.append(port) or []
cfg = {"rotor": {"enabled": True, "model": 1, "mode": "service", "port": 4540}}
pg = RotorPage(cfg, test_fn=lambda p: None, service_ok=True)
pg.enabled.setChecked(False)
answers[:] = [QMessageBox.StandardButton.Yes]
out["rot"] = [pg.apply(), list(handed), len(asked)]
print("OUT" + json.dumps(out))
'''


def test_dialogs_offer_handover(tmp_path):
    units = tmp_path / "units"
    units.mkdir()
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HOME=str(tmp_path),
               XDG_CONFIG_HOME=str(tmp_path / "cfg"), XDG_DATA_HOME=str(tmp_path / "data"))
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(units)], capture_output=True, text=True, env=env, timeout=60)
    lines = [ln[3:] for ln in r.stdout.splitlines() if ln.startswith("OUT")]
    assert lines, r.stderr[-2000:]
    o = json.loads(lines[-1])
    assert o["del_yes"] == [True, ["gogoham-rigctld-4532.service"], 1, []]
    assert o["del_no"] == [[], 1]
    assert o["keep"] == [[], 0]
    assert o["rot"] == [True, [4540], 1]
