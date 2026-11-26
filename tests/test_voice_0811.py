"""0.8.11: Sprachausgabe mit eigenen Aufnahmen – Zusammenbau, Bearbeitung und der Sendeablauf
im echten Qt-Fenster (offscreen). Funkgerät und Tongerät sind Platzhalter, die nur mitschreiben."""

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

from gogoham import voice

HERE = Path(__file__).parent


def tone(sec=0.4, amp=0.3, silence=0.3, f=440.0):
    t = np.arange(int(sec * voice.RATE)) / voice.RATE
    s = np.zeros(int(silence * voice.RATE), np.float32)
    return np.concatenate([s, (amp * np.sin(2 * np.pi * f * t)).astype(np.float32), s])


# ------------------------------------------------------------ Zusammenbau
def test_plan_spells_and_uses_phrases():
    have = set("DL1ABC590") | {"CQ", "TU"}
    p = voice.plan("{CALL} {RST} {EXCH}", {"CALL": "DL1ABC", "RST": "59", "EXCH": "001"}, have)
    assert [x for x in p.parts if isinstance(x, str)] == list("DL1ABC590" "01")[:6] + \
        ["5", "9", "0", "0", "1"]
    assert not p.missing and p.text == "DL1ABC 59 001"
    assert voice.GAP_WORD in p.parts and voice.GAP_LETTER in p.parts
    assert isinstance(p.parts[0], str) and isinstance(p.parts[-1], str)


def test_mycall_recording_and_slash():
    p = voice.plan("[CQ] {MYCALL}", {"MYCALL": "DO2GGH/P"}, {"CQ", "MYCALL"})
    assert [x for x in p.parts if isinstance(x, str)] == ["CQ", "MYCALL"]
    assert p.text == "CQ DO2GGH/P"
    p = voice.plan("{MYCALL}", {"MYCALL": "DO2GGH/P"}, set("DO2GH"))
    assert p.missing == [voice.SLASH, "P"]
    assert "/" in voice.missing_text(p.missing) and "P (Papa)" in voice.missing_text(p.missing)


def test_missing_listed_once_and_punctuation_skipped():
    p = voice.plan("[AGN] ?? {CALL}", {"CALL": "OK1AA"}, {"AGN"})
    assert p.missing == ["O", "K", "1", "A"]
    assert "?" not in p.text
    assert voice.plan("", {}, set()).empty
    assert voice.plan("{CALL}", {"CALL": ""}, set()).empty


def test_default_texts_cover_all_keys():
    assert sorted(voice.DEFAULT_SSB_TEXT) == [f"F{i}" for i in range(1, 9)]
    ids = {i for i, _n, _h in voice.all_items()}
    assert set(voice.PHRASE_IDS) <= ids and set("AZ09") <= ids and voice.SLASH in ids


# ------------------------------------------------------------- Bearbeitung
def test_trim_removes_silence():
    x = tone(sec=0.5, silence=0.6)
    y = voice.trim_silence(x)
    assert 0.5 <= len(y) / voice.RATE <= 0.62
    assert len(voice.trim_silence(np.zeros(48000, np.float32))) == 0


def test_all_equally_loud():
    a = voice.prepare_clip(tone(amp=0.05))
    b = voice.prepare_clip(tone(amp=0.6, f=800))
    ra, rb = np.sqrt((a ** 2).mean()), np.sqrt((b ** 2).mean())
    assert abs(20 * np.log10(ra / rb)) < 1.0
    assert np.abs(a).max() <= 0.9 and np.abs(b).max() <= 0.9


