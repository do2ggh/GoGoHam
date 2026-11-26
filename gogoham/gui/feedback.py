"""Rückmeldung (ab 0.8.18.3): Kontakt zu DO2GGH, Fehlerbericht und Uhrzeit-Prüfung."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog, QLabel,
                               QMessageBox, QPlainTextEdit, QVBoxLayout)

from .. import CONTACT_EMAIL, applog, bugreport
from .. import livestick
from .. import clockcheck as ck
from ..i18n import num, tr


def _open_mail(parent, url: str) -> None:
    """E-Mail-Programm öffnen; klappt das nicht, die Adresse zum Kopieren zeigen."""
    from .. import mailopen
    if not mailopen.open_mail(url, mailopen.qt_open):
        box = QMessageBox(QMessageBox.Icon.Information, tr("Kontakt zu DO2GGH"),
                          tr("Es ließ sich kein E-Mail-Programm öffnen. Bitte schreib an:\n\n{mail}",
                             mail=CONTACT_EMAIL), parent=parent)
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.exec()


def open_contact(parent, call: str = "") -> None:
    _open_mail(parent, bugreport.mailto(bugreport.subject(tr("Rückmeldung"), call)))


class BugReportDialog(QDialog):
    """Bericht zeigen; speichern, kopieren oder per E-Mail an DO2GGH."""

    def __init__(self, cfg: dict, call: str = "", parent=None):
        super().__init__(parent)
        self.call = call
        self.setWindowTitle(tr("Fehlerbericht"))
        self.resize(820, 600)
        self.report = bugreport.build(cfg)
        v = QVBoxLayout(self)
        info = QLabel(tr("Das steht im Bericht. Passwörter und deine QSOs sind <b>nicht</b> "
                         "dabei. Schreib unten in die E-Mail kurz, was du gemacht hast und was "
                         "passiert ist."))
        info.setWordWrap(True)
        v.addWidget(info)
        self.text = QPlainTextEdit(self.report)
        self.text.setReadOnly(True)
        self.text.setFont(QFont("monospace"))
        v.addWidget(self.text)
        bb = QDialogButtonBox()
        self.btn_mail = bb.addButton(tr("E-Mail an DO2GGH …"), QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_save = bb.addButton(tr("Als Datei speichern …"), QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_copy = bb.addButton(tr("Kopieren"), QDialogButtonBox.ButtonRole.ActionRole)
        bb.addButton(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        self.btn_mail.clicked.connect(self.send_mail)
        self.btn_save.clicked.connect(self.save_as)
        self.btn_copy.clicked.connect(self.copy)
        v.addWidget(bb)

    def write(self, path: Path) -> bool:
        try:
            path.write_text(self.report + "\n", encoding="utf-8")
            return True
        except OSError as e:
            QMessageBox.warning(self, tr("Fehlerbericht"),
                                tr("Konnte die Datei nicht speichern: {e}", e=e))
            return False

    def save_as(self) -> None:
        name, _f = QFileDialog.getSaveFileName(self, tr("Fehlerbericht speichern"),
                                               str(Path.home() / bugreport.file_name()),
                                               tr("Textdateien (*.txt)"))
        if name and self.write(Path(name)):
            self.btn_save.setText(tr("Gespeichert ✓"))

    def copy(self) -> None:
        QApplication.clipboard().setText(self.report)
        self.btn_copy.setText(tr("Kopiert ✓"))

    def send_mail(self) -> None:
        """Bericht im persönlichen Ordner ablegen und eine E-Mail mit Hinweis darauf öffnen."""
        path = Path.home() / bugreport.file_name()
        if not self.write(path):
            return
        body = tr("Was ist passiert?\n\n\n\nBitte die Datei anhängen: {path}\n", path=path)
        _open_mail(self, bugreport.mailto(bugreport.subject(tr("Fehlerbericht"), self.call), body))
        QMessageBox.information(self, tr("Fehlerbericht"),
                                tr("Der Bericht liegt jetzt hier:\n{path}\n\nBitte häng diese Datei "
                                   "an die E-Mail an.", path=path))


class ClockWatch(QObject):
    """Prüft die Uhr beim Start und dann stündlich; bietet „Synchronisieren“ an."""

    def __init__(self, window, first_delay_s: float = 8.0):
        super().__init__(window)
        self.win = window
        self.checker: ck.Checker | None = None
        self.next_at = time.monotonic() + first_delay_s
        self.asked = False               # Rückfrage nur einmal je Programmlauf von selbst
        self.manual = False              # über das Menü angestoßen → immer antworten
        self.after_sync = False
        self.proc: QProcess | None = None
        self.last: float | None = None
        self.unsynced_hint = ""          # Stick ohne Internet: Text des ruhigen Hinweises (0.10.10)

    # wird aus dem langsamen Takt des Hauptfensters aufgerufen
    def tick(self) -> None:
        c = self.checker
        if c is not None and not c.is_alive():
            self.checker = None
            self._result(c.result)
        if self.checker is None and self.proc is None and time.monotonic() >= self.next_at:
            self.start()

    def start(self, manual: bool = False) -> None:
        self.manual = self.manual or manual
        self.next_at = time.monotonic() + ck.INTERVAL_S
        if self.checker is None:
            self.checker = ck.Checker()
            self.checker.start()

    def check_now(self) -> None:
        """Menü „Uhrzeit prüfen“."""
        self.win.statusBar().showMessage(tr("Prüfe die Uhrzeit …"), 5000)
        self.start(manual=True)
        QTimer.singleShot(3500, self.tick)

    def _result(self, off: float | None) -> None:
        manual, after, self.manual, self.after_sync = self.manual, self.after_sync, False, False
        self.last = off
        sb = self.win.statusBar()
        if off is None:
            if livestick.is_live():
                if livestick.clock_synced() is True:
                    self._clear_unsynced()          # Linux hat inzwischen selbst abgeglichen
                else:
                    self._stick_unsynced(manual)    # Stick ohne Internet (0.10.8, ruhig ab 0.10.10)
                    return
            if manual or after:
                sb.showMessage(tr("Uhrzeit: kein Zeitserver erreichbar (Internet?)"), 10000, level="warn")
            return
        applog.message(f"Uhr-Abweichung {off:+.2f} s")
        if not ck.is_wrong(off):
            self._clear_unsynced()
        if not ck.is_wrong(off):
            if manual or after:
                sign = "+" if off >= 0 else "−"
                sb.showMessage(tr("Uhrzeit stimmt (Abweichung {s} s) ✓", s=sign + num(abs(off), 1)),
                               10000)
            return
        if after:
            sb.showMessage(tr("Die Uhr geht immer noch falsch ({off}). Bitte über das Menü Station → "
                              "„Uhrzeit prüfen …“ noch einmal versuchen.", off=ck.describe(off)),
                           0, level="error")
            return
        sb.showMessage(ck.describe(off) + " " + tr("Das ist fürs Log wichtig – Menü Station → "
                                                   "„Uhrzeit prüfen …“"), 0, level="warn")
        if manual or not self.asked:
            self.asked = True
            self.ask(off)

    def _stick_unsynced(self, manual: bool) -> None:
        """Live-Stick, kein Zeitserver: GoGoHam nimmt die Uhr des Rechners. Der Stick liest sie
        passend zum Rechner (Windows: Ortszeit, sonst UTC) und zur Zeitzone aus dem Locator –
        also nur ein ruhiger Hinweis (0.10.10). Rückfrage nur über das Menü."""
        text = tr("Uhrzeit vom Rechner übernommen (noch nicht mit dem Internet abgeglichen) – "
                  "bitte einmal mit dem Handy vergleichen (UTC oben rechts).")
        if not self.unsynced_hint:
            self.unsynced_hint = text
            self.win.statusBar().showMessage(text, 0)
        self.next_at = time.monotonic() + 120     # bald wieder schauen, ob Internet da ist
        if not manual:
            return
        self.asked = True
        from PySide6.QtCore import QDateTime
        box = QMessageBox(self.win)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("Uhrzeit"))
        now = QDateTime.currentDateTimeUtc().toString("HH:mm")
        box.setText(tr("Die Uhrzeit konnte nicht mit einem Zeitserver abgeglichen werden "
                       "(kein Internet?).\n\nDer Rechner zeigt jetzt {now} UTC. An fremden "
                       "Rechnern geht die Uhr oft eine oder zwei Stunden falsch – bitte mit "
                       "einer Funkuhr oder dem Handy vergleichen.", now=now))
        set_btn = box.addButton(tr("Uhr stellen …"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Stimmt so"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(set_btn)
        box.exec()
        if box.clickedButton() is set_btn:
            self.set_manually()

    def _clear_unsynced(self) -> None:
        """Abgeglichen: den ruhigen Hinweis wieder wegnehmen."""
        if not self.unsynced_hint:
            return
        sb = self.win.statusBar()
        if sb.currentMessage() == self.unsynced_hint:
            sb.clearMessage()
        self.unsynced_hint = ""
        sb.showMessage(tr("Uhrzeit mit dem Internet abgeglichen ✓"), 10000)

    def set_manually(self) -> None:
        """Uhr von Hand stellen (UTC) – nur die Systemuhr, die eingebaute bleibt."""
        from PySide6.QtCore import QDateTime, QTimeZone
        from PySide6.QtWidgets import QDateTimeEdit
        dlg = QDialog(self.win)
        dlg.setWindowTitle(tr("Uhr stellen"))
        dlg.setMinimumWidth(460)
        lay = QVBoxLayout(dlg)
        lbl = QLabel(tr("Bitte die richtige Zeit in UTC eintragen (z. B. von Funkuhr, Handy oder "
                        "Zeitzeichensender). Achtung: UTC, nicht die Ortszeit."))
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        edit = QDateTimeEdit(QDateTime.currentDateTimeUtc())
        edit.setTimeZone(QTimeZone.utc())
        edit.setDisplayFormat("yyyy-MM-dd  HH:mm:ss  'UTC'")
        f = edit.font()
        f.setPointSize(f.pointSize() + 4)
        edit.setFont(f)
        lay.addWidget(edit)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Uhr stellen"))
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if not dlg.exec():
            return
        cmd = livestick.set_time_command(edit.dateTime().toSecsSinceEpoch())
        if not cmd:
            QMessageBox.warning(self.win, tr("Uhr stellen"),
                                tr("Uhr stellen geht hier nicht (pkexec fehlt)."))
            return
        applog.message("Uhr von Hand stellen: " + cmd[-1])
        proc = QProcess(self)
        proc.finished.connect(lambda code, _s: self._manual_done(proc, code))
        proc.start(cmd[0], cmd[1:])

    def _manual_done(self, proc: QProcess, code: int) -> None:
        err = bytes(proc.readAllStandardError()).decode(errors="replace").strip()
        proc.deleteLater()
        from PySide6.QtCore import QDateTime
        sb = self.win.statusBar()
        if code != 0:
            applog.message(f"Uhr von Hand stellen fehlgeschlagen ({code}): {err}", "warn")
            sb.showMessage(tr("Uhr stellen ging nicht: {e}", e=err or code), 15000, level="warn")
            return
        sb.showMessage(tr("Uhr gestellt: {t} UTC ✓",
                          t=QDateTime.currentDateTimeUtc().toString("HH:mm:ss")), 10000)

    def ask(self, off: float) -> None:
        cmd = ck.sync_command()
        box = QMessageBox(self.win)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("Uhrzeit"))
        text = ck.describe(off) + "\n\n" + tr(
            "Für den Contest muss die Zeit stimmen – falsche Zeiten im Log kosten Punkte, und "
            "FT8/FT4 klappt dann nicht.")
        if cmd:
            box.setText(text + "\n\n" + tr("„Synchronisieren“ stellt die Uhr nach einem Zeitserver "
                                           "und lässt sie künftig von Linux selbst stellen. Dafür "
                                           "fragt Linux einmal nach deinem Passwort."))
            sync = box.addButton(tr("Synchronisieren"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(tr("Später"), QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(sync)
            box.exec()
            if box.clickedButton() is sync:
                self.sync(cmd)
            return
        manual_cmd = ck.manual_commands()
        if manual_cmd:
            box.setText(text + "\n\n" + tr("Mit diesem Befehl im Terminal stellt Linux die Uhr "
                                           "(fragt nach deinem Passwort):"))
            box.setInformativeText(manual_cmd)
        else:
            box.setText(text + "\n\n" + tr("Bitte die Uhr in den Systemeinstellungen stellen "
                                           "(„Zeit automatisch einstellen“)."))
        box.exec()

    def sync(self, cmd: list[str]) -> None:
        applog.message("Uhr stellen: " + " ".join(cmd[:1] + cmd[3:]))
        self.win.statusBar().showMessage(tr("Stelle die Uhr … (Linux fragt nach dem Passwort)"), 0)
        self.proc = QProcess(self)
        self.proc.finished.connect(self._sync_done)
        self.proc.errorOccurred.connect(lambda _e: self._sync_done(-1, None))
        self.proc.start(cmd[0], cmd[1:])

    def _sync_done(self, code: int, _status) -> None:
        if self.proc is None:
            return
        err = bytes(self.proc.readAllStandardError()).decode(errors="replace").strip()
        self.proc.deleteLater()
        self.proc = None
        if code != 0:
            applog.message(f"Uhr stellen fehlgeschlagen ({code}): {err}", "warn")
            msg = tr("Abgebrochen – kein Passwort eingegeben.") if code in (126, 127) else \
                tr("Uhr stellen ging nicht: {e}", e=err or code)
            self.win.statusBar().showMessage(msg, 15000, level="warn")
            return
        self.win.statusBar().showMessage(tr("Uhr gestellt – prüfe noch einmal …"), 10000)
        self.after_sync = True
        self.next_at = time.monotonic() + 5        # kurz warten, dann nachmessen
