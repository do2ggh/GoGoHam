"""0.8.12.9/0.10.4: Menüleiste (Datei · Log & Contest · Station · Fenster · Hilfe) und
Einstellungen mit Liste links („Sprachaufnahmen“ unter „Ton & Ansagen“).
Läuft mit echtem Qt (offscreen); Tongeräte sind Platzhalter, gesendet wird nichts."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).parent

SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[2])))
from gogoham import config as cfgmod
from gogoham.gui import audio
audio.available = lambda: ""
audio.inputs = lambda: [("mic1", "Mikrofon")]
audio.outputs = lambda: [("hp", "Kopfhörer"), ("codec", "PCM2901 Audio Codec")]
cfg = cfgmod.load()
cfg.update(rig_enabled=False, wsjtx_enabled=False)
cfgmod.save(cfg)
from gogoham.gui import main_window
main_window.MainWindow._welcome = lambda self: None
main_window.MainWindow._ask_scp = lambda self: None
w = main_window.MainWindow()
out = {}
menus = {}
for a in w.menuBar().actions():
    m = a.menu()
    if m is None:                        # Knopf direkt in der Menüleiste (Kontakt, 0.8.18.3)
        continue
    menus[a.text()] = [(x.menu().title() if x.menu() else x.text()) for x in m.actions()
                       if not x.isSeparator()]
out["bar"] = [a.text() for a in w.menuBar().actions()]
out["menus"] = menus
def _all(menu):
    for x in menu.actions():
        if x.isSeparator():
            continue
        if x.menu():
            yield from _all(x.menu())
        else:
            yield x
out["keys"] = {x.text(): x.shortcut().toString() for a in w.menuBar().actions()
               if a.menu() for x in _all(a.menu())}
out["sub"] = {x.menu().title(): [y.text() for y in x.menu().actions() if not y.isSeparator()]
              for a in w.menuBar().actions() if a.menu() for x in a.menu().actions()
              if x.menu() and x.menu().title() not in ("Funkgerät-Profil",
                                                       "Digitalprogramm starten")}

from gogoham.gui.dialogs import SettingsDialog
from gogoham.gui.voice_dialog import VoicePage
d = SettingsDialog(w.cfg, w, start="voice", mycall="DO2GGH")
out["tab"] = d.current_title()
out["nav"] = [d.nav.item(i).text() for i in range(d.nav.count())]
vp, cb = d.voice_page, d.macro_page.cb_source
out["ok"] = vp.ok
# Quelle der SSB-Ansagen nur noch auf dem Reiter Funktionstasten; Sprachaufnahmen folgt
out["no_check"] = hasattr(vp, "chk_use")
cb.setCurrentIndex(cb.findData("gogoham"))
out["follows"] = [vp.source, cfgmod.load()["voice_source"]]
cb.setCurrentIndex(cb.findData("rig"))
out["follows"].append(vp.source)
# auf einem anderen Reiter geändert, dann Klang verstellt: nur „voice_*“ landet auf der Platte
d.pages[list(SettingsDialog.TABS).index("display")][2].theme.setCurrentIndex(2)
w.cfg["theme_probe"] = "nicht speichern"
vp.sliders["bass"][0].setValue(-7)
disk = cfgmod.load()
out["only_voice"] = [disk["voice_tone"]["bass"], "theme_probe" in disk]
del w.cfg["theme_probe"]
d.reject()
out["after_cancel"] = [cfgmod.load()["voice_tone"]["bass"], vp.tick.isActive()]
# 0.8.13: Meldungen vom Funkgerät in der Hinweiszeile unten; Fenster und Rufzeichenfeld
# bleiben gleich breit, das Meldefeld beim Rufzeichen bleibt leer
w.resize(900, 700); w.show(); app.processEvents()
before = [w.width(), w.ed_call.width(), w.lbl_status.height(), w.sb.hint.height()]
from gogoham.rig import command_notice_long
w._show_rig_notice(command_notice_long("send_voice_mem", (3,)))
app.processEvents()
w.statusBar().showMessage("Das Funkgerät hat " * 30, 5000, level="error")   # viel zu lang
app.processEvents()
after = [w.width(), w.ed_call.width(), w.lbl_status.height(), w.sb.hint.height()]
out["status"] = [before == after, w.lbl_status.text() == "", "#c62828" in w.sb.hint.styleSheet()]
# zu lange Meldung beim Rufzeichen: kleiner, Fenster bleibt gleich
w._set_status("Zählt nicht: " + "sehr lange Begründung " * 8, "#e08a00"); app.processEvents()
out["long"] = [w.lbl_status.font().pointSize() < w._status_big.pointSize(),
               [w.width(), w.ed_call.width()] == after[:2]]
w._set_status("DUPE", "#c62828"); app.processEvents()
out["short"] = [w.lbl_status.font().pointSize() == w._status_big.pointSize(),
                w.lbl_status.toolTip()]
# Hinweise zum Rufzeichen erscheinen unten, sobald keine Meldung läuft
w.sb.clearMessage(); w.sb.set_notes("⚠ Test-Hinweis")
out["notes"] = [w.sb.hint.text(), "#e08a00" in w.sb.hint.styleSheet()]
w.sb.showMessage("QSY", 3000)
out["msg_over_notes"] = w.sb.hint.text()
w.sb.clearMessage()
out["notes_back"] = w.sb.hint.text()
# Funkwetter: Platzhalter, dann Werte mit Farbe je Band
from gogoham.spaceweather import SpaceWeather
out["wx_wait"] = w.sb.weather.text()
w._sw = SpaceWeather(sfi=111, a=10, k=1, sfi_time="2026-11-04 17:00", k_time="2026-11-04 15:00",
                     a_date="2026-11-04")
w._update_weather()
out["wx"] = [w.sb.weather.text(), w.sb.weather.toolTip()]
w.close()
print("RESULT " + json.dumps(out))
'''


def test_log_menu_and_voice_tab(tmp_path):
    data, cfg = tmp_path / "data", tmp_path / "cfg"
    (cfg / "gogoham").mkdir(parents=True)
    (data / "gogoham").mkdir(parents=True)
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(HERE / "cty_sample.dat")],
                       capture_output=True, text=True, env=env, timeout=90)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    # 0.10.4: aufgeräumte Menüleiste
    assert o["bar"] == ["&Datei", "&Log && Contest", "&Station", "&Fenster", "&Hilfe",
                        "Kontakt zu DO2GGH"]
    assert o["menus"]["&Datei"] == ["Übungsmodus …", "Einstellungen …", "Beenden"]
    assert o["menus"]["&Log && Contest"] == [
        "Contest-Kalender …", "Neues Contest-Log …", "Log öffnen …", "Log-Ordner öffnen …",
        "Log-Einstellungen …",
        "Log prüfen …", "Übersicht (Multis, Rate) …", "Call-History …", "QTC", "Exportieren",
        "Sicherung wiederherstellen …"]
    assert o["menus"]["&Station"] == ["Funkgerät-Profil", "Operator wechseln …",
                                      "Uhrzeit prüfen …", "Digitalprogramm starten",
                                      "Stationslog …",
                                      "Nachricht an andere Plätze …"]
    assert o["menus"]["&Fenster"] == ["Bandmap", "Super Check Partial", "Karte (Grayline)",
                                      "Baken (NCDXF/IARU)", "Bandöffnung (Vorschau)", "Rotor",
                                      "Station (Plätze und Nachrichten)"]
    assert o["menus"]["&Hilfe"] == ["Handbuch …", "Tastenkürzel", "Nach neuer Version suchen …",
                                    "Fehlerbericht erstellen …",
                                    "☕ Spendier DO2GGH einen Kaffee", "Über GoGoHam …"]
    assert o["sub"] == {"QTC": ["QTC empfangen/geben (WAE) …", "QTC-Liste …"],
                        "Exportieren": ["Log exportieren …", "Cabrillo exportieren …",
                                        "ADIF exportieren …"]}
    k = o["keys"]
    assert (k["Neues Contest-Log …"], k["Log öffnen …"], k["Log-Einstellungen …"],
            k["Log prüfen …"], k["QTC empfangen/geben (WAE) …"], k["Log exportieren …"]) == \
        ("Ctrl+N", "Ctrl+O", "Ctrl+L", "Ctrl+P", "Ctrl+Q", "Ctrl+E")
    assert not any("Sprachaufnahmen" in t for t in k)
    assert (k["Contest-Kalender …"], k["Übersicht (Multis, Rate) …"], k["Einstellungen …"],
            k["Nachricht an andere Plätze …"], k["Tastenkürzel"]) == \
        ("Ctrl+K", "Ctrl+M", "Ctrl+,", "Ctrl+T", "Ctrl+H")
    assert o["tab"] == "Ton & Ansagen → Sprachaufnahmen" and o["ok"] is True
    assert o["nav"] == ["Operator", "Funkgerät", "Rotor", "GPS", "Funktionstasten", "Daten & Updates",
                        "Ton & Ansagen", "Online-Dienste", "Zusatzprogramme", "Darstellung"]
    assert o["no_check"] is False
    assert o["follows"] == ["gogoham", "rig", "rig"]   # erst mit OK gespeichert
    assert o["only_voice"] == [-7, False]
    assert o["after_cancel"] == [-7, False]
    assert o["status"] == [True, True, True], o["status"]
    assert o["long"] == [True, True]
    assert o["short"] == [True, ""]
    assert o["notes"] == ["⚠ Test-Hinweis", True]
    assert o["msg_over_notes"] == "QSY" and o["notes_back"] == "⚠ Test-Hinweis"
    assert "Funkwetter" in o["wx_wait"]
    html, tip = o["wx"]
    assert "SFI&nbsp;111" in html and "A&nbsp;10" in html and "K&nbsp;1" in html
    assert "#1b8a3a" in html and "#f2c200" in html            # K 1 grün, A 10 gelb
    assert "NOAA" in tip and "17:00" in tip          # Aufnahme-Einstellung bleibt, Takt aus