def test_tone_presets_and_send_level():
    x = voice.prepare_clip(tone())
    n = voice.apply_tone(x, {"preset": "normal"})
    c = voice.apply_tone(x, dict(voice.PRESETS["contest"], preset="contest"))
    assert len(n) == len(c) == len(x)
    assert np.abs(c).max() <= 1.0
    quiet = voice.apply_tone(x, {"preset": "normal", "volume": 50})
    assert np.abs(quiet).max() < np.abs(n).max() * 0.6
    half = voice.apply_send_level(n, 50)
    assert np.allclose(half, n * 0.5, atol=1e-6)
    # Bässe absenken nimmt tiefe Töne wirklich weg
    low = voice.prepare_clip(tone(f=100))
    cut = voice.apply_tone(low, {"bass": -12})
    assert np.abs(voice.equalize(low, -12, 0, 0)).max() < np.abs(low).max() * 0.5
    assert len(cut) == len(low)


def test_wav_roundtrip_and_cache(tmp_path):
    x = tone()
    voice.save_wav(voice.clip_path("A", tmp_path), x)
    y = voice.load_wav(voice.clip_path("A", tmp_path))
    assert len(y) == len(x) and np.abs(y - x).max() < 1e-3
    cache = voice.ClipCache(tmp_path)
    assert cache.have() == {"A"}
    assert cache.get("A") is not None and cache.get("B") is None
    out = voice.render(voice.plan("AA", {}, cache.have()), cache, None)
    one = len(cache.get("A"))
    assert len(out) == 2 * one + int(voice.GAP_LETTER * voice.RATE)


def test_resample_and_mono():
    st = np.repeat(tone(), 2)                         # Stereo, beide Kanäle gleich
    m = voice.to_mono(st, 2, 44100)
    assert abs(len(m) - len(tone()) * 48000 / 44100) <= 1


# ------------------------------------------------- Sendeablauf im Fenster
SCRIPT = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui import main_window as mw
from gogoham.gui.main_window import MainWindow
from gogoham.rig import RigState
MainWindow._welcome = lambda self: None
MainWindow._ask_scp = lambda self, *a, **k: None
w = MainWindow()
p = Path(sys.argv[2]) / "wpx.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="wpx-ssb", mycall="DO2GGH")); db.close()
w.open_log(str(p))
sent = []
refuse = {"ptt": False}
class Rig:
    def __init__(self): self.state = RigState(connected=True)
    def submit(self, *a):
        sent.append(list(a))
        if a[0] == "ptt":
            self.state.ptt_id += 1
            self.state.ptt = bool(a[1]) and not refuse["ptt"]
    def snapshot(self): return RigState(**self.state.__dict__)
    def stop(self): pass
played = []
class Player:
    def __init__(self): self.error = ""; self.on = False
    def play(self, samples, dev):
        played.append(len(samples)); self.on = True; return True
    def stop(self, notify=True):
        was = self.on; self.on = False
        if was and notify: w._voice_finished()
    def finish(self): self.stop()
w.rig = Rig(); w._rig_connected = lambda: True; w.rig_caps = None
w._voice_device = lambda: object()
player = Player()
w._make_voice_player = lambda: player
from gogoham import config as cfgmod
w.cfg["voice_source"] = "gogoham"; w.cfg["voice_rig_out"] = "rig-codec"
w._updating = True; w.cb_mode.setCurrentText("USB"); w._updating = False
w._update_macro_buttons()
w.show(); app.processEvents()
import time
def settle():
    t = time.monotonic() + 1.5
    while time.monotonic() < t and w._vs == "ptt":
        app.processEvents(); time.sleep(0.01)
