"""Startbildschirm von GoGoHam mit Morse-Ladebalken „GGH“.

Ablauf:
  * GGH wird Element für Element gegeben (14 WpM, echtes Morse-Timing) und läuft
    in einer Schleife, solange geladen wird.
  * Der Startbildschirm bleibt mindestens einen vollen Durchlauf plus Wortpause.
  * Nach ``finish(fenster)`` wird der laufende Durchlauf noch zu Ende gegeben,
    dann erscheint das Hauptfenster und der Startbildschirm blendet sich aus.
  * Mithörton (650 Hz) optional, standardmäßig aus.

Verwendung::

    splash = MorseSplash(ton=config.get("splash_ton", False))
    splash.show()
    splash.set_status("Lade Länderdatei …")   # ruft processEvents() auf
    ...
    fenster = MainWindow(...)
    splash.finish(fenster)   # zeigt das Fenster zum richtigen Zeitpunkt
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

from PySide6.QtCore import (QBuffer, QByteArray, QElapsedTimer, QIODevice,
                            QRectF, Qt, QTimer, QVariantAnimation)
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QWidget

from .. import morse_timing as mt
from ..i18n import tr

try:
    from PySide6.QtSvg import QSvgRenderer
except ImportError:          # QtSvg fehlt → Startbildschirm ohne Logo
    QSvgRenderer = None

RED = QColor("#C8102E")
DARK = QColor("#8A0C20")
PAPER = QColor("#F7F4EE")
DIM = QColor("#E3C9CC")

LOGO = Path(__file__).resolve().parent.parent / "assets" / "gogoham.svg"

TONE_HZ = 650
RATE = 48000


class _Tone:
    """Erzeugt den Mithörton für einen ganzen Durchlauf und spielt ihn ab."""

    def __init__(self, parent):
        self.ok = False
        try:
            from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
        except ImportError:
            return
        dev = QMediaDevices.defaultAudioOutput()
        if dev.isNull():
            return
        # Stereo (0.8.13): manche Systeme geben Mono nur noch auf dem linken Lautsprecher aus
        for ch in (2, 1):
            fmt = QAudioFormat()
            fmt.setSampleRate(RATE)
            fmt.setChannelCount(ch)
            fmt.setSampleFormat(QAudioFormat.Int16)
            if dev.isFormatSupported(fmt):
                break
        else:
            return
        self.sink = QAudioSink(dev, fmt, parent)
        self.sink.setVolume(0.3)
        self.data = QByteArray(self._pcm(ch))
        self.buf = QBuffer(parent)
        self.buf.setData(self.data)
        self.ok = True

    @staticmethod
    def _pcm(channels: int = 1) -> bytes:
        total = int(mt.cycle_ms() / 1000 * RATE)
        samples = [0] * total
        ramp = int(0.005 * RATE)                     # 5 ms weiche Flanken, kein Klicken
        for e in mt.schedule():
            a = int(e.start / 1000 * RATE)
            n = int(e.duration / 1000 * RATE)
            for i in range(n):
                env = min(1.0, i / ramp, (n - i) / ramp)
                samples[a + i] = int(12000 * env *
                                     math.sin(2 * math.pi * TONE_HZ * i / RATE))
        if channels > 1:
            samples = [s for s in samples for _ in range(channels)]   # links = rechts
        return struct.pack(f"<{len(samples)}h", *samples)

    def play_cycle(self):
        if not self.ok:
            return
        self.sink.stop()
        self.buf.close()
        self.buf.open(QIODevice.ReadOnly)
        self.sink.start(self.buf)

    def stop(self):
        if self.ok:
            self.sink.stop()


class MorseSplash(QWidget):
    W, H = 620, 220

    def __init__(self, ton: bool = False, status: str = "", version: str = ""):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.W, self.H)
        self._status = status or tr("Lade Contest-Regeln …")
        self._hidden_for_dialog = False
        self._version = version
        self._opacity = 1.0
        self._clock = QElapsedTimer()
        self._close_at: float | None = None
        self._window = None
        self._fading = False
        self._last_cycle = -1
        self._sched = mt.schedule()
        self._cycle = mt.cycle_ms()
        self._logo = (QSvgRenderer(str(LOGO)) if QSvgRenderer and LOGO.exists()
                      else None)
        self._tone = _Tone(self) if ton else None

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)

        scr = QGuiApplication.primaryScreen()
        if scr:
            g = scr.availableGeometry()
            self.move(g.center().x() - self.W // 2, g.center().y() - self.H // 2)

    # ------------------------------------------------------------ öffentliche API
    def show(self):
        super().show()
        self._clock.start()
        self._timer.start(15)
        QApplication.processEvents()

    def show_again(self):
        super().show()

    def set_status(self, text: str):
        self._status = text
        self.update()
        QApplication.processEvents()

    def finish(self, window: QWidget):
        """Laden ist fertig: Durchlauf zu Ende geben, dann Fenster zeigen."""
        self._window = window
        self._close_at = mt.close_time(self._clock.elapsed())

    # ------------------------------------------------------------------ Ablauf
    def _now(self) -> float:
        t = float(self._clock.elapsed())
        if self._close_at is not None:
            # nicht in den nächsten Durchlauf springen (sonst kurzes Aufflackern)
            t = min(t, self._close_at - 0.5)
        return t

    def _tick(self):
        # Fragt GoGoHam beim Start etwas (z. B. „Log beschädigt“), darf der Startbildschirm
        # die Rückfrage nicht verdecken: so lange ausblenden.
        modal = QApplication.activeModalWidget()
        if modal is not None and modal is not self and not self._fading:
            if not self._hidden_for_dialog:
                self._hidden_for_dialog = True
                if self._tone:
                    self._tone.stop()
                self.hide()
            return
        if self._hidden_for_dialog:
            self._hidden_for_dialog = False
            self.show_again()
        t = self._now()
        cyc = int(t // self._cycle)
        if cyc != self._last_cycle:
            self._last_cycle = cyc
            if self._tone and (self._close_at is None
                               or cyc * self._cycle < self._close_at):
                self._tone.play_cycle()
        if (self._close_at is not None and not self._fading
                and self._clock.elapsed() >= self._close_at):
            self._start_fade()
        self.update()

    def _start_fade(self):
        self._fading = True
        if self._tone:
            self._tone.stop()
        if self._window is not None:
            self._window.show()
            self.raise_()
        anim = QVariantAnimation(self)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setDuration(300)
        anim.valueChanged.connect(self._set_opacity)
        anim.finished.connect(self._done)
        anim.start()
        self._anim = anim

    def _set_opacity(self, v):
        self._opacity = float(v)
        self.update()

    def _done(self):
        self._timer.stop()
        self.close()
        if self._window is not None:
            self._window.activateWindow()
            self._window.raise_()
            # Rückfragen beim Start (Willkommen, Länderdatei …) erst jetzt zeigen
            after = getattr(self._window, "run_startup_popups", None)
            if after is not None:
                after()

    # ---------------------------------------------------------------- Zeichnen
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._opacity)

        frame = QRectF(1.5, 1.5, self.W - 3, self.H - 3)
        p.setPen(Qt.NoPen)
        p.setBrush(PAPER)
        p.drawRoundedRect(frame, 14, 14)
        pen = p.pen()
        pen.setColor(RED)
        pen.setWidthF(2.5)
        pen.setStyle(Qt.SolidLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(frame, 14, 14)
        p.setPen(Qt.NoPen)

        if self._logo:
            self._logo.render(p, QRectF(26, 26, 168, 168))

        x = 220
        f = QFont(self.font())
        f.setPixelSize(36)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(RED)
        p.drawText(x, 82, "GoGoHam")
        f.setPixelSize(14)
        f.setWeight(QFont.Normal)
        p.setFont(f)
        p.setPen(DARK)
        p.drawText(x, 108, tr("by DO2GGH · Contest-Logger für Linux"))

        self._paint_bar(p, x, 134)

        p.setPen(DARK)
        p.drawText(x, 184, self._status)
        if self._version:
            f.setPixelSize(12)
            p.setFont(f)
            p.drawText(QRectF(0, self.H - 30, self.W - 20, 20),
                       Qt.AlignRight | Qt.AlignVCenter, self._version)
        p.end()

    def _paint_bar(self, p: QPainter, x0: int, y: int):
        fr = mt.fractions(self._now())
        x = x0
        last_letter = 0
        p.setPen(Qt.NoPen)
        for e, frac in zip(self._sched, fr):
            if e.letter != last_letter:
                x += 14                      # Abstand zwischen Buchstaben
                last_letter = e.letter
            w = 34 if e.kind == "-" else 10
            rect = QRectF(x, y, w, 10)
            path = QPainterPath()
            path.addRoundedRect(rect, 5, 5)
            p.fillPath(path, DIM)
            if frac > 0:
                p.save()
                p.setClipRect(QRectF(x, y, w * frac, 10))
                p.fillPath(path, RED)
                p.restore()
            x += w + 7
