"""0.8.14.1: Zusatzfenster – offen = Funktion an, zu = aus (egal ob Menü Ansicht,
Rechtsklick-Menü der Fenster oder X). Beim Start nur, was in Einstellungen → Darstellung
angehakt ist (Standard: keins). Echtes Qt (offscreen); Cluster und RBN sind Platzhalter."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).parent

SCRIPT = r'''
import json, queue, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui import main_window
M = main_window.MainWindow
M._welcome = lambda self: None
M._ask_scp = lambda self, *a, **k: None
M._start_daily_update = lambda self, wait=10.0: None

class Fake:
    def __init__(self, name):
        self.name, self.spots = name, queue.Queue()
        self.connected = self.ever_connected = True
        self.error, self.host, self.started, self.stopped = "", name, False, False
    def start(self): self.started = True
    def stop(self): self.stopped = True
made = []
def fake(name):
    def make(self, *a):
        f = Fake(name); made.append(f); return f
    return make
M._make_cluster = fake("cluster")
M._make_rbn = fake("rbn")

contest, flags = sys.argv[4], json.loads(sys.argv[5])
p = Path(sys.argv[2]) / (contest + ".ggh")
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest=contest, mycall="DO2GGH",
                                my_grid="JN59ME")); db.close()
cfg = cfgmod.load()
cfg.update(rig_enabled=False, wsjtx_enabled=False, last_log=str(p), **flags)
cfgmod.save(cfg)

def wait(n=3):
    for _ in range(n):
        app.processEvents()
w = M()
wait()
state = lambda: {"scp": not w.scp_dock.isHidden(), "bm": not w.bm_dock.isHidden(),
                 "bc": not w.bc_dock.isHidden(), "cluster": w.cluster is not None,
                 "rbn": w.rbn is not None, "act_bm": w.act_bandmap.isChecked(),
                 "act_bc": w.act_beacons.isChecked()}
out = {"start": state()}
view = [a.menu() for a in w.menuBar().actions() if a.text() == "&Fenster"][0]
out["view"] = [x.text() for x in view.actions() if not x.isSeparator()]
w.show(); wait()
if contest == "cqww-ssb" and not flags:
    # Rechtsklick-Menü der Fenster = toggleViewAction von Qt
    w.bm_dock.toggleViewAction().trigger(); wait()
    out["ctx_bm_on"] = state()
    w.bm_dock.toggleViewAction().trigger(); wait()
    out["ctx_bm_off"] = [state(), made[-1].stopped]
    w.bc_dock.toggleViewAction().trigger(); wait()
    out["ctx_bc_on"] = [state(), made[-1].name, made[-1].started]
    w.bc_dock.close(); wait()                              # X
    out["x_bc_off"] = [state(), made[-1].stopped]
    w.scp_dock.toggleViewAction().trigger(); wait()
    out["ctx_scp"] = state()["scp"]
    # Menü Ansicht
    w.act_bandmap.trigger(); wait()
    out["menu_bm"] = state()
    w.bm_dock.close(); wait()
    out["x_bm"] = state()
    # Minimieren schaltet nichts ab
    w.toggle_beacons(True); wait()
    w.showMinimized(); wait()
    out["minimized"] = state()
    w.showNormal(); wait()
    # Reiter „Darstellung“ speichert die Häkchen
    from gogoham.gui.dialogs import DisplayPage
    page = DisplayPage(w.cfg)
    out["page_default"] = {k: cb.isChecked() for k, cb in page.open_docks.items()}
    page.open_docks["open_bandmap"].setChecked(True)
    page.apply()
    out["page_saved"] = [w.cfg.get("open_scp"), w.cfg.get("open_bandmap"), w.cfg.get("open_beacons")]
w.close()
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def _run(tmp_path, contest, flags):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    for d in (data / "gogoham", cfg / "gogoham", logs):
        d.mkdir(parents=True, exist_ok=True)
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(logs), str(HERE / "cty_sample.dat"), contest, json.dumps(flags)],
                       capture_output=True, text=True, env=env, timeout=90)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    return json.loads(lines[-1][7:])


def test_default_nothing_open_and_window_is_switch(tmp_path):
    o = _run(tmp_path, "cqww-ssb", {})
    off = {"scp": False, "bm": False, "bc": False, "cluster": False, "rbn": False,
           "act_bm": False, "act_bc": False}
    assert o["start"] == off                                  # Standard: kein Fenster offen
    assert "DX-Cluster verbinden" not in o["view"]            # nur noch „Bandmap“
    assert "Bandmap" in o["view"] and "Baken (NCDXF/IARU)" in o["view"]
    assert o["ctx_bm_on"] == dict(off, bm=True, cluster=True, act_bm=True)
    assert o["ctx_bm_off"] == [off, True]
    assert o["ctx_bc_on"] == [dict(off, bc=True, rbn=True, act_bc=True), "rbn", True]
    assert o["x_bc_off"] == [off, True]
    assert o["ctx_scp"] is True
    assert o["menu_bm"] == dict(off, scp=True, bm=True, cluster=True, act_bm=True)
    assert o["x_bm"] == dict(off, scp=True)
    assert o["minimized"] == dict(off, scp=True, bc=True, rbn=True, act_bc=True)
    assert o["page_default"] == {"open_scp": False, "open_bandmap": False, "open_beacons": False,
                                 "open_map": False, "open_rotor": False,
                                 "open_propagation": False, "open_station": False}
    assert o["page_saved"] == [False, True, False]


def test_startup_opens_ticked_windows(tmp_path):
    o = _run(tmp_path, "cqww-ssb", {"open_scp": True, "open_bandmap": True, "open_beacons": True})
    assert o["start"] == {"scp": True, "bm": True, "bc": True, "cluster": True, "rbn": True,
                          "act_bm": True, "act_bc": True}


def test_startup_beacons_skipped_without_beacon_bands(tmp_path):
    o = _run(tmp_path, "cq160-ssb", {"open_beacons": True})
    assert o["start"]["bc"] is False and o["start"]["rbn"] is False
