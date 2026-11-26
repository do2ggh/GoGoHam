"""0.8.21: Contest-Kalender – Termine, Filter, Erinnerung, .ics-Export, Log anlegen."""

import json
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path

from gogoham import contestcal as cc
from gogoham.contests import CONTESTS, contest_count

HERE = Path(__file__).parent
NOW = datetime(2026, 11, 14, 15, 0)            # OK/OM DX CW läuft (12:00–12:00 UTC)


def test_entries_sorted_one_per_contest():
    items = cc.entries(CONTESTS, NOW)
    assert len(items) == contest_count()          # ohne das freie Log (0.10.18)
    assert [x.start for x in items] == sorted(x.start for x in items)
    # ab 0.10.7 läuft auch WAE RTTY (Sa 00 UTC) – vor OK/OM (Sa 12 UTC)
    assert items[0].cid == "podxs-tp-nov" and items[0].running(NOW)    # 0.10.37
    assert items[1].cid == "wae-rtty" and items[1].running(NOW)
    assert items[2].cid == "jidx-ph" and items[2].running(NOW)         # ab 0.10.32
    assert items[3].cid == "okom-cw" and items[3].running(NOW)
    assert items[4].cid == "lzdx" and items[4].start == datetime(2026, 11, 21, 12)   # ab 0.8.31
    assert items[5].cid == "aoec-160" and items[5].start == datetime(2026, 11, 21, 16)
    assert items[6].cid == "rsgb-160-nov" and items[6].start == datetime(2026, 11, 21, 20)  # 0.10.36
    assert items[7].cid == "arrl-ss-ssb" and items[7].start == datetime(2026, 11, 21, 21)  # 0.10.33
    assert items[8].cid == "cqww-cw" and items[8].start == datetime(2026, 11, 28)
    assert all(x.end > NOW for x in items)


def test_entries_two_years_for_export():
    items = cc.entries(CONTESTS, NOW, count=2)
    cq = [x for x in items if x.cid == "cqww-cw"]
    assert [x.start.year for x in cq] == [2026, 2027]


def test_kinds_and_filter():
    k = {x.cid: x.kinds for x in cc.entries(CONTESTS, NOW)}
    assert k["cqww-cw"] == {"CW"}
    assert k["cqww-ssb"] == {"SSB"}
    assert k["ww-digi"] == {"DIGI"}
    assert k["arrl-10"] == {"CW", "SSB"}
    assert "UKW" in k["iaru-vhf"] and "UKW" in k["iaru-uhf"]
    assert "UKW" not in k["cqww-cw"]
    items = cc.entries(CONTESTS, NOW)
    ukw = cc.filtered(items, {"UKW"})
    assert {x.cid for x in ukw} == {"iaru-vhf", "iaru-uhf", "darc-vhf", "darc-ukw-spring", "darc-microwave", "marconi-vhf", "darc-ukw-fd-winter", "darc-ukw-fd-summer",
                                   "franken-k", "franken-l", "bbt-winter-1", "bbt-winter-2",
                                   "bbt-summer-1", "bbt-summer-2", "schwaben-ukw",
                                   "alpe-adria-vhf", "canada-day", "arrl-digi",   # auch 6 m/2 m
                                   "alpe-adria-uhf", "iaru-50", "iaru-70", "cqww-vhf",
                                   "cqww-vhf-digi", "arrl-vhf-jun", "arrl-vhf-sep",  # 0.10.33
                                   "txqp", "nyqp",  # 0.10.36: auch UKW
                                   "ncqp", "wa-salmon-run", "podxs-stpat"}  # 0.10.37: 6 m/2 m
    assert cc.filtered(items, set()) == []                      # nichts gewählt = nichts (0.8.21.1)
    assert len(cc.filtered(items, set(cc.KINDS))) == len(items)
    assert not any(x.cid == "cqww-ssb" for x in cc.filtered(items, {"CW"}))


