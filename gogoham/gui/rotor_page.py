"""Reiter „Rotor“ in den Einstellungen (ab 0.8.23) – aufgebaut wie „Funkgerät“: vorne nur das
Nötige, rotctld und eigene Optionen hinter „Erweiterte Einstellungen …“."""

from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from .. import hamlib
from .. import rotor as rt
from ..i18n import tr


class RotorPage(QWidget):
    def __init__(self, cfg: dict, parent=None, test_fn=None, service_ok=None):
        super().__init__(parent)
        from .. import rigservice
        self.cfg = cfg
        self.test_fn = test_fn                  # Tests: Ersatz für rotor.test_profile
        self.prof = rt.profile(cfg)
        self.rotors = list(rt.list_rotors())
        self._svc_ok = rigservice.available() if service_ok is None else service_ok
        self._loading = False

        form = QFormLayout()
        self.enabled = QCheckBox(tr("Rotor steuern"))
        self.enabled.setChecked(bool(self.prof["enabled"]))
        form.addRow(self.enabled)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Suchen: z. B. GS-232, ERC, SPID, Easycomm …"))
        self.search.textEdited.connect(lambda t: self._fill_models(self.model.currentData() or 0))
        form.addRow(tr("Rotor/Interface suchen:"), self.search)
        self.model = QComboBox()
        self.model.currentIndexChanged.connect(lambda _i: self._model_changed())
        form.addRow(tr("Rotor/Interface:"), self.model)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        form.addRow("", self.info)
        if not self.rotors:
            self.info.setText(tr("Hamlib (rotctl) nicht gefunden – bitte Hamlib installieren."))

        self.device = QComboBox()
        self.device.setEditable(True)
        self.device.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.device.setMinimumContentsLength(24)
        self.btn_ports = QPushButton(tr("Neu suchen"))
        self.btn_ports.clicked.connect(lambda: self._fill_ports(self.device.currentText()))
        row = QHBoxLayout()
        row.addWidget(self.device, 1)
        row.addWidget(self.btn_ports)
        form.addRow(tr("Schnittstelle:"), row)
        self.baud = QComboBox()
        form.addRow(tr("Baudrate:"), self.baud)

        self.btn_test = QPushButton(tr("Verbindung testen"))
        self.btn_test.setToolTip(tr("Liest einmal die Richtung – der Rotor dreht dabei nicht"))
        self.btn_test.clicked.connect(self._test)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self.btn_test)
        row.addWidget(self.test_result, 1)
        form.addRow("", row)

        self.auto = QCheckBox(tr("Automatisch drehen, wenn ein Rufzeichen eingetippt ist"))
        self.auto.setToolTip(tr("Dreht auf den Short Path, sobald du 1,5 Sekunden nicht tippst und "
                                "GoGoHam die Richtung kennt. Standard: aus"))
        self.auto.setChecked(bool(cfg.get("rotor_auto", False)))
        form.addRow("", self.auto)
        self.beamwidth = QSpinBox()
        self.beamwidth.setRange(5, 180)
        self.beamwidth.setSuffix("°")
        self.beamwidth.setValue(int(self.prof["beamwidth"]))
        self.beamwidth.setToolTip(tr("Öffnungswinkel deiner Antenne (Halbwertsbreite aus dem "
                                     "Datenblatt) – so breit zeichnet die Karte den Beam-Keil"))
        row = QHBoxLayout()
        row.addWidget(self.beamwidth)
        row.addWidget(QLabel(tr("(Breite des Beam-Keils auf der Karte)")), 1)
        form.addRow(tr("Öffnungswinkel der Antenne:"), row)

        # ---- Erweiterte Einstellungen
        self.adv = QDialog(self)
        self.adv.setWindowTitle(tr("Rotor – erweiterte Einstellungen"))
        self.adv.setMinimumWidth(640)
        al = QVBoxLayout(self.adv)
        box = QGroupBox(tr("rotctld (Verbindung zu Hamlib, auch für andere Programme)"))
        f = QFormLayout(box)
        self.mode = QComboBox()
        self.mode.addItem(tr("GoGoHam startet rotctld selbst (solange GoGoHam läuft)"), "self")
        if self._svc_ok:
            self.mode.addItem(tr("GoGoHam richtet rotctld dauerhaft ein (läuft immer)"), "service")
        self.mode.addItem(tr("Vorhandenen rotctld benutzen (z. B. PstRotator, Systemdienst)"),
                          "external")
        f.addRow(tr("rotctld:"), self.mode)
        self.host = QLineEdit()
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        row = QHBoxLayout()
        row.addWidget(self.host, 1)
        row.addWidget(QLabel(tr("Port:")))
        row.addWidget(self.port)
        f.addRow(tr("rotctld Rechner:"), row)
        al.addWidget(box)
        box = QGroupBox(tr("Für Kenner"))
        f = QFormLayout(box)
        self.extra = QLineEdit()
        self.extra.setPlaceholderText(tr("z. B. --set-conf=min_az=-180,max_az=180"))
        f.addRow(tr("Weitere rotctld-Optionen:"), self.extra)
        al.addWidget(box)
        al.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.button(QDialogButtonBox.StandardButton.Close).setText(tr("Fertig"))
        bb.rejected.connect(self.adv.accept)
        al.addWidget(bb)
        for w in (self.mode,):
            w.currentIndexChanged.connect(lambda _i: self._update_summary())
        self.host.textChanged.connect(lambda _t: self._update_summary())
        self.port.valueChanged.connect(lambda _v: self._update_summary())
        self.extra.textChanged.connect(lambda _t: self._update_summary())

        self.btn_adv = QPushButton(tr("Erweiterte Einstellungen …"))
        self.btn_adv.setToolTip(tr("rotctld-Betriebsart, Rechner/Port, eigene Optionen"))
        self.btn_adv.clicked.connect(self.show_advanced)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color:#888888;")
        row = QHBoxLayout()
        row.addWidget(self.btn_adv)
        row.addWidget(self.summary, 1)
        form.addRow("", row)

        hint = QLabel(tr("Viele Rotor-Steuergeräte (z. B. Yaesu G-450/G-1000, Ham IV) brauchen ein "
                         "Interface für den PC, z. B. Yaesu GS-232B oder ERC – dann dieses Interface "
                         "wählen. Bedienung: Alt+R dreht auf den Short Path zum Rufzeichen, "
                         "Alt+Shift+R auf den Long Path, Alt+S stoppt. Der Test dreht nie."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888888;")
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addStretch(1)
        self._load()

    # ------------------------------------------------------------------ Laden/Speichern
    def _load(self) -> None:
        p = self.prof
        self._loading = True
        mode = p.get("mode") or ("service" if self._svc_ok else "self")   # Standard (0.8.23)
        i = self.mode.findData(mode)
        self.mode.setCurrentIndex(i if i >= 0 else self.mode.findData("self"))
        self.host.setText(p.get("host") or "127.0.0.1")
        self.port.setValue(int(p.get("port") or rt.DEFAULT_PORT))
        self.extra.setText(p.get("extra", ""))
        self._fill_ports(p.get("device", ""))
        self._loading = False
        self._fill_models(p["model"])
        self._model_changed(p.get("baud") or None)
        self._update_summary()

    def current(self) -> dict:
        return {"enabled": self.enabled.isChecked(),
                "model": int(self.model.currentData() or 0),
                "name": (rt.find_model(self.model.currentData() or 0, self.rotors).name
                         if rt.find_model(self.model.currentData() or 0, self.rotors) else ""),
                "device": self.device.currentText().strip(),
                "baud": int(self.baud.currentData() or 0),
                "extra": self.extra.text().strip(),
                "host": self.host.text().strip() or "127.0.0.1",
                "port": self.port.value(),
                "mode": self.mode.currentData() or "self",
                "beamwidth": self.beamwidth.value()}

    def apply(self) -> bool:
        p = self.current()
        if p["enabled"] and not p["model"]:
            self.test_result.setText("✘ " + tr("Bitte zuerst den Rotor bzw. das Interface wählen."))
            self.test_result.setStyleSheet("color:#c62828;")
            return False
        ports = {int(q.get("port") or 0) for q in (self.cfg.get("rig_profiles") or [])}
        if p["enabled"] and p["mode"] != "external" and p["port"] in ports and \
                p["host"] in ("127.0.0.1", "localhost"):
            self.test_result.setText("✘ " + tr("Port {port} benutzt schon ein Funkgerät-Profil – "
                                               "bitte unter „Erweiterte Einstellungen“ einen "
                                               "anderen wählen (Standard 4540).", port=p["port"]))
            self.test_result.setStyleSheet("color:#c62828;")
            return False
        self._offer_handover(p)
        self.cfg["rotor"] = p
        self.cfg["rotor_auto"] = self.auto.isChecked()
        return True

    def _offer_handover(self, new: dict) -> None:
        """0.8.23.5: Fällt der dauerhafte rotctld weg (Rotor aus, andere Betriebsart oder anderer
        Port), fragen, ob er für andere Programme weiterlaufen soll (Standard: ja)."""
        import os
        from PySide6.QtWidgets import QMessageBox
        from .. import rigservice
        old = rt.profile(self.cfg)
        if not (old["enabled"] and old["mode"] == "service"):
            return
        if new["enabled"] and new["mode"] == "service" and int(new["port"]) == old["port"]:
            return
        unit = rt.unit_name(old["port"])
        if not os.path.exists(os.path.join(rigservice.unit_dir(), unit)):
            return
        ans = QMessageBox.question(
            self, tr("rotctld weiterlaufen lassen?"),
            tr("Für den Rotor läuft ein dauerhafter rotctld auf Port {port}. Andere Programme "
               "benutzen ihn vielleicht.\n\nJa: Er läuft als eigenständiger Dienst weiter – "
               "GoGoHam ändert oder entfernt ihn nicht mehr.\nNein: Er wird beendet und "
               "entfernt.", port=old["port"]),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if ans == QMessageBox.StandardButton.Yes:
            errors = rt.handover(old["port"])
            if errors:
                QMessageBox.warning(self, tr("rotctld weiterlaufen lassen?"), "\n".join(errors))

    # ------------------------------------------------------------------ Geräte
    def _fill_models(self, select: int = 0) -> None:
        self._loading = True
        self.model.clear()
        shown = rt.filter_rotors(self.rotors, self.search.text())
        if select and not any(r.model == select for r in shown):
            r = rt.find_model(select, self.rotors)
            if r:
                shown = [r] + shown
        self.model.addItem(tr("– bitte wählen –"), 0)
        for r in shown:
            extra = "  (Beta)" if r.status == "Beta" else ""
            self.model.addItem(f"{r.label}{extra}", r.model)
        i = self.model.findData(select)
        self.model.setCurrentIndex(i if i >= 0 else (1 if self.search.text() and len(shown) else 0))
        self._loading = False
        self._model_changed()

    def _model_changed(self, want_baud=None) -> None:
        if self._loading:
            return
        model = int(self.model.currentData() or 0)
        caps = rt.rotor_caps(model) if model else None
        bauds = caps.bauds() if caps else list(hamlib.STANDARD_BAUDS)
        if want_baud and int(want_baud) not in bauds:
            bauds = sorted(set(bauds) | {int(want_baud)})
        self.baud.clear()
        for b in bauds:
            self.baud.addItem(str(b), b)
        pick = int(want_baud) if want_baud else (caps.speed_max if caps and caps.speed_max
                                                  else bauds[-1])
        i = self.baud.findData(pick)
        self.baud.setCurrentIndex(i if i >= 0 else self.baud.count() - 1)
        serial = caps.serial if caps else True
        self.baud.setEnabled(serial)
        if model and caps:
            parts = [tr("Hamlib-Nr. {model}", model=model),
                     tr("Drehbereich {lo}…{hi}°", lo=int(caps.min_az), hi=int(caps.max_az))]
            if not caps.serial:
                parts.append(tr("über das Netzwerk – „Schnittstelle“ leer lassen oder "
                                "Rechner:Port eintragen"))
            if not caps.can_stop:
                parts.append(tr("kann nicht stoppen"))
            self.info.setText(" · ".join(parts))
        elif self.rotors:
            self.info.setText("")

    def _fill_ports(self, keep: str = "") -> None:
        self.device.clear()
        for p in hamlib.serial_ports():
            self.device.addItem(p)
        if keep and self.device.findText(keep) < 0:
            self.device.addItem(keep)
        self.device.setCurrentText(keep or "")

    # ------------------------------------------------------------------ Test / Erweitert
    def _test(self) -> None:
        p = self.current()
        if not p["model"]:
            self.test_result.setText(tr("Bitte zuerst den Rotor bzw. das Interface wählen."))
            return
        self.test_result.setStyleSheet("")
        self.test_result.setText(tr("Teste … (bis zu 8 Sekunden)"))
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        res = (self.test_fn or rt.test_profile)(p)
        self.test_result.setText(("✔ " if res.ok else "✘ ") + res.text)
        self.test_result.setStyleSheet("color:#1b8a3a;" if res.ok else "color:#c62828;")

    def show_advanced(self) -> None:
        self.adv.adjustSize()
        self.adv.exec()
        self._update_summary()

    def _update_summary(self) -> None:
        parts = []
        mode = self.mode.currentData()
        if mode == "self" and self._svc_ok:
            parts.append(tr("rotctld nur mit GoGoHam"))
        elif mode == "service" and not self._svc_ok:
            parts.append(tr("rotctld dauerhaft"))
        elif mode == "external":
            parts.append(tr("vorhandener rotctld"))
        if self.extra.text().strip():
            parts.append(tr("eigene Optionen"))
        host = self.host.text().strip() or "127.0.0.1"
        net = tr("Andere Programme: „Hamlib NET rotctl“ mit {addr}",
                 addr=f"{host}:{self.port.value()}")
        self.summary.setText((tr("Erweitert: {list}", list=", ".join(parts)) if parts
                              else tr("Erweitert: alles Standard")) + "\n" + net)
