"""Aufnahme und Wiedergabe über Qt (QtMultimedia) – ohne fremde Programme (ab 0.8.11).

Qt wird erst geladen, wenn die Sprachausgabe wirklich gebraucht wird. Fehlt QtMultimedia
(Paket ``qt6-multimedia`` bzw. ``python3-pyside6.qtmultimedia``), meldet GoGoHam das verständlich
und läuft sonst normal weiter.
"""

from __future__ import annotations

import time

import numpy as np

from ..i18n import tr
from .. import voice

# Bekannte Soundkarten in Funkgeräten (USB-Codec von Texas Instruments/Burr-Brown – z. B. IC-7300,
# IC-705, IC-9700, IC-7610). Nur ein Hinweis in der Auswahlliste, es wird nichts automatisch gewählt.
RIG_CODEC_HINTS = ("PCM2901", "PCM2902", "PCM2903", "Burr-Brown", "USB Audio CODEC")


def available() -> str:
    """Leerer Text = QtMultimedia ist da, sonst eine verständliche Meldung."""
    try:
        import PySide6.QtMultimedia  # noqa: F401
    except ImportError:
        return tr("Für Aufnahme und Wiedergabe fehlt der Qt-Teil „QtMultimedia“. "
                  "Garuda/Arch: sudo pacman -S qt6-multimedia qt6-multimedia-ffmpeg · "
                  "Debian/Ubuntu: sudo apt install python3-pyside6.qtmultimedia")
    return ""


def _dev_id(dev) -> str:
    return bytes(dev.id()).decode("utf-8", "replace")


def describe(dev) -> str:
    name = dev.description()
    if any(h.lower() in name.lower() for h in RIG_CODEC_HINTS):
        name += " " + tr("(Funkgerät, z. B. IC-7300?)")
    return name


def inputs() -> list[tuple[str, str]]:
    """Mikrofone: (Kennung, Name)."""
    from PySide6.QtMultimedia import QMediaDevices
    return [(_dev_id(d), describe(d)) for d in QMediaDevices.audioInputs()]


def outputs() -> list[tuple[str, str]]:
    """Wiedergabegeräte: (Kennung, Name)."""
    from PySide6.QtMultimedia import QMediaDevices
    return [(_dev_id(d), describe(d)) for d in QMediaDevices.audioOutputs()]


def find(kind: str, dev_id: str):
    """Gerät zur gespeicherten Kennung – None, wenn es (gerade) nicht da ist."""
    from PySide6.QtMultimedia import QMediaDevices
    devs = QMediaDevices.audioInputs() if kind == "in" else QMediaDevices.audioOutputs()
    for d in devs:
        if _dev_id(d) == dev_id:
            return d
    return None


def _format(dev, channels: int = 1):
    """48 kHz 16 Bit mit `channels` Kanälen (sonst mono), wenn das Gerät es kann – sonst sein
    bevorzugtes Format. Stereo (0.8.13) fürs Probehören: manche Systeme geben Mono nur noch
    links aus. Zum Funkgerät bleibt es mono (Sendepegel unverändert)."""
    from PySide6.QtMultimedia import QAudioFormat
    for ch in dict.fromkeys((channels, 1)):
        f = QAudioFormat()
        f.setSampleRate(voice.RATE)
        f.setChannelCount(ch)
        f.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if dev.isFormatSupported(f):
            return f
    return dev.preferredFormat()


