"""Seite „GPS“ in den Einstellungen (ab 0.10.25): Empfänger wählen, Live-Anzeige, Uhr stellen,
USB-Freigabe."""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from .. import clockcheck as ck
from .. import gps
from .. import permissions
from ..i18n import tr

BAUD_CHOICES = [0, 4800, 9600, 19200, 38400, 57600, 115200]


class GpsPage(QWidget):
    def __init__(self, cfg: dict, parent=None, watch=None, scan_fn=gps.scan,
                 gpsd_fn=gps.gpsd_available, listen_fn=gps.listen):
        super().__init__(parent)
        self.cfg = cfg
        self.g = dict(gps.gps_settings(cfg))
        self.watch = watch                       # GpsWatch des Hauptfensters (Live-Anzeige)
        self.scan_fn, self.gpsd_fn, self.listen_fn = scan_fn, gpsd_fn, listen_fn
        self._probe: threading.Thread | None = None
        self._probe_result = None
        self.ports: list[gps.Port] = []

        form = QFormLayout()
        self.enabled = QCheckBox(tr("GPS-Empfänger benutzen (Standort, Locator und Uhrzeit)"))
        self.enabled.setChecked(bool(self.g["enabled"]))
        form.addRow(self.enabled)
        self.device = QComboBox()
        self.device.setMinimumContentsLength(30)
        self.btn_scan = QPushButton(tr("Neu suchen"))
        self.btn_scan.clicked.connect(self.fill)
        row = QHBoxLayout()
        row.addWidget(self.device, 1)
        row.addWidget(self.btn_scan)
        form.addRow(tr("Empfänger:"), row)
        self.baud = QComboBox()
        for b in BAUD_CHOICES:
            self.baud.addItem(tr("Automatisch") if b == 0 else f"{b} Baud", b)
        self.baud.setCurrentIndex(max(self.baud.findData(int(self.g.get("baud") or 0)), 0))
        form.addRow(tr("Geschwindigkeit:"), self.baud)
        self.btn_probe = QPushButton(tr("Diesen Anschluss prüfen"))
        self.btn_probe.setToolTip(tr("Hört nach, ob an dem gewählten Anschluss GPS-Daten "
                                     "ankommen. Es wird nichts gesendet."))
        self.btn_probe.clicked.connect(self.probe)
        self.probe_result = QLabel("")
        self.probe_result.setWordWrap(True)
        prow = QHBoxLayout()
        prow.addWidget(self.btn_probe)
        prow.addWidget(self.probe_result, 1)
        form.addRow("", prow)
        self.device.currentIndexChanged.connect(lambda _i: self._device_changed())

        opts = QGroupBox(tr("Was GoGoHam mit dem GPS macht"))
        ol = QVBoxLayout(opts)
        self.grid_hint = QCheckBox(tr("Hinweis, wenn der Locator im Log nicht zum Standort passt "
                                      "(mit Knopf „Übernehmen“)"))
        self.grid_hint.setChecked(bool(self.g["grid_hint"]))
        self.map = QCheckBox(tr("Eigener Standort auf Karte, für Rotor und Baken vom GPS"))
        self.map.setChecked(bool(self.g["map"]))
        self.clock = QCheckBox(tr("Uhrzeit mit dem GPS vergleichen und bei Abweichung fragen"))
        self.clock.setChecked(bool(self.g["clock"]))
        for w in (self.grid_hint, self.map, self.clock):
            ol.addWidget(w)

        live = QGroupBox(tr("Jetzt"))
        ll = QVBoxLayout(live)
        self.live = QLabel("")
        self.live.setWordWrap(True)
        self.live.setTextInteractionFlags(self.live.textInteractionFlags())
        ll.addWidget(self.live)
        crow = QHBoxLayout()
        self.btn_clock = QPushButton(tr("PC-Uhr nach GPS stellen"))
        self.btn_clock.clicked.connect(self._set_clock)
        crow.addWidget(self.btn_clock)
        crow.addStretch(1)
        ll.addLayout(crow)

        acc = QGroupBox(tr("Zugriff auf USB-Geräte"))
        al = QHBoxLayout(acc)
        self.access = QLabel("")
        self.access.setWordWrap(True)
        self.btn_access = QPushButton(tr("USB-Geräte freigeben …"))
        self.btn_access.clicked.connect(self._fix_access)
        al.addWidget(self.access, 1)
        al.addWidget(self.btn_access)

        self.btn_forget = QPushButton(tr("Abgelehnte Geräte wieder anbieten"))
        self.btn_forget.clicked.connect(self._forget)
        hint = QLabel(tr("Einfach den GPS-Empfänger einstecken – egal an welche Buchse. GoGoHam "
                         "erkennt ihn und fragt, ob er benutzt werden soll. Allgemeine "
                         "USB-Adapter (wie in Funkgeräten und Interfaces) öffnet GoGoHam nie von "
                         "selbst: Über manche Leitungen wird dort gesendet. Für so einen Adapter "
                         "gibt es „Diesen Anschluss prüfen“."))
        hint.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addWidget(opts)
        lay.addWidget(live)
        lay.addWidget(acc)
        frow = QHBoxLayout()
        frow.addWidget(self.btn_forget)
        frow.addStretch(1)
        lay.addLayout(frow)
        lay.addStretch(1)
        self.fill()
        self._update_access()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    # ------------------------------------------------------------------ Auswahl
    def fill(self) -> None:
        keep = self.current()
        self.ports = self.scan_fn(verified=self.g.get("verified", []))
        self.device.blockSignals(True)
        self.device.clear()
        self.device.addItem(tr("Automatisch (gpsd, falls vorhanden – sonst erkannter Empfänger)"),
                            ("auto", ""))
        if self.gpsd_fn():
            self.device.addItem(tr("gpsd (läuft auf diesem Rechner)"), ("gpsd", ""))
        keys = set()
        for p in self.ports:
            keys.add(p.key)
            if gps.is_profile_port(p.path, self.cfg):
                extra = tr("Funkgerät-Profil")
            elif p.kind == "gps":
                extra = tr("GPS erkannt")
            else:
                extra = tr("unbekannt – erst prüfen")
            self.device.addItem(f"{p.label} – {extra}", ("dev", p.key))
        if self.g.get("device") and self.g["device"] not in keys:
            self.device.addItem(tr("{name} – nicht eingesteckt",
                                   name=self.g.get("label") or self.g["device"]),
                                ("dev", self.g["device"]))
        want = keep if keep is not None else (
            ("gpsd", "") if self.g["source"] == "gpsd" else
            ("dev", self.g["device"]) if self.g["source"] == "serial" and self.g["device"]
            else ("auto", ""))
        idx = self.device.findData(want)
        self.device.setCurrentIndex(max(idx, 0))
        self.device.blockSignals(False)
        self._device_changed()

    def current(self):
        return self.device.currentData() if self.device.count() else None

    def selected_port(self) -> gps.Port | None:
        cur = self.current()
        if not cur or cur[0] != "dev":
            return None
        return gps.find(cur[1], self.ports)

    def _device_changed(self) -> None:
        self.btn_probe.setEnabled(self.selected_port() is not None)
        self.probe_result.setText("")

    # ------------------------------------------------------------------ Prüfen
    def probe(self) -> None:
        p = self.selected_port()
        if p is None or self._probe is not None:
            return
        if gps.is_profile_port(p.path, self.cfg):
            self.probe_result.setText("✘ " + tr("Dieser Anschluss gehört zu einem Funkgerät- oder "
                                                "Rotor-Profil – GoGoHam prüft ihn nicht."))
            self.probe_result.setStyleSheet("color:#c62828;")
            return
        if p.kind != "gps":
            ans = QMessageBox.question(
                self, tr("Anschluss prüfen"),
                tr("Hängt an {name} sicher kein Funkgerät und kein Interface?\n\nBeim Öffnen "
                   "können bei manchen Adaptern kurz Steuerleitungen schalten – bei manchen "
                   "Interfaces heißt das: Senden. Es wird nur gelesen, nichts geschickt.",
                   name=p.label),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                return
        if not os.access(p.path, os.R_OK):
            self.probe_result.setText("✘ " + tr("Kein Zugriff – bitte zuerst „USB-Geräte "
                                                "freigeben …“."))
            self.probe_result.setStyleSheet("color:#c62828;")
            return
        self.probe_result.setStyleSheet("")
        self.probe_result.setText(tr("Höre zu … (bis zu 20 Sekunden)"))
        self.btn_probe.setEnabled(False)
        baud = self.baud.currentData() or 0
        listen_fn = self.listen_fn

        def run() -> None:
            try:
                self._probe_result = ("ok", listen_fn(p.path, [baud] if baud else None,
                                                     dtr_retry=p.kind == "gps"))
            except OSError as e:
                self._probe_result = ("err", gps.explain(e, p.path)[1])
        self._probe_port = p
        self._probe = threading.Thread(target=run, daemon=True)
        self._probe.start()
        QTimer.singleShot(300, self._probe_poll)

    def _probe_poll(self) -> None:
        if self._probe is not None and self._probe.is_alive():
            QTimer.singleShot(300, self._probe_poll)
            return
        self._probe = None
        kind, res = self._probe_result or ("err", "?")
        self.btn_probe.setEnabled(True)
        p = self._probe_port
        if kind == "ok" and res:
            ver = set(self.g.get("verified", []))
            ver.add(p.key)
            self.g["verified"] = sorted(ver)
            self.probe_result.setText("✔ " + tr("GPS-Daten gefunden ({b} Baud) – dieser Anschluss "
                                                "gilt jetzt als GPS-Empfänger.", b=res[0]))
            self.probe_result.setStyleSheet("color:#1b8a3a; font-weight:bold;")
        elif kind == "ok":
            self.probe_result.setText("✘ " + tr("Keine GPS-Daten – ist das wirklich ein "
                                                "GPS-Empfänger? Andere Geschwindigkeit versuchen."))
            self.probe_result.setStyleSheet("color:#c62828;")
        else:
            self.probe_result.setText("✘ " + str(res))
            self.probe_result.setStyleSheet("color:#c62828;")

    # ------------------------------------------------------------------ Anzeige
    def refresh(self) -> None:
        st = self.watch.snapshot() if self.watch is not None else None
        if st is None:
            self.live.setText(tr("GPS ist aus.") if not gps.gps_settings(self.cfg)["enabled"] else
                              tr("Noch kein Empfänger verbunden."))
            self.btn_clock.setEnabled(False)
            return
        from .gps_watch import GpsWatch
        text, _lvl = gps.status_text(st)
        self.live.setText("<b>" + text + "</b><br>" + GpsWatch.details(st).replace("\n", "<br>"))
        self.btn_clock.setEnabled(bool(self.watch.can_set_clock()) and ck.is_wrong(st.offset))

    def _set_clock(self) -> None:
        if self.watch is None:
            return
        self.btn_clock.setEnabled(False)
        self.watch.set_clock(done=lambda ok: self.refresh())

    def _update_access(self) -> None:
        if permissions.rule_installed():
            self.access.setText("✔ " + tr("USB-Geräte sind freigegeben."))
            self.btn_access.setVisible(False)
        elif permissions.in_serial_group():
            self.access.setText("✔ " + tr("Du darfst USB-Geräte benutzen (Gruppe). Mit "
                                          "„Freigeben“ geht es künftig auch ohne Gruppe."))
            self.btn_access.setVisible(permissions.uaccess_supported())
        else:
            self.access.setText(tr("USB-Geräte sind noch nicht freigegeben."))
            self.btn_access.setVisible(True)

    def _fix_access(self) -> None:
        from .dialogs import PermissionDialog
        PermissionDialog("", self).exec()
        self._update_access()

    def _forget(self) -> None:
        self.g["ignored"] = []
        self.btn_forget.setText(tr("Erledigt – abgelehnte Geräte werden wieder angeboten"))
        self.btn_forget.setEnabled(False)

    # ------------------------------------------------------------------ Speichern
    def apply(self) -> bool:
        cur = self.current() or ("auto", "")
        g = self.g
        g["enabled"] = self.enabled.isChecked()
        if cur[0] == "dev":
            port = gps.find(cur[1], self.ports)
            g.update(source="serial", device=cur[1], path="",
                     label=port.label if port else g.get("label", ""))
        else:
            g["source"] = cur[0]
            if cur[0] == "gpsd":
                g["path"] = ""                  # fester Anschluss (von Hand) gilt dann nicht mehr
        g["baud"] = int(self.baud.currentData() or 0)
        g["grid_hint"] = self.grid_hint.isChecked()
        g["map"] = self.map.isChecked()
        g["clock"] = self.clock.isChecked()
        self.cfg["gps"] = g
        return True

    def shutdown(self) -> None:
        self.timer.stop()
