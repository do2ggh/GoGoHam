"""CW über einen WinKey (K1EL WinKeyer, WK2/WK3) und PTT über eine Schnittstellen-Leitung (ab 0.8.18).

Ein WinKey ist ein eigener CW-Geber an einer seriellen Schnittstelle, z. B. eingebaut im
microHAM DXP (eigene Schnittstelle „WinKey“), oder als WinKeyer USB. GoGoHam schickt ihm nur
den Text, das Tasten macht der WinKey selbst (sauberes Timing, Paddle-Unterbrechung).

Protokoll (K1EL-Datenblatt WK2/WK3, öffentlich): 1200 Baud, 8 Datenbits, 2 Stoppbits.
- Admin 0x00 0x02 „Host Open“ → Antwort 1 Byte Version (z. B. 23 = WK2.3, 31 = WK3.1)
- Admin 0x00 0x03 „Host Close“
- 0x02 n  Tempo n WpM     · 0x05 min bereich 0  Tempo-Knopf einrichten · 0x07 Knopf abfragen
- 0x0A    Puffer leeren (CW sofort abbrechen) · 0x15 Status abfragen
- Text = ASCII-Großbuchstaben, Ziffern, Satzzeichen (Bytes unter 0x20 sind Befehle!)
- Vom WinKey: 0b110xxxxx Status (Bit0 XOFF, Bit1 Paddle-Unterbrechung, Bit2 sendet),
  0b10xxxxxx Stellung des Tempo-Knopfs (0–63, Tempo = min + Wert), sonst Echo.

**Ohne echtes Gerät nach Datenblatt gebaut** – Testlauf mit einem DXP steht noch aus.

Schnittstellen öffnen: Linux schaltet beim Öffnen DTR/RTS ein. Beides wird sofort wieder
abgeschaltet – beim DXP kann DTR jeder Schnittstelle im Gerätemenü als PTT/CW eingestellt sein.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass

from .i18n import tr

BAUD = 1200
POT_MIN, POT_RANGE = 10, 40          # Tempo-Knopf: 10–50 WpM
WPM_MIN, WPM_MAX = 5, 60             # wie bei Bild auf / Bild ab
FIFO_CHUNK = 16                      # so viele Zeichen auf einmal, dann XOFF prüfen


def clean_text(text: str) -> bytes:
    """Text für den WinKey: Großbuchstaben, nur druckbare Zeichen (keine Befehlsbytes)."""
    out = bytearray()
    for ch in (text or "").upper():
        o = ord(ch)
        if 0x20 <= o <= 0x7E:
            out.append(o)
    return bytes(out)


def version_text(v: int) -> str:
    """Versionsbyte lesbar machen: 23 → „WK2.3“, 31 → „WK3.1“."""
    if v < 0:
        return tr("in Benutzung")
    if 10 <= v <= 99:
        return f"WK{v // 10}.{v % 10}"
    return f"WinKey ({v})"


# --- Schnittstelle --------------------------------------------------------------------------
def _lines_off(fd: int, which: int | None = None) -> None:
    import fcntl
    import struct
    import termios
    bits = which if which is not None else (termios.TIOCM_DTR | termios.TIOCM_RTS)
    try:
        fcntl.ioctl(fd, termios.TIOCMBIC, struct.pack("I", bits))
    except OSError:
        pass                                  # Schnittstelle ohne Steuerleitungen


def open_serial(path: str, baud: int = BAUD, stop2: bool = True) -> int:
    """Schnittstelle roh öffnen (8 Datenbits, 2 Stoppbits), DTR/RTS aus. Gibt den fd zurück."""
    import termios
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        _lines_off(fd)
        a = termios.tcgetattr(fd)
        a[0] = 0
        a[1] = 0
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL | (termios.CSTOPB if stop2 else 0)
        a[3] = 0
        a[4] = a[5] = getattr(termios, f"B{int(baud)}")
        termios.tcsetattr(fd, termios.TCSANOW, a)
        _lines_off(fd)
        termios.tcflush(fd, termios.TCIOFLUSH)
    except Exception:
        os.close(fd)
        raise
    return fd


class SerialPort:
    """Kleine Hülle um den fd – in Tests durch eine Attrappe ersetzbar."""

    def __init__(self, path: str):
        self.fd = open_serial(path)

    def write(self, data: bytes) -> None:
        import select
        view = memoryview(data)
        end = time.monotonic() + 2.0
        while view:
            if time.monotonic() > end:
                raise OSError(tr("WinKey nimmt keine Daten an"))
            select.select([], [self.fd], [], 0.2)
            try:
                n = os.write(self.fd, view)
            except BlockingIOError:
                continue
            view = view[n:]

    def read(self, timeout: float) -> bytes:
        import select
        r, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
        if not r:
            return b""
        data = os.read(self.fd, 256)
        if not data:
            raise OSError(tr("WinKey-Schnittstelle ist weg"))
        return data

    def close(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass


def _host_open(port, timeout: float = 1.0) -> int:
    """„Host Open“ schicken und die Version lesen (0 = keine Antwort)."""
    port.write(b"\x00\x02")
    end = time.monotonic() + timeout
    while (left := end - time.monotonic()) > 0:
        for b in port.read(left):
            if b < 0x80:                      # Status/Knopf-Bytes haben Bit 7 gesetzt
                return b
    return 0


def probe(path: str, opener=SerialPort) -> int:
    """Ist an ``path`` ein WinKey? Gibt die Version zurück (0 = nein). Sendet kein CW."""
    try:
        port = opener(path)
    except OSError:
        return 0
    try:
        v = _host_open(port)
        if v:
            port.write(b"\x00\x03")           # Host Close – WinKey wieder für sich allein
        return v
    except OSError:
        return 0
    finally:
        port.close()


def held_here(path: str) -> bool:
    """Hat GoGoHam selbst (dieser Prozess) die Schnittstelle offen?"""
    want = os.path.realpath(path)
    try:
        for fd in os.listdir("/proc/self/fd"):
            try:
                if os.path.realpath(os.path.join("/proc/self/fd", fd)) == want:
                    return True
            except OSError:
                continue
    except OSError:
        pass
    return False


# --- Hintergrund-Thread ---------------------------------------------------------------------
@dataclass
class KeyerState:
    connected: bool = False
    version: int = 0
    wpm: int = 0
    busy: bool = False
    error: str = ""
    breakin_id: int = 0        # zählt hoch, wenn mit dem Paddle unterbrochen wurde
    pot_id: int = 0            # zählt hoch, wenn der Tempo-Knopf gedreht wurde


class WinKeyWorker(threading.Thread):
    """Hält die Verbindung zum WinKey, schickt CW-Text, liest Status und Tempo-Knopf."""

    def __init__(self, path: str, opener=SerialPort, retry: float = 3.0):
        super().__init__(daemon=True, name="winkey")
        self.path = path
        self.opener = opener
        self.retry = retry
        self.state = KeyerState()
        self.lock = threading.Lock()
        self.commands: queue.Queue = queue.Queue()
        self._halt = threading.Event()
        self._port = None
        self._xoff = False
        self._pending = b""                   # CW-Text, der noch in den WinKey muss

    # öffentliche Seite (Hauptfenster)
    def submit(self, name: str, *args) -> None:
        """'send' (Text), 'stop', 'set_wpm' (n)."""
        self.commands.put((name, args))

    def snapshot(self) -> KeyerState:
        with self.lock:
            return KeyerState(**self.state.__dict__)

    def stop(self) -> None:
        self._halt.set()

    def _set(self, **kw) -> None:
        with self.lock:
            for k, v in kw.items():
                setattr(self.state, k, v)

    # Ablauf
    def run(self) -> None:
        while not self._halt.is_set():
            try:
                self._connect()
            except OSError as e:
                self._set(connected=False, error=str(e) or tr("WinKey nicht erreichbar"))
                self._halt.wait(self.retry)
                continue
            try:
                while not self._halt.is_set():
                    self._do_commands()
                    self._feed()
                    self._on_bytes(self._port.read(0.05))
            except OSError as e:
                self._set(connected=False, busy=False, error=str(e))
                self._close(polite=False)
                self._halt.wait(self.retry)
        self._close(polite=True)

    def _connect(self) -> None:
        self._port = self.opener(self.path)
        v = _host_open(self._port)
        if not v:
            self._close(polite=False)
            raise OSError(tr("An {path} antwortet kein WinKey", path=self.path))
        self._xoff, self._pending = False, b""
        self._port.write(bytes([0x05, POT_MIN, POT_RANGE, 0]))   # Tempo-Knopf 10–50 WpM
        self._port.write(b"\x07")                                # Knopf-Stellung abfragen
        self._set(connected=True, version=v, error="", busy=False)

    def _close(self, polite: bool) -> None:
        if not self._port:
            return
        if polite:
            try:
                self._port.write(b"\x0A\x00\x03")    # Puffer leeren, Host Close
            except OSError:
                pass
        self._port.close()
        self._port = None

    def _do_commands(self) -> None:
        while True:
            try:
                name, args = self.commands.get_nowait()
            except queue.Empty:
                return
            if name == "send":
                self._pending += clean_text(args[0] if args else "")
            elif name == "stop":
                self._pending = b""
                self._port.write(b"\x0A")
                self._set(busy=False)
            elif name == "set_wpm":
                n = min(WPM_MAX, max(WPM_MIN, int(args[0])))
                self._port.write(bytes([0x02, n]))
                self._set(wpm=n)

    def _feed(self) -> None:
        if self._pending and not self._xoff:
            chunk, self._pending = self._pending[:FIFO_CHUNK], self._pending[FIFO_CHUNK:]
            self._port.write(chunk)
            self._set(busy=True)

    def _on_bytes(self, data: bytes) -> None:
        for b in data:
            if b & 0xC0 == 0xC0:                  # Status
                self._xoff = bool(b & 0x01)
                with self.lock:
                    self.state.busy = bool(b & 0x04) or bool(self._pending)
                    if b & 0x02:                  # Paddle: WinKey hat den Puffer selbst geleert
                        self.state.breakin_id += 1
                if b & 0x02:
                    self._pending = b""
            elif b & 0xC0 == 0x80:                # Tempo-Knopf
                n = min(WPM_MAX, max(WPM_MIN, POT_MIN + (b & 0x3F)))
                self._port.write(bytes([0x02, n]))
                with self.lock:
                    self.state.wpm = n
                    self.state.pot_id += 1
            # sonst: Echo – wird nicht gebraucht
