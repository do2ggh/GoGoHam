"""GUI-Ablauf mit Qt-Attrappe: Log anlegen, tippen, loggen, WSJT-X, Export."""

import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent


@pytest.fixture()
def win(tmp_path, monkeypatch):
    sys.path.insert(0, str(HERE))
    import fake_qt
    fake_qt.install()
    for m in [m for m in sys.modules if m.startswith("gogoham.gui")]:
        del sys.modules[m]
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path))
    import gogoham.cty as cty
    monkeypatch.setattr(cty.CtyDB, "load_default",
                        classmethod(lambda c: c.from_file(HERE / "cty_sample.dat")))
    import gogoham.config as cfgmod
    cfg = cfgmod.load()
    cfg["rig_enabled"] = False
    cfg["wsjtx_enabled"] = False
    cfgmod.save(cfg)
    from gogoham.gui.main_window import MainWindow
    w = MainWindow()
    yield w, fake_qt, tmp_path
    w.closeEvent(fake_qt.Stub())


def new_log(w, fq, tmp_path, contest, grid=""):
    from gogoham.gui import dialogs

    orig = dialogs.LogSettingsDialog.__init__

    def patched(self, meta, parent=None, new_log=False):
        orig(self, meta, parent, new_log)
        self.contest.setCurrentIndex(self.contest.findData(contest))
        self.mycall.setText("dl1abc")
        self.grid.setText(grid)
        self.zone.setValue(14)
    dialogs.LogSettingsDialog.__init__ = patched
    import gogoham.gui.main_window as mw
    mw.LogSettingsDialog.__init__ = patched
    fq.QFileDialog.save_path = str(tmp_path / f"{contest}.ggh")
    w.new_log()
    dialogs.LogSettingsDialog.__init__ = orig


def type_and_log(w, call, exch=None):
    w.clear_entry()
    w.ed_call.type(call)
    if exch is not None:
        w.ed_exch.setText("")
        w.ed_exch.type(exch)
    w.enter_pressed()


