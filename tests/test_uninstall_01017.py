"""0.10.17: Zusatzprogramme deinstallieren; JTDX ist nicht mehr dabei."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham import extapps, wsdl


def test_jtdx_gone():
    assert [a.key for a in extapps.APPS] == ["wsjtx_improved", "fldigi"]
    assert "jtdx" not in wsdl.PROJECTS


def test_removable_package():
    dpkg = lambda a, t=0: (0, "ws: /usr/bin/ws\n")                      # noqa: E731
    assert extapps.removable_package("wsjtx_improved", "/usr/bin/ws", "apt-get", dpkg) == "ws"
    pac = lambda a, t=0: (0, "wsjtx-improved\n")                         # noqa: E731
    assert extapps.removable_package("wsjtx_improved", "/usr/bin/ws", "pacman", pac) \
        == "wsjtx-improved"
    # gehört zu einem fremden Paket → nicht anfassen
    other = lambda a, t=0: (0, "big-ham-suite\n")                        # noqa: E731
    assert extapps.removable_package("fldigi", "/usr/bin/fldigi", "pacman", other) == ""
    # selbst gebaut (keinem Paket zugeordnet)
    none = lambda a, t=0: (1, "")                                        # noqa: E731
    assert extapps.removable_package("fldigi", "/usr/local/bin/fldigi", "pacman", none) == ""
    assert extapps.removable_package("fldigi", "flatpak:com.w1hkj.fldigi") \
        == "flatpak:com.w1hkj.fldigi"
    assert extapps.removable_package("fldigi", None) == ""


def test_uninstall_command():
    w = {"pkexec": "/x", "pacman": "/x", "flatpak": "/x"}.get
    # nur das Paket selbst – bricht ab, wenn ein anderes es braucht
    assert extapps.uninstall_command("wsjtx-improved", "pacman", w) == [
        "pkexec", "/bin/sh", "-c", "pacman -R --noconfirm wsjtx-improved"]
    assert extapps.uninstall_command("ws", "apt-get", w)[-1] == "dpkg -r ws"
    assert extapps.uninstall_command("ws", "dnf", w)[-1] == "rpm -e ws"
    assert extapps.uninstall_command("ws", "zypper", w)[-1] == "rpm -e ws"
    assert extapps.uninstall_command("ws", "pacman", {"pacman": "/x"}.get) is None   # kein pkexec
    assert extapps.uninstall_command("", "pacman", w) is None
    # Flatpak für alle: mit pkexec, danach nicht mehr gebrauchte Laufzeiten weg
    cmd = extapps.uninstall_command("flatpak:com.w1hkj.fldigi", "pacman", w,
                                    user_only=lambda i: False)
    assert cmd[0] == "pkexec" and "uninstall --system -y --noninteractive com.w1hkj.fldigi" \
        in cmd[-1] and "--unused" in cmd[-1]
    # Flatpak nur im Benutzerordner: ohne pkexec
    cmd = extapps.uninstall_command("flatpak:com.w1hkj.fldigi", "pacman", w,
                                    user_only=lambda i: True)
    assert cmd[0] == "/bin/sh" and "--user" in cmd[-1]
    assert extapps.uninstall_command("flatpak:x", "pacman", {"pkexec": "/x"}.get) is None


def test_flatpak_user_only(tmp_path):
    app = tmp_path / ".local/share/flatpak/app/com.w1hkj.fldigi/current"
    assert not extapps.flatpak_user_only("com.w1hkj.fldigi", str(tmp_path))
    app.mkdir(parents=True)
    assert extapps.flatpak_user_only("com.w1hkj.fldigi", str(tmp_path)) \
        == (not Path("/var/lib/flatpak/app/com.w1hkj.fldigi/current").exists())


SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import extapps
from gogoham.gui.dialogs import WsjtxDialog
from gogoham.gui.apps_page import AppsPage
state = {"found": True, "running": False}
extapps.find = lambda k, *a, **kw: "/usr/bin/ws" if k == "wsjtx_improved" and state["found"] else None
extapps.running = lambda k, *a, **kw: state["running"]
extapps.installed_version = lambda *a, **kw: "3.2.1.261010-1"
extapps.removable_package = lambda k, p, *a, **kw: "ws"
extapps.uninstall_command = lambda pkg, *a, **kw: ["pkexec", "/bin/sh", "-c", "dpkg -r " + pkg]
cfg = {"wsjtx_enabled": False, "wsjtx_address": "127.0.0.1", "wsjtx_port": 2237}
page = AppsPage(cfg, WsjtxDialog(cfg, embedded=True), check=False)
asked, told, ran = [], [], []
answer = {"v": False}
page.ask = lambda t, x: (asked.append(x), answer["v"])[1]
page.tell = lambda t, x: told.append(x)
page._run_install = lambda k, cmd, aur=False, remove=False: ran.append([k, cmd, remove])
out = {"visible": not page.remove_buttons["wsjtx_improved"].isHidden(),
       "fldigi_hidden": page.remove_buttons["fldigi"].isHidden(),
       "no_pref": page.ft8_pref.isHidden()}
state["running"] = True
page.uninstall("wsjtx_improved")
out["running"] = told[-1]
state["running"] = False
page.uninstall("wsjtx_improved")                       # Nein gesagt
out["asked"] = asked[-1]
out["ran_after_no"] = len(ran)
answer["v"] = True
page.uninstall("wsjtx_improved")
out["ran"] = ran[-1]
out["removing"] = page._removing
# Abschluss: weg
page._removing = ""
state["found"] = False
page.refresh()
page._removed(extapps.BY_KEY["wsjtx_improved"], 0, "")
out["done"] = told[-1]
out["hidden_after"] = page.remove_buttons["wsjtx_improved"].isHidden()
page._removed(extapps.BY_KEY["wsjtx_improved"], 1, "error: ws wird benötigt von xyz")
out["fail"] = told[-1]
print("RESULT " + json.dumps(out))
'''


def test_apps_page_uninstall(tmp_path):
    env = {"QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin",
           "XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT),
                        str(Path(__file__).parent.parent)],
                       capture_output=True, text=True, env=env, timeout=60)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["visible"] and o["fldigi_hidden"] and o["no_pref"]
    assert "bitte zuerst schließen" in o["running"]
    assert "WS (DG2YCB) 3.2.1 jetzt deinstallieren?" in o["asked"]
    assert "Einstellungen und Logs" in o["asked"]
    assert o["ran_after_no"] == 0
    assert o["ran"] == ["wsjtx_improved", ["pkexec", "/bin/sh", "-c", "dpkg -r ws"], True]
    assert o["removing"] == "wsjtx_improved"
    assert "ist deinstalliert" in o["done"] and o["hidden_after"]
    assert "ws wird benötigt von xyz" in o["fail"]
