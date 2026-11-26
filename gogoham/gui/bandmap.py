"""Bandmap (ab 0.8.12): Spots des aktuellen Bandes, nach Frequenz sortiert, mit deiner eigenen
Frequenz als Markierung. Grün ★ = neuer Multi auf diesem Band, normal = neues QSO, grau
durchgestrichen = schon gearbeitet. Orange ↕ (ab 0.8.19) = auf einem anderen Band noch ein
fehlender Multi (lohnt den Bandwechsel) – welche Bänder steht im Tooltip. Ältere Spots werden
blasser. Ein Klick stellt das Funkgerät auf die Station ein – gesendet wird nie etwas.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

from ..bands import band_label
from ..i18n import num, tr

GREEN, BLUE, GREY, ORANGE = "#1b8a3a", "#1565c0", "#8a8a8a", "#c77f00"
ROLE_SPOT = Qt.ItemDataRole.UserRole


class BandmapView(QListWidget):
    """rows: Liste (spot, status[, other_bands]) mit status „mult“, „new“, „dupe“ oder
    „invalid“. other_bands = Bänder, auf denen die Station noch ein fehlender Multi wäre."""

    def __init__(self, font_size: int = 13, on_pick=None, parent=None, on_menu=None):
        super().__init__(parent)
        self.on_pick = on_pick
        self.on_menu = on_menu            # Rechtsklick auf einen Spot (0.8.19.2): (spot, globale Pos.)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        f = QFont("Monospace", font_size)
        f.setStyleHint(QFont.StyleHint.TypeWriter)
        self.setFont(f)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setToolTip(tr("Klick: Funkgerät auf Frequenz und Betriebsart stellen, Rufzeichen "
                           "eintragen, Betrieb auf S&P – gesendet wird nichts. "
                           "Rechtsklick: Rufzeichen bei QRZ.com ansehen"))
        self.itemClicked.connect(self._clicked)
        self._center_key = None
        self.max_age = 30 * 60
        # Zeitungsspalten (0.8.14, Wunsch des Nutzers): passt die Breite für zwei oder mehr
        # Spalten, läuft die Liste von oben nach unten und dann in der nächsten Spalte weiter –
        # die Frequenz bleibt so in Lesereihenfolge. Schmal: eine Spalte wie bisher.
        fm = QFontMetrics(f)
        self._cell = QSize(fm.horizontalAdvance("0" * 31), fm.height() + 2)
        self._columns = False

    def resizeEvent(self, ev):  # noqa: N802
        super().resizeEvent(ev)
        self._apply_layout()

    def _apply_layout(self) -> None:
        many = self.viewport().width() >= 2 * self._cell.width()
        if many == self._columns:
            return
        self._columns = many
        self.setFlow(QListWidget.Flow.TopToBottom)
        self.setWrapping(many)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setGridSize(self._cell if many else QSize())
        if self.currentItem() is None and self.count():
            self.scrollToTop()

    def columns(self) -> bool:
        """True = mehrere Spalten (Zeitungsspalten)."""
        return self._columns
    def _context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        spot = item.data(ROLE_SPOT) if item is not None else None
        if spot is not None and self.on_menu:
            self.on_menu(spot, self.viewport().mapToGlobal(pos))

    def _clicked(self, item: QListWidgetItem) -> None:
        spot = item.data(ROLE_SPOT)
        if spot is not None and self.on_pick:
            self.on_pick(spot)

    def show_rows(self, rows: list, own_hz: int, band: str, now: float | None = None) -> None:
        now = now or time.time()
        bar = self.horizontalScrollBar() if self._columns else self.verticalScrollBar()
        keep = bar.value()
        self.clear()
        marker = None
        for spot, status, *rest in rows:
            other = rest[0] if rest else []
            if marker is None and own_hz and spot.freq > own_hz:
                marker = self._marker(own_hz)
            self.addItem(self._item(spot, status, now, other))
        if marker is None and own_hz:
            marker = self._marker(own_hz)
        if not rows:
            it = QListWidgetItem(tr("Noch keine Spots auf diesem Band"))
            it.setForeground(QBrush(QColor(GREY)))
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addItem(it)
        # bei Bandwechsel oder deutlicher QSY die eigene Frequenz in die Mitte holen
        key = (band, own_hz // 5000 if own_hz else 0)
        if marker is not None and key != self._center_key:
            self.scrollToItem(marker, QAbstractItemView.ScrollHint.PositionAtCenter)
            self._center_key = key
        else:
            bar.setValue(keep)

    def _marker(self, own_hz: int) -> QListWidgetItem:
        it = QListWidgetItem(tr("{khz}  ◀ hier bist du", khz=num(own_hz / 1000, 1).rjust(9)))
        it.setForeground(QBrush(QColor(BLUE)))
        f = self.font()
        f.setBold(True)
        it.setFont(f)
        it.setFlags(Qt.ItemFlag.NoItemFlags)
        self.addItem(it)
        return it

    def _item(self, spot, status: str, now: float, other=()) -> QListWidgetItem:
        age_min = max(0, int((now - spot.received) // 60))
        mark = ("★" if status == "mult" else "") + ("↕" if other else "")
        text = f"{num(spot.freq / 1000, 1).rjust(9)}  {spot.call:<11}{mark:<2}"
        if age_min >= 1:
            text += f"  {age_min}′"
        it = QListWidgetItem(text)
        it.setData(ROLE_SPOT, spot)
        tip = tr("{call} · gemeldet von {spotter} um {utc}Z · {comment}",
                 call=spot.call, spotter=spot.spotter, utc=spot.utc,
                 comment=spot.comment or "–")
        if other:
            tip += "\n" + tr("Multi – fehlt noch auf {bands}",
                             bands=", ".join(band_label(b) for b in other))
        it.setToolTip(tip)
        f = QFont(self.font())
        if status == "mult":
            color = QColor(GREEN)
            f.setBold(True)
        elif other:                       # hier kein neuer Multi, aber auf anderem Band noch gesucht
            color = QColor(ORANGE)
            f.setBold(True)
        elif status == "dupe":
            color = QColor(GREY)
            f.setStrikeOut(True)
        elif status == "invalid":
            color = QColor(GREY)
            f.setItalic(True)
        else:
            color = self.palette().text().color()
        # blasser, je älter (bis höchstens halb durchsichtig)
        frac = min(1.0, (now - spot.received) / max(1, self.max_age))
        color.setAlpha(int(255 - 130 * frac))
        it.setForeground(QBrush(color))
        it.setFont(f)
        return it
