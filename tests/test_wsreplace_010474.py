"""0.10.47.4: WS vom Entwickler ersetzt das gleichnamige Debian-Paket „wsjtx-improved“
(beide bringen /usr/bin/cablog usw. mit – sonst „trying to overwrite …“, dpkg Fehler 1).
WSJT-X (Paket „wsjtx“) wird nur nach Rückfrage entfernt."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham import wsdl


def test_installed_debs():
    out = ("wsjtx-improved install ok installed\n"
           "wsjtx-improved-doc deinstall ok config-files\n"
           "wsjtx-improved-data:amd64 install ok installed\n")
    seen = []

    def run(args, timeout=0):
        seen.append(args)
        return 1, out                      # dpkg-query: Code 1, wenn ein Name unbekannt ist
    assert wsdl.installed_debs(wsdl.REPLACE_DEBS, run) == ["wsjtx-improved",
                                                           "wsjtx-improved-data"]
    assert seen[0][:2] == ["dpkg-query", "-W"] and seen[0][-3:] == list(wsdl.REPLACE_DEBS)
    assert wsdl.installed_debs(wsdl.CONFLICT_DEBS, lambda a, t=0: (-1, "")) == []


def test_install_shell_removes_in_same_step():
    s = wsdl.install_shell(Path("/c/ws.deb"), "apt-get", ["wsjtx-improved", "wsjtx-improved-data"])
    assert s.endswith("apt-get install -y '/c/ws.deb' wsjtx-improved- wsjtx-improved-data-")
    # nur echte Paketnamen – nichts, was die Befehlszeile verändern könnte
    s = wsdl.install_shell(Path("/c/ws.deb"), "apt-get", ["x; rm -rf /", "wsjtx"])
    assert s.endswith("'/c/ws.deb' wsjtx-") and "rm" not in s
    assert wsdl.install_shell(Path("/x.rpm"), "dnf", ["wsjtx"]) == "dnf install -y '/x.rpm'"


SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import extapps, wsdl
from gogoham.gui.dialogs import WsjtxDialog
from gogoham.gui.apps_page import AppsPage
extapps.find = lambda k, *a, **kw: None
extapps.running = lambda k, *a, **kw: False
extapps.package_manager = lambda *a, **kw: "apt-get"
inst = {"REPLACE": ["wsjtx-improved"], "CONFLICT": []}
wsdl.installed_debs = lambda names, run=None: list(
    inst["REPLACE"] if names == wsdl.REPLACE_DEBS else inst["CONFLICT"])
wsdl.latest = lambda kind, project=None: wsdl.Package("3.2.1", "261010", "u", "m", kind)
wsdl.download = lambda p, folder, prog=None: Path("/c/ws.deb")
cfg = {"wsjtx_enabled": False, "wsjtx_address": "127.0.0.1", "wsjtx_port": 2237,
       "rig_profile": 0, "rig_profiles": []}
page = AppsPage(cfg, WsjtxDialog(cfg, embedded=True), check=False)
cmds, asked = [], []
page._run_install = lambda key, cmd, **kw: cmds.append(cmd)
answer = {"v": False}
page._ask = lambda t, x: (asked.append(x), answer["v"])[1]

def go():
    n = len(cmds)
    page._install_dg2ycb("wsjtx_improved", "deb")
    for _ in range(200):
        app.processEvents()
        if len(cmds) > n or not page._installing:
            break
        import time; time.sleep(0.02)
    return cmds[-1][-1] if len(cmds) > n else None

out = {"replace": go(), "asked0": len(asked)}
inst["CONFLICT"] = ["wsjtx", "wsjtx-data"]
out["no"] = go()
out["asked1"] = asked[-1]
answer["v"] = True
out["yes"] = go()
inst["REPLACE"], inst["CONFLICT"] = [], []
out["plain"] = go()
print("RESULT " + json.dumps(out))
'''


def test_apps_page_replaces_old_ws(tmp_path):
    env = {"QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin",
           "XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT),
                        str(Path(__file__).parent.parent)],
                       capture_output=True, text=True, env=env, timeout=60)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    # altes WS aus den Paketquellen: ohne Rückfrage im selben Schritt ersetzt
    assert o["replace"].endswith("'/c/ws.deb' wsjtx-improved-") and o["asked0"] == 0
    # WSJT-X installiert: Rückfrage; „Nein“ = nichts passiert
    assert o["no"] is None and "WSJT-X entfernen und WS installieren?" in o["asked1"]
    assert o["yes"].endswith("'/c/ws.deb' wsjtx-improved- wsjtx- wsjtx-data-")
    assert o["plain"].endswith("'/c/ws.deb'")
