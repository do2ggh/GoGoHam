"""Fenster passen auf den Bildschirm – mit Taskleiste (ab 0.10.12).

Auf Laptops (Full HD mit 125 %, 1366×768) waren manche Fenster höher als der Bildschirm. Plasma
schneidet sie dann ab, Qt drückt den Inhalt zusammen, Zeilen rutschen übereinander und die Knöpfe
unten liegen hinter der Taskleiste.

Darum begrenzt ein Ereignisfilter für die ganze Anwendung jedes Fenster beim Öffnen auf die freie
Fläche des Bildschirms (`availableGeometry` = ohne Taskleiste, egal wo sie sitzt) und schiebt es
ganz hinein. Fenster mit viel Inhalt haben dafür einen Scrollbereich (`scroll_wrap`), die Knöpfe
bleiben außerhalb und damit immer sichtbar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QFrame, QLayout, QScrollArea, QWidget

if TYPE_CHECKING:                     # Tests ersetzen Qt teilweise durch Attrappen
    from PySide6.QtCore import QRect

# Rand für Fensterrahmen und Titelleiste, die Qt vor dem ersten Zeigen noch nicht kennt
FRAME_W = 16
FRAME_H = 48


def available(w: QWidget | None = None) -> QRect | None:
    scr = (w.screen() if w is not None else None) or QApplication.primaryScreen()
    return scr.availableGeometry() if scr is not None else None


def fit(w: QWidget, avail: QRect | None = None) -> None:
    """Größe auf die freie Fläche begrenzen und das Fenster ganz hineinschieben."""
    if w.isMaximized() or w.isFullScreen():
        return
    a = avail or available(w)
    if a is None or a.width() < 200 or a.height() < 200:
        return
    max_w, max_h = a.width() - FRAME_W, a.height() - FRAME_H
    # Mindestgröße darf nicht über den Bildschirm hinausgehen (Inhalt scrollt dann)
    if w.minimumWidth() > max_w:
        w.setMinimumWidth(max_w)
    if w.minimumHeight() > max_h:
        w.setMinimumHeight(max_h)
    if w.width() > max_w or w.height() > max_h:
        w.resize(min(w.width(), max_w), min(w.height(), max_h))
    g = w.frameGeometry()
    x = min(max(g.x(), a.x()), a.right() + 1 - g.width())
    y = min(max(g.y(), a.y()), a.bottom() + 1 - g.height())
    if (x, y) != (g.x(), g.y()):
        w.move(max(x, a.x()), max(y, a.y()))


def scroll_wrap(layout: QLayout) -> QScrollArea:
    """Inhalt in einen Scrollbereich ohne Rahmen packen: Ist genug Platz da, sieht man keinen
    Unterschied; ist er knapp, wird gescrollt statt zusammengedrückt."""
    inner = QWidget()
    inner.setLayout(layout)
    return scroll_widget(inner)


def scroll_widget(inner: QWidget) -> QScrollArea:
    """Wie scroll_wrap, für eine fertige Seite (z. B. in den Einstellungen)."""
    area = _Area()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(inner)
    # So hoch wie der Inhalt, wenn es passt – fit() begrenzt danach das ganze Fenster
    h = inner.sizeHint().height()
    if isinstance(h, int):                        # (Qt-Attrappe in den Tests liefert keine Zahl)
        area.setMinimumHeight(min(h, 300))
    return area


class _Area(QScrollArea):
    """Wünscht sich die volle Höhe des Inhalts (QScrollArea nimmt sonst nur wenig)."""

    def sizeHint(self):  # noqa: N802 – Qt-Name
        w = self.widget()
        if w is None:
            return super().sizeHint()
        m = self.contentsMargins()
        s = w.sizeHint()
        # Breite mit Platz für den Scrollbalken, falls er gebraucht wird
        return type(s)(s.width() + m.left() + m.right() + self.verticalScrollBar().sizeHint().width(),
                     s.height() + m.top() + m.bottom())


class ScreenFit(QObject):
    """Ereignisfilter für die ganze Anwendung: jedes Fenster beim Zeigen einpassen."""

    def eventFilter(self, obj, ev):  # noqa: N802 – Qt-Name
        if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            t = obj.windowType()
            if t not in (Qt.WindowType.Popup, Qt.WindowType.ToolTip, Qt.WindowType.SplashScreen):
                try:
                    fit(obj)
                except RuntimeError:              # Fenster wird gerade gelöscht
                    pass
        return False


def install(app: QApplication) -> ScreenFit:
    f = ScreenFit(app)
    app.installEventFilter(f)
    return f
