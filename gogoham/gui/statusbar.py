"""Untere Leiste mit zwei Zeilen (ab 0.8.13, Wunsch des Nutzers).

Oben (Platz für zwei Zeilen): wechselnde Hinweise (QSY, Funkgerät, Fehler …) als farbige
Schrift – blau = Hinweis, orange = Warnung, rot = Fehler (0.8.13: ohne gefüllten Hintergrund,
Wunsch des Nutzers – ruhiger fürs Auge). Gibt es nichts Neues, stehen hier die ⚠-Hinweise zum gerade
getippten Rufzeichen (z. B. Band-/Modewechsel), sonst bleibt die Zeile leer.
Unten: links das Funkwetter, rechts die dauernden Anzeigen (Cluster, WSJT-X, cty.dat, SCP …).

Alle bisherigen statusBar().showMessage()-Aufrufe landen automatisch in der oberen Zeile –
so kann keine Meldung das Funkwetter verdecken.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QStatusBar, QVBoxLayout, QWidget

from ..i18n import tr

INFO, WARN, ERROR = "info", "warn", "error"
COLORS = {INFO: "#1565c0", WARN: "#e08a00", ERROR: "#c62828"}


class HintStatusBar(QStatusBar):
    def __init__(self, font_size: int = 15, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(False)
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 2, 0, 0)
        v.setSpacing(3)
        self.hint = QLabel("")
        f = QFont()
        f.setPointSize(font_size)
        f.setBold(True)
        self.hint.setFont(f)
        self.hint.setWordWrap(True)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        # nie breiter machen als das Fenster; zwei Zeilen Platz, damit nichts springt
        self.hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.hint.setFixedHeight(2 * QFontMetrics(f).lineSpacing() + 2)
        v.addWidget(self.hint)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        self.weather = QLabel("")
        self.weather.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self.weather)
        row.addStretch(1)
        self._right = row
        v.addLayout(row)
        super().addWidget(box, 1)
        self._msg, self._level = "", INFO
        self._notes = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clearMessage)

    # ---- wie QStatusBar, aber in die obere Zeile
    def showMessage(self, text: str, timeout: int = 0, level: str = INFO,  # noqa: N802
                    speak: bool = True) -> None:
        self._msg, self._level = text or "", level
        cb = getattr(self, "on_message", None)          # Ansagen (0.8.26)
        if cb and self._msg and speak:     # speak=False: hat eine eigene Ansage (0.10.3)
            cb(self._msg, level)
        from .. import applog
        applog.message(self._msg, level)          # fürs Protokoll / den Fehlerbericht
        self.hint.setToolTip(self._msg)
        if timeout and self._msg:
            self._timer.start(int(timeout))
        else:
            self._timer.stop()
        self._render()

    def clearMessage(self) -> None:  # noqa: N802
        self._timer.stop()
        self._msg = ""
        self.hint.setToolTip("")
        self._render()

    def currentMessage(self) -> str:  # noqa: N802
        return self._msg

    def addPermanentWidget(self, w, stretch: int = 0) -> None:  # noqa: N802
        self._right.addWidget(w, stretch)

    # ---- eigene Teile
    def set_notes(self, text: str) -> None:
        """Dauernde ⚠-Hinweise zum gerade getippten Rufzeichen (leer = keine)."""
        self._notes = text or ""
        self._render()

    def notes(self) -> str:
        return self._notes

    def _render(self) -> None:
        text, level = (self._msg, self._level) if self._msg else (self._notes, WARN)
        self.hint.setText(text)
        self.hint.setStyleSheet(f"color:{COLORS.get(level, COLORS[INFO])}; padding:0 4px;"
                                if text else "")


def weather_html(w, band: str) -> tuple[str, str]:
    """Text (mit Farben) und Tooltip für das Funkwetter; w = SpaceWeather oder None."""
    from .. import spaceweather as sw
    if w is None:
        return (f'<span style="color:#8a8a8a">{tr("Funkwetter: …")}</span>',
                tr("Funkwetter wird geladen (NOAA SWPC)"))
    if w.empty:
        return (f'<span style="color:#8a8a8a">{tr("Funkwetter: –")}</span>',
                tr("Funkwetter: keine Verbindung zu NOAA – neuer Versuch in wenigen Minuten"))
    bg = {sw.GOOD: ("#1b8a3a", "white"), sw.FAIR: ("#f2c200", "black"),
          sw.POOR: ("#c62828", "white"), sw.NEUTRAL: ("#9e9e9e", "white")}

    def pill(label, val, level):
        b, fg = bg[level]
        v = "–" if val is None else str(val)
        return (f'<span style="background:{b}; color:{fg}; font-weight:bold">'
                f'&nbsp;{label}&nbsp;{v}&nbsp;</span>')
    s_lv = sw.sfi_level(w.sfi, band)
    html = "&nbsp;".join((pill("SFI", w.sfi, s_lv), pill("A", w.a, sw.a_level(w.a)),
                          pill("K", w.k, sw.k_level(w.k))))
    word = {sw.GOOD: tr("gut"), sw.FAIR: tr("mittel"), sw.POOR: tr("schlecht")}
    lines = [tr("Funkwetter (NOAA SWPC) – grün gut, gelb mittel, rot schlecht")]
    if w.sfi is not None:
        if s_lv == sw.NEUTRAL:
            lines.append(tr("SFI {v} (Sonnenfluss, {t} UTC) – auf diesem Band wenig "
                            "aussagekräftig", v=w.sfi, t=w.sfi_time))
        else:
            lines.append(tr("SFI {v} (Sonnenfluss, {t} UTC) – für dieses Band {w}",
                            v=w.sfi, t=w.sfi_time, w=word[s_lv]))
    if w.a is not None:
        lines.append(tr("A {v} (Tageswert {d}, Unruhe des Erdmagnetfelds) – {w}",
                        v=w.a, d=w.a_date, w=word[sw.a_level(w.a)]))
    if w.k is not None:
        lines.append(tr("K {v} (3-Stunden-Wert {t} UTC, Unruhe des Erdmagnetfelds) – {w}",
                        v=w.k, t=w.k_time, w=word[sw.k_level(w.k)]))
    return html, "\n".join(lines)
