"""Erscheinungsbild: System / Hell / Dunkel / Franken hell / Franken dunkel /
Nightshift hell / Nightshift dunkel – jederzeit umschaltbar.

Franken (ab 0.8.10.1): Rot-Weiß wie der Frankenrechen im Logo. Rot nur für den Rahmen
(Menüleiste, Tabellenkopf, aktiver Reiter, Linien) – Rot bleibt in GoGoHam die Signalfarbe
für Dupe und Fehler und soll in den Arbeitsfeldern weiter sofort auffallen.
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

_original = {}


def _remember(app) -> None:
    if not _original:
        _original["style"] = app.style().name()
        _original["palette"] = QPalette(app.palette())


FRANKEN_RED = "#C8102E"          # Rot aus dem Logo
FRANKEN_RED_DARK = "#9E0C24"     # für das dunkle Franken-Design (blendet weniger)


# ---------------------------------------------------------------- Nightshift (0.10.39)
# Farben wie in Ham Pocket: Nachtblau, Bernstein als Hauptfarbe, Türkis-Blau für Auswahl.
NS = {"night": "#060A13", "raised": "#0C1322", "panel": "#111A2D", "panel_high": "#18233A",
      "line": "#26344F", "amber": "#FFB547", "amber_deep": "#FF8A3D", "signal": "#3FE0D0",
      "signal_deep": "#2A9DF4", "text": "#E9EEF8", "muted": "#8C9AB5", "on_amber": "#1E1200"}
AMBER_H = f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {NS['amber']}, stop:1 {NS['amber_deep']})"
AMBER_V = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {NS['amber']}, stop:1 {NS['amber_deep']})"
SIGNAL_H = f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {NS['signal']}, stop:1 {NS['signal_deep']})"
SIGNAL_V = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {NS['signal']}, stop:1 {NS['signal_deep']})"

# Signalfarben je Design (Farbenblind-Regel: Zeichen/Text bleiben, nur Helligkeit passt sich an).
# Auf dem Nachtblau sind die üblichen Farben zu dunkel (Rot 3,1 : 1) → hellere Fassungen.
SIGNALS = {
    "nightshift-dark": {"GREEN": "#4ADE80", "RED": "#FF6B7F", "ORANGE": "#FFB020",
                        "BLUE": "#6CB4FF", "GREY": "#9AA6BD"},
    "nightshift": {"ORANGE": "#B45F00"},       # Orange auf Weiß sonst nur 2,7 : 1
}
# Module mit Signalfarben als Konstanten; apply() stellt sie passend zum Design ein.
SIGNAL_MODULES = ("gogoham.gui.main_window", "gogoham.gui.bandmap", "gogoham.gui.statusbar")
_STATUS_KEYS = {"info": "BLUE", "warn": "ORANGE", "error": "RED"}
_sig_original: dict = {}
_mode = "system"


def is_nightshift(mode: str | None = None) -> bool:
    return (_mode if mode is None else mode) in ("nightshift", "nightshift-dark")


def on_signal() -> str:
    """Schriftfarbe auf einer Signalfarbe als Hintergrund (helle Signalfarben → dunkle Schrift)."""
    return NS["night"] if _mode == "nightshift-dark" else "white"


def _apply_signals(mode: str) -> None:
    over = SIGNALS.get(mode, {})
    for name in SIGNAL_MODULES:
        mod = sys.modules.get(name)
        if mod is None:
            continue
        orig = _sig_original.get(name)
        if orig is None:
            orig = {k: getattr(mod, k) for k in ("GREEN", "RED", "ORANGE", "BLUE", "GREY")
                    if isinstance(getattr(mod, k, None), str)}
            if isinstance(getattr(mod, "COLORS", None), dict):
                orig["COLORS"] = dict(mod.COLORS)
            _sig_original[name] = orig
        for k, v in orig.items():
            if k == "COLORS":
                mod.COLORS.clear()
                mod.COLORS.update({lvl: over.get(_STATUS_KEYS.get(lvl, ""), c) for lvl, c in v.items()})
            else:
                setattr(mod, k, over.get(k, v))


_delegate_cls = None


def _selection_delegate():
    """Delegate erst bei Bedarf bauen (Qt-Attrappen der Tests kennen ihn nicht)."""
    global _delegate_cls
    if _delegate_cls is not None:
        return _delegate_cls
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QLinearGradient
    from PySide6.QtWidgets import QStyle, QStyledItemDelegate

    class SelectionDelegate(QStyledItemDelegate):
        """Nightshift: markierte Zeile mit gedämpftem Grund + Türkis-Balken links; die eigene
        Schriftfarbe einer Zelle (Dupe, Multi …) bleibt auch in der markierten Zeile erhalten."""

        def initStyleOption(self, option, index):
            super().initStyleOption(option, index)
            if is_nightshift() and index.data(Qt.ItemDataRole.ForegroundRole) is not None:
                option.palette.setBrush(QPalette.ColorRole.HighlightedText,
                                        option.palette.brush(QPalette.ColorRole.Text))

        def paint(self, painter, option, index):
            super().paint(painter, option, index)
            if not (is_nightshift() and option.state & QStyle.StateFlag.State_Selected):
                return
            hdr = getattr(self.parent(), "horizontalHeader", None)
            if hdr is not None:
                h = hdr()
                first = next((h.logicalIndex(v) for v in range(h.count())
                              if not h.isSectionHidden(h.logicalIndex(v))), 0)
                if index.column() != first:
                    return
            r = option.rect
            g = QLinearGradient(0, r.top(), 0, r.bottom())
            g.setColorAt(0, QColor(NS["signal"]))
            g.setColorAt(1, QColor(NS["signal_deep"]))
            painter.save()
            painter.fillRect(QRectF(r.left(), r.top(), 4, r.height()), g)
            painter.restore()

    _delegate_cls = SelectionDelegate
    return _delegate_cls


def install_selection(view) -> None:
    """Markierungs-Darstellung für Nightshift an einer Tabelle/Liste anbringen
    (in anderen Designs verhält sie sich wie gewohnt)."""
    try:
        view.setItemDelegate(_selection_delegate()(view))
    except (ImportError, TypeError, AttributeError):     # Qt-Attrappe in Tests
        pass


def _palette(dark: bool, franken: bool = False, nightshift: bool = False) -> QPalette:
    p = QPalette()
    R = QPalette.ColorRole
    if nightshift and dark:
        colors = {
            R.Window: NS["raised"], R.WindowText: NS["text"], R.Base: NS["panel"],
            R.AlternateBase: NS["panel_high"], R.ToolTipBase: NS["panel_high"],
            R.ToolTipText: NS["text"], R.Text: NS["text"], R.Button: NS["panel_high"],
            R.ButtonText: NS["text"], R.BrightText: "#FF6B7F", R.Highlight: "#0E2F38",
            R.HighlightedText: NS["text"], R.Link: NS["signal"], R.PlaceholderText: NS["muted"],
            R.Mid: NS["line"], R.Dark: NS["night"], R.Light: "#2E3E5C",
        }
    elif nightshift:
        colors = {
            R.Window: "#F4F6FA", R.WindowText: "#1A2233", R.Base: "#ffffff",
            R.AlternateBase: "#F2F5FA", R.ToolTipBase: "#FFF6E8", R.ToolTipText: "#1A2233",
            R.Text: "#1A2233", R.Button: "#E9EDF4", R.ButtonText: "#1A2233",
            R.BrightText: "#c62828", R.Highlight: "#D3F3EF", R.HighlightedText: "#1A2233",
            R.Link: "#1565c0", R.PlaceholderText: "#5A6884", R.Mid: "#D5DCE8",
        }
    elif franken and dark:
        colors = {
            R.Window: "#2a2526", R.WindowText: "#ece8e8", R.Base: "#1d1a1b",
            R.AlternateBase: "#2c2425", R.ToolTipBase: "#3a2f30", R.ToolTipText: "#f4f0f0",
            R.Text: "#eeeaea", R.Button: "#3a3132", R.ButtonText: "#ece8e8",
            R.BrightText: "#ff5252", R.Highlight: "#6e2a34", R.HighlightedText: "#ffffff",
            R.Link: "#ff8a9a", R.PlaceholderText: "#8f8586",
        }
    elif franken:
        colors = {
            R.Window: "#faf6f4", R.WindowText: "#1a1a1a", R.Base: "#ffffff",
            R.AlternateBase: "#fbf0f0", R.ToolTipBase: "#fff8f0", R.ToolTipText: "#1a1a1a",
            R.Text: "#1a1a1a", R.Button: "#f2e6e6", R.ButtonText: "#1a1a1a",
            R.BrightText: "#c62828", R.Highlight: "#f3c4ca", R.HighlightedText: "#1a1a1a",
            R.Link: "#a30d25", R.PlaceholderText: "#8a8a8a",
        }
    elif dark:
        colors = {
            R.Window: "#2b2b2b", R.WindowText: "#e8e8e8", R.Base: "#1e1e1e",
            R.AlternateBase: "#2f2f2f", R.ToolTipBase: "#3a3a3a", R.ToolTipText: "#f0f0f0",
            R.Text: "#ececec", R.Button: "#353535", R.ButtonText: "#e8e8e8",
            R.BrightText: "#ff5252", R.Highlight: "#3d6fb4", R.HighlightedText: "#ffffff",
            R.Link: "#6cb4ff", R.PlaceholderText: "#8a8a8a",
        }
    else:
        colors = {
            R.Window: "#f0f0f0", R.WindowText: "#1a1a1a", R.Base: "#ffffff",
            R.AlternateBase: "#f5f5f5", R.ToolTipBase: "#ffffdc", R.ToolTipText: "#1a1a1a",
            R.Text: "#1a1a1a", R.Button: "#e6e6e6", R.ButtonText: "#1a1a1a",
            R.BrightText: "#c62828", R.Highlight: "#3d6fb4", R.HighlightedText: "#ffffff",
            R.Link: "#1565c0", R.PlaceholderText: "#8a8a8a",
        }
    for role, c in colors.items():
        p.setColor(role, QColor(c))
    dis = QPalette.ColorGroup.Disabled
    for role in (R.Text, R.WindowText, R.ButtonText):
        p.setColor(dis, role, QColor("#5A6884" if nightshift and dark else "#777777"))
    return p


def is_dark(app=None) -> bool:
    app = app or QApplication.instance()
    try:
        return app.palette().color(QPalette.ColorRole.Window).lightness() < 128
    except Exception:  # noqa: BLE001
        return False


def _franken_sheet(dark: bool) -> str:
    """Rote Rahmen-Teile; alles andere kommt aus der Palette."""
    red = FRANKEN_RED_DARK if dark else FRANKEN_RED
    hover = "#7e0a1d" if dark else "#a30d25"
    return f"""
