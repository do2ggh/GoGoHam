"""Minimale PySide6-Attrappe, um die GUI-Logik ohne Qt testen zu können.

Bildet nur das Verhalten nach, das GoGoHam benutzt (Text in Feldern,
Combo-Boxen, Tabellenzeilen, Signale). Alles andere sind No-ops.
"""

import sys
import types


class Enumish:
    def __init__(self, name="E"):
        self._n = name

    def __getattr__(self, k):
        if k.startswith("__"):
            raise AttributeError(k)
        return Enumish(f"{self._n}.{k}")

    def __or__(self, o):
        return Enumish(f"{self._n}|{o._n}")

    def __eq__(self, o):
        return isinstance(o, Enumish) and o._n == self._n

    def __hash__(self):
        return hash(self._n)

    def __call__(self, *a, **k):
        return Enumish(self._n + "()")


class Signal:
    def __init__(self):
        self.slots = []

    def connect(self, f):
        self.slots.append(f)

    def emit(self, *a):
        for f in list(self.slots):
            f(*a)


class Meta(type):
    def __getattr__(cls, k):
        if k.startswith("__"):
            raise AttributeError(k)
        return Enumish(f"{cls.__name__}.{k}")


class Stub(metaclass=Meta):
    _signals = ()

    def __init__(self, *a, **k):
        for s in self._signals:
            setattr(self, s, Signal())
        self._visible = True

    def __getattr__(self, k):
        if k.startswith("__"):
            raise AttributeError(k)
        if k == "aboutToShow":                 # Menü-Signal (Digitalprogramm starten, 0.10.6)
            sig = Signal()
            object.__setattr__(self, k, sig)
            return sig
        return lambda *a, **kw: Stub()

    def setVisible(self, v):
        self._visible = v

    def isVisible(self):
        return self._visible


class QWidget(Stub):
    def fontMetrics(self):
        return QFontMetrics()


class QLabel(Stub):
    _signals = ("linkActivated",)

    def __init__(self, text="", *a):
        super().__init__()
        self._t = text

    def fontMetrics(self):
        return QFontMetrics()

    def setText(self, t):
        self._t = t

    def text(self):
        return self._t

    def width(self):
        return 400


class _Rect(Stub):
    def width(self):
        return 100

    def height(self):
        return 100


class QGridLayout(Stub):
    def cellRect(self, *a):
        return _Rect()

    def horizontalSpacing(self):
        return 6


class QFontMetrics(Stub):
    """Grobe Textbreite: 10 Punkte je Zeichen."""
    def horizontalAdvance(self, t):
        return 10 * len(t)

    def height(self):
        return 20

    def lineSpacing(self):
        return 20

    def elidedText(self, t, *a):
        return t

    def averageCharWidth(self):
        return 8


class QLineEdit(Stub):
    _signals = ("textEdited", "returnPressed", "textChanged")

    def __init__(self, text="", *a):
        super().__init__()
        self._t = text
        self._c = len(text)

    def text(self):
        return self._t

    def setText(self, t):
        self._t = t
        self._c = len(t)

    def clear(self):
        self._t = ""

    def cursorPosition(self):
        return self._c

    def setCursorPosition(self, c):
        self._c = c

    def type(self, t):  # Testhilfe: Nutzer tippt
        self._t += t
        self.textEdited.emit(self._t)


class QPlainTextEdit(Stub):
    def __init__(self, text="", *a):
        super().__init__()
        self._t = text

    def toPlainText(self):
        return self._t


class QComboBox(Stub):
    _signals = ("currentTextChanged", "currentIndexChanged")

    def __init__(self, *a):
        super().__init__()
        self.items, self.data, self.cur = [], [], -1

    def addItems(self, items):
        for i in items:
            self.addItem(i)

    def clear(self):
        self.items, self.data, self.cur = [], [], -1

    def count(self):
        return len(self.items)

    def itemText(self, i):
        return self.items[i]

    def addItem(self, t, d=None):
        self.items.append(t)
        self.data.append(d)
        if self.cur < 0:
            self.cur = 0

    def currentText(self):
        return self.items[self.cur] if self.cur >= 0 else ""

    def setCurrentText(self, t):
        if t in self.items:
            i = self.items.index(t)
            if i != self.cur:
                self.cur = i
                self.currentTextChanged.emit(t)

    def findText(self, t):
        return self.items.index(t) if t in self.items else -1

    def findData(self, d):
        return self.data.index(d) if d in self.data else -1

    def setCurrentIndex(self, i):
        self.cur = i
        self.currentIndexChanged.emit(i)

    def currentData(self):
        return self.data[self.cur]


class QSpinBox(Stub):
    _signals = ("valueChanged",)

    def __init__(self, *a):
        super().__init__()
        self.v = 0

    def setValue(self, v):
        self.v = v

    def value(self):
        return self.v


class QCheckBox(Stub):
    _signals = ("toggled",)                 # Grayline-Karte (0.8.15)

    def __init__(self, *a):
        super().__init__()
        self.c = False

    def setChecked(self, c):
        self.c = c

    def isChecked(self):
        return self.c


