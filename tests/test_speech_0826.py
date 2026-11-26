"""0.8.26: Ansagen per Sprachausgabe (speech.py, Reiter „Ansagen“, Tasten Alt+1 … Alt+6)."""

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham import speech


class FakeProc:
    def __init__(self, args, **kw):
        self.args, self.done = args, False

    def poll(self):
        return 0 if self.done else None

    def terminate(self):
        self.done = True


class FakeSpeaker:
    ok = True

    def __init__(self):
        self.said, self.stops = [], 0

    def say(self, text):
        self.said.append(text)

    def stop(self):
        self.stops += 1


# ------------------------------------------------------------ Texte
def test_texts():
    assert speech.spell_call("dl1abc/p") == "D L 1 A B C Strich P"
    assert speech.spell_call("DL1A", phonetic=True) == "Delta Lima 1 Alfa"
    assert speech.band_words("20") == "20 Meter"
    assert speech.band_words("70cm") == "70 Zentimeter"
    assert speech.band_words("1.25cm") == "24 Gigahertz"
    assert speech.band_words("submm") == "über 300 Gigahertz"
    assert speech.mode_words("CW") == "C W" and speech.mode_words("USB") == "U S B"
    assert speech.mode_words("PKTUSB") == "Daten U S B"
    assert speech.freq_words(14_025_300, "CW") == "14,025 Megahertz, C W"
    assert speech.clean("⚠ DUPE · 20 m ★") == "DUPE , 20 m"


def test_choose_backend():
    assert speech.choose("auto", True, True, False) == "speechd"
    assert speech.choose("auto", False, True, False) == "espeak"
    assert speech.choose("espeak", True, True, False) == "espeak"
    assert speech.choose("speechd", False, True, False) == "espeak"   # Ersatz, statt stumm
    assert speech.choose("auto", False, False, False) is None
    assert speech.choose("auto", True, True, True) == "piper"          # 0.8.26.2
    assert speech.choose("espeak", True, True, True) == "espeak"
    assert speech.choose("piper", True, True, False) == "speechd"
    assert speech.backend_name(None) == "keine"


def test_espeak_speaker_interrupts(monkeypatch):
    monkeypatch.setattr(speech, "espeak_exe", lambda: "/usr/bin/espeak-ng")
    procs = []
    sp = speech.Speaker("espeak", "fast", lang="de",
                        popen=lambda a, **k: procs.append(FakeProc(a)) or procs[-1])
    sp.say("Dupe")
    sp.say("⚠ Neuer Multi")
    assert procs[0].args == ["/usr/bin/espeak-ng", "-v", "de", "-s", "230", "Dupe"]
    assert procs[0].done and procs[1].args[-1] == "Neuer Multi"     # neue Ansage unterbricht
    sp.stop()
    assert procs[1].done
    assert not speech.Speaker(None).ok


# ------------------------------------------------------------ Wann wird gesprochen?
def test_announcer_rules():
    cfg = {"announce_enabled": False}
    fs = FakeSpeaker()
    a = speech.Announcer(cfg, fs)
    a.call_status("DL1ABC", "dupe")
    a.say("Test")
    assert fs.said == []                                   # aus = stumm
    cfg["announce_enabled"] = True
    a.call_status("DL1ABC", "dupe")
    a.call_status("DL1ABC", "dupe")                        # gleicher Zustand: nur einmal
    a.call_status("DL1ABC", "ok")
    a.call_status("DL1ABC", "dupe")                        # wieder Dupe: neu ansagen
    a.call_status("DK5XY", "new_mult")
    assert fs.said == ["Dupe", "Dupe", "Neuer Multi"]
    fs.said.clear()
    a.band_mode("10", "USB")                               # Startbildschirm: Ruhezeit (0.8.26.3)
    a.band_mode("20", "CW")                                # Log/Funkgerät beim Start: still
    assert fs.said == []
    a.quiet(0)
    a.band_mode("20", "CW")
    a.band_mode("40", "CW")
    a.band_mode("40", "USB")
    assert fs.said == ["40 Meter", "U S B"]
    a.quiet(60)                                            # z. B. Funkgerät gerade verbunden
    a.band_mode("15", "USB")
    a.quiet(0)
    a.band_mode("15", "USB")
    assert fs.said == ["40 Meter", "U S B"]
    fs.said.clear()
    cfg["announce_events"] = {"logged": False, "band": False}
    a.logged("DL1ABC")
    a.band_mode("80", "USB")
    a.hint("Verbunden mit DB0SUE", "info")                 # Infos nicht vorlesen
    a.hint("Funkgerät antwortet nicht", "warn")
    assert fs.said == ["Funkgerät antwortet nicht"] and a.last_text == fs.said[-1]
    cfg["announce_spelling"] = "phonetic"
    cfg["announce_events"] = {}
    a.logged("DA0X")
    assert fs.said[-1] == "Geloggt: Delta Alfa 0 X-Ray"


