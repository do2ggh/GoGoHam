"""Reiter „Sprachaufnahmen“ (ab 0.8.11 eigenes Fenster, ab 0.8.12.9 Reiter in den Einstellungen):
eigene Stimme aufnehmen, Klang einstellen, probehören. Alles wird sofort gespeichert – auch
wenn das Einstellungsfenster mit „Abbrechen“ geschlossen wird.

Probehören läuft nie über das Funkgerät – hier wird nie gesendet. Gesendet wird nur über
F1–F8, „Enter sendet“ und Auto-CQ im Hauptfenster.
"""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QProgressBar, QPushButton, QSlider, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import config as cfgmod
from .. import voice
from ..i18n import num, tr
from . import audio

GREEN, RED, ORANGE = "#1b8a3a", "#c62828", "#e08a00"
MAX_REC_SEC = 15
PROFILE_SLOTS = 2               # eigene Klang-Profile (ab 0.8.11.3)


def _btn(text: str, slot) -> QPushButton:
    b = QPushButton(text)
    b.setAutoDefault(False)
    b.clicked.connect(lambda _=False: slot())
    return b


def _slider(lo: int, hi: int, value: int) -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(int(value))
    s.setMinimumWidth(180)
    return s


class VoicePage(QWidget):
    def __init__(self, cfg: dict, mycall: str = "", parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.mycall = (mycall or "").upper()
        self.cache = voice.ClipCache()
        self.items = voice.all_items()
        self.rec = audio.Recorder(on_level=self._level)
        self.player = audio.Player(on_finished=self._play_done)
        self._rec_item = ""
        self._rec_started = 0.0
        # Pegelanzeige (0.8.11.1): springt sofort hoch, fällt zügig ab (wie ein Aussteuerungs-
        # messer); die Spitze bleibt 1,5 s als Zahl stehen
        self._lvl_new = -60.0          # lautestes Stück seit der letzten Anzeige
        self._lvl_disp = -60.0         # angezeigter Balken
        self._lvl_hold = -60.0         # gehaltene Spitze
        self._lvl_hold_t = 0.0
        self._lvl_color = ""

        missing_qt = audio.available()
        lay = QVBoxLayout(self)
        if missing_qt:
            lab = QLabel(missing_qt)
            lab.setWordWrap(True)
            lab.setStyleSheet(f"color:{RED}; font-weight:bold;")
            lay.addWidget(lab)
            lay.addStretch(1)
            self.ok = False
            return
        self.ok = True

        # ---- Geräte
        dev_box = QGroupBox(tr("Geräte"))
        df = QFormLayout(dev_box)
        self.cb_mic, self.cb_mon, self.cb_rig = QComboBox(), QComboBox(), QComboBox()
        df.addRow(tr("Mikrofon:"), self.cb_mic)
        df.addRow(tr("Probehören über:"), self.cb_mon)
        df.addRow(tr("Soundkarte des Funkgeräts (Senden):"), self.cb_rig)
        refresh = _btn(tr("Geräte neu suchen"), self._fill_devices)
        df.addRow("", refresh)
        self._fill_devices()
        for cb in (self.cb_mic, self.cb_mon, self.cb_rig):
            cb.currentIndexChanged.connect(lambda _i: self._store_devices())

        # ---- Liste der Aufnahmen
        self.tbl = QTableWidget(len(self.items), 3)
        self.tbl.setHorizontalHeaderLabels([tr("Aufnahme"), tr("Was du sagst"), tr("Stand")])
        self.tbl.verticalHeader().hide()
        self.tbl.setMinimumWidth(420)       # als Reiter (0.8.12.9): Spalte „Was du sagst“ lesbar
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for r, (_pid, name, hint) in enumerate(self.items):
            self.tbl.setItem(r, 0, QTableWidgetItem(name))
            self.tbl.setItem(r, 1, QTableWidgetItem(hint))
            self.tbl.setItem(r, 2, QTableWidgetItem(""))
        self.tbl.selectRow(0)
        self.tbl.itemSelectionChanged.connect(self._selection_changed)

        # ---- Aufnehmen
        rec_box = QGroupBox(tr("Aufnehmen"))
        rl = QVBoxLayout(rec_box)
        self.lbl_item = QLabel("")
        self.lbl_item.setWordWrap(True)
        rl.addWidget(self.lbl_item)
        row = QHBoxLayout()
        self.btn_rec = _btn(tr("● Aufnehmen"), self.toggle_record)
        self.btn_play = _btn(tr("▶ Probehören"), self.play_item)
        self.btn_del = _btn(tr("Löschen"), self.delete_item)
        for b in (self.btn_rec, self.btn_play, self.btn_del):
            row.addWidget(b)
        rl.addLayout(row)
        gl = QFormLayout()
        self.sl_gain = _slider(0, 30, int(cfg.get("voice_gain_db", 0)))
        self.lbl_gain = QLabel("")
        g = QHBoxLayout()
        g.addWidget(self.sl_gain)
        g.addWidget(self.lbl_gain)
        gl.addRow(tr("Verstärkung:"), g)
        self.meter = QProgressBar()
        self.meter.setRange(-60, 0)
        self.meter.setValue(-60)
        self.meter.setTextVisible(True)
        self.meter.setFormat(tr("Pegel: –"))
        m = QHBoxLayout()
        m.addWidget(self.meter, 1)
        self.btn_level = _btn(tr("Pegel prüfen"), self.toggle_level)
        m.addWidget(self.btn_level)
        gl.addRow(tr("Pegel:"), m)
        rl.addLayout(gl)
        tip = QLabel(tr("Sprich wie im Contest. Spitzen um −12 dB (grün), nie rot. Stille "
                        "schneidet GoGoHam selbst ab; danach geht es mit dem nächsten Eintrag "
                        "weiter."))
        tip.setWordWrap(True)
        rl.addWidget(tip)
        self.sl_gain.valueChanged.connect(self._gain_changed)
        self._gain_changed(self.sl_gain.value())

        # ---- Klang
        tone = dict(voice.DEFAULT_TONE, **cfg.get("voice_tone", {}))
        tone_box = QGroupBox(tr("Klang (wirkt beim Abspielen und Senden)"))
        tf = QFormLayout(tone_box)
        self.cb_preset = QComboBox()
        self.cb_preset.addItem(tr("Normal"), "normal")
        self.cb_preset.addItem(tr("Kräftig (Kompromiss aus Normal und Contest)"), "strong")
        self.cb_preset.addItem(tr("Contest (kräftiger, besser verständlich)"), "contest")
        # Eigene Profile (ab 0.8.11.3): zwei Speicherplätze für eigene Regler-Einstellungen.
        # voice_tone["preset"] bleibt die Grundart (Normal/Kräftig/Contest) für die Bearbeitung,
        # voice_tone["profile"] sagt, was im Feld ausgewählt ist.
        self._base = tone.get("preset", "normal")
        for i in range(PROFILE_SLOTS):
            self.cb_preset.addItem("", f"user{i + 1}")
        self._label_profiles()
        self.cb_preset.setCurrentIndex(
            max(0, self.cb_preset.findData(tone.get("profile") or tone.get("preset"))))
        self.cb_preset.setToolTip(tr("Normal: unverändert · Kräftig: Brummfilter, weniger Bass und "
                                     "Dumpfes, mehr Präsenz – ohne eigene Kompression (dafür den "
                                     "Sprachprozessor im Funkgerät nutzen) · Contest: schmal und "
                                     "verdichtet"))
        pr = QHBoxLayout()
        pr.addWidget(self.cb_preset, 1)
        self.btn_save_profile = _btn(tr("Als eigenes Profil speichern …"), self.save_profile)
        pr.addWidget(self.btn_save_profile)
        tf.addRow(tr("Voreinstellung:"), pr)
        self.sliders = {}
        for key, label in (("bass", tr("Bässe:")), ("lowmid", tr("Tiefmitten:")),
                           ("mid", tr("Mitten:")), ("treble", tr("Höhen:"))):
            s = _slider(-12, 12, int(tone.get(key, 0)))
            lab = QLabel("")
            h = QHBoxLayout()
            h.addWidget(s)
            h.addWidget(lab)
            tf.addRow(label, h)
            self.sliders[key] = (s, lab, "{v:+d} dB")
        s = _slider(0, 150, int(tone.get("volume", 100)))
        lab = QLabel("")
        h = QHBoxLayout()
        h.addWidget(s)
        h.addWidget(lab)
        tf.addRow(tr("Lautstärke:"), h)
        self.sliders["volume"] = (s, lab, "{v} %")
        self.ed_test = QLineEdit(cfg.get("voice_test_text", "[CQ] {MYCALL} {MYCALL}"))
        self.ed_test.setToolTip(tr("Zum Probehören: feste Ansagen in eckigen Klammern, z. B. "
                                   "[CQ] [TU]; {MYCALL} = dein Rufzeichen; alles andere wird "
                                   "buchstabiert"))
        th = QHBoxLayout()
        th.addWidget(self.ed_test, 1)
        th.addWidget(_btn(tr("▶ Ansage probehören"), self.play_test))
        tf.addRow(tr("Probe-Ansage:"), th)
        for key, (s, lab, fmt) in self.sliders.items():
            s.valueChanged.connect(lambda _v, k=key: self._tone_changed(k))
            lab.setText(fmt.format(v=s.value()))
        self.cb_preset.currentIndexChanged.connect(self._preset_changed)

        # ---- Senden
        send_box = QGroupBox(tr("Aussenden"))   # über das Funkgerät (nicht „Nachricht senden“)
        sf = QFormLayout(send_box)
        # Ob F1–F8 diese Aufnahmen senden, steht nur noch auf dem Reiter Funktionstasten
        # („SSB-Ansagen kommen aus“) – ab 0.8.12.9; hier nur für die Warnung unten gemerkt
        self.source = cfg.get("voice_source", "rig")
        self.sl_send = _slider(0, 100, int(cfg.get("voice_send_level", 20)))
        self.lbl_send = QLabel("")
        h = QHBoxLayout()
        h.addWidget(self.sl_send)
        h.addWidget(self.lbl_send)
        sf.addRow(tr("Sendepegel zum Funkgerät:"), h)
        self.sl_send.valueChanged.connect(self._send_changed)
        self._send_changed(self.sl_send.value())
        hint = QLabel(tr("IC-7300: MENU → SET → Connectors → MOD Input → „DATA OFF MOD“ auf "
                         "„USB“ (oder „MIC,USB“) stellen, sonst fehlt der Ton in der Aussendung. "
                         "Pegel mit der ALC-Anzeige prüfen – am besten an einer Kunstantenne."))
        hint.setWordWrap(True)
        sf.addRow(hint)

        # ---- Zusammenbau
        self.lbl_state = QLabel("")
        self.lbl_state.setWordWrap(True)
        right = QVBoxLayout()
        right.addWidget(rec_box)
        right.addWidget(tone_box)
        right.addWidget(send_box)
        right.addStretch(1)
        rw = QWidget()
        rw.setLayout(right)
        mid = QHBoxLayout()
        mid.addWidget(self.tbl, 1)
        mid.addWidget(rw, 1)
        lay.addWidget(dev_box)
        lay.addLayout(mid, 1)
        lay.addWidget(self.lbl_state)
        note = QLabel(tr("Aufnahmen und Einstellungen auf diesem Reiter werden sofort gespeichert "
                         "– auch bei „Abbrechen“."))
        note.setWordWrap(True)
        note.setStyleSheet("color:gray;")
        lay.addWidget(note)

        self.tick = QTimer(self)
        self.tick.timeout.connect(self._tick)
        self.tick.start(30)
        self._refresh_table()
        self._selection_changed()

    # ------------------------------------------------------------- Geräte
    def _fill_devices(self) -> None:
        ins, outs = audio.inputs(), audio.outputs()
        for cb, devs, key, empty in (
                (self.cb_mic, ins, "voice_mic", tr("(Standard des Systems)")),
                (self.cb_mon, outs, "voice_monitor", tr("(Standard des Systems)")),
                (self.cb_rig, outs, "voice_rig_out", self._auto_rig_text())):
            cb.blockSignals(True)
            cb.clear()
            cb.addItem(empty, "")
            for dev_id, name in devs:
                cb.addItem(name, dev_id)
            want = self.cfg.get(key, "")
            i = cb.findData(want)
            if want and i < 0:                         # gespeichertes Gerät gerade nicht da
                cb.addItem(tr("{name} (nicht angeschlossen)", name=want), want)
                i = cb.count() - 1
            cb.setCurrentIndex(max(0, i))
            cb.blockSignals(False)

    def _auto_rig(self) -> tuple[str, str]:
        """Automatisch gefundene Soundkarte des Funkgeräts (0.10.30.1) – ohne Handwahl."""
        if getattr(self, "_auto_rig_hit", None) is None:
            from .. import rigaudio
            try:
                self._auto_rig_hit = rigaudio.voice_out(dict(self.cfg, voice_rig_out=""))
            except Exception:  # noqa: BLE001 – Suche darf das Fenster nie verhindern
                self._auto_rig_hit = ("", "")
        return self._auto_rig_hit

    def _auto_rig_text(self) -> str:
        dev_id, _how = self._auto_rig()
        if not dev_id:
            return tr("Automatisch – noch keine gefunden (bitte wählen)")
        name = next((n for i, n in audio.outputs() if i == dev_id), "")
        if not name:
            from ..extapps import nice_sound
            name = nice_sound(dev_id)
        return tr("Automatisch: {name}", name=name)

    def _store_devices(self) -> None:
        self.cfg["voice_mic"] = self.cb_mic.currentData() or ""
        self.cfg["voice_monitor"] = self.cb_mon.currentData() or ""
        self.cfg["voice_rig_out"] = self.cb_rig.currentData() or ""
        self._save()
        self._update_state()

    def _mic(self):
        from PySide6.QtMultimedia import QMediaDevices
        dev_id = self.cfg.get("voice_mic", "")
        return audio.find("in", dev_id) if dev_id else QMediaDevices.defaultAudioInput()

    def _monitor(self):
        from PySide6.QtMultimedia import QMediaDevices
        dev_id = self.cfg.get("voice_monitor", "")
        return audio.find("out", dev_id) if dev_id else QMediaDevices.defaultAudioOutput()

    def _monitor_is_rig(self, dev) -> bool:
        rig = self.cfg.get("voice_rig_out", "") or self._auto_rig()[0]
        if dev is None:
            return False
        dev_id = bytes(dev.id()).decode("utf-8", "replace")
        if rig:
            return dev_id == rig
        return any(h.lower() in dev.description().lower() for h in audio.RIG_CODEC_HINTS)

    # -------------------------------------------------------------- Liste
    def current_item(self) -> str:
        r = self.tbl.currentRow()
        return self.items[r][0] if 0 <= r < len(self.items) else ""

    def _refresh_table(self) -> None:
        have = self.cache.have()
        for r, (pid, _n, _h) in enumerate(self.items):
            it = self.tbl.item(r, 2)
            if pid in have:
                x = self.cache.get(pid)
                sec = len(x) / voice.RATE if x is not None else 0
                it.setText(tr("✔ {s} s", s=num(sec, 1)))
                it.setForeground(Qt.GlobalColor.darkGreen)
            else:
                it.setText("—")
                it.setForeground(Qt.GlobalColor.gray)
        self._update_state()

    def _update_state(self) -> None:
        have = self.cache.have()
        miss = [c for c in voice.required_for_spelling() if c not in have]
        parts = []
        if miss:
            parts.append(tr("Zum Buchstabieren fehlen noch {n}: {list}", n=len(miss),
                            list=" ".join(miss)))
        else:
            parts.append(tr("Alle Buchstaben und Ziffern sind aufgenommen."))
        if self.source == "gogoham" and not self.cfg.get("voice_rig_out") \
                and not self._auto_rig()[0]:
            parts.append(tr("Bitte noch die Soundkarte des Funkgeräts wählen – sonst kann "
                            "GoGoHam nicht senden."))
        self.lbl_state.setText(" ".join(parts))
        self.lbl_state.setStyleSheet(f"color:{ORANGE};" if len(parts) > 1 or miss
                                     else f"color:{GREEN};")

    def _selection_changed(self) -> None:
        r = self.tbl.currentRow()
        if not (0 <= r < len(self.items)):
            return
        _pid, name, hint = self.items[r]
        self.lbl_item.setText(tr("<b>{name}</b> – sag: {hint}", name=name, hint=hint or "…"))

    # ---------------------------------------------------------- Aufnahme
    def toggle_record(self) -> None:
        if self.rec.recording:
            self._finish_record()
            return
        item = self.current_item()
        if not item:
            return
        self.player.stop(notify=False)
        if not self.rec.start(self._mic(), record=True):
            QMessageBox.warning(self, tr("Sprachaufnahmen"), self.rec.error)
            return
        self._rec_item = item
        self._rec_started = time.monotonic()
        self.btn_rec.setText(tr("■ Stopp"))
        self.btn_rec.setStyleSheet(f"background:{RED}; color:white; font-weight:bold;")
        self.btn_level.setText(tr("Pegel prüfen"))
        self.tbl.setEnabled(False)

    def _finish_record(self) -> None:
        x = self.rec.stop()
        self._reset_meter()
        self.btn_rec.setText(tr("● Aufnehmen"))
        self.btn_rec.setStyleSheet("")
        self.tbl.setEnabled(True)
        item, self._rec_item = self._rec_item, ""
        if not item:
            return
        if len(voice.trim_silence(x)) < voice.RATE // 20:
            QMessageBox.warning(self, tr("Sprachaufnahmen"),
                                tr("In der Aufnahme ist nichts zu hören – Mikrofon und "
                                   "Verstärkung prüfen. Die alte Aufnahme bleibt erhalten."))
            return
        voice.save_wav(voice.clip_path(item), x)
        self.cache.forget(item)
        self._refresh_table()
        r = self.tbl.currentRow()
        if r + 1 < len(self.items):
            self.tbl.selectRow(r + 1)                    # gleich das Nächste aufnehmen

    def toggle_level(self) -> None:
        if self.rec.active:
            if self.rec.recording:
                return
            self.rec.stop()
            self.btn_level.setText(tr("Pegel prüfen"))
            self._reset_meter()
            return
        if not self.rec.start(self._mic(), record=False):
            QMessageBox.warning(self, tr("Sprachaufnahmen"), self.rec.error)
            return
        self.btn_level.setText(tr("Pegel aus"))

    def _gain_changed(self, v: int) -> None:
        self.rec.gain_db = float(v)
        self.lbl_gain.setText(f"+{v} dB")
        self.cfg["voice_gain_db"] = int(v)
        self._save()

    def _level(self, db: float) -> None:
        """Vom Mikrofon (etwa alle 20 ms) – nur merken, gezeichnet wird im Takt von _tick."""
        self._lvl_new = max(self._lvl_new, db)

    def _reset_meter(self) -> None:
        self._lvl_new = self._lvl_disp = self._lvl_hold = -60.0
        self.meter.setValue(-60)
        self.meter.setFormat(tr("Pegel: –"))

    def _draw_meter(self) -> None:
        if not self.rec.active:
            return
        now = time.monotonic()
        new, self._lvl_new = self._lvl_new, -60.0
        # sofort hoch, dann ca. 30 dB pro Sekunde abfallen
        self._lvl_disp = max(new, self._lvl_disp - 30.0 * 0.03, -60.0)
        if new >= self._lvl_hold or now - self._lvl_hold_t > 1.5:
            self._lvl_hold, self._lvl_hold_t = max(new, self._lvl_disp), now
        v = int(round(max(-60.0, min(0.0, self._lvl_disp))))
        if v != self.meter.value():
            self.meter.setValue(v)
        hold = int(round(max(-60.0, min(0.0, self._lvl_hold))))
        self.meter.setFormat(tr("Spitze: {v} dB", v=hold))
        color = RED if hold > -3 else (ORANGE if hold > -8 or hold < -30 else GREEN)
        if color != self._lvl_color:                    # Stil nur bei Farbwechsel setzen
            self._lvl_color = color
            self.meter.setStyleSheet(f"QProgressBar::chunk {{ background:{color}; }}")

    def _tick(self) -> None:
        self._draw_meter()
        if self.rec.recording and time.monotonic() - self._rec_started > MAX_REC_SEC:
            self._finish_record()

    # --------------------------------------------------------- Abspielen
    def _tone(self) -> dict:
        t = {k: s.value() for k, (s, _l, _f) in self.sliders.items()}
        t["preset"] = self._base
        t["profile"] = self.cb_preset.currentData()
        return t

    def _play(self, samples: np.ndarray) -> None:
        if self.rec.recording:
            return
        dev = self._monitor()
        if self._monitor_is_rig(dev):
            QMessageBox.warning(self, tr("Sprachaufnahmen"),
                                tr("Probehören geht nie über das Funkgerät. Bitte bei "
                                   "„Probehören über“ Kopfhörer oder Lautsprecher wählen."))
            return
        if not self.player.play(samples, dev, stereo=True):      # Probehören: beide Seiten
            QMessageBox.warning(self, tr("Sprachaufnahmen"), self.player.error)

    def play_item(self) -> None:
        item = self.current_item()
        if item not in self.cache.have():
            return
        p = voice.Plan(parts=[item])
        self._play(voice.render(p, self.cache, self._tone()))

    def play_test(self) -> None:
        self.cfg["voice_test_text"] = self.ed_test.text()
        p = voice.plan(self.ed_test.text(), {"MYCALL": self.mycall or "DO2GGH"},
                       self.cache.have())
        if p.missing:
            QMessageBox.information(self, tr("Sprachaufnahmen"),
                                    tr("Dafür fehlen noch Aufnahmen: {list}",
                                       list=voice.missing_text(p.missing)))
            return
        if p.empty:
            return
        self._play(voice.render(p, self.cache, self._tone()))

    def _play_done(self) -> None:
        if self.player.error:
            self.lbl_state.setText(self.player.error)

    def delete_item(self) -> None:
        item = self.current_item()
        path = voice.clip_path(item)
        if not path.is_file():
            return
        name = self.items[self.tbl.currentRow()][1]
        if QMessageBox.question(self, tr("Sprachaufnahmen"),
                                tr("Aufnahme „{name}“ löschen?", name=name)) \
                != QMessageBox.StandardButton.Yes:
            return
        path.unlink(missing_ok=True)
        self.cache.forget(item)
        self._refresh_table()

    # -------------------------------------------------------------- Klang
    # ------------------------------------------------------- eigene Profile
    def _profiles(self) -> list:
        prof = list(self.cfg.get("voice_profiles") or [])
        return (prof + [None] * PROFILE_SLOTS)[:PROFILE_SLOTS]

    def _label_profiles(self) -> None:
        """Einträge „Eigenes Profil 1/2“ beschriften; leere Plätze sind nicht wählbar."""
        model = self.cb_preset.model()
        for i, prof in enumerate(self._profiles()):
            row = self.cb_preset.findData(f"user{i + 1}")
            if prof:
                text = tr("Eigenes Profil {n}: {name}", n=i + 1, name=prof.get("name") or "–")
            else:
                text = tr("Eigenes Profil {n} (noch leer)", n=i + 1)
            self.cb_preset.setItemText(row, text)
            item = model.item(row)
            if item is not None:
                item.setEnabled(bool(prof))

    def save_profile(self) -> None:
        """Aktuelle Regler (mit Grundart und Lautstärke) in Profil 1 oder 2 speichern."""
        from PySide6.QtWidgets import QInputDialog
        profs = self._profiles()
        names = []
        for i, prof in enumerate(profs):
            names.append(tr("Profil {n}: {name} (wird überschrieben)", n=i + 1,
                            name=prof.get("name") or "–") if prof
                         else tr("Profil {n} (leer)", n=i + 1))
        cur = self.cb_preset.currentData() or ""
        start = int(cur[4:]) - 1 if cur.startswith("user") else \
            next((i for i, pr in enumerate(profs) if not pr), 0)
        choice, ok = QInputDialog.getItem(self, tr("Eigenes Profil speichern"),
                                          tr("Speicherplatz:"), names, start, False)
        if not ok:
            return
        slot = names.index(choice)
        old = profs[slot] or {}
        name, ok = QInputDialog.getText(self, tr("Eigenes Profil speichern"), tr("Name:"),
                                        text=old.get("name") or tr("Mein Klang {n}", n=slot + 1))
        if not ok:
            return
        t = self._tone()
        profs[slot] = {"name": name.strip()[:40] or tr("Mein Klang {n}", n=slot + 1),
                       "base": self._base,
                       **{k: int(t[k]) for k in ("bass", "lowmid", "mid", "treble", "volume")}}
        self.cfg["voice_profiles"] = profs
        self._label_profiles()
        self.cb_preset.blockSignals(True)
        self.cb_preset.setCurrentIndex(self.cb_preset.findData(f"user{slot + 1}"))
        self.cb_preset.blockSignals(False)
        self._save_tone()

    def _set_sliders(self, vals: dict) -> None:
        for k, v in vals.items():
            if k not in self.sliders:
                continue
            s = self.sliders[k][0]
            s.blockSignals(True)
            s.setValue(int(v))
            s.blockSignals(False)
            self.sliders[k][1].setText(self.sliders[k][2].format(v=int(v)))

    def _preset_changed(self, _i: int) -> None:
        key = self.cb_preset.currentData() or "normal"
        if key.startswith("user"):
            prof = self._profiles()[int(key[4:]) - 1]
            if not prof:
                return
            self._base = prof.get("base", "normal")
            self._set_sliders({k: prof.get(k, 0 if k != "volume" else 100)
                               for k in ("bass", "lowmid", "mid", "treble", "volume")})
            self._save_tone()
            return
        self._base = key
        vals = voice.PRESETS.get(key, {})
        for k, v in vals.items():
            s = self.sliders[k][0]
            s.blockSignals(True)
            s.setValue(v)
            s.blockSignals(False)
            self.sliders[k][1].setText(self.sliders[k][2].format(v=v))
        self._save_tone()

    def _tone_changed(self, key: str) -> None:
        s, lab, fmt = self.sliders[key]
        lab.setText(fmt.format(v=s.value()))
        self._save_tone()

    def _save_tone(self) -> None:
        self.cfg["voice_tone"] = self._tone()
        self._save()

    def _send_changed(self, v: int) -> None:
        self.lbl_send.setText(f"{v} %")
        self.cfg["voice_send_level"] = int(v)
        self._save()

    def set_source(self, source: str) -> None:
        """Auswahl auf dem Reiter Funktionstasten geändert (noch nicht gespeichert)."""
        self.source = source
        self._update_state()

    # ------------------------------------------------------------ Sonstiges
    def _save(self) -> None:
        """Sofort speichern – aber nur die Sprach-Einstellungen. Was auf anderen Reitern geändert
        und noch nicht mit OK bestätigt wurde, darf dabei nicht mit auf die Platte."""
        disk = cfgmod.load()
        disk.update({k: v for k, v in self.cfg.items() if k.startswith("voice_")})
        cfgmod.save(disk)

    def apply(self) -> bool:
        """Für das Einstellungsfenster: hier ist schon alles gespeichert."""
        return True

    def shutdown(self) -> None:
        """Beim Schließen der Einstellungen (OK oder Abbrechen): Aufnahme/Wiedergabe beenden."""
        if not self.ok:
            return
        self.tick.stop()
        self.rec.stop()
        self.player.stop(notify=False)
        self.cfg["voice_test_text"] = self.ed_test.text()
        self._save()
