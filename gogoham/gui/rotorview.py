"""Fenster „Rotor“ (ab 0.8.23.1): Kompassrose mit Ist- und Zielrichtung, Gradzahl eingeben,
Short/Long Path zum Rufzeichen, Stopp. Klick in die Rose dreht in diese Richtung.

Das Fenster zeigt und bedient nur – ob der Rotor verbunden ist, hängt allein an
Einstellungen → Rotor (auch bei geschlossenem Fenster dreht Alt+R).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSpinBox,
                               QToolTip, QVBoxLayout, QWidget)

from ..i18n import tr

NEEDLE = "#ff8f00"                    # wie der Beam auf der Karte
TARGET = "#1565c0"


class CompassRose(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(180, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.heading: int | None = None
        self.target: int | None = None
        self.enabled_turn = False
        self.on_click = None                         # (Grad)

    def _geom(self) -> tuple[QPointF, float]:
        r = min(self.width(), self.height()) / 2 - 22
        return QPointF(self.width() / 2, self.height() / 2), max(20.0, r)

    def bearing_at(self, x: float, y: float) -> int | None:
        c, r = self._geom()
        dx, dy = x - c.x(), y - c.y()
        if math.hypot(dx, dy) > r + 18 or math.hypot(dx, dy) < 4:
            return None
        return int(round(math.degrees(math.atan2(dx, -dy)))) % 360

    def _pt(self, c: QPointF, r: float, deg: float) -> QPointF:
        a = math.radians(deg)
        return QPointF(c.x() + r * math.sin(a), c.y() - r * math.cos(a))

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pal = self.palette()
        text = pal.color(QPalette.ColorRole.WindowText)
        c, r = self._geom()
        p.setPen(QPen(text, 1.4))
        p.setBrush(pal.color(QPalette.ColorRole.Base))
        p.drawEllipse(c, r, r)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for deg in range(0, 360, 10):
            inner = r - (10 if deg % 90 == 0 else 7 if deg % 30 == 0 else 4)
            p.drawLine(self._pt(c, inner, deg), self._pt(c, r, deg))
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        names = {0: tr("N"), 90: tr("O"), 180: tr("S"), 270: tr("W")}
        for deg in range(0, 360, 30):
            label = names.get(deg, str(deg))
            pt = self._pt(c, r + 12, deg)
            p.drawText(QPointF(pt.x() - fm.horizontalAdvance(label) / 2,
                               pt.y() + fm.ascent() / 2 - 1), label)
        if self.target is not None:
            pen = QPen(QColor(TARGET), 2.4, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(c, self._pt(c, r - 4, self.target))
        if self.heading is not None:
            col = QColor(NEEDLE)
            tip = self._pt(c, r - 6, self.heading)
            side_a = self._pt(c, 7, self.heading + 90)
            side_b = self._pt(c, 7, self.heading - 90)
            p.setPen(QPen(QColor(0, 0, 0, 160), 1.2))
            p.setBrush(col)
            p.drawPolygon(QPolygonF([tip, side_a, side_b]))
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(text, 1))
        p.setBrush(text)
        p.drawEllipse(c, 3, 3)
        # Gradzahl groß in die Mitte unten
        if self.heading is not None:
            big = QFont(self.font())
            big.setPointSizeF(self.font().pointSizeF() + 6)
            big.setBold(True)
            p.setFont(big)
            t = f"{self.heading}°"
            fm = p.fontMetrics()
            box = QRectF(c.x() - fm.horizontalAdvance(t) / 2 - 4, c.y() + r * 0.35,
                         fm.horizontalAdvance(t) + 8, fm.height())
            bg = QColor(pal.color(QPalette.ColorRole.Base))
            bg.setAlpha(210)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(box, 3, 3)
            p.setPen(text)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, t)
        p.end()

    def mouseMoveEvent(self, e):  # noqa: N802
        b = self.bearing_at(e.position().x(), e.position().y())
        if b is not None and self.enabled_turn:
            QToolTip.showText(e.globalPosition().toPoint(), tr("Klick: auf {az}° drehen", az=b), self)
        else:
            QToolTip.hideText()

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton or not self.enabled_turn:
            return
        b = self.bearing_at(e.position().x(), e.position().y())
        if b is not None and self.on_click:
            self.on_click(b)


class DegreeBox(QSpinBox):
    """Gradzahl; Enter dreht (nur Enter – Fokuswechsel löst nie aus)."""

    def __init__(self, on_enter=None, parent=None):
        super().__init__(parent)
        self.on_enter = on_enter

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.on_enter:
            self.interpretText()
            self.on_enter()
            return
        super().keyPressEvent(e)


class RotorView(QWidget):
    """Inhalt des Fensters. Rückrufe: on_turn(Grad), on_stop(), on_call(long_path), on_setup()."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_turn = self.on_stop = self.on_call = self.on_setup = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.status)
        self.rose = CompassRose()
        self.rose.on_click = lambda az: self.on_turn and self.on_turn(az)
        lay.addWidget(self.rose, 1)
        row = QHBoxLayout()
        self.deg = DegreeBox(lambda: self.btn_go.click())
        self.deg.setRange(0, 359)
        self.deg.setSuffix("°")
        self.deg.setWrapping(True)
        self.btn_go = QPushButton(tr("Drehen"))
        self.btn_go.clicked.connect(lambda: self.on_turn and self.on_turn(self.deg.value()))
        self.btn_stop = QPushButton(tr("Stopp"))
        self.btn_stop.setToolTip(tr("Rotor anhalten (Alt+S)"))
        self.btn_stop.setStyleSheet("font-weight:bold;")
        self.btn_stop.clicked.connect(lambda: self.on_stop and self.on_stop())
        row.addWidget(self.deg)
        row.addWidget(self.btn_go)
        row.addStretch(1)
        row.addWidget(self.btn_stop)
        lay.addLayout(row)
        row = QHBoxLayout()
        self.btn_sp = QPushButton(tr("Short Path"))
        self.btn_sp.setToolTip(tr("Auf den Short Path zum Rufzeichen im Eingabefeld (Alt+R)"))
        self.btn_sp.clicked.connect(lambda: self.on_call and self.on_call(False))
        self.btn_lp = QPushButton(tr("Long Path"))
        self.btn_lp.setToolTip(tr("Auf den Long Path zum Rufzeichen im Eingabefeld (Alt+Shift+R)"))
        self.btn_lp.clicked.connect(lambda: self.on_call and self.on_call(True))
        row.addWidget(self.btn_sp)
        row.addWidget(self.btn_lp)
        lay.addLayout(row)
        self.btn_setup = QPushButton(tr("Rotor einrichten …"))
        self.btn_setup.clicked.connect(lambda: self.on_setup and self.on_setup())
        lay.addWidget(self.btn_setup)
        self.setMinimumWidth(240)
        self.show_state(None)

    def show_state(self, st, call: str = "") -> None:
        """st = rotor.RotorState oder None (kein Rotor eingerichtet)."""
        ready = st is not None and st.connected and st.heading is not None
        for w in (self.deg, self.btn_go, self.btn_stop, self.btn_sp, self.btn_lp):
            w.setEnabled(ready)
        self.rose.enabled_turn = ready
        self.btn_setup.setVisible(st is None)
        if st is None:
            self.status.setText(tr("Kein Rotor eingerichtet"))
            self.rose.heading = self.rose.target = None
        elif not ready:
            self.status.setText(st.error or tr("Verbinde mit dem Rotor …"))
            self.rose.heading = self.rose.target = None
        else:
            self.rose.heading, self.rose.target = st.heading, st.target
            self.status.setText(tr("dreht auf {target}°", target=st.target)
                                if st.target is not None else tr("steht"))
        sp_tip = tr("Auf den Short Path zum Rufzeichen im Eingabefeld (Alt+R)")
        self.btn_sp.setText(tr("SP {call}", call=call) if call else tr("Short Path"))
        self.btn_lp.setText(tr("LP {call}", call=call) if call else tr("Long Path"))
        self.btn_sp.setToolTip(sp_tip)
        self.rose.update()
