"""0.10.22: Live-Stick ohne Datenteil erkennen und deutlich warnen; Einrichtungs-Skript da."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham import livestick

HERE = Path(__file__).parent
STICK = HERE.parent / "stick" / "config" / "includes.chroot_before_packages" / "etc" / \
    "initramfs-tools"


def test_persistent():
    mit = ("/dev/sda4 /run/live/persistence/sda4 ext4 rw,noatime 0 0\n"
           "overlay / overlay rw 0 0\n")
    ohne = "overlay / overlay rw 0 0\ntmpfs /run tmpfs rw 0 0\n"
    assert livestick.persistent(mit) and not livestick.persistent(ohne)


def test_initramfs_script_present_and_ordered():
    s = STICK / "scripts" / "init-premount" / "gogoham-einrichten"
    assert s.is_file() and s.stat().st_mode & 0o111            # sonst überspringt initramfs es
    text = s.read_text()
    assert "*/usb*" in text and "GGH-DATEN" in text and "DATEN_START=16777216" in text
    assert subprocess.run(["sh", "-n", str(s)]).returncode == 0
    reset = (STICK / "scripts" / "init-premount" / "gogoham-reset").read_text()
    assert 'PREREQ="udev gogoham-einrichten"' in reset           # erst einrichten
    hook = (STICK / "hooks" / "gogoham-live-boot").read_text()
    for b in ("sfdisk", "mke2fs", "mkfs.exfat", "blkid", "debugfs"):
        assert b in hook
    # echte Werkzeuge im eigenen Ordner – im Startsystem sind die gleichnamigen oft BusyBox
    assert "copy_exec \"$b\" \"/usr/lib/gogoham/${b##*/}\"" in hook   # voller Zielpfad
    assert "G=/usr/lib/gogoham" in text
    for bare in ("\nsfdisk ", "\nmkfs.ext4 ", "\nmke2fs ", " | sfdisk "):
        assert bare not in text                                  # nie ohne vollen Pfad
    assert "FORTSETZEN=1" in text                                # abgebrochene Einrichtung


SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
from gogoham import livestick
livestick.is_live = lambda marker=None: True
livestick.persistent = lambda mounts=None: sys.argv[2] == "1"
warned = []
QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2]))
from gogoham.gui.main_window import MainWindow
for n in ("_welcome", "_first_welcome", "_ask_scp", "_stick_hint", "_stick_timezone"):
    setattr(MainWindow, n, lambda self, *a, **k: None)
MainWindow._start_daily_update = lambda self, wait=10.0: None
w = MainWindow()
import time
end = time.monotonic() + 1.5
while time.monotonic() < end:
    app.processEvents(); time.sleep(0.02)
print("RESULT " + json.dumps({"warned": warned, "status": w.sb.currentMessage()}, ensure_ascii=False))
'''


def test_warning_without_data_part(tmp_path):
    out = {}
    for flag in ("0", "1"):
        env = {"QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin",
               "XDG_CONFIG_HOME": str(tmp_path / "x"), "XDG_DATA_HOME": str(tmp_path / "d")}
        r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent), flag],
                           capture_output=True, text=True, env=env, timeout=60)
        lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
        assert lines, r.stderr[-3000:]
        out[flag] = json.loads(lines[-1][7:])
    assert out["0"]["warned"] and "speichert nichts" in out["0"]["warned"][0]
    assert "DD-Modus" in out["0"]["warned"][0]
    assert "speichert nichts" in out["0"]["status"]
    assert out["1"]["warned"] == []
