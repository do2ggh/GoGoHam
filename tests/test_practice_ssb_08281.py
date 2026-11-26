"""0.8.28.1: Übungsmodus SSB – Stimmen (ssbvoice), Ablauf in SSB und Hauptfenster.

Piper selbst wird hier nicht gestartet (heruntergeladenes Programm) – eine Attrappe spielt
seine Rolle: eine JSON-Zeile rein, Pfad einer WAV-Datei raus."""

import io
import json
import random
import subprocess
import sys
import textwrap
import wave
from pathlib import Path

import numpy as np

from gogoham import practice as pm
from gogoham import ssbvoice as sv
from gogoham.contests import CONTESTS
from gogoham.contests.base import Station
from gogoham.cty import CtyDB

HERE = Path(__file__).parent
CALLS = ["DL1ABC", "OE3ABC", "PA3AAA", "G4BBB", "UA3CCC", "JA1DDD", "K1EEE", "W3FFF",
         "VE3GGG", "PY2HHH", "VK2III", "HA5JJJ", "OK1KKK", "SP9LLL", "ON4MMM"]


def wav_bytes(seconds=0.5, rate=22050, f=440.0):
    t = np.arange(int(seconds * rate)) / rate
    x = (0.3 * np.sin(2 * np.pi * f * t) * 32767).astype("<i2")
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(x.tobytes())
    return b.getvalue()


def test_spoken_texts():
    rng = random.Random(1)
    assert sv.spell("DL1ABC") == "Delta Lima one Alpha Bravo Charlie"
    assert sv.call_text("K1AR", True) == "Kilo one Alpha Romeo, Kilo one Alpha Romeo"
    t = sv.exchange_text("59 14", rng, "QSL")
    assert t.startswith("QSL, five nine, ") and t.split(", ")[-1] in ("fourteen", "one four")
    assert sv.exchange_text("59 KW", rng) == "five nine, kilowatt"
    assert sv.exchange_text("59 123", rng) == "five nine, one two three"
    assert sv.exchange_text("59 B36", rng) == "five nine, Bravo three six"


def test_radio_sound_band_and_speed():
    rate = sv.RATE
    t = np.arange(rate) / rate
    x = (np.sin(2 * np.pi * 100 * t) + np.sin(2 * np.pi * 1000 * t) +
         np.sin(2 * np.pi * 5000 * t)).astype(np.float32)
    y = sv.radio(x)
    spec = np.abs(np.fft.rfft(y))
    assert spec[1000] > 20 * spec[100] and spec[1000] > 20 * spec[5000]   # nur 300–2700 Hz
    assert abs(float(np.sqrt(np.mean(y * y))) - 0.2) < 0.08
    assert len(sv.speed(x, 1.1)) == int(len(x) / 1.1)
    assert len(sv.read_wav(wav_bytes(0.5))) == rate // 2                   # 22,05 → 48 kHz


class FakeRun:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, wav_bytes(0.4), b"")


class FakePiper:
    """Wie piper --json-input --output_dir: liest eine Zeile, schreibt WAV, nennt den Pfad."""

    def __init__(self, cmd, **kw):
        self.cmd, self.dir = cmd, Path(cmd[cmd.index("--output_dir") + 1])
        self.lines, self.n = [], 0
        me = self

        class In:
            def write(self, s):
                me.lines.append(json.loads(s))

            def flush(self):
                pass

            def close(self):
                pass

        class Out:
            def readline(self):
                me.n += 1
                p = me.dir / f"{me.n}.wav"
                p.write_bytes(wav_bytes(0.3))
                return str(p) + "\n"

        self.stdin, self.stdout = In(), Out()

    def poll(self):
        return None

    def terminate(self):
        pass


def wait_for(bank, key):
    import time
    for _ in range(300):
        x = bank.get(key)
        if x is not None:
            return x
        time.sleep(0.01)
    raise AssertionError("Stimme kam nicht")


def test_voicebank_espeak_and_piper(monkeypatch, tmp_path):
    run = FakeRun()
    b = sv.VoiceBank("espeak", run=run)
    b.request("k1", "Delta Lima one", 3, 1.0)
    x = wait_for(b, "k1")
    assert len(x) > 0.3 * sv.RATE and run.calls[0][:3] == ["espeak-ng", "-v", "en-us+m4"]
    b.close()
    from gogoham import piper
    monkeypatch.setattr(piper, "practice_voice_path", lambda: tmp_path / "v.onnx")
    made = []
    b = sv.VoiceBank("piper", popen=lambda cmd, **kw: made.append(FakePiper(cmd)) or made[-1])
    b.request("a", "Kilo one", 17, 1.05)
    b.request("b", "five nine", 400, 1.0)
    wait_for(b, "a"), wait_for(b, "b")
    assert "--json-input" in made[0].cmd and len(made) == 1          # ein Piper für alles
    assert made[0].lines == [{"text": "Kilo one", "speaker_id": 17},
                             {"text": "five nine", "speaker_id": 400}]
    assert not list(Path(made[0].dir).glob("*.wav"))                  # aufgeräumt
    b.close()
    assert sv.VoiceBank("").ok is False


def test_ssb_meaning_and_estimate():
    assert pm.ssb_meaning("[CQ] DL9ZZZ DL9ZZZ", "DL9ZZZ") == "CQ DL9ZZZ DL9ZZZ"
    assert pm.ssb_meaning("[AGN]", "X") == "AGN?" and pm.ssb_meaning("[CALLQ]", "X") == "?"
    assert pm.ssb_meaning("[TU] [MYCALL]", "DL9ZZZ") == "TU DL9ZZZ"
    assert 2.5 < pm.spoken_estimate("DL1ABC 59 14", "DL9ZZZ") < 5


