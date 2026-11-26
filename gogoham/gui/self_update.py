"""Fenster „GoGoHam aktualisieren“ für die Installation mit install.sh (ab 0.10.47).

Ein Klick holt die neueste Version von GitHub, prüft sie und legt sie bereit (siehe
gogoham/selfupdate.py). Beim Neustart wird sie eingespielt – das geöffnete Log wird gespeichert
und wieder geöffnet. „Zurück zur vorigen Version“ tauscht beim Neustart zurück.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QMessageBox, QPushButton,
                               QVBoxLayout)

from .. import __version__, selfupdate, versioncheck
from ..i18n import tr


class _Bridge(QObject):
    progress = Signal(str)
    done = Signal(object)


def _check_and_prepare(progress=None, latest=None, prepare=None) -> selfupdate.Result:
    """Neueste Versionsmarke holen; ist sie neuer, vorbereiten."""
    latest = latest or versioncheck.latest
    prepare = prepare or selfupdate.prepare
    if progress:
        progress(tr("Suche nach einer neuen Version …"))
    try:
        v = latest()
    except OSError as e:
        return selfupdate.Result(False, "", tr("GitHub ist nicht erreichbar – bitte später noch "
                                               "einmal versuchen.\n\n{err}", err=e))
    if not v or not versioncheck.is_newer(v):
        return selfupdate.Result(True, "", tr("Du hast die neueste Version ({v}).", v=__version__))
    return prepare(v, progress=progress)


class SelfUpdateDialog(QDialog):
    def __init__(self, parent=None, worker=None):
        super().__init__(parent)
        self.setWindowTitle(tr("GoGoHam aktualisieren"))
        self._work = worker or _check_and_prepare
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
        self.btn_back = QPushButton(tr("Zurück zur vorigen Version"))
        self.btn_back.setToolTip(tr("Beim Neustart läuft wieder die Version, die vor dem "
                                    "letzten Aktualisieren installiert war."))
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
        text = tr("Es läuft GoGoHam {v}.", v=__version__) + "\n" + tr(
            "Neue Versionen kommen von GitHub; dafür braucht der Rechner Internet. Die neue "
            "Version wird vorher zur Probe geladen – fehlt dem Rechner etwas, bleibt alles, wie "
            "es ist. Logs und Einstellungen bleiben erhalten.")
        job = selfupdate.pending()
        if job and job.get("action") == "install":
            text += "\n\n" + tr("Bereit zum Einspielen beim nächsten Start: {v}.",
                                v=job.get("version", "?"))
        elif job:
            text += "\n\n" + tr("Beim nächsten Start geht es zurück zur vorigen Version.")
        self.info.setText(text)
        self.btn_back.setVisible(selfupdate.has_previous() and not job)

    def start(self) -> None:
        self.btn_update.setEnabled(False)
        self.btn_back.setEnabled(False)
        self.status.setText(tr("Bitte warten …"))

        def work():
            try:
                res = self._work(progress=self._bridge.progress.emit)
            except Exception as e:  # noqa: BLE001
                res = selfupdate.Result(False, "", tr("Aktualisieren fehlgeschlagen: {e}", e=e))
            self._bridge.done.emit(res)
        threading.Thread(target=work, daemon=True).start()

    def _finished(self, res) -> None:
        self.result = res
        self.status.setText(res.message)
        self.btn_update.setEnabled(True)
        self.btn_back.setEnabled(True)
        if res.ok and res.version:
            self.btn_update.hide()
            self.btn_restart.show()
        self._show_state()

    def back(self) -> None:
        ans = QMessageBox.question(self, tr("Zurück zur vorigen Version"), tr(
            "Beim Neustart wieder die Version starten, die vor dem letzten Aktualisieren "
            "installiert war? Logs und Einstellungen bleiben erhalten."))
        if ans != QMessageBox.StandardButton.Yes:
            return
        selfupdate.request_rollback()
        self.status.setText(tr("Wird beim Neustart zurückgetauscht."))
        self.btn_update.hide()
        self.btn_restart.show()
        self._show_state()

    def _restart(self) -> None:
        self.restart_wanted = True
        self.accept()
