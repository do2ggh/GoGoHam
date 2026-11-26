"""0.10.44: Fenster „Entwicklung“ per Strg+Umschalt+E im Hauptfenster, WS im Nightshift-Design."""

import base64
import json
import struct
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from gogoham import wsnightshift as ws

HERE = Path(__file__).parent
IDENT = struct.pack(">9d", 1, 0, 0, 0, 1, 0, 0, 0, 1)         # Qt-Transformation (Einheit)


def brush(style: int, rgb=(0, 0, 0)) -> bytes:
    col = struct.pack(">bHHHHH", 1, 0xFFFF, *(c * 257 for c in rgb), 0)
    return bytes([style]) + col + IDENT


def entry(name: str, on: bool, fg: bytes, bg: bytes) -> bytes:
    raw = name.encode() + b"\0"
    return struct.pack(">I", len(raw)) + raw + bytes([on]) + fg + bg


def blob() -> bytes:
    items = [entry("MyCall", True, brush(0), brush(1, (255, 102, 102))),
             entry("LotW", False, brush(1, (153, 0, 0)), brush(0)),        # nur Schrift
             entry("CQ", True, brush(0), brush(1, (102, 255, 102))),
             entry("Tx", True, brush(1, (0, 0, 255)), brush(1, (255, 255, 0)))]  # eigene Schrift
    return struct.pack(">I", len(items)) + b"".join(items)


def test_black_text():
    new, n = ws.black_text(blob())
    assert n == 2 and len(new) == len(blob())
    again, n2 = ws.black_text(new)
    assert n2 == 0 and again == new                         # zweiter Lauf ändert nichts
    with pytest.raises(ValueError):
        ws.black_text(blob()[:-3])
    with pytest.raises(ValueError):
        ws.black_text(blob() + b"x")