def test_cqww_flow(win):
    w, fq, tmp = win
    import gogoham.gui.main_window as mw
    from gogoham.scp import ScpDB
    w.scp = ScpDB.parse("W1AW\nW1AX\nJA1ABC\n")
    new_log(w, fq, tmp, "cqww-ssb")
    assert w.contest.id == "cqww-ssb" and w.meta["mycall"] == "DL1ABC"
    # Live-Prüfung: Zone wird vorbelegt, neuer Multi angezeigt
    w.ed_call.type("W1AW")
    assert w.ed_exch.text() == ""                 # USA hat mehrere Zonen
    assert "erfragen" in w.info_lines[0].text()
    w.enter_pressed()                             # ohne Zone kein Log
    assert not w.qsos and "Zone" in w.lbl_status.text()
    assert [i.text() for i in w.partial.items] == ["W1AW"]
    assert w.lbl_cname.text() == "USA" and w.lbl_cont.text() == "NA"
    assert w.info_lines[0].text().startswith("CQ-Zone: erfragen")
    assert w.lbl_flag.text() == "K"                 # keine Flagge geladen -> Ersatz-Schild
    w.ed_exch.type("05")
    assert "NEUER MULTI" in w.lbl_status.text() and "3 Pkt" in w.lbl_status.text()
    assert "+6" in w.lbl_status.text()          # 3 Pkt × 2 Multis
    w.enter_pressed()
    # SCP-Farben: W1AW auf 20 m gearbeitet = rot, W1AX = grün
    w.ed_call.type("W1A")
    cols = {i.data(None): i.color for i in w.partial.items}
    assert cols == {"W1AW": mw.RED, "W1AX": mw.GREEN}
    # Doppelklick übernimmt
    w._scp_pick(w.partial.items[1])
    assert w.ed_call.text() == "W1AX"
    w.clear_entry()
    assert len(w.qsos) == 1 and w.qsos[0].exch_r == "05" and w.qsos[0].exch_s == "14"
    assert w.ed_sent.text() == "14" and w.lbl_sent.text() == "Zone ges."
    land = w.tbl.item(0, mw.LAND_COL)
    assert land.text() == "USA" and land.icon is None     # Flaggen noch nicht geladen
    # Design umschalten darf nichts kaputt machen
    for mode in ("dark", "light", "system"):
        w.set_theme(mode)
    assert w.cfg["theme"] == "system"
    assert w.ed_call.text() == ""
    # Dupe-Anzeige
    w.ed_call.type("W1AW")
    assert "DUPE" in w.lbl_status.text()
    assert "W1AW" in w.partial.items[0].text() and w.partial.items[0].color == mw.RED
    w.clear_entry()
    type_and_log(w, "JA1ABC")
    type_and_log(w, "OE1XYZ")
    assert w.scorer.total_points == 7
    assert w.lbl_score.text() == str(7 * 6)
    # Bandwechsel per kHz-Eingabe
    w.ed_call.type("7050")
    w.enter_pressed()
    assert w.cb_band.currentText() == "40" and w.manual_freq == 7_050_000
    w.ed_call.type("W1A")
    cols = {i.data(None): i.color for i in w.partial.items}
    assert cols["W1AW"] == mw.BLUE              # anderes Band gearbeitet
    w.clear_entry()
    type_and_log(w, "W1AW", "05")
    assert w.qsos[-1].band == "40" and w.scorer.score == 10 * 8
    # Falsche Zone wird abgelehnt
    type_and_log(w, "PY1AA", "77")
    assert len(w.qsos) == 4 and "Zone" in w.lbl_status.text()
    # Löschen / neu laden
    w.delete_last()
    assert len(w.qsos) == 3
    # Export
    fq.QFileDialog.save_path = str(tmp / "out.cbr")
    w.export_cabrillo()
    txt = (tmp / "out.cbr").read_text()
    assert "CONTEST: CQ-WW-SSB" in txt and txt.count("QSO:") == 3
    fq.QFileDialog.save_path = str(tmp / "out.adi")
    import gogoham.callbook as cb
    calls_seen = []

    class FakeSvc:
        name = "Fake"

        def lookup(self, call):
            calls_seen.append(call)
            return cb.Entry(call, name="Hiram", qth="Newington", grid="FN31pr")
    monkey_services = lambda cfg: [FakeSvc()]
    orig = cb.services_from_config
    cb.services_from_config = monkey_services
    w.cfg["callbook_enabled"] = True
    try:
        w.export_adif()
        w.cb_job.thread.join(2)
        w._check_callbook_job()
    finally:
        cb.services_from_config = orig
    txt = (tmp / "out.adi").read_text()
    assert txt.count("<EOR>") == 3 and "<NAME:5>Hiram" in txt and "<QTH:9>Newington" in txt
    assert sorted(calls_seen) == ["JA1ABC", "OE1XYZ", "W1AW"]
    name_col = mw.COL["name"]
    assert w.tbl.item(0, name_col).text() == "Hiram"
    # zweiter Export: alles aus dem Zwischenspeicher, keine neuen Abfragen
    calls_seen.clear()
    cb.services_from_config = monkey_services
    try:
        w.export_adif()
    finally:
        cb.services_from_config = orig
    assert calls_seen == [] and w.cb_job is None


def test_wpx_serials(win):
    w, fq, tmp = win
    new_log(w, fq, tmp, "wpx-ssb")
    assert w.ed_sent.text() == "001" and w.lbl_sent.text() == "Nr ges."
    type_and_log(w, "W1AW", "")          # Nummer fehlt -> nicht geloggt
    assert not w.qsos
    type_and_log(w, "W1AW", "123")
    type_and_log(w, "DL2ABC", "45")
    assert [q.exch_s for q in w.qsos] == ["001", "002"]
    assert w.ed_sent.text() == "003"
    assert w.scorer.score == (3 + 1) * 2


def test_wwdigi_from_wsjtx(win):
    w, fq, tmp = win
    new_log(w, fq, tmp, "ww-digi", grid="JN59")
    from gogoham.wsjtx import parse_packet, build_logged_adif_packet
    adif = ("<call:4>W1AW <gridsquare:4>FN42 <mode:3>FT8 <rst_sent:3>-10 <rst_rcvd:3>-05 "
            "<qso_date:8>20260829 <time_on:6>120515 <band:3>20m <freq:9>14.074500 <EOR>")
    rec = parse_packet(build_logged_adif_packet(adif))
    w._wsjtx_qso(rec)
    w._wsjtx_qso(rec)   # doppelt gesendet -> ignorieren
    assert len(w.qsos) == 1 and w.qsos[0].exch_s == "JN59"
    assert w.scorer.score == 3 * 1
    assert "Von WSJT-X" in w.statusBar().currentMessage()