QMenuBar {{ background:{red}; color:white; }}
QMenuBar::item {{ background:transparent; color:white; padding:4px 10px; }}
QMenuBar::item:selected, QMenuBar::item:pressed {{ background:{hover}; }}
QHeaderView::section {{ background:{red}; color:white; border:none;
    border-right:1px solid {hover}; padding:3px 6px; font-weight:bold; }}
QHeaderView#score_header::section {{ padding:3px 2px; }}
QTabBar::tab:selected {{ background:{red}; color:white; }}
QStatusBar {{ border-top:2px solid {red}; }}
QDockWidget::title {{ background:{red}; color:white; padding:3px; }}
QPushButton:default {{ border:2px solid {red}; }}
"""


def _nightshift_sheet(dark: bool) -> str:
    """Verläufe wie in Ham Pocket. Bernstein nur im Rahmen (Menü, Köpfe, Reiter, Hauptknopf),
    nie in den Arbeitsfeldern – dort bleiben die Signalfarben unter sich."""
    if dark:
        bar = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {NS['panel_high']}, stop:1 {NS['night']})"
        btn = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1E2A44, stop:1 {NS['panel']})"
        btn_hover = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #26365A, stop:1 {NS['panel_high']})"
        group = ("qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(24,35,58,0.85), "
                 "stop:1 rgba(12,19,34,0.35))")
        glow = (f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2A2218, stop:0.28 {NS['raised']}, "
                f"stop:0.72 {NS['raised']}, stop:1 #0E2238)")
        fg, line, muted, tab = NS["text"], NS["line"], NS["muted"], NS["panel"]
        fill = NS["panel_high"]
    else:
        bar = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFFFFF, stop:1 #E6EBF3)"
        btn = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFFFFF, stop:1 #E4E9F1)"
        btn_hover = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFFFFF, stop:1 #D9E0EB)"
        group = ("qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255,255,255,0.9), "
                 "stop:1 rgba(233,237,244,0.5))")
        glow = ("qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FCEBD6, stop:0.28 #F4F6FA, "
                "stop:0.72 #F4F6FA, stop:1 #DCEBFA)")
        fg, line, muted, tab = "#1A2233", "#C9D2E0", "#5A6884", "#E9EDF4"
        fill = "#E9EDF4"
    on = NS["on_amber"]
    return f"""
