"""0.8.29: S&P-Übung – Stationen auf eigenen Frequenzen, gedreht wird am VFO-Knopf (nur lesen)."""

import json
import subprocess
import sys
import textwrap

import numpy as np

from gogoham import cwsynth as cs
from gogoham import practice as pm
from gogoham import practice_sp as sp
from gogoham.contests import CONTESTS
from gogoham.contests.base import Station
from gogoham.cty import CtyDB
from gogoham.rig import RigWorker

from test_practice_0828 import CALLS, HERE


# ------------------------------------------------------------------ Ton beim Abstimmen
def _tone(vfo, sideband=1, rf=14025000, x=None, filt=None):
    m = cs.Mixer(noise_db=-120, volume=1.0)
    if filt:
        m.set_filter(*filt)
    m.add_tuned(cs.render_analytic("TEST TEST", 22, 600) if x is None else x, 0, rf, 0)
    m.tune(vfo, sideband)
    y = np.concatenate([m.render(720) for _ in range(150)])
    f = np.fft.rfftfreq(len(y), 1 / cs.RATE)
    return float(np.sqrt(np.mean(y * y))), float(f[np.abs(np.fft.rfft(y)).argmax()])


def test_tone_follows_vfo_and_filter():
    loud, f0 = _tone(14025000)
    assert abs(f0 - 600) < 15 and loud > 0.2                       # genau drauf: 600 Hz
    assert abs(_tone(14025100)[1] - 500) < 15                       # VFO höher → Ton tiefer
    assert abs(_tone(14024900)[1] - 700) < 15
    assert abs(_tone(14025100, -1)[1] - 700) < 15                   # CW-R: umgekehrt
    assert _tone(14025600)[0] < 0.01 * loud                         # außerhalb des Filters
    assert _tone(None)[0] < 1e-6                                    # ohne Funkgerät: still


def test_ssb_voice_shifts_and_other_sideband_is_cut():
    t = np.arange(int(1.5 * cs.RATE)) / cs.RATE
    voice = cs.analytic((0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32))
    filt = (1500.0, 1200.0)
    assert abs(_tone(14200000, 1, 14200000, voice, filt)[1] - 1000) < 15
    assert abs(_tone(14200300, 1, 14200000, voice, filt)[1] - 700) < 15     # USB daneben
    assert abs(_tone(7100300, -1, 7100000, voice, filt)[1] - 1300) < 15     # LSB: umgekehrt
    assert _tone(14203000, 1, 14200000, voice, filt)[0] < 0.02              # weit weg: weg


# ------------------------------------------------------------------ Ablauf
def make(seed=5, **kw):
    cty = CtyDB.from_file(HERE / "cty_sample.dat")
    c = CONTESTS["cqww-cw"](cty, Station(call="DL9ZZZ", cq_zone=14, grid="JN59ME"))
    s = pm.Settings(contest="cqww-cw", band="20", activity=2, style="sp", **kw)
    return sp.SPPractice(c, s, CALLS, "DL9ZZZ", (49.2, 11.0), 140, 2, seed=seed)


def wait_listen(e, r, t):
    while t < 120:
        e.tick(t)
        if r.mode == "listen" and r.tx and r.tx[-1][1] < t - 0.1 and not r.ghost_now:
            return t
        t += 0.02
    raise AssertionError("Station hört nie zu")


def test_band_full_of_stations_on_own_frequencies():
    e = make()
    lo, hi = sp.segment("20", "CW")
    assert len(e.runners) == min(e.target(), e.pool_size)
    fs = sorted(r.rf for r in e.runners)
    assert all(lo <= f <= hi for f in fs)
    assert min(b - a for a, b in zip(fs, fs[1:])) >= sp.SPACING["CW"]
    due = []
    t = 0.0
    while t < 12:
        due += e.tick(t)
        t += 0.05
    assert due and all(tx.rf for tx in due)                  # jede Sendung hat eine Frequenz
    assert any(tx.text.startswith(("CQ", "TEST")) or "TEST" in tx.text for tx in due)