def test_black_brush_matches_qt():
    """Der eingesetzte schwarze Pinsel ist Byte für Byte so, wie Qt ihn selbst schreibt
    (QDataStream, Format Qt 5.15 wie in WS.ini). Eigener Prozess: andere Tests ersetzen Qt."""
    code = ("import sys\nfrom PySide6.QtCore import QByteArray, QDataStream, QIODevice\n"
            "from PySide6.QtGui import QBrush, QColor\n"
            "ba = QByteArray(); s = QDataStream(ba, QIODevice.OpenModeFlag.WriteOnly)\n"
            "s.setVersion(QDataStream.Version.Qt_5_15); s << QBrush(QColor('#000000'))\n"
            "sys.stdout.write(bytes(ba).hex())\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                       env={"QT_QPA_PLATFORM": "offscreen", "PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, r.stderr[-2000:]
    qt = bytes.fromhex(r.stdout.strip())
    assert qt == ws._BLACK + IDENT
    new, _n = ws.black_text(blob())
    assert qt in new


def make_ini(home: Path, data: bytes, crlf: bool = False) -> Path:
    ini = home / ".config" / "WS.ini"
    ini.parent.mkdir(parents=True, exist_ok=True)
    nl = "\r\n" if crlf else "\n"
    text = nl.join(["[Configuration]", "MyCall=DO2GGH",
                    f'DecodeHighlighting_v2="{base64.b64encode(data).decode()}"', "Zz=1", ""])
    ini.write_bytes(text.encode())
    return ini


@pytest.mark.parametrize("crlf", [False, True])
def test_install_and_remove(tmp_path, crlf):
    ini = make_ini(tmp_path, blob(), crlf)
    before = ini.read_bytes()
    (tmp_path / ".config" / "user-dirs.dirs").write_text('XDG_DESKTOP_DIR="$HOME/Schreibtisch"\n')
    find = lambda key: "/usr/bin/ws"
    res = ws.install(str(tmp_path), find=find, running=lambda key: False, now=0, data_dirs=[])
    assert res.ok and res.backup and res.backup.read_bytes() == before
    assert any("2 Arten" in ln for ln in res.lines)
    after = ini.read_bytes()
    assert after.count(b"\r\n") == before.count(b"\r\n")            # Zeilenenden bleiben
    assert after.replace(b"DecodeHighlighting_v2", b"").count(b"\n") == before.count(b"\n")
    assert b"MyCall=DO2GGH" in after and b"Zz=1" in after
    qss = ws.qss_path(str(tmp_path))
    assert qss.read_text().startswith("/* Nightshift dunkel")
    menu = tmp_path / ".local/share/applications/ws.desktop"        # Ersatz-Starter „WS“
    assert ws.is_installed(str(tmp_path)) and "Name=WS\n" in menu.read_text()
    assert f"Exec=/usr/bin/ws -style Fusion -stylesheet {qss}" in menu.read_text()
    assert menu.stat().st_mode & 0o111
    assert not any(p.exists() for p in ws.starter_paths(str(tmp_path)))  # kein Extra-Symbol
    assert any("kein WS-Symbol" in ln for ln in res.lines)
    # zweiter Lauf: nichts mehr zu ändern, keine neue Sicherung
    res2 = ws.install(str(tmp_path), find=find, running=lambda key: False, now=100, data_dirs=[])
    assert res2.ok and res2.backup is None and ini.read_bytes() == after
    assert any("schon schwarze" in ln for ln in res2.lines)
    res3 = ws.remove(str(tmp_path))
    assert res3.ok and not qss.exists() and not menu.exists()
    assert ini.read_bytes() == after                               # Schrift bleibt


def test_install_refuses(tmp_path):
    ini = make_ini(tmp_path, blob())
    before = ini.read_bytes()
    r = ws.install(str(tmp_path), find=lambda k: None, running=lambda k: False)
    assert not r.ok and "nicht installiert" in r.lines[0]
    r = ws.install(str(tmp_path), find=lambda k: "flatpak:x.y", running=lambda k: False)
    assert not r.ok and "Flatpak" in r.lines[0]
    r = ws.install(str(tmp_path), find=lambda k: "/usr/bin/ws", running=lambda k: True)
    assert not r.ok and "läuft" in r.lines[0]
    assert ini.read_bytes() == before and not ws.qss_path(str(tmp_path)).exists()


def test_install_odd_ini(tmp_path):
    find, run = (lambda k: "/usr/bin/ws"), (lambda k: False)
    r = ws.install(str(tmp_path), find=find, running=run)          # noch keine WS.ini
    assert r.ok and "gibt es noch nicht" in r.lines[-1]
    ini = make_ini(tmp_path, b"\0\0\0\5kaputt")
    before = ini.read_bytes()
    r = ws.install(str(tmp_path), find=find, running=run)
    assert r.ok and "nicht erkannt" in r.lines[-1] and ini.read_bytes() == before
    assert not list(ini.parent.glob("WS.ini.nightshift-*"))


def test_starter_quotes_spaces():
    t = ws.starter_text("/opt/W S/ws", Path("/home/a b/.config/ws-nightshift.qss"))
    assert 'Exec="/opt/W S/ws" -style Fusion -stylesheet "/home/a b/.config/ws-nightshift.qss"' in t
    assert ws.starts(t, "/opt/W S/ws") and ws.plain_text(t) == ws.starter_text("/opt/W S/ws")


PKG = ("[Desktop Entry]\nVersion=1.0\nName=WS\nName[de]=WS Funk\nExec=ws %f\nIcon=ws_icon\n"
       "Type=Application\n\n[Desktop Action x]\nName=X\nExec=ws --x\n")


def test_normal_starters_switched_and_restored(tmp_path):
    """0.10.47.2: kein Extra-Symbol – der normale WS-Starter wird umgestellt und zurückgestellt."""
    home = str(tmp_path)
    sysdir = tmp_path / "usr/share"
    (sysdir / "applications").mkdir(parents=True)
    pkg = sysdir / "applications/ws.desktop"
    pkg.write_text(PKG)
    (sysdir / "applications/message_aggregator.desktop").write_text(
        "[Desktop Entry]\nName=MA\nExec=message_aggregator\n")
    desk = tmp_path / "Schreibtisch"
    desk.mkdir()
    (desk / "ws.desktop").symlink_to(pkg)                      # wie beim Nutzer: Verweis
    (desk / "andere.desktop").write_text("[Desktop Entry]\nName=Q\nExec=qlog\n")
    (desk / "ws-kopie.desktop").write_text(PKG)                # echte Kopie
    for p in ws.starter_paths(home):                           # alter Extra-Starter (0.10.44)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(ws.starter_text("/usr/bin/ws"))
    run = dict(find=lambda k: "/usr/bin/ws", running=lambda k: False, data_dirs=[sysdir])
    for _ in range(2):                                         # zweimal = „Erneuern“
        res = ws.install(home, **run)
        assert res.ok
        qss = ws.qss_path(home)
        want = f"Exec=ws -style Fusion -stylesheet {qss} %f"
        menu = tmp_path / ".local/share/applications/ws.desktop"
        for p in (menu, desk / "ws.desktop", desk / "ws-kopie.desktop"):
            t = p.read_text()
            assert not p.is_symlink() and t.count(want) == 1 and "Name[de]=WS Funk" in t
            assert "Exec=ws --x" in t and t.count(ws.MARK) == 1 and p.stat().st_mode & 0o111
        assert not any(p.exists() for p in ws.starter_paths(home))
        assert ws.is_installed(home)
    assert any("2 WS-Symbol" in ln for ln in res.lines)
    assert pkg.read_text() == PKG and "ws" not in (desk / "andere.desktop").read_text().lower()
    ws.remove(home)
    assert not menu.exists() and not ws.is_installed(home)
    assert (desk / "ws.desktop").is_symlink() and (desk / "ws.desktop").resolve() == pkg
    assert (desk / "ws-kopie.desktop").read_text() == PKG
    assert not list(ws.backup_dir(home).iterdir())


def test_remove_without_backup(tmp_path):
    """Fehlt die Sicherung, wird das Aussehen aus der Startzeile wieder herausgenommen."""
    home = str(tmp_path)
    (tmp_path / "Desktop").mkdir()
    p = tmp_path / "Desktop/ws.desktop"
    p.write_text(ws.nightshift_text(PKG, Path("/x/ws-nightshift.qss")))
    ws.remove(home)
    assert p.read_text() == PKG.rstrip("\n") + "\n" and ws.MARK not in p.read_text()


def test_users_own_menu_entry_kept(tmp_path):
    home = str(tmp_path)
    own = tmp_path / ".local/share/applications/ws.desktop"
    own.parent.mkdir(parents=True)
    own.write_text(PKG.replace("Exec=ws %f", "Exec=ws --mein"))
    ws.install(home, find=lambda k: "/usr/bin/ws", running=lambda k: False, data_dirs=[])
    assert "Exec=ws -style Fusion -stylesheet" in own.read_text() and "--mein" in own.read_text()
    ws.remove(home)
    assert own.read_text() == PKG.replace("Exec=ws %f", "Exec=ws --mein")


SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
app = QApplication([])
from gogoham import devmode, wsnightshift
devmode.PASSWORD_HASH = devmode.make_hash("geheim", rounds=1000)
devmode.lock()
from gogoham.gui import dev_page
told, saved, out = [], [], {}
QMessageBox.warning = staticmethod(lambda *a, **k: told.append(a[2]))
QMessageBox.information = staticmethod(lambda *a, **k: told.append(a[2]))
shown = []
def fake_exec(self, ok=True):
    shown.append([ck for ck in self.page.boxes])
    self.page.boxes.get("free_log") and self.page.boxes["free_log"].setChecked(True)
    self.accept()
    return 1
dev_page.DevWindow.exec = fake_exec
cfg = {}
save = lambda c: saved.append(dict(c))
answers = ["falsch", None, "geheim"]
ask = lambda parent: answers.pop(0)
out["wrong"] = [dev_page.open_dev_window(None, cfg, save, ask=ask), told[-1], devmode.is_unlocked()]
out["cancel"] = dev_page.open_dev_window(None, cfg, save, ask=ask)
out["right"] = [dev_page.open_dev_window(None, cfg, save, ask=ask), devmode.is_unlocked()]
out["no_ask"] = dev_page.open_dev_window(None, cfg, save, ask=lambda p: 1 / 0)   # schon frei
out["home"] = dev_page.open_dev_window(None, {}, save, features=False, ask=lambda p: 1 / 0)
out["shown"] = shown
out["saved"] = saved
# WS-Knöpfe im Fenster
w = dev_page.DevWindow({}, None, features=False)
p = w.page
out["state0"] = [p.ws_state.text(), p.ws_install.text(), p.ws_remove.isEnabled(), p.isWindow()]
wsnightshift.install = lambda: wsnightshift.Result(False, ["WS läuft gerade"])
p.install_ws()
out["refused"] = told[-1]
# Hauptfenster: Kürzel vorhanden
from gogoham.gui import main_window
from PySide6.QtGui import QShortcut
src = open(main_window.__file__, encoding="utf-8").read()
out["shortcut"] = 'QKeySequence("Ctrl+Shift+E")' in src and "def open_dev" in src
devmode.PASSWORD_HASH = ""; devmode.lock()
out["no_hash"] = dev_page.open_dev_window(None, {}, save, ask=lambda p: 1 / 0)
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def test_dev_window(tmp_path):
    env = {"QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin",
           "XDG_CONFIG_HOME": str(tmp_path / "xdg"), "XDG_DATA_HOME": str(tmp_path / "d")}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent)],
                       capture_output=True, text=True, env=env, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["wrong"] == [False, "Falsches Passwort.", False]
    assert o["cancel"] is False
    assert o["right"] == [True, True]
    assert o["no_ask"] is True and o["home"] is True
    assert o["shown"] == [["free_log"], ["free_log"], []]          # GoGoHome: ohne Schalter
    assert o["saved"][0] == {"dev_features": {"free_log": True}}
    assert o["state0"] == ["Stand: nicht eingerichtet", "Einrichten", False, False]   # eingebettet
    assert o["refused"] == "• WS läuft gerade"
    assert o["shortcut"] is True
    assert o["no_hash"] is False


