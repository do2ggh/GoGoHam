"""Fenster „Wohin mit dem Log?“ nach dem Export (ab 0.10.41)."""

from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from .. import schedule
from .. import submit as sm
from ..i18n import tr

_PH = {"USB", "LSB", "SSB", "FM", "AM", "PH"}


def log_modes(qsos) -> set[str]:
    out = set()
    for q in qsos:
        m = (q.mode or "").upper()
        out.add("CW" if m.startswith("CW") else "PH" if m in _PH else "RY" if m == "RTTY" else "DG")
    return out


def contest_end(contest, qsos, now: datetime | None = None) -> datetime | None:
    """Ende des Contests, zu dem das Log gehört (aus der ersten QSO-Zeit)."""
    rule = getattr(contest, "schedule", None)
    if not rule:
        return None
    times = []
    for q in qsos:
        try:
            times.append(datetime.strptime(q.time, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            pass
    try:
        if times:
            found = schedule.period_of(rule, min(times))
            if found:
                return found[1]
        return None
    except (KeyError, ValueError, IndexError, TypeError):
        return None


def _a(url: str, text: str | None = None) -> str:
    return f'<a href="{html.escape(url, True)}">{html.escape(text or url)}</a>'


class SubmitDialog(QDialog):
    """Zeigt, wohin das Log muss; E-Mail/Upload-Seite öffnen und zugleich den Ordner mit der
    markierten Datei – zum Hineinziehen in die Mail bzw. ins Upload-Formular."""

    def __init__(self, contest, files: list[str], call: str, qsos=(), parent=None,
                 now: datetime | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Wohin mit dem Log?"))
        self.setMinimumWidth(560)
        self.files = [str(f) for f in files]
        self.sub = sm.block(contest)
        self.rules_url = (getattr(contest, "rules", None) or {}).get("rules_url", "")
        name = getattr(contest, "name", "")
        self.addresses = sm.emails(self.sub, log_modes(qsos))
        self.subject = sm.subject(self.sub, call, name)
        self.upload = self.sub.get("upload_url", "")
        now = now or datetime.now(timezone.utc).replace(tzinfo=None)

        parts = [tr("<b>Gespeichert:</b>") + "<br>" +
                 "<br>".join(html.escape(f) for f in self.files)]
        if self.addresses:
            parts.append(tr("<b>Per E-Mail an:</b> {mail}",
                            mail=", ".join(_a("mailto:" + a, a) for a in self.addresses)) +
                         ("<br>" + tr("Kopie (CC) an: {mail}", mail=_a("mailto:" + self.sub["cc"],
                                                                     self.sub["cc"]))
                          if self.sub.get("cc") else "") +
                         "<br>" + tr("Betreff: {subject}", subject=html.escape(self.subject)))
        if self.upload:
            parts.append(tr("<b>Hochladen auf:</b> {url}", url=_a(self.upload)))
        if self.addresses or self.upload:
            parts.append(tr("Beim Öffnen zeigt GoGoHam auch den Ordner mit der markierten "
                            "Log-Datei: einfach in die E-Mail bzw. ins Upload-Formular ziehen."))
        dl = sm.deadline(self.sub, contest_end(contest, qsos))
        if dl:
            left = (dl - now).days
            when = dl.strftime("%d.%m.%Y %H:%M")
            parts.append(tr("<b>Einsendeschluss:</b> {when} UTC (noch {n} Tage)", when=when, n=left)
                         if dl >= now else
                         tr("<b>Einsendeschluss:</b> {when} UTC – ⚠ vorbei", when=when))
        n = sm.note(self.sub)
        if n:
            parts.append(html.escape(n))
        if not self.sub:
            parts.append(tr("Für diesen Contest hat GoGoHam noch keinen gesicherten Einsendeweg. "
                            "Wohin das Log muss, steht in der Ausschreibung:") +
                         ("<br>" + _a(self.rules_url) if self.rules_url else ""))
        elif self.rules_url:
            parts.append(tr("Ausschreibung: {url}", url=_a(self.rules_url)))

        self.text = QLabel("<p>" + "</p><p>".join(parts) + "</p>")
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.text.setOpenExternalLinks(False)
        self.text.linkActivated.connect(self.open_link)
        lay = QVBoxLayout(self)
        lay.addWidget(self.text)

        bb = QDialogButtonBox()
        self.btn_mail = self.btn_upload = None
        if self.addresses:
            self.btn_mail = bb.addButton(tr("E-Mail-Programm öffnen"),
                                         QDialogButtonBox.ButtonRole.ActionRole)
            self.btn_mail.clicked.connect(self.open_mail)
        if self.upload:
            self.btn_upload = bb.addButton(tr("Upload-Seite öffnen"),
                                           QDialogButtonBox.ButtonRole.ActionRole)
            self.btn_upload.clicked.connect(lambda: self.open_link(self.upload))
        if not self.sub and self.rules_url:
            b = bb.addButton(tr("Ausschreibung öffnen"), QDialogButtonBox.ButtonRole.ActionRole)
            b.clicked.connect(lambda: self.open_link(self.rules_url))
        self.btn_folder = bb.addButton(tr("Ordner zeigen"), QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_folder.clicked.connect(self.show_folder)
        bb.addButton(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    # --- Aktionen --------------------------------------------------------------------
    def open_url(self, url: str) -> bool:                 # für Tests austauschbar
        return QDesktopServices.openUrl(QUrl(url))

    def send_mail(self, url: str) -> bool:                # für Tests austauschbar
        from .. import mailopen
        return mailopen.open_mail(url, self.open_url)

    def show_folder(self) -> None:
        if not sm.show_in_folder(self.files):
            self.open_url(QUrl.fromLocalFile(str(Path(self.files[0]).parent)).toString())

    def open_mail(self) -> None:
        self.show_folder()
        if not self.send_mail(sm.mailto(self.addresses, self.subject, self.sub.get("cc", ""))):
            self.text.setText(self.text.text() + "<p>" + tr(
                "⚠ Es ließ sich kein E-Mail-Programm öffnen. Bitte die Adresse oben in dein "
                "E-Mail-Programm übernehmen.") + "</p>")

    def open_link(self, url: str) -> None:
        if url.startswith("mailto:"):
            self.open_mail()
            return
        if url == self.upload:
            self.show_folder()
        self.open_url(url)
