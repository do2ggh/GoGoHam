"""0.10.26: HSC CW und Schwaben-Contest (KW, UKW mit FM) im echten Hauptfenster (offscreen) –
eigener Austausch mit Mitgliedsnummer bzw. DOK (+ Locator), QSO loggen, Cabrillo-Zeile."""

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
for cid, meta, band, mode, call, ex in (
        ("hsc", {"my_member": "1688"}, "40", "CW", "DK5XY", "1537"),
        ("schwaben-kw", {"my_dok": "T01"}, "80", "LSB", "DL0T", "T18"),
        ("schwaben-ukw", {"my_dok": "T01", "my_grid": "JN58AA"}, "2", "FM", "DL0T",
         "T02 JN58XX")):
    p = Path(sys.argv[2]) / f"{cid}.ggh"
    db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest=cid, mycall="DL1ABC", **meta)); db.close()
    w = main_window.MainWindow(); w.open_log(str(p)); w.show()
    for _ in range(3): app.processEvents()
    if w.current_band() != band:
        w.cb_band.setCurrentText(band)             # wie per Maus wählen
    w.cb_mode.setCurrentText(mode)
    out.setdefault("bands", []).append(w.current_band())
    w.ed_call.setText(call); w.update_check()
    w.ed_exch.setText(ex); w.exch_auto = False; w.update_check()
    n = len(w.qsos)
    w.log_qso()
    for _ in range(3): app.processEvents()
    q = w.qsos[-1] if len(w.qsos) > n else None
    out[cid] = {"logged": q is not None, "exch_s": q.exch_s if q else "",
                "score": w.scorer.score, "band": q.band if q else "", "mode": q.mode if q else "",
                "exch_r": q.exch_r if q else "",
                "line": cabrillo_qso_line(w.contest, q, "DL1ABC") if q else ""}
    w.close()
print("RESULT " + json.dumps(out))
'''


def test_hsc_and_schwaben_in_main_window(tmp_path):
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
    assert o["bands"] == ["40", "80", "2"]
    h = o["hsc"]
    assert h["logged"] and h["exch_s"] == "1688" and h["score"] == 5 * 1   # Mitglied, 1 Land
    assert "599 1688" in h["line"] and "599 1537" in h["line"]
    k = o["schwaben-kw"]
    assert k["logged"] and k["exch_s"] == "T01" and k["mode"] == "LSB"
    assert "T01" in k["line"] and "T18" in k["line"] and " PH " in k["line"]
    u = o["schwaben-ukw"]
    assert u["logged"] and u["exch_s"] == "T01 JN58AA" and u["mode"] == "FM"
    assert "T01 JN58AA" in " ".join(u["line"].split()) and "T02 JN58XX" in u["line"]
