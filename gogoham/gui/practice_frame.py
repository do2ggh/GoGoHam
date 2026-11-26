"""Übungsmodus unübersehbar markieren (ab 0.10.19): leuchtend gelber Rand ums Hauptfenster.

Nutzerwunsch: Man vergisst in der Übung schnell, dass es eine Übung ist – und greift womöglich
zum Mikrofon. Der Rand liegt als durchsichtige Schicht über allem (Mausklicks gehen hindurch)
und folgt der Fenstergröße.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

YELLOW = "#ffd600"
WIDTH = 8                                   # Randbreite in Pixeln
BAR_STYLE = (f"background:{YELLOW}; color:black; font-weight:bold;")
CALL_STYLE = "QLineEdit { background:#fff59d; color:black; }"


class PracticeFrame(QWidget):
    """Gelber Rahmen über dem ganzen Fenster; nur sichtbar, solange geübt wird."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._watch = _Watch(self)
        parent.installEventFilter(self._watch)
        self.hide()

    def follow(self) -> None:
        p = self.parentWidget()
        if p is not None:
            self.setGeometry(p.rect())
        self.raise_()

    def set_on(self, on: bool) -> None:
        # 0.10.19.1 (Nutzer): Der Rand lag über Menüleiste und Funkwetter. Jetzt rückt der
        # Fensterinhalt um die Randbreite nach innen – gemalt wird nur im frei gewordenen Streifen.
        p = self.parentWidget()
        if on:
            if p is not None and not self.isVisible():
                self._margins = p.contentsMargins()
                p.setContentsMargins(WIDTH, WIDTH, WIDTH, WIDTH)
            self.follow()
            self.show()
        else:
            if p is not None and self.isVisible():
                m = getattr(self, "_margins", None)
                if m is not None:
                    p.setContentsMargins(m)
                else:
                    p.setContentsMargins(0, 0, 0, 0)
            self.hide()

    def paintEvent(self, _ev) -> None:  # noqa: N802 (Qt-Name)
        p = QPainter(self)
        pen = QPen(QColor(YELLOW))
        pen.setWidth(WIDTH)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)
        h = WIDTH // 2
        p.drawRect(self.rect().adjusted(h, h, -h, -h))
        p.end()


class _Watch(QObject):
    """Größe ändern und neue Unterfenster (Docks): Rahmen wieder obenauf legen."""

    def __init__(self, frame: PracticeFrame) -> None:
        super().__init__(frame)
        self.frame = frame

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 (Qt-Name)
        if self.frame.isVisible() and ev.type() in (
                QEvent.Type.Resize, QEvent.Type.ChildAdded, QEvent.Type.LayoutRequest,
                QEvent.Type.Show):
            self.frame.follow()
        return False
