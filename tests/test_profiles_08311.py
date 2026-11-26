"""0.8.31.1: Start mit dem zuletzt benutzten Funkgerät-Profil; Suche bei der Contest-Auswahl."""

import json
import subprocess
import sys
import textwrap

from gogoham import rigprofiles

from test_practice_0828 import HERE

PROFS = [{"name": "IC-7300", "model": 3073, "device": "/dev/a", "baud": 0, "host": "127.0.0.1",
          "port": 4532, "start": False, "slot": 1},
         {"name": "FT-891", "model": 1036, "device": "/dev/b", "baud": 38400,
          "host": "127.0.0.1", "port": 4533, "start": False, "slot": 2}]


def test_ensure_profiles_applies_the_saved_profile():
    cfg = {"rig_profiles": [dict(p) for p in PROFS], "rig_profile": 1,
           "rig_model": 3073, "rig_port": 4532, "rig_device": "/dev/a"}   # Felder vom anderen
    rigprofiles.ensure_profiles(cfg)
    assert cfg["rig_profile"] == 1 and cfg["rig_model"] == 1036 and cfg["rig_port"] == 4533
    assert cfg["rig_device"] == "/dev/b" and rigprofiles.active(cfg)["name"] == "FT-891"


SCRIPT = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod
from gogoham.rig import RigState
from gogoham.gui import main_window, dialogs
made = []
class FakeRig:
    def __init__(self, host, port, poll=0.4, listen_only=False):
        self.port = port
        made.append(port)
    def start(self): pass
    def stop(self): pass
    def join(self, t=None): pass
    def snapshot(self): return RigState(connected=True, freq=14030000, mode="CW")
    def submit(self, *a): pass
main_window.RigWorker = FakeRig
M = main_window.MainWindow
M._welcome = lambda self: None
M._ask_scp = lambda self, *a, **k: None
M._ask_flags = lambda self, *a, **k: None
M._start_daily_update = lambda self, wait=10.0: None
cfg = cfgmod.load()
cfg.update(rig_enabled=True, rig_autostart=False, wsjtx_enabled=False,
           rig_profiles=json.loads(sys.argv[4]), rig_profile=1, rig_model=3073, rig_port=4532)
cfgmod.save(cfg)
out = {}
w = M(); w.show(); app.processEvents()
out["first"] = [w.cfg["rig_profile"], w.cfg["rig_port"], made[-1] if made else None,
                [a.text() for a in w.menu_profiles.actions() if a.isChecked()]]
w.switch_profile(0); app.processEvents()
out["saved"] = cfgmod.load()["rig_profile"]
w.close()
made.clear()
w = M(); w.show(); app.processEvents()
out["second"] = [w.cfg["rig_profile"], w.cfg["rig_port"], made[-1] if made else None]
w.close()
d = dialogs.LogSettingsDialog({"contest": "cqww-cw"}, None, new_log=True)
lst = d.contest_list
ids = lambda: [lst.item(i).data(256) for i in range(lst.count())]
out["start"] = [lst.count(), d.contest.currentData(), lst.currentItem().data(256),
                d.count_label.text()]
d.search.setText("i")
n_i = lst.count()
d.search.setText("iar")
out["iar"] = [n_i, ids(), d.contest.currentData()]
d.search.setText("iaru h")
out["iaruh"] = [ids(), d.contest.currentData(), d.count_label.text()]
d.search.setText("xyzq")
out["none"] = [lst.count(), d.search_hint.text(), d.contest.currentData()]
d.search.setText("cq ww dx")
lst.setCurrentRow(1)
out["cqww"] = [ids(), d.contest.currentData()]
d.search.clear()
out["all"] = [lst.count(), d.contest.currentData()]
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def test_main_window_starts_with_last_profile_and_log_search(tmp_path):
    data, cfg = tmp_path / "data", tmp_path / "cfg"
    for d in (data / "gogoham", cfg / "gogoham"):
        d.mkdir(parents=True, exist_ok=True)
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent), "",
                        str(HERE / "cty_sample.dat"), json.dumps(PROFS)],
                       capture_output=True, text=True, env=env, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    from gogoham.contests import CONTESTS
    assert o["first"] == [1, 4533, 4533, ["3: FT-891"]]      # zuletzt benutzt: FT-891
    assert o["saved"] == 0                                    # Umschalten wird gemerkt
    assert o["second"] == [0, 4532, 4532]
    n = len(CONTESTS)
    # 0.10.21: das freie Log steht nur nach Freischalten (Entwicklung) in der Liste
    assert o["start"] == [n - 1, "cqww-cw", "cqww-cw", f"{n - 1} Contests in GoGoHam"]
    assert n > o["iar"][0] > len(o["iar"][1]) >= 3                # mit jedem Buchstaben weniger
    from gogoham.contests import CONTESTS as C
    assert all("IARU" in C[i].name for i in o["iar"][1]) and o["iar"][2] == o["iar"][1][0]
    assert o["iaruh"] == [["iaru-hf"], "iaru-hf", f"1 von {n - 1} Contests"]
    assert o["none"] == [0, "kein Contest gefunden", "iaru-hf"]    # letzte Wahl bleibt
    assert sorted(o["cqww"][0]) == ["cqww-cw", "cqww-rtty", "cqww-ssb"] \
        and o["cqww"][1] == o["cqww"][0][1]
    assert o["all"][0] == n - 1


def test_log_window_has_min_width_and_room_for_two_rule_lines():
    """0.8.32.1: beim Verkleinern rutschten Contest-Anzahl und Regelstand übereinander."""
    from gogoham.gui import dialogs
    assert dialogs.MIN_LOG_WIDTH >= 600
