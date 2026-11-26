"""Fenster „GoGoHam aktualisieren“ auf dem Live-Stick (ab 0.10.24).

Ein Klick sucht in der GoGoHam-Paketquelle nach einer neueren Version und spielt sie in den
Datenteil des Sticks ein (siehe gogoham/stickupdate.py). Danach startet GoGoHam neu – das
geöffnete Log wird gespeichert und wieder geöffnet. „Zurück zur Fassung des Sticks“ löscht
alle eingespielten Updates.
"""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QMessageBox, QPushButton,
                               QVBoxLayout)

from .. import __version__, stickupdate
from ..i18n import tr


class _Bridge(QObject):
    progress = Signal(str)
    done = Signal(object)


class StickUpdateDialog(QDialog):
    def __init__(self, parent=None, installer=None):
        super().__init__(parent)
        self.setWindowTitle(tr("GoGoHam aktualisieren"))
        self._install = installer or stickupdate.install
        self.restart_wanted = False
        self.result = None
        lay = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.btn_update = QPushButton(tr("Nach neuer Version suchen und aktualisieren"))
        self.btn_update.clicked.connect(self.start)
        lay.addWidget(self.btn_update)
        self.btn_back = QPushButton(tr("Zurück zur Fassung des Sticks"))
        self.btn_back.setToolTip(tr("Löscht alle eingespielten Updates – nach dem Neustart läuft "
                                    "wieder die Version, die auf dem Stick mitgeliefert wurde."))
        self.btn_back.clicked.connect(self.back)
        lay.addWidget(self.btn_back)
        self.btn_restart = QPushButton(tr("GoGoHam jetzt neu starten"))
        self.btn_restart.clicked.connect(self._restart)
        self.btn_restart.hide()
        lay.addWidget(self.btn_restart)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self._bridge = _Bridge()
        self._bridge.progress.connect(self.status.setText)
        self._bridge.done.connect(self._finished)
        self._show_state()

    def _show_state(self) -> None:
        running = os.environ.get(stickupdate.ENV_ACTIVE)
        ups = stickupdate.installed_updates()
        if running:
            text = tr("Es läuft GoGoHam {v} – eingespielt per Aktualisieren.", v=__version__)
        else:
            text = tr("Es läuft GoGoHam {v} – die Version, die auf dem Stick mitgeliefert wurde.",
                      v=__version__)
        text += "\n" + tr("Neue Versionen kommen aus der GoGoHam-Paketquelle; dafür braucht der "
                          "Rechner Internet. Logs und Einstellungen bleiben erhalten.")
        self.info.setText(text)
        self.btn_back.setVisible(bool(ups) or bool(running))

    def start(self) -> None:
        self.btn_update.setEnabled(False)
        self.btn_back.setEnabled(False)
        self.status.setText(tr("Bitte warten …"))

        def work():
            try:
                res = self._install(progress=self._bridge.progress.emit)
            except Exception as e:  # noqa: BLE001
                res = stickupdate.Result(message=tr("Aktualisieren fehlgeschlagen: {e}", e=e))
            self._bridge.done.emit(res)
        threading.Thread(target=work, daemon=True).start()

    def _finished(self, res) -> None:
        self.result = res
        self.status.setText(res.message)
        self.btn_update.setEnabled(True)
        self.btn_back.setEnabled(True)
        if res.ok and res.version and stickupdate.newer(res.version, __version__):
            self.btn_update.hide()
            self.btn_restart.show()
        self._show_state()

    def back(self) -> None:
        ans = QMessageBox.question(self, tr("Zurück zur Fassung des Sticks"), tr(
            "Alle eingespielten Updates löschen? Nach dem Neustart läuft wieder die Version, "
            "die auf dem Stick mitgeliefert wurde. Logs und Einstellungen bleiben erhalten."))
        if ans != QMessageBox.StandardButton.Yes:
            return
        stickupdate.remove_all(protect=os.environ.get(stickupdate.ENV_ACTIVE))
        self.status.setText(tr("Updates gelöscht."))
        if os.environ.get(stickupdate.ENV_ACTIVE):
            self.btn_update.hide()
            self.btn_restart.show()
        self._show_state()

    def _restart(self) -> None:
        self.restart_wanted = True
        self.accept()