def test_full_sp_qso_and_far_or_colliding_calls_are_not_heard():
    e = make(seed=7)
    r = e.runners[0]
    r.ghost = None
    t = wait_listen(e, r, 0.0)
    e.on_sent("DL9ZZZ", t, t + 1.2, "14", rf=r.rf + 1500)     # weit daneben: hört dich nicht
    assert r.mode == "listen"
    sp.P_PARTIAL, sp.P_BUST, keep = 0.0, 0.0, (sp.P_PARTIAL, sp.P_BUST)
    try:
        e.on_sent("DL9ZZZ", t, t + 1.2, "14", rf=r.rf + 80)
    finally:
        sp.P_PARTIAL, sp.P_BUST = keep
    assert r.mode == "me" and r.heard_as == "DL9ZZZ"
    t2 = t
    got = []
    while not got and t2 < t + 6:
        got = [tx for tx in e.tick(t2) if tx.who == r.call]
        t2 += 0.02
    assert got and got[0].text.startswith("DL9ZZZ 5NN")
    end = r.tx[-1][1]
    e.on_sent("5NN 14", end + 0.3, end + 1.5, "14", rf=r.rf)
    assert [d.call for d in e.done] == [r.call] and e.done[0].logged_as == "DL9ZZZ"
    # während die Station sendet, hört sie nicht
    r2 = e.runners[1]
    r2.ghost = None
    t3 = wait_listen(e, r2, t2)
    e.tick(t3)
    r2.mode, r2.next_at = "cq", t3
    e.tick(t3 + 0.01)
    a, b = r2.tx[-1]
    e.on_sent("DL9ZZZ", a + 0.5, a + 1.5, "14", rf=r2.rf)
    assert r2.mode == "listen"                                 # nicht gehört


def test_busted_call_must_be_corrected():
    e = make(seed=11)
    r = e.runners[0]
    r.ghost = None
    t = wait_listen(e, r, 0.0)
    sp.P_PARTIAL, sp.P_BUST, keep = 0.0, 1.0, (sp.P_PARTIAL, sp.P_BUST)
    try:
        e.on_sent("DL9ZZZ", t, t + 1.2, "14", rf=r.rf)
    finally:
        sp.P_PARTIAL, sp.P_BUST = keep
    assert r.mode == "me" and r.heard_as != "DL9ZZZ"
    wrong = r.heard_as
    # ohne Berichtigung geloggt → Fehler „falsch geloggt worden“
    e2_end = r.tx[-1][1]
    e.on_sent("5NN 14", e2_end + 0.3, e2_end + 1.3, "14", rf=r.rf)
    assert e.done[-1].logged_as == wrong
    q = type("Q", (), {"call": r.call, "exch_r": r.exch, "band": "20"})
    res = e.evaluate([q(), q()], 120)
    kinds = [f.kind for f in res.findings]
    assert "theirs" in kinds and "dupe" in kinds
    # mit Berichtigung (Rufzeichen + Austausch) richtig im Log
    e2 = make(seed=11)
    r = e2.runners[0]
    r.ghost = None
    t = wait_listen(e2, r, 0.0)
    sp.P_PARTIAL, sp.P_BUST = 0.0, 1.0
    try:
        e2.on_sent("DL9ZZZ", t, t + 1.2, "14", rf=r.rf)
    finally:
        sp.P_PARTIAL, sp.P_BUST = keep
    b = r.tx[-1][1]
    e2.on_sent("DL9ZZZ 5NN 14", b + 0.3, b + 1.8, "14", rf=r.rf)
    assert e2.done[-1].logged_as == "DL9ZZZ"


def test_spots_band_change_and_wrong_band():
    e = make(spots=True)
    for r in e.runners:
        r.spot_at = 0.0
    e.tick(0.1)
    spots = e.take_spots()
    rf = {r.call: r.rf for r in e.runners}
    assert spots and all(abs(s.freq - rf[s.call]) <= 250 for s in spots if s.call in rf)
    assert all(s.spotter.endswith("-#") and "WPM" in s.comment for s in spots)
    e.set_band("40", 5.0)
    lo, hi = sp.segment("40", "CW")
    assert e.runners and all(lo <= r.rf <= hi for r in e.runners)
    e.set_band(None, 6.0)
    assert e.runners == [] and e.tick(7.0) == []


def test_bust_changes_exactly_one_char():
    import random
    rng = random.Random(1)
    for call in ("DL9ZZZ", "DO2GGH", "K1EEE", "DL1ABC/P"):
        b = sp.bust(call, rng)
        assert b != call and len(b) == len(call)
        assert sum(x != y for x, y in zip(b, call)) == 1


