"""0.10.21: Bereich „Entwicklung“ (Passwort, versteckt) – das freie Log nur nach Freischalten."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from gogoham import devmode

HERE = Path(__file__).parent


def test_password_hash():
    h = devmode.make_hash("geheim", rounds=1000)
    assert h.startswith("pbkdf2_sha256$1000$") and "geheim" not in h
    assert devmode.check("geheim", h) and not devmode.check("Geheim", h)
    assert not devmode.check("geheim", "") and not devmode.check("x", "kaputt$1$zz$00")
    assert devmode.make_hash("geheim", rounds=1000) != h               # eigenes Salz je Aufruf
    assert not devmode.available("") and devmode.available(h)
    devmode.lock()
    assert not devmode.unlock("falsch", h) and not devmode.is_unlocked()
    assert devmode.unlock("geheim", h) and devmode.is_unlocked()
    devmode.lock()
    assert not devmode.is_unlocked()


def test_enabled():
    assert not devmode.enabled("free_log", {})
    assert devmode.enabled("free_log", {"dev_features": {"free_log": True}})
    assert [k for k, _n, _i in devmode.features()] == ["free_log"]


SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham import devmode
devmode.PASSWORD_HASH = devmode.make_hash("geheim", rounds=1000)
from gogoham.gui.dialogs import LogSettingsDialog, SettingsDialog
from gogoham.db import DEFAULT_META
def contests(meta=None, new=True):
    d = LogSettingsDialog(dict(DEFAULT_META, **(meta or {})), new_log=new)
    if new:
        d._filter_contests("frei")
        free = [d.contest_list.item(i).data(256) for i in range(d.contest_list.count())]
        d._filter_contests("")
        return [d.contest.findData("freies-log") >= 0, free, d.count_label.text()]
    return [d.contest.currentData()]
out = {"off": contests(), "existing": contests({"contest": "freies-log"}, new=False)}
from gogoham import config as cfgmod
cfg = cfgmod.load()
s = SettingsDialog(cfg, check_apps=False)
titles = lambda: [s.nav.item(i).text() for i in range(s.nav.count())]
out["hidden"] = "Entwicklung" in titles()
answers = ["falsch", None, "geheim"]
s.ask_password = lambda: answers.pop(0)
told = []
from PySide6.QtWidgets import QMessageBox
QMessageBox.warning = staticmethod(lambda *a, **k: told.append(a[2]))
s.unlock_dev(); out["wrong"] = ["Entwicklung" in titles(), told[-1], devmode.is_unlocked()]
s.unlock_dev(); out["cancel"] = "Entwicklung" in titles()
s.unlock_dev(); out["right"] = ["Entwicklung" in titles(), s.current_key(), devmode.is_unlocked()]
page = [p for p in s.pages if p[0] == "dev"][0][2]
page.boxes["free_log"].setChecked(True)
s.accept()
out["cfg"] = cfg.get("dev_features")
cfgmod.save(cfg)
out["on"] = contests()
s2 = SettingsDialog(cfg, check_apps=False)                 # bis zum Ende offen
out["still_open"] = "Entwicklung" in [s2.nav.item(i).text() for i in range(s2.nav.count())]
page = [p for p in s2.pages if p[0] == "dev"][0][2]
page.boxes["free_log"].setChecked(False); s2.accept()
out["cfg_off"] = "dev_features" in cfg
devmode.PASSWORD_HASH = ""; devmode.lock()
s3 = SettingsDialog(cfg, check_apps=False); s3.ask_password = lambda: 1 / 0
s3.unlock_dev()                                           # ohne Passwort-Prüfsumme: nichts
out["no_hash"] = "Entwicklung" in [s3.nav.item(i).text() for i in range(s3.nav.count())]
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def test_dev_settings_and_free_log(tmp_path):
    env = {"QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin",
           "XDG_CONFIG_HOME": str(tmp_path / "xdg"), "XDG_DATA_HOME": str(tmp_path / "d")}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent)],
                       capture_output=True, text=True, env=env, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    in_combo, free_hits, count = o["off"]
    assert not in_combo and free_hits == [] and "von" not in count       # ausgeblendet
    assert o["existing"] == ["freies-log"]                               # altes Log: geht auf
    assert not o["hidden"]
    assert o["wrong"] == [False, "Falsches Passwort.", False]
    assert not o["cancel"]
    assert o["right"] == [True, "dev", True]
    assert o["cfg"] == {"free_log": True}
    in_combo, free_hits, _count = o["on"]
    assert in_combo and free_hits == ["freies-log"]
    assert o["still_open"] and o["cfg_off"] is False
    assert not o["no_hash"]
