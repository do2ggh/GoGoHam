"""Fenster „Übersicht“: Multis je Band und Rate-Grafik."""

from __future__ import annotations

from ..i18n import tr

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHeaderView, QLabel, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .. import stats
from ..bands import BAND_NAMES, band_label
from ..countries import german_name

BAND_COLORS = {"160": "#8e24aa", "80": "#3949ab", "40": "#1e88e5", "20": "#43a047",
               "15": "#fdd835", "10": "#fb8c00"}
GREEN = "#1b8a3a"


class RateWidget(QWidget):
    """Gestapelte Balken: QSOs pro Stunde, farbig nach Band."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: list[tuple[str, dict[str, int]]] = []
        self.bands: list[str] = []
        self.setMinimumHeight(260)

    def set_data(self, data, bands) -> None:
        self.data, self.bands = data, bands
        self.update()

    def paintEvent(self, _ev):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        fg = self.palette().color(self.foregroundRole())
        p.setPen(QPen(fg))
        if not self.data:
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, tr("Noch keine QSOs"))
            return
        left, bottom, top, right = 46, 46, 28, 12
        maxv = max(sum(b.values()) for _l, b in self.data) or 1
        step = 10 if maxv <= 60 else 25 if maxv <= 150 else 50
        maxv = ((maxv + step - 1) // step) * step
        ch = h - top - bottom
        cw = w - left - right
        # Achsen und Hilfslinien
        small = QFont()
        small.setPointSize(8)
        p.setFont(small)
        for v in range(0, maxv + 1, step):
            y = top + ch - ch * v / maxv
            p.setPen(QPen(QColor(128, 128, 128, 80)))
            p.drawLine(left, int(y), w - right, int(y))
            p.setPen(QPen(fg))
            p.drawText(QRectF(0, y - 8, left - 6, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(v))
        n = len(self.data)
        bw = cw / n
        for i, (label, per_band) in enumerate(self.data):
            x = left + i * bw
            y = top + ch
            for band in self.bands:
                cnt = per_band.get(band, 0)
                if not cnt:
                    continue
                bh = ch * cnt / maxv
                p.fillRect(QRectF(x + 1, y - bh, max(1.0, bw - 2), bh),
                           QBrush(QColor(BAND_COLORS.get(band, "#888888"))))
                y -= bh
            if n <= 48 and (i % max(1, n // 12) == 0):
                p.setPen(QPen(fg))
                p.drawText(QRectF(x - 20, top + ch + 4, bw + 40, 16),
                           Qt.AlignmentFlag.AlignHCenter, label[7:9] + "h")
        # Legende
        x = left
        for band in self.bands:
            p.fillRect(QRectF(x, h - 18, 12, 12), QBrush(QColor(BAND_COLORS.get(band, "#888"))))
            p.setPen(QPen(fg))
            p.drawText(QRectF(x + 16, h - 20, 50, 16), Qt.AlignmentFlag.AlignVCenter, band_label(band))
            x += 64
        p.drawText(QRectF(left, 4, cw, 18), Qt.AlignmentFlag.AlignLeft,
                   tr("QSOs pro Stunde (UTC)"))


class StatsWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Übersicht – Multis und Rate"))
        self.resize(780, 620)
        self.tabs = QTabWidget()
        self.rate = RateWidget()
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        self._tables: dict[str, QTableWidget] = {}

    def refresh(self, contest, scorer, qsos) -> None:
        if contest is None or scorer is None:
            return
        matrix = stats.mult_matrix(contest, scorer, qsos)
        if [self.tabs.tabText(i) for i in range(self.tabs.count())] != \
                [matrix[k]["label"] for k in matrix] + ["Rate"]:
            self.tabs.clear()
            self._tables = {}
            for key in matrix:
                t = QTableWidget()
                t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
                t.verticalHeader().setVisible(True)
                t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
                self._tables[key] = t
                self.tabs.addTab(t, matrix[key]["label"])
            self.tabs.addTab(self.rate, tr("Rate"))
        for key, m in matrix.items():
            t = self._tables[key]
            cols = m["cols"] if contest.mults_per_band else [tr("Band (erstes QSO)")]
            t.setColumnCount(len(cols))
            t.setHorizontalHeaderLabels([band_label(c) if c in BAND_NAMES else c for c in cols])
            t.setRowCount(len(m["rows"]))
            labels = []
            for r, val in enumerate(m["rows"]):
                if key == "country":
                    en = contest.cty.name_for_prefix(val) if contest.cty else val
                    labels.append(f"{german_name(val, en)} ({val.lstrip('*')})")
                elif key == "zone":
                    labels.append(tr("Zone {val}", val=val))
                else:
                    labels.append(val)
                for c, band in enumerate(cols):
                    if contest.mults_per_band:
                        ok = (val, band) in m["worked"]
                        text = "✔" if ok else ""
                    else:
                        b = next((bb for vv, bb in m["worked"] if vv == val), "")
                        ok, text = bool(b), (band_label(b) if b else "")
                    it = QTableWidgetItem(text)
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if ok:
                        it.setBackground(QBrush(QColor(GREEN)))
                        it.setForeground(QBrush(QColor("white")))
                    t.setItem(r, c, it)
            t.setVerticalHeaderLabels(labels)
        self.rate.set_data(stats.rate_by_hour(qsos, contest.bands,
                                              dupes={i for i, e in scorer.evals.items()
                                                     if e.dupe}),
                           contest.bands)


class LogCheckDialog(QDialog):
    """Ergebnis der Log-Prüfung. Doppelklick öffnet das QSO zum Bearbeiten."""

    def __init__(self, findings, parent=None, for_export: bool = False, on_edit=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QDialogButtonBox
        self.setWindowTitle(tr("Log-Prüfung"))
        self.resize(820, 480)
        self.findings = findings
        self.on_edit = on_edit
        warn = sum(1 for f in findings if f.level == "warn")
        head = QLabel(tr("<b>{warn} Hinweis(e) zum Prüfen</b>, {p3} zur Info. Doppelklick "
                         "auf eine Zeile öffnet das QSO zum Bearbeiten.", warn=warn, p3=len(findings) - warn)
                      if findings else tr("<b>Keine Auffälligkeiten gefunden.</b> 👍"))
        head.setWordWrap(True)
        self.tbl = QTableWidget(len(findings), 4)
        self.tbl.setHorizontalHeaderLabels([tr("UTC"), tr("Band"), tr("Rufzeichen"), tr("Hinweis")])
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        for r, f in enumerate(findings):
            for c, v in enumerate((f.time[11:16], f.band, f.call, f.text)):
                it = QTableWidgetItem(v)
                if f.level == "warn":
                    it.setForeground(QBrush(QColor("#e08a00")))
                self.tbl.setItem(r, c, it)
        self.tbl.cellDoubleClicked.connect(self._edit)
        if for_export:
            bb = QDialogButtonBox()
            bb.addButton(tr("Trotzdem exportieren"), QDialogButtonBox.ButtonRole.AcceptRole)
            bb.addButton(tr("Abbrechen"), QDialogButtonBox.ButtonRole.RejectRole)
        else:
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(head)
        lay.addWidget(self.tbl)
        lay.addWidget(bb)

    def _edit(self, row: int, _col: int) -> None:
        if self.on_edit and 0 <= row < len(self.findings):
            self.on_edit(self.findings[row].qso_id)