out = {}
out["labels"] = [b.text() for b in w.fbuttons]
# 1) F1: PTT an, warten auf Bestätigung, abspielen, am Ende PTT aus
sent.clear(); w.run_macro(1, manual=True); settle()
out["f1"] = [list(sent), len(played), w._vs, w.lbl_sending.text()]
player.finish(); app.processEvents()
out["f1_end"] = [list(sent), w._vs, w.lbl_sending.text()]
# 2) F2 mit Rufzeichen, bei dem eine Aufnahme fehlt (Q): nichts senden
sent.clear(); played.clear()
w.ed_call.setText("DQ1ABC"); w.run_macro(2, manual=True); settle()
out["missing"] = [list(sent), len(played), w.sb.currentMessage()]
# 3) Esc während der Ansage: sofort PTT aus
w.ed_call.setText("DL1ABC"); sent.clear()
w.run_macro(2, manual=True); settle()
w.escape_pressed(); app.processEvents()
out["esc"] = [list(sent), w._vs, player.on]
# 4) Funkgerät lehnt PTT ab: nichts abspielen
refuse["ptt"] = True; sent.clear(); played.clear()
w.run_macro(3, manual=True); settle()
out["refused"] = [list(sent), len(played), w._vs]
refuse["ptt"] = False
# 5) ESM Run in SSB: Rufzeichen + Enter spielt F2 (Call + Austausch)
w.cfg["esm_enabled"] = True; w.cfg["esm_mode"] = "run"
w.ed_call.setText("DL1ABC"); w.update_check(); w.ed_call.setFocus(); app.processEvents()
sent.clear(); played.clear(); w.enter_pressed(); settle()
out["esm_call"] = [list(sent), len(played), w._vs_text]
player.finish(); app.processEvents()
# 6) Soundkarte nicht gewählt: Hinweis, nichts senden
w.cfg["voice_rig_out"] = ""; sent.clear()
w.run_macro(1, manual=True); settle()
out["no_dev"] = [list(sent), w.sb.currentMessage()]
w.cfg["voice_rig_out"] = "rig-codec"
# 7) Sprachspeicher des Funkgeräts weiterhin möglich
w.cfg["voice_source"] = "rig"; sent.clear()
w.run_macro(1, manual=True)
out["rig_mem"] = list(sent)
print("RESULT " + json.dumps(out))
w.close()
'''


def _clip_dir(data: Path) -> Path:
    d = data / "gogoham" / "voice"
    d.mkdir(parents=True)
    for item in list("DL1ABCO2GH0123456789") + ["CQ", "TU"]:
        voice.save_wav(d / f"{item}.wav", tone(sec=0.15, silence=0.05))
    return d


def test_send_flow_with_own_voice(tmp_path):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    (data / "gogoham").mkdir(parents=True)
    (cfg / "gogoham").mkdir(parents=True)
    logs.mkdir()
    shutil.copy(HERE / "cty_sample.dat", data / "gogoham" / "cty.dat")
    _clip_dir(data)
    (cfg / "gogoham" / "config.json").write_text(json.dumps({
        "rig_enabled": False, "wsjtx_enabled": False, "livescore_enabled": False,
        "rules_auto_update": False, "daily_update": False, "last_log": "", "language": "de"}))
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(logs)], capture_output=True, text=True, env=env, timeout=90)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["labels"][4:] == ["F5 Sein Call", "F6 Nochmal", "F7 Call?", "F8 Nr?"]
    f1_sent, f1_played, f1_state, f1_label = o["f1"]
    assert f1_sent == [["ptt", True]] and f1_played == 1 and f1_state == "play"
    assert "CQ DO2GGH DO2GGH" in f1_label
    assert o["f1_end"][0] == [["ptt", True], ["ptt", False]] and o["f1_end"][1] == "idle"
    assert o["f1_end"][2] == ""
    m_sent, m_played, m_status = o["missing"]
    assert m_sent == [] and m_played == 0 and "Q (Quebec)" in m_status
    e_sent, e_state, e_on = o["esc"]
    assert e_sent[0] == ["ptt", True] and e_sent[-1] == ["ptt", False]
    assert e_state == "idle" and e_on is False
    r_sent, r_played, r_state = o["refused"]
    assert r_sent == [["ptt", True]] and r_played == 0 and r_state == "idle"
    es_sent, es_played, es_text = o["esm_call"]
    assert es_sent == [["ptt", True]] and es_played == 1 and es_text.startswith("DL1ABC 59")
    assert o["no_dev"][0] == [] and "Soundkarte" in o["no_dev"][1]
    assert o["rig_mem"] == [["send_voice_mem", 1]]


DIALOG = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
from gogoham import config as cfgmod
from gogoham.gui import audio, voice_dialog
audio.available = lambda: ""
audio.inputs = lambda: [("mic1", "Razer Seiren Mini")]
audio.outputs = lambda: [("hp", "Kopfhörer"), ("codec", "PCM2901 Audio Codec (Funkgerät, z. B. IC-7300?)")]
warned = []
QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2]))
class Dev:
    def __init__(self, i, d): self._i, self._d = i, d
    def id(self): return self._i.encode()
    def description(self): return self._d
cfg = cfgmod.load()
cfg["voice_rig_out"] = "codec"
d = voice_dialog.VoicePage(cfg, "DO2GGH")
out = {"rows": d.tbl.rowCount(), "state": d.lbl_state.text(),
       "rig": d.cb_rig.currentData(), "mic": d.cb_mic.count()}
d.cb_preset.setCurrentIndex(d.cb_preset.findData("strong"))
out["strong"] = [d.sliders[k][0].value() for k in ("bass", "lowmid", "mid", "treble")]
d.cb_preset.setCurrentIndex(d.cb_preset.findData("contest"))
out["contest"] = [d.sliders[k][0].value() for k in ("bass", "mid", "treble")]
out["tone"] = dict(cfg["voice_tone"])
out["presets"] = [d.cb_preset.itemData(i) for i in range(d.cb_preset.count())]
# Eigene Profile: Kräftig mit eigenen Werten speichern, umschalten, zurückholen
from PySide6.QtWidgets import QInputDialog
QInputDialog.getItem = staticmethod(lambda *a, **k: (a[3][0], True))
QInputDialog.getText = staticmethod(lambda *a, **k: ("Kräftig DO2GGH", True))
out["empty_enabled"] = d.cb_preset.model().item(d.cb_preset.findData("user1")).isEnabled()
d.cb_preset.setCurrentIndex(d.cb_preset.findData("strong"))
for k, v in (("bass", -8), ("lowmid", -5), ("mid", 1), ("treble", 8), ("volume", 90)):
    d.sliders[k][0].setValue(v)
d.save_profile()
out["after_save"] = [d.cb_preset.currentData(), d.cb_preset.currentText()]
d.cb_preset.setCurrentIndex(d.cb_preset.findData("contest"))
d.cb_preset.setCurrentIndex(d.cb_preset.findData("user1"))
out["restored"] = [d.sliders[k][0].value() for k in ("bass", "lowmid", "mid", "treble", "volume")]
saved = cfgmod.load()
out["saved"] = [saved["voice_profiles"][0], saved["voice_tone"]["preset"], saved["voice_tone"]["profile"]]
d.shutdown()
d = voice_dialog.VoicePage(cfgmod.load(), "DO2GGH")              # nach Neustart des Fensters
out["reopen"] = [d.cb_preset.currentData(), d.sliders["lowmid"][0].value()]
# ab 0.8.12.9 kein eigenes Häkchen mehr: die Quelle kommt vom Reiter Funktionstasten
saved_rig = d.cfg.get("voice_rig_out")
d.cfg["voice_rig_out"] = ""
d.set_source("gogoham")
out["source"] = [cfgmod.load()["voice_source"], "Soundkarte des Funkgeräts" in d.lbl_state.text()]
d.set_source("rig")
out["source"].append("Soundkarte des Funkgeräts" in d.lbl_state.text())
d.cfg["voice_rig_out"] = saved_rig
# Probehören über die Soundkarte des Funkgeräts wird verweigert
d._monitor = lambda: Dev("codec", "PCM2901 Audio Codec")
played = []
d.player.play = lambda s, dev, **k: played.append(len(s)) or True
d._play(__import__("numpy").zeros(100))
out["blocked"] = [len(played), len(warned)]
d._monitor = lambda: Dev("hp", "Kopfhörer")
d._play(__import__("numpy").zeros(100))
out["played"] = len(played)
# Pegelanzeige: springt sofort hoch, fällt zügig ab, Spitze bleibt als Zahl stehen
d.rec._src = object()
d._level(-12.0); d._draw_meter(); up = d.meter.value()
for _ in range(10): d._level(-50.0); d._draw_meter()        # 0,3 s leise
out["meter"] = [up, d.meter.value(), d.meter.format()]
d.rec._src = None
d.shutdown()
print("RESULT " + json.dumps(out))
'''