# ------------------------------------------------------------------ Funkgerät nur hören
def test_listen_only_worker_never_queues_transmit_commands():
    w = RigWorker("127.0.0.1", 1, listen_only=True)
    for name, args in (("ptt", (True,)), ("send_morse", ("CQ",)), ("send_voice_mem", (1,)),
                       ("set_keyspd", (25,)), ("set_freq", (14025000,)),
                       ("set_mode", ("CW", 0))):
        w.submit(name, *args)
    got = []
    while not w.commands.empty():
        got.append(w.commands.get_nowait()[0])
    assert got == ["set_freq", "set_mode"]


# ------------------------------------------------------------------ Hauptfenster
SCRIPT = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod, practice_sp as sp
from gogoham.db import DEFAULT_META, LogDB
from gogoham.rig import RigState
from gogoham.gui import main_window
from gogoham.gui import practice_mode as pmode
made = []
class FakeRig:
    def __init__(self, host, port, poll=0.4, listen_only=False):
        self.kw = dict(poll=poll, listen=listen_only)
        self.freq, self.mode, self.sent = 14030000, "CW", []
        made.append(self)
    def start(self): pass
    def stop(self): pass
    def join(self, t=None): pass
    def snapshot(self):
        return RigState(connected=True, freq=self.freq, mode=self.mode)
    def submit(self, name, *a):
        self.sent.append(name)
class FakeKeyer:
    def __init__(self, *a, **k): made.append("keyer")
    def start(self): pass
    def stop(self): pass
    def join(self, t=None): pass
    def snapshot(self):
        from gogoham.winkey import KeyerState
        return KeyerState()
main_window.RigWorker = FakeRig
main_window.wkmod.WinKeyWorker = FakeKeyer
M = main_window.MainWindow
M._welcome = lambda self: None
M._ask_scp = lambda self, *a, **k: None
M._ask_flags = lambda self, *a, **k: None
M._start_daily_update = lambda self, wait=10.0: None
M._make_practice_stream = lambda self, mixer, dev: pmode.SilentStream(mixer)
M._show_practice_dialog = lambda self, dlg: True
M._show_practice_result = lambda self, dlg: None
p = Path(sys.argv[2]) / "cqww-cw.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="cqww-cw", mycall="DL9ZZZ",
                                my_grid="JN59ME")); db.close()
cfg = cfgmod.load()
cfg.update(rig_enabled=True, rig_model=3073, rig_autostart=False, wsjtx_enabled=False,
           last_log=str(p), esm_enabled=True, esm_mode="run")
cfg["rig_profiles"] = [{"name": "IC-7300", "model": 3073, "device": "/dev/null", "baud": 0,
                        "host": "127.0.0.1", "port": 4532, "start": False,
                        "winkey": "/dev/null", "ptt_line": "DTR", "ptt_device": "/dev/null"}]
cfg["practice"] = {"contest": "cqww-cw", "band": "20", "activity": 2, "minutes": 10,
                   "style": "sp", "spots": True}
cfgmod.save(cfg)
def wait(sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.01)
w = M(); w.show(); wait(0.3)
made.clear()
w.start_practice(); wait(0.3)
c = w.practice
out = {"listen": c.listen, "engine": type(c.engine).__name__}
rig = w.rig
out["rig"] = [rig.kw, "keyer" in made, w.keyer is None]
out["esm"] = w.cfg["esm_mode"]
out["bar"] = w.lbl_practice.text()
r = min(c.engine.runners, key=lambda x: x.next_at)
r.ghost = None
for x in c.engine.runners:
    x.spot_at = 0.0
rig.freq = r.rf + 40
sp.P_PARTIAL, sp.P_BUST = 0.0, 0.0
end = time.monotonic() + 20
while time.monotonic() < end and not (r.mode == "listen" and r.tx and
                                      r.tx[-1][1] < c.mixer.now - 0.1 and not r.ghost_now):
    app.processEvents(); time.sleep(0.01)
out["vfo"] = c.vfo == r.rf + 40
out["spots"] = len(w.spots.spots) > 0
w.ed_call.setText(r.call); w.update_check(); w.ed_call.setFocus()
w.enter_pressed()                       # ESM S&P: eigenes Rufzeichen
end = time.monotonic() + 12
while time.monotonic() < end and r.mode != "me":
    app.processEvents(); time.sleep(0.01)
