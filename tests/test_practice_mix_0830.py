"""0.8.30: gemischte Übung – Run auf deiner Frequenz, zwischendurch S&P; SSB deutlicher."""

import json
import subprocess
import sys
import textwrap

from gogoham import practice as pm
from gogoham import practice_mix as mx
from gogoham import practice_sp as sp
from gogoham.contests import CONTESTS
from gogoham.contests.base import Station
from gogoham.cty import CtyDB

from test_practice_0828 import CALLS, HERE
from test_practice_sp_0829 import SCRIPT as SP_SCRIPT


def make(seed=5, **kw):
    cty = CtyDB.from_file(HERE / "cty_sample.dat")
    c = CONTESTS["cqww-cw"](cty, Station(call="DL9ZZZ", cq_zone=14, grid="JN59ME"))
    s = pm.Settings(contest="cqww-cw", band="20", activity=3, style="mix", qrm=True, **kw)
    # feste Uhrzeit: die Übung rechnet mit der Bandöffnung zur Stunde (abends ist 20 m zu)
    from datetime import datetime, timezone
    e = mx.MixedPractice(c, s, CALLS, "DL9ZZZ", (49.2, 11.0), 140, 2, seed=seed,
                         when=datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc))
    del e.sp.runners[6:]              # kleine Rufzeichen-Liste: Platz für Anrufer lassen
    e.sp._next_new = 1e9
    return e


def run_until(e, t, until, vfo, cond=lambda due: False):
    out = []
    while t < until:
        e.set_vfo(vfo, t)
        due = e.tick(t)
        out += due
        if cond(due):
            break
        t += 0.02
    return t, out


def test_cq_sets_run_frequency_and_callers_sit_there():
    e = make()
    assert e.s.qrm is False and e.at_run(14030000) is None       # noch keine Run-Frequenz
    run_rf = 14031000
    e.set_vfo(run_rf, 0.0)
    e.on_sent("CQ TEST DL9ZZZ", 0.0, 2.0, "14")
    assert e.run_rf == run_rf and e.at_run() is True
    assert all(abs(r.rf - run_rf) >= sp.SPACING["CW"] for r in e.runners)   # weggerückt
    t, due = run_until(e, 0.0, 8.0, run_rf)
    calls = [tx for tx in due if tx.who in {c.call for c in e.run.callers}]
    assert calls and all(abs(tx.rf - run_rf) <= 150 for tx in calls)
    assert all(tx.rf for tx in due)                               # alles liegt auf dem Band
    # Rufzeichen zurück → Austausch → TU: Run-QSO
    c = e.run.callers[0]
    e.on_sent(f"{c.call} 5NN 14", t, t + 2.0, "14")
    assert c.state == pm.SENT
    e.on_sent("TU DL9ZZZ", t + 4.0, t + 5.0, "14")
    assert c in e.run.done
    # weggedreht: Senden geht an die S&P-Stationen, die Run-Anrufer hören nichts
    r = e.runners[0]
    e.set_vfo(r.rf, t + 6.0)
    assert e.at_run() is False
    before = list(e.run.planned)
    e.on_sent("DL9ZZZ", t + 6.0, t + 7.0, "14")
    assert e.run.planned == before and e.run_rf == run_rf
    # CQ woanders: Run-Frequenz wandert mit, alte Anrufer sind weg
    old = list(e.run.callers)                # Verweise halten (sonst werden ids neu vergeben)
    e.on_sent("CQ TEST DL9ZZZ", t + 9.0, t + 11.0, "14", rf=r.rf + 1000)
    assert e.run_rf == r.rf + 1000 and \
        not any(x is y for x in old for y in e.run.callers)


def test_frequency_is_stolen_only_with_checkbox():
    for steal in (False, True):
        e = make(seed=9, steal=steal)
        e.set_vfo(14031000, 0.0)
        e.on_sent("CQ TEST DL9ZZZ", 0.0, 2.0, "14")
        run_until(e, 2.0, 200.0, 14045000)                         # lange weg
        if not steal:
            assert e.thief is None
            continue
        assert e.thief is not None and e.thief.thief
        assert abs(e.thief.rf - 14031000) <= 150
        assert e.run.damp == mx.THIEF_DAMP                         # kaum noch Anrufer
        assert e.sp.keep_free == []


def test_evaluation_counts_run_and_sp_separately():
    e = make()
    e.set_vfo(14031000, 0.0)
    e.on_sent("CQ TEST DL9ZZZ", 0.0, 2.0, "14")
    t, _ = run_until(e, 0.0, 70.0, 14031000)
    e.on_sent("CQ TEST DL9ZZZ", t, t + 2.0, "14")
    t, _ = run_until(e, t, t + 10.0, 14031000, lambda due: any(c.state == pm.CALLING
                                                               for c in e.run.callers))
    c = next(c for c in e.run.callers if c.state == pm.CALLING)
    e.on_sent(f"{c.call} 5NN 14", t, t + 2.0, "14")
    e.on_sent("TU", t + 4.0, t + 5.0, "14")
    d = sp.Done("F5ABC", "14", "DL9ZZZ")
    e.sp.done.append(d)

    class Q:
        def __init__(self, call, exch):
            self.call, self.exch_r, self.band = call, exch, "20"
    res = e.evaluate([Q(c.call, c.exch), Q("F5ABC", "14")], 120.0)
    assert res.parts["run"]["qsos"] == 1 and res.parts["sp"]["qsos"] == 1
    assert res.parts["run"]["seconds"] >= 70 and res.correct == 2
    assert res.parts["sp"]["seconds"] == 120.0 - res.parts["run"]["seconds"]


def test_ssb_voices_stand_out_more_from_the_noise():
    s = pm.Settings(mode="SSB", noise=3)
    assert pm.noise_db(s) <= pm.NOISE_DB[3] - 10                  # Rauschen deutlich leiser
    assert pm.noise_db(pm.Settings(mode="CW", noise=3)) == pm.NOISE_DB[3]   # CW wie bisher
    assert pm.lift("SSB") > 0 and pm.lift("CW") == 0


SCRIPT = SP_SCRIPT.replace('"style": "sp"', '"style": "mix", "steal": False').split(
    "out[\"bar\"] = w.lbl_practice.text()")[0] + '''
out["bar"] = w.lbl_practice.text()
e = c.engine
w.run_macro(1)                          # F1: CQ auf 14030 → Run-Frequenz
wait(0.3)
out["run_rf"] = e.run_rf
out["esm_run"] = w.cfg["esm_mode"]
rig.freq = 14045000
wait(0.3)
out["esm_away"] = w.cfg["esm_mode"]
out["bar_away"] = w.lbl_practice.text()
rig.freq = 14030050
wait(0.3)
out["esm_back"] = w.cfg["esm_mode"]
w.end_practice(); wait(0.2)
out["after"] = [w.practice is None, w.cfg["esm_mode"], w.last_practice_result.parts is not None]
w.close()
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def test_main_window_mixed_practice(tmp_path):
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
    assert o["engine"] == "MixedPractice" and o["listen"] is True
    assert o["esm"] == "run" and o["bar"].startswith("GEMISCHTE ÜBUNG")
    assert o["run_rf"] == 14030000 and o["esm_run"] == "run"
    assert o["esm_away"] == "sp" and "S&P · Run-Frequenz 14.030,0 kHz" in o["bar_away"]
    assert o["esm_back"] == "run"
    assert o["after"] == [True, "run", True]
