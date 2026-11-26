"""Fenster „Station“ (ab 0.10.3): Überblick über alle Plätze des Stationslogs und Nachrichten.

Oben eine Tabelle (Platz, Operator, Sender, Band, Frequenz, Betriebsart, QSOs, Rate,
Verbindung), unten der Nachrichtenverlauf mit Eingabezeile. Plätze auf demselben Band werden
rot hinterlegt. Das Fenster zeigt nur an – Daten und Versand stecken im StationController.
"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from ..i18n import tr

RED_BG = "#f8d0d0"
GREY_FG = "#888888"


def _freq_text(freq) -> str:
    try:
        f = float(freq or 0)
    except (TypeError, ValueError):
        return ""
    return f"{f / 1000:.1f}" if f > 0 else ""


class StationView(QWidget):
    COLS = 9

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_send = None                  # (an, Text) -> None
        self.on_setup = None                 # Knopf „Stationslog …“
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.btn_setup = QPushButton(tr("Stationslog einrichten …"))
        self.btn_setup.clicked.connect(lambda: self.on_setup and self.on_setup())
        lay.addWidget(self.btn_setup, 0, Qt.AlignmentFlag.AlignLeft)
        self.table = QTableWidget(0, self.COLS)
        self.table.setHorizontalHeaderLabels([
            tr("Platz"), tr("Operator"), tr("Sender"), tr("Band"), tr("Frequenz (kHz)"),
            tr("Mode"), tr("QSOs"), tr("Rate 10 / 60 min"), tr("Verbindung")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setToolTip(tr("Rot = mehrere Plätze auf demselben Band. Rate = QSOs pro "
                                 "Stunde, gerechnet über die letzten 10 bzw. 60 Minuten."))
        lay.addWidget(self.table, 2)
        box = QGroupBox(tr("Nachrichten"))
        bl = QVBoxLayout(box)
        self.history = QTextBrowser()
        self.history.setOpenLinks(False)
        bl.addWidget(self.history, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("An:")))
        self.to = QComboBox()
        self.to.setMinimumContentsLength(10)
        row.addWidget(self.to)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(tr("Nachricht schreiben – Enter schickt sie ab"))
        self.edit.setMaxLength(500)
        self.edit.returnPressed.connect(self._send)
        row.addWidget(self.edit, 1)
        self.btn_send = QPushButton(tr("Senden"))
        self.btn_send.setToolTip(tr("Schickt die Nachricht an den gewählten Platz – geht nur "
                                    "übers Netzwerk, nie über das Funkgerät"))
        self.btn_send.clicked.connect(self._send)
        row.addWidget(self.btn_send)
        bl.addLayout(row)
        lay.addWidget(box, 3)
        self._chat_sig = None
        self._targets: list[str] = []
        self.set_active(False, "")

    # ------------------------------------------------------------ Anzeige
    def set_active(self, active: bool, text: str) -> None:
        self.info.setText(text)
        self.info.setVisible(bool(text))
        self.btn_setup.setVisible(not active)
        for w in (self.to, self.edit, self.btn_send):
            w.setEnabled(active)

    def set_rows(self, rows: list[dict], busy: dict[str, set[str]]) -> None:
        """rows: Platz-Zeilen (place, op, tx_text, band, freq, mode, qsos, r10, r60, own,
        host, gone_text); busy: Band -> Plätze auf demselben Band."""
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            name = r.get("place", "?")
            if r.get("own"):
                name += " " + tr("(dieser Platz)")
            elif r.get("host"):
                name += " " + tr("(Hauptplatz)")
            if r.get("gone_text"):
                conn = r["gone_text"]
            elif r.get("own"):
                conn = "–"
            else:
                conn = tr("verbunden")
            vals = [name, r.get("op", ""), r.get("tx_text", ""), r.get("band", ""),
                    _freq_text(r.get("freq")), r.get("mode", ""), str(r.get("qsos", 0)),
                    f"{r.get('r10', 0)} / {r.get('r60', 0)}", conn]
            red = not r.get("gone_text") and r.get("place") in busy.get(r.get("band", ""), ())
            for c, v in enumerate(vals):
                it = self.table.item(i, c)
                if it is None:
                    it = QTableWidgetItem()
                    self.table.setItem(i, c, it)
                it.setText(str(v))
                it.setBackground(QBrush(QColor(RED_BG)) if red else QBrush())
                it.setForeground(QBrush(QColor(GREY_FG)) if r.get("gone_text") else QBrush())
                if red and c == 3:
                    it.setToolTip(tr("Auf diesem Band sind mehrere Plätze"))
                else:
                    it.setToolTip("")
                font = it.font()
                font.setBold(bool(r.get("own")))
                it.setFont(font)

    def set_targets(self, names: list[str]) -> None:
        """Auswahl „An:“ – an alle oder einen Platz (die Auswahl bleibt stehen)."""
        if names == self._targets:
            return
        self._targets = list(names)
        cur = self.to.currentData()
        self.to.blockSignals(True)
        self.to.clear()
        self.to.addItem(tr("alle Plätze"), "")
        for n in names:
            self.to.addItem(n, n)
        idx = self.to.findData(cur) if cur else 0
        self.to.setCurrentIndex(max(idx, 0))
        self.to.blockSignals(False)

    def set_chats(self, chats: list[dict]) -> None:
        sig = tuple((c["mid"], c["state"]) for c in chats)
        if sig == self._chat_sig:
            return
        self._chat_sig = sig
        lines = []
        for c in chats:
            t = html.escape((c.get("time") or "")[11:16])
            text = html.escape(c.get("text", ""))
            to = c.get("to", "")
            if c.get("state") == "in":
                who = html.escape(c.get("from", "?"))
                if to:
                    who += " → " + html.escape(tr("dich"))
                lines.append(f"<p><span style='color:{GREY_FG}'>{t}</span> <b>{who}:</b> {text}</p>")
            else:
                to_txt = html.escape(to or tr("alle"))
                state = {"out": tr("unterwegs …"), "ok": tr("zugestellt"),
                         "fail": tr("nicht zugestellt")}.get(c.get("state"), "")
                color = "#c62828" if c.get("state") == "fail" else GREY_FG
                lines.append(f"<p><span style='color:{GREY_FG}'>{t}</span> <b>"
                             f"{html.escape(tr('Ich'))} → {to_txt}:</b> {text} "
                             f"<span style='color:{color}'>({html.escape(state)})</span></p>")
        if not lines:
            lines.append(f"<p style='color:{GREY_FG}'>"
                         + html.escape(tr("Noch keine Nachrichten.")) + "</p>")
        self.history.setHtml("".join(lines))
        sb = self.history.verticalScrollBar()
        sb.setValue(sb.maximum())

    def focus_input(self) -> None:
        self.edit.setFocus()

    def _send(self) -> None:
        text = self.edit.text().strip()
        if not text or not self.edit.isEnabled():
            return
        if self.on_send:
            self.on_send(self.to.currentData() or "", text)
        self.edit.clear()