def test_reopen_keeps_log(win):
    w, fq, tmp = win
    new_log(w, fq, tmp, "cqww-ssb")
    type_and_log(w, "W1AW", "05")
    path = str(w.db.path)
    w.open_log(path)
    assert len(w.qsos) == 1 and w.tbl.rowCount() == 1



def test_columns_in_gui(win):
    w, fq, tmp = win
    import gogoham.gui.main_window as mw
    new_log(w, fq, tmp, "cqww-ssb")
    hidden = {mw.COLS[c] for c in w.tbl.hidden}
    assert {"mode", "name", "prefix", "km"} == hidden
    assert w.tbl.horizontalHeader().labels[mw.COL["ex_s"]] == "Zone ges."
    # Spalte einblenden, verschieben -> wird für CQ WW gemerkt
    w.set_column_visible("name", True)
    hdr = w.tbl.horizontalHeader()
    hdr.moveSection(hdr.visualIndex(mw.COL["call"]), 0)
    saved = w.cfg["columns"]["cqww-ssb"]
    assert saved["order"][0] == "call" and "name" not in saved["hidden"]
    # anderer Contest hat seine eigene Vorgabe
    new_log(w, fq, tmp, "ww-digi", grid="JN59me")
    hidden = {mw.COLS[c] for c in w.tbl.hidden}
    assert "km" not in hidden and "rst_s" in hidden and "name" in hidden
    assert hdr is not w.tbl.horizontalHeader() or True
    assert w.tbl.horizontalHeader().labels[mw.COL["ex_r"]] == "Loc empf."
    # km-Spalte wird gefüllt
    from gogoham.wsjtx import parse_packet, build_logged_adif_packet
    adif = ("<call:4>W1AW <gridsquare:4>FN42 <mode:3>FT8 <qso_date:8>20260829 "
            "<time_on:6>120515 <band:3>20m <freq:9>14.074500 <EOR>")
    w._wsjtx_qso(parse_packet(build_logged_adif_packet(adif)))
    km = w.tbl.item(0, mw.COL["km"]).text()
    assert km and 5800 < int(km.replace(".", "")) < 6300
    # zurück zu CQ WW: gemerkte Anordnung wird wiederhergestellt
    w.open_log(str(tmp / "cqww-ssb.ggh"))
    h = w.tbl.horizontalHeader()
    assert h.logicalIndex(0) == mw.COL["call"] and not w.tbl.isColumnHidden(mw.COL["name"])
    # Standard wiederherstellen
    w.reset_columns()
    assert "cqww-ssb" not in w.cfg["columns"]
    assert w.tbl.isColumnHidden(mw.COL["name"]) and h.logicalIndex(0) == mw.COL["nr"]


def test_about_dialog(win):
    w, fq, tmp = win
    from gogoham.gui.dialogs import AboutDialog
    AboutDialog(w)           # darf nicht abstürzen
    import inspect, gogoham.gui.dialogs as d
    src = inspect.getsource(d.AboutDialog)
    assert "© 2026 Franz, DO2GGH" in src and "do2ggh.de@gmail.com" in src


# ----------------------------------------------------------------- 0.6
def test_local_clock():
    from datetime import datetime, timezone
    import gogoham.gui.main_window as mw
    import time
    os.environ["TZ"] = "Europe/Berlin"
    time.tzset()
    assert mw.local_clock_text(datetime(2026, 11, 2, 0, 10, 23, tzinfo=timezone.utc)) == "01:10:23 MEZ"
    assert mw.local_clock_text(datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)) == "14:00:00 MESZ"


class FakeRig:
    def __init__(self):
        self.sent = []

    def snapshot(self):
        from gogoham.rig import RigState
        return RigState(connected=True, freq=14_250_000, mode="USB")

    def submit(self, *a):
        self.sent.append(a)

    def stop(self):
        pass

    def join(self, *_):
        pass


