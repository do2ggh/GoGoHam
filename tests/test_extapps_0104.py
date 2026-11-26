"""0.10.4: Zusatzprogramme – erkennen, installieren, Verbindung zu GoGoHam eintragen.
Nur mit Attrappen und Dateien im Testordner; es wird nichts installiert."""

from gogoham import extapps, rigprofiles

# Ausschnitt so, wie WSJT-X (Improved) die Datei schreibt
INI = (
    "[General]\nx=1\n\n[Configuration]\nAcceptUDPRequests=true\n"
    "CATNetworkPort=192.168.1.5:4540\nCATSerialPort=/dev/ttyUSB0\n"
    r"PTTMethod=@Variant(\0\0\0\x7f\0\0\0\x1eTransceiverFactory::PTTMethod\0\0\0\0\xfPTT_method_VOX\0)"
    "\nRig=Icom IC-7300\nUDPServer=127.0.0.1\nUDPServerPort=2237\nMyCall=DO2GGH\n\n"
    "[MultiSettings]\nCurrentName=Default\n"
)


def test_five_profiles():
    assert rigprofiles.MAX_PROFILES == 5
    cfg = {"rig_profiles": [{"name": str(i), "model": 1, "port": 4532 + i, "slot": i}
                            for i in range(5)]}
    rigprofiles.ensure_profiles(cfg)
    assert [p["slot"] for p in cfg["rig_profiles"]] == [0, 1, 2, 3, 4]
    assert rigprofiles.free_port(cfg) == 4537


def test_changes_and_apply(tmp_path):
    ini = tmp_path / "WS.ini"
    ini.write_text(INI)
    diff = extapps.changes(ini, "127.0.0.1", 4532, "127.0.0.1", 2237)
    labels = [d[0] for d in diff]
    assert ("Verbindung zum Funkgerät: 127.0.0.1:4532", "192.168.1.5:4540") in diff
    assert ("PTT (Senden): über CAT", "VOX") in diff
    assert ("Funkgerät: Hamlib NET rigctl", "Icom IC-7300") in diff
    assert not any("UDP" in x for x in labels)          # stimmt schon
    backup = extapps.apply(ini, "127.0.0.1", 4532, "127.0.0.1", 2237, now=0)
    assert backup and backup.read_text() == INI           # Sicherungskopie = alter Stand
    new = ini.read_text()
    assert "MyCall=DO2GGH" in new and "CATSerialPort=/dev/ttyUSB0" in new
    assert "[MultiSettings]\nCurrentName=Default" in new
    assert "Rig=Hamlib NET rigctl\n" in new and "CATNetworkPort=127.0.0.1:4532\n" in new
    assert extapps.PTT_CAT in new
    assert extapps.changes(ini, "127.0.0.1", 4532, "127.0.0.1", 2237) == []
    # nur die Werte geändert, keine Zeile mehr oder weniger
    assert len(new.splitlines()) == len(INI.splitlines())


def test_apply_new_file_and_missing_keys(tmp_path):
    ini = tmp_path / "cfg" / "JTDX.ini"
    assert extapps.apply(ini, "127.0.0.1", 4533, "224.0.0.1", 2237) is None
    vals = extapps.current(ini)
    assert vals["CATNetworkPort"] == "127.0.0.1:4533" and vals["UDPServer"] == "224.0.0.1"
    other = tmp_path / "x.ini"
    other.write_text("[Configuration]\r\nMyCall=DL1ABC\r\n\r\n[Other]\r\na=b\r\n")
    extapps.apply(other, "127.0.0.1", 4532, "127.0.0.1", 2237)
    text = other.read_bytes().decode()
    assert "\r\n" in text and "MyCall=DL1ABC" in text
    # neue Schlüssel stehen im Abschnitt [Configuration], nicht in [Other]
    conf = text.split("[Other]")[0]
    assert "UDPServerPort=2237" in conf and "Rig=Hamlib NET rigctl" in conf


def test_ini_path(tmp_path):
    (tmp_path / ".config").mkdir()
    home = str(tmp_path)
    assert extapps.ini_path("wsjtx_improved", home, "/usr/bin/ws").name == "WS.ini"
    assert extapps.ini_path("wsjtx_improved", home, "/usr/bin/wsjtx").name == "WSJT-X.ini"
    (tmp_path / ".config" / "WSJT-X.ini").write_text("")
    assert extapps.ini_path("wsjtx_improved", home, "/usr/bin/ws").name == "WSJT-X.ini"


def test_find_improved_vs_original():
    which = {"wsjtx": "/usr/bin/wsjtx"}.get
    # 0.10.13: Original-WSJT-X gibt es in GoGoHam nicht mehr – sein „wsjtx“ ist nicht WS
    assert "wsjtx" not in extapps.BY_KEY
    assert extapps.find("wsjtx_improved", which, owner=lambda p: "wsjtx") is None
    assert extapps.find("wsjtx_improved", which,
                        owner=lambda p: "wsjtx-improved") == "/usr/bin/wsjtx"
    ws = {"ws": "/usr/bin/ws"}.get
    assert extapps.find("wsjtx_improved", ws, owner=lambda p: "") == "/usr/bin/ws"
    assert extapps.find("wsjtx_improved", ws, owner=lambda p: "ws") == "/usr/bin/ws"   # Debian
    assert extapps.find("wsjtx_improved", ws, owner=lambda p: "websocket-tool") is None
    assert extapps.find("fldigi", {"fldigi": "/usr/bin/fldigi"}.get) == "/usr/bin/fldigi"