class QTableWidgetItem(Stub):
    def __init__(self, text=""):
        super().__init__()
        self._t = text
        self._d = None
        self.icon = None

    def setIcon(self, i):
        self.icon = i

    def text(self):
        return self._t

    def setData(self, role, v):
        self._d = v

    def data(self, role):
        return self._d


class FakeHeader(Stub):
    _signals = ("sectionMoved", "sectionResized", "customContextMenuRequested")

    def __init__(self, n):
        super().__init__()
        self.visual = list(range(n))       # visual position -> logical index
        self.labels = []

    def visualIndex(self, logical):
        return self.visual.index(logical)

    def logicalIndex(self, visual):
        return self.visual[visual]

    def fontMetrics(self):
        return QFontMetrics()

    def minimumSectionSize(self):
        return 20

    def moveSection(self, frm, to):
        lg = self.visual.pop(frm)
        self.visual.insert(to, lg)
        self.sectionMoved.emit(lg, frm, to)


class QTabWidget(Stub):
    def __init__(self, *a):
        super().__init__()
        self.tabs = []

    def addTab(self, w, label):
        self.tabs.append((w, label))

    def clear(self):
        self.tabs = []

    def count(self):
        return len(self.tabs)

    def tabText(self, i):
        return self.tabs[i][1]

    def setCurrentIndex(self, i):          # Einstellungen mit Unterreitern (0.10.4)
        self._cur = i

    def currentIndex(self):
        return getattr(self, "_cur", 0)


class QTableWidget(Stub):
    def viewport(self):
        return _Rect()

    _signals = ("customContextMenuRequested", "doubleClicked", "cellDoubleClicked")

    def __init__(self, r=0, c=0):
        super().__init__()
        self.rows = [dict() for _ in range(r)]
        self.cols = c
        self._hdr = FakeHeader(c)
        self.hidden = set()
        self.widths = {}

    def horizontalHeader(self):
        return self._hdr

    def setHorizontalHeaderLabels(self, labels):
        self._hdr.labels = list(labels)

    def setColumnHidden(self, c, h):
        (self.hidden.add if h else self.hidden.discard)(c)

    def isColumnHidden(self, c):
        return c in self.hidden

    def setColumnWidth(self, c, w):
        self.widths[c] = w
        self._hdr.sectionResized.emit(c, 0, w)

    def horizontalHeaderItem(self, c):
        return QTableWidgetItem("Spalte")

    def columnWidth(self, c):
        return 0 if c in self.hidden else self.widths.get(c, 100)

    def rowCount(self):
        return len(self.rows)

    def setRowCount(self, n):
        self.rows = self.rows[:n] + [dict() for _ in range(n - len(self.rows))]

    def insertRow(self, r):
        self.rows.insert(r, {})

    def setItem(self, r, c, it):
        self.rows[r][c] = it

    def item(self, r, c):
        return self.rows[r].get(c)

    def setColumnCount(self, n):
        self.cols = n


class QListWidgetItem(Stub):
    def __init__(self, text=""):
        super().__init__()
        self._t, self._d, self.color = text, None, None

    def text(self):
        return self._t

    def setData(self, role, v):
        self._d = v

    def data(self, role):
        return self._d

    def setForeground(self, brush):
        self.color = brush.color