out["me"] = r.mode
end = time.monotonic() + 12
while time.monotonic() < end and not (r.tx and r.tx[-1][1] < c.mixer.now - 0.2):
    app.processEvents(); time.sleep(0.01)
out["dbg"] = [r.mode, r.tx[-2:], c.mixer.now]
w.ed_exch.setText(r.exch)
w.enter_pressed()                       # ESM S&P: Austausch + loggen
wait(0.3)
out["qsos"] = len(w.qsos)
out["done"] = [d.call for d in c.engine.done] == [r.call]
out["qso_freq"] = w.qsos[-1].freq if w.qsos else 0
out["sent_to_rig"] = rig.sent
out["dbg"].append([r.mode, r.tx[-2:], c.mixer.now, w.qsos[-1].exch_r if w.qsos else ""])
w.end_practice(); wait(0.2)
out["after"] = [w.practice is None, len(w.spots.spots), w.cfg["esm_mode"],
                made[-1].kw if made and not isinstance(made[-1], str) else made[-1]]
res = w.last_practice_result
out["result"] = [res.qsos, res.correct]
w.close()
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def test_main_window_sp_practice(tmp_path):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    for d in (data / "gogoham", cfg / "gogoham", logs):
        d.mkdir(parents=True, exist_ok=True)
    (data / "gogoham" / "MASTER.SCP").write_text("\n".join(CALLS) + "\n")
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(logs), str(HERE / "cty_sample.dat"), str(data)],
                       capture_output=True, text=True, env=env, timeout=150)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["listen"] is True and o["engine"] == "SPPractice"
    kw, keyer_made, no_keyer = o["rig"]
    assert kw == {"poll": None, "listen": True}      # nur hören, Abfrage gemessen
    assert not keyer_made and no_keyer                              # kein WinKey
    assert o["esm"] == "sp" and o["bar"].startswith("S&P-ÜBUNG – es wird nichts gesendet")
    assert o["vfo"] and o["spots"]
    assert o["me"] == "me" and o["qsos"] == 1, o["dbg"]
    assert o["done"] is True, o["dbg"]
    assert o["me"] == "me" and o["qsos"] == 1 and o["done"] is True
    assert o["qso_freq"] > 14000000
    assert not set(o["sent_to_rig"]) - {"set_freq", "set_mode"}     # nie PTT/CW ans Gerät
    assert o["after"][0] and o["after"][1] == 0 and o["after"][2] == "run"
    assert o["after"][3] == "keyer" or o["after"][3]["listen"] is False   # wieder normal
    assert o["result"] == [1, 1]


def test_ssb_sp_runs_with_voices_and_own_segment():
    cty = CtyDB.from_file(HERE / "cty_sample.dat")
    c = CONTESTS["cqww-ssb"](cty, Station(call="DL9ZZZ", cq_zone=14, grid="JN59ME"))
    s = pm.Settings(contest="cqww-ssb", band="40", mode="SSB", activity=3, style="sp")

    class Voices:
        asked = []

        def speakers(self):
            return 904

        def request(self, key, text, voice, rate):
            self.asked.append(text)

        def get(self, key):
            return np.zeros(4800, np.float32)

    v = Voices()
    e = sp.SPPractice(c, s, CALLS, "DL9ZZZ", (49.2, 11.0), 140, 2, seed=3, voices=v)
    lo, hi = sp.segment("40", "SSB")
    assert e.runners and all(lo <= r.rf <= hi for r in e.runners)
    assert min(abs(a.rf - b.rf) for a in e.runners for b in e.runners if a is not b) >= 2800
    assert any("contest" in t for t in v.asked)                    # Sätze vorab bestellt
    due, t = [], 0.0
    while t < 15:
        due += e.tick(t)
        t += 0.05
    assert due and all(tx.key and tx.rf for tx in due)
    r = e.runners[0]
    assert e.nearest(r.rf + 600) is r and e.nearest(r.rf + 1400) is None


