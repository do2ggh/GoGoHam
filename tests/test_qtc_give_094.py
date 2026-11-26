"""0.9.4: QTCs geben (eigene Station außerhalb Europas, WAE DX Contest)."""

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from gogoham import qtc as qtcmod
from gogoham import speech
from gogoham.contests import CONTESTS, Qso, Scorer, Station
from gogoham.cty import CtyDB
from gogoham.db import LogDB
from gogoham.export import cabrillo

HERE = Path(__file__).parent
ROOT = HERE.parent


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def make(cty, call="K1ABC", cid="wae-cw"):
    c = CONTESTS[cid](cty, Station(call=call))
    return c, Scorer(c)


def qso(i, call, nr, t, band="20"):
    return Qso(id=i, time=f"2026-08-08 {t}:00", call=call, band=band, mode="CW",
               freq=14_020_000, rst_s="599", rst_r="599", exch_s=f"{i:03d}", exch_r=nr)


QSOS = [qso(1, "DL1ABC", "12", "10:01"), qso(2, "G4AAA", "7", "10:05"),
        qso(3, "OK1XYZ", "000", "10:09"),                   # keine Nummer bekommen
        qso(4, "DL1ABC", "13", "10:12"),                    # Dupe auf 20 m
        qso(5, "SP5AAA", "431", "10:20"), qso(6, "F5XYZ", "88", "10:30", band="40")]


def test_candidates(cty):
    c, _s = make(cty)
    got = qtcmod.give_candidates(QSOS, [], "G4AAA", c.dupe_key)
    # ältestes zuerst; nicht der Empfänger selbst, nicht „000“, kein Dupe
    assert [q.id for q in got] == [1, 5, 6]
    assert qtcmod.give_line(got[0]) == ("1001", "DL1ABC", "12")
    # schon gemeldet (an wen auch immer) -> nicht noch einmal
    done = [qtcmod.Qtc(sender="K1ABC", receiver="F5XYZ", series=1, total=1, qso_time="1001",
                       qso_call="DL1ABC", qso_nr="12", qso_id=1)]
    assert [q.id for q in qtcmod.give_candidates(QSOS, done, "G4AAA", c.dupe_key)] == [5, 6]
    # auch ohne qso_id (z. B. von Hand geändert): Zeit + Call + Nummer
    done[0].qso_id = 0
    assert [q.id for q in qtcmod.give_candidates(QSOS, done, "G4AAA", c.dupe_key)] == [5, 6]
    # /P zählt als dieselbe Station
    assert 1 not in [q.id for q in qtcmod.give_candidates(QSOS, [], "DL1ABC/P", c.dupe_key)]


def test_series_limits_and_receiver(cty):
    c, _s = make(cty)
    rec = [qtcmod.Qtc(sender="W1AW", series=9, total=1, qso_call="X", qso_nr="1")]
    given = [qtcmod.Qtc(sender="K1ABC", receiver="DL1ABC", series=s, total=3, qso_nr="1")
             for s in (1, 2, 2)]
    assert qtcmod.next_own_series([]) == 1
    assert qtcmod.next_own_series(rec + given) == 3          # empfangene zählen nicht
    assert qtcmod.sent_to(given, "dl1abc") == 3
    assert qtcmod.give_remaining(given, "DL1ABC") == 7
    assert qtcmod.received_from(rec + given, "K1ABC") == 0   # gegebene sind nicht „empfangen“
    assert qtcmod.receiver_problem(c, "W1AW", "K1ABC", []) == \
        "QTCs gehen nur an Stationen in Europa"
    assert qtcmod.receiver_problem(c, "K1ABC/P", "K1ABC", []) == "Das ist dein eigenes Rufzeichen"
    assert qtcmod.receiver_problem(c, "DL1ABC", "K1ABC", []) == ""
    full = [qtcmod.Qtc(sender="K1ABC", receiver="DL1ABC", series=1, total=10)] * 10
    assert "schon 10 QTCs" in qtcmod.receiver_problem(c, "DL1ABC", "K1ABC", full)
    assert qtcmod.cw_header(4, 10) == "QTC 4/10"
    assert qtcmod.cw_line(("1307", "DL1ABC", "042")) == "1307 DL1ABC 042"


def test_db_upgrade_and_cabrillo(cty, tmp_path):
    p = tmp_path / "alt.ggh"
    # Log von vor 0.9.4: Tabelle qtc ohne die neuen Spalten
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE qtc (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT NOT NULL, "
                "band TEXT NOT NULL, mode TEXT NOT NULL, freq INTEGER NOT NULL DEFAULT 0, "
                "sender TEXT NOT NULL, series INTEGER NOT NULL DEFAULT 0, total INTEGER NOT "
                "NULL DEFAULT 0, qso_time TEXT NOT NULL, qso_call TEXT NOT NULL, qso_nr TEXT "
                "NOT NULL)")
    con.execute("INSERT INTO qtc (time, band, mode, sender, qso_time, qso_call, qso_nr) "
                "VALUES ('2026-08-08 09:00:00', '20', 'CW', 'W1AW', '0800', 'OK1AA', '5')")
    con.commit()
    con.close()
    db = LogDB(p)
    old = db.all_qtcs()
    assert len(old) == 1 and not old[0].given and old[0].receiver == ""
    c, s = make(cty)
    for q in QSOS:
        db.add(q)
    t = qtcmod.Qtc(time="2026-08-08 10:28:00", band="15", mode="CW", freq=21_011_000,
                   sender="K1ABC", receiver="DL1XYZ", series=7, total=10, qso_time="1020",
                   qso_call="SP5AAA", qso_nr="431", qso_id=5)
    db.add_qtcs([t])
    got = [q for q in db.all_qtcs() if q.given]
    assert got[0].receiver == "DL1XYZ" and got[0].qso_id == 5
    s.rebuild(QSOS)
    s.set_qtcs(1)
    txt = cabrillo(c, {"mycall": "K1ABC"}, QSOS, s, got)
    line = [ln for ln in txt.splitlines() if ln.startswith("QTC:")][0]
    # Reihenfolge laut DARC: … EMPFÄNGER SERIE GEBER …
    assert line.split() == ["QTC:", "21011", "CW", "2026-08-08", "1028", "DL1XYZ", "7/10",
                            "K1ABC", "1020", "SP5AAA", "431"]
    db.close()


