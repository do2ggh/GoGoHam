"""Fenster „Neuen Stick erstellen“ (ab 0.10.20) – nur auf dem Live-Stick.

Der laufende Stick schreibt sein System auf einen anderen USB-Stick (frisch, ohne deine Daten).
Die Logik steckt in stickcopy.py, das Schreiben im Hilfsprogramm des Sticks (über pkexec).
"""

from __future__ import annotations

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMessageBox, QProgressBar, QPushButton, QVBoxLayout)

from .. import livestick, stickcopy
from ..i18n import tr


class StickCopyDialog(QDialog):
    # für Tests austauschbar
    scan = staticmethod(stickcopy.usb_sticks)
    make_command = staticmethod(stickcopy.command)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Neuen Stick erstellen"))
        self.resize(640, 440)
        self.sticks: list[stickcopy.Stick] = []
        self.proc: QProcess | None = None
        self._buf = ""
        self._error: tuple[str, str] | None = None
        self._speed: tuple[int, int] | None = None
        self._done = False
        self._target: stickcopy.Stick | None = None

        lay = QVBoxLayout(self)
        intro = QLabel(tr(
            "Macht aus einem anderen USB-Stick einen GoGoHam-Stick – zum Beispiel für einen "
            "Funkfreund. Der neue Stick ist <b>frisch</b>: Deine Logs, Einstellungen und "
            "Passwörter kommen nicht mit. Er bekommt dieselbe GoGoHam-Version wie dieser Stick.<br>"
            "<b>Alles, was auf dem gewählten Stick ist, wird gelöscht.</b> Er braucht mindestens "
            "16 GB; ein USB-3-Stick an einem USB-3-Anschluss ist deutlich schneller."))
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(intro)

        lay.addWidget(QLabel(tr("Angesteckte USB-Sticks (der Stick, von dem GoGoHam läuft, steht "
                                "nicht dabei):")))
        self.list = QListWidget()
        self.list.currentRowChanged.connect(lambda _r: self._update())
        lay.addWidget(self.list, 1)
        self.lbl_none = QLabel(tr("Kein weiterer USB-Stick gefunden – bitte den neuen Stick "
                                  "einstecken."))
        self.lbl_none.setStyleSheet("color: gray;")
        lay.addWidget(self.lbl_none)

        self.lbl_step = QLabel("")
        self.lbl_step.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFormat("%p %")
        self.lbl_step.hide()
        self.bar.hide()
        lay.addWidget(self.lbl_step)
        lay.addWidget(self.bar)

        row = QHBoxLayout()
        self.btn_scan = QPushButton(tr("Neu suchen"))
        self.btn_scan.clicked.connect(lambda: self.refresh(force=True))
        self.btn_go = QPushButton(tr("Stick erstellen …"))
        self.btn_go.clicked.connect(self.start)
        self.btn_close = QPushButton(tr("Schließen"))
        self.btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_scan)
        row.addStretch(1)
        row.addWidget(self.btn_go)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

        # neu eingesteckte Sticks von selbst zeigen
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    # ------------------------------------------------------------ Auswahl
    def refresh(self, force: bool = False) -> None:
        if self.running():
            return
        keep = self.current().key() if self.current() else None
        sticks = self.scan()
        if not force and [s.key() for s in sticks] == [s.key() for s in self.sticks] and \
                [s.labels for s in sticks] == [s.labels for s in self.sticks]:
            return
        self.sticks = sticks
        self.list.clear()
        row = -1
        for i, s in enumerate(sticks):
            it = QListWidgetItem(stickcopy.describe(s))
            if not s.fits:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.list.addItem(it)
            if s.key() == keep:
                row = i
        if row < 0:
            usable = [i for i, s in enumerate(sticks) if s.fits]
            row = usable[0] if len(usable) == 1 else -1
        self.list.setCurrentRow(row)
        self._update()

    def current(self) -> stickcopy.Stick | None:
        r = self.list.currentRow() if hasattr(self, "list") else -1
        return self.sticks[r] if 0 <= r < len(self.sticks) else None

    def running(self) -> bool:
        return self.proc is not None

    def _update(self) -> None:
        s = self.current()
        busy = self.running()
        self.lbl_none.setVisible(not self.sticks and not busy)
        self.btn_go.setEnabled(not busy and s is not None and s.fits)
        self.btn_scan.setEnabled(not busy)
        self.btn_close.setEnabled(not busy)
        self.list.setEnabled(not busy)

    # ------------------------------------------------------------ Schreiben
    def ask(self, s: stickcopy.Stick) -> bool:
        box = QMessageBox(QMessageBox.Icon.Warning, tr("Neuen Stick erstellen"), tr(
            "<b>Alles auf diesem Stick wird gelöscht:</b><br><br>{stick}<br><br>"
            "Danach: System bis 8 GB · Datenteil {data} · Austausch-Ordner {exch}.<br>"
            "Das dauert je nach Stick 5 bis 15 Minuten. Währenddessen den Stick nicht abziehen.",
            stick=stickcopy.describe(s), data=livestick.size_text(stickcopy.data_size(s.size)),
            exch=livestick.size_text(stickcopy.exchange_size(s.size))), parent=self)
        box.setTextFormat(Qt.TextFormat.RichText)
        go = box.addButton(tr("Alles löschen und Stick erstellen"),
                           QMessageBox.ButtonRole.DestructiveRole)
        no = box.addButton(tr("Abbrechen"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(no)                       # Enter bricht ab
        box.setEscapeButton(no)
        box.exec()
        return box.clickedButton() is go

    def tell(self, title: str, text: str, warn: bool = False) -> None:
        (QMessageBox.warning if warn else QMessageBox.information)(self, title, text)

    def start(self) -> None:
        s = self.current()
        if s is None or not s.fits or self.running():
            return
        if not self.ask(s):
            return
        # noch derselbe Stick an derselben Stelle?
        now = {x.key(): x for x in self.scan()}
        if s.key() not in now:
            self.tell(tr("Neuen Stick erstellen"),
                      tr("Der Stick ist nicht mehr da – bitte noch einmal auswählen."), warn=True)
            self.refresh(force=True)
            return
        cmd = self.make_command(s.path)
        if cmd is None:
            self.tell(tr("Neuen Stick erstellen"),
                      tr("Das geht nur auf einem GoGoHam-Stick ab Version 0.10.20."), warn=True)
            return
        from .. import applog
        applog.message(f"Neuen Stick erstellen: {s.path} ({s.name}, {s.size} Byte)")
        self._target, self._error, self._speed, self._done, self._buf = s, None, None, False, ""
        self.lbl_step.setText(stickcopy.step_text("aushaengen"))
        self.lbl_step.show()
        self.bar.setValue(0)
        self.bar.show()
        proc = self.proc = QProcess(self)
        proc.readyReadStandardOutput.connect(self._read)
        proc.finished.connect(self._finished)
        proc.errorOccurred.connect(lambda _e: self._finished(-1))
        self._update()
        proc.start(cmd[0], cmd[1:])

    def _read(self) -> None:
        if self.proc is None:
            return
        self._buf += bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        *lines, self._buf = self._buf.split("\n")
        for ln in lines:
            self.handle(ln)

    def handle(self, line: str) -> None:
        ev = stickcopy.parse(line)
        if ev is None:
            return
        if ev[0] == "step":
            self.lbl_step.setText(stickcopy.step_text(ev[1]))
            if ev[1] in ("pruefen", "aufteilen", "einrichten"):
                self.bar.setValue(max(self.bar.value(), {"pruefen": 900, "aufteilen": 960,
                                                         "einrichten": 980}[ev[1]]))
            if ev[1] == "fertig":
                self._done = True
                self.bar.setValue(1000)
        elif ev[0] == "progress" and ev[2] > 0:
            self.bar.setValue(int(900 * min(ev[1], ev[2]) / ev[2]))   # Schreiben = 90 %
        elif ev[0] == "speed":
            self._speed = (ev[1], ev[2])
        elif ev[0] == "error":
            self._error = (ev[1], ev[2])

    def _finished(self, code: int, _status=None) -> None:
        if self.proc is None:
            return
        self._read()
        if self._buf:
            self.handle(self._buf)
            self._buf = ""
        err = bytes(self.proc.readAllStandardError()).decode(errors="replace").strip()
        self.proc.deleteLater()
        self.proc = None
        from .. import applog
        title = tr("Neuen Stick erstellen")
        if code == 0 and self._done and self._error is None:
            applog.message(f"Neuer Stick fertig, Tempo {self._speed}")
            text = tr("Der neue GoGoHam-Stick ist fertig und kann jetzt abgezogen werden.")
            if self._speed:
                mb, small = self._speed
                text += "\n\n" + tr("Schreibtempo dieses Sticks: {mb} MB/s, kleine Blöcke: "
                                    "{small} pro Sekunde.", mb=mb, small=small)
                if stickcopy.is_slow(mb, small):
                    text += "\n\n" + tr(
                        "Dieser Stick ist langsam. GoGoHam läuft darauf, aber der erste Start "
                        "und Installationen (z. B. fldigi) dauern deutlich länger – an einem "
                        "USB-2-Anschluss noch einmal mehr. Empfohlen: ein USB-3-Stick an einem "
                        "USB-3-Anschluss.")
            self.lbl_step.setText(stickcopy.step_text("fertig"))
            self.tell(title, text)
        else:
            if self._error:
                why = stickcopy.error_text(*self._error)
            elif code in (126, 127):
                why = tr("Abgebrochen – keine Berechtigung.")
            else:
                why = (err.splitlines() or [tr("unbekannter Fehler ({code})", code=code)])[-1]
            applog.message(f"Neuer Stick fehlgeschlagen ({code}): {self._error} {err[-300:]}",
                           "warn")
            self.lbl_step.setText(tr("Nicht fertig geworden."))
            self.tell(title, tr("Der Stick ist nicht fertig geworden: {why}\n\nAuf dem Stick ist "
                                "jetzt kein brauchbares System – einfach noch einmal versuchen.",
                                why=why) if self._target else why, warn=True)
        self.refresh(force=True)             # Liste neu aufbauen (Inhalt hat sich geändert)
        self._update()

    # ------------------------------------------------------------ nicht mitten drin schließen
    def reject(self) -> None:
        if self.running():
            return
        self.timer.stop()
        super().reject()

    def closeEvent(self, e):  # noqa: N802 (Qt-Name)
        if self.running():
            e.ignore()
            return
        self.timer.stop()
        super().closeEvent(e)