def test_voice_dialog(tmp_path):
    data, cfg = tmp_path / "data", tmp_path / "cfg"
    (cfg / "gogoham").mkdir(parents=True)
    _clip_dir(data)
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(DIALOG), str(HERE.parent)],
                       capture_output=True, text=True, env=env, timeout=60)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["rows"] == len(voice.all_items())
    assert "fehlen noch" in o["state"] and o["rig"] == "codec" and o["mic"] == 2
    assert o["contest"] == [-6, 3, 6] and o["tone"]["preset"] == "contest"
    assert o["strong"] == [-4, -4, 2, 5]
    assert o["presets"] == ["normal", "strong", "contest", "user1", "user2"]
    assert o["empty_enabled"] is False
    assert o["after_save"] == ["user1", "Eigenes Profil 1: Kräftig DO2GGH"]
    assert o["restored"] == [-8, -5, 1, 8, 90]
    prof, base, sel = o["saved"]
    assert prof == {"name": "Kräftig DO2GGH", "base": "strong", "bass": -8, "lowmid": -5,
                    "mid": 1, "treble": 8, "volume": 90}
    assert base == "strong" and sel == "user1"
    assert o["reopen"] == ["user1", -5]
    assert o["source"] == ["rig", True, False]       # nur Warnung, nichts gespeichert
    assert o["blocked"] == [0, 1] and o["played"] == 1
    up, later, fmt = o["meter"]
    assert up == -12 and -23 <= later <= -19 and "−12" not in fmt and "-12" in fmt


