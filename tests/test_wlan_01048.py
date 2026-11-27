"""0.10.48: WLAN verbinden ohne Linux-Kenntnisse (gogoham/wlan.py, gui/wlan_dialog.py)."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham import wlan

HERE = Path(__file__).resolve().parent

LIST = """\
 :Heimnetz:72:WPA2
*:Heimnetz:85:WPA2
 :Gast\\:Café:40:
 ::90:WPA2
 :Nachbar:20:WPA1 WPA2
 :Offen:55:--
"""


def test_split_terse():
    assert wlan.split_terse(r"a\:b:c\\d:") == ["a:b", "c\\d", ""]


def test_parse_networks():
    nets = wlan.parse_networks(LIST)
    assert [n.ssid for n in nets] == ["Heimnetz", "Offen", "Gast:Café", "Nachbar"]
    home = nets[0]
    assert home.signal == 85 and home.secure and home.in_use     # stärkstes von zweien, verbunden
    assert not nets[1].secure and not nets[2].secure              # „--“ und leer = offen
    assert nets[3].secure


def test_state_and_bars():
    assert wlan.has_wifi("ethernet:unavailable\nwifi:disconnected\nloopback:connected (externally)")
    assert not wlan.has_wifi("ethernet:connected\nwifi:unavailable")
    assert not wlan.has_wifi("ethernet:connected")
    assert wlan.online("connected\n") and not wlan.online("connected (site only)")
    assert not wlan.online("disconnected")
    assert wlan.bars(10) == "▂···" and wlan.bars(60) == "▂▄▆·" and wlan.bars(95) == "▂▄▆█"


def test_failure():
    msg = "Error: Connection activation failed: Secrets were required, but not provided."
    assert wlan.failure(4, "", msg) == "password"
    assert wlan.failure(10, "", "Error: No network with SSID 'x' found.") == "not_found"
    assert wlan.failure(-2, "", "timeout") == "timeout"
    assert wlan.failure(1, "", "Error: something else") == "other"


class FakeNmcli:
    def __init__(self, connect_code=0, connect_err=""):
        self.profiles = {"Kabel"}
        self.calls = []
        self.connect_code, self.connect_err = connect_code, connect_err

    def __call__(self, args, timeout):
        self.calls.append(args)
        if args[:5] == ["nmcli", "-t", "-f", "NAME", "connection"]:
            return 0, "\n".join(sorted(self.profiles)) + "\n", ""
        if "connect" in args and "wifi" in args:
            self.profiles.add(args[args.index("connect") + 1])      # nmcli legt immer an
            return self.connect_code, "", self.connect_err
        if args[:3] == ["nmcli", "connection", "delete"]:
            self.profiles.discard(args[-1])
            return 0, "", ""
        if args[-1] == "device" and "TYPE,STATE" in args:
            return 0, "wifi:disconnected\n", ""
        if args[-1] == "general":
            return 0, "disconnected\n", ""
        return 1, "", "unbekannt"


def test_connect():
    ok = FakeNmcli()
    assert wlan.connect("Heimnetz", "geheim123", run=ok) == (True, "")
    cmd = [c for c in ok.calls if "connect" in c][0]
    assert cmd[-4:] == ["connect", "Heimnetz", "password", "geheim123"]
    assert "Heimnetz" in ok.profiles
    # falsches Passwort: neu angelegte Verbindung wieder weg, sonst probiert NM es beim Start
    bad = FakeNmcli(4, "Error: Connection activation failed: Secrets were required, but not "
                       "provided.")
    assert wlan.connect("Heimnetz", "falsch", run=bad) == (False, "password")
    assert "Heimnetz" not in bad.profiles
    # schon gespeicherte Verbindung bleibt auch bei einem Fehlversuch
    known = FakeNmcli(4, "Error: Secrets were required, but not provided.")
    known.profiles.add("Heimnetz")
    wlan.connect("Heimnetz", "falsch", run=known)
    assert "Heimnetz" in known.profiles
    # offenes Netz: kein Passwort
    op = FakeNmcli()
    wlan.connect("Offen", run=op)
    assert [c for c in op.calls if "connect" in c][0][-2:] == ["connect", "Offen"]
    assert wlan.state(run=op) == (True, False)
    assert wlan.state(run=lambda a, t: (-1, "", "fehlt")) == (False, False)


def test_dialog(tmp_path):
    script = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(HERE.parent)!r})
        from PySide6.QtWidgets import QApplication
        app = QApplication([])
        from gogoham import wlan
        from gogoham.gui.wlan_dialog import WlanDialog
        nets = [wlan.Network("Heimnetz", 80, True), wlan.Network("Offen", 50, False)]
        tried = []
        def connect(ssid, pw):
            tried.append((ssid, pw))
            return (False, "password") if pw == "falsch" else (True, "")
        def wait(cond):
            t = time.time() + 5
            while not cond() and time.time() < t:
                app.processEvents(); time.sleep(0.02)
        cfg = {{}}
        d = WlanDialog(cfg, at_start=True, scan_fn=lambda: nets, connect_fn=connect)
        wait(lambda: d.list.count() == 2)
        assert "Heimnetz" in d.list.item(0).text() and "▂▄▆█" in d.list.item(0).text()
        assert d.password.isEnabled()
        d.start_connect()                                   # ohne Passwort: nur Hinweis
        assert tried == [] and "Passwort" in d.status.text()
        d.password.setText("falsch"); d.start_connect()
        wait(lambda: d.btn_scan.isEnabled())
        assert "Passwort stimmt nicht" in d.status.text() and not d.ok_ssid
        d.password.setText("richtig"); d.start_connect()
        wait(lambda: d.ok_ssid)
        assert d.ok_ssid == "Heimnetz" and "Verbunden" in d.status.text()
        d.list.setCurrentRow(1)
        assert not d.password.isEnabled()                   # offenes Netz
        d.chk_ask.setChecked(False); d.show(); d.reject()
        assert cfg["stick_wlan_ask"] is False
        print("ok", tried)
    """)
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    assert r.stdout.startswith("ok"), r.stderr[-2000:]
    assert "('Heimnetz', 'richtig')" in r.stdout