# ------------------------------------------------------------ im echten Hauptfenster
GUI_SCRIPT = r'''
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui.main_window import MainWindow
from gogoham.gui.dialogs import SettingsDialog
MainWindow._welcome = lambda self: None
MainWindow._ask_scp = lambda self, *a, **k: None
w = MainWindow()
p = Path(sys.argv[2]) / "cq.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="cqww-ssb", mycall="DO2GGH")); db.close()
w.open_log(str(p))
class Fake:
    ok = True
    def __init__(self): self.said = []
    def say(self, t): self.said.append(t)
    def stop(self): pass
out = {}
w.say_score(); app.processEvents()
out["off_msg"] = w.sb.currentMessage()
w.cfg["announce_enabled"] = True
fs = Fake(); w.announcer.speaker = fs
w.show(); app.processEvents()
def wait(sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.02)
wait(0.4)
w._updating = True; w.cb_band.setCurrentText("15"); w._updating = False; wait(0.4)
out["startup_quiet"] = list(fs.said)                # Fenster gerade erst da: keine Bandansage
w.announcer.quiet(0)
w.ed_call.setText("JA1ABC"); w.update_check(); wait(1.0)
out["typed"] = list(fs.said)
w.ed_exch.setText("25"); w.log_qso(); wait(0.3)
w.ed_call.setText("JA1ABC"); w.update_check(); wait(1.0)
w.say_call(); w.say_last_qso(); w.say_score(); w.say_time()
w._updating = True; w.cb_band.setCurrentText("40"); w._updating = False; wait(0.5)
w.sb.showMessage("Achtung Test", 5000, "warn")
w.say_again()
out["said"] = fs.said
d = SettingsDialog(dict(w.cfg), w, start="announce")
pg = d.announce_page
pg.events["dupe"].setChecked(False); pg.spelling.setCurrentIndex(1)
d.accept()
out["cfg"] = {k: d.cfg[k] for k in ("announce_enabled", "announce_spelling", "announce_events")}
print("OUT" + json.dumps(out))
w.close()
'''


def test_main_window_announcements(tmp_path):
    here = Path(__file__).parent
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    (data / "gogoham").mkdir(parents=True)
    (cfg / "gogoham").mkdir(parents=True)
    logs.mkdir()
    shutil.copy(here / "cty_sample.dat", data / "gogoham" / "cty.dat")
    (cfg / "gogoham" / "config.json").write_text(json.dumps({
        "rig_enabled": False, "wsjtx_enabled": False, "livescore_enabled": False,
        "rules_auto_update": False, "last_log": "", "language": "de"}))
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(GUI_SCRIPT), str(here.parent),
                        str(logs)], capture_output=True, text=True, env=env, timeout=60)
    lines = [ln[3:] for ln in r.stdout.splitlines() if ln.startswith("OUT")]
    assert lines, r.stderr[-2000:]
    o = json.loads(lines[-1])
    assert "Ansagen sind aus" in o["off_msg"]
    assert o["startup_quiet"] == []
    assert o["typed"] == ["Neuer Multi"]
    said = o["said"]
    assert "Geloggt: J A 1 A B C" in said
    assert "Dupe" in said
    assert any(s.startswith("J A 1 A B C, Dupe auf") for s in said)
    assert any(s.startswith("Letztes QSO: J A 1 A B C") for s in said)
    assert any(s.endswith("Punkte, 1 QSOs") for s in said)
    assert any(s.endswith("UTC") or "Contest" in s for s in said)
    assert "40 Meter" in said
    assert said[-2:] == ["Achtung Test", "Achtung Test"]          # Warnung + Alt+6
    assert o["cfg"]["announce_spelling"] == "phonetic"
    assert o["cfg"]["announce_events"]["dupe"] is False