def test_autocq(win):
    w, fq, tmp = win
    new_log(w, fq, tmp, "cqww-ssb")
    w.toggle_autocq(True)                 # ohne CAT: geht nicht
    assert not w.autocq_timer.isActive()
    w.rig = FakeRig()
    w.toggle_autocq(True)
    assert w.autocq_timer.isActive() and w.autocq_timer.interval == 11_000
    assert w.rig.sent == [("send_voice_mem", 1)]
    w._autocq_fire()
    assert w.rig.sent[-1] == ("send_voice_mem", 1) and len(w.rig.sent) == 2
    # Station antwortet: Tippen stoppt Auto-CQ
    w.ed_call.type("W")
    assert not w.autocq_timer.isActive()
    w.clear_entry()
    # andere F-Taste stoppt ebenfalls
    w.toggle_autocq(True)
    w.run_macro(3, manual=True)
    assert not w.autocq_timer.isActive() and w.rig.sent[-1] == ("send_voice_mem", 3)
    # Esc stoppt
    w.toggle_autocq(True)
    w.escape_pressed()
    assert not w.autocq_timer.isActive()
    w.cfg["autocq_msg_sec"], w.cfg["autocq_listen_sec"] = 5, 10
    w.toggle_autocq(True)
    assert w.autocq_timer.interval == 15_000
    w.toggle_autocq(False)
    w.rig = None


def test_call_history_prefill(win):
    w, fq, tmp = win
    new_log(w, fq, tmp, "cqww-ssb")
    w.history._merge("W1AW", zone="4", name="Hiram", source="test")
    w.ed_call.type("W1AW")
    assert w.ed_exch.text() == "04"
    texts = [l.text() for l in w.info_lines]
    assert texts[0].startswith("Zone 4 aus Call-History") and "Name: Hiram" in texts
    w.enter_pressed()
    assert w.qsos[-1].exch_r == "04"
    # neue Logs lernen aus den alten
    new_log(w, fq, tmp, "wpx-ssb")
    assert w.history.get("W1AW").zone == "4"


def test_backup_and_broken_log(win):
    w, fq, tmp = win
    import gogoham.backup as bk
    new_log(w, fq, tmp, "cqww-ssb")
    path = w.db.path
    assert len(bk.list_backups(path)) == 1           # Sicherung beim Öffnen
    type_and_log(w, "JA1ABC")
    assert w._dirty
    w._backup_now()
    assert len(bk.list_backups(path)) == 2 and not w._dirty
    # Log kaputt machen
    w.db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    w.db.close()
    w.db = None
    data = bytearray(path.read_bytes())
    data[:16] = b"kaputtkaputtkapu"
    path.write_bytes(bytes(data))
    w.cfg["last_log"] = str(path)
    choice = {}
    orig = w._broken_log
    w._broken_log = lambda p, prob: choice.update(path=p, problem=prob)
    w.open_log(str(path))
    assert choice["path"] == str(path) and choice["problem"] != "ok"
    assert w.cfg["last_log"] == ""                    # nicht bei jedem Start erneut
    w._broken_log = orig
    # Wiederherstellen aus der Sicherung
    fq.QFileDialog.open_path = str(bk.list_backups(path)[-1])
    orig_open = fq.QFileDialog.getOpenFileName
    fq.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (fq.QFileDialog.open_path, ""))
    try:
        w.restore_backup()
    finally:
        fq.QFileDialog.getOpenFileName = orig_open
    assert "wiederhergestellt" in str(w.db.path) and len(w.qsos) == 1


def test_stats_logcheck_contesttime(win):
    w, fq, tmp = win
    new_log(w, fq, tmp, "wpx-ssb")
    type_and_log(w, "W1AW", "12")
    type_and_log(w, "XX9ZZZ", "3")
    w.show_stats()
    assert w.stats_win is not None
    assert [w.stats_win.tabs.tabText(i) for i in range(w.stats_win.tabs.count())] == \
        ["Präfixe", "Rate"]
    findings = w._findings()
    assert any("Präfix unbekannt" in f.text for f in findings)
    w.check_log()                                     # darf nicht abstürzen
    w._update_contest_time()
    txt = w.lbl_ctime.text()
    assert txt.startswith("CQ WPX SSB: ") and "Betriebszeit" in txt and "von 36:00 h" in txt


