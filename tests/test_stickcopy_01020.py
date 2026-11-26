"""0.10.20: Neuen Stick erstellen – Auswahl (nur USB, nie der laufende Stick), Größe, Meldungen."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham import stickcopy as sc

HERE = Path(__file__).parent
GB = 1000 ** 3


def test_sizes_like_aufteilung_sh():
    assert not sc.fits(14 * GB) and sc.fits(int(15.5 * GB)) and sc.fits(16 * GB)
    assert sc.exchange_size(16 * GB) == 2 * sc.GIB                 # mindestens 2 GiB
    assert sc.exchange_size(32 * GB) == 5579 * 1024 * 1024          # wie tausch_groesse
    assert sc.exchange_size(256 * GB) == 16 * sc.GIB                # höchstens 16 GiB
    assert sc.data_size(16 * GB) >= sc.DATA_MIN


LSBLK = {"blockdevices": [
    {"name": "nvme0n1", "path": "/dev/nvme0n1", "size": 512 * GB, "type": "disk", "tran": "nvme",
     "model": "Samsung", "children": [{"name": "nvme0n1p1", "label": "Windows",
                                       "mountpoints": [None]}]},
    {"name": "sda", "path": "/dev/sda", "size": 32 * GB, "type": "disk", "tran": "usb",
     "vendor": "SanDisk", "model": "SanDisk Ultra", "serial": "AAA", "mountpoints": [None],
     "children": [{"name": "sda1", "label": "GOGOHAM_LIVE", "mountpoints": ["/run/live/medium"]},
                  {"name": "sda4", "label": "GGH-DATEN", "mountpoints": ["/run/live/persistence/sda4"]}]},
    {"name": "sdb", "path": "/dev/sdb", "size": 16 * GB, "type": "disk", "tran": "usb",
     "vendor": "Intenso ", "model": "Rainbow Line", "serial": "BBB", "mountpoints": [None],
     "children": [{"name": "sdb1", "label": "INTENSO", "mountpoints": ["/media/gogoham/INTENSO"]}]},
    {"name": "sdc", "path": "/dev/sdc", "size": 8 * GB, "type": "disk", "tran": "usb",
     "vendor": "Noname", "model": "", "serial": "CCC", "mountpoints": [None]},
    {"name": "sdd", "path": "/dev/sdd", "size": 0, "type": "disk", "tran": "usb",
     "model": "Card Reader", "mountpoints": [None]},
    {"name": "sde", "path": "/dev/sde", "size": 500 * GB, "type": "disk", "tran": "usb",
     "model": "Ext HDD", "serial": "EEE", "mountpoints": [None],
     "children": [{"name": "sde1", "mountpoints": ["/"]}]},
    {"name": "sdf", "path": "/dev/sdf", "size": 64 * GB, "type": "disk", "tran": "usb",
     "model": "Old stick", "serial": "FFF", "mountpoints": [None],
     "children": [{"name": "sdf4", "label": "GGH-DATEN", "mountpoints": [None]}]},
]}


def fake_run(args):
    if args[0] == "findmnt":
        return 0, "/dev/sda1\n"
    if args[:3] == ["lsblk", "-nro", "PKNAME"]:
        return 0, "sda\n"
    if args[:2] == ["lsblk", "-J"]:
        return 0, json.dumps(LSBLK)
    return 1, ""


def test_only_usb_never_the_running_stick():
    assert sc.boot_disk(fake_run) == "/dev/sda"
    # live-boot über /dev/loop0 (so in der VM): dahinter der ganze Stick
    loop = lambda a: (0, "/dev/loop0\n") if a[0] == "findmnt" else (0, "\n")     # noqa: E731
    assert sc.boot_disk(loop, backing=lambda d: "/dev/sda" if d == "/dev/loop0" else "") \
        == "/dev/sda"
    assert sc.boot_disk(loop, backing=lambda d: "") == ""
    sticks = sc.usb_sticks(fake_run)
    assert [s.path for s in sticks] == ["/dev/sdb", "/dev/sdc", "/dev/sdf"]
    b, c, f = sticks
    assert b.fits and not c.fits and f.gogoham and b.name == "Intenso Rainbow Line"
    assert "enthält: INTENSO" in sc.describe(b) and "/dev/sdb" in sc.describe(b)
    assert "zu klein – mindestens 16 GB" in sc.describe(c)
    assert "ohne erkennbaren Inhalt" in sc.describe(c)
    assert "schon ein GoGoHam-Stick" in sc.describe(f)
    # unbekannter Start-Stick: trotzdem nie etwas mit /run/live eingehängtem
    assert "/dev/sda" not in [s.path for s in sc.usb_sticks(fake_run, boot="")]
    assert sc.usb_sticks(lambda a: (1, "")) == []


def test_command(tmp_path):
    helper = tmp_path / "gogoham-stick-kopie"
    marker = tmp_path / "livestick.json"
    marker.write_text(json.dumps({"copy": str(helper)}))
    w = {"pkexec": "/usr/bin/pkexec"}.get
    assert sc.command("/dev/sdb", marker, w) is None                 # Hilfsprogramm fehlt
    helper.write_text("#!/bin/sh\n")
    assert sc.command("/dev/sdb", marker, w) == ["pkexec", str(helper), "/dev/sdb"]
    assert sc.command("/dev/sdb; rm -rf /", marker, w) is None
    assert sc.command("sdb", marker, w) is None
    assert sc.command("/dev/sdb", marker, {}.get) is None            # kein pkexec
    assert sc.command("/dev/sdb", tmp_path / "fehlt.json", w) is None   # kein Stick


def test_parse():
    assert sc.parse("SCHRITT schreiben") == ("step", "schreiben")
    assert sc.parse("FORTSCHRITT 4194304 2694834176") == ("progress", 4194304, 2694834176)
    assert sc.parse("TEMPO 31 88") == ("speed", 31, 88)
    assert sc.parse("FEHLER zu_klein 8000000000") == ("error", "zu_klein", "8000000000")
    assert sc.parse("irgendwas") is None and sc.parse("") is None
    assert sc.parse("FORTSCHRITT x y") is None
    assert "16 GB" in sc.error_text("zu_klein") and sc.is_slow(10, 50) and sc.is_slow(30, 5)
    assert not sc.is_slow(30, 50)


SCRIPT = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import stickcopy as sc
from gogoham.gui.stick_copy import StickCopyDialog
GB = 1000 ** 3
state = {"sticks": [sc.Stick("/dev/sdb", 16 * GB, "Rainbow Line", "Intenso", "BBB", ["INTENSO"]),
                    sc.Stick("/dev/sdc", 8 * GB, "", "Noname", "CCC")],
         "script": ""}
StickCopyDialog.scan = staticmethod(lambda: list(state["sticks"]))
StickCopyDialog.make_command = staticmethod(lambda dev: ["/bin/sh", "-c", state["script"], "x", dev])
d = StickCopyDialog()
told, answers = [], {"v": False}
d.tell = lambda t, x, warn=False: told.append([x, warn])
d.ask = lambda s: answers["v"]
def wait(cond, sec=10):
    end = time.monotonic() + sec
    while not cond() and time.monotonic() < end:
        app.processEvents(); time.sleep(0.01)
out = {"rows": d.list.count(), "auto": d.list.currentRow(), "go": d.btn_go.isEnabled()}
d.list.setCurrentRow(1); out["small_go"] = d.btn_go.isEnabled()
d.list.setCurrentRow(0)
d.start(); out["no_answer"] = d.running()
answers["v"] = True
state["script"] = ('echo SCHRITT aushaengen; echo SCHRITT schreiben; echo "FORTSCHRITT 50 100"; '
                   'sleep 0.3; echo SCHRITT pruefen; echo SCHRITT aufteilen; echo SCHRITT einrichten; '
                   'echo "TEMPO 9 40"; echo SCHRITT fertig; echo "$1" > "%s"')
state["script"] = state["script"] % (sys.argv[2] + "/ziel.txt")
d.start(); app.processEvents()
out["busy"] = [d.running(), d.btn_close.isEnabled(), d.list.isEnabled()]
d.reject(); out["stays_open"] = d.running()
wait(lambda: not d.running())
out["ok"] = told[-1]
out["target"] = open(sys.argv[2] + "/ziel.txt").read().strip()
out["bar"] = d.bar.value()
# Fehler vom Hilfsprogramm
state["script"] = 'echo SCHRITT schreiben; echo "FEHLER pruefen"; exit 1'
d.list.setCurrentRow(0); d.start(); wait(lambda: not d.running())
out["fail"] = told[-1]
# Stick zwischendurch abgezogen
d.list.setCurrentRow(0); state["sticks"] = []
d.start()
out["gone"] = told[-1]
out["empty"] = [d.list.count(), not d.lbl_none.isHidden()]
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def test_dialog(tmp_path):
    env = {"QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin",
           "XDG_CONFIG_HOME": str(tmp_path / "xdg"), "XDG_STATE_HOME": str(tmp_path / "st")}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(tmp_path)], capture_output=True, text=True, env=env, timeout=60)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["rows"] == 2 and o["auto"] == 0 and o["go"]          # einziger passender: gewählt
    assert not o["small_go"]                                       # 8 GB: nicht wählbar
    assert not o["no_answer"]                                      # Abbrechen: nichts passiert
    assert o["busy"] == [True, False, False] and o["stays_open"]
    text, warn = o["ok"]
    assert not warn and "fertig und kann jetzt abgezogen werden" in text
    assert "9 MB/s" in text and "langsam" in text
    assert o["target"] == "/dev/sdb" and o["bar"] == 1000
    assert o["fail"][1] and "Prüfung hat Fehler gefunden" in o["fail"][0]
    assert o["gone"][1] and "nicht mehr da" in o["gone"][0]
    assert o["empty"] == [0, True]


MENU = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import livestick
live = sys.argv[2] == "1"
livestick.is_live = lambda marker=None: live
livestick.poweroff_command = lambda which=None: ["true"]
livestick.persistent = lambda mounts=None: True
from gogoham.gui.main_window import MainWindow
from gogoham.gui.stick_page import StickPage
MainWindow._welcome = lambda self: None
MainWindow._ask_scp = lambda self, *a, **k: None
MainWindow._stick_hint = lambda self: None
w = MainWindow()
asked = []
from PySide6.QtWidgets import QMessageBox
QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2]), QMessageBox.StandardButton.No)[1])
w.act_quit.trigger(); app.processEvents()
page = StickPage({}, actions={"clock_set": lambda: None, "stick_poweroff": lambda: None})
print("RESULT " + json.dumps({"text": w.act_quit.text(), "asked": asked, "visible": w.isVisible(),
                              "off_button": hasattr(page, "btn_off")}, ensure_ascii=False))
'''


def test_quit_menu_on_stick_only(tmp_path):
    out = {}
    for live in ("1", "0"):
        env = {"QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin",
               "XDG_CONFIG_HOME": str(tmp_path / "xdg"), "XDG_DATA_HOME": str(tmp_path / "d")}
        r = subprocess.run([sys.executable, "-c", textwrap.dedent(MENU), str(HERE.parent), live],
                           capture_output=True, text=True, env=env, timeout=60)
        lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
        assert lines, r.stderr[-3000:]
        out[live] = json.loads(lines[-1][7:])
    assert out["1"]["text"] == "Beenden und herunterfahren …"
    assert "herunterfahren" in out["1"]["asked"][0]               # erst fragen (hier: Nein)
    assert out["0"]["text"] == "Beenden" and out["0"]["asked"] == []
    assert not out["1"]["off_button"]                              # Knopf unter USB-Stick weg