QMainWindow, QDialog {{ background:{glow}; }}
QMenuBar {{ background:{bar}; color:{fg}; border-bottom:2px solid {AMBER_H}; }}
QMenuBar::item {{ background:transparent; color:{fg}; padding:4px 10px; border-radius:4px; }}
QMenuBar::item:selected, QMenuBar::item:pressed {{ background:{AMBER_V}; color:{on}; }}
QMenu {{ border:1px solid {line}; }}
QMenu::item:selected {{ background:{AMBER_H}; color:{on}; }}
QDockWidget::title {{ background:{bar}; color:{fg}; padding:4px;
    border-bottom:2px solid {AMBER_H}; }}
QHeaderView::section {{ background:{AMBER_V}; color:{on}; border:none;
    border-right:1px solid {NS['amber_deep']}; padding:3px 6px; font-weight:bold; }}
QHeaderView#score_header::section {{ padding:3px 2px; }}
QTableCornerButton::section {{ background:{AMBER_V}; border:none; }}
QTabBar::tab {{ background:{tab}; color:{muted}; border:1px solid {line}; border-bottom:none;
    border-top-left-radius:6px; border-top-right-radius:6px; padding:4px 12px; margin-right:2px; }}
QTabBar::tab:hover {{ color:{fg}; }}
QTabBar::tab:selected {{ background:{AMBER_V}; color:{on}; font-weight:bold; }}
QPushButton {{ background:{btn}; color:{fg}; border:1px solid {line}; border-radius:6px;
    padding:4px 12px; min-height:18px; }}
