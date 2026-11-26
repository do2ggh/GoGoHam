"""0.8.28.3: „Alles herunterladen“ – alle Schritte nacheinander, eine Zusammenfassung,
speech-dispatcher zuletzt. Keine echten Downloads: alle Quellen sind Attrappen."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).parent

SCRIPT = r'''
import json, sys, time, shutil
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod, rulesupdate, scp, dok, flags, mapimages, piper, speech
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui import main_window, dialogs
calls = []
class R:
    offline = False; errors = []; changed = False
    def summary(self): return "Contest-Regeln sind aktuell"
rulesupdate.check_and_download = lambda: calls.append("rules") or R()
def cdl(*a, **k):
    calls.append("cty"); p = Path(sys.argv[4]) / "cty.dat"; shutil.copy(sys.argv[3], p); return p
cty.download = cdl
def sdl(*a, **k):
    calls.append("scp"); p = Path(sys.argv[4]) / "MASTER.SCP"; p.write_text("DL1ABC\nK1AR\n"); return p
scp.download = sdl
def ddl(*a, **k):
    calls.append("doks"); raise OSError("keine Verbindung")
dok.download = ddl
flags.missing_codes = lambda: calls.append("flags") or []
def mrun(self): calls.append("map-" + self.what)
mapimages.MapDownloader.run = mrun
def prun(self): calls.append("piper-" + self.what)
piper.PiperDownloader.run = prun
speech.speechd_ok = lambda: False
M = main_window.MainWindow
M._welcome = lambda self: None
M._ask_scp = lambda self, *a, **k: None
M._ask_flags = lambda self, *a, **k: None
M._start_daily_update = lambda self, wait=10.0: None
M.install_speechd = lambda self, done=None: (calls.append("speechd"), done(True))
shown = []
QMessageBox.information = staticmethod(lambda *a, **k: shown.append(a[2]))
p = Path(sys.argv[2]) / "cqww-cw.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="cqww-cw", mycall="DL9ZZZ")); db.close()
cfg = cfgmod.load(); cfg.update(rig_enabled=False, wsjtx_enabled=False, last_log=str(p)); cfgmod.save(cfg)
w = M()
page = dialogs.DataPage(w.cfg, actions={"all": w.download_all})
out = {"box": [page.all_btn.text(), page.all_voices.text(), page.all_voices.isChecked()]}
page.all_voices.setChecked(True)
page.all_btn.click()
out["busy"] = [not page.all_btn.isEnabled(), w.download_all(False, print, print)]
end = time.monotonic() + 20
while time.monotonic() < end and not shown:
    app.processEvents(); time.sleep(0.02)
out["calls"] = calls
out["summary"] = shown[0].splitlines() if shown else []
out["status"] = page.all_status.text()
out["scp"] = len(w.scp) if w.scp else 0
out["after"] = page.all_btn.isEnabled()
w.close()
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def test_download_all(tmp_path):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    for d in (data / "gogoham", cfg / "gogoham", logs):
        d.mkdir(parents=True, exist_ok=True)
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(logs), str(HERE / "cty_sample.dat"), str(data / "gogoham")],
                       capture_output=True, text=True, env=env, timeout=90)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["box"][0] == "Alles herunterladen / aktualisieren"
    assert o["box"][1].startswith("auch natürliche Stimmen (ca. ") and o["box"][2] is False
    assert o["busy"] == [True, False]                   # zweimal starten geht nicht
    assert o["calls"] == ["rules", "cty", "scp", "doks", "flags", "map-nasa", "map-relief",
                          "piper-speech", "piper-practice", "speechd"]   # Passwort zuletzt
    s = o["summary"]
    assert len(s) == 10 and s[0].startswith("✓ Contest-Regeln")
    assert any(x.startswith("✗ DOK-Liste: keine Verbindung") for x in s)   # Fehler einzeln
    assert "✓ speech-dispatcher: installiert" in s
    assert o["status"] == "Fertig: 9 von 10 erledigt" and o["scp"] == 2 and o["after"] is True