# ------------------------------------------------------------------ 0.8.29.1
def test_more_stations_scaled_by_band_width():
    e = make()
    for act, cw in ((1, 15), (3, 50), (5, 100)):
        e.s.activity = act
        assert e.target() == cw
    e.set_band("40", 1.0)                           # 40 kHz statt 60 kHz
    e.s.activity = 5
    assert e.target() == 67
    e.ssb = True
    e._seg = sp.segment("20", "SSB")
    assert e.target() == 55


def test_ssb_station_waits_for_its_voice_instead_of_missing_out():
    cty = CtyDB.from_file(HERE / "cty_sample.dat")
    c = CONTESTS["cqww-ssb"](cty, Station(call="DL9ZZZ", cq_zone=14, grid="JN59ME"))
    s = pm.Settings(contest="cqww-ssb", band="20", mode="SSB", activity=1, style="sp")

    class Voices:
        ready = False

        def speakers(self):
            return 904

        def request(self, key, text, voice, rate, tag=""):
            pass

        def get(self, key):
            return np.zeros(4800, np.float32) if self.ready else None

    v = Voices()
    e = sp.SPPractice(c, s, CALLS, "DL9ZZZ", (49.2, 11.0), 140, 2, seed=3, voices=v)
    due = []
    for i in range(200):
        due += e.tick(i * 0.05)
    assert due == [] and all(r.mode == "cq" for r in e.runners)     # nichts fällt aus
    v.ready = True
    for i in range(200, 400):
        due += e.tick(i * 0.05)
    assert due                                                      # jetzt rufen sie
    r = e.runners[0]
    assert r.call in e.near_calls(r.rf + 5000) and r.call not in e.near_calls(r.rf + 50000)


def test_voicebank_does_nearby_stations_first():
    from gogoham import ssbvoice
    b = ssbvoice.VoiceBank(kind="")                 # ohne Hintergrund-Thread
    for n in range(3):
        b.request(f"k{n}", "x", 0, 1.0, tag=f"S{n}")
    b.request("k0", "x", 0, 1.0, tag="S0")          # doppelt: nur einmal in der Liste
    assert len(b._jobs) == 3
    b.focus({"S2"})
    assert b._next_job()[0] == "k2" and b._next_job()[0] == "k0"
    b.close()


def test_practice_never_plays_to_the_rig_soundcard():
    from gogoham.gui.main_window import MainWindow

    class Win:
        practice = object()

    assert MainWindow._say_plan(Win(), object()) is False


def test_worker_measures_and_polls_as_fast_as_the_radio_allows():
    import socket
    import threading
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    seen = []

    def serve():
        conn, _ = srv.accept()
        f = conn.makefile("rb")
        for line in f:
            cmd = line.decode().strip()
            seen.append(cmd)
            if cmd == "f":
                conn.sendall(b"14025000\n")
            elif cmd == "m":
                conn.sendall(b"CW\n500\n")
            elif cmd.startswith("\\set_cache"):
                conn.sendall(b"RPRT 0\n")
            else:
                conn.sendall(b"RPRT 0\n")

    threading.Thread(target=serve, daemon=True).start()
    import gogoham.rig as rigmod
    keep = rigmod.query_model
    rigmod.query_model = lambda h, p, timeout=1.5: 3073      # wie ein echter rigctld
    try:
        w = RigWorker("127.0.0.1", srv.getsockname()[1])
        w.start()
        import time
        time.sleep(1.2)
        st = w.snapshot()
        w.stop()
        w.join(2)
    finally:
        rigmod.query_model = keep
    assert st.connected and st.freq == 14025000 and st.mode == "CW"
    assert st.poll_ms == 20                                 # schnelles Gerät: 50-mal pro Sekunde
    assert "\\set_cache 0" in seen and "\\set_cache 10" in seen
    assert seen.count("f") > 20 and seen.count("m") <= 3     # Betriebsart nur 1× pro Sekunde
    fixed = RigWorker("127.0.0.1", 1, poll=0.005)
    assert fixed.poll == 0.02 and not fixed.auto            # nie öfter als 50-mal pro Sekunde