def test_package_and_install_command():
    calls = []

    def run(args, timeout=0):
        calls.append(args)
        return (0, "Name : wsjtx-improved\n") if args[-1] == "wsjtx-improved" else (1, "")
    # 0.10.14: fldigi immer von Flathub (neueste Version)
    assert extapps.available_package("fldigi", "pacman", run) == "flathub:com.w1hkj.fldigi"
    # WS unter Arch ohne AUR-Helfer: offizielle Quellen (0.10.17: JTDX nicht mehr dabei)
    assert extapps.available_package("wsjtx_improved", "pacman", run,
                                     which=lambda n: None) == "wsjtx-improved"
    assert calls[0] == ["pacman", "-Si", "wsjtx-improved"]
    assert extapps.available_package("wsjtx_improved", "", run) == ""
    which = {"pkexec": "/usr/bin/pkexec", "zypper": "/usr/bin/zypper"}.get
    assert extapps.install_command("fldigi", which=which) == [
        "pkexec", "/bin/sh", "-c", "zypper --non-interactive install fldigi"]
    assert extapps.install_command("fldigi", which={"zypper": "/x"}.get) is None
    assert extapps.owner_package("/usr/bin/ws", "apt-get",
                                 lambda a, t=0: (0, "wsjtx-improved: /usr/bin/ws\n")) == \
        "wsjtx-improved"


def test_running():
    assert extapps.running("wsjtx_improved",
                           lambda a, t=0: (0 if a == ["pgrep", "-x", "ws"] else 1, ""))
    assert not extapps.running("fldigi", lambda a, t=0: (1, ""))


SCRIPT = r'''
import json, sys, os
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import extapps
from gogoham.gui.dialogs import WsjtxDialog
from gogoham.gui.apps_page import AppsPage
extapps.find = lambda k, *a, **kw: "/usr/bin/ws" if k == "wsjtx_improved" else None
extapps.running = lambda k, *a, **kw: False
cfg = {"wsjtx_enabled": False, "wsjtx_address": "127.0.0.1", "wsjtx_port": 2237,
       "rig_profile": 0, "rig_profiles": [
           {"name": "IC-7300", "model": 3073, "port": 4532, "slot": 1, "start": True},
           {"name": "FT-891", "model": 1036, "port": 4533, "slot": 2, "service": True}]}
w = WsjtxDialog(cfg, embedded=True)
page = AppsPage(cfg, w, check=False)
asked, told = [], []
page.ask = lambda t, x: (asked.append(x), True)[1]
page.tell = lambda t, x: told.append(x)
out = {"hint0": page.hint.text()}
cfg["rig_profile"] = 1                                # Station → Funkgerät-Profil: FT-891
page._update_hint()
out["hint1"] = page.hint.text()
ini = Path(os.environ["HOME"]) / ".config" / "WS.ini"
ini.parent.mkdir(parents=True)
ini.write_text("[Configuration]\nMyCall=DO2GGH\nRig=None\n")
out["ok"] = page.setup_connection("wsjtx_improved")
out["asked"] = asked
out["vals"] = extapps.current(ini)
out["backups"] = len(list(ini.parent.glob("WS.ini.gogoham-*.bak")))
out["enabled"] = w.enabled.isChecked()
out["again"] = page.setup_connection("wsjtx_improved")
out["told"] = told
out["btn"] = [page.buttons["wsjtx_improved"].text(),
              page.setup_buttons["wsjtx_improved"].isEnabled(),
              page.setup_buttons["fldigi"].isEnabled(),
              page.remove_buttons["wsjtx_improved"].isHidden(),
              page.remove_buttons["fldigi"].isHidden()]
print("RESULT " + json.dumps(out))
'''


def test_apps_page_setup(tmp_path):
    import json, subprocess, sys, textwrap
    from pathlib import Path
    env = {"QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin",
           "XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT),
                        str(Path(__file__).parent.parent)],
                       capture_output=True, text=True, env=env, timeout=60)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert "IC-7300 (Port 4532)" in o["hint0"] and "solange GoGoHam läuft" in o["hint0"]
    assert "FT-891 (Port 4533)" in o["hint1"] and "solange" not in o["hint1"]
    assert o["ok"] is True and len(o["asked"]) == 1
    assert "127.0.0.1:4533" in o["asked"][0] and "(bisher: None)" in o["asked"][0]
    assert o["vals"]["CATNetworkPort"] == "127.0.0.1:4533" and o["vals"]["MyCall"] == "DO2GGH"
    assert o["backups"] == 1 and o["enabled"] is True
    assert o["again"] is True and "nichts zu ändern" in o["told"][-1]
    assert "Sicherungskopie" in o["told"][0]
    assert o["btn"] == ["Downloadseite", True, False, False, True]