class QListWidget(Stub):
    _signals = ("itemDoubleClicked", "itemClicked", "customContextMenuRequested",
                "currentItemChanged", "currentRowChanged")

    def __init__(self, *a):
        super().__init__()
        self.items = []
        self._row = -1

    def addItem(self, t):
        self.items.append(t)

    def clear(self):
        self.items = []
        self._row = -1

    def count(self):
        return len(self.items)

    def item(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def currentRow(self):
        return self._row

    def currentItem(self):
        return self.item(self._row)

    def setCurrentRow(self, i):
        self._row = i
        self.currentRowChanged.emit(i)


class QPushButton(Stub):
    _signals = ("clicked",)

    def __init__(self, t="", *a):
        super().__init__()
        self._t = t
        self._checked = False

    def setChecked(self, c):
        self._checked = c

    def isChecked(self):
        return self._checked

    def setText(self, t):
        self._t = t

    def text(self):
        return self._t


class QDialogButtonBox(Stub):
    _signals = ("accepted", "rejected")

    def addButton(self, *a):
        return QPushButton(a[0] if a and isinstance(a[0], str) else "")


class QAction(Stub):
    _signals = ("triggered", "toggled")


class QShortcut(Stub):
    _signals = ("activated",)


class QTimer(Stub):
    _signals = ("timeout",)

    def __init__(self, *a):
        super().__init__()
        self.active, self.interval = False, 0

    def start(self, ms=None):
        self.active = True
        if ms is not None:
            self.interval = ms

    def stop(self):
        self.active = False

    def isActive(self):
        return self.active

    @staticmethod
    def singleShot(ms, f):
        pass


class QMessageBox(Stub):
    answer = None

    @staticmethod
    def question(*a, **k):
        return QMessageBox.StandardButton.Yes

    @staticmethod
    def warning(*a, **k):
        QMessageBox.last = a

    information = critical = about = warning


class QInputDialog(Stub):
    @staticmethod
    def getText(*a, **k):
        return "", False

    @staticmethod
    def getItem(*a, **k):
        return "", False


class QDialog(Stub):
    def accept(self):
        self._accepted = True

    def reject(self):
        self._accepted = False

    def exec(self):
        self._accepted = False
        self.accept()          # simuliert Klick auf OK
        return 1 if self._accepted else 0


class QMainWindow(Stub):
    def __init__(self, *a):
        super().__init__()
        self._sb = _StatusBar()

    def statusBar(self):
        return self._sb

    def setStatusBar(self, sb):
        self._sb = sb

    def menuBar(self):
        return Stub()


class _StatusBar(Stub):
    msg = ""

    def showMessage(self, m, t=0, *a, **k):
        self.msg = m

    def currentMessage(self):
        return self.msg

    def addWidget(self, *a, **k):
        pass


class QStatusBar(_StatusBar):
    pass


class QFileDialog(Stub):
    save_path = ""

    @staticmethod
    def getSaveFileName(*a, **k):
        return QFileDialog.save_path, ""

    @staticmethod
    def getOpenFileName(*a, **k):
        return "", ""


class QFont(Stub):
    pass


class QColor(Stub):
    def __init__(self, c="", *a):
        super().__init__()
        self.name_ = c


class QBrush(Stub):
    def __init__(self, color=None, *a):
        super().__init__()
        self.color = color.name_ if color is not None else None


class QDockWidget(Stub):
    _signals = ("visibilityChanged",)


class QProgressDialog(Stub):
    def __init__(self, *a):
        super().__init__()
        self.value = 0

    def wasCanceled(self):
        return False

    def setValue(self, v):
        self.value = v


def install():
    qtw = types.ModuleType("PySide6.QtWidgets")
    qtg = types.ModuleType("PySide6.QtGui")
    qtc = types.ModuleType("PySide6.QtCore")
    g = globals()
    for name in ["QAbstractItemView", "QApplication", "QFrame", "QGroupBox",
                 "QHBoxLayout", "QHeaderView", "QMenu", "QSplitter", "QVBoxLayout",
                 "QFormLayout", "QProgressBar", "QSlider", "QSizePolicy"]:
        setattr(qtw, name, type(name, (Stub,), {"_signals": ("accepted", "rejected")}))
    for name in ["QComboBox", "QDialog", "QFileDialog", "QLabel", "QLineEdit", "QListWidget",
                 "QMainWindow", "QMessageBox", "QPushButton", "QTableWidget",
                 "QTableWidgetItem", "QWidget", "QSpinBox", "QCheckBox", "QPlainTextEdit",
                 "QListWidgetItem", "QDockWidget", "QDialogButtonBox", "QInputDialog"]:
        setattr(qtw, name, g[name])
    for name in ["QAction", "QShortcut", "QFont", "QFontMetrics"]:
        setattr(qtg, name, g[name])
    for name in ["QGridLayout", "QStatusBar"]:
        setattr(qtw, name, g[name])
    for name in []:
        setattr(qtg, name, g[name])
    for name in ["QKeySequence", "QPixmap", "QIcon", "QActionGroup", "QPalette",
                 "QDesktopServices", "QPainter", "QPen"]:
        setattr(qtg, name, type(name, (Stub,), {}))
    qtg.QColor = QColor
    qtg.QBrush = QBrush
    qtc.Qt = type("Qt", (Stub,), {})
    qtc.QEvent = type("QEvent", (Stub,), {})
    qtc.QTimer = QTimer
    qtc.QObject = type("QObject", (Stub,), {})          # Uhrzeit-Prüfung (0.8.18.3)
    qtc.QProcess = type("QProcess", (Stub,), {})
    qtc.QSize = type("QSize", (Stub,), {})
    qtc.QUrl = type("QUrl", (Stub,), {})
    qtc.QRectF = type("QRectF", (Stub,), {})
    qtc.QPointF = type("QPointF", (Stub,), {})          # Grayline-Karte (0.8.15)
    for name in ["QImage", "QPainterPath", "QPolygonF", "QSyntaxHighlighter", "QTextCharFormat",
                 "QTextCursor"]:                                   # RTTY-Fenster (0.10.5)
        setattr(qtg, name, type(name, (Stub,), {}))
    qtw.QToolTip = type("QToolTip", (Stub,), {})
    qtw.QTabWidget = QTabWidget
    qtw.QTextBrowser = type("QTextBrowser", (Stub,), {})
    qtw.QScrollArea = type("QScrollArea", (Stub,), {})
    qtw.QLayout = type("QLayout", (Stub,), {})                    # fitscreen (0.10.12)
    qtw.QStackedWidget = type("QStackedWidget", (Stub,), {})      # Einstellungen (0.10.4)
    qtw.QProgressDialog = QProgressDialog
    pkg = types.ModuleType("PySide6")
    pkg.QtWidgets, pkg.QtGui, pkg.QtCore = qtw, qtg, qtc
    sys.modules.update({"PySide6": pkg, "PySide6.QtWidgets": qtw, "PySide6.QtGui": qtg,
                        "PySide6.QtCore": qtc})
