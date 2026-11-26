"""Einstellungsbereich „USB-Stick“ (ab 0.10.8) – nur sichtbar, wenn GoGoHam vom Live-Stick läuft."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QGroupBox, QLabel, QMessageBox,
                               QPushButton, QVBoxLayout)

from .. import livestick as ls
from .. import stickcopy
from ..i18n import tr


class StickPage(QDialog):
    def __init__(self, cfg: dict, parent=None, actions: dict | None = None):
        super().__init__(parent)
        self.cfg = cfg
        self.actions = actions or {}
        lay = QVBoxLayout(self)
        intro = QLabel(tr("GoGoHam läuft von einem USB-Stick. Logs, Einstellungen und "
                          "nachinstallierte Programme bleiben auf dem Stick – auch wenn du ihn "
                          "an einem anderen Rechner startest."))
        intro.setWordWrap(True)
        lay.addWidget(intro)

        box = QGroupBox(tr("Platz auf dem Stick"))
        form = QFormLayout(box)
        self.lbl_data = QLabel()
        self.lbl_exch = QLabel()
        form.addRow(tr("Daten (Logs, Einstellungen, Programme):"), self.lbl_data)
        form.addRow(tr("Austausch-Ordner:"), self.lbl_exch)
        lay.addWidget(box)

        box = QGroupBox(tr("Austausch-Ordner"))
        bl = QVBoxLayout(box)
        hint = QLabel(tr("Diesen Ordner kann auch Windows lesen: Stick an einen Windows-PC stecken, "
                         "dann erscheint er dort als eigenes Laufwerk. So kommen Cabrillo- und "
                         "ADIF-Dateien leicht auf einen anderen Rechner."))
        hint.setWordWrap(True)
        bl.addWidget(hint)
        self.btn_open = QPushButton(tr("Austausch-Ordner öffnen"))
        self.btn_open.clicked.connect(self._open_exchange)
        bl.addWidget(self.btn_open)
        self.chk_backup = QCheckBox(tr("Logs auch in den Austausch-Ordner sichern"))
        self.chk_backup.setToolTip(tr("Bei jeder Sicherung legt GoGoHam eine Kopie des Logs als "
                                      "ADIF und als GoGoHam-Datei in den Ordner „{folder}“. Geht "
                                      "der Datenteil einmal kaputt, sind die Logs dort noch da.",
                                      folder=ls.BACKUP_FOLDER))
        self.chk_backup.setChecked(bool(cfg.get("stick_backup", True)))
        bl.addWidget(self.chk_backup)
        lay.addWidget(box)

        box = QGroupBox(tr("Uhrzeit"))
        bl = QVBoxLayout(box)
        self.btn_clock = QPushButton(tr("Uhrzeit stellen …"))
        self.btn_clock.setToolTip(tr("Wenn kein Internet da ist, kann Linux die Uhr nicht selbst "
                                     "stellen – dann hier von Hand."))
        # Herunterfahren: seit 0.10.20 unter Datei → Beenden und herunterfahren
        for b, key in ((self.btn_clock, "clock_set"),):
            if key in self.actions:
                b.clicked.connect(self.actions[key])
            else:
                b.setEnabled(False)
            bl.addWidget(b)
        lay.addWidget(box)

        # 0.10.20: Neuen Stick erstellen (z. B. für einen Funkfreund)
        box = QGroupBox(tr("Stick weitergeben"))
        bl = QVBoxLayout(box)
        hint = QLabel(tr("Macht aus einem anderen USB-Stick (ab 16 GB) einen frischen "
                         "GoGoHam-Stick – ohne Internet und ohne deine Logs und Einstellungen."))
        hint.setWordWrap(True)
        bl.addWidget(hint)
        self.btn_copy = QPushButton(tr("Neuen Stick erstellen …"))
        if stickcopy.available():
            self.btn_copy.clicked.connect(self._new_stick)
        else:
            self.btn_copy.setEnabled(False)
            self.btn_copy.setToolTip(tr("Geht erst mit einem Stick ab GoGoHam 0.10.20."))
        bl.addWidget(self.btn_copy)
        lay.addWidget(box)

        box = QGroupBox(tr("Werkseinstellungen"))
        bl = QVBoxLayout(box)
        hint = QLabel(tr("Löscht alle Logs, Einstellungen und nachinstallierten Programme auf dem "
                         "Stick. Danach ist er wie neu. Der Austausch-Ordner bleibt erhalten."))
        hint.setWordWrap(True)
        bl.addWidget(hint)
        self.btn_reset = QPushButton(tr("Stick auf Werkseinstellungen zurücksetzen …"))
        if "stick_reset" in self.actions and ls.reset_command():
            self.btn_reset.clicked.connect(self.actions["stick_reset"])
        else:
            self.btn_reset.setEnabled(False)
        bl.addWidget(self.btn_reset)
        lay.addWidget(box)
        lay.addStretch(1)
        self.refresh()

    def showEvent(self, e):  # noqa: N802 – Platz bei jedem Anzeigen neu lesen
        self.refresh()
        super().showEvent(e)

    def refresh(self) -> None:
        for lbl, path in ((self.lbl_data, ls.data_dir()), (self.lbl_exch, ls.exchange_dir())):
            sp = ls.space(path)
            lbl.setText(ls.space_text(sp))
            low = sp is not None and ls.is_low(*sp)
            lbl.setStyleSheet("color: #c0392b; font-weight: bold;" if low else "")
        self.btn_open.setEnabled(ls.exchange_dir() is not None)

    def _open_exchange(self) -> None:
        d = ls.exchange_dir()
        if d is None:
            QMessageBox.warning(self, tr("USB-Stick"), tr("Der Austausch-Ordner ist nicht da."))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def _new_stick(self) -> None:
        from .stick_copy import StickCopyDialog
        StickCopyDialog(self).exec()

    def apply(self) -> bool:
        self.cfg["stick_backup"] = self.chk_backup.isChecked()
        return True
