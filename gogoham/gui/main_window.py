"""Hauptfenster: Eingabezeile, Live-Prüfung, Log und Punktestand."""

from __future__ import annotations

import json
import re

import numpy as np
from html import escape as html_escape
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QEvent, QProcess, QSize, Qt, QTimer, QUrl
from .. import DONATE_URL
from PySide6.QtGui import (QAction, QActionGroup, QBrush, QColor, QDesktopServices, QFont, QFontMetrics, QIcon, QKeySequence,
                           QPixmap, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QDockWidget,
                               QFileDialog, QListWidgetItem, QProgressDialog,
                               QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QTableWidget,
                               QSizePolicy, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import APP_NAME, APP_TITLE, __version__, is_prerelease
from ..i18n import num, tr
from .. import beacons as bc
from .. import applog
from .. import config as cfgmod
from .. import hamlib
from .. import rigprofiles
from .. import rotor as rotmod
from .. import winkey as wkmod
from .. import cty as ctymod
from .. import backup as bkmod
from .. import callbook as cbmod
from .. import callhistory as chmod
from .. import livescore as lsmod
from .. import logcheck
from .. import schedule
from .. import stats
from .. import columns as colmod
from .. import flags as flagmod
from ..countries import flag_code, german_name
from .. import infobox
from .. import weblookup
from .. import scp as scpmod
from .. import dok as dokmod
from .. import qtc as qtcmod
from ..bands import (BAND_NAMES, CONTEST_START_FREQ, DEFAULT_FREQ, band_label, short_label, RIG_MODES, band_for_freq, cabrillo_mode,
                     default_rst)
from .. import contests as contestmod
from .. import rulesupdate
from .. import dailyupdate as dailymod
from .. import versioncheck as vcheckmod
from ..cwdisplay import CwTicker
from .. import voice as voicemod
from .. import speech
from .. import dxcluster as dxc
from ..contests import (CONTESTS, LOAD_RESULT, Qso, Scorer, Station, class_from_log, is_free,
                        wpx_prefix)
from ..db import DEFAULT_META, LogDB
from ..export import adif, cabrillo
from ..rig import RIG_FILTER, RigWorker, port_in_use, start_rigctld
from ..wsjtx import WsjtxListener, adif_to_qso, wsjtx_direct_cat
from . import theme
from .scoretable import ScoreTable
from .announce_page import keys_text
from .dialogs import (AboutDialog, ExportDialog, LogSettingsDialog,
                      SettingsDialog,
                      QsoEditDialog, show_help)
from .stats_window import LogCheckDialog, StatsWindow
from .qtc_dialog import QtcDialog, QtcGiveDialog, QtcListDialog
from .station_ui import StationController, StationDialog

CALL_RE = re.compile(r"^(?=.*\d)(?=.*[A-Z])[A-Z0-9/]{3,15}$")
GREEN, RED, ORANGE, BLUE = "#1b8a3a", "#c62828", "#e08a00", "#1565c0"
# Standard-Beschriftungen der Funktionstasten (config.DEFAULTS) – nur für die Übersetzung
_DEFAULT_MACRO_LABELS = (tr("Austausch"), tr("Mein Call"), tr("Sein Call"), tr("Nochmal"),
                         tr("Speicher 5"), tr("Speicher 6"), tr("Speicher 7"), tr("Speicher 8"))
# Eigene Aufnahmen (ab 0.8.11): F5–F8 haben dann andere Standard-Texte – passende Beschriftung,
# solange noch die alte Standard-Beschriftung „Speicher N“ eingetragen ist
OWN_VOICE_LABELS = {"F5": tr("Sein Call"), "F6": tr("Nochmal"), "F7": tr("Call?"), "F8": tr("Nr?")}
INFOBOX_WIDTH = 500             # feste Breite der Infobox rechts (Flagge, Land, Hinweise)
AUTOCQ_WAIT_MS = 600000         # Auto-CQ mit eigener Stimme: Takt ruht, bis die Ansage fertig ist
STATION_KEYS = ("my_zone", "my_grid", "my_state", "my_power", "my_itu", "my_licyear", "my_dok",
                "my_oblast", "my_iota", "my_age", "my_iota_dxped", "my_iota_island",
                "my_district", "edi_section", "my_power_w", "my_antenna", "my_member",
                "my_class")
MULT_SINGULAR = {"zone": tr("Zone"), "country": tr("Land"), "prefix": tr("Präfix"), "field": tr("Feld"),
                 "state": tr("State"), "province": tr("Provinz"), "xe": tr("XE-State"),
                 "region": tr("ITU-Region"), "itu": tr("ITU-Zone"), "hq": tr("Verband"),
                 "year": tr("Jahrgang"), "dok": tr("DOK"), "district": tr("Distrikt"),
                 "area": tr("Gebiet"), "oblast": tr("Oblast"),
                 "iota": "IOTA", "subdiv": tr("Kürzel"), "member": tr("Mitglied")}
# Spalten der Log-Tabelle: feste logische Reihenfolge, sichtbare Anordnung je Contest
COLS = colmod.COLUMN_KEYS
COL = {k: i for i, k in enumerate(COLS)}
LAND_COL = COL["land"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


_TZ_DE = {"CET": "MEZ", "CEST": "MESZ"}


def local_clock_text(now: datetime | None = None) -> str:
    """Ortszeit mit Zeitzone aus dem System, z. B. „01:10:23 MEZ“."""
    now = (now or datetime.now(timezone.utc)).astimezone()
    tz = now.tzname() or ""
    return f"{now.strftime('%H:%M:%S')} {_TZ_DE.get(tz, tz)}".strip()


def widest(label, texts) -> int:
    """Breite (Pixel) des breitesten Textes in der Schrift des Feldes; 0 = unbekannt."""
    try:
        fm = label.fontMetrics()
        return int(max(fm.horizontalAdvance(t) for t in texts))
    except (TypeError, AttributeError, ValueError):
        return 0


def every_digit(pattern: str) -> list[str]:
    """„88:88:88 UTC“ mit jeder Ziffer 0–9 – in vielen Schriften sind Ziffern
    verschieden breit; so findet man die breiteste Variante."""
    return [pattern.replace("8", str(d)) for d in range(10)]


def hold_width(label, texts) -> None:
    """Feld mindestens so breit machen wie der breiteste Text – dann schiebt eine
    laufende Uhr oder eine neue Frequenz die Nachbarn in der Kopfzeile nicht mehr."""
    w = widest(label, texts)
    if w:
        label.setMinimumWidth(w + 4)


def welcome_text() -> str:
    """Text des Willkommensfensters (0.10.12) – eigene Funktion für Test und Übersetzung."""
    imp = [tr("<b>Internet verbinden</b>, wenn möglich – dann wird die Uhrzeit abgeglichen und "
              "GoGoHam kann Länderdaten, Rufzeichen-Vorschläge und Updates holen."),
           tr("<b>Operator</b>: Rufzeichen und Locator – sonst fehlen Entfernungen und Punkte, "
              "auf dem USB-Stick auch die richtige Zeitzone."),
           tr("<b>Funkgerät</b>: damit Frequenz und Band von selbst kommen."),
           tr("<b>Daten &amp; Updates → „Alles herunterladen“</b>: Länder und Zonen, "
              "Rufzeichen-Vorschläge (SCP), Flaggen.")]
    rest = tr("Rotor, Funktionstasten, Ton &amp; Ansagen, Online-Dienste, Zusatzprogramme, "
              "Darstellung")
    items = "".join(f"<li>{t}</li>" for t in imp)
    return (tr("<h3>Willkommen bei GoGoHam!</h3>"
               "<p>Geh am besten die Einstellungen der Reihe nach von oben nach unten durch.</p>")
            + "<p><b>" + tr("Wichtig für den Betrieb:") + f"</b></p><ol>{items}</ol>"
            + "<p><b>" + tr("Nach Bedarf:") + f"</b> {rest}</p>"
            + "<p>" + tr("Die Einstellungen findest du jederzeit unter Datei → Einstellungen "
                         "(Strg+,).") + "</p>")

class MainWindow(QMainWindow):
    def __init__(self, progress=None) -> None:
        """progress: Rückmeldung an den Startbildschirm (Text des Ladeschritts)."""
        super().__init__()
        step = progress or (lambda _text: None)
        self._startup_popups: list[tuple[int, object]] = []
        self.cfg = cfgmod.load()
        self.db: LogDB | None = None
        self.meta: dict = dict(DEFAULT_META)
        self.contest = None
        self.scorer: Scorer | None = None
        self.qsos: list[Qso] = []
        self.qtcs: list[qtcmod.Qtc] = []       # empfangene QTCs (WAE)
        self.serial = 1
        self.exch_auto = True
        self._exch_from_history = ""
        self._exch_history_key = ""
        self.rig: RigWorker | None = None
        self.rigctld_proc = None
        self.icom_bridge = None                          # 0.10.30: Icom über LAN/WLAN
        self.icom_msgs = None
        self.rotor: rotmod.RotorWorker | None = None   # Rotor (0.8.23)
        self.rotctld_proc = None
        self._rot_notice = 0
        self._rot_auto_last = None
        self._rot_auto_timer = QTimer(self)
        self._rot_auto_timer.setSingleShot(True)
        self._rot_auto_timer.setInterval(1500)     # erst drehen, wenn 1,5 s nicht getippt wurde
        self._rot_auto_timer.timeout.connect(self._rotor_auto)
        self.keyer: wkmod.WinKeyWorker | None = None   # WinKey für CW (ab 0.8.18)
        self._keyer_seen = (0, 0, None)                # breakin_id, pot_id, connected
        self.rig_caps: hamlib.RigCaps | None = None
        self.rig_foreign = False                 # rigctld lief schon (nicht von GoGoHam)
        self.locked_by: str | None = None        # FT8-Programm, das gerade steuert
        self._direct_cat_warned = False
        self.wsjtx: WsjtxListener | None = None
        self.practice = None                     # Übungsmodus (0.8.28): PracticeController
        self.manual_freq = DEFAULT_FREQ["20"]
        self._updating = False
        self.flag_dl = None
        self._pixmaps: dict[str, object] = {}
        self._icons: dict[str, object] = {}
        self.cb_cache: dict[str, dict] = {}
        self.cb_job = None
        self.cb_progress = None
        self._pending_adif = ""
        self.history = chmod.CallHistory()
        self._exch_from_history = ""
        self._exch_history_key = ""
        self.stats_win = None
        self.live = None
        self._live_xml = ""
        self._dirty = False
        self._last_backup = time.monotonic()
        self._last_slow_tick = 0.0
        self.autocq_timer = QTimer(self)
        self.autocq_timer.timeout.connect(self._autocq_fire)
        self.cw_ticker = CwTicker()
        self._voice_until = 0.0
        # Sprachausgabe mit eigenen Aufnahmen (ab 0.8.11): idle → ptt (warten, bis das Gerät
        # auf Senden ist) → play → idle
        # DX-Cluster und Bandmap (ab 0.8.12)
        self.cluster = None
        self.spots = dxc.SpotStore(int(self.cfg.get("cluster_max_age", 30)))
        self._bm_sig = None
        self._bm_next = 0.0
        self._mapm_sig = None                    # Baken/Spots auf der Karte (0.8.20)
        self._rbn_offline = False                # RBN war nicht erreichbar: Karte versucht es
                                                 # erst nach neuem Einschalten wieder
        self._mapm_next = 0.0
        self._spot_eval: dict = {}
        self._assisted_warned = False
        self._bc_assisted_warned = False
        # Bakenanzeige über das Reverse Beacon Network (ab 0.8.14)
        self.rbn = None
        self.beacon_board = None
        self._bc_next = 0.0
        self._bc_started = 0.0
        self._vs = "idle"
        self._vs_samples = None
        self._vs_ptt_id = 0
        self._vs_deadline = 0.0
        self._vs_play_at = 0.0
        self._vs_text = ""
        self._vplayer = None
        self._vcache = None
        self._vs_timer = QTimer(self)
        self._vs_timer.timeout.connect(self._voice_tick)
        self.sending_timer = QTimer(self)
        self.sending_timer.timeout.connect(self._update_sending)
        theme.apply(self.cfg.get("theme", "system"))

        step(tr("Lade Länderdatei …"))
        self.cty = ctymod.CtyDB.load_default()
        step(tr("Lade Super Check Partial …"))
        self.scp = scpmod.ScpDB.load_default()

        step(tr("Baue das Fenster auf …"))
        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        # Ansagen per Sprachausgabe (0.8.26); Rufzeichen-Zustand erst nach kurzer Tipp-Pause
        self.announcer = speech.Announcer(self.cfg, None)
        self._ann_pending: tuple[str, str] | None = None
        self._ann_timer = QTimer(self)
        self._ann_timer.setSingleShot(True)
        self._ann_timer.setInterval(700)
        self._ann_timer.timeout.connect(self._announce_pending)
        self._setup_speech()
        self.sb.on_message = self.announcer.hint

        from .feedback import ClockWatch
        self.clock = ClockWatch(self)            # Uhrzeit-Prüfung (ab 0.8.18.3)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(250)
        # 0.8.29.1: Frequenz flüssig anzeigen (das Funkgerät wird bis zu 50-mal/s gefragt)
        self.freq_timer = QTimer(self)
        self.freq_timer.timeout.connect(self._freq_tick)
        self.freq_timer.start(40)

        # 0.8.31.1: mit dem zuletzt benutzten Profil starten – und dessen Einstellungen auch
        # wirklich übernehmen (vorher: Nummer auf Profil 1, Einstellungen vom letzten → CAT tot)
        rigprofiles.ensure_profiles(self.cfg)
        self._fill_profile_menu()
        step(tr("Verbinde mit dem Funkgerät …"))
        self.start_rig()
        self.start_rotor()
        self.start_wsjtx()
        self.gpsw.start()

        # Rückfragen beim Start erst zeigen, wenn das Hauptfenster da ist
        # (der Startbildschirm ruft run_startup_popups() auf)
        later = self._startup_popups
        last = self.cfg.get("last_log")
        self._startup_question = False
        if last and Path(last).is_file() and progress is not None:
            # 0.10.2 (Nutzer): beim Start leer – erst fragen, ob es mit dem letzten Log
            # weitergeht. So läuft kein altes Log (oder Stationslog) unbemerkt weiter.
            self._startup_question = True
            later.append((200, lambda: self._ask_last_log(last)))
        elif last and Path(last).is_file():
            step(tr("Öffne das Log …"))
            self.open_log(last)
        elif progress is not None and not self.cfg.get("welcome_done"):
            # 0.10.12 (Nutzer): beim allerersten Start ein Willkommensfenster mit der Reihenfolge
            # fürs Einrichten statt einzelner Fragen (Station, Länderdatei, SCP, Flaggen)
            later.append((200, self._first_welcome))
        else:
            later.append((200, self._welcome))
        self._open_startup_docks()
        from .. import livestick
        if livestick.is_live() and not livestick.persistent():
            later.append((90, self._stick_no_save))        # 0.10.22: Stick ohne Datenteil
        if livestick.is_live() and livestick.refreshed() is not None:
            later.append((95, self._stick_refreshed))     # 0.10.47.6: neues Abbild, aufgeräumt
        if livestick.is_live() and not self.cfg.get("stick_hint_done"):
            later.append((100, self._stick_hint))         # Live-Stick: einmal „nicht abziehen“, zuerst
        # 0.10.12: keine Frage nach Rufzeichen/Locator mehr beim Start – das Willkommensfenster
        # schickt zu Einstellungen → Operator (dort stellt der Locator auch die Zeitzone ein)
        if livestick.is_live():
            later.append((160, self._stick_timezone))     # Zeitzone passend zum Locator
            later.append((170, self._stick_wlan_later))   # 0.10.48: kein Internet → WLAN-Fenster
        # Tägliches Update (ab 0.8.10): nur beim echten Start mit Ladebildschirm
        self.daily: dailymod.DailyUpdater | None = None
        if progress is not None and dailymod.is_due(self.cfg):
            step(tr("Suche nach Updates …"))
            self._start_daily_update(wait=10.0)
        # Neue GoGoHam-Version? (ab 0.9.4) – eigener Hintergrund-Thread, kein Warten
        self.vcheck: vcheckmod.VersionChecker | None = None
        if progress is not None and vcheckmod.is_due(self.cfg):
            self.vcheck = vcheckmod.VersionChecker()
            self.vcheck.start()
        # 0.10.12 (Nutzer): keine Startfragen mehr nach Länderdatei, SCP und Flaggen –
        # Einstellungen → Daten & Updates → „Alles herunterladen“ (steht im Willkommensfenster)
        if LOAD_RESULT.problems:
            later.append((600, self._show_rule_problems))
        later.append((3000, self._calendar_reminder))      # Contest-Kalender (0.8.21)
        if progress is not None:
            later.append((250, self._serial_access_check))  # USB-Freigabe (0.10.25)
        if progress is None:
            self.run_startup_popups()

    def _serial_access_check(self) -> None:
        """Einmal anbieten, USB-Geräte (Funkgerät, GPS …) freizugeben, wenn GoGoHam sie noch
        nicht öffnen dürfte – die Pakete bringen die Regel mit, AppImage & Co. nicht (0.10.25)."""
        from .. import livestick, permissions
        if self.cfg.get("serial_access_asked") or livestick.is_live() or \
                permissions.access_ok():
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(tr("USB-Geräte freigeben"))
        box.setText(tr("Damit GoGoHam Funkgerät-Kabel, GPS-Empfänger, WinKeyer und "
                       "Rotor-Steuerung über USB benutzen darf, muss Linux sie einmal freigeben. "
                       "Das geht jetzt mit einem Klick und dem Systempasswort – danach nie "
                       "wieder."))
        b_now = box.addButton(tr("Jetzt freigeben"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Später"), QMessageBox.ButtonRole.RejectRole)
        b_never = box.addButton(tr("Nicht mehr fragen"), QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(b_now)
        box.exec()
        if box.clickedButton() is b_never:
            self.cfg["serial_access_asked"] = True
            cfgmod.save(self.cfg)
        elif box.clickedButton() is b_now:
            from .dialogs import PermissionDialog
            dlg = PermissionDialog("", self)
            dlg._fix()                           # gleich ausführen – das Fenster zeigt das Ergebnis
            dlg.exec()
            if dlg.done_ok:
                self.cfg["serial_access_asked"] = True
                cfgmod.save(self.cfg)
                self.gpsw.start()

    def run_startup_popups(self) -> None:
        """Rückfragen beim Start (Willkommen, Länderdatei, SCP, Flaggen, Regel-Probleme) –
        **nacheinander** (0.10.8): Gleichzeitig geöffnete Fenster lagen übereinander, und unter
        Wayland nahm das oberste dann keine Klicks an."""
        todo = sorted(self._startup_popups, key=lambda t: t[0])   # gleiche Zeit: Reihenfolge bleibt
        self._startup_popups = []

        def step(i: int, prev: int) -> None:
            if i >= len(todo):
                return
            delay, func = todo[i]

            def run() -> None:
                try:
                    func()
                finally:
                    step(i + 1, delay)
            QTimer.singleShot(max(0, delay - prev), run)
        step(0, 0)

    # ================================================================ UI-Aufbau
    def _set_title(self, title: str) -> None:
        """Während einer Übung steht „ÜBUNGSMODUS“ vorn im Titel (auch in der Taskleiste)."""
        self._title_plain = title
        if getattr(self, "practice", None) is not None:
            title = tr("⚠ ÜBUNGSMODUS – es wird nichts gesendet") + " – " + title
        self.setWindowTitle(title)

    def _practice_marks(self, on: bool) -> None:
        """Übung unübersehbar markieren (0.10.19): gelber Rand, Titel, gelbes Rufzeichenfeld."""
        from .practice_frame import CALL_STYLE, PracticeFrame
        if getattr(self, "practice_frame", None) is None:
            self.practice_frame = PracticeFrame(self)
        self.practice_frame.set_on(on)
        self.ed_call.setStyleSheet(CALL_STYLE if on else "")
        self._set_title(getattr(self, "_title_plain", APP_TITLE))

    def _build_ui(self) -> None:
        self._set_title(APP_TITLE)
        self.resize(1250, 800)
        fs = int(self.cfg.get("font_size", 15))
        big = QFont()
        big.setPointSize(fs + 3)
        big.setBold(True)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        mono.setPointSize(fs + 4)
        mono.setBold(True)

        central = QWidget()
        root = QVBoxLayout(central)
        # Übungsmodus (0.8.28): roter Balken ganz oben, nur während einer Übung
        self.practice_bar = QWidget()
        pb = QHBoxLayout(self.practice_bar)
        pb.setContentsMargins(8, 4, 8, 4)
        from .practice_frame import BAR_STYLE
        self.practice_bar.setStyleSheet(BAR_STYLE)         # 0.10.19: leuchtend gelb
        self.lbl_practice = QLabel("")
        pf = QFont()
        pf.setPointSize(fs + 3)
        pf.setBold(True)
        self.lbl_practice.setFont(pf)
        pb.addWidget(self.lbl_practice, 1)
        self.btn_practice_end = QPushButton(tr("Übung beenden"))
        self.btn_practice_end.setStyleSheet("color:black; font-weight:normal;")
        self.btn_practice_end.clicked.connect(lambda: self.end_practice())
        pb.addWidget(self.btn_practice_end)
        root.addWidget(self.practice_bar)
        self.practice_bar.hide()

        # --- Kopfzeile: Contest, Frequenz, Band, Mode, CAT, Uhr
        top = QHBoxLayout()
        self.lbl_contest = QLabel(tr("Kein Log geöffnet"))
        self.lbl_contest.setFont(big)
        self.lbl_freq = QLabel("—")
        f2 = QFont(mono)
        f2.setPointSize(fs + 8)
        self.lbl_freq.setFont(f2)
        self.lbl_freq.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.cb_band = QComboBox()
        self.cb_band.addItems(BAND_NAMES)
        self.cb_band.setCurrentText("20")
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(RIG_MODES)
        self.cb_mode.setCurrentText("USB")
        self.lbl_cat = QPushButton(tr("CAT: aus"))
        self.lbl_cat.setFlat(True)
        self.lbl_cat.setToolTip(tr("Klicken: Funkgerät-Profil wechseln"))
        self.lbl_cat.clicked.connect(self._cat_clicked)
        self.lbl_clock = QLabel("")
        self.lbl_clock.setFont(big)
        self.lbl_clock.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_clock_local = QLabel("")
        self.lbl_clock_local.setAlignment(Qt.AlignmentFlag.AlignRight)
        # Feste Breiten: Uhr und Frequenz sollen die Nachbarn nicht hin- und herschieben
        hold_width(self.lbl_clock, every_digit("88:88:88 UTC"))
        zones = {local_clock_text().rpartition(" ")[2], "MESZ", "CEST", "EEST", "AEDT"}
        hold_width(self.lbl_clock_local, [t + " " + z for t in every_digit("88:88:88")
                                          for z in zones])
        hold_width(self.lbl_freq, every_digit(f"{num(88888.88, 2)} kHz"))
        top.addWidget(self.lbl_contest)
        top.addStretch(1)
        top.addWidget(self.lbl_freq)
        top.addWidget(QLabel(tr("Band:")))
        top.addWidget(self.cb_band)
        top.addWidget(QLabel(tr("Mode:")))
        top.addWidget(self.cb_mode)
        top.addSpacing(12)
        top.addWidget(self.lbl_cat)
        top.addSpacing(12)
        clock = QVBoxLayout()
        clock.setSpacing(0)
        clock.addWidget(self.lbl_clock)
        clock.addWidget(self.lbl_clock_local)
        top.addLayout(clock)
        root.addLayout(top)

        # --- Eingabezeile
        entry = QGroupBox(tr("QSO-Eingabe"))
        eg = QGridLayout(entry)
        self.ed_call = QLineEdit()
        self.ed_call.setFont(mono)
        self.ed_call.setMinimumWidth(260)
        self.ed_call.setPlaceholderText(tr("Rufzeichen"))
        self.ed_rst_s = QLineEdit()
        self.ed_rst_r = QLineEdit()
        for w in (self.ed_rst_s, self.ed_rst_r):
            w.setFont(mono)
            w.setMaximumWidth(80)
        self.ed_exch = QLineEdit()
        self.ed_exch.setFont(mono)
        self.ed_exch.setMaximumWidth(160)
        # gesendeter Austausch: nur zum Ablesen (Zone, Nummer oder Locator)
        self.ed_sent = QLineEdit()
        self.ed_sent.setFont(mono)
        self.ed_sent.setMaximumWidth(120)
        self.ed_sent.setReadOnly(True)
        self.ed_sent.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lbl_exch = QLabel(tr("Austausch"))
        self.lbl_sent = QLabel(tr("Ges."))
        eg.addWidget(QLabel(tr("Rufzeichen")), 0, 0)
        self.lbl_rst_s = QLabel(tr("RST ges."))
        self.lbl_rst_r = QLabel(tr("RST empf."))
        eg.addWidget(self.lbl_rst_s, 0, 1)
        eg.addWidget(self.lbl_sent, 0, 2)
        eg.addWidget(self.lbl_rst_r, 0, 3)
        eg.addWidget(self.lbl_exch, 0, 4)
        eg.addWidget(self.ed_call, 1, 0)
        eg.addWidget(self.ed_rst_s, 1, 1)
        eg.addWidget(self.ed_sent, 1, 2)
        eg.addWidget(self.ed_rst_r, 1, 3)
        eg.addWidget(self.ed_exch, 1, 4)
        self.setTabOrder(self.ed_call, self.ed_rst_s)
        self.setTabOrder(self.ed_rst_s, self.ed_rst_r)
        self.setTabOrder(self.ed_rst_r, self.ed_exch)
        self._style_sent_field()
        eg.setColumnStretch(5, 1)
        eg.addWidget(self._build_infobox(fs), 0, 5, 4, 1)

        self.lbl_status = QLabel("")
        self.lbl_status.setFont(big)
        # Feste Größe (0.8.12.9): lange Meldungen brechen um statt Rufzeichenfeld und Fenster
        # auseinanderzudrücken; Höhe für zwei Zeilen der kleinen Schrift, damit nichts springt
        self._status_big = QFont(big)
        self._status_small = QFont()
        self._status_small.setPointSize(max(9, fs - 2))
        self._status_small.setBold(True)
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.lbl_status.setFixedHeight(max(36, QFontMetrics(big).height() + 10,
                                           2 * QFontMetrics(self._status_small).lineSpacing() + 10))
        # ohne Rahmen (0.8.12.4): leer soll hier kein Kasten zu sehen sein
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # ⚠-Hinweise zum Rufzeichen stehen ab 0.8.13 in der Hinweiszeile unten (self.sb)
        eg.addWidget(self.lbl_status, 2, 0, 1, 2)
        self._entry_grid = eg

        # gearbeitete Bänder für das aktuelle Rufzeichen
        bands_row = QHBoxLayout()
        bands_row.addWidget(QLabel(tr("Gearbeitet auf:")))
        self.band_lamps: dict[str, QLabel] = {}
        self._lamps_box = QHBoxLayout()               # nur die Kästchen (je Contest neu)
        bands_row.addLayout(self._lamps_box)
        bands_row.addSpacing(24)
        # Was gerade gesendet wird: CW Buchstabe für Buchstabe, SSB der Sprachspeicher (ab 0.8.10.1)
        self.lbl_sending = QLabel("")
        sf = QFont("Monospace", fs + 1)
        sf.setStyleHint(QFont.StyleHint.TypeWriter)
        sf.setBold(True)
        self.lbl_sending.setFont(sf)
        self.lbl_sending.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_sending.setToolTip(tr("Was GoGoHam gerade sendet – in CW Buchstabe für Buchstabe "
                                       "(aus dem Tempo berechnet)"))
        bands_row.addWidget(self.lbl_sending)
        bands_row.addStretch(1)
        self._build_band_lamps(["160", "80", "40", "20", "15", "10"])
        eg.addLayout(bands_row, 3, 0, 1, 5)

        # Funktionstasten
        fk = QHBoxLayout()
        self.fbuttons = []
        for i in range(1, 9):
            btn = QPushButton(f"F{i}")
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda _=False, n=i: self.run_macro(n, manual=True))
            fk.addWidget(btn)
            self.fbuttons.append(btn)
        self.btn_autocq = QPushButton(tr("Auto-CQ"))
        self.btn_autocq.setCheckable(True)
        self.btn_autocq.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_autocq.setToolTip(tr("F1 automatisch wiederholen (Strg+R)"))
        self.btn_autocq.clicked.connect(lambda _=False: self.toggle_autocq())
        fk.addWidget(self.btn_autocq)
        # „Enter sendet“ (ESM) und Betriebsart Run / S&P (ab 0.8.9)
        self.btn_esm = QPushButton(tr("ESM"))
        self.btn_esm.setCheckable(True)
        self.btn_esm.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_esm.setToolTip(tr("Enter sendet: Enter löst je nach Lage CQ, Austausch, "
                                   "Mein Call oder TU aus"))
        self.btn_esm.clicked.connect(lambda on: self.set_esm(on))
        fk.addWidget(self.btn_esm)
        self.btn_runsp = QPushButton("Run")
        self.btn_runsp.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_runsp.setToolTip(tr("Run (du rufst CQ) oder S&P (du rufst an) – Strg+Tab"))
        self.btn_runsp.clicked.connect(lambda _=False: self.toggle_run_sp())
        fk.addWidget(self.btn_runsp)
        eg.addLayout(fk, 4, 0, 1, 6)
        root.addWidget(entry)

        # --- unten: Log | Punkte. Ab 0.8.14 (Wunsch des Nutzers): Punktestand fest daneben,
        # die Spalten der Logtabelle passen sich der Breite an (_fit_columns)
        split = QHBoxLayout()
        self.tbl = QTableWidget(0, len(COLS))
        theme.install_selection(self.tbl)           # Nightshift: Dupe/Multi auch markiert lesbar
        self.tbl.setHorizontalHeaderLabels([colmod.header_label(k, "Ex") for k in COLS])
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.verticalHeader().setVisible(False)
        # feste Spaltenbreiten (ResizeToContents wäre bei tausenden QSOs zu langsam)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tbl.setIconSize(QSize(24, 16))
        hdr = self.tbl.horizontalHeader()
        hdr.setSectionsMovable(True)              # Spalten per Maus verschieben
        hdr.setStretchLastSection(False)          # _fit_columns füllt die Breite genau aus
        hdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        hdr.customContextMenuRequested.connect(self._header_menu)
        hdr.sectionMoved.connect(lambda *_a: self._save_columns())
        hdr.sectionResized.connect(self._column_dragged)
        self._applying_columns = False
        self.tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl.customContextMenuRequested.connect(self._log_menu)
        self.tbl.doubleClicked.connect(lambda _i: self.edit_selected())
        self.tbl.installEventFilter(self)
        split.addWidget(self.tbl, 1)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.lbl_score_title = QLabel(tr("<b>Punktestand</b>"))
        rl.addWidget(self.lbl_score_title)
        self.tbl_score = ScoreTable(0, 0)      # Spaltenbreite nach Inhalt (0.8.19.1)
        self.tbl_score.verticalHeader().setVisible(False)
        self.tbl_score.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_score.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        rl.addWidget(self.tbl_score, 1)
        self.lbl_score = QLabel("0")
        sf = QFont()
        sf.setPointSize(fs + 12)
        sf.setBold(True)
        self.lbl_score.setFont(sf)
        self.lbl_score.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(self.lbl_score)
        self.lbl_rate = QLabel(tr("Rate: –"))
        self.lbl_rate.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(self.lbl_rate)
        self.lbl_ctime = QLabel("")
        self.lbl_ctime.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_ctime.setWordWrap(True)
        rl.addWidget(self.lbl_ctime)
        right.setFixedWidth(max(300, QFontMetrics(QFont()).averageCharWidth() * 36))
        split.addWidget(right)
        root.addLayout(split, 1)

        self.setCentralWidget(central)

        # --- Super Check Partial als andockbares Fenster
        self.scp_dock = QDockWidget("Super Check Partial", self)
        self.scp_dock.setObjectName("scp_dock")
        self.partial = QListWidget()
        self.partial.setFont(QFont("Monospace", fs - 1))   # 0.8.14: zwischen Bandmap und früher
        self.partial.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Mehrspaltig (0.8.14, Wunsch des Nutzers): so viele Spalten, wie in die Breite passen –
        # schmal = eine Spalte wie bisher; Reihenfolge zeilenweise wie beim Lesen
        self.partial.setFlow(QListWidget.Flow.LeftToRight)
        self.partial.setWrapping(True)
        self.partial.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.partial.itemDoubleClicked.connect(self._scp_pick)
        self.scp_dock.setWidget(self.partial)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.scp_dock)
        # --- Bandmap (ab 0.8.12) als andockbares Fenster unter Super Check Partial
        from .bandmap import BandmapView
        self.bm_dock = QDockWidget(tr("Bandmap"), self)
        self.bm_dock.setObjectName("bandmap_dock")
        self.bandmap = BandmapView(max(9, fs - 3), on_pick=self.bandmap_pick,
                                   on_menu=self._bandmap_menu)
        theme.install_selection(self.bandmap)
        self.bandmap.setMinimumWidth(max(9, fs - 3) * 24)     # ca. 30 Zeichen Monospace
        self.bm_dock.setWidget(self.bandmap)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.bm_dock)
        self.splitDockWidget(self.scp_dock, self.bm_dock, Qt.Orientation.Vertical)
        self.bm_dock.hide()          # beim Start nur per Häkchen (0.8.14.1, _open_startup_docks)
        # --- Bakenanzeige (ab 0.8.14) als andockbares Fenster links neben SCP/Bandmap
        from .beaconview import BeaconView
        self.bc_dock = QDockWidget(tr("Baken (NCDXF/IARU)"), self)
        self.bc_dock.setObjectName("beacon_dock")
        self.beacon_view = BeaconView()
        self.bc_dock.setWidget(self.beacon_view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.bc_dock)
        self.splitDockWidget(self.scp_dock, self.bc_dock, Qt.Orientation.Horizontal)
        self.bc_dock.hide()
        self.scp_dock.hide()
        # --- Grayline-Karte (ab 0.8.15): eigenes Fenster, andockbar wie die Bandmap
        from .mapview import MapView
        self.map_dock = QDockWidget(tr("Karte (Grayline)"), self)
        self.map_dock.setObjectName("map_dock")
        self.map_view = MapView(self.cfg, on_change=self._map_option_changed)
        self.map_view.on_need_download = self._map_need_download
        self.map_view.canvas.on_spot_click = self._map_spot_click
        self.map_view.canvas.on_spot_menu = self._map_spot_menu
        self.map_dl = None                       # Kartenbilder im Hintergrund (mapimages)
        self._map_asked: set[str] = set()
        self.map_dock.setWidget(self.map_view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.map_dock)
        # 0.10.47.6: erst verstecken, dann schweben lassen – andersherum bekam der Fenstermanager von
        # LXQt (xfwm4) kurz ein Fenster gezeigt und behielt es unsichtbar oben links auf dem
        # Bildschirm, wo es alle Mausklicks schluckte (Live-Stick, Laptop-Test). Gilt für alle Docks.
        self.map_dock.hide()
        self.map_dock.setFloating(True)          # erst als eigenes Fenster; andocken per Doppelklick
        self._map_placed = False
        self.map_view.canvas.on_point_menu = self._map_point_menu        # 0.8.23.1
        # --- Rotor-Fenster (0.8.23.1): Kompassrose, andockbar
        from .rotorview import RotorView
        self.rot_dock = QDockWidget(tr("Rotor"), self)
        self.rot_dock.setObjectName("rotor_dock")
        self.rotor_view = RotorView()
        self.rotor_view.on_turn = lambda az: self.rotor_turn(az)
        self.rotor_view.on_stop = self.rotor_stop
        self.rotor_view.on_call = self.rotor_to_call
        self.rotor_view.on_setup = lambda: self.open_settings("rotor")
        self.rot_dock.setWidget(self.rotor_view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.rot_dock)
        self.rot_dock.hide()
        self.rot_dock.setFloating(True)
        self._rot_view_sig = None
        self._map_target = (None, "")
        # --- Bandöffnungs-Vorschau (0.8.27): eigenes Fenster, andockbar
        from .propview import PropagationView
        self.prop_dock = QDockWidget(tr("Bandöffnung (Vorschau)"), self)
        self.prop_dock.setObjectName("propagation_dock")
        self.prop_view = PropagationView(self.cfg, on_change=lambda: cfgmod.save(self.cfg))
        self.prop_dock.setWidget(self.prop_view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.prop_dock)
        self.prop_dock.hide()
        self.prop_dock.setFloating(True)
        # --- Zusatzprogramme passend zum Contest (0.10.6): fldigi, WSJT-X & Co.
        from .companions import Companions
        self.companions = Companions(self)
        self._cont_cache: dict[str, str | None] = {}
        self._prop_last = 0.0
        self._loc_cache: dict[str, tuple[float, float] | None] = {}
        # Untere Leiste mit zwei Zeilen (ab 0.8.13): oben wechselnde Hinweise, unten Funkwetter
        # und dauernde Anzeigen – alle statusBar().showMessage() landen oben
        from .statusbar import HintStatusBar
        self.sb = HintStatusBar(fs, self)
        self.setStatusBar(self.sb)
        self._sw = None                          # Funkwetter (spaceweather.SpaceWeather)
        self._sw_fetch = None
        self._sw_next = 0.0
        self._sw_band = None
        self._update_weather()
        self.lbl_sb_cluster = QLabel("")
        self.lbl_sb_cty = QLabel("")
        self.lbl_sb_wsjtx = QLabel("")
        self.lbl_sb_live = QLabel("")
        self.lbl_sb_wpm = QLabel("")             # CW-Tempo (ab 0.8.10), nur in CW sichtbar
        self.lbl_sb_wpm.setToolTip(tr("CW-Tempo am Funkgerät – ändern mit Bild auf / Bild ab"))
        self.lbl_sb_wpm.setStyleSheet("font-weight:bold;")
        self.lbl_sb_wpm.hide()
        self.lbl_sb_rotor = QPushButton("")      # Rotor (0.8.23): Klick = Einstellungen
        self.lbl_sb_rotor.setFlat(True)
        self.lbl_sb_rotor.setToolTip(tr("Rotor – klicken: Einstellungen. Alt+R = Short Path, "
                                        "Alt+Shift+R = Long Path, Alt+S = Stopp"))
        self.lbl_sb_rotor.clicked.connect(lambda: self.open_settings("rotor"))
        self.lbl_sb_rotor.hide()
        self.statusBar().addPermanentWidget(self.lbl_sb_wpm)
        self.statusBar().addPermanentWidget(self.lbl_sb_rotor)
        from .gps_watch import GpsWatch
        self.gpsw = GpsWatch(self)               # GPS-Empfänger (0.10.25)
        self.statusBar().addPermanentWidget(self.gpsw.label)
        self.statusBar().addPermanentWidget(self.lbl_sb_cluster)
        self.statusBar().addPermanentWidget(self.lbl_sb_live)
        self.statusBar().addPermanentWidget(self.lbl_sb_wsjtx)
        self.statusBar().addPermanentWidget(self.lbl_sb_cty)
        self._update_cty_label()
        # Stationslog mit mehreren Plätzen (ab 0.10)
        self.station = StationController(self)
        self.statusBar().addPermanentWidget(self.station.label)
        # Fenster „Station“ (0.10.3): Plätze im Überblick + Nachrichten, andockbar
        from .station_view import StationView
        self.st_dock = QDockWidget(tr("Station"), self)
        self.st_dock.setObjectName("station_dock")
        self.station_view = StationView()
        self.station_view.on_send = self.station.send_chat
        self.station_view.on_setup = self.show_station
        self.st_dock.setWidget(self.station_view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.st_dock)
        self.st_dock.hide()
        self.st_dock.setFloating(True)
        self.st_dock.resize(720, 460)
        self.station.view = self.station_view
        self.station.view_visible = lambda: not self.st_dock.isHidden()
        self.station.label.on_click = self.open_station_window

        # Signale erst jetzt verbinden, wenn alle Widgets existieren
        self.cb_band.currentTextChanged.connect(self._band_changed)
        self.cb_band.currentTextChanged.connect(lambda _b: self._update_sent())
        self.cb_mode.currentTextChanged.connect(self._mode_changed)
        self.ed_call.textEdited.connect(self._call_edited)
        self.ed_exch.textEdited.connect(self._exch_edited)
        for w in (self.ed_call, self.ed_rst_s, self.ed_rst_r, self.ed_exch):
            w.returnPressed.connect(self.enter_pressed)
            w.installEventFilter(self)
        self._update_macro_buttons()
        self._update_esm_buttons()
        self.clear_entry()

    def _build_infobox(self, fs: int) -> QFrame:
        """Box rechts neben der Eingabe: Flagge, Land, Multi-Status, Richtung."""
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.NoFrame)      # ohne Rahmen (0.8.12.4)
        frame.setMinimumWidth(INFOBOX_WIDTH)
        # Der Block hat eine feste Breite und hängt rechts (0.8.12.5) – so springt die Flagge
        # nicht hin und her, wenn Ländernamen verschieden lang sind; freier Platz bleibt links
        outer = QHBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        inner = QWidget()
        inner.setFixedWidth(INFOBOX_WIDTH)
        outer.addWidget(inner, 0, Qt.AlignmentFlag.AlignTop)
        lay = QGridLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        self.lbl_flag = QLabel()
        self.lbl_flag.setFixedSize(84, 58)
        self.lbl_flag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_cname = QLabel("")
        f = QFont()
        f.setPointSize(fs + 6)
        f.setBold(True)
        self.lbl_cname.setFont(f)
        self.lbl_cont = QLabel("")
        f2 = QFont()
        f2.setPointSize(fs + 2)
        f2.setBold(True)
        self.lbl_cont.setFont(f2)
        self.lbl_cont.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.lbl_flag, 0, 0, 2, 1)
        lay.addWidget(self.lbl_cname, 0, 1)
        lay.addWidget(self.lbl_cont, 0, 3)          # Kontinent rechtsbündig am Rand (0.8.12.6)
        lf = QFont()
        lf.setPointSize(fs)
        self.info_lines = []
        for i in range(4):
            lab = QLabel("")
            lab.setFont(lf)
            lab.setWordWrap(True)                        # feste Breite: lange Zeilen umbrechen
            lay.addWidget(lab, 1 + i, 1, 1, 3)           # bis rechts: zieht Land/Kontinent nicht auseinander
            self.info_lines.append(lab)
        self.lbl_path = QLabel("")
        self.lbl_path.setFont(lf)
        lay.addWidget(self.lbl_path, 5, 0, 1, 4)
        # Inhalt bleibt oben links zusammen, egal wie groß das Fenster ist (0.8.12.4):
        # der freie Platz geht in eine leere Spalte rechts und eine leere Zeile unten
        lay.setColumnStretch(2, 1)                  # Abstand zwischen Land und Kontinent
        lay.setRowStretch(6, 1)
        lay.setHorizontalSpacing(12)
        return frame

    def _show_flag(self, code: str, prefix: str) -> None:
        pm = self._pixmaps.get(code) if code else None
        if code and pm is None:
            p = flagmod.flag_path(code)
            if p:
                pm = QPixmap(str(p)).scaled(80, 54, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
                self._pixmaps[code] = pm
        if pm is not None:
            self.lbl_flag.setText("")
            self.lbl_flag.setStyleSheet("")
            self.lbl_flag.setPixmap(pm)
        else:
            # Ersatz-Schild mit dem Präfix
            self.lbl_flag.setPixmap(QPixmap())
            self.lbl_flag.setText(prefix or "")
            self.lbl_flag.setStyleSheet(
                "border:2px solid #888; border-radius:6px; font-weight:bold; font-size:16pt;"
                if prefix else "")

    def _update_infobox(self, q: Qso | None, ev) -> None:
        self._map_set_target(q, ev)
        if self.rotor is not None and self.cfg.get("rotor_auto", False):
            self._rot_auto_timer.start()              # Rotor: nach 1,5 s Ruhe drehen (0.8.23)
        if q is None or ev is None or not self.contest:
            box = infobox.InfoBox()
        else:
            box = infobox.build(self.contest, self.scorer, q, ev, self.meta.get("my_grid", ""))
            if self._exch_from_history and q.exch_r == self._exch_from_history:
                key = self._exch_history_key
                if key == "zone":
                    txt = tr("Zone {int} aus Call-History – bitte gegenhören", int=int(q.exch_r))
                elif key == "dok":
                    txt = tr("DOK {dok} aus Call-History – bitte gegenhören", dok=q.exch_r)
                else:
                    txt = tr("{what} {value} aus Call-History – bitte gegenhören",
                             what=chmod.key_label(key), value=q.exch_r)
                box.lines.insert(0, (txt, infobox.ASK))
            h = self.history.get(q.call)
            kind = self.contest.expected_kind(ev.lookup)
            if h and kind and kind.startswith("serial_"):
                # Nummer + feste Angabe (DOK, Locator, Bezirk …): nur als Hinweis
                val, key = self.history.suggest(q.call, kind)
                if val and val not in q.exch_r.upper().split():
                    txt = (tr("DOK laut Call-History: {dok} – bitte gegenhören", dok=val)
                           if key == "dok" else
                           tr("{what} laut Call-History: {value} – bitte gegenhören",
                              what=chmod.key_label(key), value=val))
                    box.lines.insert(0, (txt, infobox.ASK))
            if h and h.name and len(box.lines) < len(self.info_lines):
                box.lines.append((tr("Name: {name}", name=h.name), infobox.WORKED))
            qh = self._qtc_hint(q.call) if ev.valid else ""
            if qh and len(box.lines) < len(self.info_lines):
                box.lines.append((qh, infobox.ASK))
        self._show_flag(box.flag, box.prefix)
        self.lbl_cname.setText(box.name)
        self.lbl_cont.setText(box.cont)
        colors = {infobox.NEW: GREEN, infobox.WORKED: "#777777", infobox.ASK: ORANGE}
        for i, lab in enumerate(self.info_lines):
            if i < len(box.lines):
                text, cls = box.lines[i]
                lab.setText(text)
                bold = "font-weight:bold;" if cls in (infobox.NEW, infobox.ASK) else ""
                lab.setStyleSheet(f"color:{colors.get(cls, '')}; {bold}")
            else:
                lab.setText("")
                lab.setStyleSheet("")
        self.lbl_path.setText(box.path if not box.empty else "")

    def _build_menu(self) -> None:
        # 0.10.4: Menüleiste aufgeräumt – Datei · Log & Contest · Station · Fenster · Hilfe;
        # alle Tastenkürzel bleiben wie vorher
        mb = self.menuBar()
        m = mb.addMenu(tr("&Datei"))
        self.act_practice = self._act(m, tr("Übungsmodus …"), self.practice_menu)
        self._act(m, tr("Einstellungen …"), self.open_settings, "Ctrl+,")
        m.addSeparator()
        # Live-Stick (0.10.20, Nutzerwunsch): Beenden fährt gleich den Rechner herunter – so ist
        # das Ausschalten leicht zu finden (vorher nur unter Einstellungen → USB-Stick)
        from .. import livestick
        if livestick.is_live() and livestick.poweroff_command():
            self.act_quit = self._act(m, tr("Beenden und herunterfahren …"), self.stick_poweroff)
        else:
            self.act_quit = self._act(m, tr("Beenden"), self.close)   # Strg+Q = QTC
        m = mb.addMenu(tr("&Log && Contest"))
        self._act(m, tr("Contest-Kalender …"), self.show_calendar, "Ctrl+K")
        self._act(m, tr("Neues Contest-Log …"), lambda: self.new_log(), "Ctrl+N")
        self._act(m, tr("Log öffnen …"), self.open_log_dialog, "Ctrl+O")
        self._act(m, tr("Log-Ordner öffnen …"), self.open_logs_folder)
        self._act(m, tr("Log-Einstellungen …"), self.edit_log_settings, "Ctrl+L")
        m.addSeparator()
        self._act(m, tr("Log prüfen …"), self.check_log, "Ctrl+P")
        self._act(m, tr("Übersicht (Multis, Rate) …"), self.show_stats, "Ctrl+M")
        self._act(m, tr("Call-History …"), self.show_call_history)
        sub = m.addMenu(tr("QTC"))
        self._act(sub, tr("QTC empfangen/geben (WAE) …"), self.receive_qtc, "Ctrl+Q")
        self._act(sub, tr("QTC-Liste …"), self.show_qtcs)
        m.addSeparator()
        sub = m.addMenu(tr("Exportieren"))
        self._act(sub, tr("Log exportieren …"), self.export_log, "Ctrl+E")
        self._act(sub, tr("Cabrillo exportieren …"), self.export_cabrillo)
        self._act(sub, tr("ADIF exportieren …"), self.export_adif)
        self._act(m, tr("Sicherung wiederherstellen …"), self.restore_backup)
        m = mb.addMenu(tr("&Station"))
        self.menu_profiles = m.addMenu(tr("Funkgerät-Profil"))
        self._fill_profile_menu()
        self._act(m, tr("Operator wechseln …"), self.change_operator)
        self._act(m, tr("Uhrzeit prüfen …"), lambda: self.clock.check_now())
        self.menu_companions = m.addMenu(tr("Digitalprogramm starten"))
        self.menu_companions.aboutToShow.connect(self._fill_companion_menu)
        m.addSeparator()
        self._act(m, tr("Stationslog …"), self.show_station)
        self._act(m, tr("Nachricht an andere Plätze …"), self.write_station_message, "Ctrl+T")
        m = mb.addMenu(tr("&Fenster"))
        # Eigener Menüeintrag (0.8.12.3): der Fenstertitel zeigt das Band („Bandmap 40 m“) –
        # im Menü soll nur „Bandmap“ stehen, sie gilt ja für jedes Band
        self.act_bandmap = QAction(tr("Bandmap"), self)
        self.act_bandmap.setCheckable(True)
        self.act_bandmap.setChecked(self.bm_dock.isVisible())
        self.act_bandmap.toggled.connect(self.toggle_cluster)
        # Regel (0.8.14.1, Nutzer): Fenster offen = Funktion an, zu = aus – egal ob über
        # dieses Menü, das Rechtsklick-Menü der Fenster (toggleViewAction) oder das X
        self.bm_dock.visibilityChanged.connect(self._bandmap_dock_visibility)
        self.act_beacons = QAction(tr("Baken (NCDXF/IARU)"), self)
        self.act_beacons.setCheckable(True)
        self.act_beacons.setToolTip(tr("Welches Band ist gerade wohin offen? Über das Reverse "
                                       "Beacon Network – nur bei Contests mit 20, 15 oder 10 m"))
        self.act_beacons.toggled.connect(self.toggle_beacons)
        self.bc_dock.visibilityChanged.connect(self._beacon_dock_visibility)
        self.act_prop = QAction(tr("Bandöffnung (Vorschau)"), self)
        self.act_prop.setCheckable(True)
        self.act_prop.setToolTip(tr("Geschätzt: welches Band ist jetzt und in den nächsten 12 "
                                    "Stunden wohin offen? Aus Funkwetter und Tag/Nacht – keine "
                                    "Garantie"))
        self.act_prop.toggled.connect(lambda on: self.prop_dock.setVisible(bool(on)))
        self.prop_dock.visibilityChanged.connect(
            lambda _v: (self.act_prop.setChecked(not self.prop_dock.isHidden()),
                        self._prop_tick(force=True)))
        self.act_map = QAction(tr("Karte (Grayline)"), self)
        self.act_map.setCheckable(True)
        self.act_map.setToolTip(tr("Weltkarte mit Tag/Nacht, Dämmerung und dem Weg zur "
                                   "Gegenstation (Short und Long Path)"))
        self.act_map.toggled.connect(self.toggle_map)
        self.map_dock.visibilityChanged.connect(self._map_dock_visibility)
        self.act_rotor = QAction(tr("Rotor"), self)
        self.act_rotor.setCheckable(True)
        self.act_rotor.setToolTip(tr("Kompassrose mit Rotor-Richtung, drehen per Klick oder "
                                     "Gradzahl, Stopp – einrichten unter Einstellungen → Rotor"))
        self.act_rotor.toggled.connect(lambda on: self.rot_dock.setVisible(bool(on)))
        self.rot_dock.visibilityChanged.connect(
            lambda _v: (self.act_rotor.setChecked(not self.rot_dock.isHidden()),
                        self._rotor_tick(force=True)))
        self.act_station = QAction(tr("Station (Plätze und Nachrichten)"), self)
        self.act_station.setCheckable(True)
        self.act_station.setToolTip(tr("Stationslog: alle Plätze mit Band, Frequenz, Operator "
                                       "und Rate – und Nachrichten zwischen den Plätzen"))
        self.act_station.toggled.connect(lambda on: self.st_dock.setVisible(bool(on)))
        self.st_dock.visibilityChanged.connect(
            lambda _v: (self.act_station.setChecked(not self.st_dock.isHidden()),
                        self.station.refresh_view()))
        # Reihenfolge: Betrieb – Ausbreitung und Karte – Technik
        m.addAction(self.act_bandmap)
        m.addAction(self.scp_dock.toggleViewAction())
        m.addSeparator()
        for act in (self.act_map, self.act_beacons, self.act_prop):
            m.addAction(act)
        m.addSeparator()
        m.addAction(self.act_rotor)
        m.addAction(self.act_station)
        m = mb.addMenu(tr("&Hilfe"))          # Hilfe und das frühere Menü „Info“ zusammen
        self._act(m, tr("Handbuch …"), lambda: show_help(self, "start"))
        self._act(m, tr("Tastenkürzel"), self.show_keys, "Ctrl+H")
        m.addSeparator()
        self._act(m, tr("Nach neuer Version suchen …"), self.check_version_now)
        self._act(m, tr("Fehlerbericht erstellen …"), self.bug_report)
        m.addSeparator()
        # 0.8.28.4: freiwillige Spende, öffnet nur den Link im Browser
        self.act_donate = self._act(m, tr("☕ Spendier DO2GGH einen Kaffee"),
                                    lambda: self._open_url(DONATE_URL))
        self._act(m, tr("Über GoGoHam …"), self.about)
        if is_prerelease():
            # Vor 1.0: direkt in der Menüleiste, ein Klick öffnet die E-Mail
            self.act_contact = QAction(tr("Kontakt zu DO2GGH"), self)
            self.act_contact.setToolTip(tr("E-Mail an DO2GGH – für Ideen, Lob und Fragen. Für "
                                           "Fehler bitte Hilfe → „Fehlerbericht erstellen …“"))
            self.act_contact.triggered.connect(self.contact)
            mb.addAction(self.act_contact)

    def _act(self, menu: QMenu, text: str, slot, shortcut: str | None = None) -> QAction:
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    def _build_shortcuts(self) -> None:
        for i in range(1, 9):
            sc = QShortcut(QKeySequence(f"F{i}"), self)
            sc.activated.connect(lambda n=i: self.run_macro(n, manual=True))
        sc = QShortcut(QKeySequence("Escape"), self)
        sc.activated.connect(self.escape_pressed)
        sc = QShortcut(QKeySequence("Ctrl+R"), self)
        sc.activated.connect(self.toggle_autocq)
        sc = QShortcut(QKeySequence("Ctrl+Tab"), self)
        sc.setContext(Qt.ShortcutContext.WindowShortcut)
        sc.activated.connect(self.toggle_run_sp)
        sc = QShortcut(QKeySequence("PgUp"), self)
        sc.activated.connect(lambda: self.change_wpm(+1))
        sc = QShortcut(QKeySequence("PgDown"), self)
        sc.activated.connect(lambda: self.change_wpm(-1))
        sc = QShortcut(QKeySequence("Alt+W"), self)
        sc.activated.connect(self.clear_entry)
        sc = QShortcut(QKeySequence("Ctrl+D"), self)
        sc.activated.connect(self.delete_last)
        sc = QShortcut(QKeySequence("Alt+B"), self)
        sc.activated.connect(lambda: self._step_band(+1))
        sc = QShortcut(QKeySequence("Alt+Shift+B"), self)
        sc.activated.connect(lambda: self._step_band(-1))
        # Rotor (0.8.23)
        sc = QShortcut(QKeySequence("Alt+R"), self)
        sc.activated.connect(lambda: self.rotor_to_call(False))
        sc = QShortcut(QKeySequence("Alt+Shift+R"), self)
        sc.activated.connect(lambda: self.rotor_to_call(True))
        sc = QShortcut(QKeySequence("Alt+S"), self)
        sc.activated.connect(self.rotor_stop)
        # Bereich „Entwicklung“ direkt im Hauptfenster (0.10.44) – nur mit Passwort
        sc = QShortcut(QKeySequence("Ctrl+Shift+E"), self)
        sc.activated.connect(self.open_dev)
        # Ansagen auf Tastendruck (0.8.26) – Ziffern, damit kein Menü-Kürzel im Weg ist
        for i, fn in enumerate((self.say_freq, self.say_call, self.say_last_qso,
                                self.say_score, self.say_time, self.say_again), start=1):
            sc = QShortcut(QKeySequence(f"Alt+{i}"), self)
            sc.activated.connect(fn)

    # ============================================================ Ereignisse
    def eventFilter(self, obj, event):  # noqa: N802 (Qt-Name)
        if obj is getattr(self, "tbl", None) and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._fit_columns)
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if obj is self.tbl and key == Qt.Key.Key_Delete:
                self.delete_selected()
                return True
            if obj in (self.ed_call, self.ed_exch, self.ed_rst_s, self.ed_rst_r) \
                    and key == Qt.Key.Key_Space:
                # Leertaste springt zum nächsten Feld
                if obj is self.ed_call:
                    self.ed_exch.setFocus()
                    self.ed_exch.selectAll()
                else:
                    self.ed_call.setFocus()
                    self.ed_call.end(False)
                return True
        return super().eventFilter(obj, event)

    def set_language(self, key: str) -> None:
        """Sprache umstellen (wirkt nach Neustart) und nach dem Neustart fragen."""
        if key == self.cfg.get("language", "auto"):
            return
        self.cfg["language"] = key
        cfgmod.save(self.cfg)
        self._ask_restart(language=True)

    def _ask_restart(self, language: bool = False, font: bool = False) -> None:
        from .. import i18n
        if language:
            new = i18n.available().get(i18n.resolve(self.cfg.get("language")), "")
            text = tr("Die Sprache wird beim nächsten Start auf {name} umgestellt.\n\n"
                      "Jetzt neu starten? Das Log wird gespeichert und wieder geöffnet.", name=new)
            text += "\n\n(Language: " + new + " – restart now?)"
        else:
            text = tr("Die neue Schriftgröße wirkt nach einem Neustart.\n\n"
                      "Jetzt neu starten? Das Log wird gespeichert und wieder geöffnet.")
        ans = QMessageBox.question(self, tr("Neustart"), text)
        if ans == QMessageBox.StandardButton.Yes:
            self.restart_requested = True
            self.close()

    def closeEvent(self, event):  # noqa: N802
        if getattr(self, "companions", None):
            self.companions.shutdown()            # selbst gestartete Zusatzprogramme beenden
        if getattr(self, "station", None):
            self.station.shutdown()
        if self.announcer.speaker is not None:
            self.announcer.speaker.close()
        self.toggle_autocq(False)
        self.voice_stop()
        self.stop_rotor()
        if getattr(self, "gpsw", None):
            self.gpsw.stop()
        self.stop_cluster()
        self.stop_beacons()
        self._backup_now()
        if self.live:
            self.live.stop()
        self.cfg["last_log"] = str(self.db.path) if self.db else self.cfg.get("last_log", "")
        if self.practice is not None:                    # Übungslog nie beim Start öffnen
            self.practice.stop()
            self.cfg["last_log"] = self.practice.prev_log
            if getattr(self.practice, "listen", False):  # S&P: „Enter sendet“ zurück (0.8.29.1)
                self.cfg["esm_mode"] = getattr(self, "_practice_esm", "run")
            self.practice = None
        cfgmod.save(self.cfg)
        self.stop_rig()
        if self.wsjtx:
            self.wsjtx.stop()
        if self.db:
            self.db.close()
        event.accept()

    # ================================================================ Log-Datei
    def _first_welcome(self) -> None:
        """Allererster Start (0.10.12): was man der Reihe nach einrichten sollte."""
        self.cfg["welcome_done"] = True
        cfgmod.save(self.cfg)
        box = QMessageBox(self)
        box.setWindowTitle(tr("Willkommen bei GoGoHam"))
        box.setIcon(QMessageBox.Icon.Information)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(welcome_text())
        b_set = box.addButton(tr("Einstellungen öffnen"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Später"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(b_set)
        box.exec()
        if box.clickedButton() is b_set:
            self.open_settings(start="operator")

    def _welcome(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(tr("Willkommen bei GoGoHam!\n\nNeues Contest-Log anlegen oder "
                    "ein vorhandenes öffnen?"))
        b_new = box.addButton(tr("Neues Log"), QMessageBox.ButtonRole.AcceptRole)
        b_open = box.addButton(tr("Öffnen …"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(tr("Später"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is b_new:
            self.new_log()
        elif box.clickedButton() is b_open:
            self.open_log_dialog()

    @staticmethod
    def _log_summary(path: str) -> str:
        """„CQ WW DX CW – station-….ggh (123 QSOs)“ für die Frage beim Start."""
        try:
            db = LogDB(path)
            try:
                meta, n = db.get_meta(), db.count()
            finally:
                db.close()
        except Exception:  # noqa: BLE001 – dann eben nur der Dateiname
            return Path(path).name
        cls = CONTESTS.get(meta.get("contest", ""))
        name = cls.name if cls else meta.get("contest", "")
        extra = tr(" · Stationslog") if meta.get("station_role") else ""
        return tr("{name} – {file} ({n} QSOs){extra}", name=name, file=Path(path).name, n=n,
                  extra=extra)

    def _ask_last_log(self, path: str) -> None:
        """Start (0.10.2): mit dem letzten Log weitermachen, ein neues anlegen – oder leer."""
        try:
            box = QMessageBox(self)
            box.setWindowTitle(APP_NAME)
            box.setText(tr("Zuletzt benutzt:\n{log}\n\nWeitermachen?",
                           log=self._log_summary(path)))
            b_go = box.addButton(tr("Weitermachen"), QMessageBox.ButtonRole.AcceptRole)
            b_new = box.addButton(tr("Neues Contest-Log …"), QMessageBox.ButtonRole.ActionRole)
            box.addButton(tr("Nein"), QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(b_go)
            box.exec()
            clicked = box.clickedButton()
        finally:
            self._startup_question = False
        if clicked is b_go:
            self.open_log(path)
        elif clicked is b_new:
            self.new_log()

    def open_logs_folder(self) -> None:
        """Ordner mit den Log-Dateien (.ggh) im Dateimanager öffnen (z. B. Dolphin) – zum
        Aufräumen, Kopieren, Löschen (0.10.7.1). Ist ein Log offen, sein Ordner."""
        folder = str(Path(self.db.path).parent) if self.db else self._logs_dir()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
            self.sb.showMessage(tr("Dateimanager ließ sich nicht öffnen – der Ordner ist: "
                                   "{folder}", folder=folder), 15000, "warn")
            return
        if self.db:
            self.sb.showMessage(tr("Log-Ordner geöffnet. Das gerade offene Log ({name}) bitte "
                                   "nicht löschen oder verschieben, solange es in GoGoHam offen "
                                   "ist.", name=Path(self.db.path).name), 12000)

    def _logs_dir(self) -> str:
        d = Path.home() / "GoGoHam"
        d.mkdir(exist_ok=True)
        return str(d)

    # ------------------------------------------------------------ Contest-Kalender (0.8.21)
    def show_calendar(self) -> None:
        from .calendar_dialog import CalendarDialog
        dlg = CalendarDialog(CONTESTS, self.cfg, on_new_log=self.new_log,
                             on_change=lambda: cfgmod.save(self.cfg), parent=self)
        dlg.exec()

    def _calendar_reminder(self) -> None:
        """Beim Start: laufende Contests und Beginn in den nächsten Tagen (Statuszeile)."""
        if not self.cfg.get("calendar_remind", True):
            return
        from .. import contestcal as cc
        now = utc_now().replace(tzinfo=None)
        items = cc.filtered(cc.entries(CONTESTS, now), self.cfg.get("calendar_filter", cc.KINDS))
        text = cc.reminder(items, now)
        if text:
            self.statusBar().showMessage(text + " – " + tr("Log & Contest → Contest-Kalender"), 30000)

    def new_log(self, contest: str | None = None, year: int | None = None) -> None:
        """Neues Log; ``contest``/``year`` vorbelegt aus dem Contest-Kalender (0.8.21)."""
        if self.cfg.get("rules_auto_update", True):
            self.update_rules(manual=False)
        meta = self._prefill_meta(dict(DEFAULT_META))
        if contest:
            meta["contest"] = contest
        dlg = LogSettingsDialog(meta, self, new_log=True)
        if not dlg.exec():
            return
        meta = dlg.meta
        self._remember_station(meta)
        if getattr(dlg, "station_password", ""):     # Stationslog für mehrere Plätze (0.10)
            meta = self.station.new_host_meta(meta, dlg.station_password)
        cls = CONTESTS.get(meta["contest"])
        if cls is not None and getattr(cls, "_has_dok", False) \
                and self.cfg.get("rules_auto_update", True):
            age = dokmod.age_days()
            if age is None or age > 14:          # Sonder-DOKs ändern sich ständig
                self.update_doks(manual=False)
        if cls is not None:
            meta["rules_json"] = json.dumps(cls.rules, ensure_ascii=False)  # Log merkt sich Regeln
        if year is None or meta["contest"] != contest:
            year = utc_now().year
        suggestion = str(Path(self._logs_dir()) /
                         f"{meta['contest']}-{year}-{meta['mycall'].replace('/', '-')}.ggh")
        path, _ = QFileDialog.getSaveFileName(self, tr("Log speichern unter"), suggestion,
                                              tr("GoGoHam-Log (*.ggh)"))
        if not path:
            return
        if not path.endswith(".ggh"):
            path += ".ggh"
        if Path(path).exists():
            QMessageBox.warning(self, tr("Datei existiert"),
                                tr("Diese Datei gibt es schon – bitte „Log öffnen“ benutzen "
                                "oder einen anderen Namen wählen."))
            return
        db = LogDB(path)
        db.set_meta(meta)
        db.close()
        self.open_log(path)

    def open_log_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Log öffnen"), self._logs_dir(),
                                              tr("GoGoHam-Log (*.ggh)"))
        if path:
            self.open_log(path)

    def open_log(self, path: str) -> None:
        if getattr(self, "_ann_live", False):
            self.announcer.quiet(3)                      # Band/Mode des Logs: keine Ansage
        self.toggle_autocq(False)
        if self.db:
            self._backup_now()
            self.db.close()
            self.db = None
        problem = bkmod.check(path) if Path(path).exists() else ""
        db = None
        if problem in ("", "ok"):
            try:
                db = LogDB(path)
                db.get_meta()
            except Exception as e:  # noqa: BLE001
                problem = str(e)
                db = None
        if db is None:
            # nicht bei jedem Start erneut versuchen
            if self.cfg.get("last_log") == path:
                self.cfg["last_log"] = ""
                cfgmod.save(self.cfg)
            self._broken_log(path, problem)
            return
        self.db = db
        self.meta = self.db.get_meta()
        self.cfg["last_log"] = path
        cfgmod.save(self.cfg)
        self._setup_contest()
        # Ein-Band-Contest (ARRL 10 m, CQ 160): gleich auf das Band wechseln (siehe _tick)
        bands = list(self.contest.bands) if self.contest else []
        self._band_offer = bands[0] if len(bands) == 1 else None
        self._band_offer_until = time.monotonic() + 15
        self._rebuild_history(Path(path).parent)
        self.reload()
        self._backup_now(force=True)
        self._assisted_warned = False
        self._bc_assisted_warned = False
        self.start_cluster()
        if getattr(self, "station", None):
            self.station.log_opened()
        if getattr(self, "companions", None):
            QTimer.singleShot(0, self.companions.log_opened)    # passendes Zusatzprogramm
        if len(self.history):
            self.statusBar().showMessage(tr("Call-History: {len} Rufzeichen bekannt", len=len(self.history)),
                                         6000)

    def _broken_log(self, path: str, problem: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(tr("Log beschädigt"))
        box.setText(tr("Das Log\n{path}\nlässt sich nicht öffnen:\n{problem}\n\nWas möchtest "
                       "du tun? (Die Datei selbst wird nicht verändert.)", path=path, problem=problem))
        b_fix = box.addButton(tr("Reparieren"), QMessageBox.ButtonRole.AcceptRole)
        b_open = box.addButton(tr("Anderes Log öffnen …"), QMessageBox.ButtonRole.ActionRole)
        b_new = box.addButton(tr("Neues Log …"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(tr("Abbrechen"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_fix:
            self.repair_log(path)
        elif clicked is b_open:
            self.open_log_dialog()
        elif clicked is b_new:
            self.new_log()

    def repair_log(self, path: str) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            fixed, n = bkmod.repair(path)
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, tr("Reparatur"), tr("Reparatur fehlgeschlagen:\n{e}\n\nVersuch es mit einer Sicherung "
                                                      "(Log & Contest → Sicherung wiederherstellen).", e=e))
            return
        QApplication.restoreOverrideCursor()
        QMessageBox.information(self, tr("Reparatur"),
                                tr("{n} QSOs gerettet.\nNeue Datei:\n{fixed}\n\nDas beschädigte "
                                   "Original ist unverändert geblieben.", n=n, fixed=fixed))
        self.open_log(str(fixed))

    # ------------------------------------------------------------ Sicherungen
    def _backup_now(self, force: bool = False) -> None:
        if not self.db or not (force or self._dirty):
            return
        try:
            made = bkmod.make_backup(self.db.conn, self.db.path)
            self._dirty = False
            self._last_backup = time.monotonic()
        except Exception as e:  # noqa: BLE001
            self.statusBar().showMessage(tr("Sicherung fehlgeschlagen: {e}", e=e), 10000, level="error")
            return
        self._stick_backup(made)

    def _export_suggestion(self, suffix: str) -> str:
        """Speicherort-Vorschlag für Exporte – auf dem Live-Stick der Ordner „Export“ im
        Austausch-Ordner (auch unter Windows sichtbar), sonst neben dem Log (0.10.8.1)."""
        from .. import livestick
        p = livestick.export_path(self.db.path, suffix) if livestick.is_live() else None
        return str(p or Path(self.db.path).with_suffix(suffix))

    def _stick_backup(self, made) -> None:
        """Live-Stick: Kopie des Logs zusätzlich in den Austausch-Ordner (0.10.8)."""
        from .. import livestick
        if self.practice is not None or not self.cfg.get("stick_backup", True):
            return
        exch = livestick.exchange_dir() if livestick.is_live() else None
        if exch is None:
            return
        try:
            text = adif(self.contest, self.meta, self.qsos, self.cb_cache)
            livestick.backup_to_exchange(exch, self.db.path, text, made)
        except Exception as e:  # noqa: BLE001
            applog.message(f"Sicherung in den Austausch-Ordner fehlgeschlagen: {e}", "warn")
            self.statusBar().showMessage(tr("Sicherung in den Austausch-Ordner fehlgeschlagen: {e}",
                                            e=e), 10000, level="warn")

    def _stick_space_check(self) -> None:
        """Live-Stick: warnen, bevor der Platz ausgeht (alle 5 Minuten)."""
        from .. import livestick
        if not livestick.is_live():
            return
        for path, name in ((livestick.data_dir(), tr("Datenteil")),
                           (livestick.exchange_dir(), tr("Austausch-Ordner"))):
            sp = livestick.space(path)
            if sp is not None and livestick.is_low(*sp):
                self.statusBar().showMessage(
                    tr("Der Stick ist fast voll ({name}: noch {free}). Bitte Platz schaffen, sonst "
                       "kann das Speichern fehlschlagen.", name=name,
                       free=livestick.size_text(sp[0])), 0, level="error")
                return

    def _stick_no_save(self) -> None:
        """Live-Stick ohne Datenteil: deutlich warnen – bei jedem Start (0.10.22)."""
        self.sb.showMessage(tr("Dieser Stick speichert nichts – Logs vor dem Ausschalten "
                               "exportieren!"), 0, "error")
        QMessageBox.warning(self, tr("USB-Stick"), tr(
            "Dieser Stick speichert nichts!\n\nLogs und Einstellungen gehen beim Ausschalten "
            "verloren, weil der Datenteil fehlt. Meist ist der Stick kleiner als 16 GB, oder er "
            "wurde mit Rufus im ISO-Modus geschrieben (richtig: DD-Modus).\n\nAbhilfe: den Stick "
            "neu schreiben – am einfachsten von einem anderen GoGoHam-Stick aus (Einstellungen → "
            "USB-Stick → Neuen Stick erstellen). Bis dahin Logs vor dem Ausschalten als ADIF oder "
            "Cabrillo auf einen anderen Datenträger exportieren."))

    def _stick_hint(self) -> None:
        QMessageBox.information(self, tr("USB-Stick"), tr(
            "GoGoHam läuft vom USB-Stick.\n\nBitte den Stick nicht einfach abziehen, solange der "
            "Rechner läuft – sonst können Logs und Einstellungen verloren gehen. Zum Schluss "
            "Datei → „Beenden und herunterfahren …“ wählen und den Stick erst abziehen, wenn der "
            "Rechner aus ist."))
        self.cfg["stick_hint_done"] = True
        cfgmod.save(self.cfg)

    def _stick_refreshed(self) -> None:
        """Nach einem neuen Stick-Abbild hat der Stick die alten Systemdateien weggeräumt (0.10.47.6)."""
        from .. import extapps, livestick
        keys = livestick.refreshed() or []
        names = [extapps.BY_KEY[k].name for k in keys if k in extapps.BY_KEY]
        text = tr("Der Stick wurde mit einem neuen System aktualisiert. Logs, Einstellungen und "
                  "WLAN-Zugänge sind erhalten.\n\nProgramme, die du zusätzlich installiert "
                  "hattest, wurden dabei entfernt und müssen neu installiert werden – WS, JTDX "
                  "und fldigi unter Datei → Einstellungen → Zusatzprogramme. Ihre Einstellungen "
                  "sind noch da.")
        if names:
            text += "\n\n" + tr("Neu installieren: {names}", names=", ".join(names))
        QMessageBox.information(self, tr("USB-Stick"), text)
        livestick.refreshed_done()

    WLAN_WAIT_MS = 12000          # so lange darf sich der Rechner erst selbst verbinden
    WLAN_TRIES = 6                # danach bis zu 6 × 5 s warten, falls gerade ein Fenster offen ist

    def _stick_wlan_later(self) -> None:
        """Live-Stick (0.10.48): nach dem Start kurz warten – Kabel und bekannte WLANs verbinden
        sich von selbst. Ist dann kein Internet da, aber WLAN, öffnet sich das WLAN-Fenster."""
        if self.cfg.get("stick_wlan_ask", True):
            QTimer.singleShot(self.WLAN_WAIT_MS, lambda: self._stick_wlan_check(self.WLAN_TRIES))

    def _stick_wlan_check(self, tries: int) -> None:
        from .. import wlan
        if not wlan.available():
            return
        wifi, is_online = wlan.state()
        if not wifi or is_online:
            return
        if QApplication.activeModalWidget() is not None:     # nicht über ein anderes Fenster
            if tries > 0:
                QTimer.singleShot(5000, lambda: self._stick_wlan_check(tries - 1))
            return
        applog.message("Live-Stick: kein Internet – WLAN-Fenster")
        self.open_wlan(at_start=True)

    def open_wlan(self, at_start: bool = False) -> None:
        """Fenster „Mit dem Internet verbinden“ (0.10.48)."""
        from .wlan_dialog import WlanDialog
        parent = QApplication.activeModalWidget() or self
        dlg = WlanDialog(self.cfg, parent, at_start=at_start)
        dlg.exec()
        cfgmod.save(self.cfg)
        if dlg.ok_ssid:
            self.statusBar().showMessage(tr("Mit dem WLAN „{ssid}“ verbunden.", ssid=dlg.ok_ssid),
                                         10000)

    def _close_for_stick(self) -> bool:
        """Einstellungsfenster schließen, dann GoGoHam ordentlich beenden (Log sichern …)."""
        modal = QApplication.activeModalWidget()
        if isinstance(modal, QDialog):
            modal.reject()
        QApplication.processEvents()
        return self.close()

    def stick_poweroff(self) -> None:
        from .. import livestick
        cmd = livestick.poweroff_command()
        parent = QApplication.activeModalWidget() or self
        if not cmd:
            QMessageBox.warning(parent, tr("USB-Stick"), tr("Herunterfahren geht hier nicht."))
            return
        if QMessageBox.question(parent, tr("Rechner herunterfahren"), tr(
                "GoGoHam beenden und den Rechner herunterfahren?\n\nDen Stick erst abziehen, "
                "wenn der Rechner aus ist.")) != QMessageBox.StandardButton.Yes:
            return
        if self._close_for_stick():
            applog.message("Live-Stick: herunterfahren")
            QProcess.startDetached(cmd[0], cmd[1:])

    def stick_reset(self) -> None:
        from .. import livestick
        cmd = livestick.reset_command()
        parent = QApplication.activeModalWidget() or self
        if not cmd:
            QMessageBox.warning(parent, tr("USB-Stick"), tr("Zurücksetzen geht hier nicht."))
            return
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("Stick zurücksetzen"))
        box.setText(tr("Alle Logs, Einstellungen und nachinstallierten Programme auf dem Stick "
                       "werden gelöscht. Wirklich zurücksetzen?"))
        box.setInformativeText(tr("Der Austausch-Ordner bleibt erhalten – Dateien dort (z. B. "
                                  "Cabrillo-Logs) gehen nicht verloren. Der Rechner startet "
                                  "danach neu."))
        yes = box.addButton(tr("Ja, alles löschen und neu starten"),
                            QMessageBox.ButtonRole.DestructiveRole)
        no = box.addButton(tr("Abbrechen"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(no)
        box.exec()
        if box.clickedButton() is not yes:
            return
        if self._close_for_stick():
            applog.message("Live-Stick: Werkseinstellungen, Neustart")
            QProcess.startDetached(cmd[0], cmd[1:])

    def restore_backup(self) -> None:
        if not self.db:
            start = str(Path(self._logs_dir()) / "Sicherungen")
        else:
            start = str(bkmod.backup_dir(self.db.path))
        path, _ = QFileDialog.getOpenFileName(self, tr("Sicherung wiederherstellen"), start,
                                              tr("GoGoHam-Log (*.ggh)"))
        if not path:
            return
        src = Path(path)
        base = src.stem.rsplit("_", 1)[0]
        target = Path(self._logs_dir()) / f"{base}-wiederhergestellt{src.suffix}"
        n = 1
        while target.exists():
            target = Path(self._logs_dir()) / f"{base}-wiederhergestellt{n}{src.suffix}"
            n += 1
        import shutil
        shutil.copy2(src, target)
        self.open_log(str(target))

    def _setup_contest(self) -> None:
        cls, note = class_from_log(self.meta)
        if note:
            self.statusBar().showMessage(note, 15000, level="warn")
        if cls is None:
            cls = CONTESTS.get(self.meta.get("contest", ""))
            if cls is not None:
                # Log aus der Zeit vor 0.6.5: aktuelle Regeln im Log merken
                self.meta["rules_json"] = json.dumps(cls.rules, ensure_ascii=False)
                self.db.set_meta({"rules_json": self.meta["rules_json"]})
            else:
                cls = CONTESTS["cqww-ssb"]
                self.statusBar().showMessage(
                    tr("Contest „{get}“ ist unbekannt – bitte unter Einstellungen → "
                       "Contest-Regeln aktualisieren", get=self.meta.get('contest')), 20000, level="warn")
        power = (self.meta.get("my_power") or "").strip().upper() or \
            {"HIGH": "KW", "LOW": "100", "QRP": "5"}.get(self.meta.get("cat_power", "HIGH"), "")
        station = Station(call=self.meta.get("mycall", ""),
                          cq_zone=int(self.meta.get("my_zone") or 14),
                          grid=self.meta.get("my_grid", ""),
                          state=(self.meta.get("my_state") or "").strip().upper(),
                          power=power,
                          itu=(self.meta.get("my_itu") or "").strip().upper(),
                          lic_year=(self.meta.get("my_licyear") or "").strip()[-2:],
                          dok=(self.meta.get("my_dok") or "").strip().upper(),
                          oblast=(self.meta.get("my_oblast") or "").strip().upper(),
                          iota=(self.meta.get("my_iota") or "").strip().upper(),
                          age=(self.meta.get("my_age") or "").strip(),
                          district=(self.meta.get("my_district") or "").strip().upper(),
                          member=(self.meta.get("my_member") or "").strip(),
                          pclass=(self.meta.get("my_class") or "").strip().upper(),
                          cat_power=self.meta.get("cat_power", "HIGH"),
                          cat_operator=self.meta.get("cat_operator", "SINGLE-OP"),
                          cat_assisted=self.meta.get("cat_assisted", "NON-ASSISTED"),
                          name=((self.meta.get("name") or "").split() or [""])[0])
        self.contest = cls(self.cty, station)
        self.scorer = Scorer(self.contest)
        self._build_band_lamps(list(cls.bands))
        QTimer.singleShot(0, self._beacons_for_contest)      # Bakenanzeige passend zum Contest
        self._map_home()                                     # Karte: eigener Standort
        self.lbl_contest.setText(f"{cls.name} · {station.call}")
        self._set_title(f"{APP_TITLE} – {cls.name} – {Path(self.db.path).name}")
        self.lbl_score_title.setText(tr("<b>QSOs</b>") if is_free(cls) else tr("<b>Punktestand</b>"))
        self.lbl_exch.setText(tr("{exchange_label} empf.", exchange_label=cls.exchange_label))
        self.lbl_sent.setText(tr("{exchange_label} ges.", exchange_label=cls.exchange_label))
        free = is_free(cls)                       # freies Log: nur eine breite Bemerkung
        if free:
            self.lbl_exch.setText(cls.exchange_label)
        self.lbl_sent.setVisible(not free)
        self.ed_sent.setVisible(not free)
        self.ed_exch.setMaximumWidth(520 if free else 160)
        self.ed_exch.setMinimumWidth(360 if free else 0)
        for w in (self.ed_rst_s, self.ed_rst_r, self.lbl_rst_s, self.lbl_rst_r):
            w.setVisible(cls.uses_rst)
        # Mode passend zum Contest vorwählen, falls kein CAT
        if not self._rig_connected():
            want = {"PH": "USB", "CW": "CW", "DG": "FT8"}.get(next(iter(cls.modes)), "USB")
            if cabrillo_mode(self.cb_mode.currentText()) not in cls.modes:
                self.cb_mode.setCurrentText(want)
        self._apply_columns()
        # Punktetabelle vorbereiten
        cols = [tr("Band"), "QSOs", tr("Pkt")] + [lab for _k, lab in self.contest.mult_types] + [tr("Dupes")]
        self.tbl_score.setColumnCount(len(cols))
        self.tbl_score.setHorizontalHeaderLabels(cols)
        self.tbl_score.schedule_fit()

    def reload(self, keep_entry: bool = False) -> None:
        """Log neu laden und komplett neu bewerten. keep_entry: Eingabezeile nicht leeren
        (Änderungen von anderen Plätzen eines Stationslogs, ab 0.10)."""
        if not self.db or not self.scorer:
            return
        self.qsos = self.db.all_qsos()
        self.cb_cache = self.db.callbook()
        self.qtcs = self.db.all_qtcs() if self.contest.qtc else []
        self.scorer.set_qtcs(len(self.qtcs))
        self.scorer.rebuild(self.qsos)
        self.serial = self.db.next_serial()
        self.tbl.setRowCount(0)
        for q in self.qsos:
            self._append_row(q)
        self.tbl.scrollToBottom()
        self.refresh_score()
        if keep_entry:                  # laufendes QSO bleibt stehen, nur neu prüfen (Dupe …)
            if self.ed_call.text().strip():
                self.update_check()
            else:
                self._update_sent()
        else:
            self.clear_entry()

    # ============================================================ Log-Tabelle
    def _append_row(self, q: Qso) -> None:
        ev = self.scorer.evals.get(q.id)
        row = self.tbl.rowCount()
        self.tbl.insertRow(row)
        lk = ev.lookup if ev else None
        for col, v in enumerate(self._row_values(q, ev, row)):
            it = QTableWidgetItem(v)
            it.setData(Qt.ItemDataRole.UserRole, q.id)
            if col == LAND_COL and lk is not None and not lk.maritime:
                icon = self._flag_icon(flag_code(lk.entity.prefix))
                if icon is not None:
                    it.setIcon(icon)
            if ev and ev.dupe:
                it.setForeground(QBrush(QColor(RED)))
            elif ev and ev.new_mults and COLS[col] in ("mult", "gain"):
                it.setForeground(QBrush(QColor(GREEN)))
            self.tbl.setItem(row, col, it)

    def _row_values(self, q: Qso, ev, row: int) -> list[str]:
        """Inhalt aller Spalten in der logischen Reihenfolge COLS."""
        lk = ev.lookup if ev else None
        if lk is None:
            land = "?"
        elif lk.maritime:
            land = "Maritime Mobile"
        else:
            land = german_name(lk.entity.prefix, lk.entity.name)
        p = infobox.path_info(self.contest, q, lk, self.meta.get("my_grid", ""))
        v = {
            "nr": str(row + 1),
            "utc": q.time[11:16],
            "band": q.band,
            "mode": q.mode,
            "khz": f"{q.freq / 1000:.1f}" if q.freq else "",
            "call": q.call,
            "rst_s": q.rst_s,
            "ex_s": q.exch_s,
            "rst_r": q.rst_r,
            "ex_r": q.exch_r,
            "land": land,
            "prefix": wpx_prefix(q.call) or "",
            "km": (str(int(km)) if (km := self._ukw_km(q)) is not None
                   else num(p["sp_km"]) if p else ""),
            "name": self.cb_cache.get(q.call.upper(), {}).get("name", ""),
            "pts": "DUPE" if ev and ev.dupe else str(ev.points if ev else 0),
            "gain": f"+{ev.gain}" if ev and ev.gain else "",
            "mult": ", ".join(val for _t, val in ev.new_mults) if ev else "",
        }
        return [v[k] for k in COLS]

    # ------------------------------------------------------- Spalten-Anordnung
    def _column_layout(self) -> dict:
        saved = self.cfg.setdefault("columns", {}).get(self.contest.id) if self.contest else None
        return colmod.normalize(saved, type(self.contest) if self.contest else None)

    def _apply_columns(self) -> None:
        """Anordnung des aktuellen Contests auf die Tabelle anwenden."""
        if not self.contest:
            return
        self._applying_columns = True
        try:
            lay = self._column_layout()
            ex = self.contest.exchange_label
            self.tbl.setHorizontalHeaderLabels([colmod.header_label(k, ex) for k in COLS])
            hdr = self.tbl.horizontalHeader()
            for visual, key in enumerate(lay["order"]):
                hdr.moveSection(hdr.visualIndex(COL[key]), visual)
            for key in COLS:
                self.tbl.setColumnHidden(COL[key], key in lay["hidden"])
                self.tbl.setColumnWidth(COL[key], lay["widths"][key])
        finally:
            self._applying_columns = False
        QTimer.singleShot(0, self._fit_columns)

    def _min_col_width(self, key: str) -> int:
        """Schmaler als ihr Titel wird keine Spalte (0.8.14)."""
        item = self.tbl.horizontalHeaderItem(COL[key])
        text = item.text() if item is not None else ""
        hdr = self.tbl.horizontalHeader()
        # Qt hat selbst eine Untergrenze – darunter würde es stillschweigend aufrunden
        return max(hdr.fontMetrics().horizontalAdvance(text) + 14, hdr.minimumSectionSize())

    def _visible_order(self) -> list[str]:
        hdr = self.tbl.horizontalHeader()
        keys = [k for k in COLS if not self.tbl.isColumnHidden(COL[k])]
        return sorted(keys, key=lambda k: hdr.visualIndex(COL[k]))

    def _column_dragged(self, logical: int, old: int, new: int) -> None:
        """Spaltengrenze gezogen: Was die Spalte breiter wird, verliert ihr rechter Nachbar –
        alle anderen bleiben, wie sie sind (0.8.14, nach Rückmeldung des Nutzers)."""
        if self._applying_columns or not self.contest:
            return
        order = self._visible_order()
        key = next((k for k in order if COL[k] == logical), None)
        if key is None:
            return
        pos = order.index(key)
        self._applying_columns = True
        try:
            own_min = self._min_col_width(key)
            if new < own_min:                              # nicht schmaler als der Titel
                new = own_min
                self.tbl.setColumnWidth(logical, new)
            if pos + 1 < len(order):
                nb = order[pos + 1]
                nb_old = self.tbl.columnWidth(COL[nb])
                nb_new = nb_old - (new - old)
                nb_min = self._min_col_width(nb)
                if nb_new < nb_min:                        # Nachbar schon am Minimum
                    new -= nb_min - nb_new
                    nb_new = nb_min
                    self.tbl.setColumnWidth(logical, new)
                self.tbl.setColumnWidth(COL[nb], nb_new)
            else:                                          # letzte Spalte: bis zum Rand
                rest = self.tbl.viewport().width() - sum(
                    self.tbl.columnWidth(COL[k]) for k in order[:-1])
                self.tbl.setColumnWidth(logical, max(own_min, rest))
        finally:
            self._applying_columns = False
        self._save_columns()

    def _fit_columns(self) -> None:
        """Fenstergröße geändert: sichtbare Spalten im Verhältnis ihrer gespeicherten Breiten
        auf die Tabellenbreite verteilen – keine schmaler als ihr Titel."""
        if not self.contest or self._applying_columns:
            return
        avail = self.tbl.viewport().width()
        widths = self._column_layout()["widths"]
        order = self._visible_order()
        if not order or avail < 50:
            return
        want = {k: max(1, int(widths.get(k, 80))) for k in order}
        mins = {k: self._min_col_width(k) for k in order}
        fixed: dict[str, int] = {}
        # Spalten, die im Verhältnis zu schmal würden, bekommen ihr Minimum; Rest neu verteilen
        while True:
            free = [k for k in order if k not in fixed]
            room = avail - sum(fixed.values())
            total = sum(want[k] for k in free)
            if not free or total <= 0:
                break
            short = [k for k in free if want[k] * room / total < mins[k]]
            if not short:
                break
            for k in short:
                fixed[k] = mins[k]
        free = [k for k in order if k not in fixed]
        room = max(0, avail - sum(fixed.values()))
        total = sum(want[k] for k in free) or 1
        self._applying_columns = True
        try:
            used = 0
            for i, k in enumerate(order):
                if k in fixed:
                    w = fixed[k]
                elif k == free[-1]:
                    w = max(mins[k], avail - used - sum(fixed[x] for x in order[i + 1:]
                                                        if x in fixed))
                else:
                    w = max(mins[k], int(want[k] * room / total))
                self.tbl.setColumnWidth(COL[k], w)
                used += w
        finally:
            self._applying_columns = False

    def _save_columns(self) -> None:
        if self._applying_columns or not self.contest:
            return
        hdr = self.tbl.horizontalHeader()
        order = sorted(COLS, key=lambda k: hdr.visualIndex(COL[k]))
        # ausgeblendete Spalten haben Breite 0 – deren alte Breite behalten
        widths = dict(self._column_layout()["widths"])
        for k in COLS:
            if not self.tbl.isColumnHidden(COL[k]):
                widths[k] = self.tbl.columnWidth(COL[k])
        self.cfg.setdefault("columns", {})[self.contest.id] = {
            "order": order,
            "hidden": [k for k in COLS if self.tbl.isColumnHidden(COL[k])],
            "widths": widths,
        }

    def _header_menu(self, pos) -> None:
        if not self.contest:
            return
        m = QMenu(self)
        ex = self.contest.exchange_label
        hdr = self.tbl.horizontalHeader()
        for key in sorted(COLS, key=lambda k: hdr.visualIndex(COL[k])):
            a = QAction(colmod.header_label(key, ex), self)
            a.setCheckable(True)
            a.setChecked(not self.tbl.isColumnHidden(COL[key]))
            a.triggered.connect(lambda checked, k=key: self.set_column_visible(k, checked))
            m.addAction(a)
        m.addSeparator()
        self._act(m, tr("Standard wiederherstellen"), self.reset_columns)
        m.exec(hdr.mapToGlobal(pos))

    def set_column_visible(self, key: str, visible: bool) -> None:
        if not visible and sum(not self.tbl.isColumnHidden(COL[k]) for k in COLS) <= 1:
            return                                   # mindestens eine Spalte bleibt
        self.tbl.setColumnHidden(COL[key], not visible)
        self._save_columns()
        cfgmod.save(self.cfg)
        self._fit_columns()

    def reset_columns(self) -> None:
        if self.contest:
            self.cfg.setdefault("columns", {}).pop(self.contest.id, None)
            cfgmod.save(self.cfg)
            self._apply_columns()

    def _flag_icon(self, code: str):
        """Kleine Flagge für die Log-Tabelle – jede Flagge nur einmal laden."""
        if code in self._icons:
            return self._icons[code]
        p = flagmod.flag_path(code)
        icon = QIcon(str(p)) if p else None
        self._icons[code] = icon
        return icon

    def _selected_id(self) -> int | None:
        rows = self.tbl.selectionModel().selectedRows()
        if not rows:
            return None
        it = self.tbl.item(rows[0].row(), 0)
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _log_menu(self, pos) -> None:
        if self._selected_id() is None:
            return
        m = QMenu(self)
        self._act(m, tr("Bearbeiten …"), self.edit_selected)
        self._act(m, tr("Löschen"), self.delete_selected)
        qid = self._selected_id()
        q = next((x for x in self.qsos if x.id == qid), None)
        if q is not None:
            self._add_qrz_action(m, q.call)
        m.exec(self.tbl.viewport().mapToGlobal(pos))

    def _add_qrz_action(self, menu: QMenu, call: str, separator: bool = True) -> None:
        """Menüpunkt „… bei QRZ.com ansehen“ (0.8.19.2), öffnet den Standardbrowser."""
        is_pfx = (lambda part: part in self.cty.prefixes) if self.cty else None
        url = weblookup.qrz_url(call, is_pfx)
        if not url:
            return
        if separator and not menu.isEmpty():
            menu.addSeparator()
        shown = weblookup.base_call(call, is_pfx)
        self._act(menu, tr("{call} bei QRZ.com ansehen", call=shown),
                  lambda: self._open_url(url))

    def _open_url(self, url: str) -> None:
        if not QDesktopServices.openUrl(QUrl(url)):
            self.statusBar().showMessage(tr("Browser ließ sich nicht öffnen: {url}", url=url),
                                         10000, level="warn")

    def _bandmap_menu(self, spot, global_pos) -> None:
        """Rechtsklick auf einen Spot in der Bandmap (0.8.19.2)."""
        m = QMenu(self)
        self._add_rotor_actions(m, spot.call)
        self._add_qrz_action(m, spot.call)
        if m.actions():
            m.exec(global_pos)

    def edit_selected(self) -> None:
        qid = self._selected_id()
        q = next((x for x in self.qsos if x.id == qid), None)
        if not q:
            return
        old = (q.call, q.time)
        dlg = QsoEditDialog(q, self.contest.exchange_label, self)
        if dlg.exec():
            self.db.update(dlg.q)
            self.station.qso_changed(dlg.q)
            if self.practice is None:             # Call-History: geändertes QSO neu lernen
                self.history.forget_qso(*old)
                self.history.learn_qso(self.contest, dlg.q.call, dlg.q.exch_r, dlg.q.time)
            self._dirty = True
            self.reload()

    def delete_selected(self) -> None:
        qid = self._selected_id()
        q = next((x for x in self.qsos if x.id == qid), None)
        if q and QMessageBox.question(self, "Löschen",
                                      f"QSO mit {q.call} ({band_label(q.band)}, {q.time}) löschen?") \
                == QMessageBox.StandardButton.Yes:
            self.db.delete(q.id)
            self.station.qso_deleted(q.uid)
            self.history.forget_qso(q.call, q.time)
            self._dirty = True
            self.reload()

    def delete_last(self) -> None:
        if not self.qsos:
            return
        q = self.qsos[-1]
        if QMessageBox.question(self, "Letztes QSO löschen",
                                f"Letztes QSO mit {q.call} löschen?") \
                == QMessageBox.StandardButton.Yes:
            self.db.delete(q.id)
            self.station.qso_deleted(q.uid)
            self.history.forget_qso(q.call, q.time)
            self._dirty = True
            self.reload()

    # ================================================================= Eingabe
    def current_freq(self) -> int:
        st = self.rig.snapshot() if self.rig else None
        if st and st.connected and st.freq:
            return st.freq
        return self.manual_freq

    def current_band(self) -> str:
        return self.cb_band.currentText()

    def current_mode(self) -> str:
        return self.cb_mode.currentText()

    def _draft(self) -> Qso:
        return Qso(time="", call=self.ed_call.text().strip().upper(),
                   band=self.current_band(), mode=self.current_mode(),
                   freq=self.current_freq(), rst_s=self.ed_rst_s.text().strip(),
                   exch_s="", rst_r=self.ed_rst_r.text().strip(),
                   exch_r=self._exch_text())

    def _exch_text(self) -> str:
        """Empfangener Austausch – im freien Log eine Bemerkung, so wie getippt."""
        t = self.ed_exch.text().strip()
        return t if is_free(self.contest) else t.upper()

    def clear_entry(self) -> None:
        self.ed_call.clear()
        self.ed_exch.clear()
        rst = default_rst(self.current_mode())
        self.ed_rst_s.setText(rst)
        self.ed_rst_r.setText(rst)
        self.exch_auto = True
        self.lbl_status.setText("")
        self.lbl_status.setStyleSheet("")
        self.sb.set_notes("")
        self.partial.clear()
        self._update_infobox(None, None)
        for lab in self.band_lamps.values():
            lab.setStyleSheet("")
        self._update_sent()
        self.ed_call.setFocus()

    def _update_sent(self) -> None:
        text = self.contest.sent_exchange(self._serial()) if self.contest else ""
        self.ed_sent.setText(text)
        # Felder mitwachsen lassen, damit z. B. „001 JN59ME“ (UKW) ganz zu sehen ist (ab 0.8.9)
        self._fit_width(self.ed_sent, text, 120)
        self._fit_width(self.ed_exch, text + "00", 160)

    @staticmethod
    def _fit_width(w, text: str, minimum: int) -> None:
        """Breite eines Eingabefelds an den Text anpassen (nie schmaler als minimum)."""
        need = w.fontMetrics().horizontalAdvance(text + "  ")
        if not isinstance(need, int):               # Test-Attrappe ohne echte Schrift
            return
        width = max(minimum, need + 16)
        w.setMinimumWidth(width)
        w.setMaximumWidth(width)

    def _style_sent_field(self) -> None:
        bg = "#3a3a3a" if theme.is_dark() else "#e4e4e4"
        fg = "#f0f0f0" if theme.is_dark() else "#1a1a1a"
        if theme.is_nightshift():
            bg = "#22304D" if theme.is_dark() else "#E4E9F1"
        self.ed_sent.setStyleSheet(f"background:{bg}; color:{fg}; border:1px solid #888;")

    def _call_edited(self, text: str) -> None:
        if text.strip() and self.autocq_timer.isActive():
            self.toggle_autocq(False)          # Station antwortet -> Auto-CQ aus
        up = text.upper()
        if up != text:
            pos = self.ed_call.cursorPosition()
            self.ed_call.setText(up)
            self.ed_call.setCursorPosition(pos)
        self.update_check()

    def _exch_edited(self, text: str) -> None:
        up = text if is_free(self.contest) else text.upper()
        if up != text:
            pos = self.ed_exch.cursorPosition()
            self.ed_exch.setText(up)
            self.ed_exch.setCursorPosition(pos)
        self.exch_auto = not text
        self.update_check()

    def _build_band_lamps(self, bands: list[str]) -> None:
        """Kästchen „Gearbeitet auf:“ – nur die Bänder, die im Contest zählen (ab 0.8.8)."""
        if list(self.band_lamps) == list(bands):
            return
        box = self._lamps_box
        for lab in self.band_lamps.values():
            box.removeWidget(lab)
            lab.hide()                                # sofort weg, nicht erst beim Aufräumen
            lab.setParent(None)
            lab.deleteLater()
        self.band_lamps = {}
        for b in bands:
            lab = QLabel(f" {short_label(b)} ")
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setMinimumWidth(42)
            lab.setFrameShape(QFrame.Shape.Box)
            self.band_lamps[b] = lab
            box.addWidget(lab)

    def _set_status(self, text: str, color: str | None, tip: str = "") -> None:
        # Hier steht ab 0.8.13 nur noch die Live-Prüfung des Rufzeichens (kurz); alles andere
        # geht in die Hinweiszeile unten. Ist eine Meldung doch zu lang: kleinere Schrift,
        # höchstens zwei Zeilen – das Feld macht das Fenster nie breiter (0.8.12.9)
        narrow = self._status_narrow_width()
        long = QFontMetrics(self._status_big).horizontalAdvance(text) > narrow - 20
        self.lbl_status.setFont(self._status_small if long else self._status_big)
        if long:
            fm = QFontMetrics(self._status_small)
            text = fm.elidedText(text, Qt.TextElideMode.ElideRight, 2 * narrow - 60)
        self.lbl_status.setText(text)
        self.lbl_status.setToolTip(tip or (text if long else ""))
        if color:
            self.lbl_status.setStyleSheet(
                f"background:{color}; color:{theme.on_signal()}; border-radius:4px; padding:2px 8px;")
        else:
            self.lbl_status.setStyleSheet("")

    def _status_narrow_width(self) -> int:
        """Breite unter Rufzeichen und RST gesendet (normaler Platz des Meldefelds)."""
        g = self._entry_grid
        w = sum(g.cellRect(0, c).width() for c in (0, 1)) + g.horizontalSpacing()
        return max(w, 200)

    def update_check(self) -> None:
        """Live-Prüfung beim Tippen: Dupe, neue Multis, Punkte, Land."""
        call = self.ed_call.text().strip().upper()
        self._update_partial(call)
        for b, lab in self.band_lamps.items():
            worked = self.scorer and b in self.scorer.worked_bands(call)
            lab.setStyleSheet(f"background:{GREEN}; color:{theme.on_signal()};" if worked else "")
        self._ann_pending = None
        if not self.scorer or len(call) < 2:
            self._set_status("", None)
            self.sb.set_notes("")
            self._update_infobox(None, None)
            return
        if call.isdigit():
            self._set_status(tr("Frequenz in kHz – Enter = QSY"), BLUE)
            self.sb.set_notes("")
            self._update_infobox(None, None)
            return
        q = self._draft()
        lk = self.contest.lookup(call)
        if self.exch_auto:
            default = self.contest.default_rcvd_exchange(lk, call)
            self._exch_from_history = ""
            kind = self.contest.expected_kind(lk)
            if kind and not kind.startswith("serial_"):
                val, key = self.history.suggest(call, kind)
                if val:
                    if val != default:
                        self._exch_from_history = val   # Vorschlag aus der Call-History
                        self._exch_history_key = key
                    default = val
            if default != self.ed_exch.text():
                self.ed_exch.setText(default)
            q.exch_r = default
        ev = self.scorer.evaluate(q)
        notes = self.contest.notes(q, lk) + ([ev.warning] if ev.warning else [])
        limit = getattr(self.contest, "max_changes_per_hour", None)
        if limit:
            q.time = utc_now().strftime("%Y-%m-%d %H:%M:%S")
            n, _hour = stats.changes_in_hour(self.qsos, q)
            if n > limit:
                notes.append(tr("{n}. Band-/Modewechsel in dieser Stunde – erlaubt sind {limit}", n=n, limit=limit))
            elif n == limit:
                notes.append(tr("{n}. Wechsel – der letzte erlaubte in dieser Stunde", n=n))
        from .. import multiop                    # Multi-OP-Regeln (ab 0.10.2)
        cat = multiop.category(self.meta)
        if cat and self.qsos:
            tx = self.station.tx if self.station.active else "0"
            notes += multiop.band_notes(self.contest, cat, self.qsos, q.band, q.mode, tx,
                                        utc_now().replace(tzinfo=None),
                                        is_new_mult=bool(ev.new_mults) if ev.valid else None)
        total = getattr(self.contest, "max_changes_total", None)
        if total and self.qsos:
            q.time = utc_now().strftime("%Y-%m-%d %H:%M:%S")
            n = stats.changes_total(self.qsos, q)
            before = stats.changes_total(self.qsos)
            if n > before:                       # dieses QSO wäre ein Wechsel
                if n > total:
                    notes.append(tr("{n}. Band-/Modewechsel – erlaubt sind {total} im ganzen "
                                    "Contest", n=n, total=total))
                elif n >= total - 2:
                    notes.append(tr("{n}. von {total} erlaubten Band-/Modewechseln", n=n,
                                    total=total))
        self.sb.set_notes("   ".join(f"⚠ {n}" for n in notes))
        self._update_infobox(q, ev)
        kind = "dupe" if ev.dupe else "invalid" if not ev.valid else \
            "new_mult" if ev.new_mults else "ok"
        self._ann_pending = (call, kind)
        self._ann_timer.start()
        if is_free(self.contest):                 # freies Log: nur „schon gearbeitet?“
            from ..contests.freelog import worked_text
            seen = [h[:3] for h in self.scorer.history.get(call, [])]
            self._set_status(worked_text(seen), BLUE if seen else GREEN)
        elif ev.dupe:
            self._set_status(tr("DUPE auf {band}", band=band_label(q.band)), RED)
        elif not ev.valid:
            self._set_status(tr("Zählt nicht: {warning}", warning=ev.warning), ORANGE)
        elif ev.new_mults:
            txt = ", ".join(f"{MULT_SINGULAR.get(t, t)} {v}" for t, v in ev.new_mults)
            self._set_status(tr("NEUER MULTI: {txt} · {points} Pkt · +{gain}", txt=txt, points=ev.points, gain=ev.gain), GREEN)
        else:
            self._set_status(tr("OK · {points} Pkt · +{gain}", points=ev.points, gain=ev.gain), BLUE)

    def _update_partial(self, call: str) -> None:
        """Super Check Partial: Treffer aus MASTER.SCP und eigenem Log.

        Rot = auf diesem Band schon gearbeitet, Blau = auf anderem Band
        gearbeitet, Grün = noch nicht gearbeitet.
        """
        self.partial.clear()
        if len(call) < scpmod.MIN_CHARS or call.isdigit():
            return
        logged = set(self.scorer.calls) if self.scorer else set()
        db = self.scp or scpmod.ScpDB()
        order = {b: i for i, b in enumerate(BAND_NAMES)}
        fm = QFontMetrics(self.partial.font())
        widest = 0
        for c in db.search(call, extra=logged):
            bands = self.scorer.worked_bands(c) if self.scorer else set()
            dupe = False
            if self.scorer and bands:
                probe = self._draft()
                probe.call = c
                dupe = self.contest.dupe_key(probe) in self.scorer.worked
            color = RED if dupe else BLUE if bands else GREEN
            text = f"{c:<12} {' '.join(sorted(bands, key=lambda x: order.get(x, 99)))}".rstrip()
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, c)
            it.setForeground(QBrush(QColor(color)))
            self.partial.addItem(it)
            widest = max(widest, fm.horizontalAdvance(text))
        # gleich breite Spalten, so breit wie der längste Eintrag (+ Abstand)
        self.partial.setGridSize(QSize(widest + fm.horizontalAdvance("   "), fm.height() + 4))

    def _scp_pick(self, item) -> None:
        call = item.data(Qt.ItemDataRole.UserRole)
        if not call:
            return
        self.ed_call.setText(call)
        self.update_check()
        self.ed_call.setFocus()
        self.ed_call.end(False)

    def enter_pressed(self) -> None:
        self._clear_rig_notice()
        call = self.ed_call.text().strip().upper()
        if call.isdigit() and 3 <= len(call) <= 8:
            self.qsy_khz(int(call))
            self.ed_call.clear()
            self.update_check()
            return
        if self.cfg.get("esm_enabled"):
            self._esm_enter(call)
            return
        self.log_qso()

    # ------------------------------------------------------- Enter sendet (ESM)
    def _esm_step(self, call: str) -> str:
        """Welcher Schritt jetzt dran ist: cq (leer), call (Rufzeichen steht, Austausch noch
        nicht dran) oder log (Austausch steht und der Cursor ist dort)."""
        if not call:
            return "cq"
        exch = self.ed_exch.text().strip()
        if not self.ed_call.hasFocus():
            if not exch and self.contest is not None \
                    and getattr(self.contest, "exchange_optional", lambda _lk: False)(
                        self.contest.lookup(call)):
                return "log"                 # Gegenstation sendet nur den Rapport (ARRL 160, DIG)
            return "log" if exch else "missing"
        return "call"

    def _esm_enter(self, call: str) -> None:
        """Run: CQ (F1) → Austausch (F2) → TU (F3) + loggen.
        S&P: Mein Call (F4) → Austausch (F2) + loggen + TU (F3).
        In SSB spielen nur feste Sprachspeicher (CQ, Mein Call, TU) – Rufzeichen und Nummer
        sprichst du selbst; das kommt mit der Sprachausgabe (0.8.10)."""
        run = self.cfg.get("esm_mode", "run") != "sp"
        cw = cabrillo_mode(self.current_mode()) == "CW"
        step = self._esm_step(call)
        if step == "cq":
            if run:
                self.run_macro(1)
            else:
                self._set_status(tr("S&P: erst das Rufzeichen eintippen"), BLUE)
            return
        if step == "missing":                              # Cursor im Austausch, aber leer
            self._set_status(tr("Austausch fehlt – bitte eintragen (gesendet wird nichts)"), ORANGE)
            return
        if step == "call":
            if not CALL_RE.match(call):
                self._set_status(tr("Rufzeichen prüfen"), ORANGE)
                return
            if run:
                if cw or self._own_voice() or self.practice is not None:
                    self.run_macro(2, manual=True)        # Rufzeichen + Austausch
                else:
                    self.toggle_autocq(False)             # SSB: Call und Nummer selbst sprechen
            else:
                self.run_macro(4, manual=True)            # Mein Call
            self.ed_exch.setFocus()
            self.ed_exch.selectAll()
            return
        # step == "log": Austausch steht – senden und loggen, aber nur, wenn das QSO zählt
        before = len(self.qsos)
        own = not cw and self._own_voice()
        exch_text = self._macro_text(2) if (cw and not run) else ""
        practice_ssb = self.practice is not None and not cw and not run
        # Übung SSB, S&P (0.8.29.1): Austausch + TU – vor dem Loggen, dann stehen Call/Nummer noch
        prep = self._practice_ssb_prepare(self._ssb_text(2) + " " + self._ssb_text(3)) \
            if practice_ssb else None
        sp_plan = self._voice_plan(self._ssb_text(2) + " " + self._ssb_text(3)) \
            if (own and not run and not practice_ssb) else None
        self.log_qso()
        if len(self.qsos) == before:
            return                                         # Austausch fehlerhaft: nichts senden
        if practice_ssb:
            if prep is not None:
                self._practice_ssb_send(*prep)
        elif not run and cw:
            tu = self._macro_text(3)
            self._send_cw(" ".join(t for t in (exch_text, tu) if t))
        elif sp_plan is not None:
            self.toggle_autocq(False)
            self._say_plan(sp_plan)
        else:
            self.run_macro(3, manual=True)                # TU

    def _macro_text(self, n: int) -> str:
        """CW-Text einer Funktionstaste mit eingesetzten Platzhaltern."""
        m = self.cfg["macros_cw"].get(f"F{n}", {})
        ex = self.contest.sent_exchange(self._serial()) if self.contest else ""
        text = (m.get("text", "").replace("{MYCALL}", self.meta.get("mycall", ""))
                .replace("{CALL}", self.ed_call.text().strip().upper())
                .replace("{EXCH}", ex)
                .replace("{RST}", self.ed_rst_s.text().strip()))
        return " ".join(text.split())

    # ------------------------------------------------------------ RTTY über fldigi (0.10.5)
    def _rig_mode_for(self, mode: str) -> str:
        """Betriebsart fürs Funkgerät: RTTY über die Soundkarte (AFSK) = LSB-Daten."""
        if mode in ("RTTY", "RTTYR") and self.cfg.get("rtty_tx", "afsk") != "fsk":
            return "PKTLSB"
        return mode

    def cabrillo_mode_now(self) -> str:
        return cabrillo_mode(self.current_mode())

    def companion_call(self, call: str, previous: str) -> None:
        """Rufzeichen aus dem Rufzeichenfeld von fldigi: in GoGoHam anzeigen (Dupe, Multi,
        Infobox). Gesendet wird nichts. Leert fldigi das Feld, leert GoGoHam seins mit –
        aber nur, wenn dort noch das übernommene Rufzeichen steht."""
        cur = self.ed_call.text().strip().upper()
        if call:
            if cur in ("", previous):
                self.ed_call.setText(call)
                self.update_check()
        elif previous and cur == previous:
            self.clear_entry()

    def start_companion(self, key: str) -> None:
        """Station → Digitalprogramm starten ▸ (0.10.6)."""
        self.companions.start(key)

    def calibrate_fldigi_level(self, parent=None) -> None:
        """Sendepegel für fldigi einmessen (0.10.7). Sendet nur nach ausdrücklicher Zustimmung;
        Abbrechen schaltet sofort auf Empfang."""
        from PySide6.QtWidgets import QProgressDialog
        from .. import fldigi, levelcal
        parent = parent or self
        title = tr("Sendepegel einmessen")
        prof = rigprofiles.active(self.cfg) if self.cfg.get("rig_enabled") else None
        if prof is None:
            QMessageBox.information(parent, title, tr("Dafür braucht es ein eingerichtetes "
                                                      "Funkgerät (Einstellungen → Funkgerät)."))
            return
        comp = self.companions
        if fldigi.running() and "fldigi" not in comp.procs:
            QMessageBox.information(parent, title, tr(
                "fldigi läuft schon, aber nicht über GoGoHam. Bitte fldigi schließen – GoGoHam "
                "startet es zum Einmessen selbst, fertig eingerichtet."))
            return
        ask = QMessageBox(QMessageBox.Icon.Warning, title, tr(
            "GoGoHam schaltet das Funkgerät gleich bis zu etwa 15 Sekunden auf SENDEN: fldigi "
            "schickt einen Dauerton, GoGoHam erhöht den Pegel Schritt für Schritt und liest dabei "
            "die ALC.\n\nBitte nur an einem Dummy-Load oder auf einer freien Frequenz mit kleiner "
            "Leistung (z. B. 5–10 W) – genauso wie später im Betrieb über USB.\n\nJetzt senden "
            "und einmessen?"), parent=parent)
        b_yes = ask.addButton(tr("Senden und einmessen"), QMessageBox.ButtonRole.AcceptRole)
        ask.addButton(QMessageBox.StandardButton.Cancel)
        ask.setDefaultButton(QMessageBox.StandardButton.Cancel)
        ask.exec()
        if ask.clickedButton() is not b_yes:
            return
        if comp.link is None and not comp.start("fldigi"):
            return
        prog = QProgressDialog(tr("fldigi wird vorbereitet …"), tr("Abbrechen – sofort Empfang"),
                               0, 0, parent)
        prog.setWindowTitle(title)
        prog.setMinimumDuration(0)
        prog.show()
        t0 = time.monotonic()
        while not comp.connected and time.monotonic() - t0 < 45 and not prog.wasCanceled():
            QApplication.processEvents()
            time.sleep(0.05)
        if not comp.connected or prog.wasCanceled():
            prog.close()
            if not prog.wasCanceled():
                QMessageBox.warning(parent, title, tr("fldigi antwortet nicht – Einmessen "
                                                      "abgebrochen."))
            return
        texts: list[str] = []
        cal = levelcal.Calibration(fldigi.Client(),
                                   prof.get("host", "127.0.0.1") or "127.0.0.1", int(prof["port"]),
                                   progress=texts.append)
        cal.start()
        while cal.is_alive():
            if prog.wasCanceled():
                cal.cancel.set()
            if texts:
                prog.setLabelText(tr("Sende … {step}", step=texts[-1]))
            QApplication.processEvents()
            time.sleep(0.05)
        prog.close()
        if cal.error:
            msg = {"no_meter": tr("Dein Funkgerät meldet über Hamlib keine ALC – Einmessen geht "
                                  "damit nicht. Den Pegel bitte am Funkgerät einstellen."),
                   "cancelled": tr("Abgebrochen – das Funkgerät ist wieder auf Empfang.")
                   }.get(cal.error, tr("Einmessen abgebrochen: {e}", e=cal.error))
            QMessageBox.information(parent, title, msg)
            return
        db, verdict, measured = cal.result
        self.cfg["fldigi_txatten"] = db
        cfgmod.save(self.cfg)
        rows = "\n".join(f"{d:+d} dB · ALC {a:.2f}" for d, a in measured)
        text = {
            "ok": tr("Eingemessen: {db} dB – die ALC schlägt dabei nicht aus. fldigi benutzt "
                     "diesen Pegel ab jetzt bei jedem Start.", db=db),
            "too_loud": tr("Schon der leiseste Pegel ({db} dB) lässt die ALC ausschlagen. Bitte am "
                           "Funkgerät den USB-Eingangspegel senken (IC-7300: MENU → SET → "
                           "Connectors → USB MOD Level) und noch einmal einmessen.", db=db),
            "no_alc": tr("Auch beim vollen Pegel schlägt die ALC nicht aus – fldigi sendet mit "
                         "0 dB. Kommt trotzdem zu wenig Leistung, am Funkgerät den "
                         "USB-Eingangspegel etwas erhöhen."),
        }.get(verdict, "")
        QMessageBox.information(parent, title, text + "\n\n" + tr("Messwerte:") + "\n" + rows)

    def _fill_companion_menu(self) -> None:
        from .. import extapps
        m = self.menu_companions
        m.clear()
        found = False
        for app in extapps.APPS:
            if extapps.find(app.key):
                found = True
                a = m.addAction(app.name)
                a.triggered.connect(lambda _c=False, k=app.key: self.start_companion(k))
        if not found:
            a = m.addAction(tr("Keins installiert – Einstellungen → Zusatzprogramme …"))
            a.triggered.connect(lambda: self.open_settings("wsjtx"))

    def _send_cw(self, text: str, warn: bool = False) -> None:
        """CW senden – über den WinKey, falls im Profil eingerichtet, sonst übers Funkgerät.
        Im Übungsmodus nur als Mithörton über die Soundkarte (0.8.28) – nie zum Funkgerät."""
        if self.practice is not None:
            if text:
                ex = self.contest.sent_exchange(self._serial()) if self.contest else ""
                self.practice.send(text, ex)
                self._show_sending_cw(text)
            return
        if not text or self.locked_by:
            return
        if self.keyer:
            if not self.keyer.snapshot().connected:
                if warn:
                    self.statusBar().showMessage(tr("WinKey nicht verbunden – CW wird nicht gesendet"),
                                                 6000, level="warn")
                return
            self.keyer.submit("send", text)
        else:
            if not self._rig_connected():
                return
            if self.rig_caps and not self.rig_caps.can_morse:
                if warn:
                    self.statusBar().showMessage(
                        tr("{profile_name}: CW über CAT kann dieses Gerät laut Hamlib nicht",
                           profile_name=self._profile_name()), 6000, level="warn")
                return
            self.rig.submit("send_morse", text)
        self._show_sending_cw(text)
        self.statusBar().showMessage(f"CW: {text}", 5000)

    # ------------------------------------------- Sprachausgabe (eigene Aufnahmen, ab 0.8.11)
    def _own_voice(self) -> bool:
        return self.cfg.get("voice_source") == "gogoham"

    def _ssb_text(self, n: int) -> str:
        k = f"F{n}"
        m = self.cfg["macros_ssb"].get(k, {})
        return m.get("text", voicemod.DEFAULT_SSB_TEXT.get(k, ""))

    def _voice_values(self) -> dict:
        ex = self.contest.sent_exchange(self._serial()) if self.contest else ""
        return {"MYCALL": self.meta.get("mycall", ""),
                "CALL": self.ed_call.text().strip().upper(),
                "EXCH": ex, "RST": self.ed_rst_s.text().strip()}

    def _voice_plan(self, text: str):
        if self._vcache is None:
            self._vcache = voicemod.ClipCache()
        return voicemod.plan(text, self._voice_values(), self._vcache.have())

    def say(self, text: str) -> bool:
        """Funktionstasten-Text mit der eigenen Stimme senden."""
        return self._say_plan(self._voice_plan(text))

    def _voice_device(self):
        """Soundkarte des Funkgeräts – None, wenn nicht gewählt oder nicht angeschlossen."""
        from . import audio
        dev_id = self._rig_voice_out()
        return audio.find("out", dev_id) if dev_id else None

    def _rig_voice_out(self) -> str:
        """Soundkarte des Funkgeräts für die Sprachspeicher: von Hand gewählt, sonst automatisch
        zum aktiven Profil (0.10.30.1); bei Icom übers Netz die Netzwerk-Soundkarte. Das
        Ergebnis der automatischen Suche gilt 30 s (Funktionstasten sollen nicht warten)."""
        import time
        from .. import rigaudio
        prof = rigprofiles.active(self.cfg) or {}
        key = (self.cfg.get("voice_rig_out", ""), prof.get("conn"), prof.get("device"),
               prof.get("port"), prof.get("audio_out"), prof.get("net_audio"))
        hit = getattr(self, "_voice_out_cache", None)
        if hit and hit[0] == key and time.monotonic() - hit[1] < 30:
            return hit[2]
        dev = rigaudio.voice_out(self.cfg)[0]
        self._voice_out_cache = (key, time.monotonic(), dev)
        return dev

    def _make_voice_player(self):
        from . import audio
        return audio.Player(on_finished=self._voice_finished)

    def _say_plan(self, p) -> bool:
        if self.practice is not None:
            # Übung (0.8.29.1): nie Ton an die Soundkarte des Funkgeräts – auch nicht über einen
            # Umweg; mit VOX könnte das Gerät sonst senden. Die Übung spielt selbst ab.
            return False
        msg = ""
        if p.missing:
            msg = tr("Aufnahme fehlt: {list} – gesendet wird nichts (Einstellungen → Ton & Ansagen → Sprachaufnahmen)",
                     list=voicemod.missing_text(p.missing))
        elif p.empty:
            return False
        elif not self._rig_voice_out():
            msg = tr("Soundkarte des Funkgeräts noch nicht gewählt (Einstellungen → Ton & Ansagen → Sprachaufnahmen) – "
                     "gesendet wird nichts")
        if not msg:
            from . import audio
            msg = audio.available()
        dev = None
        if not msg:
            dev = self._voice_device()
            if dev is None:
                msg = tr("Soundkarte des Funkgeräts nicht gefunden – USB-Kabel prüfen. "
                         "Gesendet wird nichts.")
        if msg:
            self.sb.showMessage(msg, 8000, "warn")
            return False
        samples = voicemod.render(p, self._vcache, self.cfg.get("voice_tone"))
        samples = voicemod.apply_send_level(samples, int(self.cfg.get("voice_send_level", 20)))
        # kurze Stille am Ende: das Tongerät spielt noch nach, bevor PTT abfällt
        samples = np.concatenate([samples, np.zeros(int(0.25 * voicemod.RATE), np.float32)])
        self._vs_dev = dev
        self._vs_samples = samples
        self._vs_text = p.text
        if self._vplayer is None:
            self._vplayer = self._make_voice_player()
        if self._vs == "play":                          # neue Ansage ersetzt die laufende
            self._vplayer.stop(notify=False)
            self._voice_start_playing()
            return True
        if self._vs == "ptt":
            return True                                 # wird gleich mit der neuen gespielt
        st = self.rig.snapshot() if self.rig else None
        self._vs_ptt_id = getattr(st, "ptt_id", 0)
        self._vs = "ptt"
        self._vs_deadline = time.monotonic() + 2.0
        self._vs_play_at = 0.0
        self.rig.submit("ptt", True)
        self._show_sending_say(p.text)
        self._vs_timer.start(20)
        return True

    def _voice_tick(self) -> None:
        if self._vs != "ptt":
            self._vs_timer.stop()
            return
        now = time.monotonic()
        st = self.rig.snapshot() if self.rig else None
        if self._vs_play_at:
            if now >= self._vs_play_at:
                self._vs_timer.stop()
                self._voice_start_playing()
            return
        if st is not None and getattr(st, "ptt_id", 0) != self._vs_ptt_id:
            if st.ptt:
                self._vs_play_at = now + 0.15          # Relais umschalten lassen
            else:                                       # Gerät hat PTT abgelehnt (Hinweis kommt)
                self._voice_reset()
            return
        if now > self._vs_deadline:
            self.rig.submit("ptt", False)
            self._voice_reset()
            msg = tr("Das Funkgerät hat nicht auf Senden umgeschaltet – gesendet wird nichts")
            self.sb.showMessage(msg, 8000, "warn")

    def _voice_start_playing(self) -> None:
        self._vs = "play"
        if not self._vplayer.play(self._vs_samples, self._vs_dev):
            msg = self._vplayer.error
            self.rig.submit("ptt", False)
            self._voice_reset()
            self.sb.showMessage(msg, 8000, "warn")
            return
        self._show_sending_say(self._vs_text)

    def _voice_finished(self) -> None:
        """Ansage zu Ende: sofort zurück auf Empfang."""
        if self._vs == "idle":
            return
        self.rig.submit("ptt", False)
        self._voice_reset()
        if self.autocq_timer.isActive():               # Auto-CQ: jetzt beginnt die Hörpause
            self.autocq_timer.start(int(self.cfg.get("autocq_listen_sec", 8)) * 1000)

    def voice_stop(self) -> None:
        """Esc / Programmende: Ansage abbrechen und PTT aus."""
        if self._vs == "idle":
            return
        if self._vplayer is not None:
            self._vplayer.stop(notify=False)
        if self.rig:
            self.rig.submit("ptt", False)
        self._voice_reset()

    def _voice_reset(self) -> None:
        self._vs = "idle"
        self._vs_timer.stop()
        self._vs_samples = None
        self._voice_until = 0.0
        self._update_sending()

    def _show_sending_say(self, text: str) -> None:
        self.cw_ticker.stop(time.monotonic())
        self.lbl_sending.setText(f'<span style="color:{BLUE}">{html_escape("▶ " + text)}</span>')
        self._voice_until = time.monotonic() + 3600     # bleibt stehen, bis die Ansage fertig ist
        self.sending_timer.start(200)

    # ------------------------------------------------- DX-Cluster und Bandmap (ab 0.8.12)
    def default_spotter_cont(self) -> list[str]:
        """Voreinstellung „gespottet von“: der eigene Kontinent (aus dem Rufzeichen)."""
        lk = self.cty.lookup(self.meta.get("mycall", "")) if self.cty else None
        return [lk.cont] if lk and lk.cont else ["EU"]

    def _cluster_call(self) -> str:
        return (self.cfg.get("cluster_call") or self.meta.get("mycall", "") or "").strip().upper()

    def _make_cluster(self, host: str, port: int, call: str):
        return dxc.ClusterClient(host, port, call)

    # ------------------------------------------------------------ Zusatzfenster (0.8.14.1)
    STARTUP_DOCKS = (("open_scp", "scp_dock"), ("open_bandmap", "bm_dock"),
                     ("open_beacons", "bc_dock"), ("open_map", "map_dock"),
                     ("open_rotor", "rot_dock"), ("open_propagation", "prop_dock"),
                     ("open_station", "st_dock"))

    def _open_startup_docks(self) -> None:
        """Beim Programmstart nur die Fenster öffnen, die in Einstellungen → Darstellung
        angehakt sind (Standard: keins). Baken nur, wenn das Log Bakenbänder hat – sonst still."""
        for key, attr in self.STARTUP_DOCKS:
            if not self.cfg.get(key):
                continue
            if attr == "bc_dock" and not self._beacon_bands():
                continue
            getattr(self, attr).show()
        self._bandmap_dock_visibility()       # Qt meldet nichts, solange das Hauptfenster zu ist
        self._beacon_dock_visibility()
        self._map_dock_visibility()

    # ------------------------------------------------------------ Grayline-Karte (0.8.15)
    def toggle_map(self, on: bool | None = None) -> None:
        """Karte an/aus = Fenster auf/zu."""
        self.map_dock.setVisible(self.map_dock.isHidden() if on is None else bool(on))
        self._map_dock_visibility()

    def _map_dock_visibility(self, _v: bool = False) -> None:
        on = not self.map_dock.isHidden()
        self.act_map.setChecked(on)
        if on and not self._map_placed and self.map_dock.isFloating():
            # beim ersten Öffnen: ordentliche Größe, mittig über dem Hauptfenster
            self._map_placed = True
            w, h = 940, 560
            c = self.geometry().center()
            self.map_dock.resize(w, h)
            self.map_dock.move(max(0, c.x() - w // 2), max(0, c.y() - h // 2))
        if on:
            self._map_home()
            self.map_view.set_target(*self._map_target)
            self._rbn_offline = False            # Karte neu geöffnet: RBN wieder versuchen
        self._sync_feeds()                       # Karte braucht ggf. Cluster/RBN (0.8.20.1)
        if on:
            # Monat gewechselt, während GoGoHam lief: neues NASA-Bild holen
            from .. import mapimages
            if mapimages.nasa_update_due() and not self.map_dl:
                self.start_map_download("nasa-month")
        self.map_view.set_active(on)

    # ------------------------------------------- Baken und Spots auf der Karte (0.8.15.1)
    def _map_marks_tick(self, force: bool = False) -> None:
        """Höchstens einmal je Sekunde und nur bei offener Karte: Zeichen neu zusammenstellen."""
        if self.map_dock.isHidden() and not force:
            return
        now = time.monotonic()
        if now < self._mapm_next and not force:
            return
        self._mapm_next = now + 1.0
        c = self.map_view.canvas
        board = self.beacon_board
        band = self.current_band() if self.db else ""
        cl = self.cluster
        sig = (c.show_beacons, c.show_spots, band, len(self.qsos), self._rbn_offline,
               board.version if board else None,
               (cl.connected, cl.error) if cl is not None else None,
               self.spots.version, int(time.time() // 30), self._home_pos() if self.db else None,
               self.practice is not None)
        if sig == self._mapm_sig and not force:
            return
        self._mapm_sig = sig
        notes = []
        c.beacon_marks, note = self._map_beacon_marks(band) if c.show_beacons else ([], "")
        if note:
            notes.append(note)
        c.spot_marks, note = self._map_spot_marks(band) if c.show_spots else ([], "")
        if note:
            notes.append(note)
        c.notes = notes
        c.update()

    def _map_beacon_marks(self, band: str) -> tuple[list[dict], str]:
        from .beaconview import COLORS, place_name
        board = self.beacon_board
        if board is None:
            if not self._beacon_bands():
                return [], tr("Baken: nur bei Contests mit 20, 15 oder 10 m")
            if not self._cluster_call():
                return [], tr("Baken: kein Rufzeichen für die Anmeldung beim RBN")
            if self._rbn_offline:
                return [], tr("Baken: Reverse Beacon Network nicht erreichbar")
            return [], ""
        bands = self._beacon_bands()
        if band in bands:
            use, note = [band], tr("Baken: {band}", band=band_label(band))
        else:
            use = bands
            note = tr("Baken: bestes von {bands} (auf {band} gibt es keine Baken)",
                      bands=", ".join(band_label(b) for b in bands), band=band_label(band))
        order = {bc.GOOD: 2, bc.FAIR: 1, bc.NONE: 0}
        now = time.time()
        marks = []
        for b in bc.BEACONS:
            cells = [(board.cell(b.call, x, now), x) for x in use]
            cell, cb = max(cells, key=lambda t: order.get(t[0].level, 0)) if cells \
                else (bc.Cell(), band)
            color = COLORS[cell.level][0] if cell.level in COLORS else "#9e9e9e"
            state = {bc.GOOD: tr("gut gehört"), bc.FAIR: tr("schwach oder vor 15–30 Minuten")
                     }.get(cell.level, tr("nicht gehört"))
            tip = tr("Bake {call} · {place}", call=b.call, place=place_name(b.call)) + "\n" + \
                tr("{band}: {state}", band=band_label(cb), state=state)
            if cell.best_db is not None:
                tip += tr(" · bis {db} dB", db=cell.best_db)
            marks.append({"lat": b.lat, "lon": b.lon, "call": b.call, "color": color,
                          "tip": tip})
        return marks, note

    def _map_spot_marks(self, band: str) -> tuple[list[dict], str]:
        from .bandmap import GREEN, GREY, ORANGE
        if self.practice is not None:
            # Übung (0.10.19): die nachgebildeten Spots aus der Bandmap, keine echten
            if not getattr(self.practice, "listen", False):
                return [], tr("Spots: in der Run-Übung gibt es keine")
        elif self.cluster is None:
            return [], tr("Spots: Cluster nicht verbunden (Rufzeichen/Knoten in den Einstellungen?)")
        elif not self.cluster.connected:
            return [], (tr("Spots: Cluster – {err}", err=self.cluster.error) if self.cluster.error
                        else tr("Spots: verbinde mit dem Cluster …"))
        groups: dict[tuple, list] = {}
        info: dict[int, tuple] = {}
        for sp in self.spots.on_band(band):
            pos = self._locate(sp.call)
            if pos is None:
                continue
            st, other = self._spot_status(sp)
            groups.setdefault((round(pos[0], 2), round(pos[1], 2)), []).append(sp)
            info[id(sp)] = (st, other)
        rank = {"mult": 4, "other": 3, "new": 2, "dupe": 1, "invalid": 0}
        color = {"mult": GREEN, "other": ORANGE, "new": "#f4f4f4", "dupe": GREY,
                 "invalid": GREY}
        marks = []
        for (lat, lon), sps in groups.items():
            def kind(sp):
                st, other = info[id(sp)]
                return "other" if st != "mult" and other else st
            sps.sort(key=lambda sp: -rank[kind(sp)])
            best = kind(sps[0])
            label = sps[0].call + (f" +{len(sps) - 1}" if len(sps) > 1 else "")
            lines = []
            for sp in sps[:10]:
                st, other = info[id(sp)]
                extra = {"mult": " ★ " + tr("neuer Multi"), "dupe": " · " + tr("schon gearbeitet"),
                         "invalid": " · " + tr("zählt nicht")}.get(st, "")
                if st != "mult" and other:
                    extra = " ↕ " + tr("Multi auf {bands}",
                                       bands=", ".join(band_label(b) for b in other))
                lines.append(f"{sp.call}  {num(sp.freq / 1000, 1)}{extra}")
            if len(sps) > 10:
                lines.append(tr("… und {n} weitere", n=len(sps) - 10))
            lines.append(tr("Klick: einstellen · Rechtsklick: QRZ.com"))
            marks.append({"lat": lat, "lon": lon, "spots": sps, "color": color[best],
                          "label": label, "tip": "\n".join(lines), "rank": rank[best]})
        marks.sort(key=lambda m: -m["rank"])            # Multis zuerst beschriften
        note = tr("Spots: {band} · {n} auf der Karte", band=band_label(band),
                  n=sum(len(m["spots"]) for m in marks))
        return marks, note

    def _map_spot_click(self, spots: list, gpos) -> None:
        """Klick auf einen Spot in der Karte: wie in der Bandmap. Mehrere am selben Ort: wählen."""
        if len(spots) == 1:
            self.bandmap_pick(spots[0])
            return
        m = QMenu(self)
        for sp in spots[:20]:
            self._act(m, f"{sp.call}  {num(sp.freq / 1000, 1)}",
                      lambda _c=False, sp=sp: self.bandmap_pick(sp))
        m.exec(gpos)

    def _map_spot_menu(self, spots: list, gpos) -> None:
        """Rechtsklick auf einen Spot in der Karte: QRZ.com (je Rufzeichen)."""
        m = QMenu(self)
        if spots:                                   # Rotor auf den Spot-Ort (0.8.23.1)
            self._add_rotor_actions(m, spots[0].call)
            if m.actions():
                m.addSeparator()
        seen = set()
        for sp in spots[:20]:
            if sp.call not in seen:
                seen.add(sp.call)
                self._add_qrz_action(m, sp.call, separator=False)
        if m.actions():
            m.exec(gpos)

    def _map_need_download(self, bg: str) -> None:
        """Hintergrund gewählt, Bilder fehlen: einmal fragen, dann im Hintergrund laden."""
        from .. import mapimages
        if self.map_dl and self.map_dl.is_alive():
            return
        if bg in self._map_asked:
            return
        self._map_asked.add(bg)
        if self._ask_map_download(bg, mapimages.SIZE_MB.get(bg, 50)):
            self.start_map_download(bg)
        else:
            self.map_view.set_background("simple")

    def _ask_map_download(self, bg: str, mb: int) -> bool:
        what = (tr("Satellitenbilder der NASA (Tag und Nacht mit Stadtlichtern)") if bg == "nasa"
                else tr("Reliefkarte von Natural Earth"))
        text = tr("Für diesen Kartenhintergrund werden die {what} einmalig heruntergeladen "
                  "(rund {mb} MB). Danach geht alles offline.", what=what, mb=mb)
        if bg == "nasa":
            text += "\n\n" + tr("Das NASA-Bild passt zum Monat (z. B. Schnee im Winter) und wird "
                                 "beim täglichen Update jeden Monat erneuert (rund 30 MB).")
        text += "\n\n" + tr("Jetzt herunterladen?")
        return QMessageBox.question(self, tr("Kartenbild"), text) == \
            QMessageBox.StandardButton.Yes

    def start_map_download(self, what: str) -> None:
        """what: nasa, nasa-month oder relief."""
        from .. import mapimages
        if self.map_dl and self.map_dl.is_alive():
            self.sb.showMessage(tr("Ein Kartenbild wird gerade schon geladen."), 5000)
            return
        self.map_dl = mapimages.MapDownloader(what)
        self.map_dl.start()
        self._check_map_download()

    def _check_map_download(self) -> None:
        d = self.map_dl
        if not d:
            return
        c = self.map_view.canvas
        if d.is_alive():
            text = tr("{phase} … {p} %", phase=d.phase or tr("Kartenbild wird geladen"),
                      p=d.percent)
            if c.status_line != text:
                c.status_line = text
                c.update()
            return
        self.map_dl = None
        c.status_line = ""
        if d.error:
            self.sb.showMessage(tr("Kartenbild konnte nicht geladen werden: {e}", e=d.error),
                                15000, "error")
            c.update()
            return
        self.map_view.reload_layers()
        self.sb.showMessage(tr("Kartenbild geladen – die Karte zeigt es jetzt."), 8000)

    def _map_home(self) -> None:
        """Eigener Standort für die Karte: Locator aus dem Log, sonst Mitte des Landes."""
        from ..locator import is_grid
        g = (self.meta.get("my_grid") or "").strip().upper() if self.db else ""
        if getattr(self, "gpsw", None) and self.gpsw.position() is not None:
            g = self.gpsw.grid() or g                 # Standort vom GPS (0.10.25)
        label = g if is_grid(g) else (self.meta.get("mycall", "") if self.db else "")
        self.map_view.set_home(self._home_pos() if self.db else None, label)

    def _map_set_target(self, q, ev) -> None:
        """Gegenstation = Rufzeichen in der Eingabezeile (Locator, sonst Land aus cty.dat)."""
        target, label = None, ""
        if q is not None and ev is not None and self.contest and q.call:
            lk = ev.lookup
            target = infobox.target_pos(self.contest, q, lk)
            if target:
                land = ""
                if lk is not None and lk.entity is not None and not lk.maritime:
                    land = german_name(lk.entity.prefix, lk.entity.name)
                label = f"{q.call} · {land}" if land else q.call
        self._map_target = (target, label)
        if not self.map_dock.isHidden():
            self.map_view.set_target(target, label)

    def _bandmap_dock_visibility(self, _v: bool = False) -> None:
        on = not self.bm_dock.isHidden()       # nicht _v: das ist auch beim Minimieren False
        self.act_bandmap.setChecked(on)
        self._sync_feeds()

    # ------------------------------------------- Wer braucht Cluster und RBN? (0.8.20.1)
    def _map_wants(self, key: str) -> bool:
        """Karte offen und Häkchen („map_spots“/„map_beacons“) an."""
        return not self.map_dock.isHidden() and bool(self.cfg.get(key, True))

    def _cluster_wanted(self) -> bool:
        """Cluster läuft, solange die Bandmap offen ist ODER die Karte Spots zeigen soll –
        die Karte braucht kein anderes Fenster (Nutzerwunsch 0.8.20.1)."""
        return bool(self.db) and self.practice is None and \
            (not self.bm_dock.isHidden() or self._map_wants("map_spots"))

    def _beacons_wanted(self) -> bool:
        # auch in der Übung (0.10.19): das RBN wird nur gehört, gesendet wird nichts
        if not self._beacon_bands() or not self._cluster_call():
            return False
        if not self.bc_dock.isHidden():
            return True
        return self._map_wants("map_beacons") and not self._rbn_offline

    def _sync_feeds(self) -> None:
        """Cluster und RBN passend zu Fenstern und Karten-Häkchen starten oder beenden."""
        if self._cluster_wanted():
            if self.cluster is None:
                self.start_cluster()
        elif self.cluster is not None:
            self.stop_cluster()
            self.spots.clear()
            self.lbl_sb_cluster.setText("")
        if self._beacons_wanted():
            if self.rbn is None:
                self.start_beacons()
        elif self.rbn is not None:
            self.stop_beacons()
        self._map_marks_tick(force=True)

    def _map_option_changed(self) -> None:
        """Häkchen in der Karte geändert: speichern, Cluster/RBN nachziehen."""
        cfgmod.save(self.cfg)
        if self.cfg.get("map_beacons", True):
            self._rbn_offline = False           # neuer Versuch, wenn neu eingeschaltet
        self._sync_feeds()

    def start_cluster(self) -> None:
        self.stop_cluster()
        if not self._cluster_wanted():
            self.lbl_sb_cluster.setText("")
            return
        node = dxc.parse_node(self.cfg.get("cluster_node") or dxc.DEFAULT_NODE)
        call = self._cluster_call()
        if not node or not call:
            self.lbl_sb_cluster.setText(tr("Cluster: kein Rufzeichen/Knoten eingestellt"))
            return
        self.cluster = self._make_cluster(node[0], node[1], call)
        self.cluster.start()
        self.lbl_sb_cluster.setText(tr("Cluster: verbinde mit {host} …", host=node[0]))
        self.lbl_sb_cluster.setStyleSheet("")

    def stop_cluster(self) -> None:
        if self.cluster is not None:
            self.cluster.stop()
            self.cluster = None

    def toggle_cluster(self, on: bool | None = None) -> None:
        """DX-Cluster an/aus = Bandmap auf/zu (0.8.14.1)."""
        self.bm_dock.setVisible(self.bm_dock.isHidden() if on is None else bool(on))
        self._bandmap_dock_visibility()       # Qt meldet nichts, solange das Hauptfenster zu ist

    # ------------------------------------------------------------ Bakenanzeige (0.8.14)
    def _beacon_bands(self) -> list[str]:
        return bc.contest_bands(self.contest.bands) if self.contest else []

    def _home_pos(self):
        """Eigener Standort: GPS (0.10.25), sonst Locator aus dem Log, sonst Mitte des Landes."""
        from ..locator import is_grid, latlon
        pos = self.gpsw.position() if getattr(self, "gpsw", None) else None
        if pos is not None:
            return pos
        g = (self.meta.get("my_grid") or "").strip() if self.db else ""
        if is_grid(g):
            return latlon(g)
        return self._locate(self.meta.get("mycall", "") if self.db else "")

    def _locate(self, call: str):
        lk = self.cty.lookup(call) if (self.cty and call) else None
        if lk is None:
            return None
        if lk.lat is not None and lk.lon is not None:
            return (lk.lat, lk.lon)
        if lk.entity:
            return (lk.entity.lat, lk.entity.lon)
        return None

    def toggle_beacons(self, on: bool | None = None) -> None:
        """Bakenanzeige an/aus = Fenster auf/zu (0.8.14.1)."""
        show = self.bc_dock.isHidden() if on is None else bool(on)
        if show:
            self._rbn_offline = False
        self.bc_dock.setVisible(show)
        self._beacon_dock_visibility()        # Qt meldet nichts, solange das Hauptfenster zu ist

    def _beacon_dock_visibility(self, _v: bool = False) -> None:
        on = not self.bc_dock.isHidden()       # nicht _v: das ist auch beim Minimieren False
        if on and self.rbn is None:
            if not self._beacon_bands():
                self.sb.showMessage(
                    tr("Bakenanzeige gibt es nur bei Contests mit 20, 15 oder 10 m")
                    if self.db else tr("Bitte zuerst ein Log anlegen oder öffnen"), 8000, "warn")
                self.toggle_beacons(False)
                return
            if not self._cluster_call():
                self.sb.showMessage(tr("Bakenanzeige: kein Rufzeichen für die Anmeldung beim RBN"),
                                    8000, "warn")
                self.toggle_beacons(False)
                return
        self.act_beacons.setChecked(on)
        self._sync_feeds()            # Fenster zu: RBN läuft weiter, wenn die Karte Baken zeigt

    def _beacons_for_contest(self) -> None:
        """Nach dem Öffnen eines Logs: läuft das RBN (Fenster oder Karte) → mit dem neuen
        Standort neu anfangen; Contest ohne Bakenbänder → Fenster zu."""
        if not self.bc_dock.isHidden() and not self._beacon_bands():
            self.toggle_beacons(False)
            return
        if self._beacons_wanted() and (self.rbn is None or self.beacon_board is None
                                       or self.beacon_board.home != self._home_pos()):
            self.start_beacons()
        else:
            self._sync_feeds()

    def start_beacons(self) -> None:
        self.stop_beacons()
        call = self._cluster_call()
        if not call:
            self.sb.showMessage(tr("Bakenanzeige: kein Rufzeichen für die Anmeldung beim RBN"),
                                8000, "warn")
            self.toggle_beacons(False)
            return
        self.beacon_board = bc.BeaconBoard(self._home_pos(), self._locate)
        self.beacon_view.status.setToolTip(tr(
            "Die Baken stehen weltweit verteilt – jede steht für eine Richtung. Gezählt wird, "
            "was Empfänger des Reverse Beacon Network in deiner Nähe (bis {km} km) von ihnen "
            "hören. Grün heißt also: Von hier aus ist das Band gerade in diese Richtung offen.",
            km=bc.RADIUS_KM))
        self.rbn = self._make_rbn(call)
        self.rbn.start()
        self._bc_started = time.monotonic()
        self.beacon_view.set_status(tr("Verbinde mit dem Reverse Beacon Network …"))
        self.beacon_view.show_board(self.beacon_board, self._beacon_bands(), self._home_pos(),
                                    force=True)

    def _make_rbn(self, call: str):
        return dxc.ClusterClient(bc.RBN_HOST, bc.RBN_PORT, call, history=0,
                                 keep=bc.is_beacon_spot, name="rbn")

    def stop_beacons(self) -> None:
        if self.rbn is not None:
            self.rbn.stop()
            self.rbn = None
        self.beacon_board = None

    def _beacon_tick(self) -> None:
        rb, board = self.rbn, self.beacon_board
        if rb is None or board is None:
            return
        for _ in range(500):
            try:
                spot = rb.spots.get_nowait()
            except Exception:                        # queue.Empty
                break
            board.add(spot)
        if not rb.connected and rb.error and not rb.ever_connected:
            # Ohne Internet: gar nicht erst einschalten – klar sagen, warum
            err = rb.error
            self._rbn_offline = True                    # Karte: nicht dauernd neu versuchen
            self.stop_beacons()
            self.toggle_beacons(False)                  # Fenster zu = aus (0.8.14.1)
            self.sb.showMessage(tr("Bakenanzeige: keine Internetverbindung (Reverse Beacon "
                                   "Network nicht erreichbar) – Einschalten nicht möglich"),
                                15000, "error")
            self.sb.hint.setToolTip(err)                # technische Ursache für Neugierige
            return
        now = time.monotonic()
        if now < self._bc_next:
            return
        self._bc_next = now + 1.0
        board.expire()
        if rb.connected:
            mins = int((now - self._bc_started) // 60)
            text = tr("RBN verbunden · gezählt wird nur, was Empfänger bis {km} km um dich "
                      "hören", km=bc.RADIUS_KM)
            if mins < 15:
                text += " · " + tr("füllt sich noch (nach 10–15 Minuten vollständig)")
            color = ""
            # wie beim DX-Cluster (0.8.14, Wunsch des Nutzers): manche Regeln zählen jede
            # Nutzung des RBN als Unterstützung
            if self.meta.get("cat_assisted", "NON-ASSISTED") != "ASSISTED":
                text += " · " + tr("Log ist NON-ASSISTED!")
                color = ORANGE
                if not self._bc_assisted_warned:
                    self._bc_assisted_warned = True
                    self.sb.showMessage(
                        tr("Bakenanzeige ist an, das Log steht aber auf NON-ASSISTED – manche "
                           "Contests zählen das RBN als Unterstützung (Log & Contest → Log-Einstellungen)"),
                        15000, "warn")
            self.beacon_view.set_status(text, color)
        elif rb.error:
            self.beacon_view.set_status(tr("RBN: {err} – verbinde neu …", err=rb.error), RED)
        if self.bc_dock.isVisible():
            self.beacon_view.show_board(board, self._beacon_bands(), board.home)

    def _spot_wanted(self, spot) -> bool:
        lk_sp = self.cty.lookup(spot.spotter_call) if self.cty else None
        lk_dx = self.cty.lookup(spot.call) if self.cty else None
        want_sp = set(self.cfg.get("cluster_spotter_cont") or self.default_spotter_cont())
        want_dx = set(self.cfg.get("cluster_dx_cont") or dxc.CONTINENTS)
        if not dxc.passes_filter(spot, lk_sp.cont if lk_sp else None,
                                 lk_dx.cont if lk_dx else None, want_sp, want_dx):
            return False
        if self.cfg.get("cluster_contest_only", True) and self.contest:
            q = Qso(time="", call=spot.call, band=spot.band or "", mode=dxc.rig_mode(spot),
                    freq=spot.freq)
            if not (self.contest.band_ok(q) and self.contest.mode_ok(q)):
                return False
        return True

    def _cluster_tick(self) -> None:
        cl = self.cluster
        if cl is not None:
            for _ in range(500):
                try:
                    spot = cl.spots.get_nowait()
                except Exception:                    # queue.Empty
                    break
                if self._spot_wanted(spot):
                    self.spots.add(spot)
            self._update_cluster_label()
        now = time.monotonic()
        if now >= self._bm_next:
            self._bm_next = now + 1.0
            self.spots.expire()
            self._refresh_bandmap()

    def _update_cluster_label(self) -> None:
        cl = self.cluster
        if cl is None:
            return
        if cl.connected:
            if self.cfg.get("cluster_contest_only", True) and self.contest:
                text = tr("Cluster: {host} · {n} Spots (alle Contest-Bänder)", host=cl.host,
                          n=len(self.spots))
            else:
                text = tr("Cluster: {host} · {n} Spots (alle Bänder)", host=cl.host,
                          n=len(self.spots))
            style = ""
            if self.meta.get("cat_assisted", "NON-ASSISTED") != "ASSISTED":
                text += tr(" · Log ist NON-ASSISTED!")
                style = f"color:{ORANGE}; font-weight:bold;"
                if not self._assisted_warned:
                    self._assisted_warned = True
                    self.statusBar().showMessage(
                        tr("DX-Cluster ist an, das Log steht aber auf NON-ASSISTED – im Contest "
                           "meist ASSISTED wählen (Log & Contest → Log-Einstellungen)"), 15000, level="warn")
        else:
            text = tr("Cluster: {err}", err=cl.error) if cl.error else \
                tr("Cluster: verbinde mit {host} …", host=cl.host)
            style = f"color:{RED};" if cl.error else ""
        if text != self.lbl_sb_cluster.text():
            self.lbl_sb_cluster.setText(text)
            self.lbl_sb_cluster.setStyleSheet(style)
            self.lbl_sb_cluster.setToolTip(tr(
                "Gezählt werden alle Spots, die durch deine Filter kommen – auf allen Bändern. "
                "Die Bandmap zeigt davon nur das Band, auf dem du gerade bist."))

    def _spot_status(self, spot) -> tuple[str, list[str]]:
        """Status auf dem Band des Spots und die anderen Bänder, auf denen er noch Multi wäre."""
        if not self.scorer:
            return "new", []
        mode = dxc.rig_mode(spot)
        band = spot.band or ""
        key = (spot.call, band, mode, len(self.qsos))
        hit = self._spot_eval.get(key)
        if hit:
            return hit
        q = Qso(time="", call=spot.call, band=band, mode=mode, freq=spot.freq,
                rst_s="", exch_s="", rst_r="", exch_r="")
        ev = self.scorer.evaluate(q)
        st = "dupe" if ev.dupe else ("invalid" if not ev.valid else
                                     ("mult" if ev.new_mults else "new"))
        res = (st, self._spot_other_band_mults(spot, mode, band))
        if len(self._spot_eval) > 5000:
            self._spot_eval.clear()
        self._spot_eval[key] = res
        return res

    def _spot_other_band_mults(self, spot, mode: str, band: str) -> list[str]:
        """Bänder (außer dem eigenen), auf denen diese Station noch ein fehlender Multi wäre.
        Nur bei Contests, die Multis je Band zählen – sonst gäbe es nichts „je Band“ zu holen."""
        c = self.contest
        per = getattr(c, "mult_per", None) or ("band" if c.mults_per_band else "once")
        if per not in ("band", "band_mode") or not c.mult_types:
            return []
        out = []
        for b in c.bands:
            if b == band:
                continue
            q = Qso(time="", call=spot.call, band=b, mode=mode, freq=0,
                    rst_s="", exch_s="", rst_r="", exch_r="")
            ev = self.scorer.evaluate(q)
            if ev.valid and not ev.dupe and ev.new_mults:
                out.append(b)
        return out

    def _refresh_bandmap(self, force: bool = False) -> None:
        if not self.bm_dock.isVisible() and not force:
            return
        band = self.current_band()
        own = self.current_freq()
        sig = (self.spots.version, band, own // 100, len(self.qsos), int(time.time() // 30))
        if sig == self._bm_sig and not force:
            return
        self._bm_sig = sig
        rows = [(sp, *self._spot_status(sp)) for sp in self.spots.on_band(band)]
        self.bandmap.max_age = self.spots.max_age
        self.bandmap.show_rows(rows, own if band_for_freq(own) == band else 0, band)
        self.bm_dock.setWindowTitle(tr("Bandmap {band}", band=band_label(band)))

    def bandmap_pick(self, spot) -> None:
        """Klick in der Bandmap: Frequenz + Betriebsart einstellen, Rufzeichen eintragen,
        Betrieb auf S&P. Gesendet wird nichts."""
        self.toggle_autocq(False)
        self.voice_stop()
        mode = dxc.rig_mode(spot)
        band = spot.band or ""
        if self.locked_by:
            self.sb.showMessage(tr("Funkgerät wird von {locked_by} gesteuert – Frequenz bitte dort "
                                   "ändern", locked_by=self.locked_by), 8000, "warn")
            return
        if self._rig_connected():
            self.rig.submit("set_mode", mode, RIG_FILTER)
            self.rig.submit("set_freq", spot.freq)
        self.manual_freq = spot.freq
        self._updating = True
        if band and self.cb_band.findText(band) >= 0:
            self.cb_band.setCurrentText(band)
        if self.cb_mode.findText(mode) < 0:
            self.cb_mode.addItem(mode)
        self.cb_mode.setCurrentText(mode)
        self._updating = False
        self._update_macro_buttons()
        self._show_freq(spot.freq)
        self.clear_entry()
        self.ed_call.setText(spot.call)
        self.update_check()
        self.ed_call.setFocus()
        self.ed_call.end(False)
        if self.cfg.get("esm_mode", "run") != "sp":
            self.cfg["esm_mode"] = "sp"
            cfgmod.save(self.cfg)
            self._update_esm_buttons()
        self.statusBar().showMessage(tr("QSY {khz} kHz {mode} · {call} (S&P)",
                                        khz=num(spot.freq / 1000, 1), mode=mode,
                                        call=spot.call), 5000)
        self._refresh_bandmap(force=True)

    def change_wpm(self, direction: int) -> None:
        """CW-Tempo am Funkgerät ändern (Bild auf/ab). Ändert nur die Einstellung, sendet nichts."""
        if cabrillo_mode(self.current_mode()) != "CW":
            self.statusBar().showMessage(tr("Bild auf / Bild ab ändert das CW-Tempo – nur in CW"), 4000, level="warn")
            return
        if self.locked_by:
            self.statusBar().showMessage(tr("{who} ist aktiv – GoGoHam ändert am Funkgerät nichts",
                                            who=self.locked_by), 5000, level="warn")
            return
        if not self.keyer and not self._rig_connected():
            self.statusBar().showMessage(tr("CW-Tempo braucht eine CAT-Verbindung"), 5000, level="warn")
            return
        wpm = self._cw_wpm()
        if wpm <= 0:
            self.statusBar().showMessage(tr("WinKey nicht verbunden") if self.keyer else
                                         tr("Das Funkgerät meldet kein CW-Tempo – über CAT nicht "
                                            "einstellbar"), 6000, level="warn")
            return
        step = max(1, int(self.cfg.get("cw_wpm_step", 2)))
        new = min(60, max(5, wpm + step * (1 if direction > 0 else -1)))
        if new == wpm:
            return
        if self.keyer:
            self.keyer.submit("set_wpm", new)
            with self.keyer.lock:
                self.keyer.state.wpm = new
        else:
            self.rig.submit("set_keyspd", new)
            with self.rig.lock:                  # sofort anzeigen, das Gerät bestätigt gleich
                self.rig.state.wpm = new
        self._show_wpm(new)
        self.statusBar().showMessage(tr("CW-Tempo: {n} WpM", n=new), 3000)

    def _cw_wpm(self) -> int:
        """Aktuelles CW-Tempo: vom WinKey (falls eingerichtet) oder vom Funkgerät (0 = unbekannt)."""
        if self.practice is not None:
            return self.practice.s.my_wpm
        if self.keyer:
            st = self.keyer.snapshot()
            return st.wpm if st.connected else 0
        st = self.rig.snapshot() if self.rig else None
        return getattr(st, "wpm", 0) or 0

    def _poll_keyer(self) -> None:
        """WinKey: Paddle-Unterbrechung beendet die Laufschrift, Tempo-Knopf kurz melden."""
        if not self.keyer:
            return
        st = self.keyer.snapshot()
        breakin, pot, conn = self._keyer_seen
        if st.breakin_id != breakin:
            self.cw_ticker.stop(time.monotonic())
            self._update_sending()
        if st.pot_id != pot and st.connected and pot:
            self.statusBar().showMessage(tr("CW-Tempo: {n} WpM", n=st.wpm), 3000)
        if st.connected != conn and (st.connected or st.error):
            if st.connected:
                self.statusBar().showMessage(tr("WinKey verbunden ({v})", v=wkmod.version_text(st.version)),
                                             5000)
            else:
                self.statusBar().showMessage(tr("WinKey nicht verbunden: {e}", e=st.error), 10000,
                                             level="warn")
        if st.connected or st.error:
            self._keyer_seen = (st.breakin_id, st.pot_id, st.connected)

    def _show_sending_cw(self, text: str) -> None:
        self.cw_ticker.add(text, self._cw_wpm(), time.monotonic())
        self._voice_until = 0.0
        self._update_sending()
        self.sending_timer.start(40)

    def _show_sending_voice(self, n: int, label: str) -> None:
        self.cw_ticker.stop(time.monotonic())
        text = tr("▶ Sprachspeicher {n} ({label})", n=n, label=label) if label \
            else tr("▶ Sprachspeicher {n}", n=n)
        self.lbl_sending.setText(f'<span style="color:{BLUE}">{html_escape(text)}</span>')
        self._voice_until = time.monotonic() + 4.0
        self.sending_timer.start(200)

    def _update_sending(self) -> None:
        """Anzeige „was wird gesendet“ auffrischen (läuft nur, solange etwas zu zeigen ist)."""
        now = time.monotonic()
        if self._voice_until > now:
            return
        st = self.cw_ticker.state(now)
        if st is None:
            self.lbl_sending.setText("")
            self.sending_timer.stop()
            return
        text, done, cur = st
        if done < 0:                                  # Tempo unbekannt: nur anzeigen
            self.lbl_sending.setText(html_escape(text))
            return
        esc = lambda t: html_escape(t).replace(" ", "&nbsp;")   # noqa: E731
        parts = [esc(text[:done])]
        if cur >= 0:
            parts.append(f'<span style="background:{BLUE}; color:{theme.on_signal()}">{esc(text[cur])}</span>')
            rest = text[cur + 1:]
        else:
            rest = text[done:]
        parts.append(f'<span style="color:#8a8a8a">{esc(rest)}</span>')
        self.lbl_sending.setText("".join(parts))

    def _show_wpm(self, wpm: int) -> None:
        if wpm > 0 and cabrillo_mode(self.current_mode()) == "CW":
            self.lbl_sb_wpm.setText(tr("CW {n} WpM", n=wpm))
            self.lbl_sb_wpm.show()
        else:
            self.lbl_sb_wpm.hide()

    def set_esm(self, on: bool) -> None:
        self.cfg["esm_enabled"] = bool(on)
        cfgmod.save(self.cfg)
        self._update_esm_buttons()
        self.statusBar().showMessage(
            tr("Enter sendet (ESM) ist an – Enter löst jetzt Funktionstasten aus") if on
            else tr("Enter sendet (ESM) ist aus – Enter loggt nur"), 5000)

    def toggle_run_sp(self) -> None:
        self.cfg["esm_mode"] = "run" if self.cfg.get("esm_mode", "run") == "sp" else "sp"
        cfgmod.save(self.cfg)
        self._update_esm_buttons()
        self.statusBar().showMessage(tr("Betrieb: Run (du rufst CQ)") if self.cfg["esm_mode"] == "run"
                                     else tr("Betrieb: S&P (du rufst an)"), 4000)

    def _update_esm_buttons(self) -> None:
        on = bool(self.cfg.get("esm_enabled"))
        self.btn_esm.setChecked(on)
        self.btn_esm.setStyleSheet(f"background:{ORANGE}; color:{theme.on_signal()}; font-weight:bold;"
                                   if on else "")
        run = self.cfg.get("esm_mode", "run") != "sp"
        self.btn_runsp.setText("Run" if run else "S&&P")      # „&&“ = ein sichtbares & (0.8.13)
        self.btn_runsp.setStyleSheet(f"background:{GREEN if run else BLUE}; color:{theme.on_signal()}; "
                                     "font-weight:bold;")

    def escape_pressed(self) -> None:
        self.announcer.stop()
        self.toggle_autocq(False)
        self.voice_stop()
        if self.practice is not None:
            self.practice.stop_sending()
        if self.keyer:
            self.keyer.submit("stop")
        elif self.rig and cabrillo_mode(self.current_mode()) == "CW":
            self.rig.submit("stop_morse")
        self.cw_ticker.stop(time.monotonic())
        self._voice_until = 0.0
        self._update_sending()
        self.clear_entry()

    def log_qso(self) -> None:
        if not self.db or not self.contest:
            self.sb.showMessage(tr("Bitte zuerst ein Log anlegen oder öffnen"), 8000, "warn")
            return
        call = self.ed_call.text().strip().upper()
        if not CALL_RE.match(call):
            self._set_status(tr("Rufzeichen prüfen"), ORANGE)
            self.ed_call.setFocus()
            return
        exch = self._exch_text()
        err = self.contest.validate_exchange(exch, self.contest.lookup(call))
        if err:
            self._set_status(err, ORANGE)
            self.ed_exch.setFocus()
            self.ed_exch.selectAll()
            return
        q = self._draft()
        q.time = utc_now().strftime("%Y-%m-%d %H:%M:%S")
        q.exch_s = self.contest.sent_exchange(self._serial(q.band))
        if not self.contest.uses_rst:
            q.rst_s = q.rst_r = ""
        self._store(q)
        self.clear_entry()

    def _serial(self, band: str | None = None) -> int:
        """Nächste eigene Nummer. UKW (serial_per_band): je Band ab 001, sonst durchgehend."""
        from .. import multiop
        per_band = self.contest is not None and (
            getattr(self.contest, "serial_per_band", False) is True
            or multiop.serial_mode(self.contest, multiop.category(self.meta)) == "band")
        if not per_band:
            own = self.serial
        else:
            band = band or self.current_band()
            used = [self._sent_serial(q.exch_s) or 0 for q in self.qsos if q.band == band]
            own = max(used, default=0) + 1
        st = getattr(self, "station", None)
        if st is not None and st.active and self.contest and self.contest.uses_serial:
            return st.serial(own)                    # Stationslog: Nummer vom Hauptplatz
        return own

    def _ukw_km(self, q: Qso) -> float | None:
        f = getattr(self.contest, "qso_km", None)
        return f(q) if f is not None else None

    def _sent_serial(self, exch_s: str) -> int | None:
        f = getattr(self.contest, "sent_serial", None)
        if f is not None:
            return f(exch_s)
        return int(exch_s) if exch_s.isdigit() else None

    def add_remote_qso(self, q: Qso) -> None:
        """QSO von einem anderen Platz des Stationslogs anhängen (steht schon in der Datei) –
        einzeln bewerten statt das ganze Log neu zu rechnen (0.10.2)."""
        self.qsos.append(q)
        self.scorer.evaluate(q, commit=True)
        n = self._sent_serial(q.exch_s)
        if n is not None and self.contest.uses_serial:
            self.serial = max(self.serial, n + 1)
        self._append_row(q)
        self.tbl.scrollToBottom()

    def _store(self, q: Qso) -> None:
        self.station.stamp(q)
        self.db.add(q)
        self.station.qso_added(q)
        self._dirty = True
        if self.practice is None:                 # Übung: erfundene Stationen nie lernen
            self.history.learn_qso(self.contest, q.call, q.exch_r, q.time)
        self.qsos.append(q)
        self.announcer.logged(q.call)
        self.scorer.evaluate(q, commit=True)
        n = self._sent_serial(q.exch_s)
        if n is not None and self.contest.uses_serial:
            self.serial = max(self.serial, n + 1)
        self._append_row(q)
        self.tbl.scrollToBottom()
        self.refresh_score()
        hint = self._qtc_hint(q.call)
        if hint:
            self.statusBar().showMessage(hint, 60000)

    # ================================================================ QTC (WAE)
    def _qtc_hint(self, call: str) -> str:
        """„QTC möglich: noch 10 von 10 (Strg+Q)“ – oder leer, wenn nicht passend."""
        c = self.contest
        if not c or not c.qtc or not call:
            return ""
        limit = int(c.qtc.get("max_per_station", qtcmod.MAX_PER_STATION))
        if c.qtc_both_ways():                         # WAE RTTY: geben und empfangen
            lk = c.lookup(call)
            if lk is None or c.qtc_other_continent_problem(lk):
                return ""
            n = qtcmod.remaining(self.qtcs, call, limit, True)
            if n == 0:
                return tr("QTC mit {call}: alle {limit} schon ausgetauscht", call=call.upper(),
                          limit=limit)
            return tr("QTC möglich mit {call}: noch {n} von {limit} (Strg+Q)",
                      call=call.upper(), n=n, limit=limit)
        if not c.qtc_receiving():                    # eigene Station gibt QTCs (ab 0.9.4)
            mycall = self.meta.get("mycall", "")
            if c.lookup(call) is None or qtcmod.receiver_problem(c, call, mycall, []):
                return ""
            n = qtcmod.give_remaining(self.qtcs, call, limit)
            if n == 0:
                return tr("QTC an {call}: alle {limit} schon gegeben", call=call.upper(),
                          limit=limit)
            if not qtcmod.give_candidates(self.qsos, self.qtcs, call, c.dupe_key):
                return ""
            return tr("QTC möglich an {call}: noch {n} von {limit} (Strg+Q)", call=call.upper(),
                      n=n, limit=limit)
        if c.qtc_sender_problem(c.lookup(call)) or c.lookup(call) is None:
            return ""
        n = qtcmod.remaining(self.qtcs, call, limit)
        if n == 0:
            return tr("QTC von {call}: alle {limit} schon empfangen", call=call.upper(), limit=limit)
        return tr("QTC möglich von {call}: noch {n} von {limit} (Strg+Q)", call=call.upper(),
                  n=n, limit=limit)

    def receive_qtc(self) -> None:
        """Strg+Q: QTC-Fenster öffnen – Empfangen (Station in Europa, nur Mitschreiben)
        oder Geben (Station außerhalb Europas, ab 0.9.4)."""
        c = self.contest
        if not self.db or not c:
            return
        if not c.qtc:
            self.statusBar().showMessage(tr("QTCs gibt es nur im WAE DX Contest"), 8000, level="warn")
            return
        if not c.qtc_receiving():
            self.give_qtc()
            return
        if c.qtc_both_ways():                         # WAE RTTY: jeder gibt und empfängt
            box = QMessageBox(self)
            box.setWindowTitle(tr("QTC"))
            box.setText(tr("QTCs empfangen oder geben?"))
            b_rx = box.addButton(tr("Empfangen"), QMessageBox.ButtonRole.AcceptRole)
            b_tx = box.addButton(tr("Geben"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() is b_tx:
                self.give_qtc()
                return
            if box.clickedButton() is not b_rx:
                return
        sender = self.ed_call.text().strip().upper()
        if not sender and self.qsos:
            sender = self.qsos[-1].call.upper()
        worked = {q.call.upper() for q in self.qsos}
        dlg = QtcDialog(c, self.meta.get("mycall", ""), self.qtcs, sender, worked, self)
        if not dlg.exec() or not dlg.result:
            return
        now = utc_now().strftime("%Y-%m-%d %H:%M:%S")
        for t in dlg.result:
            t.time, t.band, t.mode, t.freq = (now, self.current_band(), self.current_mode(),
                                              self.current_freq())
        self.db.add_qtcs(dlg.result)
        self.station.qtcs_changed(dlg.result)
        self.qtcs.extend(dlg.result)
        self._dirty = True
        self.scorer.set_qtcs(len(self.qtcs))
        self.refresh_score()
        self.statusBar().showMessage(
            tr("{n} QTCs von {sender} gespeichert (+{n} Punkte)", n=len(dlg.result),
               sender=dlg.result[0].sender), 10000)

    def _stop_cw(self) -> None:
        if self.keyer:
            self.keyer.submit("stop")
        elif self.rig and self._rig_connected():
            self.rig.submit("stop_morse")
        self.cw_ticker.stop(time.monotonic())
        self._update_sending()

    def give_qtc(self) -> None:
        """QTCs geben (eigene Station außerhalb Europas). In CW sendet das Fenster Zeile für
        Zeile – nur, wenn der Nutzer Enter oder F2 drückt."""
        c = self.contest
        if self.practice is not None:
            self.statusBar().showMessage(tr("QTCs geben geht im Übungsmodus noch nicht"), 8000,
                                         level="warn")
            return
        receiver = self.ed_call.text().strip().upper()
        if not receiver and self.qsos:
            receiver = self.qsos[-1].call.upper()
        cm = cabrillo_mode(self.current_mode())
        cw = cm in ("CW", "RY")                     # RTTY: Zeilen gehen über fldigi raus
        if cm == "RY":
            send, stop = self.companions.send_text, self.companions.abort
        else:
            send, stop = (lambda text: self._send_cw(text, warn=True)), self._stop_cw
        dlg = QtcGiveDialog(c, self.meta.get("mycall", ""), self.qtcs, self.qsos, receiver, cw,
                            send=send,
                            stop=stop, say=self.announcer.qtc,
                            phonetic=self.announcer.phonetic, parent=self)
        ok = dlg.exec()
        self.announcer.stop()
        if not ok or not dlg.result:
            return
        now = utc_now().strftime("%Y-%m-%d %H:%M:%S")
        for t in dlg.result:
            t.time, t.band, t.mode, t.freq = (now, self.current_band(), self.current_mode(),
                                              self.current_freq())
        self.db.add_qtcs(dlg.result)
        self.station.qtcs_changed(dlg.result)
        self.qtcs.extend(dlg.result)
        self._dirty = True
        self.scorer.set_qtcs(len(self.qtcs))
        self.refresh_score()
        self.statusBar().showMessage(
            tr("{n} QTCs an {receiver} gegeben (+{n} Punkte)", n=len(dlg.result),
               receiver=dlg.result[0].receiver), 10000)

    # ================================================== Stationslog (mehrere Plätze, ab 0.10)
    def show_station(self) -> None:
        StationDialog(self.station, self).exec()

    def open_station_window(self) -> None:
        """Fenster „Station“ zeigen (Klick auf die Stationslog-Anzeige unten rechts)."""
        self.st_dock.show()
        self.st_dock.raise_()
        self.station.refresh_view()

    def write_station_message(self) -> None:
        """Strg+T: Fenster „Station“ öffnen und gleich in die Nachrichtenzeile springen."""
        self.open_station_window()
        self.st_dock.activateWindow()
        self.station_view.focus_input()
        if not self.station.active:
            self.statusBar().showMessage(tr("Nachrichten gibt es nur im Stationslog (mehrere "
                                            "Plätze) – einrichten unter Station → Stationslog …"),
                                         8000, level="warn")

    def change_operator(self) -> None:
        if not self.station.active:
            self.statusBar().showMessage(tr("Operator wechseln gibt es nur im Stationslog "
                                            "(mehrere Plätze)"), 8000, level="warn")
            return
        self.station.ask_operator()

    def show_qtcs(self) -> None:
        if not self.db or not self.contest:
            return
        if not self.contest.qtc:
            self.statusBar().showMessage(tr("QTCs gibt es nur im WAE DX Contest"), 8000, level="warn")
            return
        dlg = QtcListDialog(self.qtcs, self, mycall=self.meta.get("mycall", ""))
        if not dlg.exec():
            return
        uids = {t.id: t.uid for t in self.qtcs}
        for qid in dlg.deleted:
            self.db.delete_qtc(qid)
            self.station.qtc_deleted(uids.get(qid, ""))
        for t in dlg.changed:
            self.db.update_qtc(t)
        self.station.qtcs_changed(dlg.changed)
        if dlg.deleted or dlg.changed:
            self._dirty = True
            self.qtcs = self.db.all_qtcs()
            self.scorer.set_qtcs(len(self.qtcs))
            self.refresh_score()

    # ================================================================ Punkte
    def refresh_score(self) -> None:
        if not self.scorer:
            return
        c, s = self.contest, self.scorer
        rows = [b for b in c.bands if b in s.band_stats] + \
               [b for b in s.band_stats if b not in c.bands]
        extra = 1 if c.qtc else 0                 # Zeile „QTC“ (WAE)
        self.tbl_score.setRowCount(len(rows) + 1 + extra)
        tot = {"qsos": 0, "points": 0, "dupes": 0}
        for r, b in enumerate(rows):
            bs = s.band_stats[b]
            # WAE: Gewichtung der Multis direkt am Band zeigen („80 ×4“)
            label = f"{b} ×{c.mult_weight(b)}" if c.mult_factor else b
            vals = [label, bs["qsos"], bs["points"]]
            for k, _lab in c.mult_types:
                if c.mults_per_band:
                    vals.append(len(s.mults.get((k, b), set())))
                else:
                    vals.append(bs["mults"].get(k, 0))
            vals.append(bs["dupes"])
            for k in tot:
                tot[k] += bs[k]
            for col, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tbl_score.setItem(r, col, it)
        if extra:
            vals = ["QTC", "", s.qtc_points] + ["" for _ in c.mult_types] + [""]
            for col, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tbl_score.setItem(len(rows), col, it)
        vals = [tr("Summe"), tot["qsos"], tot["points"] + s.qtc_points] + \
               [s.weighted_mults(k) for k, _ in c.mult_types] + [tot["dupes"]]
        bold = QFont()
        bold.setBold(True)
        for col, v in enumerate(vals):
            it = QTableWidgetItem(str(v))
            it.setFont(bold)
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if c.mult_factor and 3 <= col < 3 + len(c.mult_types):
                it.setToolTip(tr("Multis mal Band-Faktor zusammengezählt"))
            self.tbl_score.setItem(len(rows) + extra, col, it)
        self.tbl_score.schedule_fit()
        # freies Log (0.10.18): keine Punkte – dort zählen nur die QSOs
        self.lbl_score.setText(num(s.total_qsos) if is_free(c) else num(s.score))
        self._update_rate()
        if self.stats_win is not None and self.stats_win.isVisible():
            self.stats_win.refresh(self.contest, self.scorer, self.qsos)

    def _update_rate(self) -> None:
        now = utc_now().replace(tzinfo=None)
        n60 = n10 = 0
        for q in reversed(self.qsos):
            try:
                t = datetime.strptime(q.time, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            age = now - t
            if age > timedelta(minutes=60):
                break
            n60 += 1
            if age <= timedelta(minutes=10):
                n10 += 1
        self.lbl_rate.setText(tr("Rate: {n60} QSOs/60 min · {n10}/h (letzte 10 min)", n60=n60, n10=n10 * 6))

    # ============================================================ Band/Mode/CAT
    def _rig_connected(self) -> bool:
        return bool(self.rig and self.rig.snapshot().connected)

    def _band_changed(self, band: str) -> None:
        if getattr(self, "_updating", False):
            return
        if self.locked_by:
            return
        f = DEFAULT_FREQ.get(band)
        if f:
            if self._rig_connected():
                self.rig.submit("set_freq", f)
            self.manual_freq = f
        self._show_freq(self.current_freq() if self._rig_connected() else f)
        self.update_check()

    def _mode_changed(self, mode: str) -> None:
        if getattr(self, "_updating", False):
            return
        if self._rig_connected() and not self.locked_by and mode not in ("FT8", "FT4", "PSK31", "JT65"):
            self.rig.submit("set_mode", self._rig_mode_for(mode), RIG_FILTER)
        if not self.ed_call.text():
            rst = default_rst(mode)
            self.ed_rst_s.setText(rst)
            self.ed_rst_r.setText(rst)
        self._update_sent()
        self._update_macro_buttons()
        self.update_check()

    def _step_band(self, step: int) -> None:
        bands = self.contest.bands if self.contest else BAND_NAMES
        cur = self.current_band()
        i = bands.index(cur) if cur in bands else 0
        self.cb_band.setCurrentText(bands[(i + step) % len(bands)])

    def qsy_khz(self, khz: int) -> None:
        if self.locked_by:
            self.sb.showMessage(tr("Funkgerät wird von {locked_by} gesteuert – Frequenz bitte dort ändern", locked_by=self.locked_by), 8000, "warn")
            return
        hz = khz * 1000
        band = band_for_freq(hz)
        if not band:
            self.sb.showMessage(tr("{khz} kHz liegt in keinem Amateurband", khz=khz), 8000, "warn")
            return
        if self._rig_connected():
            self.rig.submit("set_freq", hz)
        self.manual_freq = hz
        self._updating = True
        self.cb_band.setCurrentText(band)
        self._updating = False
        self._show_freq(hz)

    def _show_freq(self, hz: int) -> None:
        if hz:
            khz = hz / 1000
            self.lbl_freq.setText(f"{num(khz, 2)} kHz")
            # UKW/UHF (ab 100 MHz) braucht mehr Platz: einmal breiter, danach bleibt es so
            w = widest(self.lbl_freq, [self.lbl_freq.text()])
            if w + 4 > self._freq_width():
                self.lbl_freq.setMinimumWidth(w + 4)
        else:
            self.lbl_freq.setText("—")

    def _freq_width(self) -> int:
        try:
            return int(self.lbl_freq.minimumWidth())
        except (TypeError, ValueError):
            return 1 << 30

    def _freq_tick(self) -> None:
        """Nur die Frequenz (und die Markierung in der Bandmap) – alles andere macht _tick."""
        rig = self.rig
        if rig is None:
            return
        st = rig.snapshot()
        if not st.connected or not st.freq or st.freq == getattr(self, "_fast_freq", 0):
            return
        self._fast_freq = st.freq
        if band_for_freq(st.freq) != self.cb_band.currentText():
            return                                       # Bandwechsel: macht _tick
        self._show_freq(st.freq)
        self._refresh_bandmap()

    def _tick(self) -> None:
        if self.rig is not None and hasattr(self.rig, "alive"):
            self.rig.alive()                             # Sende-Wächter: Oberfläche lebt (0.10.46)
        self.lbl_clock.setText(utc_now().strftime("%H:%M:%S UTC"))
        self.lbl_clock_local.setText(local_clock_text())
        if not getattr(self, "_ann_live", False) and self.isVisible():
            self._ann_live = True                        # Fenster da: noch 5 s still übernehmen
            self.announcer.quiet(5)
        conn = self._rig_connected()
        if conn and not getattr(self, "_ann_rig_conn", False):
            self.announcer.quiet(3)                      # Funkgerät gerade verbunden
        self._ann_rig_conn = conn
        self.announcer.band_mode(self.cb_band.currentText(), self.current_mode())
        self._check_piper_download()
        # selbst gestartetes rigctld beendet? (Gerät belegt, falscher Port …)
        if self.rigctld_proc and self.rigctld_proc.poll() is not None:
            err = b""
            try:
                err = self.rigctld_proc.stderr.read() or b""
            except (OSError, ValueError):
                pass
            msg = err.decode("utf-8", "replace").strip().splitlines()
            self.statusBar().showMessage(
                tr("rigctld wurde beendet") + (f": {msg[-1]}" if msg else "") +
                tr(" – läuft es schon, oder stimmt die Schnittstelle?"), 20000, level="error")
            self.rigctld_proc = None
        self._icom_tick()
        self._update_lock()
        self._check_band_offer()
        self._cluster_tick()
        self._beacon_tick()
        self._map_marks_tick()
        self._rotor_tick()
        self._prop_tick()
        # CAT
        if self.rig:
            st = self.rig.snapshot()
            if st.connected:
                text, style = cat_text(st.model, self.cfg.get("rig_model", 0),
                                       self._profile_name(), self.locked_by)
                self.lbl_cat.setText(text)
                self.lbl_cat.setStyleSheet(style)
                self._updating = True
                band = band_for_freq(st.freq)
                if band and band != self.cb_band.currentText():
                    self.cb_band.setCurrentText(band)
                    self.update_check()
                mode = (st.mode or "").upper()
                if mode and mode != self.cb_mode.currentText() and \
                        not (mode in ("PKTUSB", "PKTLSB") and self.cb_mode.currentText() in ("FT8", "FT4")) \
                        and not (mode in ("PKTUSB", "PKTLSB", "RTTY", "RTTYR")
                                 and self.cb_mode.currentText() in ("RTTY", "RTTYR")):
                    if self.cb_mode.findText(mode) < 0:
                        self.cb_mode.addItem(mode)
                    self.cb_mode.setCurrentText(mode)
                    self._update_macro_buttons()
                    if not self.ed_call.text():
                        rst = default_rst(mode)
                        self.ed_rst_s.setText(rst)
                        self.ed_rst_r.setText(rst)
                    self._update_sent()
                self._updating = False
                self._show_freq(st.freq)
                self._show_wpm(self._cw_wpm())
                if st.notice_id != getattr(self, "_rig_notice_id", 0):
                    self._rig_notice_id = st.notice_id
                    self._show_rig_notice(st.notice_long or st.notice)
            else:
                self.lbl_cat.setText(tr("CAT: getrennt · {profile_name}", profile_name=self._profile_name()))
                self.lbl_cat.setStyleSheet(f"color:{RED};")
                self.lbl_cat.setToolTip(st.error)
                self._show_freq(self.manual_freq)
                self._show_wpm(0)
        else:
            self._show_freq(self.manual_freq)
        self._poll_keyer()
        # WSJT-X
        if self.wsjtx:
            if self.wsjtx.error:
                self.lbl_sb_wsjtx.setText(f"WSJT-X: {self.wsjtx.error}")
            else:
                self.lbl_sb_wsjtx.setText(tr("FT8: lauscht auf {address}:{port}",
                                             address=self.wsjtx.address, port=self.wsjtx.port))
            while not self.wsjtx.records.empty():
                self._wsjtx_qso(self.wsjtx.records.get_nowait())
        self._check_flag_download()
        self._check_map_download()
        self.gpsw.tick()                          # GPS (0.10.25), drosselt sich selbst
        if self.daily is not None and not self.daily.is_alive():
            self._finish_daily_update()
        if getattr(self, "vcheck", None) is not None and not self.vcheck.is_alive():
            self._finish_version_check()
        self._check_callbook_job()
        if time.monotonic() - self._last_slow_tick >= 5:
            self._last_slow_tick = time.monotonic()
            self._slow_tick()
        # Uhr-Rate gelegentlich aktualisieren
        if int(time.time()) % 30 == 0:
            self._update_rate()

    def _wsjtx_qso(self, rec: dict, program: str = "WSJT-X") -> None:
        """Geloggtes QSO aus WSJT-X & Co. oder (0.10.6) aus fldigi übernehmen."""
        if not self.db or not self.contest:
            return
        q = adif_to_qso(rec)
        if program == "fldigi":
            q.source = "fldigi"
            q.exch_s = ""                 # eigenen Austausch rechnet GoGoHam (Nummer von fldigi)
            if not q.mode:
                q.mode = "RTTY"
        if not q.call or not q.band:
            return
        if not q.time:
            q.time = utc_now().strftime("%Y-%m-%d %H:%M:%S")
        # doppelte Meldungen derselben Verbindung ignorieren
        for old in self.qsos[-30:]:
            if old.call == q.call and old.band == q.band and old.time[:16] == q.time[:16]:
                return
        if not q.exch_s:
            stx = (rec.get("STX") or "").strip()
            serial = int(stx) if program == "fldigi" and stx.isdigit() and int(stx) > 0 \
                else self._serial(q.band)
            q.exch_s = self.contest.sent_exchange(serial)
        self._store(q)
        ev = self.scorer.evals.get(q.id)
        msg = tr("Von {program}: {call} {exch} – ", program=program, call=q.call, exch=q.exch_r)
        msg += "DUPE" if ev and ev.dupe else tr("{p0} Pkt", p0=ev.points if ev else 0)
        if ev and ev.new_mults:
            msg += tr(" · neuer Multi ") + ", ".join(v for _t, v in ev.new_mults)
        self.statusBar().showMessage(msg, 15000)

    def start_rig(self, listen: bool = False) -> None:
        """listen=True (S&P-Übung, 0.8.29): nur Frequenz/Mode lesen – kein PTT, kein CW, kein
        WinKey, keine PTT-Leitung."""
        if getattr(self, "_ann_live", False):
            self.announcer.quiet(5)                      # Stand des Funkgeräts: keine Ansage
        self.stop_rig()
        if self.practice is not None:                    # Übung: Funkgerät bleibt getrennt …
            listen = listen or bool(getattr(self.practice, "listen", False))
            if not listen:                               # … außer S&P (nur hören)
                return
        rigprofiles.ensure_profiles(self.cfg)
        self.rig_caps = hamlib.rig_caps(self.cfg["rig_model"]) if self.cfg["rig_enabled"] else None
        self._apply_rig_bands()
        self.rig_foreign = False
        if not self.cfg["rig_enabled"]:
            self.lbl_cat.setText(tr("CAT: aus"))
            self.lbl_cat.setStyleSheet("")
            return
        if not self.cfg.get("rig_profiles"):
            self.lbl_cat.setText(tr("CAT: kein Funkgerät – hier klicken"))
            self.lbl_cat.setStyleSheet("")
            return
        self._resync_ptt_service()                      # 0.10.45: alter Dienst ohne PTT-Leitung
        host, port = self.cfg["rig_host"], int(self.cfg["rig_port"])
        moved = self._foreign_port(host, port)          # Regel A (0.10.43)
        if moved:
            port = moved
            self.rig_foreign = True
        elif self.cfg["rig_autostart"] and port_in_use(host, port):
            # Nie einen zweiten rigctld auf denselben Port setzen – den vorhandenen mitbenutzen
            self.rig_foreign = True
            self.statusBar().showMessage(
                tr("Auf {host}:{port} läuft schon ein rigctld (nicht von GoGoHam) – "
                   "GoGoHam benutzt ihn mit und startet keinen zweiten.", host=host, port=port), 15000)
        elif self.cfg["rig_autostart"] and rigprofiles.conn(rigprofiles.active(self.cfg)) == "icom":
            self._start_icom(rigprofiles.active(self.cfg))
        elif self.cfg["rig_autostart"]:
            try:
                self.rigctld_proc = start_rigctld(self.cfg["rig_model"], self.cfg["rig_device"],
                                                  self.cfg["rig_baud"], self.cfg["rig_port"],
                                                  self.cfg.get("rig_extra", ""))
            except (OSError, FileNotFoundError) as e:
                self.statusBar().showMessage(tr("rigctld konnte nicht starten: {e}", e=e), 15000, level="error")
        prof = rigprofiles.active(self.cfg) or {}
        poll_ms = int(prof.get("poll_ms") or 0)          # 0 = automatisch (gemessen)
        poll = max(20, poll_ms) / 1000 if poll_ms else None
        if listen:
            self.rig = RigWorker(host, port, poll=poll, listen_only=True)
            self.rig.start()
            return
        self.rig = RigWorker(host, port, poll=poll)     # PTT über DTR/RTS: schaltet rigctld
        self.rig.start()
        if self.rig_foreign:
            QTimer.singleShot(1500, lambda h=host, p=port: self._check_foreign_ptt(h, p))
        if prof.get("winkey"):
            self.keyer = wkmod.WinKeyWorker(prof["winkey"])
            self.keyer.start()

    def _resync_ptt_service(self) -> None:
        """Einmal je Programmstart: Hintergrund-Dienste von GoGoHam aus älteren Versionen kannten
        die PTT-Leitung noch nicht – Dienst neu schreiben (nur wenn sich etwas ändert)."""
        if getattr(self, "_ptt_resynced", False):
            return
        self._ptt_resynced = True
        if any(p and p.get("service") and rigprofiles.ptt_args(p)
               for p in self.cfg.get("rig_profiles") or []):
            self._sync_rig_services()

    def _check_foreign_ptt(self, host: str, port: int) -> None:
        """PTT über DTR/RTS gewünscht, aber der mitbenutzte rigctld (nicht von GoGoHam) schaltet
        sie nicht? 0.10.46: Gehört er zu einem Dienst, einmal fragen und die Leitung dort
        eintragen (Sicherung, kurzer Neustart). Sonst verständlich darauf hinweisen."""
        from .. import rigdetect, rigservice
        prof = rigprofiles.active(self.cfg) or {}
        if host not in ("127.0.0.1", "localhost") or not rigprofiles.ptt_args(prof):
            return
        have = rigdetect.ptt_type_on_port(port)
        if have is None or have == prof["ptt_line"]:
            return
        line = prof["ptt_line"]
        try:
            u = next((x for x in rigservice.foreign_units() if x["port"] == int(port)), None)
        except (OSError, ValueError):
            u = None
        asked = getattr(self, "_ptt_asked", set())
        self._ptt_asked = asked
        if u is None or u["unit"] in asked:
            self.statusBar().showMessage(tr(
                "Achtung: Der rigctld auf Port {port} (nicht von GoGoHam) sendet nicht über {line}. "
                "Senden geht deshalb über CAT. Damit alle Programme über {line} senden, beim Start "
                "dieses rigctld „--ptt-type={line}“ ergänzen.", port=port, line=line),
                30000, level="warn")
            return
        asked.add(u["unit"])                             # je Programmstart nur einmal fragen
        ans = QMessageBox.question(
            self, tr("PTT über {line}", line=line),
            tr("GoGoHam benutzt für dieses Funkgerät den vorhandenen Dienst {u} (Port {port}) mit. "
               "Dieser schaltet die {line}-Leitung aber nicht – so würden weder GoGoHam noch "
               "WSJT-X, fldigi & Co. über {line} senden.\n\nSoll GoGoHam die Leitung in diesem "
               "Dienst eintragen? Es legt vorher eine Sicherungskopie an. Der Dienst startet "
               "dabei kurz neu – andere Programme sind ein paar Sekunden getrennt.",
               u=u["unit"], port=port, line=line),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        if self._someone_sends(host, port):
            QMessageBox.information(self, tr("PTT über {line}", line=line), tr(
                "Gerade sendet ein Programm über diesen rigctld. Bitte später noch einmal: "
                "GoGoHam fragt beim nächsten Programmstart wieder."))
            return
        errors = rigservice.add_ptt(u, prof)
        if errors:
            QMessageBox.warning(self, tr("PTT über {line}", line=line), "\n".join(errors))
            return
        self.statusBar().showMessage(tr(
            "Dienst {u}: PTT über {line} eingetragen und neu gestartet – jetzt senden alle "
            "Programme darüber.", u=u["unit"], line=line), 20000)

    def _someone_sends(self, host: str, port: int) -> bool:
        """Sendet gerade jemand über diesen rigctld? (Fragt nur „t“ – liest, sendet nichts.)"""
        from ..rig import RigctldClient
        c = RigctldClient(host, port, timeout=2.0)
        try:
            c.connect()
            return (c.command("t") or ["0"])[0].strip() == "1"
        except (OSError, RuntimeError, ConnectionError, IndexError):
            return False
        finally:
            c.close()

    def _foreign_port(self, host: str, port: int) -> int:
        """Regel A (0.10.43): Hält schon ein anderer Dienst (GoGoHome, GoGoHandy, ein übergebener
        rigctld …) dieses Gerät auf einem anderen Port, benutzt GoGoHam ihn mit, statt einen
        zweiten rigctld aufs selbe Gerät zu setzen. 0 = nichts zu tun."""
        from .. import rigservice
        prof = rigprofiles.active(self.cfg) or {}
        if host not in ("127.0.0.1", "localhost") or not prof.get("device") \
                or port_in_use(host, port) or rigprofiles.conn(prof) != "usb":
            return 0
        try:
            u = rigservice.foreign_for(dict(prof, port=-1), rigservice.foreign_units())
        except (OSError, ValueError, KeyError):
            return 0
        if not u or u["port"] == port or not port_in_use("127.0.0.1", u["port"]):
            return 0
        self.statusBar().showMessage(tr(
            "Für dieses Funkgerät läuft schon der Dienst {u} auf Port {p} – GoGoHam benutzt ihn "
            "mit und startet keinen zweiten.", u=u["unit"], p=u["port"]), 15000)
        return int(u["port"])

    def stop_rig(self) -> None:
        if self.keyer:
            self.keyer.stop()
            self.keyer.join(1.5)
            self.keyer = None
        if self.rig:
            self.rig.stop()
            self.rig.join(1.5)
            self.rig = None
        if self.rigctld_proc:
            self.rigctld_proc.terminate()
            try:
                self.rigctld_proc.wait(2)
            except Exception:  # noqa: BLE001
                self.rigctld_proc.kill()
            self.rigctld_proc = None
        if self.icom_bridge:
            self.icom_bridge.terminate()
            try:
                self.icom_bridge.wait(4)
            except Exception:  # noqa: BLE001
                self.icom_bridge.kill()
            self.icom_bridge = None
            self.icom_msgs = None

    def _start_icom(self, prof: dict) -> None:
        """Icom über LAN/WLAN (0.10.30): Brücke starten; sie startet rigctld selbst, sobald
        das Funkgerät verbunden ist. Meldungen liest ein kleiner Faden mit."""
        import queue
        import threading
        from .. import icomlan
        from ..rigprofiles import full_extra
        if not prof.get("net_host"):
            self.statusBar().showMessage(tr("Icom über das Netzwerk: Bitte in den Einstellungen "
                                            "die Adresse des Funkgeräts eintragen."), 15000,
                                         level="error")
            return
        try:
            self.icom_bridge = icomlan.start_bridge(prof, int(prof.get("port", 4532)),
                                                    full_extra(prof))
        except OSError as e:
            self.statusBar().showMessage(tr("rigctld konnte nicht starten: {e}", e=e), 15000,
                                         level="error")
            return
        q = queue.Queue()
        self.icom_msgs = q
        out = self.icom_bridge.stdout

        def reader():
            import json
            try:
                for line in out:
                    try:
                        q.put(json.loads(line))
                    except ValueError:
                        pass
            except (OSError, ValueError):
                pass
        threading.Thread(target=reader, daemon=True).start()
        self.statusBar().showMessage(tr("Verbinde mit dem Funkgerät im Netzwerk ({host}) …",
                                        host=prof["net_host"]), 10000)

    def _icom_tick(self) -> None:
        """Meldungen der Icom-Brücke anzeigen."""
        q = self.icom_msgs
        if q is None:
            return
        from ..hamlib import icom_message
        while not q.empty():
            msg = q.get_nowait()
            st, text = msg.get("state", ""), msg.get("text", "")
            if st == "connected":
                self.statusBar().showMessage(tr("Funkgerät im Netzwerk verbunden: {name}",
                                                name=text or "Icom"), 8000)
                continue
            nice = icom_message(st, text)
            if nice:
                bad = st.startswith("error") or st == "busy"
                self.statusBar().showMessage(nice, 20000, level="error" if bad else "info")
        if self.icom_bridge is not None and self.icom_bridge.poll() is not None and q.empty():
            self.icom_bridge = None
            self.icom_msgs = None

    def start_wsjtx(self) -> None:
        if self.wsjtx:
            self.wsjtx.stop()
            self.wsjtx.join(1.5)
            self.wsjtx = None
        if self.cfg["wsjtx_enabled"] and self.practice is None:
            self.wsjtx = WsjtxListener(int(self.cfg["wsjtx_port"]), self.cfg["wsjtx_address"])
            self.wsjtx.start()
        else:
            self.lbl_sb_wsjtx.setText(tr("FT8: aus"))

    def tidy_logs(self) -> int:
        """Hilfsdateien (-wal/-shm) in den Log-Ordnern aufräumen – Reste ohne Log löschen,
        liegen gebliebene abschließen; das offene Log bleibt, wie es ist (0.10.7.2)."""
        from ..db import tidy_folder
        self._tidy_last = time.monotonic()
        home = Path(self._logs_dir())
        folders = {home, home / "Übung"}
        if self.db:
            folders.add(Path(self.db.path).parent)
        skip = (str(self.db.path),) if self.db else ()
        n = 0
        for f in folders:
            try:
                n += tidy_folder(f, skip)
            except OSError:
                pass
        return n

    def _slow_tick(self) -> None:
        """Alle paar Sekunden: Contest-Uhr, Betriebszeit, Sicherung, Live-Score."""
        if time.monotonic() - getattr(self, "_tidy_last", -1e9) > 300:
            self.tidy_logs()                     # alle 5 Minuten (und beim Start) aufräumen
            self._stick_space_check()
        self._update_contest_time()
        minutes = int(self.cfg.get("backup_minutes", 10))
        if self._dirty and time.monotonic() - self._last_backup >= minutes * 60:
            self._backup_now()
        self._update_live()
        self._weather_tick()
        self.clock.tick()

    def _weather_tick(self) -> None:
        """Funkwetter alle 30 Minuten im Hintergrund holen; Farbe folgt dem aktiven Band."""
        from .. import spaceweather as swmod
        f = self._sw_fetch
        if f is not None and not f.is_alive():
            self._sw, self._sw_fetch = f.result, None
            # ohne Internet nach 5 Minuten noch einmal versuchen
            if self._sw is None or self._sw.empty:
                self._sw_next = time.monotonic() + 5 * 60
            self._sw_band = None
        if self._sw_fetch is None and time.monotonic() >= self._sw_next:
            self._sw_next = time.monotonic() + swmod.INTERVAL_S
            self._sw_fetch = swmod.Fetcher()
            self._sw_fetch.start()
        if self._sw_band != self.current_band():
            self._update_weather()

    def _update_weather(self) -> None:
        from .statusbar import weather_html
        self._sw_band = self.current_band()
        html, tip = weather_html(self._sw, self._sw_band)
        self.sb.weather.setText(html)
        self.sb.weather.setToolTip(tip)

    def contest_running(self) -> bool:
        if not self.contest or not self.contest.schedule:
            return False
        now = utc_now().replace(tzinfo=None)
        s, e = schedule.next_period(self.contest.schedule, now)
        return s <= now < e

    def _update_contest_time(self) -> None:
        c = self.contest
        if not c or not c.schedule:
            self.lbl_ctime.setText("")
            return
        now = utc_now().replace(tzinfo=None)
        parts = [f"{c.name}: {schedule.countdown(c.schedule, now)}"]
        style = ""
        limit = None
        if self.meta.get("cat_operator", "SINGLE-OP") == "SINGLE-OP":
            limit = c.max_hours_classic if self.meta.get("cat_overlay") == "CLASSIC" \
                and c.max_hours_classic else c.max_hours_single
        six = getattr(c, "log_format", "") == "edi" and self.meta.get("edi_section") == "6H"
        if six:                                   # UKW-Klasse „6 Stunden“ (Pausen ab 2 h)
            limit = 6
        if limit:
            times = []
            for q in list(self.qsos) + list(self.qtcs):      # auch QTCs sind Betrieb (WAE)
                try:
                    times.append(datetime.strptime(q.time, "%Y-%m-%d %H:%M:%S"))
                except ValueError:
                    pass
            start, end = schedule.next_period(c.schedule, now)
            if times:
                # Log aus einem früheren Contest: dessen Zeitraum nehmen
                found = schedule.period_of(c.schedule, min(times))
                if found:
                    start, end = found
            brk = 120 if six else (getattr(c, "min_break_minutes", 60) or 60)
            op = schedule.operating_time(times, start, end, now, timedelta(minutes=brk))
            h, m = divmod(int(op.total_seconds()) // 60, 60)
            parts.append(tr("Betriebszeit {h:02d}:{m:02d} von {limit}:00 h (Pausen ab {brk} min)", h=h, m=m, limit=limit, brk=brk))
            used = op.total_seconds() / 3600
            if used > limit:
                style = f"color:{RED}; font-weight:bold;"
            elif used > limit - 1:
                style = f"color:{ORANGE}; font-weight:bold;"
        self.lbl_ctime.setText("\n".join(parts))
        self.lbl_ctime.setStyleSheet(style)

    # ------------------------------------------------------------- Live-Score
    def _update_live(self) -> None:
        want = bool(self.cfg.get("livescore_enabled")) and self.db is not None \
            and self.contest_running() and self.practice is None
        if want and self.live is None:
            user = self.cfg.get("livescore_user") or self.meta.get("mycall", "")
            self.live = lsmod.LiveScore(self.cfg.get("livescore_url", lsmod.DEFAULT_URL),
                                        user, self.cfg.get("livescore_password", ""),
                                        lambda: self._live_xml)
            self._live_xml = lsmod.build_xml(self.contest, self.meta, self.scorer)
            self.live.start()
        elif not want and self.live is not None:
            self.live.stop()
            self.live = None
        if self.live is not None:
            self._live_xml = lsmod.build_xml(self.contest, self.meta, self.scorer)
            self.lbl_sb_live.setText(f"Live-Score: {self.live.status}")
        else:
            self.lbl_sb_live.setText("")

    # --------------------------------------------------------- Übersicht etc.
    def show_stats(self) -> None:
        if self.stats_win is None:
            self.stats_win = StatsWindow(self)
        self.stats_win.refresh(self.contest, self.scorer, self.qsos)
        self.stats_win.show()
        self.stats_win.raise_()

    def _rebuild_history(self, folder) -> None:
        """Call-History neu aufbauen – ohne die Übungslogs (erfundene Stationen)."""
        from .practice_mode import practice_dir
        old = getattr(self, "history", None)
        store = old.store if old is not None else None
        try:
            learn = Path(folder).resolve() != practice_dir().resolve()
        except OSError:
            learn = True
        self.history = chmod.build(folder, cty=self.cty, learn_logs=learn, store=store)

    def show_call_history(self) -> None:
        from .history_dialog import CallHistoryDialog
        CallHistoryDialog(self.history, self.cty, self).exec()

    def import_history(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Call-History importieren"),
                                              str(Path.home() / "Downloads"),
                                              tr("Call-History (*.txt *.csv);;Alle Dateien (*)"))
        if not path:
            return
        try:
            chmod.import_file(path)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, tr("Call-History"), str(e))
            return
        self._rebuild_history(Path(self.db.path).parent if self.db else self._logs_dir())
        QMessageBox.information(self, tr("Call-History"),
                                tr("Importiert. Bekannt sind jetzt {len} Rufzeichen.", len=len(self.history)))

    def _findings(self):
        return logcheck.check(self.contest, self.qsos, self.scorer, self.scp, self.history,
                              meta=self.meta)

    def _edit_qso_id(self, qid: int) -> None:
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            if it is not None and it.data(Qt.ItemDataRole.UserRole) == qid:
                self.tbl.selectRow(r)
                break
        self.edit_selected()

    def check_log(self) -> None:
        if not self.db:
            return
        LogCheckDialog(self._findings(), self, on_edit=self._edit_qso_id).exec()

    # ================================================================= Makros
    def _update_macro_buttons(self) -> None:
        cw = cabrillo_mode(self.current_mode()) == "CW"
        macros = self.cfg["macros_cw" if cw else "macros_ssb"]
        own = not cw and self._own_voice()
        for i, btn in enumerate(self.fbuttons, start=1):
            m = macros.get(f"F{i}", {})
            label = m.get("label", "")
            if own and label == f"Speicher {i}" and f"F{i}" in OWN_VOICE_LABELS:
                text = OWN_VOICE_LABELS[f"F{i}"]
            else:
                text = tr(label)      # Standard-Beschriftungen übersetzt, eigene bleiben
            btn.setText(f"F{i} {text}".strip())
            if own:
                btn.setToolTip(tr("Eigene Aufnahmen: {macro}", macro=self._ssb_text(i)))
            elif not cw:
                btn.setToolTip(tr("Sprachspeicher {n} im Funkgerät", n=m.get("voice", 0)))
            else:
                btn.setToolTip(m.get("text", ""))

    # ---------------------------------------------------------------- Auto-CQ
    def toggle_autocq(self, on: bool | None = None) -> None:
        on = (not self.autocq_timer.isActive()) if on is None else on
        if on:
            if self.locked_by:
                self.statusBar().showMessage(tr("{locked_by} ist aktiv – kein Auto-CQ", locked_by=self.locked_by), 6000, level="warn")
                self.btn_autocq.setChecked(False)
                return
            if not self._rig_connected():
                self.statusBar().showMessage(tr("Auto-CQ braucht eine CAT-Verbindung"), 5000, level="warn")
                self.btn_autocq.setChecked(False)
                return
            period = int(self.cfg.get("autocq_msg_sec", 3)) + int(self.cfg.get("autocq_listen_sec", 8))
            self.run_macro(1)
            # Eigene Aufnahmen: der Takt beginnt erst, wenn die Ansage fertig ist
            self.autocq_timer.start(AUTOCQ_WAIT_MS if self._vs != "idle" else period * 1000)
            self.btn_autocq.setChecked(True)
            self.btn_autocq.setText(f"Auto-CQ ({period} s)")
            self.btn_autocq.setStyleSheet(f"background:{GREEN}; color:{theme.on_signal()}; font-weight:bold;")
        else:
            self.autocq_timer.stop()
            self.btn_autocq.setChecked(False)
            self.btn_autocq.setText(tr("Auto-CQ"))
            self.btn_autocq.setStyleSheet("")

    def _autocq_fire(self) -> None:
        if self.ed_call.text().strip():
            self.toggle_autocq(False)
            return
        if self._vs != "idle":
            return                                     # eigene Ansage läuft noch
        self.run_macro(1)
        if self._vs != "idle":
            self.autocq_timer.start(AUTOCQ_WAIT_MS)

    def _show_rig_notice(self, text: str) -> None:
        """Hinweis des Funkgeräts in der Hinweiszeile – verschwindet nach 10 s oder sobald
        wieder eine Funktionstaste/Enter benutzt wird."""
        self._rig_notice_text = text
        self.sb.showMessage(text, 10000, "warn")

    def _clear_rig_notice(self, text: str | None = None) -> None:
        cur = getattr(self, "_rig_notice_text", "")
        if cur and (text is None or text == cur) and self.sb.currentMessage() == cur:
            self.sb.clearMessage()
        if text is None or text == cur:
            self._rig_notice_text = ""

    def run_macro(self, n: int, manual: bool = False) -> None:
        self._clear_rig_notice()
        if manual and self.autocq_timer.isActive():
            self.toggle_autocq(False)          # jede Funktionstaste stoppt Auto-CQ
            if n == 1:
                return
        cmode = cabrillo_mode(self.current_mode())
        if cmode not in ("PH", "CW"):
            return
        if self.locked_by:
            self.statusBar().showMessage(tr("{locked_by} ist aktiv – GoGoHam sendet währenddessen nichts", locked_by=self.locked_by), 6000, level="warn")
            return
        if self.practice is not None:                    # Übung: Betriebsart der Übung zählt
            if self.practice.s.mode == "SSB":
                self._practice_ssb(n)
                return
            cmode = "CW"
        if not self._rig_connected() and self.practice is None:
            self.statusBar().showMessage(tr("Funktionstasten brauchen eine CAT-Verbindung"), 5000, level="warn")
            return
        if cmode == "PH":
            m = self.cfg["macros_ssb"].get(f"F{n}", {})
            if self._own_voice():
                self.say(self._ssb_text(n))
                return
            if int(m.get("voice", 0)) > 0:
                if self.rig_caps and not self.rig_caps.can_voice:
                    self.statusBar().showMessage(
                        tr("{profile_name}: Sprachspeicher über CAT kann dieses Gerät laut Hamlib nicht", profile_name=self._profile_name()), 6000, level="warn")
                    return
                self.rig.submit("send_voice_mem", int(m["voice"]))
                self._show_sending_voice(int(m["voice"]), m.get("label", ""))
                self.statusBar().showMessage(f"Sprachspeicher {m['voice']}", 3000)
        else:
            m = self.cfg["macros_cw"].get(f"F{n}", {})
            text = m.get("text", "")
            ex = self.contest.sent_exchange(self._serial()) if self.contest else ""
            text = (text.replace("{MYCALL}", self.meta.get("mycall", ""))
                        .replace("{CALL}", self.ed_call.text().strip().upper())
                        .replace("{EXCH}", ex)
                        .replace("{RST}", self.ed_rst_s.text().strip()))
            text = " ".join(text.split())
            if text:
                self._send_cw(text, warn=True)

    # ================================================================= Export
    def export_log(self) -> None:
        """Format wählen – das vom Contest verlangte ist vorausgewählt."""
        if not self.db:
            return
        dlg = ExportDialog(self.contest, self)
        if not dlg.exec():
            return
        fmt = dlg.choice()
        if fmt == "cabrillo":
            self.export_cabrillo()
        elif fmt == "adif":
            self.export_adif()
        elif fmt == "edi":
            self.export_edi()
        elif fmt == "bbt":
            self.export_bbt()

    def export_bbt(self) -> None:
        """Bayerischer Bergtag: je Band eine Textdatei mit Deckblatt und Logblatt (0.10.42)."""
        if not self.db:
            return
        findings = self._findings()
        if any(f.level == "warn" for f in findings):
            dlg = LogCheckDialog(findings, self, for_export=True, on_edit=self._edit_qso_id)
            if not dlg.exec():
                return
        bands = [b for b in self.contest.bands if any(q.band == b for q in self.qsos)]
        if not bands:
            QMessageBox.information(self, tr("BBT-Deckblatt"), tr(
                "Im Log sind noch keine QSOs auf den Bändern dieses Contests."))
            return
        from .. import bbt
        from .bbt_dialog import BbtDialog
        dlg = BbtDialog(self.meta, bands, self)
        if not dlg.exec():
            return
        self.meta["bbt"] = bbt.dump(dlg.data)
        self.db.set_meta({"bbt": self.meta["bbt"]})
        call = self.meta.get("mycall", "")
        sug = bbt.filename(self._export_suggestion(".txt"), call, bands[0])
        path, _ = QFileDialog.getSaveFileName(self, tr("BBT-Deckblatt + Log speichern (eine Datei je Band)"),
                                              sug, tr("Text (*.txt)"))
        if not path:
            return
        start = self._contest_start()
        written = []
        for b in bands:
            out = Path(bbt.filename(path, call, b))
            out.write_bytes(bbt.sheet(self.contest, self.meta, self.qsos, self.scorer, b, start))
            written.append(str(out))
        self._show_submit(written)

    def _contest_start(self) -> datetime:
        """Beginn des Contests, zu dem das Log gehört (für Winter/Sommer); sonst erste QSO-Zeit."""
        times = []
        for q in self.qsos:
            try:
                times.append(datetime.strptime(q.time, "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                pass
        if not times:
            return datetime.now(timezone.utc).replace(tzinfo=None)
        rule = getattr(self.contest, "schedule", None)
        try:
            found = schedule.period_of(rule, min(times)) if rule else None
        except (KeyError, ValueError, IndexError, TypeError):
            found = None
        return found[0] if found else min(times)

    def export_edi(self) -> None:
        """EDI (UKW): eine Datei je Band, z. B. log_2m.edi, log_70cm.edi."""
        if not self.db:
            return
        findings = self._findings()
        if any(f.level == "warn" for f in findings):
            dlg = LogCheckDialog(findings, self, for_export=True, on_edit=self._edit_qso_id)
            if not dlg.exec():
                return
        bands = [b for b in self.contest.bands if any(q.band == b for q in self.qsos)]
        if not bands:
            QMessageBox.information(self, "EDI", tr("Im Log sind noch keine QSOs auf den Bändern "
                                                    "dieses Contests."))
            return
        sug = self._export_suggestion(".edi")
        path, _ = QFileDialog.getSaveFileName(self, tr("EDI speichern (eine Datei je Band)"), sug,
                                              tr("EDI (*.edi)"))
        if not path:
            return
        from ..export import edi, edi_filename
        written = []
        for b in bands:
            out = Path(edi_filename(path, b))
            out.write_bytes(edi(self.contest, self.meta, self.qsos, self.scorer, b))
            written.append(str(out))
        self._show_submit(written)

    def export_cabrillo(self) -> None:
        if not self.db:
            return
        findings = self._findings()
        if any(f.level == "warn" for f in findings):
            dlg = LogCheckDialog(findings, self, for_export=True, on_edit=self._edit_qso_id)
            if not dlg.exec():
                return
        sug = self._export_suggestion(".cbr")
        path, _ = QFileDialog.getSaveFileName(self, tr("Cabrillo speichern"), sug,
                                              tr("Cabrillo (*.cbr *.log *.txt)"))
        if not path:
            return
        Path(path).write_text(cabrillo(self.contest, self.meta, self.qsos, self.scorer,
                                       self.qtcs),
                              encoding="utf-8")
        self._show_submit([path])

    def export_adif(self) -> None:
        if not self.db:
            return
        sug = self._export_suggestion(".adi")
        path, _ = QFileDialog.getSaveFileName(self, tr("ADIF speichern"), sug, tr("ADIF (*.adi *.adif)"))
        if not path:
            return
        # DXCC-Nummern: cty.csv bei Bedarf einmal nachladen
        if self.cty and not self.cty.dxcc:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            if ctymod.download_csv():
                self.cty.load_dxcc()
            QApplication.restoreOverrideCursor()
        services = cbmod.services_from_config(self.cfg) if self.cfg.get("callbook_enabled") else []
        missing = sorted({q.call.upper() for q in self.qsos} - set(self.cb_cache))
        if services and missing:
            self._pending_adif = path
            self.cb_job = cbmod.CallbookJob(services, missing)
            self.cb_progress = QProgressDialog(tr("Name und QTH werden nachgeschlagen …"),
                                               tr("Ohne Rest speichern"), 0, len(missing), self)
            self.cb_progress.setWindowTitle(tr("ADIF-Export"))
            self.cb_progress.setMinimumDuration(0)
            self.cb_progress.setValue(0)
            self.cb_job.start()
            return
        self._write_adif(path)

    def _check_callbook_job(self) -> None:
        job = self.cb_job
        if not job:
            return
        if self.cb_progress is not None:
            if self.cb_progress.wasCanceled():
                job.cancel()
            self.cb_progress.setValue(job.done)
        if job.is_alive():
            return
        for call, e in job.results.items():
            self.db.set_callbook(call, e.name, e.qth, e.grid, e.source)
        if self.cb_progress is not None:
            self.cb_progress.close()
            self.cb_progress = None
        self.cb_job = None
        self.cb_cache = self.db.callbook()
        path, self._pending_adif = self._pending_adif, ""
        self._write_adif(path)
        msg = tr("Name/QTH gefunden: {len} von {total}", len=len(job.results), total=job.total)
        if job.errors:
            msg += tr(" · Fehler: ") + "; ".join(f"{k}: {v}" for k, v in job.errors.items())
        self.statusBar().showMessage(msg, 20000)
        self.reload()

    def _write_adif(self, path: str) -> None:
        Path(path).write_text(adif(self.contest, self.meta, self.qsos, self.cb_cache),
                              encoding="utf-8")
        self.statusBar().showMessage(tr("ADIF gespeichert: {path}", path=path), 8000)
        if getattr(self.contest, "log_format", "") == "adif" and not getattr(self.contest, "free", False):
            self._show_submit([path])           # Contest verlangt ADIF (PODXS): Einsendeweg zeigen

    def _show_submit(self, files: list[str]) -> None:
        """Nach dem Export: wohin mit dem Log? (0.10.41)"""
        from .submit_dialog import SubmitDialog
        SubmitDialog(self.contest, files, self.meta.get("mycall", ""), list(self.qsos), self).exec()

    # ========================================================== Einstellungen
    def edit_log_settings(self) -> None:
        if not self.db:
            self.new_log()
            return
        dlg = LogSettingsDialog(self.meta, self)
        if dlg.exec():
            self.meta = dlg.meta
            self._remember_station(self.meta)
            self.db.set_meta(self.meta)
            self.station.meta_changed(self.meta)
            self._setup_contest()
            self.reload()

    def apply_my_grid(self, grid: str) -> None:
        """Locator ins offene Log schreiben (GPS, 0.10.25) – wie im Fenster Log-Einstellungen."""
        if not self.db:
            return
        self.meta["my_grid"] = grid
        self.db.set_meta(self.meta)
        self.station.meta_changed(self.meta)
        self._setup_contest()
        self.reload()
        self._map_home()
        applog.message(f"Locator vom GPS übernommen: {grid}")
        self.statusBar().showMessage(tr("Locator {g} vom GPS ins Log übernommen ✓", g=grid), 8000)

    OPERATOR_KEYS = ("mycall", "my_grid", "name", "address", "email", "club", "my_dok",
                     "my_licyear", "my_zone", "my_itu")

    def _prefill_meta(self, meta: dict) -> dict:
        """Neues Log vorausfüllen (0.10.11): zuerst Einstellungen → Operator, dann was im
        zuletzt offenen Log stand, dann sonst Gemerktes. Alter aus dem Geburtsdatum."""
        from .operator_page import age_from
        sd = self.cfg.get("station_defaults") or {}
        for k in self.OPERATOR_KEYS:
            if sd.get(k):
                meta[k] = str(sd[k])
        if self.meta.get("mycall"):
            for k in ("mycall", "operators", "my_zone", "my_grid", "name", "address",
                      "email", "club", "cat_power"):
                if not sd.get(k) and self.meta.get(k):
                    meta[k] = self.meta[k]
        for k, v in sd.items():
            if k in STATION_KEYS and v and not meta.get(k):
                meta[k] = v
        age = age_from(sd)
        if age:
            meta["my_age"] = age
        gps_grid = self.gpsw.grid() if getattr(self, "gpsw", None) else ""
        if gps_grid:
            meta["my_grid"] = gps_grid               # 0.10.25: neues Log am GPS-Standort
        if not sd.get("my_zone") and meta.get("mycall") and self.cty is not None:
            try:
                lk = self.cty.lookup(meta["mycall"])
                if lk is not None and lk.cq:
                    meta["my_zone"] = str(lk.cq)
            except Exception:  # noqa: BLE001 – dann bleibt die Vorgabe
                pass
        return meta

    def _stick_timezone(self) -> None:
        """Live-Stick (0.10.10): Zeitzone aus dem Locator stellen, wenn die Uhrzeit sonst anders
        wäre. Die eingebaute Uhr des Rechners wird dabei nur gelesen, nie verändert."""
        from .. import livestick, tzfind
        if not livestick.is_live():
            return
        sd = self.cfg.get("station_defaults") or {}
        grid = (self.meta.get("my_grid") if self.db else "") or sd.get("my_grid", "")
        zone = tzfind.suggest(grid, tzfind.current_zone())
        cmd = livestick.timezone_command(zone) if zone else None
        if not cmd:
            return
        applog.message(f"Zeitzone aus Locator {grid}: {zone}")
        from PySide6.QtCore import QProcess
        proc = QProcess(self)

        def done(code: int, _status) -> None:
            err = bytes(proc.readAllStandardError()).decode(errors="replace").strip()
            proc.deleteLater()
            if code == 0:
                import os
                import time as _time
                os.environ["TZ"] = zone            # auch die Ortszeit-Anzeige in GoGoHam sofort
                _time.tzset()
                self.statusBar().showMessage(tr(
                    "Zeitzone auf {zone} gestellt (aus deinem Locator {grid}) – die Uhrzeit "
                    "wurde neu gelesen.", zone=zone, grid=grid), 15000)
            else:
                applog.message(f"Zeitzone stellen fehlgeschlagen ({code}): {err}", "warn")
        proc.finished.connect(done)
        proc.start(cmd[0], cmd[1:])

    def _remember_station(self, meta: dict) -> None:
        """Eigene Angaben für spätere Logs merken (auch wenn ein Contest sie nicht braucht)."""
        sd = dict(self.cfg.get("station_defaults") or {})
        # 0.10.11: Einstellungen → Operator ist maßgeblich – aus dem Log nur ergänzen, was dort
        # noch fehlt (ein /P-Log soll das Heimat-Rufzeichen und den Heimat-Locator nicht ändern)
        for k in STATION_KEYS:
            if meta.get(k) and not sd.get(k):
                sd[k] = meta[k]
        if meta.get("mycall") and not sd.get("mycall"):
            sd["mycall"] = meta["mycall"]
        self.cfg["station_defaults"] = sd
        cfgmod.save(self.cfg)
        self._stick_timezone()                 # 0.10.10: neuer Locator → Zeitzone auf dem Stick

    # ------------------------------------------------------------ Einstellungen
    RIG_KEYS = ("rig_enabled", "rig_profiles", "rig_profile", "rig_model", "rig_device",
                "rig_baud", "rig_extra", "rig_host", "rig_port", "rig_autostart")
    WSJTX_KEYS = ("wsjtx_enabled", "wsjtx_address", "wsjtx_port", "wsjtx_lock_rig")
    LIVE_KEYS = ("livescore_enabled", "livescore_url", "livescore_user", "livescore_password")
    CLUSTER_KEYS = ("cluster_node", "cluster_call")
    CLUSTER_FILTER_KEYS = ("cluster_max_age", "cluster_contest_only", "cluster_spotter_cont",
                           "cluster_dx_cont")

    def open_dev(self) -> None:
        """Strg+Umschalt+E: Fenster „Entwicklung“ (nach Passwort)."""
        from .dev_page import open_dev_window
        open_dev_window(self, self.cfg, cfgmod.save)

    def open_settings(self, start: str = "rig") -> None:
        """Fenster „Einstellungen“ mit Reitern; danach nur neu starten, was sich geändert hat."""
        import copy
        before = copy.deepcopy(self.cfg)
        actions = {"rules": lambda: self.update_rules(manual=True), "cty": self.update_cty,
                   "scp": self.update_scp, "flags": self.download_flags,
                   "map_nasa": lambda: self.start_map_download("nasa"),
                   "map_relief": lambda: self.start_map_download("relief"),
                   "history": self.import_history, "doks": self.update_doks,
                   "speechd": self.install_speechd, "piper": self.download_piper,
                   "all": self.download_all,
                   # Live-Stick (0.10.8)
                   "clock_set": self.clock.set_manually, "stick_poweroff": self.stick_poweroff,
                   "wlan": self.open_wlan,
                   "stick_reset": self.stick_reset, "gps_watch": self.gpsw}
        dlg = SettingsDialog(self.cfg, self, test_fn=self._test_rig, actions=actions, start=start,
                             mycall=self.meta.get("mycall", "") if self.db else "")
        if not dlg.exec():
            if dlg.tested:
                self.start_rig()        # für den Verbindungstest wurde rigctld angehalten
            # Reiter „Sprachaufnahmen“ speichert sofort – auch nach „Abbrechen“ (ab 0.8.12.9)
            self._update_macro_buttons()
            return
        cfgmod.save(self.cfg)
        changed = lambda keys: any(before.get(k) != self.cfg.get(k) for k in keys)
        if changed(self.ANNOUNCE_KEYS):
            self._setup_speech()
        if changed(self.RIG_KEYS) or dlg.tested:
            self._fill_profile_menu()
            self.stop_rig()                 # eigenen rigctld freigeben, bevor ein Dienst startet
            self._sync_rig_services()
            self.start_rig()
        if changed(("station_defaults",)):
            self._stick_timezone()          # Operator-Locator geändert (0.10.11)
        if changed(("rotor",)):
            self._sync_rotor_service()
            self.start_rotor()
        if changed(("gps", "rig_profiles", "rotor")):
            self.gpsw.start()
            self._map_home()
        if changed(self.WSJTX_KEYS):
            self.start_wsjtx()
        if changed(self.CLUSTER_KEYS):
            if self.cluster:
                self.start_cluster()            # neuer Knoten/Rufzeichen – nur wenn Bandmap offen
        elif changed(self.CLUSTER_FILTER_KEYS):
            self.spots.max_age = int(self.cfg.get("cluster_max_age", 30)) * 60
            self.spots.clear()                  # neu füllen mit den neuen Filtern
            if self.cluster:
                self.start_cluster()
        if changed(("macros_ssb", "macros_cw", "voice_source")):
            self._update_macro_buttons()
        if changed(("theme",)):
            self.set_theme(self.cfg["theme"])
        if changed(self.LIVE_KEYS):
            if self.live is not None:
                self.live.stop()
                self.live = None
            self._update_live()
        if changed(("language",)):
            self._ask_restart(language=True)
        elif changed(("font_size",)):
            self._ask_restart(font=True)

    def _sync_rig_services(self) -> None:
        """Hintergrund-rigctld (0.8.17) an die Profile anpassen – nur Geändertes neu starten."""
        from .. import rigservice
        profs = self.cfg.get("rig_profiles") or []
        if not any(p.get("service") for p in profs) and not rigservice.has_units():
            return
        notes: list[str] = []
        errors = rigservice.sync(profs, notes=notes)
        if errors:
            self.statusBar().showMessage(" · ".join(errors), 20000, level="error")
        elif notes:
            self.statusBar().showMessage(" · ".join(notes), 15000)

    def rig_settings(self) -> None:
        self.open_settings("rig")

    # ------------------------------------------------------------ Rotor (0.8.23)
    def start_rotor(self) -> None:
        self.stop_rotor()
        p = rotmod.profile(self.cfg)
        if not p["enabled"] or not p["model"]:
            self.lbl_sb_rotor.hide()
            return
        self.lbl_sb_rotor.show()
        caps = rotmod.rotor_caps(p["model"])
        lo, hi = (caps.min_az, caps.max_az) if caps else (0.0, 360.0)
        host, port = p["host"] or "127.0.0.1", int(p["port"])
        mode = p["mode"] or "self"
        if mode != "external" and not rotmod.port_in_use(host, port):
            if mode == "service":
                errors = rotmod.sync_service(p)
                if errors:
                    self.statusBar().showMessage(" · ".join(errors), 15000, level="error")
            else:
                try:
                    self.rotctld_proc = rotmod.start_rotctld(p)
                except (OSError, FileNotFoundError) as e:
                    self.statusBar().showMessage(tr("rotctld konnte nicht starten: {e}", e=e),
                                                 15000, level="error")
        self.rotor = rotmod.RotorWorker(host, port, lo, hi)
        self.rotor.start()
        self._rotor_tick()

    def stop_rotor(self) -> None:
        if self.rotor is not None:
            self.rotor.stop()
            self.rotor.join(1.5)
            self.rotor = None
        if self.rotctld_proc is not None:
            self.rotctld_proc.terminate()
            try:
                self.rotctld_proc.wait(2)
            except Exception:  # noqa: BLE001
                self.rotctld_proc.kill()
            self.rotctld_proc = None

    def _sync_rotor_service(self) -> None:
        p = rotmod.profile(self.cfg)
        if p["mode"] == "service" or rotmod.has_units():
            self.stop_rotor()                    # eigenen rotctld freigeben, bevor ein Dienst startet
            errors = rotmod.sync_service(p)
            if errors:
                self.statusBar().showMessage(" · ".join(errors), 20000, level="error")

    # ------------------------------------------------- Bandöffnungs-Vorschau (0.8.27)
    def _cont_of(self, call: str) -> str | None:
        if call not in self._cont_cache:
            lk = self.cty.lookup(call) if (self.cty and call) else None
            self._cont_cache[call] = lk.cont if lk else None
            if len(self._cont_cache) > 5000:
                self._cont_cache.clear()
        return self._cont_cache.get(call)

    def _locate_cached(self, call: str):
        if call not in self._loc_cache:
            if len(self._loc_cache) > 5000:
                self._loc_cache.clear()
            self._loc_cache[call] = self._locate(call)
        return self._loc_cache[call]

    def _prop_heard(self) -> dict:
        """Was Cluster (Melder bis 1000 km) und RBN (Baken) gerade hören (0.8.27.1)."""
        from .. import propagation as pr
        now = time.time()
        cells = []
        board = self.beacon_board
        if board is not None:
            for b in bc.BEACONS:
                for band in bc.BEACON_FREQ:
                    cell = board.cell(b.call, band, now)
                    if cell.heard:
                        cells.append((b.call, band, len(cell.heard)))
        spots = list(self.spots.spots.values()) if self.cluster is not None else []
        return pr.heard(spots, cells, self._cont_of, self._locate_cached, self._home_pos(), now)

    def _prop_tick(self, force: bool = False) -> None:
        if self.prop_dock.isHidden():
            return
        now = time.monotonic()
        if not force and now - self._prop_last < 5.0:
            return                                   # alle 5 s reicht (Takt ist 250 ms)
        self._prop_last = now
        from .. import propagation as pr
        v = self.prop_view
        if not self.db:
            v.show_message(tr("Bitte zuerst ein Log anlegen oder öffnen"))
            return
        bands = pr.hf_bands(self.contest.bands) if self.contest else list(pr.DEFAULT_BANDS)
        if not bands:
            v.show_message(tr("Für UKW gibt es keine Vorschau – nur für Kurzwelle (160–10 m)"))
            return
        home = self._home_pos()
        if home is None:
            v.show_message(tr("Eigener Standort unbekannt – bitte Locator im Log eintragen"))
            return
        sw = self._sw
        sfi = sw.sfi if sw is not None else None
        k = sw.k if sw is not None else None
        v.show_estimate(home, bands, sfi, k, self._prop_heard(), force=force)

    def _rotor_tick(self, force: bool = False) -> None:
        r = self.rotor
        st = r.snapshot() if r is not None else None
        self._rotor_views(st, force)
        if r is None:
            return
        if st.notice_id != self._rot_notice:
            self._rot_notice = st.notice_id
            if st.notice:
                self.statusBar().showMessage(st.notice, 10000, level="warn")
        if not st.connected or st.heading is None:
            text = tr("Rotor: getrennt") if st.error else tr("Rotor: verbinde …")
            style = f"color:{RED};" if st.error else ""
        elif st.target is not None:
            text = tr("Rotor: {az}° → {target}°", az=st.heading, target=st.target)
            style = "font-weight:bold;"
        else:
            text = tr("Rotor: {az}°", az=st.heading)
            style = ""
        if text != self.lbl_sb_rotor.text():
            self.lbl_sb_rotor.setText(text)
            self.lbl_sb_rotor.setStyleSheet(style)
        tip = tr("Rotor – klicken: Einstellungen. Alt+R = Short Path, Alt+Shift+R = Long Path, "
                 "Alt+S = Stopp")
        if st.error:
            tip = st.error + "\n" + tip
        self.lbl_sb_rotor.setToolTip(tip)

    def _rotor_views(self, st, force: bool = False) -> None:
        """Rotor-Fenster und Beam auf der Karte auffrischen (nur wenn sichtbar/geändert)."""
        ready = st is not None and st.connected and st.heading is not None
        az = st.heading if ready else None
        target = st.target if ready else None
        c = self.map_view.canvas
        width = rotmod.profile(self.cfg)["beamwidth"]
        if (c.beam_az, c.beam_target, c.beam_width) != (az, target, width):
            c.beam_az, c.beam_target, c.beam_width = az, target, width
            if not self.map_dock.isHidden():
                c.update()
        if self.rot_dock.isHidden() and not force:
            return
        call = (self._map_target[1] or "").split(" · ")[0] if self._map_target[0] else ""
        sig = (None if st is None else (st.connected, st.heading, st.target, st.error), call)
        if sig != self._rot_view_sig or force:
            self._rot_view_sig = sig
            self.rotor_view.show_state(st, call)

    def rotor_turn(self, az: int, why: str = "") -> bool:
        """Rotor auf ``az`` Grad drehen; False = kein Rotor eingerichtet/verbunden."""
        if self.rotor is None:
            self.statusBar().showMessage(tr("Kein Rotor eingerichtet – Datei → Einstellungen → "
                                            "Rotor"), 8000, level="warn")
            return False
        if not self.rotor.snapshot().connected:
            self.statusBar().showMessage(tr("Rotor ist nicht verbunden"), 8000, level="warn")
            return False
        self.rotor.turn(az)
        self.statusBar().showMessage(tr("Rotor dreht auf {az}°", az=int(az) % 360) +
                                     (f" ({why})" if why else ""), 6000)
        self._rotor_tick()
        return True

    def rotor_stop(self) -> None:
        if self.rotor is not None:
            self.rotor.halt_rotor()
            self.statusBar().showMessage(tr("Rotor gestoppt"), 4000)

    def rotor_to_call(self, long_path: bool = False) -> None:
        """Alt+R / Alt+Shift+R: auf die Gegenstation im Eingabefeld drehen."""
        target, label = getattr(self, "_map_target", (None, ""))
        home = self._home_pos() if self.db else None
        az = rotmod.bearing_to(home, target, long_path)
        if az is None:
            self.statusBar().showMessage(
                tr("Keine Richtung bekannt – erst ein Rufzeichen eintippen") if home else
                tr("Eigener Standort fehlt – Locator in den Log-Einstellungen eintragen"),
                6000, level="warn")
            return
        self.rotor_turn(az, ("LP" if long_path else "SP") + (f" {label}" if label else ""))

    def _rotor_auto(self) -> None:
        """Automatisch drehen (Einstellung „beim Tippen“): einmal je Rufzeichen/Richtung."""
        if self.rotor is None or not self.cfg.get("rotor_auto", False):
            return
        target, label = getattr(self, "_map_target", (None, ""))
        az = rotmod.bearing_to(self._home_pos() if self.db else None, target)
        if az is None:
            return
        key = (label, az)
        if key == self._rot_auto_last:
            return
        st = self.rotor.snapshot()
        cur = st.target if st.target is not None else st.heading
        self._rot_auto_last = key
        if cur is not None and min(abs(cur - az), 360 - abs(cur - az)) < 3:
            return                                  # steht schon richtig
        self.rotor_turn(az, tr("automatisch, SP {label}", label=label) if label else "")

    def _add_rotor_actions(self, menu: QMenu, call: str) -> None:
        """Bandmap/Karte: „Rotor drehen: SP 312° / LP 132°“ (0.8.23)."""
        self._add_rotor_actions_pos(menu, self._locate(call), call)

    def _add_rotor_actions_pos(self, menu: QMenu, pos, label: str = "") -> bool:
        if self.rotor is None:
            return False
        home = self._home_pos() if self.db else None
        sp = rotmod.bearing_to(home, pos)
        if sp is None:
            return False
        lp = (sp + 180) % 360
        why = f" {label}" if label else ""
        self._act(menu, tr("Rotor drehen: SP {az}°", az=sp),
                  lambda: self.rotor_turn(sp, f"SP{why}"))
        self._act(menu, tr("Rotor drehen: LP {az}°", az=lp),
                  lambda: self.rotor_turn(lp, f"LP{why}"))
        return True

    def _map_point_menu(self, kind: str, mark, pos, gpos) -> None:
        """Rechtsklick in der Karte auf eine Bake oder eine freie Stelle (0.8.23.1)."""
        m = QMenu(self)
        label = mark["call"] if kind == "beacon" and mark else ""
        self._add_rotor_actions_pos(m, pos, label)
        if m.actions():
            m.exec(gpos)

    def _test_rig(self, prof: dict) -> hamlib.TestResult:
        """Verbindungstest aus dem Funkgerät-Fenster – liest nur, sendet nie."""
        own = self.rigctld_proc is not None and self.rigctld_proc.poll() is None
        if own and int(prof["port"]) == int(self.cfg["rig_port"]):
            # unser eigener rigctld hält Port und Schnittstelle – kurz freigeben
            self.stop_rig()
        return hamlib.test_profile(prof)

    # --------------------------------------------------------- Geräte-Profile
    def _profile_name(self) -> str:
        p = rigprofiles.active(self.cfg)
        return p["name"] if p else ""

    def _fill_profile_menu(self) -> None:
        rigprofiles.ensure_profiles(self.cfg)
        menu = self.menu_profiles
        menu.clear()
        group = QActionGroup(self)
        for i, p in enumerate(self.cfg["rig_profiles"]):
            a = QAction(f"{p.get('slot', i) + 1}: {p['name']}", self)
            a.setCheckable(True)
            a.setChecked(i == self.cfg["rig_profile"])
            a.triggered.connect(lambda _c=False, n=i: self.switch_profile(n))
            group.addAction(a)
            menu.addAction(a)
        menu.addSeparator()
        self._act(menu, tr("Profile einrichten …"), self.rig_settings)

    def switch_profile(self, idx: int) -> None:
        if not 0 <= idx < len(self.cfg["rig_profiles"]):
            return
        if idx == self.cfg["rig_profile"]:
            return
        p = rigprofiles.apply_profile(self.cfg, idx)     # gilt auch beim nächsten Start
        cfgmod.save(self.cfg)
        self._fill_profile_menu()
        self.start_rig()
        msg = tr("Funkgerät-Profil: {p1} (nur für GoGoHam – andere Programme sind "
                 "nicht betroffen)", p1=p['name'])
        if self.rig_foreign:
            msg += (tr(" · Auf Port {p1} lief schon ein rigctld – GoGoHam benutzt ihn "
                       "mit und startet keinen zweiten.", p1=self.cfg['rig_port']))
        self.statusBar().showMessage(msg, 15000)

    def _cat_clicked(self) -> None:
        if len(self.cfg.get("rig_profiles") or []) > 1:
            from PySide6.QtGui import QCursor
            self.menu_profiles.exec(QCursor.pos())
        else:
            self.rig_settings()

    def _check_band_offer(self) -> None:
        """Ein-Band-Contest: einmal fragen, ob das Funkgerät aufs Contest-Band soll.
        Es wird nur die Frequenz umgestellt – gesendet wird nichts."""
        band = getattr(self, "_band_offer", None)
        if not band:
            return
        connected = self._rig_connected()
        if not connected and self.cfg.get("rig_enabled") and self.rig \
                and time.monotonic() < self._band_offer_until:
            return                                  # auf die CAT-Verbindung warten
        self._band_offer = None
        if self.current_band() == band or self.locked_by:
            return
        mode = cabrillo_mode(self.current_mode())
        hz = CONTEST_START_FREQ.get(band, {}).get(mode) or DEFAULT_FREQ.get(band)
        if not connected:
            self._updating = True
            self.cb_band.setCurrentText(band)        # ohne CAT: nur die Anzeige umstellen
            self._updating = False
            self.manual_freq = hz or self.manual_freq
            return
        name = self.contest.name if self.contest else tr("Dieser Contest")
        khz = num(hz // 1000)
        ans = QMessageBox.question(
            self, tr("Contest-Band"),
            tr("{name} läuft nur auf {band_label}.\n\nFunkgerät jetzt auf "
               "{band_label2} stellen ({khz} kHz)?\n\nEs wird nur die Frequenz "
               "umgestellt – gesendet wird nichts.", name=name, band_label=band_label(band), band_label2=band_label(band), khz=khz))
        if ans == QMessageBox.StandardButton.Yes:
            self.rig.submit("set_freq", hz)
            self.statusBar().showMessage(tr("Funkgerät auf {band_label} gestellt", band_label=band_label(band)), 5000)

    def _update_lock(self) -> None:
        """Solange ein FT8-Programm aktiv ist: Funkgerät nur anzeigen, nichts senden."""
        who = None
        if self.wsjtx and self.cfg.get("wsjtx_lock_rig", True):
            who = self.wsjtx.active_program()
        if who == self.locked_by:
            return
        self.locked_by = who
        for w in (self.cb_band, self.cb_mode):
            w.setEnabled(who is None)
        if who:
            if self.autocq_timer.isActive():
                self.toggle_autocq(False)
            self.statusBar().showMessage(tr("{who} ist aktiv – GoGoHam zeigt Band und Frequenz nur an und sendet nichts", who=who), 10000, level="warn")
            if not self._direct_cat_warned:
                self._direct_cat_warned = True
                direct = wsjtx_direct_cat()
                if direct:
                    QTimer.singleShot(300, lambda: self._warn_direct_cat(direct))
        else:
            self.statusBar().showMessage(tr("FT8-Programm beendet – GoGoHam steuert das "
                                         "Funkgerät wieder"), 8000)

    def _warn_direct_cat(self, direct: list[tuple[str, str, str]]) -> None:
        lines = "\n".join(tr("• {name}: „{rig}“ an {p5}", name=Path(f).name, rig=rig, p5=port or '?') for f, rig, port in direct)
        QMessageBox.information(
            self, tr("FT8-Programm und Funkgerät"),
            tr("Dein FT8-Programm spricht das Funkgerät direkt über die "
               "USB-Leitung an:\n\n{lines}\n\nWenn gleichzeitig ein rigctld (oder "
               "GoGoHam) dieselbe Leitung benutzt, kann es Aussetzer geben. "
               "Besser: im FT8-Programm unter Einstellungen → Funkgerät „Hamlib "
               "NET rigctl“ wählen und als Netzwerkserver Rechner:Port des "
               "rigctld eintragen (z. B. {get}:{get2}).\n\nMehr dazu im Handbuch, "
               "Kapitel 3.", lines=lines, get=self.cfg.get('rig_host', '127.0.0.1'), get2=self.cfg.get('rig_port', 4532)))

    def _apply_rig_bands(self) -> None:
        """Bandauswahl nach Gerät: nur Bänder, auf denen es laut Hamlib senden kann."""
        bands = (self.rig_caps.bands() if self.rig_caps else []) or BAND_NAMES
        have = [self.cb_band.itemText(i) for i in range(self.cb_band.count())]
        if have == bands:
            return
        cur = self.cb_band.currentText()
        self._updating = True
        self.cb_band.clear()
        self.cb_band.addItems(bands)
        self.cb_band.setCurrentText(cur if cur in bands else bands[0])
        self._updating = False

    def set_theme(self, mode: str) -> None:
        self.cfg["theme"] = mode
        cfgmod.save(self.cfg)
        theme.apply(mode)
        self._style_sent_field()
        self.reload(keep_entry=True)                # Signalfarben der Logliste neu (Nightshift)
        self._update_esm_buttons()
        self.map_view.canvas.update()               # Kartenfarben hell/dunkel
        self.update_check()

    # ============================================================== Länderdatei
    def _update_cty_label(self) -> None:
        if self.cty:
            v = self.cty.version
            ver = f"{v[6:8]}.{v[4:6]}.{v[:4]}" if len(v) == 8 else "?"
            txt = tr("cty.dat vom {ver}", ver=ver)
        else:
            txt = tr("cty.dat fehlt!")
        scp = getattr(self, "scp", None)
        txt += f" · SCP: {len(scp)} Calls" if scp else tr(" · SCP: keine")
        self.lbl_sb_cty.setText(txt)

    def _start_daily_update(self, wait: float = 10.0) -> None:
        """Tägliches Update im Hintergrund starten; höchstens `wait` Sekunden darauf warten
        (der Ladebildschirm läuft dabei weiter). Was länger dauert, wird später übernommen."""
        now = utc_now().replace(tzinfo=None)
        running = bool(self.contest) and dailymod.contest_running(
            getattr(self.contest, "schedule", None), now)
        self.daily = dailymod.DailyUpdater(running, dailymod.flags_due(self.cfg))
        self.daily.start()
        end = time.monotonic() + wait
        while self.daily.is_alive() and time.monotonic() < end:
            QApplication.processEvents()
            self.daily.join(0.05)
        if not self.daily.is_alive():
            self._finish_daily_update()

    def _finish_daily_update(self) -> None:
        """Ergebnis des täglichen Updates übernehmen (läuft im Fenster-Thread)."""
        d, self.daily = self.daily, None
        res = d.result if d else None
        if res is None:
            return
        if not res.offline:
            self.cfg["daily_update_last"] = utc_now().date().isoformat()
            if d.flags_due:
                self.cfg["flags_last_check"] = utc_now().date().isoformat()
            cfgmod.save(self.cfg)
        if res.rules is not None and getattr(res.rules, "changed", False):
            contestmod.reload()
        if res.cty:
            new = ctymod.CtyDB.load_default()
            if new is not None:
                self.cty = new
                if self.db:
                    self._setup_contest()
                    self.reload()
        if res.scp:
            new = scpmod.ScpDB.load_default()
            if new is not None:
                self.scp = new
        if res.doks:
            from ..contests.rulebased import reload_doks
            reload_doks()
        self._update_cty_label()
        if res.flags and not (self.flag_dl and self.flag_dl.is_alive()):
            self.flag_dl = flagmod.FlagDownloader(res.flags)
            self.flag_dl.start()
        if getattr(res, "map_month", False) and not self.map_dl:
            self.start_map_download("nasa-month")
        self.statusBar().showMessage(res.summary(), 15000)

    def _contest_running_now(self) -> bool:
        now = utc_now().replace(tzinfo=None)
        return bool(self.contest) and dailymod.contest_running(
            getattr(self.contest, "schedule", None), now)

    def _finish_version_check(self) -> None:
        """Ergebnis der Versionsprüfung übernehmen: Hinweis je Version nur einmal,
        nicht während der Contest des geöffneten Logs läuft."""
        vc, self.vcheck = self.vcheck, None
        if vc is None or vc.error:
            return                                   # kein Internet: morgen wieder
        self.cfg["version_check_last"] = utc_now().date().isoformat()
        if vcheckmod.should_show(self.cfg, vc.version) and not self._contest_running_now():
            self.cfg["version_hint_shown"] = vc.version
            self.sb.showMessage(vcheckmod.hint_text(vc.version), 30000, "info")
        cfgmod.save(self.cfg)

    def check_version_now(self) -> None:
        """Hilfe → Nach neuer Version suchen …"""
        from .. import livestick
        stick = livestick.is_live()
        if stick or vcheckmod.install_kind() == "script":
            # Stick (0.10.24) bzw. install.sh (0.10.47): Aktualisieren per Knopf
            if stick:
                from .stick_update import StickUpdateDialog as Dlg
            else:
                from .self_update import SelfUpdateDialog as Dlg
            dlg = Dlg(self)
            dlg.exec()
            if dlg.restart_wanted:
                self.restart_requested = True
                self.close()
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            v, err = vcheckmod.latest(), ""
        except Exception as e:  # noqa: BLE001
            v, err = "", str(e)
        finally:
            QApplication.restoreOverrideCursor()
        if err:
            QMessageBox.warning(self, tr("Neue Version"),
                                tr("GitHub ist nicht erreichbar – bitte später noch einmal "
                                   "versuchen.\n\n{err}", err=err))
        elif vcheckmod.is_newer(v):
            self.cfg["version_hint_shown"] = v
            cfgmod.save(self.cfg)
            QMessageBox.information(self, tr("Neue Version"), vcheckmod.hint_text(v))
        else:
            QMessageBox.information(self, tr("Neue Version"),
                                    tr("Du hast die neueste Version ({v}).", v=__version__))

    def update_rules(self, manual: bool = True) -> rulesupdate.UpdateResult:
        """Contest-Regeln von GitHub holen (nur lesen, keine Daten über dich)."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            res = rulesupdate.check_and_download()
        finally:
            QApplication.restoreOverrideCursor()
        if res.changed:
            contestmod.reload()
        if manual:
            QMessageBox.information(self, tr("Contest-Regeln"), res.summary())
        elif res.changed or res.errors:
            self.statusBar().showMessage(res.summary(), 15000)
        return res

    def _show_rule_problems(self) -> None:
        from ..rulefiles import user_dir
        text = "\n\n".join(f"• {p}" for p in LOAD_RESULT.problems)
        QMessageBox.warning(self, tr("Regel-Dateien"),
                            tr("Beim Laden der Regel-Dateien gab es Probleme:\n\n{text_}\n\nFür "
                               "diese Contests gelten weiter die eingebauten Regeln. Eigene "
                               "Regel-Dateien liegen in:\n{user_dir}", text_=text, user_dir=user_dir()))

    def download_flags(self) -> None:
        if self.flag_dl and self.flag_dl.is_alive():
            return
        codes = flagmod.missing_codes()
        if not codes:
            self.statusBar().showMessage(tr("Alle Flaggen sind schon vorhanden."), 5000)
            return
        self.flag_dl = flagmod.FlagDownloader(codes)
        self.flag_dl.start()

    def _check_flag_download(self) -> None:
        d = self.flag_dl
        if not d:
            return
        if d.is_alive():
            self.statusBar().showMessage(tr("Flaggen werden geladen … {done}/{total}", done=d.done, total=d.total), 1000)
            return
        ok = d.total - len(d.failed)
        msg = tr("Flaggen geladen: {ok} von {total}", ok=ok, total=d.total)
        if d.failed:
            msg += tr(" (fehlend: {calls})",
                      calls=", ".join(d.failed[:8]) + (" …" if len(d.failed) > 8 else ""))
        self.statusBar().showMessage(msg, 15000)
        self.flag_dl = None
        self._pixmaps.clear()
        self.update_check()

    def update_doks(self, manual: bool = True) -> None:
        """DOK-Liste (Ortsverbände von DARC/VFDB, Sonder-DOKs) neu laden."""
        from ..contests.rulebased import reload_doks
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            n_ov, n_s = dokmod.download()
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            if manual:
                QMessageBox.warning(self, tr("Download fehlgeschlagen"),
                                    tr("DOK-Liste: {e}\n\nDie bisherige Liste gilt weiter.", e=e))
            else:
                self.statusBar().showMessage(tr("DOK-Liste: kein Internet – die bisherige Liste "
                                                "gilt weiter"), 8000, level="warn")
            return
        QApplication.restoreOverrideCursor()
        reload_doks()
        msg = (tr("DOK-Liste geladen: {n_ov} Ortsverbände, {n_s} Sonder-DOKs", n_ov=n_ov, n_s=n_s)
               if n_ov else
               tr("Sonder-DOKs geladen ({n_s}); Ortsverbände: eingebaute Liste", n_s=n_s))
        self.statusBar().showMessage(msg, 8000)

    def update_scp(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            path = scpmod.download()
            self.scp = scpmod.ScpDB.from_file(path)
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, tr("Download fehlgeschlagen"),
                                tr("{e}\n\nAlternativ MASTER.SCP von supercheckpartial.com manuell "
                                   "speichern unter:\n{user_scp_path}", e=e, user_scp_path=scpmod.user_scp_path()))
            return
        QApplication.restoreOverrideCursor()
        self._update_cty_label()
        self.statusBar().showMessage(tr("MASTER.SCP geladen ({len} Rufzeichen)", len=len(self.scp)), 8000)

    def update_cty(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            path = ctymod.download()
            self.cty = ctymod.CtyDB.from_file(path)
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, tr("Download fehlgeschlagen"),
                                tr("{e}\n\nAlternativ cty.dat von country-files.com manuell speichern "
                                   "unter:\n{user_cty_path}", e=e, user_cty_path=ctymod.user_cty_path()))
            return
        QApplication.restoreOverrideCursor()
        self._update_cty_label()
        if self.db:
            self._setup_contest()
            self.reload()
        self.statusBar().showMessage(tr("Länderdatei aktualisiert ({len} Gebiete)", len=len(self.cty.entities)),
                                     8000)

    # ================================================================== Hilfe
    def show_keys(self) -> None:
        QMessageBox.information(self, tr("Tastenkürzel"), (
            tr("Enter\tQSO loggen\n"
            "Leertaste\tzwischen Rufzeichen und Austausch springen\n"
            "Tab\tnächstes Feld (auch RST)\n"
            "Esc\tEingabe löschen und Senden stoppen\n"
            "Alt+W\tEingabe löschen\n"
            "Bild auf / Bild ab\tCW-Tempo schneller / langsamer\n"
            "F1–F8\tSSB: Sprachspeicher oder eigene Aufnahmen · CW: Texte\n"
            "Ctrl+R\tAuto-CQ an/aus\n"
            "Ctrl+Tab\tRun / S&P umschalten (für „Enter sendet“)\n"
            "Ctrl+M\tÜbersicht (Multis, Rate)\n"
            "Ctrl+P\tLog prüfen\n"
            "Ctrl+Q\tQTC empfangen (WAE)\n"
            "Ctrl+T\tNachricht an andere Plätze (Stationslog)\n"
            "Alt+B / Alt+Shift+B\tBand hoch / runter\n"
            "Ctrl+D\tletztes QSO löschen\n"
            "Entf (in der Liste)\tmarkiertes QSO löschen\n"
            "Doppelklick\tQSO bearbeiten\n"
            "14025 + Enter\tFrequenz einstellen (kHz ins Rufzeichenfeld)\n"
            "Ctrl+E\tLog exportieren\n"
            "Ctrl+K\tContest-Kalender\n"
            "Alt+R / Alt+Shift+R\tRotor auf Short / Long Path drehen\n"
            "Alt+S\tRotor stoppen") + "\n" + keys_text()))

    def about(self) -> None:
        AboutDialog(self).exec()

    # ============================================================ Übungsmodus (0.8.28)
    def practice_menu(self) -> None:
        if self.practice is not None:
            self.end_practice()
        else:
            self.start_practice()

    def _make_practice_stream(self, mixer, dev_id: str):
        from .practice_mode import Stream
        return Stream(mixer, dev_id)

    def _show_practice_dialog(self, dlg) -> bool:
        return bool(dlg.exec())

    def start_practice(self) -> None:
        """Übung starten: Funkgerät, WSJT-X, Cluster und Live-Score trennen, Übungslog anlegen."""
        from .. import cwsynth
        from .. import practice as pm
        from . import practice_mode as pmode
        if self.practice is not None:
            return
        mycall = (self.meta.get("mycall") or "").strip().upper() if self.db else ""
        if not mycall:
            QMessageBox.information(self, tr("Übungsmodus"), tr(
                "Bitte zuerst ein Log anlegen oder öffnen – der Übungsmodus nimmt dein "
                "Rufzeichen, deinen Locator und deine Angaben (z. B. DOK) aus dem Log."))
            return
        scp = self.scp or scpmod.ScpDB.load_default()
        if not scp or not len(scp):
            QMessageBox.information(self, tr("Übungsmodus"), tr(
                "Der Übungsmodus braucht die Rufzeichen-Liste von Super Check Partial "
                "(MASTER.SCP) – bitte zuerst unter Einstellungen → Daten & Updates laden."))
            return
        contests = {cid: cls for cid, cls in CONTESTS.items()
                    if pm.can_practice(cls, "CW") or pm.can_practice(cls, "SSB")}
        saved = self.cfg.get("practice") or {}
        st = pm.Settings.from_dict(saved)
        if not saved and self.meta.get("contest") in contests:
            st.contest = self.meta["contest"]
        if st.contest not in contests or not pm.can_practice(contests[st.contest], st.mode):
            st.contest = "cqww-ssb" if st.mode == "SSB" else "cqww-cw"
        rig_ok = bool(self.cfg.get("rig_enabled") and self.cfg.get("rig_profiles"))
        dlg = pmode.PracticeDialog(contests, st, mycall, self, rig_ok=rig_ok)
        if not self._show_practice_dialog(dlg):
            return
        st = dlg.settings()
        sp = st.style in ("sp", "mix") and rig_ok
        mix = sp and st.style == "mix"
        if not sp:
            st.style = "run"
        self.cfg["practice"] = dict(st.to_dict(), output=dlg.output_id())
        prev = str(self.db.path)
        history, home, sw = self.history, self._home_pos(), self._sw
        cls = contests[st.contest]
        meta = dict(self.meta, contest=st.contest,
                    rules_json=json.dumps(cls.rules, ensure_ascii=False))
        path = pmode.practice_log_name(st.contest)
        db = LogDB(str(path))
        db.set_meta(meta)
        db.close()
        freq0 = self.current_freq() or 0          # S&P: Band vom Funkgerät
        # trennen: es wird nichts gesendet
        self.toggle_autocq(False)
        self.voice_stop()
        self.stop_rig()
        if self.wsjtx:
            self.wsjtx.stop()
            self.wsjtx = None
        self.open_log(str(path))
        self.cfg["last_log"] = prev
        cfgmod.save(self.cfg)
        if sp:                                   # S&P: Band und Mode kommen vom Funkgerät
            band = band_for_freq(freq0)
            if band in (cls.rules.get("bands") or []):
                st.band = band
        else:
            self.cb_band.setCurrentText(st.band)
            want = "CW" if st.mode == "CW" else ("LSB" if st.band in ("160", "80", "40")
                                                 else "USB")
            if self.cb_mode.findText(want) >= 0:
                self.cb_mode.setCurrentText(want)
        voices = None
        if st.mode == "SSB":
            voices = self._make_practice_voices()
            if not voices.ok:
                voices.close()
                QMessageBox.warning(self, tr("Übungsmodus"), tr(
                    "Für SSB fehlt eine Stimme – bitte im Übungsfenster die natürlichen Stimmen "
                    "laden (oder espeak-ng installieren)."))
                self.open_log(prev)
                self.start_rig()
                self.start_wsjtx()
                return
        try:
            doks = sorted(dokmod.DokDB.load_default().ov)
        except Exception:                                 # noqa: BLE001
            doks = []
        if mix:
            from .. import practice_mix
            engine = practice_mix.MixedPractice(self.contest, st, list(scp.calls), mycall, home,
                                                sw.sfi if sw else None, sw.k if sw else None,
                                                history, doks, voices=voices)
        elif sp:
            from .. import practice_sp
            engine = practice_sp.SPPractice(self.contest, st, list(scp.calls), mycall, home,
                                            sw.sfi if sw else None, sw.k if sw else None,
                                            history, doks, voices=voices)
        else:
            engine = pm.Practice(self.contest, st, list(scp.calls), mycall, home,
                                 sw.sfi if sw else None, sw.k if sw else None, history, doks,
                                 voices=voices)
        mixer = cwsynth.Mixer(pm.noise_db(st), pmode.mix_volume(st.volume),
                              band=(300.0, 2700.0) if st.mode == "SSB" else (300.0, 1000.0))
        stream = self._make_practice_stream(mixer, dlg.output_id())
        problem = "" if engine.pool_size else tr("Für diesen Contest fanden sich keine passenden "
                                                 "Stationen in der Rufzeichen-Liste.")
        if not problem and not stream.start():
            problem = stream.error or tr("Soundkarte lässt sich nicht öffnen")
        if problem:
            if voices is not None:
                voices.close()
            QMessageBox.warning(self, tr("Übungsmodus"), problem)
            self.open_log(prev)
            self.start_rig()
            self.start_wsjtx()
            return
        self.practice = pmode.PracticeController(self, st, engine, mixer, stream, prev, str(path))
        self.spots.clear()
        if sp:
            self._practice_esm = self.cfg.get("esm_mode", "run")
            self.cfg["esm_mode"] = "run" if mix else "sp"
            self._update_esm_buttons()
            self.start_rig(listen=True)          # nur hören: kein PTT, kein CW, kein WinKey
        self.practice.start()
        self._sync_feeds()
        self.act_practice.setText(tr("Übung beenden"))
        self.practice_bar.show()
        self._practice_marks(True)
        self._practice_banner_update(self.practice.remaining())
        self.statusBar().showMessage(
            tr("Gemischte Übung läuft – mit F1 (oder Enter) CQ rufen, zum Suchen am VFO-Knopf "
               "wegdrehen") if mix else
            tr("S&P-Übung läuft – am VFO-Knopf drehen und Stationen anrufen") if sp else
            tr("Übung läuft – mit F1 (oder Enter) CQ rufen"), 10000)
        self.ed_call.setFocus()

    def _make_practice_voices(self):
        from .. import ssbvoice
        return ssbvoice.VoiceBank()

    def _practice_ssb(self, n: int) -> None:
        """SSB-Übung: Taste n – eigene Aufnahmen abspielen oder selbst sprechen (0.8.28.1)."""
        prep = self._practice_ssb_prepare(self._ssb_text(n))
        if prep is not None:
            self._practice_ssb_send(*prep)

    def _practice_ssb_prepare(self, text: str):
        """Bedeutung, Aufnahme (oder None) und Anzeige – mit den Werten von jetzt."""
        from .. import practice as pm
        vals = self._voice_values()
        meaning = pm.ssb_meaning(voicemod.substitute(text, vals, set()), vals["MYCALL"])
        if not meaning:
            return None
        samples, shown = None, meaning
        if self._own_voice():
            p = self._voice_plan(text)
            if p.missing:
                self.sb.showMessage(tr("Aufnahme fehlt: {list} – sprich selbst",
                                       list=voicemod.missing_text(p.missing)), 6000, "warn")
            elif not p.empty:
                samples = voicemod.render(p, self._vcache, self.cfg.get("voice_tone"))
                shown = p.text
        ex = self.contest.sent_exchange(self._serial()) if self.contest else ""
        return meaning, samples, shown, ex

    def _practice_ssb_send(self, meaning: str, samples, shown: str, ex: str) -> None:
        if self.practice is None:
            return
        dur = self.practice.send_ssb(meaning, samples, ex)
        self.cw_ticker.stop(time.monotonic())
        label = "▶ " + shown if samples is not None else tr("Sprich jetzt: {words}", words=shown)
        self.lbl_sending.setText(f'<span style="color:{BLUE}">{html_escape(label)}</span>')
        self._voice_until = time.monotonic() + max(0.5, dur)
        self.sending_timer.start(200)

    def _practice_banner_update(self, remaining: int | None) -> None:
        c = self.practice
        if c is None:
            return
        name = self.contest.name if self.contest else ""
        left = tr("ohne Ende") if remaining is None else \
            tr("noch {m}:{s}", m=remaining // 60, s=f"{remaining % 60:02d}")
        if not getattr(c, "listen", False):
            self.lbl_practice.setText(tr("ÜBUNG – es wird nichts gesendet · {contest} · {band} · "
                                         "{left}", contest=name, band=band_label(c.s.band),
                                         left=left))
            return
        if c.vfo is None:
            where = tr("warte auf das Funkgerät …")
        elif not c.band_ok:
            where = tr("dieses Band gehört nicht zum Contest")
        else:
            where = band_label(c.s.band)
            want = "CW" if c.s.mode == "CW" else "SSB"
            have = "CW" if c.rig_mode.startswith("CW") else ("SSB" if c.rig_mode in (
                "USB", "LSB") else c.rig_mode)
            if have and have != want:
                where += " · " + tr("Funkgerät bitte auf {mode} stellen", mode=want)
        run_rf = getattr(c.engine, "run_rf", -1)
        if run_rf != -1:                                  # gemischte Übung (0.8.30)
            run = tr("Run-Frequenz: CQ rufen, wo du sie haben willst") if run_rf is None else \
                (tr("Run auf {khz} kHz", khz=num(run_rf / 1000, 1)) if c.at_run else
                 tr("S&P · Run-Frequenz {khz} kHz", khz=num(run_rf / 1000, 1)))
            self.lbl_practice.setText(tr("GEMISCHTE ÜBUNG – es wird nichts gesendet · {contest} · "
                                         "{where} · {run} · {left}", contest=name, where=where,
                                         run=run, left=left))
            return
        self.lbl_practice.setText(tr("S&P-ÜBUNG – es wird nichts gesendet · {contest} · {where} · "
                                     "{left}", contest=name, where=where, left=left))

    def _practice_set_esm(self, mode: str) -> None:
        """Gemischte Übung: Run/S&P folgt dem VFO (Einstellung wird am Ende zurückgesetzt)."""
        if self.cfg.get("esm_mode", "run") == mode:
            return
        self.cfg["esm_mode"] = mode
        self._update_esm_buttons()
        self.statusBar().showMessage(tr("Auf deiner Run-Frequenz – Betrieb: Run") if mode == "run"
                                     else tr("Weg von der Run-Frequenz – Betrieb: S&P"), 3000)

    def _practice_spot(self, sim) -> None:
        """Nachgebildeter Spot (S&P-Übung) in die Bandmap."""
        from datetime import datetime, timezone
        self.spots.add(dxc.Spot(call=sim.call, freq=sim.freq, spotter=sim.spotter,
                                comment=sim.comment,
                                utc=datetime.now(timezone.utc).strftime("%H%M")))
        self._refresh_bandmap(force=True)

    def _show_practice_result(self, dlg) -> None:
        dlg.exec()

    def end_practice(self, auto: bool = False) -> None:
        """Übung beenden: Auswertung zeigen, dann wieder das vorige Log, Funkgerät usw."""
        from .. import practice as pm
        from . import practice_mode as pmode
        c = self.practice
        if c is None:
            return
        c.stop()
        self.practice = None
        if getattr(c, "listen", False):
            self.stop_rig()
            self.spots.clear()                   # nachgebildete Spots nicht stehen lassen
            self.cfg["esm_mode"] = getattr(self, "_practice_esm", "run")
            self._update_esm_buttons()
            self._refresh_bandmap(force=True)
        self.cw_ticker.stop(time.monotonic())
        self._update_sending()
        res = c.engine.evaluate(list(self.qsos), c.now)
        hist = pm.save_result(c.s, res)
        self.last_practice_result = res
        name = self.contest.name if self.contest else c.s.contest
        self.practice_bar.hide()
        self._practice_marks(False)
        self.act_practice.setText(tr("Übungsmodus …"))
        self._show_practice_result(pmode.ResultDialog(res, c.s, name, hist, self))
        if c.prev_log and Path(c.prev_log).exists():
            self.open_log(c.prev_log)
        self.start_rig()
        self.start_wsjtx()
        self._sync_feeds()

    # ============================================================ Ansagen (0.8.26)
    ANNOUNCE_KEYS = ("announce_enabled", "announce_backend", "announce_rate",
                     "announce_spelling", "announce_events")

    def _setup_speech(self) -> None:
        """Sprachausgabe nach den Einstellungen (neu) anlegen – nur wenn Ansagen an sind."""
        if self.announcer.speaker is not None:
            self.announcer.speaker.close()               # auch ein laufendes Piper beenden
        sp = None
        if self.cfg.get("announce_enabled"):
            sp = speech.Speaker(speech.choose(self.cfg.get("announce_backend", "auto")),
                                self.cfg.get("announce_rate", "normal"))
            if not sp.ok:
                self.sb.showMessage(tr("Ansagen: keine Sprachausgabe gefunden – bitte "
                                       "espeak-ng oder speech-dispatcher installieren"), 15000,
                                    "warn")
            elif self.cfg.get("announce_backend", "auto") in ("auto", "piper") \
                    and sp.backend != "piper" and speech.piper_ok():
                self.sb.showMessage(tr("Ansagen: Piper ließ sich nicht starten – benutzt wird "
                                       "{name}", name=speech.backend_name(sp.backend)), 15000,
                                    "warn")
        self.announcer.speaker = sp

    def install_speechd(self, done=None) -> None:
        """speech-dispatcher (+ espeak-ng) per Klick installieren und gleich benutzen (0.8.26.1).
        ``done(ok)`` meldet das Ergebnis an den Knopf, der es ausgelöst hat."""
        from PySide6.QtCore import QProcess
        from .. import applog
        if getattr(self, "_speechd_proc", None) is not None:
            return                                   # läuft schon
        cmd = speech.install_command()
        if cmd is None:
            QMessageBox.information(self, tr("speech-dispatcher installieren"), tr(
                "GoGoHam kann speech-dispatcher hier nicht selbst installieren (keine bekannte "
                "Paketverwaltung oder kein pkexec). Bitte im Terminal den passenden Befehl "
                "eingeben:") + "\n\n" + speech.manual_commands())
            if done:
                done(False)
            return
        applog.message("speech-dispatcher installieren: " + cmd[-1])
        self.sb.showMessage(tr("Installiere speech-dispatcher … (Linux fragt nach dem Passwort)"), 0)
        proc = self._speechd_proc = QProcess(self)

        def finished(code: int, _status=None) -> None:
            if self._speechd_proc is None:
                return
            err = bytes(proc.readAllStandardError()).decode(errors="replace").strip()
            proc.deleteLater()
            self._speechd_proc = None
            ok = code == 0 and speech.speechd_ok()
            if ok:
                self._setup_speech()
                used = self.announcer.speaker.backend if self.announcer.speaker else None
                msg = tr("speech-dispatcher ist installiert.")
                if self.cfg.get("announce_enabled") and used == "speechd":
                    msg += " " + tr("Die Ansagen benutzen es ab jetzt.")
                self.sb.showMessage(msg, 15000)
            elif code in (126, 127):
                self.sb.showMessage(tr("Abgebrochen – kein Passwort eingegeben."), 15000, "warn")
            else:
                applog.message(f"speech-dispatcher: Installation fehlgeschlagen ({code}): "
                               f"{err[-500:]}", "warn")
                self.sb.showMessage(tr("speech-dispatcher ließ sich nicht installieren: {e}",
                                       e=(err.splitlines() or [str(code)])[-1]), 20000, "warn")
            if done:
                done(ok)

        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda _e: finished(-1))
        proc.start(cmd[0], cmd[1:])

    def download_all(self, voices: bool, report, finished) -> bool:
        """Alles herunterladen (0.8.28.3) – False, wenn es schon läuft."""
        from .download_all import DownloadAll
        if getattr(self, "_dl_all", None) is not None and self._dl_all.running:
            return False
        self._dl_all = DownloadAll(self, voices, report, finished)
        self._dl_all.start()
        return True

    def download_piper(self, done=None) -> None:
        """Piper + Stimmen laden (0.8.26.2); Fortschritt in der Hinweiszeile, danach sofort
        benutzen. ``done(ok)`` meldet das Ergebnis an den auslösenden Knopf."""
        from .. import piper
        d = getattr(self, "piper_dl", None)
        if d is not None and d.is_alive():
            self.sb.showMessage(tr("Piper wird gerade schon geladen."), 5000)
            return
        self.piper_dl = piper.PiperDownloader()
        self._piper_done = done
        self.piper_dl.start()
        self._check_piper_download()

    def _check_piper_download(self) -> None:
        d = getattr(self, "piper_dl", None)
        if d is None:
            return
        if d.is_alive():
            text = tr("Lade natürliche Stimme: {phase} … {p} %", phase=d.phase or "Piper",
                      p=d.percent)
            if self.sb.currentMessage() != text:
                self.sb.showMessage(text, 0)
            return
        self.piper_dl = None
        done, self._piper_done = getattr(self, "_piper_done", None), None
        ok = not d.error and speech.piper_ok()
        if d.error:
            self.sb.showMessage(tr("Piper konnte nicht geladen werden: {e}", e=d.error), 20000,
                                "error")
        elif not ok:
            self.sb.showMessage(tr("Piper ist geladen, aber es fehlt ein Abspielprogramm "
                                   "(pw-play, paplay oder aplay)."), 20000, "warn")
        else:
            self._setup_speech()
            sp = self.announcer.speaker
            msg = tr("Natürliche Stimme (Piper) ist geladen.")
            if self.cfg.get("announce_enabled") and sp is not None and sp.backend == "piper":
                msg += " " + tr("Die Ansagen benutzen sie ab jetzt.")
            self.sb.showMessage(msg, 15000)
        if done:
            try:
                done(ok)
            except RuntimeError:                         # Einstellungsfenster schon zu
                pass

    def _announce_pending(self) -> None:
        p = self._ann_pending
        if p and p[0] == self.ed_call.text().strip().upper():
            self.announcer.call_status(*p)

    def _say_key(self, text: str) -> None:
        if not self.cfg.get("announce_enabled"):
            self.sb.showMessage(tr("Ansagen sind aus – einschalten unter Einstellungen → "
                                   "Ton & Ansagen"), 6000)
            return
        self.announcer.say(text)

    def say_freq(self) -> None:
        f = self.current_freq() if self._rig_connected() else (self.manual_freq or 0)
        band = self.cb_band.currentText()
        text = speech.freq_words(f, self.current_mode()) if f else \
            f"{speech.band_words(band)}, {speech.mode_words(self.current_mode())}"
        self._say_key(text)

    def say_call(self) -> None:
        call = self.ed_call.text().strip().upper()
        if not call:
            self._say_key(tr("Rufzeichenfeld leer"))
            return
        parts = [speech.spell_call(call, self.announcer.phonetic)]
        if self.scorer and self.contest and len(call) >= 2 and not call.isdigit():
            ev = self.scorer.evaluate(self._draft())
            if ev.dupe:
                parts.append(tr("Dupe auf {band}", band=speech.band_words(self.cb_band.currentText())))
            elif not ev.valid:
                parts.append(tr("Zählt nicht: {warning}", warning=ev.warning))
            else:
                if ev.new_mults:
                    parts.append(tr("Neuer Multi"))
                parts.append(tr("{points} Punkte", points=ev.points))
        exch = self.ed_exch.text().strip()
        if exch:
            parts.append(tr("Austausch {exch}", exch=speech.spell_call(exch)
                            if not exch.isdigit() else exch))
        self._say_key(", ".join(parts))

    def say_last_qso(self) -> None:
        if not self.qsos:
            self._say_key(tr("Noch kein QSO im Log"))
            return
        q = self.qsos[-1]
        self._say_key(tr("Letztes QSO: {call}, {band}, {mode}, Austausch {exch}, {utc} UTC",
                         call=speech.spell_call(q.call, self.announcer.phonetic),
                         band=speech.band_words(q.band), mode=speech.mode_words(q.mode),
                         exch=q.exch_r or "-", utc=q.time[11:16]))

    def say_score(self) -> None:
        if not self.scorer:
            self._say_key(tr("Kein Log offen"))
            return
        self._say_key(tr("{score} Punkte, {n} QSOs", score=self.scorer.score, n=len(self.qsos)))

    def say_time(self) -> None:
        now = utc_now().replace(tzinfo=None)
        parts = [tr("{h} Uhr {m} UTC", h=now.hour, m=f"{now.minute:02d}")]
        c = self.contest
        if c and c.schedule:
            s, e = schedule.next_period(c.schedule, now)
            left = (s - now) if now < s else (e - now)
            mins = int(left.total_seconds()) // 60
            d, rest = divmod(mins, 24 * 60)
            h, m = divmod(rest, 60)
            span = (tr("{d} Tage ", d=d) if d else "") + tr("{h} Stunden {m} Minuten", h=h, m=m)
            parts.append(tr("Contest beginnt in {span}", span=span) if now < s
                         else tr("Contest läuft noch {span}", span=span))
        self._say_key(", ".join(parts))

    def say_again(self) -> None:
        text = self.announcer.last_text or self.sb.currentMessage() or self.sb.notes()
        self._say_key(text or tr("Keine Meldung"))

    def _my_call(self) -> str:
        return (self.meta.get("mycall") or self.cfg.get("cluster_call") or "").upper()

    def contact(self) -> None:
        from .feedback import open_contact
        open_contact(self, self._my_call())

    def bug_report(self) -> None:
        from .feedback import BugReportDialog
        BugReportDialog(self.cfg, self._my_call(), self).exec()


def cat_text(real_model: int, profile_model: int, profile_name: str,
             locked_by: str | None) -> tuple[str, str]:
    """Text und Farbe der CAT-Anzeige: zeigt das Gerät, das wirklich antwortet."""
    r = hamlib.find_model(real_model) if real_model else None
    real = r.name if r else (f"Hamlib {real_model}" if real_model else profile_name)
    if real_model and profile_model and real_model != profile_model:
        return (tr("CAT: verbunden · {real} – Profil ist „{profile_name}“!", real=real, profile_name=profile_name),
                f"color:{ORANGE}; font-weight:bold;")
    if locked_by:
        return (tr("CAT: {real} · gesteuert von {locked_by} – nur Anzeige", real=real, locked_by=locked_by),
                f"color:{BLUE}; font-weight:bold;")
    return tr("CAT: verbunden · {real}", real=real), f"color:{GREEN}; font-weight:bold;"