# ------------------------------------------- PTT im Funkgeräte-Teil (nachgebauter rigctld)
def _fake_rigctld(refuse_ptt=False):
    import socket
    import threading
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    log = []

    def handle(c):
        buf = b""
        with c:
            while True:
                try:
                    chunk = c.recv(1024)
                except OSError:
                    return
                if not chunk:
                    return
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    cmd = line.decode().strip()
                    log.append(cmd)
                    if cmd == "\\dump_state":
                        c.sendall(b"0\n3073\n")
                    elif cmd == "f":
                        c.sendall(b"14200000\n")
                    elif cmd == "m":
                        c.sendall(b"USB\n2400\n")
                    elif cmd.startswith("T "):
                        c.sendall(b"RPRT -11\n" if refuse_ptt else b"RPRT 0\n")
                    else:
                        c.sendall(b"RPRT 0\n")

    def serve():
        while True:
            try:
                c, _a = srv.accept()
            except OSError:
                return
            threading.Thread(target=handle, args=(c,), daemon=True).start()
    threading.Thread(target=serve, daemon=True).start()
    return srv, log


def _wait(cond, sec=3.0):
    import time
    end = time.monotonic() + sec
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_rig_ptt_confirmed_quickly_and_off_at_stop():
    import time
    from gogoham.rig import RigWorker
    srv, log = _fake_rigctld()
    w = RigWorker("127.0.0.1", srv.getsockname()[1], poll=2.0)   # langsame Abfrage
    w.start()
    try:
        assert _wait(lambda: w.snapshot().connected and "f" in log)
        time.sleep(0.1)
        t0 = time.monotonic()
        w.submit("ptt", True)
        assert _wait(lambda: w.snapshot().ptt)
        assert time.monotonic() - t0 < 0.5             # nicht bis zur nächsten Abfrage gewartet
        assert w.snapshot().ptt_id == 1 and "T 1" in log
    finally:
        w.stop()
        w.join(3)
        srv.close()
    assert log[-1] == "T 0"                            # beim Beenden nie im Senden stehen bleiben


