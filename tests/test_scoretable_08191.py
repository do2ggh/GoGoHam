"""0.8.19.1: Punktetabelle – Spaltenköpfe werden nicht mehr abgeschnitten.

In den Franken-Designs war „Länder“ an beiden Enden abgeschnitten (fetter roter Kopf mit
Innenabstand, aber stur gleich breite Spalten). Jetzt: Breite nach Inhalt, Rest verteilt."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham.gui.scoretable import column_widths

HERE = Path(__file__).parent


def test_column_widths_distributes_rest():
    assert column_widths([40, 50, 60], 160) == [44, 53, 63]
    assert sum(column_widths([40, 50, 60], 161)) == 161


def test_column_widths_never_below_need():
    assert column_widths([100, 120], 150) == [100, 120]
    assert column_widths([], 300) == []


SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham.gui import theme
from gogoham.gui.scoretable import ScoreTable
out = {}
for mode in ("light", "dark", "franken", "franken-dark"):
    theme.apply(mode)
    cols = ["Band", "QSOs", "Pkt", "Zonen", "Länder", "Dupes"]
    t = ScoreTable(2, len(cols))
    t.setHorizontalHeaderLabels(cols)
    t.setFixedWidth(max(300, QFontMetrics(QFont()).averageCharWidth() * 36))
    t.show()
    for _ in range(3): app.processEvents()
    hh = t.horizontalHeader()
    out[mode] = {"fits": all(hh.sectionSize(i) >= hh.sectionSizeFromContents(i).width()
                             for i in range(len(cols))),
                 "total": sum(hh.sectionSize(i) for i in range(len(cols))),
                 "viewport": t.viewport().width()}
print(json.dumps(out))
'''


def test_headers_fit_in_all_themes(tmp_path):
    env = {"QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path),
           "XDG_CONFIG_HOME": str(tmp_path / "cfg"), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent)],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    res = json.loads(r.stdout.strip().splitlines()[-1])
    for mode, v in res.items():
        assert v["fits"], (mode, v)
        assert v["total"] <= v["viewport"], (mode, v)     # kein Rollbalken nötig
