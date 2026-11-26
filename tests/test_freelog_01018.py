"""0.10.18: freies Log (kein Contest) – Bemerkung, „schon gearbeitet“, keine Dupes, ADIF."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham import practice
from gogoham.contests import (CONTESTS, FREE_ID, FreeLog, Qso, Scorer, Station, class_from_log,
                              contest_count, is_free)
from gogoham.contests.freelog import worked_text

HERE = Path(__file__).parent


def test_free_log_rules():
    assert next(iter(CONTESTS)) == FREE_ID and CONTESTS[FREE_ID] is FreeLog
    assert contest_count() == len(CONTESTS) - 1
    assert is_free(FreeLog) and not is_free(CONTESTS["cqww-cw"])
    assert not practice.can_practice(FreeLog, "CW") and not practice.can_practice(FreeLog, "SSB")
    assert {"30", "17", "12", "60", "2", "70cm"} <= set(FreeLog.bands)
    meta = {"contest": FREE_ID, "rules_json": json.dumps(FreeLog.rules)}
    assert class_from_log(meta) == (FreeLog, "")


def test_no_dupes_and_worked_before():
    c = FreeLog(None, Station(call="DO2GGH"))
    assert not c.uses_serial and c.sent_exchange(5) == "" and c.exchange_label == "Bemerkung"
    s = Scorer(c)
    q1 = Qso(id=1, time="2026-11-03 10:00:00", call="DL1ABC", band="40", mode="USB",
             exch_r="Hans, schönes Signal")
    ev = s.evaluate(q1, commit=True)
    assert ev.valid and not ev.dupe and ev.points == 0 and "Noch nie gearbeitet" in ev.info
    q2 = Qso(id=2, time="2026-11-13 09:00:00", call="DL1ABC", band="40", mode="USB")
    ev = s.evaluate(q2, commit=True)
    assert not ev.dupe and "Schon gearbeitet: 1× – zuletzt 03.11.2026 40 m USB" in ev.info
    assert s.total_qsos == 2 and s.dupes == 0 and s.score == 0
    assert worked_text([]) == "Noch nie gearbeitet"


SCRIPT = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui.main_window import MainWindow
from gogoham.gui.dialogs import ExportDialog
MainWindow._welcome = lambda self: None
MainWindow._ask_scp = lambda self, *a, **k: None
w = MainWindow()
p = Path(sys.argv[2]) / "frei.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="freies-log", mycall="DO2GGH")); db.close()
w.open_log(str(p))
w._updating = True; w.cb_mode.setCurrentText("USB"); w._updating = False
out = {"title": w.lbl_score_title.text(), "label": w.lbl_exch.text()}
def log(call, remark):
    w.ed_call.setText(call); w.update_check(); app.processEvents()
    w._exch_edited(remark); w.ed_exch.setText(remark); w.exch_auto = False
    status = w.lbl_status.text() if hasattr(w, "lbl_status") else ""
    w.log_qso(); app.processEvents()
    return status
log("DL1ABC", "Hans, schönes Signal")
w.ed_call.setText("DL1ABC"); w.update_check(); app.processEvents()
out["status2"] = [getattr(w, n).text() for n in dir(w)
                  if n.startswith("lbl_") and hasattr(getattr(w, n), "text")
                  and "gearbeitet" in getattr(getattr(w, n), "text")()]
w.ed_exch.setText("zweites QSO"); w.exch_auto = False
w.log_qso(); app.processEvents()
out["n"] = len(w.qsos)
out["remarks"] = [q.exch_r for q in w.qsos]
out["score"] = w.lbl_score.text()
d = ExportDialog(w.contest)
out["formats"] = [d.format.itemData(i) for i in range(d.format.count())]
a = Path(sys.argv[2]) / "frei.adi"
w._write_adif(str(a))
out["adif"] = a.read_text(encoding="utf-8")
w.open_log(str(p))                                    # wieder öffnen: Regeln aus dem Log
out["reopen"] = [type(w.contest).__name__, len(w.qsos)]
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def test_free_log_in_main_window(tmp_path):
    data, cfg = tmp_path / "data", tmp_path / "cfg"
    for d in (data / "gogoham", cfg / "gogoham"):
        d.mkdir(parents=True, exist_ok=True)
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(tmp_path)], capture_output=True, text=True, env=env, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["title"] == "<b>QSOs</b>" and o["label"] == "Bemerkung"
    assert any("Schon gearbeitet: 1×" in t for t in o["status2"]), o["status2"]
    assert o["n"] == 2                                     # derselbe Call zweimal – kein Dupe
    assert o["remarks"] == ["Hans, schönes Signal", "zweites QSO"]   # Groß/klein bleibt
    assert o["score"] == "2"
    assert o["formats"] == ["adif"]
    assert "<COMMENT:21>Hans, schönes Signal" in o["adif"] and "SRX_STRING" not in o["adif"]
    assert "CONTEST_ID" not in o["adif"]
    assert o["reopen"] == ["FreeLog", 2]