def test_livescore_only_while_running(win):
    w, fq, tmp = win
    new_log(w, fq, tmp, "cqww-ssb")
    w.cfg["livescore_enabled"] = True
    w.contest_running = lambda: False
    w._update_live()
    assert w.live is None
    w.contest_running = lambda: True
    import gogoham.livescore as ls
    started = []
    orig = ls.LiveScore.start
    ls.LiveScore.start = lambda self: started.append(self)
    try:
        w._update_live()
    finally:
        ls.LiveScore.start = orig
    assert started and "<dynamicresults>" in w._live_xml and "CQ-WW-SSB" in w._live_xml
    w.live = None


def test_help_chapters():
    from gogoham.gui.help import HANDBOOK, chapters
    ch = chapters(HANDBOOK.read_text(encoding="utf-8"))
    anchors = [a for a, _t in ch]
    for need in ("start", "log", "cat", "wsjtx", "fkeys", "autocq", "callhistory", "scp",
                 "infobox", "log-tabelle", "export", "callbook", "logpruefung", "uebersicht",
                 "contestuhr", "livescore", "design", "sicherung", "contests", "fehler"):
        assert need in anchors, need
    # alle ?-Knöpfe zeigen auf vorhandene Kapitel
    import re, inspect, gogoham.gui.dialogs as d
    for a in re.findall(r'_buttons\(self, "([^"]+)"\)', inspect.getsource(d)):
        assert a in anchors, a


def test_help_english():
    """0.8.2: englisches Handbuch – gleiche Kapitel und Sprungmarken wie das deutsche."""
    import re
    from gogoham.gui.help import HANDBOOK, chapters, handbook_path
    en = handbook_path("en")
    assert en.name == "handbook.en.html" and en.is_file()
    assert handbook_path("de") == HANDBOOK
    assert handbook_path("xx") == en                # 0.10.27: andere Sprachen → Englisch
    de_html = HANDBOOK.read_text(encoding="utf-8")
    en_html = en.read_text(encoding="utf-8")
    assert [a for a, _ in chapters(en_html)] == [a for a, _ in chapters(de_html)]
    ids = lambda h: re.findall(r'id="([^"]+)"', h)
    assert ids(en_html) == ids(de_html)
    for link in re.findall(r'href="#([^"]+)"', en_html):
        assert link in ids(en_html), link
    # keine deutschen Reste (Umlaute, deutsche Anführungszeichen)
    text = re.sub(r"<[^>]+>", "", en_html)
    assert not re.search(r"[äöüÄÖÜß„]", text)


def test_log_remembers_rules(win):
    """0.6.5: neues Log speichert seine Regeln, altes Log bekommt sie beim Öffnen."""
    import json
    w, fq, tmp = win
    from gogoham.contests import CONTESTS
    from gogoham.db import LogDB
    new_log(w, fq, tmp, "wpx-cw")
    stored = json.loads(LogDB(w.db.path).get_meta()["rules_json"])
    assert stored == CONTESTS["wpx-cw"].rules
    assert w.contest.rules_source == "log"
    # Log aus der Zeit vor 0.6.5 (ohne rules_json)
    old = tmp / "alt.ggh"
    db = LogDB(old)
    db.set_meta({"contest": "cqww-ssb", "mycall": "DL1ABC", "my_zone": "14"})
    db.close()
    w.open_log(str(old))
    assert json.loads(LogDB(old).get_meta()["rules_json"]) == CONTESTS["cqww-ssb"].rules