def _decode(raw: bytes, fmt) -> np.ndarray:
    """Rohdaten im Geräteformat -> Gleitkomma, noch mit den Kanälen des Geräts."""
    from PySide6.QtMultimedia import QAudioFormat
    sf = fmt.sampleFormat()
    if sf == QAudioFormat.SampleFormat.Int16:
        return np.frombuffer(raw[: len(raw) // 2 * 2], "<i2").astype(np.float32) / 32768.0
    if sf == QAudioFormat.SampleFormat.Int32:
        return np.frombuffer(raw[: len(raw) // 4 * 4], "<i4").astype(np.float32) / 2147483648.0
    if sf == QAudioFormat.SampleFormat.Float:
        return np.frombuffer(raw[: len(raw) // 4 * 4], "<f4").astype(np.float32)
    return (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0


def _encode(x: np.ndarray, fmt) -> bytes:
    """Mono 48 kHz -> Rohdaten im Format des Geräts."""
    from PySide6.QtMultimedia import QAudioFormat
    y = voice.resample(x, voice.RATE, fmt.sampleRate())
    ch = max(1, fmt.channelCount())
    if ch > 1:
        y = np.repeat(y, ch)
    y = np.clip(y, -1.0, 1.0)
    sf = fmt.sampleFormat()
    if sf == QAudioFormat.SampleFormat.Int16:
        return (y * 32767).astype("<i2").tobytes()
    if sf == QAudioFormat.SampleFormat.Int32:
        return (y * 2147483647).astype("<i4").tobytes()
    if sf == QAudioFormat.SampleFormat.Float:
        return y.astype("<f4").tobytes()
    return (y * 127 + 128).astype(np.uint8).tobytes()


class Recorder:
    """Mikrofon lesen: Pegel melden und – wenn gewünscht – mitschreiben.

    Die Verstärkung wirkt schon hier (die Pegelanzeige zeigt das verstärkte Signal)."""

    def __init__(self, on_level=None):
        self.on_level = on_level          # Funktion(dBFS) – Spitzenpegel des letzten Stücks
        self.gain_db = 0.0
        self.recording = False
        self._src = None
        self._io = None
        self._fmt = None
        self._chunks: list[np.ndarray] = []
        self.error = ""

    @property
    def active(self) -> bool:
        return self._src is not None

    def start(self, dev, record: bool) -> bool:
        from PySide6.QtMultimedia import QAudioSource
        self.stop()
        self.error = ""
        if dev is None:
            self.error = tr("Kein Mikrofon gewählt oder Mikrofon nicht gefunden")
            return False
        self._fmt = _format(dev)
        self._src = QAudioSource(dev, self._fmt)
        self._chunks = []
        self.recording = record
        self._io = self._src.start()
        if self._io is None:
            self.error = tr("Das Mikrofon lässt sich nicht öffnen")
            self._src = None
            return False
        self._io.readyRead.connect(self._read)
        return True

    def _read(self) -> None:
        if not self._io:
            return
        raw = bytes(self._io.readAll())
        if not raw:
            return
        x = _decode(raw, self._fmt)
        x = voice.to_mono(x, max(1, self._fmt.channelCount()), self._fmt.sampleRate())
        x = np.clip(x * 10 ** (self.gain_db / 20), -1.0, 1.0)
        if self.recording:
            self._chunks.append(x)
        if self.on_level and len(x):
            pk = float(np.abs(x).max())
            self.on_level(20 * np.log10(max(pk, 1e-5)))

    def stop(self) -> np.ndarray:
        """Anhalten; liefert das Mitgeschriebene (48 kHz mono)."""
        if self._src is not None:
            self._read()
            try:
                self._src.stop()
            except RuntimeError:
                pass
        self._src = self._io = None
        out = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)
        self._chunks = []
        self.recording = False
        return out


class Player:
    """Eine fertige Ansage auf einem Gerät abspielen. on_finished() kommt genau einmal –
    am Ende, bei stop() oder bei einem Fehler."""

    def __init__(self, on_finished=None):
        self.on_finished = on_finished
        self._sink = None
        self._buf = None
        self._timer = None
        self.error = ""

    @property
    def playing(self) -> bool:
        return self._sink is not None

    def play(self, samples: np.ndarray, dev, stereo: bool = False) -> bool:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QTimer
        from PySide6.QtMultimedia import QAudioSink
        self.stop(notify=False)
        self.error = ""
        if dev is None:
            self.error = tr("Wiedergabegerät nicht gefunden – bitte unter Einstellungen → Ton & Ansagen → Sprachaufnahmen "
                            "wählen")
            return False
        if len(samples) == 0:
            self.error = tr("Nichts zum Abspielen")
            return False
        fmt = _format(dev, 2 if stereo else 1)
        self._buf = QBuffer()
        self._buf.setData(QByteArray(_encode(samples, fmt)))
        self._buf.open(QIODevice.OpenModeFlag.ReadOnly)
        self._sink = QAudioSink(dev, fmt)
        self._sink.start(self._buf)
        # Ende erkennen: Qt meldet „Idle“, sobald alles abgespielt ist. Abgefragt statt per
        # Signal (das Signal lässt sich in PySide6 6.12 nicht sauber verbinden).
        self._deadline = time.monotonic() + len(samples) / voice.RATE + 2.0   # Sicherheitsnetz
        self._started = False
        self._timer = QTimer()
        self._timer.timeout.connect(self._check)
        self._timer.start(40)
        return True

    def _check(self) -> None:
        if self._sink is None:
            return
        try:
            from PySide6.QtMultimedia import QtAudio as _A
        except ImportError:                                    # ältere PySide6
            from PySide6.QtMultimedia import QAudio as _A
        st = self._sink.state()
        if st == _A.State.ActiveState:
            self._started = True
        done = st == _A.State.StoppedState or (st == _A.State.IdleState and
                                               (self._started or self._buf.atEnd()))
        if done or time.monotonic() > self._deadline:
            if self._sink.error() not in (_A.Error.NoError, _A.Error.UnderrunError):
                self.error = tr("Wiedergabe abgebrochen (Fehler des Tongeräts)")
            self.stop()

    def stop(self, notify: bool = True) -> None:
        was = self._sink is not None
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        sink, self._sink = self._sink, None
        if sink is not None:
            sink.stop()
        if self._buf is not None:
            self._buf.close()
            self._buf = None
        if was and notify and self.on_finished:
            self.on_finished()