def test_rig_ptt_refused():
    from gogoham.rig import RigWorker
    srv, log = _fake_rigctld(refuse_ptt=True)
    w = RigWorker("127.0.0.1", srv.getsockname()[1], poll=0.2)
    w.start()
    try:
        assert _wait(lambda: w.snapshot().connected)
        w.submit("ptt", True)
        assert _wait(lambda: w.snapshot().ptt_id == 1)
        st = w.snapshot()
        assert st.ptt is False and "Senden" in st.notice
    finally:
        w.stop()
        w.join(3)
        srv.close()


# ------------------------------------------------ 0.8.11.1: Stille besser abschneiden
def _speech_like(sec=0.5):
    t = np.arange(int(sec * voice.RATE)) / voice.RATE
    env = np.sin(np.pi * t / sec) ** 0.5
    return (0.05 * env * np.sin(2 * np.pi * 300 * t)).astype(np.float32)   # leise wie am Mikro


def test_trim_ignores_clicks_and_noise():
    rng = np.random.default_rng(1)
    noise = lambda s: (rng.standard_normal(int(s * voice.RATE)) * 10 ** (-62 / 20)).astype(np.float32)
    click = np.zeros(int(0.02 * voice.RATE), np.float32)
    click[:200] = 0.02                                   # Mausklick 4 ms, ca. −34 dB
    x = np.concatenate([click, noise(0.4), _speech_like(0.5), noise(0.3), click, noise(0.05)])
    y = voice.trim_silence(x)
    assert 0.48 <= len(y) / voice.RATE <= 0.62           # nur die Sprache (+ kurzer Rand)


def test_trim_keeps_short_sound_close_to_speech():
    """„Eight“: kurzes „t“ 100 ms nach dem Vokal gehört dazu."""
    gap = np.zeros(int(0.1 * voice.RATE), np.float32)
    t_sound = _speech_like(0.04)
    x = np.concatenate([np.zeros(20000, np.float32), _speech_like(0.4), gap, t_sound,
                        np.zeros(20000, np.float32)])
    y = voice.trim_silence(x)
    assert len(y) / voice.RATE >= 0.4 + 0.1 + 0.04


def test_trim_recording_without_pause():
    x = _speech_like(0.7) + 0.002                        # Sprache von der ersten bis zur letzten ms
    assert len(voice.trim_silence(x)) / voice.RATE >= 0.6



# ------------------------------------- 0.8.11.2: Tiefmitten und Voreinstellung „Kräftig“
def _level_at(x, freq):
    spec = np.abs(np.fft.rfft(x))
    f = np.fft.rfftfreq(len(x), 1 / voice.RATE)
    return 20 * np.log10(spec[np.argmin(np.abs(f - freq))] + 1e-12)


def test_lowmid_cuts_around_400_hz():
    t = np.arange(voice.RATE) / voice.RATE
    x = (0.1 * np.sin(2 * np.pi * 420 * t) + 0.1 * np.sin(2 * np.pi * 2000 * t)).astype(np.float32)
    y = voice.equalize(x, 0, 0, 0, lowmid=-6)
    assert -6.5 < _level_at(y, 420) - _level_at(x, 420) < -5.0
    assert abs(_level_at(y, 2000) - _level_at(x, 2000)) < 0.5


def test_strong_preset_removes_hum_without_compression():
    t = np.arange(voice.RATE) / voice.RATE
    x = (0.1 * np.sin(2 * np.pi * 60 * t) + 0.1 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    flat = dict(preset="strong", bass=0, lowmid=0, mid=0, treble=0)
    y = voice.apply_tone(x, flat)
    hum = (_level_at(y, 60) - _level_at(y, 1000)) - (_level_at(x, 60) - _level_at(x, 1000))
    assert hum < -20                                    # Brummen deutlich weg (~24 dB)
    assert set(voice.PRESETS["strong"]) == {"bass", "lowmid", "mid", "treble"}
    # ohne lowmid in alten Einstellungen läuft alles weiter
    assert len(voice.apply_tone(x, {"preset": "normal", "bass": -3})) == len(x)
