"""QR-Code fürs Handy (ab 0.10.15): einen Contest-Termin mit der Handy-Kamera übernehmen.

Der Code enthält einen Kalendertermin („BEGIN:VEVENT“). Die Kamera-App des iPhones und die meisten
Android-Kameras bzw. Google Lens erkennen das und bieten „Zum Kalender hinzufügen“ an – ohne
Datei, ohne Internet. Die Erinnerung (Voreinstellung 1 Stunde vorher) steckt mit im Code; manche
Kalender-Apps nehmen stattdessen ihre eigene Standard-Erinnerung.

Gezeichnet wird der Code selbst (Quadrate auf weißem Grund) – die mitgelieferte Bibliothek segno
liefert nur das Muster.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QVBoxLayout)

from .. import contestcal as cc
from ..i18n import tr

QUIET = 4                       # weißer Rand in Modulen (Norm: mindestens 4)


def qr_matrix(text: str) -> list[list[bool]]:
    from .._vendor import segno
    q = segno.make(text, error="m", micro=False)
    return [[bool(v) for v in row] for row in q.matrix]


def qr_pixmap(text: str, size: int = 360) -> QPixmap:
    m = qr_matrix(text)
    n = len(m) + 2 * QUIET
    cell = max(2, size // n)
    pm = QPixmap(n * cell, n * cell)
    pm.fill(QColor("white"))
    p = QPainter(pm)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("black"))
    for y, row in enumerate(m):
        for x, dark in enumerate(row):
            if dark:
                p.drawRect((x + QUIET) * cell, (y + QUIET) * cell, cell, cell)
    p.end()
    return pm


def alarm_text(minutes: int) -> str:
    if not minutes:
        return tr("keine Erinnerung")
    if minutes >= 1440:
        return tr("{n} Tag vorher", n=minutes // 1440)
    if minutes >= 60:
        return tr("{n} Std. vorher", n=minutes // 60)
    return tr("{n} Min. vorher", n=minutes)


class QrDialog(QDialog):
    """Ein Contest als QR-Code; Erinnerung wählbar (gemerkt in cfg["calendar_alarm"])."""

    def __init__(self, entry: cc.Entry, when_text: str, cfg: dict, on_change=None, parent=None):
        super().__init__(parent)
        self.entry, self.cfg, self.on_change = entry, cfg, on_change
        self.setWindowTitle(tr("QR-Code fürs Handy"))
        lay = QVBoxLayout(self)
        head = QLabel(f"<b>{entry.name}</b><br>{when_text}")
        head.setTextFormat(Qt.TextFormat.RichText)
        head.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(head)
        self.img = QLabel()
        self.img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.img, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Erinnerung:")))
        self.alarm = QComboBox()
        for m in cc.ALARM_CHOICES:
            self.alarm.addItem(alarm_text(m), m)
        i = self.alarm.findData(int(cfg.get("calendar_alarm", cc.ALARM_DEFAULT)))
        self.alarm.setCurrentIndex(max(i, 0))
        self.alarm.currentIndexChanged.connect(self._alarm_changed)
        row.addWidget(self.alarm)
        row.addStretch(1)
        lay.addLayout(row)
        hint = QLabel(tr("Mit der Kamera des Handys scannen (Android: Kamera oder Google Lens) "
                         "und „Zum Kalender hinzufügen“ wählen. Die Zeiten rechnet das Handy "
                         "selbst in seine Ortszeit um. Manche Kalender-Apps nehmen statt der "
                         "Erinnerung ihre eigene Voreinstellung."))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
        self._draw()

    def text(self) -> str:
        return cc.qr_event(self.entry, int(self.alarm.currentData() or 0))

    def _draw(self) -> None:
        self.img.setPixmap(qr_pixmap(self.text()))

    def _alarm_changed(self, _i: int) -> None:
        self.cfg["calendar_alarm"] = int(self.alarm.currentData() or 0)
        if self.on_change:
            self.on_change()
        self._draw()