# ------------------------------------------------------------------ SSB, „Enter sendet“ (0.8.29.1)
SCRIPT_SSB = r'''
import sys, time
sys.path.insert(0, sys.argv[2])
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod, practice_sp as sp
from gogoham.db import DEFAULT_META, LogDB
from gogoham.rig import RigState
from gogoham.gui import main_window
from gogoham.gui import practice_mode as pmode


class FakeRig:
    def __init__(self, *a, **k): self.freq, self.mode = 14200000, "USB"
    def start(self): pass
    def stop(self): pass
    def join(self, t=None): pass
    def snapshot(self): return RigState(connected=True, freq=self.freq, mode=self.mode)
    def submit(self, *a): pass


class V:
    ok = True
    def speakers(self): return 904
    def request(self, *a, **k): pass
    def get(self, k):
        import numpy as np; return np.zeros(4800, np.float32)
    def close(self): pass


main_window.RigWorker = FakeRig
M = main_window.MainWindow
M._welcome = lambda self: None
M._ask_scp = lambda self, *a, **k: None
M._ask_flags = lambda self, *a, **k: None
M._start_daily_update = lambda self, wait=10.0: None
M._make_practice_stream = lambda self, mixer, dev: pmode.SilentStream(mixer)
M._make_practice_voices = lambda self: V()
M._show_practice_dialog = lambda self, dlg: True
M._show_practice_result = lambda self, dlg: None
style = "sp"
p = Path(sys.argv[1]) / "fd.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="darc-fd-ssb", mycall="DO2GGH", my_grid="JN59ME")); db.close()
cfg = cfgmod.load()
cfg.update(rig_enabled=True, rig_model=3073, rig_autostart=False, wsjtx_enabled=False, last_log=str(p), esm_enabled=True)
cfg["rig_profiles"] = [{"name": "IC-7300", "model": 3073, "device": "/dev/null", "baud": 0, "host": "127.0.0.1", "port": 4532, "start": False}]
cfg["practice"] = {"contest": "darc-fd-ssb", "band": "20", "mode": "SSB", "activity": 2, "minutes": 10, "style": style, "spots": False}
cfgmod.save(cfg)


def wait(s):
    e = time.monotonic() + s
    while time.monotonic() < e:
        app.processEvents(); time.sleep(0.01)


sent = []
orig = pmode.PracticeController.send_ssb
def spy(self, meaning, samples, ex):
    sent.append(meaning)
    return orig(self, meaning, samples, ex)
pmode.PracticeController.send_ssb = spy
w = M(); w.show(); wait(0.3)
w.start_practice(); wait(0.3)
c = w.practice
sp.P_PARTIAL, sp.P_BUST = 0.0, 0.0
done = []
for r in sorted(c.engine.runners, key=lambda x: x.next_at)[:2]:
    r.ghost = None
    w.rig.freq = r.rf
    e = time.monotonic() + 25
    while time.monotonic() < e and not (c.vfo == r.rf and r.mode == "listen" and r.tx and
                                        r.tx[-1][1] < c.mixer.now - 0.1 and
                                        c.mixer.now > getattr(c, "_my_end", 0)):
        app.processEvents(); time.sleep(0.01)
    w.ed_call.setText(r.call); w.update_check(); w.ed_call.setFocus()
    w.enter_pressed()
    e = time.monotonic() + 20
    while time.monotonic() < e and not (r.mode == "me" and r.tx and r.tx[-1][1] < c.mixer.now - 0.2):
        app.processEvents(); time.sleep(0.01)
    w.ed_exch.setText(r.exch); w.enter_pressed()
    wait(0.3)
    done.append([r.call, [q.exch_s for q in w.qsos], [d.call for d in c.engine.done]])
w.end_practice(); w.close()
import json
print("RESULT " + json.dumps({"sent": sent, "done": done}))
'''


def test_ssb_sp_enter_sends_exchange_and_serial_counts(tmp_path):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    for d in (data / "gogoham", cfg / "gogoham", logs):
        d.mkdir(parents=True, exist_ok=True)
    (data / "gogoham" / "MASTER.SCP").write_text("\n".join(CALLS) + "\n")
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", SCRIPT_SSB, str(logs), str(HERE.parent),
                        str(HERE / "cty_sample.dat")],
                       capture_output=True, text=True, env=env, timeout=150)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert len(o["done"]) == 2, o
    (c1, ex1, d1), (c2, ex2, d2) = o["done"]
    assert o["sent"][0] == "DO2GGH" and o["sent"][1] == c1 + " 59 001 TU DO2GGH"
    assert o["sent"][3] == c2 + " 59 002 TU DO2GGH"
    assert ex2 == ["001", "002"] and d2 == [c1, c2]
