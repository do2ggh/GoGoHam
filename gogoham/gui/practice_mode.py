"""Übungsmodus (ab 0.8.28): Einstellungsfenster, Tonausgabe, Ablauf und Auswertung.

Grundsatz: Es wird nie gesendet. Beim Start trennt GoGoHam Funkgerät, WSJT-X, DX-Cluster/RBN
und Live-Score; das Übungslog liegt getrennt in ~/GoGoHam/Übung/. Danach ist alles wie vorher.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel,
                               QPushButton, QSlider, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from .. import cwsynth, practice as pm, propagation as pr, ssbvoice
from ..bands import band_label
from ..i18n import tr

RED = "#c62828"


# ------------------------------------------------------------------ Tonausgabe


def looks_like_rig(desc: str) -> bool:
    from . import audio
    return any(h.lower() in (desc or "").lower() for h in audio.RIG_CODEC_HINTS)


class Stream:
    """Schiebt den Tonstrom des Mixers laufend in die Soundkarte (etwa 0,15 s Vorlauf)."""

    AHEAD_S = 0.15

    def __init__(self, mixer: cwsynth.Mixer, dev_id: str = ""):
        self.mixer = mixer
        self.dev_id = dev_id
        self.error = ""
        self._sink = self._io = self._timer = None
        self._t0 = 0.0

    def start(self) -> bool:
        from . import audio
        msg = audio.available()
        if msg:
            self.error = msg
            return False
        from PySide6.QtMultimedia import QAudioSink, QMediaDevices
        dev = audio.find("out", self.dev_id) if self.dev_id else None
        if dev is None:
            dev = QMediaDevices.defaultAudioOutput()
        if dev is None or dev.isNull():
            self.error = tr("Keine Soundkarte für die Wiedergabe gefunden")
            return False
        self._fmt = audio._format(dev, 2)
        self._sink = QAudioSink(dev, self._fmt)
        self._sink.setBufferSize(int(self._fmt.bytesForDuration(int(self.AHEAD_S * 2e6))))
        self._io = self._sink.start()
        if self._io is None:
            self.error = tr("Soundkarte lässt sich nicht öffnen")
            self._sink = None
            return False
        self._t0 = time.monotonic()
        self._timer = QTimer()
        self._timer.timeout.connect(self.feed)
        self._timer.start(15)
        self.feed()
        return True

    def feed(self) -> None:
        if self._sink is None:
            return
        from . import audio
        # höchstens AHEAD_S vor der Uhr – so bleibt die Reaktion auf Tasten flott
        target = time.monotonic() - self._t0 + self.AHEAD_S
        need = int((target - self.mixer.now) * self.mixer.rate)
        free_frames = self._sink.bytesFree() // max(1, self._fmt.bytesPerFrame())
        n = min(need, int(free_frames * self.mixer.rate / max(1, self._fmt.sampleRate())))
        if n <= 0:
            return
        self._io.write(audio._encode(self.mixer.render(n), self._fmt))

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if self._sink is not None:
            self._sink.stop()
            self._sink = None


class SilentStream:
    """Ohne Soundkarte (Tests): der Strom läuft mit der Uhr, gehört wird nichts."""

    def __init__(self, mixer: cwsynth.Mixer, dev_id: str = ""):
        self.mixer, self.error, self._t0 = mixer, "", 0.0
        self._timer = None

    def start(self) -> bool:
        self._t0 = time.monotonic()
        self._timer = QTimer()
        self._timer.timeout.connect(self.feed)
        self._timer.start(15)
        return True

    def feed(self) -> None:
        need = int((time.monotonic() - self._t0 + 0.15 - self.mixer.now) * self.mixer.rate)
        if need > 0:
            self.mixer.render(need)

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None


# ------------------------------------------------------------------ Einstellungen
def level_names() -> dict[int, str]:
    return {0: tr("aus"), 1: tr("leicht"), 2: tr("mittel"), 3: tr("stark")}


def activity_names() -> dict[int, str]:
    return {1: tr("ruhig"), 2: tr("mäßig"), 3: tr("lebhaft"), 4: tr("viel los"), 5: tr("Pile-up")}


class PracticeDialog(QDialog):
    def __init__(self, contests: dict, settings: pm.Settings, mycall: str, parent=None,
                 rig_ok: bool = False):
        super().__init__(parent)
        self.rig_ok = rig_ok                 # S&P braucht ein eingerichtetes Funkgerät
        self.setWindowTitle(tr("Übungsmodus"))
        self.setMinimumWidth(640)
        self.contests = contests
        lay = QVBoxLayout(self)
        self._dl = None
        self._dl_timer = QTimer(self)
        self._dl_timer.timeout.connect(self._dl_poll)
        head = QLabel(tr("<b>Contest üben – es wird nichts gesendet.</b> Erfundene Stationen rufen "
                         "dich über die Soundkarte an; du arbeitest sie wie im echten Contest mit "
                         "F1–F8 oder Enter. Funkgerät, FT8-Programm, DX-Cluster und Live-Score sind "
                         "währenddessen getrennt. Dein Rufzeichen: {call}", call=mycall))
        head.setWordWrap(True)
        lay.addWidget(head)
        f = QFormLayout()
        self.cb_style = QComboBox()
        self.cb_style.addItem(tr("Run – du rufst CQ, die Stationen rufen dich"), "run")
        self.cb_style.addItem(tr("S&P – du suchst am VFO-Knopf und rufst an"), "sp")
        self.cb_style.addItem(tr("Gemischt – Run auf deiner Frequenz, zwischendurch S&P am "
                                 "VFO-Knopf"), "mix")
        if not rig_ok:
            for i in (1, 2):
                self.cb_style.model().item(i).setEnabled(False)
                self.cb_style.setItemData(i, tr("Funkgerät nötig – gedreht wird am VFO-Knopf"),
                                          Qt.ItemDataRole.ToolTipRole)
        want = settings.style if settings.style in ("sp", "mix") and rig_ok else "run"
        self.cb_style.setCurrentIndex(max(0, self.cb_style.findData(want)))
        f.addRow(tr("Übung:"), self.cb_style)
        self.lbl_sp = QLabel("")
        self.lbl_sp.setWordWrap(True)
        f.addRow("", self.lbl_sp)
        self.cb_mode = QComboBox()
        self.cb_mode.addItem("CW", "CW")
        self.cb_mode.addItem("SSB", "SSB")
        self.cb_mode.setCurrentIndex(max(0, self.cb_mode.findData(settings.mode)))
        f.addRow(tr("Betriebsart:"), self.cb_mode)
        self.cb_contest = QComboBox()
        f.addRow(tr("Contest:"), self.cb_contest)
        self._fill_contests(settings.contest)
        self.cb_band = QComboBox()
        f.addRow(tr("Band:"), self.cb_band)
        self.cb_contest.currentIndexChanged.connect(lambda _i: self._fill_bands(settings.band))
        self._fill_bands(settings.band)
        # SSB: Stimmen der Gegenstationen
        self.lbl_voice = QLabel("")
        self.lbl_voice.setWordWrap(True)
        self.btn_voice = QPushButton(tr("Natürliche Stimmen laden (ca. {mb} MB)",
                                        mb=self._dl_mb()))
        self.btn_voice.clicked.connect(self._download)
        self.voice_box = QGroupBox(tr("Stimmen der Gegenstationen (SSB)"))
        vrow = QVBoxLayout(self.voice_box)
        vrow.addWidget(self.lbl_voice)
        vrow.addWidget(self.btn_voice, 0, Qt.AlignmentFlag.AlignLeft)
        self.cb_mode.currentIndexChanged.connect(self._mode_changed)
        self.cb_minutes = QComboBox()
        for m in (10, 30, 60, 0):
            self.cb_minutes.addItem(tr("ohne Ende") if m == 0 else tr("{m} Minuten", m=m), m)
        self.cb_minutes.setCurrentIndex(max(0, self.cb_minutes.findData(settings.minutes)))
        f.addRow(tr("Dauer:"), self.cb_minutes)
        row = QHBoxLayout()
        self.sp_min, self.sp_max = QSpinBox(), QSpinBox()
        for sp, v in ((self.sp_min, settings.wpm_min), (self.sp_max, settings.wpm_max)):
            sp.setRange(10, 50)
            sp.setValue(v)
            sp.setSuffix(" WpM")
        row.addWidget(self.sp_min)
        row.addWidget(QLabel(tr("bis")))
        row.addWidget(self.sp_max)
        row.addStretch(1)
        f.addRow(tr("Tempo der Stationen:"), row)
        row = QHBoxLayout()
        self.sp_my = QSpinBox()
        self.sp_my.setRange(10, 50)
        self.sp_my.setValue(settings.my_wpm)
        self.sp_my.setSuffix(" WpM")
        self.sp_pitch = QSpinBox()
        self.sp_pitch.setRange(300, 1000)
        self.sp_pitch.setSingleStep(50)
        self.sp_pitch.setValue(settings.my_pitch)
        self.sp_pitch.setSuffix(" Hz")
        row.addWidget(self.sp_my)
        row.addWidget(QLabel(tr("Tonhöhe")))
        row.addWidget(self.sp_pitch)
        row.addStretch(1)
        f.addRow(tr("Dein Tempo:"), row)
        self.cb_act = QComboBox()
        for k, v in activity_names().items():
            self.cb_act.addItem(v, k)
        self.cb_act.setCurrentIndex(max(0, self.cb_act.findData(settings.activity)))
        f.addRow(tr("Betrieb:"), self.cb_act)
        self.cb_noise, self.cb_qsb = QComboBox(), QComboBox()
        for cb, v in ((self.cb_noise, settings.noise), (self.cb_qsb, settings.qsb)):
            for k, name in level_names().items():
                cb.addItem(name, k)
            cb.setCurrentIndex(max(0, cb.findData(v)))
        f.addRow(tr("Rauschen:"), self.cb_noise)
        f.addRow(tr("Schwund (QSB):"), self.cb_qsb)
        self.ck_qrm = QCheckBox(tr("Störer (andere Stationen in der Nähe)"))
        self.ck_qrm.setChecked(settings.qrm)
        self.ck_dbl = QCheckBox(tr("Doppelanrufe (Stationen rufen dazwischen oder noch einmal)"))
        self.ck_dbl.setChecked(settings.doubles)
        self.ck_cut = QCheckBox(tr("Abgekürzte Zahlen (T = 0, N = 9)"))
        self.ck_cut.setChecked(settings.cut_numbers)
        self.ck_spots = QCheckBox(tr("Spots in der Bandmap (nachgebildeter DX-Cluster)"))
        self.ck_spots.setChecked(settings.spots)
        self.ck_steal = QCheckBox(tr("Frequenz wird übernommen, wenn du länger als 1–2 Minuten "
                                     "weg bist"))
        self.ck_steal.setChecked(settings.steal)
        for ck in (self.ck_qrm, self.ck_dbl, self.ck_cut, self.ck_spots, self.ck_steal):
            f.addRow("", ck)
        self.sl_vol = QSlider(Qt.Orientation.Horizontal)
        self.sl_vol.setRange(5, 100)
        self.sl_vol.setValue(settings.volume)
        f.addRow(tr("Lautstärke:"), self.sl_vol)
        self.cb_out = QComboBox()
        self.cb_out.addItem(tr("Standard des Systems"), "")
        try:
            from . import audio
            for dev_id, desc in audio.outputs():
                self.cb_out.addItem(desc, dev_id)
        except Exception:                               # noqa: BLE001
            pass
        self.cb_out.setCurrentIndex(max(0, self.cb_out.findData(settings_out(parent))))
        self.lbl_out = QLabel("")
        self.lbl_out.setWordWrap(True)
        self.lbl_out.setStyleSheet(f"color:{RED};")
        self.cb_out.currentIndexChanged.connect(self._check_out)
        f.addRow(tr("Wiedergabe über:"), self.cb_out)
        f.addRow("", self.lbl_out)
        lay.addLayout(f)
        lay.addWidget(self.voice_box)
        bb = QDialogButtonBox()
        self.btn_start = bb.addButton(tr("Übung starten"), QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(tr("Abbrechen"), QDialogButtonBox.ButtonRole.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._check_out()
        self.cb_style.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()

    @property
    def style(self) -> str:
        return self.cb_style.currentData() or "run"

    @property
    def mode(self) -> str:
        return self.cb_mode.currentData() or "CW"

    def _fill_contests(self, want: str) -> None:
        mode = self.mode
        cur = self.cb_contest.currentData() or want
        # gleicher Contest in der anderen Betriebsart: cqww-cw ↔ cqww-ssb
        swap = {"CW": ("-ssb", "-cw"), "SSB": ("-cw", "-ssb")}[mode]
        alt = cur[: -len(swap[0])] + swap[1] if cur and cur.endswith(swap[0]) else cur
        self.cb_contest.blockSignals(True)
        self.cb_contest.clear()
        for cid, cls in sorted(self.contests.items(), key=lambda kv: kv[1].name.lower()):
            if pm.can_practice(cls, mode):
                self.cb_contest.addItem(cls.name, cid)
        i = self.cb_contest.findData(alt)
        if i < 0:
            i = self.cb_contest.findData(cur)
        self.cb_contest.setCurrentIndex(max(0, i))
        self.cb_contest.blockSignals(False)

    def _mode_changed(self, _i: int = 0) -> None:
        self._fill_contests(self.cb_contest.currentData() or "")
        if hasattr(self, "cb_band"):
            self._fill_bands(self.cb_band.currentData() or "20")
        ssb = self.mode == "SSB"
        for wdg in (self.sp_min, self.sp_max, self.sp_my, self.sp_pitch, self.ck_cut):
            wdg.setEnabled(not ssb)
        sp = self.style in ("sp", "mix")
        self.cb_band.setEnabled(not sp)
        self.ck_spots.setVisible(sp)
        self.ck_qrm.setVisible(not sp)
        self.ck_steal.setVisible(self.style == "mix")
        mix = tr("Deine Run-Frequenz ist dort, wo du CQ rufst (CW ± 150 Hz, SSB ± 400 Hz). "
                 "Drehst du weg, bist du im S&P – „Enter sendet“ schaltet dabei von selbst "
                 "zwischen Run und S&P um (Strg+Tab geht trotzdem). ") \
            if self.style == "mix" else ""
        self.lbl_sp.setText(mix + tr(
            "Gedreht wird am VFO-Knopf deines Funkgeräts – GoGoHam liest nur die Frequenz, "
            "Senden ist gesperrt. Das Band nimmt GoGoHam vom Funkgerät. Den Ton hörst du über "
            "die Soundkarte des PCs: bitte den Lautsprecher am Funkgerät leise drehen.") if sp
            else (tr("S&P geht nur mit eingerichtetem Funkgerät (Einstellungen → Funkgerät).")
                  if not self.rig_ok else ""))
        self.voice_box.setVisible(ssb)
        self._voice_status()
        self.adjustSize()

    @staticmethod
    def _dl_mb() -> int:
        from .. import piper
        return max(1, round(piper.missing_size("practice") / 1e6))

    def _voice_status(self) -> None:
        from .. import piper
        ssb = self.mode == "SSB"
        kind = ssbvoice.backend()
        busy = self._dl is not None
        if kind == "piper":
            text = tr("Natürliche englische Stimmen (Piper, {credit}) – jede Station klingt "
                      "anders.", credit=piper.PRACTICE_CREDIT)
        elif kind == "espeak":
            text = tr("Zurzeit Computerstimmen (espeak-ng). Natürlicher klingen die Stimmen von "
                      "Piper – einmal laden, danach ohne Internet.")
        else:
            text = tr("Für SSB fehlt eine Stimme: bitte die natürlichen Stimmen laden (oder "
                      "espeak-ng installieren).")
        text += " " + tr("Hast du eigene Sprachaufnahmen (Einstellungen → Ton & Ansagen → Sprachaufnahmen), "
                         "spielt GoGoHam sie ab; sonst sprichst du selbst – ins Leere, es wird "
                         "nichts gesendet – und drückst dazu die Taste.")
        self.lbl_voice.setText(text)
        self.btn_voice.setVisible(ssb and kind != "piper" and piper.supported())
        self.btn_voice.setEnabled(not busy)
        self.btn_start.setEnabled(not busy and (not ssb or bool(kind)))

    def _download(self) -> None:
        from .. import piper
        self._dl = piper.PiperDownloader(what="practice")
        self._dl.start()
        self._dl_timer.start(300)
        self._voice_status()

    def _dl_poll(self) -> None:
        d = self._dl
        if d is None:
            return
        if d.is_alive():
            self.btn_voice.setText(tr("Lade natürliche Stimmen: {phase} … {p} %",
                                      phase=d.phase or "Piper", p=d.percent))
            return
        self._dl_timer.stop()
        self._dl = None
        self.btn_voice.setText(tr("Natürliche Stimmen laden (ca. {mb} MB)", mb=self._dl_mb()))
        if d.error:
            self.lbl_voice.setText(tr("Laden fehlgeschlagen: {e}", e=d.error))
            self.btn_voice.setEnabled(True)
            return
        self._voice_status()

    def _fill_bands(self, want: str) -> None:
        cls = self.contests.get(self.cb_contest.currentData())
        bands = pr.hf_bands((cls.rules if cls else {}).get("bands") or [])
        cur = self.cb_band.currentData() or want
        self.cb_band.clear()
        for b in bands:
            self.cb_band.addItem(band_label(b), b)
        i = self.cb_band.findData(cur)
        self.cb_band.setCurrentIndex(i if i >= 0 else (bands.index("20") if "20" in bands else 0))

    def _check_out(self, _i: int = 0) -> None:
        rig = looks_like_rig(self.cb_out.currentText())
        self.lbl_out.setText(tr("Achtung: Das sieht nach der Soundkarte des Funkgeräts aus. Bei "
                                "eingeschaltetem VOX könnte das Funkgerät senden – bitte "
                                "Kopfhörer oder Lautsprecher des PCs wählen.") if rig else "")

    def settings(self) -> pm.Settings:
        lo, hi = sorted((self.sp_min.value(), self.sp_max.value()))
        return pm.Settings(contest=self.cb_contest.currentData(), band=self.cb_band.currentData(),
                           mode=self.mode, minutes=int(self.cb_minutes.currentData()),
                           wpm_min=lo, wpm_max=hi, activity=int(self.cb_act.currentData()),
                           noise=int(self.cb_noise.currentData()),
                           qsb=int(self.cb_qsb.currentData()), qrm=self.ck_qrm.isChecked(),
                           doubles=self.ck_dbl.isChecked(), cut_numbers=self.ck_cut.isChecked(),
                           my_wpm=self.sp_my.value(), my_pitch=self.sp_pitch.value(),
                           volume=self.sl_vol.value(), style=self.style,
                           spots=self.ck_spots.isChecked(), steal=self.ck_steal.isChecked())

    def output_id(self) -> str:
        return self.cb_out.currentData() or ""


def settings_out(win) -> str:
    cfg = getattr(win, "cfg", None) or {}
    return (cfg.get("practice") or {}).get("output", "")


# ------------------------------------------------------------------ Auswertung
def finding_text(f: pm.Finding) -> tuple[str, str]:
    if f.kind == "call":
        return tr("Rufzeichen falsch"), tr("{logged} geloggt – richtig war {right}",
                                            logged=f.logged, right=f.right)
    if f.kind == "exch":
        return tr("Austausch falsch"), tr("{call}: „{logged}“ geloggt – gesendet wurde „{right}“",
                                           call=f.call, logged=f.logged, right=f.right)
    if f.kind == "theirs":
        return tr("Falsch geloggt worden"), tr(
            "{call} hat dich als {logged} geloggt – das Rufzeichen hättest du berichtigen "
            "müssen", call=f.call, logged=f.logged)
    if f.kind == "dupe":
        return tr("Doppel-QSO"), tr("{call} war schon im Log – unnötig noch einmal gearbeitet",
                                    call=f.call)
    if f.kind == "nil":
        return tr("Nicht im Log der Gegenstation"), tr(
            "{logged} – mit dieser Station kam kein QSO zustande", logged=f.logged)
    return tr("Nicht geloggt"), tr("{call} hat den Austausch gesendet, steht aber nicht in "
                                   "deinem Log", call=f.call)


class ResultDialog(QDialog):
    def __init__(self, res: pm.Result, settings: pm.Settings, contest_name: str,
                 history: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Übung – Auswertung"))
        self.resize(640, 480)
        lay = QVBoxLayout(self)
        mins = res.seconds / 60
        lay.addWidget(QLabel(tr(
            "<b>{contest}, {band}</b> · {m} Minuten · <b>{n} QSOs</b>, davon {ok} fehlerfrei · "
            "Rate {rate} QSOs/Stunde · {err} Fehler", contest=contest_name,
            band=band_label(settings.band), m=f"{mins:.0f}", n=res.qsos, ok=res.correct,
            rate=res.rate, err=res.errors)))
        if res.parts:
            run, sp = res.parts["run"], res.parts["sp"]
            lb = QLabel(tr(
                "Run: {n} QSOs in {m} min, Rate {rate}, {err} Fehler · S&P: {n2} QSOs in {m2} min, "
                "Rate {rate2}, {err2} Fehler", n=run["qsos"], m=f"{run['seconds'] / 60:.0f}",
                rate=run["rate"], err=run["errors"], n2=sp["qsos"],
                m2=f"{sp['seconds'] / 60:.0f}", rate2=sp["rate"], err2=sp["errors"]))
            lb.setWordWrap(True)
            lay.addWidget(lb)
        if res.findings:
            tbl = QTableWidget(len(res.findings), 2)
            tbl.setHorizontalHeaderLabels([tr("Fehler"), tr("Was genau")])
            tbl.verticalHeader().hide()
            tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            for r, f in enumerate(res.findings):
                a, b = finding_text(f)
                tbl.setItem(r, 0, QTableWidgetItem(a))
                tbl.setItem(r, 1, QTableWidgetItem(b))
            tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            tbl.resizeColumnToContents(0)
            lay.addWidget(tbl, 1)
        else:
            lay.addWidget(QLabel(tr("Keine Fehler – sauber gearbeitet!")))
        same = [h for h in history if h.get("contest") == settings.contest
                and h.get("mode") == settings.mode
                and h.get("style", settings.style) == settings.style][-6:-1]
        if same:
            lines = [tr("Frühere Übungen ({contest}):", contest=contest_name)]
            for h in reversed(same):
                lines.append(tr("{date}: {n} QSOs in {m} min, Rate {rate}, {err} Fehler",
                                date=h["date"], n=h["qsos"], m=f"{h['minutes']:.0f}",
                                rate=h["rate"], err=h["errors"]))
            lb = QLabel("\n".join(lines))
            lb.setWordWrap(True)
            lay.addWidget(lb)
        bb = QDialogButtonBox()
        bb.addButton(tr("Schließen"), QDialogButtonBox.ButtonRole.RejectRole)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)


# ------------------------------------------------------------------ Ablauf
class PracticeController:
    """Hält Übung, Tonstrom und Banner; der Hauptbildschirm fragt nur `win.practice`."""

    def __init__(self, win, settings: pm.Settings, engine: pm.Practice, mixer: cwsynth.Mixer,
                 stream, prev_log: str, log_path: str):
        self.win, self.s, self.engine, self.mixer, self.stream = win, settings, engine, mixer, stream
        self.prev_log, self.log_path = prev_log, log_path
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.started_at = time.monotonic()
        self.voices = engine.voices
        self.waiting: list = []                          # SSB: Stimme noch nicht fertig
        self._wait: list = []
        self.listen = bool(getattr(engine, "tuned", False))   # S&P: Funkgerät nur hören
        self.vfo: int | None = None
        self.rig_mode = ""
        self.band_ok = True
        self.at_run: bool | None = None                  # gemischt: VFO auf der Run-Frequenz?
        if self.listen:
            if settings.mode == "SSB":
                mixer.set_filter(1500.0, 1200.0)
            else:
                mixer.set_filter(float(settings.my_pitch), 250.0)

    @property
    def now(self) -> float:
        return self.mixer.now

    def start(self) -> None:
        self.timer.start(20)

    def _on_sent(self, text: str, start: float, end: float, my_exch: str) -> None:
        if self.listen:
            self.engine.on_sent(text, start, end, my_exch, rf=self.vfo)
        else:
            self.engine.on_sent(text, start, end, my_exch)

    def send(self, text: str, my_exch: str) -> None:
        start = max(self.mixer.now, self.mixer.busy_until("me"))
        x = cwsynth.render(text, self.s.my_wpm, self.s.my_pitch)
        end = self.mixer.add(x, start, -8.0, None, who="me")
        self._on_sent(text, start, end, my_exch)

    def send_ssb(self, meaning: str, samples, my_exch: str) -> float:
        """SSB: eigene Aufnahmen abspielen – oder du sprichst selbst (dann nur geschätzte
        Dauer). Gibt die Dauer zurück."""
        start = max(self.mixer.now, self.mixer.busy_until("me"))
        if samples is not None and len(samples):
            end = self.mixer.add(samples, start, -6.0, None, who="me")
        else:
            end = start + pm.spoken_estimate(meaning, self.engine.mycall)
        self._my_end = end                               # Ende deiner Durchsage
        self._on_sent(meaning, start, end, my_exch)
        return end - self.mixer.now

    def stop_sending(self) -> None:
        self.mixer.cancel("me")
        self.engine.abort_own(self.mixer.now)

    def follow_rig(self) -> None:
        """S&P: VFO und Band vom Funkgerät übernehmen (nur lesen)."""
        from ..bands import band_for_freq
        rig = getattr(self.win, "rig", None)
        st = rig.snapshot() if rig is not None else None
        if st is None or not st.connected or not st.freq:
            self.vfo = None
            self.mixer.tune(None)
            if hasattr(self.engine, "set_vfo"):
                self.engine.set_vfo(None, self.mixer.now)
            return
        self.vfo, self.rig_mode = int(st.freq), (st.mode or "").upper()
        side = -1 if self.rig_mode in ("LSB", "CWR", "CW-R", "PKTLSB") else 1
        self.mixer.tune(self.vfo, side)
        if self.voices is not None and hasattr(self.voices, "focus") and \
                time.monotonic() >= getattr(self, "_focus_next", 0.0):
            self._focus_next = time.monotonic() + 0.5
            self.voices.focus(self.engine.near_calls(self.vfo))
        band = band_for_freq(self.vfo)
        bands = getattr(self.engine.contest, "bands", None) or [self.s.band]
        self.band_ok = band in bands
        self.engine.set_band(band if self.band_ok else None, self.mixer.now)
        self._follow_run()

    def _follow_run(self) -> None:
        """Gemischt (0.8.30): Run ↔ S&P umschalten, sobald du auf deine Run-Frequenz drehst
        oder von ihr weg – nur beim Wechsel, Strg+Tab dazwischen bleibt gültig."""
        if not hasattr(self.engine, "set_vfo"):
            return
        self.engine.set_vfo(self.vfo, self.mixer.now)
        at = self.engine.at_run()
        if at is not None and at != self.at_run:
            self.win._practice_set_esm("run" if at else "sp")
        if at is not None:
            self.at_run = at

    def spots(self) -> list:
        return self.engine.take_spots() if self.listen else []

    def tick(self) -> None:
        t = self.mixer.now
        if self.listen:
            self.follow_rig()
            for sp in self.spots():
                self.win._practice_spot(sp)
        for tx in self.waiting + self.engine.tick(t):
            if tx.key:                                   # SSB: Stimme fertig?
                x = self.voices.get(tx.key) if self.voices is not None else None
                if x is None:
                    # rechnet noch – gleich nochmal (S&P: länger warten statt auszulassen)
                    if t - tx.start < (15.0 if tx.rf else 4.0):
                        self._wait.append(tx)
                    continue
                if tx.rf:
                    x = cwsynth.analytic(x)
            elif tx.rf:
                x = cwsynth.render_analytic(tx.text, tx.wpm, self.s.my_pitch)
            else:
                x = cwsynth.render(tx.text, tx.wpm, tx.pitch)
            if tx.rf:
                self.mixer.add_tuned(x, max(tx.start, t), tx.rf, tx.gain_db, tx.qsb, who=tx.who)
                continue
            self.mixer.add(x, max(tx.start, t), tx.gain_db, tx.qsb, who=tx.who)
        self.waiting, self._wait = self._wait, []
        self.win._practice_banner_update(self.remaining())
        if self.engine.finished(t):
            self.win.end_practice(auto=True)

    def remaining(self) -> int | None:
        if self.s.minutes <= 0:
            return None
        return max(0, int(self.s.minutes * 60 - self.mixer.now))

    def stop(self) -> None:
        self.timer.stop()
        self.stream.stop()
        if self.voices is not None:
            self.voices.close()


def practice_dir() -> Path:
    d = Path.home() / "GoGoHam" / "Übung"
    d.mkdir(parents=True, exist_ok=True)
    return d


def practice_log_name(contest: str, when: datetime | None = None) -> Path:
    when = when or datetime.now(timezone.utc)
    base = practice_dir() / f"{contest}-{when.strftime('%Y-%m-%d-%H%M')}"
    p, n = base.with_suffix(".ggh"), 2
    while p.exists():
        p, n = Path(f"{base}-{n}.ggh"), n + 1
    return p


def mix_volume(percent: int) -> float:
    return float(np.clip(percent / 100.0, 0.02, 1.0)) * 0.9
