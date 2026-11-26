"""0.10.39: Design „Nightshift“ hell/dunkel – Verläufe, hellere Signalfarben auf Nachtblau,
markierte Zeile mit Türkis-Balken, Dupe/Multi-Farbe bleibt auch markiert erhalten."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
ROOT = HERE.parent

SCRIPT = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem
app = QApplication([])
from gogoham.contests.base import Qso
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui import bandmap, main_window, statusbar, theme
from gogoham.gui.main_window import MainWindow
MainWindow._welcome = lambda self: None
MainWindow._ask_scp = lambda self, *a, **k: None
w = MainWindow()
p = Path(sys.argv[2]) / "wpx.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="wpx-cw", mycall="DO2GGH"))
for i, call in enumerate(("DL1ABC", "OK1XYZ", "DL1ABC")):
    db.add(Qso(time=f"2026-03-28 10:0{i}:00", call=call, band="20", mode="CW",
               freq=14_025_000, rst_s="599", exch_s=str(i + 1), rst_r="599", exch_r="5"))
db.close()
w.open_log(str(p))
w.resize(1200, 760); w.show(); app.processEvents()
out = {}
for mode in ("nightshift-dark", "nightshift", "dark"):
    w.set_theme(mode)
    w.tbl.selectRow(w.tbl.rowCount() - 1); app.processEvents()
    idx = w.tbl.model().index(w.tbl.rowCount() - 1, 1)
    opt = QStyleOptionViewItem(); w.tbl.itemDelegate().initStyleOption(opt, idx)
    out[mode] = {"sheet": app.styleSheet(), "dark": theme.is_dark(),
                 "red": main_window.RED, "bm_orange": bandmap.ORANGE,
                 "sb_error": statusbar.COLORS["error"], "on": theme.on_signal(),
                 "sel_text": opt.palette.highlightedText().color().name(),
                 "item_fg": idx.data(9).color().name() if idx.data(9) is not None else ""}
    if len(sys.argv) > 3:
        w.grab().save(str(Path(sys.argv[3]) / f"{mode}.png"))
print(json.dumps(out))
'''


def test_nightshift(tmp_path):
    pytest.importorskip("PySide6")
    data = tmp_path / "data" / "gogoham"
    data.mkdir(parents=True)
    shutil.copy(HERE / "cty_sample.dat", data / "cty.dat")
    env = {"QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path),
           "XDG_CONFIG_HOME": str(tmp_path / "cfg"), "XDG_DATA_HOME": str(tmp_path / "data"),
           "PATH": "/usr/bin:/bin"}
    (tmp_path / "cfg" / "gogoham").mkdir(parents=True)
    (tmp_path / "cfg" / "gogoham" / "config.json").write_text(json.dumps(
        {"rig_enabled": False, "wsjtx_enabled": False, "language": "de"}))
    args = [sys.executable, "-c", SCRIPT, str(ROOT), str(tmp_path)]
    if os.environ.get("GGH_SHOTS"):                      # Bildschirmfotos zum Ansehen
        args.append(os.environ["GGH_SHOTS"])
    r = subprocess.run(args, capture_output=True, text=True, env=env, timeout=90)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    nd, nl, dk = out["nightshift-dark"], out["nightshift"], out["dark"]
    assert nd["dark"] and not nl["dark"]
    for o in (nd, nl):
        assert "qlineargradient" in o["sheet"] and "#FFB547" in o["sheet"]
        assert "#3FE0D0" in o["sheet"]
    # hellere Signalfarben nur im dunklen Nightshift, Orange abgedunkelt im hellen
    assert nd["red"] == "#FF6B7F" and nd["sb_error"] == "#FF6B7F" and nd["bm_orange"] == "#FFB020"
    assert nd["on"] != "white" and nl["on"] == "white"
    assert nl["red"] == "#c62828" and nl["bm_orange"] == "#B45F00"
    assert dk["red"] == "#c62828" and dk["bm_orange"] == "#c77f00" and dk["sheet"] == ""
    # Dupe in der markierten Zeile: eigene Schriftfarbe bleibt (nur Nightshift)
    assert nd["item_fg"] == "#ff6b7f" and nd["sel_text"] == "#ff6b7f"
    assert nl["item_fg"] == "#c62828" and nl["sel_text"] == "#c62828"
    assert dk["sel_text"] != dk["item_fg"]
