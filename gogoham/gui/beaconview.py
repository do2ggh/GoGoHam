"""Fenster „Baken“ (ab 0.8.14): 18 NCDXF/IARU-Baken × Bakenbänder des Contests.

Grün = in den letzten 15 Minuten von Empfängern in deiner Nähe gut gehört (ab 10 dB),
gelb = nur schwach oder vor 15–30 Minuten, grau = seit 30 Minuten nicht gehört.
Maus auf ein Feld: welche Empfänger, wie weit weg, wann, wie stark.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QLabel, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import beacons as bc
from ..bands import band_label
from ..i18n import tr

COLORS = {bc.GOOD: ("#1b8a3a", "white"), bc.FAIR: ("#f2c200", "black")}


def place_name(call: str) -> str:
    return {
        "4U1UN": tr("UNO New York, USA"), "VE8AT": tr("Eureka, Kanada"),
        "W6WX": tr("Mt. Umunhum, USA"), "KH6RS": tr("Maui, Hawaii"),
        "ZL6B": tr("Masterton, Neuseeland"), "VK6RBP": tr("Rolystone, Australien"),
        "JA2IGY": tr("Mt. Asama, Japan"), "RR9O": tr("Nowosibirsk, Russland"),
        "VR2B": tr("Hongkong"), "4S7B": tr("Colombo, Sri Lanka"),
        "ZS6DN": tr("Pretoria, Südafrika"), "5Z4B": tr("Kikuyu, Kenia"),
        "4X6TU": tr("Tel Aviv, Israel"), "OH2B": tr("Lohja, Finnland"),
        "CS3B": tr("Madeira, Portugal"), "LU4AA": tr("Buenos Aires, Argentinien"),
        "OA4B": tr("Lima, Peru"), "YV5B": tr("Caracas, Venezuela"),
    }.get(call, call)


class BeaconView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.tbl = QTableWidget(len(bc.BEACONS), 3)
        self.tbl.verticalHeader().hide()
        self.tbl.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 6)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay.addWidget(self.tbl, 1)
        # alle Spalten lesbar (Bake, Standort, Richtung, bis zu 3 Bänder)
        self.setMinimumWidth(self.fontMetrics().averageCharWidth() * 62)
        self.bands: list[str] = []
        self._sig = None

    def set_status(self, text: str, color: str = "") -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color:{color}; font-weight:bold;" if color else "")

    def show_board(self, board, bands: list[str], home, force: bool = False) -> None:
        now = time.time()
        sig = (board.version if board else -1, tuple(bands), int(now // 30))
        if sig == self._sig and not force:
            return
        self._sig = sig
        if bands != self.bands:
            self.bands = list(bands)
            self.tbl.setColumnCount(3 + len(bands))
            self.tbl.setHorizontalHeaderLabels(
                [tr("Bake"), tr("Standort"), tr("Richtung")] + [band_label(b) for b in bands])
            hh = self.tbl.horizontalHeader()
            hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for r, b in enumerate(bc.BEACONS):
            deg = bc.bearing(home, b)
            for c, text in enumerate((b.call, place_name(b.call),
                                      "–" if deg is None else f"{deg}°")):
                it = QTableWidgetItem(text)
                if c == 2:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tbl.setItem(r, c, it)
            for i, band in enumerate(bands):
                cell = board.cell(b.call, band, now) if board else bc.Cell()
                it = QTableWidgetItem(self._cell_text(cell))
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if cell.level in COLORS:
                    bg, fg = COLORS[cell.level]
                    it.setBackground(QBrush(QColor(bg)))
                    it.setForeground(QBrush(QColor(fg)))
                else:
                    it.setForeground(QBrush(QColor("#9e9e9e")))
                it.setToolTip(self._cell_tip(b.call, band, cell, now))
                self.tbl.setItem(r, 3 + i, it)

    @staticmethod
    def _cell_text(cell) -> str:
        if cell.level == bc.NONE:
            return "–"
        return tr("{db} dB", db=cell.best_db) if cell.best_db is not None else "✓"

    @staticmethod
    def _cell_tip(call: str, band: str, cell, now: float) -> str:
        head = tr("{call} auf {band}", call=call, band=band_label(band))
        if not cell.heard:
            return head + "\n" + tr("in den letzten 30 Minuten von keinem Empfänger in deiner "
                                    "Nähe gehört")
        lines = [head]
        for h in cell.heard[:8]:
            mins = max(0, int((now - h.when) // 60))
            db = tr("{db} dB", db=h.db) if h.db is not None else "?"
            lines.append(tr("{sk} ({km} km) · vor {m} min · {db}", sk=h.skimmer, km=h.km,
                            m=mins, db=db))
        if len(cell.heard) > 8:
            lines.append(tr("… und {n} weitere", n=len(cell.heard) - 8))
        return "\n".join(lines)