def test_status_and_reminder():
    items = cc.entries(CONTESTS, NOW)
    assert cc.status(items[0], NOW).startswith("läuft")              # Triple Play (0.10.37)
    assert cc.status(items[1], NOW).startswith("läuft")
    assert cc.status(items[2], NOW).startswith("läuft")              # WAE RTTY und OK/OM CW
    assert cc.status(items[3], NOW).startswith("läuft")              # + JIDX SSB (0.10.32)
    assert cc.status(items[4], NOW) == "in 7 Tagen"                   # LZ DX, AOEC 160 m
    assert cc.status(items[8], NOW) == "in 14 Tagen"
    tomorrow = cc.Entry("x", "X", datetime(2026, 11, 15, 20), datetime(2026, 11, 16), frozenset())
    assert cc.status(tomorrow, NOW) == "morgen"
    soon = cc.Entry("x", "X", datetime(2026, 11, 14, 21), datetime(2026, 11, 15), frozenset())
    assert cc.status(soon, NOW) == "in 06:00 h"
    text = cc.reminder(items, NOW)
    assert "WAE DX Contest RTTY" in text and "weitere" in text and "CQ WW DX CW" not in text   # 14 Tage: zu weit weg
    later = datetime(2026, 11, 22)
    assert cc.reminder(cc.entries(CONTESTS, later), later).count("CQ WW DX CW") == 1
    assert cc.reminder([], NOW) == ""


def test_ics():
    items = cc.filtered(cc.entries(CONTESTS, NOW, count=2), {"CW"})
    text = cc.to_ics(items, NOW)
    lines = text.split("\r\n")
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-2] == "END:VCALENDAR" and lines[-1] == ""
    assert text.count("BEGIN:VEVENT") == len(items)
    assert "UID:cqww-cw-2026@gogoham" in text and "UID:cqww-cw-2027@gogoham" in text
    assert "DTSTART:20261128T000000Z" in text and "DTEND:20261130T000000Z" in text
    assert all(len(ln.encode("utf-8")) <= 75 for ln in lines)   # gefaltet (RFC 5545)
    # gefaltete Zeilen ergeben zusammengesetzt wieder den Text (Komma escaped)
    joined = text.replace("\r\n ", "")
    assert "SUMMARY:ARRL 10 m (SSB/CW)" in joined
    assert "\\," in joined or "," not in "".join(x.name for x in items)


