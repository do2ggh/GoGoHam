"""Kleine Punktetabelle rechts im Hauptfenster (ab 0.8.19.1).

Vorher teilte „Stretch“ die feste Breite stur gleichmäßig auf. In den Franken-Designs
(fetter Tabellenkopf mit Innenabstand) wurde dabei „Länder“ an beiden Enden abgeschnitten.
Jetzt bekommt jede Spalte mindestens die Breite ihres Inhalts (Kopf und Zellen), der übrige
Platz wird gleichmäßig verteilt. Passt es gar nicht, erscheint ein Rollbalken statt
abgeschnittener Wörter.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QHeaderView, QTableWidget

OBJECT_NAME = "score_table"
HEADER_NAME = "score_header"


def column_widths(need: list[int], avail: int) -> list[int]:
    """Spaltenbreiten: jede mindestens ``need``, Rest von ``avail`` gleichmäßig verteilt."""
    total = sum(need)
    if not need or total >= avail:
        return list(need)
    extra, rest = divmod(avail - total, len(need))
    return [n + extra + (1 if i < rest else 0) for i, n in enumerate(need)]


class ScoreTable(QTableWidget):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.setObjectName(OBJECT_NAME)
        hh = self.horizontalHeader()
        hh.setObjectName(HEADER_NAME)
        hh.style().unpolish(hh)            # Name erst nach dem Anlegen gesetzt: Stilregeln
        hh.style().polish(hh)              # mit #score_header neu anwenden
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self._pending = False

    def fit_columns(self) -> None:
        self._pending = False
        n = self.columnCount()
        if not n:
            return
        hh = self.horizontalHeader()
        need = [max(hh.sectionSizeFromContents(i).width(), self.sizeHintForColumn(i),
                    hh.minimumSectionSize())        # Qt hält Spalten nie schmaler
                for i in range(n)]
        for i, w in enumerate(column_widths(need, self.viewport().width())):
            hh.resizeSection(i, w)

    def schedule_fit(self) -> None:
        """Nach dem nächsten Ereignisdurchlauf anpassen (Stil/Größe sind dann aktuell)."""
        if not self._pending:
            self._pending = True
            QTimer.singleShot(0, self.fit_columns)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self.schedule_fit()

    def viewportEvent(self, e) -> bool:  # noqa: N802
        # Senkrechter Rollbalken erscheint/verschwindet: sichtbare Breite ändert sich
        if e.type() == QEvent.Type.Resize:
            self.schedule_fit()
        return super().viewportEvent(e)

    def changeEvent(self, e) -> None:  # noqa: N802
        super().changeEvent(e)
        if e.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self.schedule_fit()