QPushButton:hover {{ background:{btn_hover}; border-color:{NS['signal_deep']}; }}
QPushButton:pressed {{ background:{fill}; }}
QPushButton:checked {{ border:2px solid {NS['signal_deep']}; }}
QPushButton:disabled {{ color:{muted}; }}
QPushButton:default {{ background:{AMBER_V}; color:{on}; border:1px solid {NS['amber_deep']};
    font-weight:bold; }}
QPushButton:default:hover {{ border:2px solid {NS['signal_deep']}; }}
QGroupBox {{ background:{group}; border:1px solid {line}; border-radius:8px;
    margin-top:1.2em; padding-top:6px; }}
QGroupBox::title {{ subcontrol-origin:margin; subcontrol-position:top left; left:10px;
    padding:0 4px; color:{fg}; font-weight:bold; }}
QStatusBar {{ border-top:1px solid {line}; }}
QProgressBar {{ border:1px solid {line}; border-radius:5px; text-align:center; }}
QProgressBar::chunk {{ background:{SIGNAL_H}; border-radius:4px; }}
QScrollBar:vertical {{ background:transparent; width:12px; margin:0; }}
QScrollBar::handle:vertical {{ background:{SIGNAL_V}; border-radius:5px; min-height:24px; margin:2px; }}
QScrollBar:horizontal {{ background:transparent; height:12px; margin:0; }}
QScrollBar::handle:horizontal {{ background:{SIGNAL_H}; border-radius:5px; min-width:24px; margin:2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background:none; }}
QToolTip {{ border:1px solid {NS['amber_deep']}; }}
"""


def is_franken(mode: str) -> bool:
    return mode in ("franken", "franken-dark")


def apply(mode: str) -> None:
    global _mode
    app = QApplication.instance()
    if app is None:
        return
    _remember(app)
    _mode = mode
    _apply_signals(mode)
    app.setStyleSheet("")
    if mode == "dark":
        app.setStyle("Fusion")
        app.setPalette(_palette(True))
    elif mode == "light":
        app.setStyle("Fusion")
        app.setPalette(_palette(False))
    elif is_franken(mode):
        dark = mode == "franken-dark"
        app.setStyle("Fusion")
        app.setPalette(_palette(dark, franken=True))
        app.setStyleSheet(_franken_sheet(dark))
    elif is_nightshift(mode):
        dark = mode == "nightshift-dark"
        app.setStyle("Fusion")
        app.setPalette(_palette(dark, nightshift=True))
        app.setStyleSheet(_nightshift_sheet(dark))
    else:
        app.setStyle(_original.get("style") or "Fusion")
        if "palette" in _original:
            app.setPalette(_original["palette"])
