"""0.8.28: Übungsmodus CW – Töne (cwsynth), Ablauf (practice) und Einbindung ins Hauptfenster."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

from gogoham import cwsynth as cs
from gogoham import practice as pm
from gogoham.contests import CONTESTS
from gogoham.contests.base import Station
from gogoham.cty import CtyDB

HERE = Path(__file__).parent
CALLS = ["DL1ABC", "DL2XYZ", "OE3ABC", "PA3AAA", "G4BBB", "UA3CCC", "JA1DDD", "K1EEE", "W3FFF",
         "VE3GGG", "PY2HHH", "VK2III", "HA5JJJ", "OK1KKK", "SP9LLL", "ON4MMM", "BY1NNN"]


# ------------------------------------------------------------------ Töne
def test_paris_timing_and_tone():
    assert abs(cs.duration_s("PARIS", 20) - 2.58) < 1e-9          # 43 Einheiten à 60 ms
    x = cs.render("E", 20, 700)
    assert len(x) == int(round(0.06 * cs.RATE))
    spec = np.abs(np.fft.rfft(x, 48000))
    assert abs(int(np.argmax(spec)) - 700) <= 2                    # Tonhöhe stimmt
    assert abs(x[0]) < 0.01 and abs(x[-1]) < 0.05                  # weiche Flanken, kein Klick


def test_cut_numbers():
    assert cs.cut_numbers("5NN 109") == "5NN 1TN"
    assert cs.cut_numbers("5NN 007", leading_only=True) == "5NN TT7"
    assert pm.norm_tokens("TT7 1TN") == ["7", "109"]


def test_mixer_timeline_noise_and_cancel():
    m = cs.Mixer(noise_db=-60, volume=1.0)
    end = m.add(cs.render("TEST", 25), 0.5, 0.0, who="me")
    assert abs(end - (0.5 + cs.duration_s("TEST", 25))) < 0.01
    a = m.render(int(0.4 * cs.RATE))
    assert np.abs(a).max() < 0.01                                  # vor 0,5 s nur leises Rauschen
    m.render(int(0.3 * cs.RATE))
    m.cancel("me")
    assert m.busy_until("me") <= m.now + 1e-6                      # Esc bricht sofort ab
    n = cs.band_noise(1.0)
    spec = np.abs(np.fft.rfft(n))
    f = np.fft.rfftfreq(len(n), 1 / cs.RATE)
    assert spec[(f > 400) & (f < 900)].mean() > 20 * spec[f > 2000].mean()   # nur CW-Bereich


# ------------------------------------------------------------------ Ablauf
def make(contest="cqww-cw", seed=3, **kw):
    cty = CtyDB.from_file(HERE / "cty_sample.dat")
    c = CONTESTS[contest](cty, Station(call="DL9ZZZ", cq_zone=14, grid="JN59ME", dok="B36"))
    s = pm.Settings(contest=contest, band="20", activity=5, **kw)
    return c, pm.Practice(c, s, CALLS, "DL9ZZZ", (49.2, 11.0), 140, 2, seed=seed)


def run_until(p, t0, t1, step=0.1):
    out, t = [], t0
    while t < t1:
        t += step
        out += p.tick(t)
    return out, t


def send(p, c, text, t, n=1):
    d = cs.duration_s(text, 28)
    p.on_sent(text, t, t + d, c.sent_exchange(n))
    return t + d


def test_nobody_calls_before_cq_and_callers_after():
    c, p = make()
    out, t = run_until(p, 0, 5)
    assert out == []                                               # ohne CQ ruft keiner
    t = send(p, c, "CQ TEST DL9ZZZ DL9ZZZ TEST", t)
    out, t = run_until(p, t, t + 3)
    calls = {tx.who for tx in out}
    assert calls and all(cl in CALLS for cl in calls) and "DL9ZZZ" not in calls
    assert all(24 <= tx.wpm <= 32 and 380 <= tx.pitch <= 820 for tx in out)


def test_full_qso_and_evaluation():
    c, p = make()
    t = send(p, c, "CQ TEST DL9ZZZ DL9ZZZ TEST", 0.0)
    out, t = run_until(p, t, t + 3)
    who = out[0].who
    t = send(p, c, f"{who} 5NN 14", t)
    out, t = run_until(p, t, t + 4)
    reply = [tx for tx in out if tx.who == who]
    assert reply and "5NN" in reply[0].text
    truth = next(x for x in p.callers if x.call == who)
    assert truth.state == pm.SENT
    t = send(p, c, "TU DL9ZZZ", t)
    assert [x.call for x in p.done] == [who]
    Q = type("Q", (), {})
    ok = Q(); ok.call, ok.exch_r = who, truth.exch
    r = p.evaluate([ok], 600)
    assert r.correct == 1 and r.findings == [] and r.rate == 6


def test_wrong_call_gets_corrected_and_partial_query():
    c, p = make(seed=11)
    t = send(p, c, "CQ TEST DL9ZZZ DL9ZZZ TEST", 0.0)
    out, t = run_until(p, t, t + 3)
    who = out[0].who
    wrong = who[:-1] + ("X" if who[-1] != "X" else "Q")
    t = send(p, c, f"{wrong} 5NN 14", t)
    out, t = run_until(p, t, t + 4)
    assert any(tx.who == who and tx.text == f"{who} {who}" for tx in out)   # korrigiert
    # halbes Rufzeichen: nur passende Stationen antworten
    frag = who[-3:]
    t = send(p, c, f"{frag}?", t)
    out, t = run_until(p, t, t + 4)
    assert out and all(frag in tx.who for tx in out if tx.who != "QRM")


def test_agn_repeats_exchange_and_patience_ends():
    c, p = make(seed=5, qrm=False)
    t = send(p, c, "CQ TEST DL9ZZZ DL9ZZZ TEST", 0.0)
    out, t = run_until(p, t, t + 3)
    who = out[0].who
    t = send(p, c, f"{who} 5NN 14", t)
    run_until(p, t, t + 4)
    t += 4
    t = send(p, c, "AGN?", t)
    out, t = run_until(p, t, t + 6)
    ex = next(x for x in p.callers if x.call == who).exch
    assert any(tx.who == who and tx.text.split()[:2] == [ex, ex] or
               pm.norm_tokens(tx.text)[:2] == pm.norm_tokens(f"{ex} {ex}") for tx in out)
    # niemand antwortet mehr: die anderen geben irgendwann auf
    t = send(p, c, "TU DL9ZZZ", t)
    run_until(p, t, t + 120)
    assert all(x.state != pm.CALLING for x in p.callers)


def test_evaluation_finds_errors():
    c, p = make()
    a = pm.Caller("OK1KKK", "15", 25, 600, -5, (0.1, 0, 0), 3, False, False, state=pm.DONE)
    b = pm.Caller("SP9LLL", "15", 25, 600, -5, (0.1, 0, 0), 3, False, False, state=pm.DONE)
    d = pm.Caller("HA5JJJ", "15", 25, 600, -5, (0.1, 0, 0), 3, False, False, state=pm.DONE)
    p.done = [a, b, d]
    Q = type("Q", (), {})
    q1 = Q(); q1.call, q1.exch_r = "OK1KKX", "15"            # Rufzeichen falsch
    q2 = Q(); q2.call, q2.exch_r = "SP9LLL", "16"            # Austausch falsch
    q3 = Q(); q3.call, q3.exch_r = "ZZ9ZZZ", "05"            # NIL
    r = p.evaluate([q1, q2, q3], 300)
    kinds = sorted(f.kind for f in r.findings)
    assert kinds == ["call", "exch", "missed", "nil"] and r.correct == 0


def test_contest_rules_respected():
    # ARRL DX von Europa aus: nur W/VE rufen an
    c, p = make("arrl-dx-cw")
    assert p.pool_size and {x[2].cont for x in p._pool} == {"NA"}
    assert pm.can_practice(CONTESTS["cqww-cw"]) and pm.can_practice(CONTESTS["wag"])
    assert not pm.can_practice(CONTESTS["cqww-ssb"])               # SSB kommt mit 0.8.28.1
    assert not pm.can_practice(CONTESTS["iaru-vhf"])               # UKW noch nicht
    assert not pm.can_practice(CONTESTS["ww-digi"])


def test_settings_roundtrip():
    s = pm.Settings(activity=5, qrm=True)
    assert pm.Settings.from_dict(dict(s.to_dict(), output="x")) == s
    assert pm.Settings.from_dict({"activity": "kaputt"}).activity == 3     # falscher Typ


# ------------------------------------------------------------------ Hauptfenster
SCRIPT = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui import main_window
from gogoham.gui import practice_mode as pmode
M = main_window.MainWindow
M._welcome = lambda self: None
M._ask_scp = lambda self, *a, **k: None
M._ask_flags = lambda self, *a, **k: None
M._start_daily_update = lambda self, wait=10.0: None
M._make_practice_stream = lambda self, mixer, dev: pmode.SilentStream(mixer)
M._show_practice_dialog = lambda self, dlg: True
shown = []
M._show_practice_result = lambda self, dlg: shown.append(dlg.windowTitle())
p = Path(sys.argv[2]) / "cqww-cw.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="cqww-cw", mycall="DL9ZZZ",
                                my_grid="JN59ME")); db.close()
cfg = cfgmod.load()
cfg.update(rig_enabled=False, wsjtx_enabled=False, last_log=str(p), esm_enabled=True)
cfg["practice"] = {"contest": "cqww-cw", "band": "20", "activity": 5, "minutes": 10}
cfgmod.save(cfg)
def wait(sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.01)
w = M(); w.show(); wait(0.3)
out = {"menu": w.act_practice.text()}
w.start_practice(); wait(0.2)
c = w.practice
import random
c.engine.rng = random.Random(3)         # fester Zufall: nach CQ ruft sicher jemand
out["running"] = c is not None
out["log"] = str(w.db.path)
out["cfg_last"] = cfgmod.load()["last_log"]
out["bar"] = [not w.practice_bar.isHidden(), w.lbl_practice.text()]
out["band_mode"] = [w.current_band(), w.current_mode()]
w.cfg["rig_enabled"] = True
w.start_rig()
out["rig_blocked"] = w.rig is None
w.ed_call.setFocus()
w.enter_pressed()                       # ESM: leer = CQ (F1)
wait(0.3)
out["sending"] = w.lbl_sending.text() != ""
wait(4.5)
callers = [x for x in c.engine.callers if x.state == "calling"]
for _ in range(3):                      # ruft doch niemand: noch einmal CQ
    if callers:
        break
    w.ed_call.setFocus(); w.enter_pressed(); wait(4.5)
    callers = [x for x in c.engine.callers if x.state == "calling"]
out["callers"] = len(callers) > 0
x = callers[0]
w.ed_call.setText(x.call); w.update_check(); w.ed_call.setFocus()
w.enter_pressed()                       # ESM: Rufzeichen + Austausch (F2)
wait(5.0)
out["state"] = x.state
w.ed_exch.setText(x.exch)
w.enter_pressed()                       # ESM: loggen + TU (F3)
wait(0.3)
out["qsos"] = len(w.qsos)
out["done"] = [d.call for d in c.engine.done] == [x.call]
w.escape_pressed()
w.end_practice()
wait(0.2)
out["after"] = [w.practice is None, str(w.db.path) == str(p), w.practice_bar.isHidden(),
                w.act_practice.text(), shown]
r = w.last_practice_result
out["result"] = [r.qsos, r.correct, r.errors]
hist = json.loads(Path(sys.argv[4]).joinpath("gogoham", "practice.json").read_text())
out["hist"] = [hist[-1]["qsos"], hist[-1]["contest"]]
w.close()
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def test_main_window_practice_flow(tmp_path):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    for d in (data / "gogoham", cfg / "gogoham", logs):
        d.mkdir(parents=True, exist_ok=True)
    (data / "gogoham" / "MASTER.SCP").write_text("\n".join(CALLS) + "\n")
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(logs), str(HERE / "cty_sample.dat"), str(data)],
                       capture_output=True, text=True, env=env, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["menu"] == "Übungsmodus …" and o["running"] is True
    assert "/GoGoHam/Übung/cqww-cw-" in o["log"] and o["cfg_last"].endswith("logs/cqww-cw.ggh")
    assert o["bar"][0] and o["bar"][1].startswith("ÜBUNG – es wird nichts gesendet")
    assert o["band_mode"] == ["20", "CW"] and o["rig_blocked"] is True
    assert o["sending"] and o["callers"] and o["state"] == "sent"
    assert o["qsos"] == 1 and o["done"] is True
    assert o["after"] == [True, True, True, "Übungsmodus …", ["Übung – Auswertung"]]
    assert o["result"] == [1, 1, 0] and o["hist"] == [1, "cqww-cw"]