SCRIPT = r'''
import json, sys
from datetime import datetime
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
import gogoham.cty as cty
cty.CtyDB.load_default = classmethod(lambda c: c.from_file(Path(sys.argv[3])))
from gogoham import config as cfgmod
cfg = cfgmod.load(); cfg.update(rig_enabled=False, wsjtx_enabled=False); cfgmod.save(cfg)
from gogoham.db import DEFAULT_META, LogDB
from gogoham.contests import CONTESTS
from gogoham.gui import main_window, dialogs
from gogoham.gui.calendar_dialog import CalendarDialog
main_window.MainWindow._welcome = lambda self: None
main_window.MainWindow._ask_scp = lambda self, *a, **k: None
main_window.MainWindow._start_daily_update = lambda self, wait=10.0: None
out = {}

# Dialog allein: Filter, Doppelklick -> on_new_log(cid, Jahr)
got, saved = [], []
c = {}
d = CalendarDialog(CONTESTS, c, on_new_log=lambda cid, y: got.append([cid, y]),
                   on_change=lambda: saved.append(1), now=datetime(2026, 11, 14, 15))
out["rows"] = d.tbl.rowCount()
out["first"] = [d.tbl.item(0, 3).text(), d.tbl.item(0, 5).text()]
d.filters["SSB"].setChecked(False); d.filters["DIGI"].setChecked(False)
d.filters["UKW"].setChecked(False); d.filters["RTTY"].setChecked(False)
out["cw_rows"] = d.tbl.rowCount()
out["cfg_kinds"] = c.get("calendar_filter")
out["all_after_cw"] = d.chk_all.isChecked()
d.filters["CW"].setChecked(False)                      # nichts gewählt -> nichts
out["none"] = [d.tbl.rowCount(), d.chk_all.isChecked(), d.empty.isVisibleTo(d),
               c.get("calendar_filter")]
d.chk_all.click()                                      # „Alle“ -> alles wieder an
out["all"] = [d.tbl.rowCount(), d.chk_all.isChecked(),
              all(x.isChecked() for x in d.filters.values()), c.get("calendar_filter")]
d.chk_all.click()                                      # „Alle“ aus -> alles aus
out["all_off"] = [d.tbl.rowCount(), any(x.isChecked() for x in d.filters.values())]
d.filters["CW"].setChecked(True)
d.tbl.selectRow(1)
out["btn"] = d.btn_log.isEnabled()
d.new_log()
out["got"] = got
d.remind.setChecked(False)
out["remind"] = c.get("calendar_remind")
out["saved"] = len(saved) > 0

# Hauptfenster: Log anlegen aus dem Kalender -> Contest vorbelegt, Name mit dem Contest-Jahr
p = Path(sys.argv[2]) / "x.ggh"
db = LogDB(p); db.set_meta(dict(DEFAULT_META, contest="cqww-ssb", mycall="DO2GGH")); db.close()
w = main_window.MainWindow(); w.open_log(str(p)); w.show()
for _ in range(3): app.processEvents()
seen = {}
def fake_exec(self):
    seen["contest"] = self.contest.currentData()
    return False                                  # abbrechen
dialogs.LogSettingsDialog.exec = fake_exec
main_window.LogSettingsDialog.exec = fake_exec
w.cfg["rules_auto_update"] = False
w.new_log("iaru-vhf", 2027)
out["preselect"] = seen.get("contest")
# Erinnerung beim Start (Uhr fest: OK/OM DX CW läuft)
from datetime import timezone
real_now = main_window.utc_now
main_window.utc_now = lambda: datetime(2026, 11, 14, 15, tzinfo=timezone.utc)
w.cfg["calendar_remind"] = True
w.cfg["calendar_filter"] = []
w._calendar_reminder()
out["msg_nofilter"] = w.statusBar()._msg if hasattr(w.statusBar(), "_msg") else ""
w.cfg["calendar_filter"] = ["CW", "SSB", "DIGI", "UKW"]
w._calendar_reminder()
out["msg"] = w.statusBar()._msg if hasattr(w.statusBar(), "_msg") else w.statusBar().currentMessage()
w.statusBar().showMessage("")
w.cfg["calendar_remind"] = False
w._calendar_reminder()
out["msg_off"] = w.statusBar()._msg if hasattr(w.statusBar(), "_msg") else ""
main_window.utc_now = real_now
w.close()
print("RESULT " + json.dumps(out))
'''


def test_calendar_gui(tmp_path):
    data, cfg, logs = tmp_path / "data", tmp_path / "cfg", tmp_path / "logs"
    (cfg / "gogoham").mkdir(parents=True)
    (data / "gogoham").mkdir(parents=True)
    logs.mkdir()
    env = {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(cfg), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin",
           "TZ": "Europe/Berlin"}
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT), str(HERE.parent),
                        str(logs), str(HERE / "cty_sample.dat")],
                       capture_output=True, text=True, env=env, timeout=90)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, r.stderr[-3000:]
    o = json.loads(lines[-1][7:])
    assert o["rows"] == contest_count()
    assert o["first"][0].startswith("PODXS 070 Club Triple Play") and o["first"][1].startswith("läuft")  # 0.10.37
    cw = [x for x in cc.entries(CONTESTS, NOW) if "CW" in x.kinds]
    assert o["cw_rows"] == len(cw)
    assert o["cfg_kinds"] == ["CW"]
    assert o["all_after_cw"] is False
    assert o["none"] == [0, False, True, []]
    assert o["all"] == [contest_count(), True, True, ["CW", "SSB", "RTTY", "DIGI", "UKW"]]
    assert o["all_off"] == [0, False]
    assert o["btn"] is True
    assert o["got"] == [["lzdx", 2026]]
    assert o["remind"] is False and o["saved"]
    assert o["preselect"] == "iaru-vhf"
    assert o["msg"].startswith("Contest-Kalender: ") and "OK/OM DX CW (läuft" in o["msg"]
    assert o["msg_off"] == ""
    assert not o["msg_nofilter"].startswith("Contest-Kalender")   # 0.9.1: Call-History-Meldung erlaubt