def make(seed=3):
    cty = CtyDB.from_file(HERE / "cty_sample.dat")
    c = CONTESTS["cqww-ssb"](cty, Station(call="DL9ZZZ", cq_zone=14, grid="JN59ME"))
    s = pm.Settings(contest="cqww-ssb", band="20", activity=5, mode="SSB")
    return c, pm.Practice(c, s, CALLS, "DL9ZZZ", (49.2, 11.0), 140, 2, seed=seed)


def run_until(p, t0, t1):
    out, t = [], t0
    while t < t1:
        t += 0.1
        out += p.tick(t)
    return out, t


def test_ssb_qso_flow():
    c, p = make()
    t = 3.0
    p.on_sent("CQ DL9ZZZ DL9ZZZ", 0, t)
    out, t = run_until(p, t, t + 3)
    assert out and all(tx.key and tx.wpm for tx in out)
    first = next(x for x in p.callers if x.call == out[0].who)
    assert out[0].text == first.say_call and "Alpha" in first.say_call or first.say_call
    p.on_sent(f"{first.call} 59 14", t, t + 3, "14")
    out, t = run_until(p, t + 3, t + 8)
    mine = [tx for tx in out if tx.who == first.call]
    assert mine and mine[0].text == first.say_exch and "five nine" in first.say_exch
    p.on_sent("AGN?", t, t + 1, "14")
    out, t = run_until(p, t + 1, t + 6)
    assert any(tx.text == first.say_again for tx in out)
    p.on_sent("TU DL9ZZZ", t, t + 1.5, "14")
    assert [x.call for x in p.done] == [first.call]


def test_ssb_contests():
    assert pm.can_practice(CONTESTS["cqww-ssb"], "SSB")
    assert not pm.can_practice(CONTESTS["cqww-ssb"], "CW")
    assert not pm.can_practice(CONTESTS["cqww-cw"], "SSB")
    assert pm.can_practice(CONTESTS["wag"], "SSB") and pm.can_practice(CONTESTS["wag"], "CW")


SCRIPT = r'''
import json, sys, time, subprocess, io, wave
sys.path.insert(0, sys.argv[1])
import numpy as np
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod, ssbvoice
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui import main_window
from gogoham.gui import practice_mode as pmode
def wavb():
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        w.writeframes(np.zeros(6000, "<i2").tobytes())
    return b.getvalue()
fake_run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, wavb(), b"")
M = main_window.MainWindow
M._welcome = lambda self: None
M._ask_scp = lambda self, *a, **k: None
M._ask_flags = lambda self, *a, **k: None
M._start_daily_update = lambda self, wait=10.0: None
M._make_practice_stream = lambda self, mixer, dev: pmode.SilentStream(mixer)
M._make_practice_voices = lambda self: ssbvoice.VoiceBank("espeak", run=fake_run)
M._show_practice_dialog = lambda self, dlg: True
shown = []
M._show_practice_result = lambda self, dlg: shown.append(dlg.windowTitle())
p = Path(sys.argv[2]) / "cqww-ssb.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="cqww-ssb", mycall="DL9ZZZ",
                                my_grid="JN59ME")); db.close()
cfg = cfgmod.load()
cfg.update(rig_enabled=False, wsjtx_enabled=False, last_log=str(p), esm_enabled=True)
cfg["practice"] = {"contest": "cqww-ssb", "band": "40", "activity": 5, "minutes": 10,
                   "mode": "SSB"}
cfgmod.save(cfg)
def wait(sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.01)
w = M(); w.show(); wait(0.3)
w.start_practice(); wait(0.2)
c = w.practice
out = {"running": c is not None, "mode": [w.current_band(), w.current_mode()]}
w.ed_call.setFocus()
w.enter_pressed()                       # ESM: CQ – du sprichst selbst
wait(0.2)
out["say"] = w.lbl_sending.text()
wait(6.0)
callers = [x for x in c.engine.callers if x.state == "calling"]
out["callers"] = len(callers) > 0
x = callers[0]
w.ed_call.setText(x.call); w.update_check(); w.ed_call.setFocus()
w.enter_pressed()                       # Rufzeichen + Austausch
wait(7.0)
out["state"] = x.state
w.ed_exch.setText(x.exch)
w.enter_pressed()                       # loggen + TU
wait(0.3)
out["done"] = [d.call for d in c.engine.done] == [x.call]
w.end_practice(); wait(0.2)
r = w.last_practice_result
out["result"] = [r.qsos, r.correct, shown, w.practice is None, str(w.db.path) == str(p)]
w.close()
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def test_main_window_ssb_flow(tmp_path):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    for d in (data / "gogoham", cfg / "gogoham", logs):
        d.mkdir(parents=True, exist_ok=True)
    (data / "gogoham" / "MASTER.SCP").write_text("\n".join(CALLS) + "\n")
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(logs), str(HERE / "cty_sample.dat")],
                       capture_output=True, text=True, env=env, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["running"] and o["mode"] == ["40", "LSB"]
    assert "Sprich jetzt: CQ DL9ZZZ DL9ZZZ" in o["say"]
    assert o["callers"] and o["state"] == "sent" and o["done"]
    assert o["result"] == [1, 1, ["Übung – Auswertung"], True, True]