# ------------------------------------------------------------ 0.8.26.1: speech-dispatcher per Klick
def test_install_command_per_distribution():
    have = lambda *names: (lambda exe: f"/usr/bin/{exe}" if exe in names else None)
    assert speech.install_command(have("pacman", "pkexec")) == [
        "pkexec", "/bin/sh", "-c", "pacman -S --needed --noconfirm speech-dispatcher espeak-ng"]
    apt = speech.install_command(have("apt-get", "pkexec"))[-1]
    assert apt.startswith("apt-get update && ") and "speech-dispatcher-espeak-ng" in apt
    assert "dnf install -y" in speech.install_command(have("dnf", "pkexec"))[-1]
    assert "zypper" in speech.install_command(have("zypper", "pkexec"))[-1]
    assert speech.install_command(have("pacman")) is None             # ohne pkexec
    assert speech.install_command(have("pkexec")) is None             # unbekannte Distribution
    assert "sudo pacman -S" in speech.manual_commands()


INSTALL_SCRIPT = r'''
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import speech
from gogoham.gui.main_window import MainWindow
from gogoham.gui.dialogs import SettingsDialog
MainWindow._welcome = lambda self: None
MainWindow._ask_scp = lambda self, *a, **k: None
state = {"installed": False}
speech.speechd_ok = lambda: state["installed"]
speech.install_command = lambda: ["/bin/sh", "-c", sys.argv[2]]
w = MainWindow()
d = SettingsDialog(w.cfg, w, start="data", actions={"speechd": w.install_speechd})
page = d.pages[list(SettingsDialog.TABS).index("data")][2]
out = {"before": page.speechd_btn.text(), "ann_btn": not d.announce_page.install_btn.isHidden()}
results = []
def wait():
    end = time.monotonic() + 5
    while w._speechd_proc is not None and time.monotonic() < end:
        app.processEvents(); time.sleep(0.02)
    app.processEvents()
if sys.argv[2] == "exit 0":
    state["installed"] = True                # „Paket ist danach da“
page.speechd_btn.click(); out["during"] = page.speechd_btn.text(); wait()
out["after"] = page.speechd_btn.text(); out["enabled"] = page.speechd_btn.isEnabled()
out["msg"] = w.sb.currentMessage()
print("OUT" + json.dumps(out))
w.close()
'''


def _run_install(tmp_path, script):
    here = Path(__file__).parent
    data, cfg = tmp_path / "data", tmp_path / "cfg"
    (data / "gogoham").mkdir(parents=True)
    (cfg / "gogoham").mkdir(parents=True)
    shutil.copy(here / "cty_sample.dat", data / "gogoham" / "cty.dat")
    (cfg / "gogoham" / "config.json").write_text(json.dumps({
        "rig_enabled": False, "wsjtx_enabled": False, "livescore_enabled": False,
        "rules_auto_update": False, "last_log": "", "language": "de"}))
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(INSTALL_SCRIPT), str(here.parent),
                        script], capture_output=True, text=True, env=env, timeout=60)
    lines = [ln[3:] for ln in r.stdout.splitlines() if ln.startswith("OUT")]
    assert lines, r.stderr[-2000:]
    return json.loads(lines[-1])


def test_install_button_success(tmp_path):
    o = _run_install(tmp_path, "exit 0")
    assert "installieren" in o["before"] and o["ann_btn"]
    assert "Installiere" in o["during"]
    assert "ist installiert" in o["after"] and not o["enabled"]
    assert o["msg"].startswith("speech-dispatcher ist installiert")


def test_install_button_failure_and_cancel(tmp_path):
    o = _run_install(tmp_path, "echo 'Ziel nicht gefunden: speech-dispatcher' >&2; exit 1")
    assert "installieren" in o["after"] and o["enabled"]
    assert "ließ sich nicht installieren: Ziel nicht gefunden" in o["msg"]
    o = _run_install(tmp_path / "b", "exit 126")
    assert o["msg"] == "Abgebrochen – kein Passwort eingegeben."
