"""0.8.17.2: PTT-Test (immer sicher wieder aus) und frei belegbare Profilplätze."""
from gogoham import hamlib, rigprofiles


class FakeClient:
    def __init__(self, log, fail=(), state="1"):
        self.log, self.fail, self.state = log, fail, state

    def command(self, cmd, lines=1):
        self.log.append(cmd)
        if cmd in self.fail:
            raise RuntimeError("RPRT -1")
        return [self.state] if cmd == "t" else ["RPRT 0"]

    def close(self):
        self.log.append("close")


PROF = {"model": 3073, "device": "/dev/x", "baud": 115200, "extra": "", "host": "127.0.0.1",
        "port": 4532, "start": False, "service": True}


def _run(fail=(), state="1", in_use=True, fail_once=False):
    log = []
    made = []

    def factory(h, p):
        f = fail if not (fail_once and made) else ()
        made.append(1)
        return FakeClient(log, f, state)
    res = hamlib.ptt_test(PROF, seconds=0, client_factory=factory, in_use=lambda h, p: in_use)
    return res, log


def test_ptt_on_then_off():
    res, log = _run()
    assert res.ok and "Senden" in res.text
    assert log[:3] == ["T 1", "t", "T 0"]


def test_ptt_off_even_if_reading_fails_and_retries_off():
    res, log = _run(fail=("t",))
    assert "T 0" in log and log.index("T 0") > log.index("T 1")
    res, log = _run(fail=("T 0",), fail_once=True)       # erstes Aus scheitert -> neue Verbindung
    assert log.count("T 0") == 2


def test_ptt_not_accepted_or_not_reported():
    res, log = _run(fail=("T 1",))
    assert not res.ok and "T 0" in log                   # trotzdem Aus geschickt
    assert not _run(state="0")[0].ok
    assert _run(state="?")[0].ok


def test_ptt_without_rigctld_starts_temporary_one():
    started, log = [], []

    class Proc:
        def terminate(self):
            started.append("weg")

        def wait(self, t):
            pass
    up = iter([False, True, True])
    res = hamlib.ptt_test(dict(PROF, start=True, service=False), seconds=0,
                          client_factory=lambda h, p: FakeClient(log),
                          starter=lambda *a: started.append(a) or Proc(),
                          in_use=lambda h, p: next(up, True))
    assert res.ok and started[0][:2] == (3073, "/dev/x") and started[-1] == "weg"
    res = hamlib.ptt_test(dict(PROF, start=False, service=False), seconds=0,
                          client_factory=lambda h, p: FakeClient(log), in_use=lambda h, p: False)
    assert not res.ok


def test_profile_slots_free_order():
    cfg = {"rig_profile": 0, "rig_profiles": [
        {"name": "C", "model": 1, "slot": 2, "port": 4534},
        {"name": "B", "model": 2, "slot": 1, "port": 4533}]}
    rigprofiles.ensure_profiles(cfg)
    assert [(p["slot"], p["name"]) for p in cfg["rig_profiles"]] == [(1, "B"), (2, "C")]
    assert cfg["rig_profile"] == 1 and cfg["rig_model"] == 1     # aktiv bleibt „C“
    old = {"rig_profiles": [{"name": "A", "model": 1}, {"name": "B", "model": 2}]}
    rigprofiles.ensure_profiles(old)                              # alte Profile: der Reihe nach
    assert [p["slot"] for p in old["rig_profiles"]] == [0, 1]