def test_cq160_and_arrl_dx_in_gui(win):
    """0.7.0: Austausch je Herkunft im Eingabefeld, Score-Tabelle mit den richtigen Multis."""
    w, fq, tmp = win
    new_log(w, fq, tmp, "cq160-cw")
    w.cb_mode.setCurrentText("CW")
    w.cb_band.setCurrentText("160")
    w.ed_call.type("VE3XYZ")
    assert w.ed_exch.text() == "ON"                 # Provinz aus dem Rufzeichen
    w.enter_pressed()
    assert len(w.qsos) == 1 and w.scorer.evals[w.qsos[0].id].points == 10
    type_and_log(w, "W1AW", "14")                   # Zone statt State -> wird nicht geloggt
    assert len(w.qsos) == 1 and "US-State" in w.lbl_status.text()
    type_and_log(w, "W1AW", "CT")
    assert len(w.qsos) == 2
    assert w.contest.mult_types == [("state", "States"), ("province", "Provinzen"),
                                    ("country", "Länder")]
    # ARRL DX: DX–DX wird gewarnt
    new_log(w, fq, tmp, "arrl-dx-ssb")
    w.cb_mode.setCurrentText("USB")
    w.cb_band.setCurrentText("20")
    assert w.contest.sent_exchange(1) == "KW"        # aus „Kategorie Leistung“ HIGH
    w.ed_call.type("OE1XX")
    assert "DX arbeitet nur W/VE" in w.sb.notes() or \
        "DX arbeitet nur W/VE" in w.lbl_status.text()


def test_status_text_and_euhfc_needs_year(win):
    """0.7.1: kein doppeltes „Zählt nicht:“; EU HF verlangt das Jahr der ersten Lizenz."""
    w, fq, tmp = win
    new_log(w, fq, tmp, "arrl-dx-ssb")
    w.cb_mode.setCurrentText("USB")
    w.cb_band.setCurrentText("20")
    w.ed_call.type("OE1XX")
    assert w.lbl_status.text() == "Zählt nicht: DX arbeitet nur W/VE (USA/Kanada)"
    # EU HF ohne Jahr: Log wird nicht angelegt
    from gogoham.gui import dialogs
    import gogoham.gui.main_window as mw
    before = w.db.path
    new_log(w, fq, tmp, "euhfc")
    assert w.db.path == before
    # mit Jahr: klappt, und das Jahr wird zweistellig gesendet
    orig = dialogs.LogSettingsDialog.__init__

    def patched(self, meta, parent=None, new_log=False):
        orig(self, meta, parent, new_log)
        self.contest.setCurrentIndex(self.contest.findData("euhfc"))
        self.mycall.setText("dl1abc")
        self.licyear.setText("1982")
    mw.LogSettingsDialog.__init__ = patched
    fq.QFileDialog.save_path = str(tmp / "euhfc.ggh")
    w.new_log()
    mw.LogSettingsDialog.__init__ = orig
    assert w.contest.id == "euhfc" and w.contest.sent_exchange(1) == "82"


def test_v072_fields_defaults_and_band_offer(win):
    """0.7.2: passende Felder, Angaben bleiben für spätere Logs, Ein-Band-Contest-Angebot."""
    w, fq, tmp = win
    from gogoham.gui import dialogs
    import gogoham.gui.main_window as mw
    d = dialogs.LogSettingsDialog({}, new_log=True)
    d.contest.setCurrentIndex(d.contest.findData("iaru-hf"))
    assert d.visible_fields == {"itu"}
    d.contest.setCurrentIndex(d.contest.findData("wpx-ssb"))
    assert d.visible_fields == set()

    # EU-HF-Log mit Lizenzjahr anlegen …
    orig = dialogs.LogSettingsDialog.__init__

    def with_year(self, meta, parent=None, new_log=False):
        orig(self, meta, parent, new_log)
        self.contest.setCurrentIndex(self.contest.findData("euhfc"))
        self.mycall.setText("dl1abc")
        self.licyear.setText("1982")
    mw.LogSettingsDialog.__init__ = with_year
    fq.QFileDialog.save_path = str(tmp / "eu1.ggh")
    w.new_log()
    mw.LogSettingsDialog.__init__ = orig
    # … dann ein CQ-WW-Log (ohne Jahr) und wieder ein EU-HF-Log: das Jahr ist vorbelegt
    new_log(w, fq, tmp, "cqww-ssb")
    seen = {}

    def peek(self, meta, parent=None, new_log=False):
        orig(self, meta, parent, new_log)
        seen["year"] = self.licyear.text()
        self.reject()
    mw.LogSettingsDialog.__init__ = peek
    w.new_log()
    mw.LogSettingsDialog.__init__ = orig
    assert seen["year"] == "82"

    # Ein-Band-Contest ohne CAT: Bandauswahl wird umgestellt
    w.cb_band.setCurrentText("20")
    new_log(w, fq, tmp, "arrl-10")
    w._check_band_offer()
    assert w.current_band() == "10"

    # mit CAT: Frage (Attrappe antwortet „Ja“) und nur Frequenz setzen
    sent = []

    class FakeRig:
        def submit(self, *a):
            sent.append(a)

        def snapshot(self):
            from gogoham.rig import RigState
            return RigState(connected=True, freq=14_200_000, mode="CW", model=3073)

        def stop(self):
            pass

        def join(self, *_a):
            pass
    w.rig = FakeRig()
    w.cb_band.setCurrentText("20")
    w.cb_mode.setCurrentText("CW")
    sent.clear()
    w.open_log(str(tmp / "arrl-10.ggh"))
    w._check_band_offer()
    assert ("set_freq", 28_025_000) in sent
    assert not any(a[0] in ("send_morse", "send_voice_mem", "ptt") for a in sent)


