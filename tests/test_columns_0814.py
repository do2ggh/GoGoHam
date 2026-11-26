"""0.8.14: Super Check Partial und Bandmap mehrspaltig, wenn das Fenster breit genug ist.
SCP zeilenweise (wie beim Lesen), Bandmap in Zeitungsspalten (Frequenz von oben nach unten).
Läuft mit echtem Qt (offscreen)."""

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
from gogoham import config as cfgmod, scp as scpmod
cfg = cfgmod.load(); cfg.update(rig_enabled=False, wsjtx_enabled=False)
cfgmod.save(cfg)
from gogoham.db import DEFAULT_META, LogDB
from gogoham.dxcluster import Spot
from gogoham.gui import main_window
from gogoham.gui.bandmap import BandmapView
main_window.MainWindow._welcome = lambda self: None
main_window.MainWindow._ask_scp = lambda self, *a, **k: None
main_window.MainWindow._start_daily_update = lambda self, wait=10.0: None
out = {}
# --- Bandmap
calls = ["DL1ABC", "SP5AAA", "G4ABC", "F5XYZ", "OK1XYZ", "HA8ZZ", "S51A", "OE1XX", "PA3ABC",
         "ON4ZZ", "EA1AB", "I2ABC", "LZ1AA", "YO3AB", "UA3AA", "9A1AA", "OH2AA", "SM5AA"]
now = time.time()
rows = [(Spot(c, 14130000 + i * 1500, "DL9GTB-#", "", "1200", received=now), "new")
        for i, c in enumerate(calls)]
for width in (380, 820):
    v = BandmapView(12); v.resize(width, 250); v.show(); app.processEvents()
    v.show_rows(rows, 14150000, "20", now); app.processEvents()
    r0, r1, rl = (v.visualItemRect(v.item(i)) for i in (0, 1, v.count() - 1))
    out[str(width)] = [v.columns(), r1.y() > r0.y(), rl.x() > r0.x(),
                       r0.width() >= v.fontMetrics().horizontalAdvance(v.item(0).text())]
# --- Super Check Partial
w = main_window.MainWindow()
p = Path(sys.argv[2]) / "x.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="cqww-ssb", mycall="DO2GGH")); db.close()
w.open_log(str(p)); w.show()
w.scp = scpmod.ScpDB(["DL1AAH", "DL1AAO", "DL1ABR", "DL1AG", "DL1AH", "DL1AIW", "DL1AKL",
                      "DL1ABCDE/P"])
w.scp_dock.setFloating(True); w.scp_dock.resize(600, 200); app.processEvents()
w.ed_call.setText("DL1A"); w.update_check(); app.processEvents()
lw = w.partial
r = [lw.visualItemRect(lw.item(i)) for i in range(lw.count())]
fits = all(r[i].width() >= lw.fontMetrics().horizontalAdvance(lw.item(i).text())
           for i in range(lw.count()))
out["scp"] = [lw.count(), r[1].y() == r[0].y() and r[1].x() > r[0].x(), fits]
# --- Logtabelle: eine Spalte nach der anderen breiter ziehen (wie der Nutzer)
w.scp_dock.setFloating(False); w.resize(1300, 760); app.processEvents()
for _ in range(3): app.processEvents()
t, hdr = w.tbl, w.tbl.horizontalHeader()
order = w._visible_order()
avail = t.viewport().width()
def widths(): return {k: t.columnWidth(main_window.COL[k]) for k in order}
start = widths()
steps = []
for k in order[:-1]:
    before = widths()
    hdr.resizeSection(main_window.COL[k], before[k] + 40)      # wie Ziehen mit der Maus
    app.processEvents()
    after = widths()
    changed = [x for x in order if after[x] != before[x]]
    steps.append(len(changed) <= 2)
mins_ok = all(t.columnWidth(main_window.COL[k]) >= w._min_col_width(k) for k in order)
for _ in range(3): app.processEvents()
out["drag"] = [all(steps), mins_ok, abs(sum(widths().values()) - avail) <= 2]
# Fenster schmaler: alles passt noch hinein, kein Titel abgeschnitten
w.resize(1100, 760)
for _ in range(5): app.processEvents()
out["narrow"] = [all(t.columnWidth(main_window.COL[k]) >= w._min_col_width(k) for k in order),
                 abs(sum(widths().values()) - t.viewport().width()) <= 2
                 or sum(widths().values()) > t.viewport().width()]
w.close()
print("RESULT " + json.dumps(out))
'''


def test_multi_column_lists(tmp_path):
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
    # schmal: eine Spalte, alles untereinander
    assert o["380"][0] is False and o["380"][1] and not o["380"][2]
    # breit: Zeitungsspalten – erst nach unten, der letzte Eintrag steht weiter rechts
    assert o["820"] == [True, True, True, True]
    # SCP: nebeneinander (zeilenweise), kein Rufzeichen abgeschnitten
    assert o["scp"] == [8, True, True]
    # Logtabelle: Ziehen ändert nur die gezogene Spalte und ihren Nachbarn, nie unter den Titel
    assert o["drag"] == [True, True, True]
    assert o["narrow"] == [True, True]
