"""0.8.15.1: Baken und Cluster-Spots auf der Karte (je einzeln schaltbar) und bessere
Rufzeichen-Erkennung für QRZ.com (Präfix aus der Länderdatei, z. B. VP2E/W1AW)."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham.weblookup import base_call, qrz_url

HERE = Path(__file__).parent


def test_base_call_with_prefix_check():
    prefixes = {"VP2E", "DL", "EA8", "KH6", "W", "K"}
    is_pfx = prefixes.__contains__
    assert base_call("VP2E/W1AW", is_pfx) == "W1AW"          # gleich lang: Präfix erkannt
    assert base_call("W1AW/VP2E", is_pfx) == "W1AW"
    assert base_call("VP2E/W1AW") == "VP2E"                  # ohne Länderdatei wie bisher
    assert base_call("EA8/DL1ABC/P", is_pfx) == "DL1ABC"
    assert qrz_url("VP2E/W1AW", is_pfx) == "https://www.qrz.com/db/W1AW"
    # Sind alle Teile Präfixe, bleibt es bei der Länge (nichts wird verworfen)
    assert base_call("KH6/W", is_pfx) == "KH6"


SCRIPT = r'''
import json, queue, sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QMenu
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod
cfg = cfgmod.load(); cfg.update(rig_enabled=False, wsjtx_enabled=False, map_background="simple")
cfgmod.save(cfg)
from gogoham.db import DEFAULT_META, LogDB
from gogoham.dxcluster import Spot
from gogoham.contests import Qso
from gogoham import beacons as bc
from gogoham.gui import main_window
main_window.MainWindow._welcome = lambda self: None
main_window.MainWindow._ask_scp = lambda self, *a, **k: None
main_window.MainWindow._start_daily_update = lambda self, wait=10.0: None
menus = []
class FakeMenu(QMenu):
    def exec(self, *a):
        menus.append([x.text() for x in self.actions() if not x.isSeparator()])
main_window.QMenu = FakeMenu
# kein Netz: Cluster und RBN als Attrappen
class FakeFeed:
    def __init__(self, name):
        self.name, self.stopped = name, False
        self.connected, self.host, self.error, self.ever_connected = True, "test", "", True
        self.spots = queue.Queue()
    def start(self): pass
    def stop(self): self.stopped = True
made = []
def fake(name):
    def make(self, *a):
        f = FakeFeed(name); made.append(f); return f
    return make
main_window.MainWindow._make_cluster = fake("cluster")
main_window.MainWindow._make_rbn = fake("rbn")
def running():
    return [w.cluster is not None, w.rbn is not None]

p = Path(sys.argv[2]) / "x.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="cqww-ssb", mycall="DO2GGH",
                                my_grid="JO50")); db.close()
w = main_window.MainWindow(); w.open_log(str(p)); w.show()
for _ in range(3): app.processEvents()
w.cb_band.setCurrentText("20")
out = {}

# 1) Alle Fenster zu, nichts läuft. Karte auf -> Cluster und RBN starten von selbst
#    (Nutzerwunsch 0.8.20.1: Karte unabhängig von Bandmap und Bakenanzeige)
out["start"] = running()
w.toggle_map(True)
for _ in range(3): app.processEvents()
c = w.map_view.canvas
out["map_open"] = running() + [w.bm_dock.isHidden(), w.bc_dock.isHidden()]
# Bandmap auf und wieder zu: Cluster bleibt für die Karte
w.toggle_cluster(True); w.toggle_cluster(False)
out["bm_closed"] = running()
# Häkchen „Cluster-Spots“ aus -> Cluster aus; wieder an -> wieder an
w.map_view.checks["map_spots"].setChecked(False)
out["spots_unchecked"] = running() + [w.cfg.get("map_spots")]
w.map_view.checks["map_spots"].setChecked(True)
# Karte zu -> beides aus
w.toggle_map(False)
out["map_closed"] = running()
w.toggle_map(True)
out["reopened"] = running()
# RBN nicht erreichbar -> aus, Hinweis, kein dauerndes Neuversuchen
w.rbn.connected, w.rbn.error, w.rbn.ever_connected = False, "offline", False
w._beacon_tick(); w._beacon_tick()
w._map_marks_tick(force=True)
out["offline"] = running() + [c.notes]
w.toggle_map(False); w.toggle_map(True)              # neu geöffnet -> neuer Versuch
out["retry"] = running()

# 2) Daten: Board von Hand füllen, Spots in den Speicher
board = w.beacon_board
now = time.time()
board.add(Spot("4U1UN", 14100000, "DK0XX-#", "15 dB", "1200"), now)
w.spots.add(Spot("JA1ABC", 14205000, "DL1XX-#", "", "1200", received=now))
w.spots.add(Spot("JA2XYZ", 14210000, "DL1XX-#", "", "1200", received=now))
w.spots.add(Spot("K3LR", 14250000, "DL1XX-#", "", "1200", received=now))
w.spots.add(Spot("DL2AA", 7150000, "DL1XX-#", "", "1200", received=now))   # anderes Band
w._map_marks_tick(force=True)
un = next(m for m in c.beacon_marks if m["call"] == "4U1UN")
oh = next(m for m in c.beacon_marks if m["call"] == "OH2B")
ja = next(m for m in c.spot_marks if any(s.call == "JA1ABC" for s in m["spots"]))
out["on"] = {"notes": c.notes, "b": len(c.beacon_marks), "un": un["color"], "oh": oh["color"],
             "s": sorted(sorted(s.call for s in m["spots"]) for m in c.spot_marks),
             "ja_label": ja["label"], "ja_color": ja["color"]}

# 3) Klick auf den Japan-Punkt (zwei Spots) -> Auswahlmenü; K3LR (einer) -> einstellen
c.resize(900, 500); app.processEvents()
def click(m, button):
    pt = c.mark_px(m)
    for typ in (QMouseEvent.Type.MouseButtonPress, QMouseEvent.Type.MouseButtonRelease):
        ev = QMouseEvent(typ, QPointF(pt), QPointF(c.mapToGlobal(pt.toPoint())), button,
                         button if typ == QMouseEvent.Type.MouseButtonPress
                         else Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(c, ev)
click(ja, Qt.MouseButton.LeftButton)
k = next(m for m in c.spot_marks if m["spots"][0].call == "K3LR")
click(k, Qt.MouseButton.LeftButton)
out["picked_call"] = w.ed_call.text()
click(ja, Qt.MouseButton.RightButton)
out["tip"] = c.tip_at(c.mark_px(un).x(), c.mark_px(un).y())

# 4) Häkchen „Cluster-Spots“ aus -> keine Spots mehr, Einstellung gespeichert
w.map_view.checks["map_spots"].setChecked(False)
w._map_marks_tick(force=True)
out["spots_off"] = {"s": len(c.spot_marks), "cfg": w.cfg.get("map_spots")}
out["menus"] = menus
w.close()
print("RESULT " + json.dumps(out))
'''


def test_map_marks(tmp_path):
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
    # Karte braucht keine anderen Fenster
    assert o["start"] == [False, False]
    assert o["map_open"] == [True, True, True, True]       # läuft, Bandmap/Baken-Fenster zu
    assert o["bm_closed"] == [True, True]
    assert o["spots_unchecked"] == [False, True, False]
    assert o["map_closed"] == [False, False]
    assert o["reopened"] == [True, True]
    assert o["offline"][:2] == [True, False]
    assert any("nicht erreichbar" in n for n in o["offline"][2])
    assert o["retry"] == [True, True]
    # an: 18 Baken, 4U1UN gehört (gut, 15 dB) grün, OH2B nicht gehört grau
    on = o["on"]
    assert on["b"] == 18
    assert on["un"] == "#1b8a3a" and on["oh"] == "#9e9e9e"
    assert "Baken: 20 m" in on["notes"]
    # nur 20-m-Spots, die beiden JA am selben Ort zusammengefasst
    assert on["s"] == [["JA1ABC", "JA2XYZ"], ["K3LR"]]
    assert on["ja_label"].endswith("+1")
    assert on["ja_color"] == "#1b8a3a"                    # neuer Multi auf 20 m
    # Klick: JA-Punkt (2 Spots) -> Auswahl, K3LR -> eingestellt; Rechtsklick -> QRZ je Call
    assert [t.split()[0] for t in o["menus"][0]] == ["JA1ABC", "JA2XYZ"]
    assert o["picked_call"] == "K3LR"
    assert o["menus"][1] == ["JA1ABC bei QRZ.com ansehen", "JA2XYZ bei QRZ.com ansehen"]
    assert "4U1UN" in o["tip"] and "15 dB" in o["tip"]
    # Häkchen aus
    assert o["spots_off"] == {"s": 0, "cfg": False}