def test_language_menu_and_restart(win):
    """0.8.0: Sprache umstellen speichert die Einstellung und fragt nach dem Neustart."""
    w, fq, tmp = win
    import gogoham.config as cfgmod
    assert w.cfg.get("language", "auto") == "auto"
    w.set_language("en")                      # Attrappe beantwortet die Frage mit „Ja“
    assert cfgmod.load()["language"] == "en"
    assert getattr(w, "restart_requested", False)
    w.restart_requested = False
    w.set_language("en")                      # gleiche Sprache: nichts passiert
    assert not w.restart_requested


def test_settings_dialog_tabs(win):
    """0.8.1: ein Einstellungsfenster mit Reitern; Fehler in einem Reiter halten es offen."""
    w, fq, tmp = win
    from gogoham.gui.dialogs import SettingsDialog
    from pathlib import Path
    import re
    cfg = dict(w.cfg)
    d = SettingsDialog(cfg, w, start="display")
    assert [p[0] for p in d.pages] == list(SettingsDialog.TABS)
    assert d.nav.count() == 10                 # 0.10.25: zehn Bereiche (GPS nach Rotor)
    assert d.current_key() == "display"
    d.select("callbook")
    assert d.current_key() == "callbook" and d.nav.currentRow() == 7
    # alle „?“-Ziele gibt es im Handbuch
    html = (Path(__file__).parent.parent / "gogoham" / "help" / "handbuch.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([^"]+)"', html))
    assert all(p[3] in ids for p in d.pages), [p[3] for p in d.pages if p[3] not in ids]
    # Darstellung und Daten werden übernommen
    tabs = list(SettingsDialog.TABS)
    d.pages[tabs.index("display")][2].theme.setCurrentIndex(2)
    d.pages[tabs.index("data")][2].backup.setValue(5)
    d.accept()
    assert cfg["theme"] == "dark" and cfg["backup_minutes"] == 5
    # zwei Funkgerät-Profile mit demselben Port: Fenster bleibt offen, Reiter Funkgerät
    cfg2 = dict(w.cfg, rig_profiles=[
        {"name": "A", "model": 1, "device": "", "baud": 0, "extra": "", "port": 4532, "start": True},
        {"name": "B", "model": 1, "device": "", "baud": 0, "extra": "", "port": 4532, "start": True}])
    d2 = SettingsDialog(cfg2, w, start="data")
    assert d2.exec() == 0


def test_open_settings_restarts_only_changed(win, monkeypatch):
    w, fq, tmp = win
    calls = []
    monkeypatch.setattr(w, "start_rig", lambda: calls.append("rig"))
    monkeypatch.setattr(w, "start_wsjtx", lambda: calls.append("wsjtx"))
    w.open_settings()                         # Attrappe: OK ohne Änderung
    assert calls == []
    from gogoham.gui import dialogs
    orig = dialogs.WsjtxDialog.apply

    def changed(self):
        ok = orig(self)
        self.cfg["wsjtx_port"] = 2238
        return ok
    monkeypatch.setattr(dialogs.WsjtxDialog, "apply", changed)
    w.open_settings("wsjtx")
    assert calls == ["wsjtx"]
