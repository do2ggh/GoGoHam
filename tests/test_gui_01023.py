"""0.10.23: AGCW QRP und Frankencontest 2 m im echten Hauptfenster (offscreen) – eigener
Austausch mit Klasse bzw. DOK + Locator, QSO loggen, Punkte und Cabrillo-Zeile."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).parent

SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod
cfg = cfgmod.load(); cfg.update(rig_enabled=False, wsjtx_enabled=False, rules_auto_update=False)
cfgmod.save(cfg)
from gogoham.db import DEFAULT_META, LogDB
from gogoham.export import cabrillo_qso_line
from gogoham.gui import main_window
main_window.MainWindow._welcome = lambda self: None
main_window.MainWindow._ask_scp = lambda self, *a, **k: None
main_window.MainWindow._start_daily_update = lambda self, wait=10.0: None

out = {}
for cid, meta, band, freq, call, ex in (
        ("agcw-qrp", {"my_member": "2583", "my_class": "QRP"}, "40", 7020000, "DK5XY",
         "012 QRP 1537"),
        ("franken-k", {"my_dok": "B37", "my_grid": "JN59ME"}, "2", 144300000, "DK5XY",
         "B26 JN59NO")):
    p = Path(sys.argv[2]) / f"{cid}.ggh"
    db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest=cid, mycall="DL1ABC", **meta)); db.close()
    w = main_window.MainWindow(); w.open_log(str(p)); w.show()
    for _ in range(3): app.processEvents()
    w._check_band_offer()                          # Ein-Band-Contest: stellt selbst auf 2 m
    if w.current_band() != band:
        w.cb_band.setCurrentText(band)             # sonst wie per Maus wählen
    out.setdefault("bands", []).append(w.current_band())
    w.ed_call.setText(call); w.update_check()
    w.ed_exch.setText(ex); w.exch_auto = False; w.update_check()
    n = len(w.qsos)
    w.log_qso()
    for _ in range(3): app.processEvents()
    q = w.qsos[-1] if len(w.qsos) > n else None
    out[cid] = {"logged": q is not None, "exch_s": q.exch_s if q else "",
                "score": w.scorer.score, "band": q.band if q else "",
                "line": cabrillo_qso_line(w.contest, q, "DL1ABC") if q else ""}
    w.close()
print("RESULT " + json.dumps(out))
'''


def test_new_contests_in_main_window(tmp_path):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    (cfg / "gogoham").mkdir(parents=True)
    (data / "gogoham").mkdir(parents=True)
    logs.mkdir()
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(logs), str(HERE / "cty_sample.dat")],
                       capture_output=True, text=True, env=env, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["bands"] == ["40", "2"]
    a = o["agcw-qrp"]
    assert a["logged"] and a["exch_s"] == "001 QRP 2583"
    assert a["score"] == 3 * 1                     # QRP–QRP 3 Punkte, 1 Mitglied
    assert "001 QRP 2583" in a["line"] and "012 QRP 1537" in a["line"]
    f = o["franken-k"]
    assert f["logged"] and f["exch_s"] == "B37 JN59ME"
    assert f["score"] > 0 and "B26 JN59NO" in f["line"]
