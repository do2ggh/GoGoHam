"""0.8.19: Band-übergreifender Multi-Hinweis in der Bandmap.

Ein Spot, der auf einem anderen Band noch ein fehlender Multi wäre, bekommt die anderen Bänder
mitgeliefert (Bandmap färbt ihn dann orange mit ↕). Schon gearbeitete Bänder fallen weg.
Läuft mit echtem Qt (offscreen), Contest CQWW-SSB (Länder- und Zonen-Multi je Band)."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).parent

SCRIPT = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod
cfg = cfgmod.load(); cfg.update(rig_enabled=False, wsjtx_enabled=False); cfgmod.save(cfg)
from gogoham.db import DEFAULT_META, LogDB
from gogoham.dxcluster import Spot
from gogoham.contests import Qso
from gogoham.gui import main_window
main_window.MainWindow._welcome = lambda self: None
main_window.MainWindow._ask_scp = lambda self, *a, **k: None
main_window.MainWindow._start_daily_update = lambda self, wait=10.0: None

p = Path(sys.argv[2]) / "x.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="cqww-ssb", mycall="DO2GGH")); db.close()
w = main_window.MainWindow(); w.open_log(str(p)); w.show()
for _ in range(3): app.processEvents()

# Ein DL auf 20 m arbeiten -> Länder-Multi DL ist auf 20 m vergeben
q = Qso(time="1200", call="DL1ABC", band="20", mode="PH", freq=14250000,
        rst_s="59", exch_s="14", rst_r="59", exch_r="14")
w.scorer.evaluate(q, commit=True)

now = time.time()
out = {}
# Spot eines anderen DL auf 20 m: hier kein neuer Multi mehr, aber auf allen anderen Bändern schon
s20 = Spot("DL2XYZ", 14280000, "OK1AA-#", "", "1200", received=now)
st, other = w._spot_status(s20)
out["s20"] = [st, sorted(other)]
# Spot eines DL auf 40 m: hier neuer Multi; 20 m faellt weg (dort schon gearbeitet)
s40 = Spot("DL3AAA", 7150000, "OK1AA-#", "", "1200", received=now)
st, other = w._spot_status(s40)
out["s40"] = [st, sorted(other)]
w.close()
print("RESULT " + json.dumps(out))
'''


def test_crossband_multi_hint(tmp_path):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    (cfg / "gogoham").mkdir(parents=True)
    (data / "gogoham").mkdir(parents=True)
    logs.mkdir()
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(logs), str(HERE / "cty_sample.dat")],
                       capture_output=True, text=True, env=env, timeout=90)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    # 20 m: kein neuer Multi hier, aber auf allen fünf anderen Bändern noch gesucht
    assert o["s20"][0] == "new"
    assert o["s20"][1] == ["10", "15", "160", "40", "80"]
    # 40 m: neuer Multi hier; 20 m ist schon gearbeitet und fehlt in der Liste
    assert o["s40"][0] == "mult"
    assert o["s40"][1] == ["10", "15", "160", "80"]