def test_main_window_shortcut(tmp_path):
    """Strg+Umschalt+E im echten Hauptfenster ruft open_dev → open_dev_window."""
    code = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QShortcut, QKeySequence
app = QApplication([])
from gogoham.gui import main_window, dev_page
calls = []
dev_page.open_dev_window = lambda parent, cfg, save, **k: calls.append(save.__name__) or True
from gogoham import config as cfgmod
cfg = cfgmod.load()
w = main_window.MainWindow.__new__(main_window.MainWindow)
w.cfg = cfg
w.open_dev()
print("RESULT " + json.dumps(calls))
'''
    env = {"QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin",
           "XDG_CONFIG_HOME": str(tmp_path / "xdg"), "XDG_DATA_HOME": str(tmp_path / "d")}
    r = subprocess.run([sys.executable, "-c", code, str(HERE.parent)],
                       capture_output=True, text=True, env=env, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    assert json.loads(lines[-1][7:]) == ["save"]


def test_side_tabs_bigger():
    """0.10.47.3: die senkrechten Reiter 1/2/3 in WS sind größer (Nutzer: „sehr klein“)."""
    rule = ws.QSS.split("QTabBar::tab:left, QTabBar::tab:right {", 1)[1].split("}", 1)[0]
    assert "min-height:30px" in rule and "padding:6px 4px" in rule and "border:none" in rule