def test_qtc_announcement_off_by_default():
    class Sp:
        ok = True
        said = []

        def say(self, t):
            self.said.append(t)

        def stop(self):
            pass

    sp = Sp()
    a = speech.Announcer({"announce_enabled": True, "announce_events": {}}, sp)
    a.qtc("1 3 0 7")
    assert sp.said == []
    a.cfg["announce_events"] = {"qtc": True}
    a.qtc("1 3 0 7")
    assert sp.said == ["1 3 0 7"]
    assert a.wants("dupe")                                   # andere bleiben von sich aus an


SCRIPT = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
from gogoham.contests import Qso
from gogoham.db import DEFAULT_META, LogDB
from gogoham.gui import main_window, qtc_dialog
main_window.MainWindow._welcome = lambda self: None
main_window.MainWindow._ask_scp = lambda self, *a, **k: None
main_window.MainWindow._start_daily_update = lambda self, wait=10.0: None
out = {}
p = Path(sys.argv[2]) / "wae.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="wae-cw", mycall="K1ABC"))
for i, (call, nr, t) in enumerate([("DL1ABC", "12", "10:01"), ("G4AAA", "7", "10:05"),
                                   ("SP5AAA", "431", "10:20"), ("OK1XYZ", "88", "10:30")], 1):
    db.add(Qso(time=f"2026-08-08 {t}:00", call=call, band="20", mode="CW", freq=14020000,
               rst_s="599", rst_r="599", exch_s=f"{i:03d}", exch_r=nr))
db.close()
w = main_window.MainWindow()
w.open_log(str(p)); app.processEvents()
w.cb_mode.setCurrentText("CW")
out["hint"] = w._qtc_hint("G4AAA")
sent = []
w._send_cw = lambda text, warn=False: sent.append(text)
w.ed_call.setText("G4AAA")
class Drive(qtc_dialog.QtcGiveDialog):
    def exec(self):
        out["series"] = self.lbl_series.text()
        out["rows"] = self.tbl.rowCount()
        self.tbl.setFocus()
        self.enter()                     # QTC 1/3
        self.enter()                     # Zeile 1
        self.repeat()                    # F2: noch einmal
        self.enter()                     # Zeile 1 bestätigt, Zeile 2
        self.enter()                     # Zeile 2 bestätigt, Zeile 3
        out["now"] = self.lbl_now.text()
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
        self.finish()                    # Zeile 3 nicht bestätigt
        return self.result != [] and 1
main_window.QtcGiveDialog = Drive
w.receive_qtc()
out["sent"] = sent
out["qtcs"] = [[q.receiver, q.series, q.total, q.qso_call] for q in w.qtcs]
out["score"] = w.scorer.qtc_points
out["after"] = w._qtc_hint("G4AAA")
db = LogDB(p); out["saved"] = len(db.all_qtcs()); db.close()
# zweite Serie an eine andere Station: Nummer 2, ohne die schon gemeldeten QSOs
w.ed_call.setText("SP5AAA")
class Look(qtc_dialog.QtcGiveDialog):
    def exec(self):
        out["second"] = [self.lbl_series.text(),
                         [self.tbl.item(r, 2).text() for r in range(self.tbl.rowCount())]]
        return 0
main_window.QtcGiveDialog = Look
w.receive_qtc()
w._dirty = False
print(json.dumps(out))
'''


def test_gui_give_flow(tmp_path):
    pytest.importorskip("PySide6")
    data = tmp_path / "data" / "gogoham"
    data.mkdir(parents=True)
    shutil.copy(HERE / "cty_sample.dat", data / "cty.dat")
    env = {"QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path),
           "XDG_CONFIG_HOME": str(tmp_path / "cfg"), "XDG_DATA_HOME": str(tmp_path / "data"),
           "PATH": "/usr/bin:/bin"}
    (tmp_path / "cfg" / "gogoham").mkdir(parents=True)
    (tmp_path / "cfg" / "gogoham" / "config.json").write_text(json.dumps(
        {"rig_enabled": False, "wsjtx_enabled": False, "language": "de"}))
    r = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT), str(tmp_path)],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["hint"] == "QTC möglich an G4AAA: noch 10 von 10 (Strg+Q)"
    assert out["series"] == "QTC 1/3" and out["rows"] == 3
    assert out["sent"] == ["QTC 1/3", "1001 DL1ABC 12", "1001 DL1ABC 12", "1020 SP5AAA 431",
                           "1030 OK1XYZ 88"]
    assert out["now"] == "1030 OK1XYZ 88"
    # nur die zwei bestätigten zählen; Serie bleibt wie angesagt 1/3
    assert out["qtcs"] == [["G4AAA", 1, 3, "DL1ABC"], ["G4AAA", 1, 3, "SP5AAA"]]
    assert out["score"] == 2 and out["saved"] == 2
    assert out["after"] == "QTC möglich an G4AAA: noch 8 von 10 (Strg+Q)"
    assert out["second"] == ["QTC 2/2", ["G4AAA", "OK1XYZ"]]
