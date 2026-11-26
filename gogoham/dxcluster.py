"""DX-Cluster (ab 0.8.12): Spots von einem Cluster-Knoten (Telnet) lesen, filtern, merken.

Kein Qt in diesem Teil. Der Empfang läuft in einem eigenen Thread; die Spots landen in einer
Warteschlange, die das Hauptfenster abholt. GoGoHam liest hier nur – es werden keine eigenen
Spots verschickt.
"""

from __future__ import annotations

import queue
import re
import socket
import threading
import time
from dataclasses import dataclass, field

from .bands import band_for_freq
from .i18n import tr

# Getestete Knoten (2026-11-04: verbunden, mit Rufzeichen angemeldet, Spots erhalten)
NODES = (
    ("DB0SUE (DL)", "db0sue.de", 8000),
    ("HamQTH", "hamqth.com", 7300),
    ("DXSpider UK", "dxspider.co.uk", 7300),
    ("DX Fun", "dxfun.com", 8000),
    ("W3LPL", "w3lpl.net", 7373),
    ("VE7CC", "dxc.ve7cc.net", 23),
)
DEFAULT_NODE = "db0sue.de:8000"

CONTINENTS = ("EU", "NA", "SA", "AS", "AF", "OC", "AN")
CONTINENT_NAMES = {"EU": "Europa", "NA": "Nordamerika", "SA": "Südamerika", "AS": "Asien",
                   "AF": "Afrika", "OC": "Ozeanien", "AN": "Antarktis"}
_FOR_TRANSLATION = (tr("Europa"), tr("Nordamerika"), tr("Südamerika"), tr("Asien"),
                    tr("Afrika"), tr("Ozeanien"), tr("Antarktis"))

# Bandplan (IARU Region 1, vereinfacht): bis cw_top CW, ab ssb_from Sprechfunk, dazwischen digital
SEGMENTS = {
    "160": (1_838_000, 1_843_000), "80": (3_570_000, 3_600_000),
    "40": (7_040_000, 7_053_000), "30": (10_150_001, 10_150_001),   # 30 m: kein SSB
    "20": (14_070_000, 14_101_000), "17": (18_095_000, 18_111_000),
    "15": (21_070_000, 21_151_000), "12": (24_915_000, 24_931_000),
    "10": (28_070_000, 28_225_000), "6": (50_100_000, 50_100_000),
}
_MODE_WORDS = (("FT8", "DG"), ("FT4", "DG"), ("PSK", "DG"), ("JT65", "DG"), ("RTTY", "RY"),
               ("SSB", "PH"), ("USB", "PH"), ("LSB", "PH"), ("CW", "CW"))
# Übliche Digital-Frequenzen (kHz, Bandplan-Lücke: liegen oft im Sprechfunkbereich) ± 3 kHz
DIGI_KHZ = (1840, 3573, 3575.5, 5357, 7074, 7047.5, 7078, 10136, 10140, 14074, 14078, 14080,
            18100, 18104, 21074, 21140, 24915, 24919, 28074, 28180, 50313, 50318, 50323)
_SKIMMER_CW = re.compile(r"\b\d+\s*WPM\b", re.IGNORECASE)
_SKIMMER_DG = re.compile(r"\b\d{3,4}\s*Hz\b", re.IGNORECASE)

_DX = re.compile(r"^DX de\s+([A-Z0-9/\-#]+?):?\s+(\d+(?:\.\d+)?)\s+([A-Z0-9/]+)\s*(.*?)\s*"
                 r"(\d{4})Z", re.IGNORECASE)
# Antwort auf „sh/dx“ (DX Spider): „ 14025.0  DL1ABC  4-Nov-2026 1751Z  comment  <SPOTTER>“
_SHDX = re.compile(r"^\s*(\d+(?:\.\d+)?)\s+([A-Z0-9/]+)\s+\d{1,2}-[A-Za-z]{3}-\d{4}\s+(\d{4})Z"
                   r"\s*(.*?)\s*<([A-Z0-9/\-#]+)>", re.IGNORECASE)


@dataclass
class Spot:
    call: str
    freq: int                      # Hz
    spotter: str
    comment: str = ""
    utc: str = ""                  # „1751“
    received: float = field(default_factory=time.time)

    @property
    def band(self) -> str | None:
        return band_for_freq(self.freq)

    @property
    def spotter_call(self) -> str:
        """Melder ohne Zusatz wie „-#“ (Skimmer) oder „-2“ (zweiter Zugang)."""
        return self.spotter.split("-")[0].upper()


def parse_line(line: str) -> Spot | None:
    line = line.strip("\r\n\x07 ")
    m = _DX.match(line)
    if m:
        spotter, khz, call, comment, utc = m.groups()
        return _mk(call, khz, spotter, comment, utc)
    m = _SHDX.match(line)
    if m:
        khz, call, utc, comment, spotter = m.groups()
        return _mk(call, khz, spotter, comment, utc)
    return None


def _mk(call, khz, spotter, comment, utc) -> Spot | None:
    try:
        hz = int(round(float(khz) * 1000))
    except ValueError:
        return None
    if not band_for_freq(hz):
        return None
    return Spot(call.upper(), hz, spotter.upper(), comment.strip(), utc)


def spot_mode(spot: Spot) -> str:
    """Cabrillo-Mode (CW/PH/RY/DG) aus Kommentar oder Bandplan."""
    text = spot.comment.upper()
    for word, mode in _MODE_WORDS:
        if re.search(rf"\b{word}\b", text):
            return mode
    if _SKIMMER_CW.search(text):                     # „25 dB 36 WPM“ (CW-Skimmer)
        return "CW"
    if _SKIMMER_DG.search(text):                     # „-03dB from JO90 1166Hz“ (FT8-Meldung)
        return "DG"
    khz = spot.freq / 1000
    if any(abs(khz - d) <= 3 for d in DIGI_KHZ):
        return "DG"
    seg = SEGMENTS.get(spot.band or "")
    if not seg:
        return "PH" if spot.freq >= 50_000_000 else "CW"
    cw_top, ssb_from = seg
    if spot.freq < cw_top:
        return "CW"
    if spot.freq >= ssb_from:
        return "PH"
    return "DG"


def rig_mode(spot: Spot) -> str:
    """Betriebsart fürs Funkgerät: CW, LSB (unter 10 MHz) oder USB, RTTY, digital PKTUSB."""
    m = spot_mode(spot)
    if m == "CW":
        return "CW"
    if m == "RY":
        return "RTTY"
    if m == "DG":
        return "PKTUSB"
    return "LSB" if spot.freq < 10_000_000 else "USB"


class SpotStore:
    """Aktuelle Spots: je Rufzeichen und Band nur der neueste."""

    def __init__(self, max_age_min: int = 30):
        self.max_age = max_age_min * 60
        self.spots: dict[tuple[str, str], Spot] = {}
        self.version = 0                 # zählt bei jeder Änderung (Anzeige neu zeichnen)

    def add(self, spot: Spot) -> None:
        key = (spot.call, spot.band or "")
        old = self.spots.get(key)
        if old and old.freq == spot.freq and spot.received - old.received < 60:
            old.received = spot.received   # gleicher Spot noch einmal: nur auffrischen
            return
        self.spots[key] = spot
        self.version += 1

    def expire(self, now: float | None = None) -> None:
        now = now or time.time()
        old = [k for k, s in self.spots.items() if now - s.received > self.max_age]
        for k in old:
            del self.spots[k]
        if old:
            self.version += 1

    def on_band(self, band: str) -> list[Spot]:
        return sorted((s for s in self.spots.values() if s.band == band), key=lambda s: s.freq)

    def clear(self) -> None:
        self.spots.clear()
        self.version += 1

    def __len__(self) -> int:
        return len(self.spots)


def passes_filter(spot: Spot, spotter_cont: str | None, dx_cont: str | None,
                  want_spotter: set[str], want_dx: set[str]) -> bool:
    """Kontinent-Filter. Unbekannte Kontinente lassen wir durch (lieber zu viel als zu wenig)."""
    if spotter_cont and want_spotter and spotter_cont not in want_spotter:
        return False
    if dx_cont and want_dx and dx_cont not in want_dx:
        return False
    return True


def parse_node(text: str) -> tuple[str, int] | None:
    """„host:port“ oder „host port“ -> (host, port)."""
    t = (text or "").strip().replace(" ", ":")
    if ":" not in t:
        return (t, 23) if t else None
    host, _sep, port = t.rpartition(":")
    try:
        return host.strip(), int(port)
    except ValueError:
        return None


class ClusterClient(threading.Thread):
    """Verbindung zu einem Cluster-Knoten. Meldet sich mit dem Rufzeichen an, liest Spots,
    verbindet sich nach einem Abbruch selbst wieder."""

    def __init__(self, host: str, port: int, call: str, history: int = 30, keep=None,
                 name: str = "dxcluster"):
        super().__init__(daemon=True, name=name)
        # keep(spot) -> bool: nur passende Spots weiterreichen (ab 0.8.14 für das RBN, das
        # sehr viele Spots liefert – die Bakenanzeige braucht nur die Baken)
        self.keep = keep
        self.ever_connected = False
        self.host, self.port, self.call = host, int(port), call.upper()
        self.history = history           # beim Verbinden die letzten n Spots holen
        self.spots: queue.Queue = queue.Queue()
        self.connected = False
        self.error = ""
        self.lines = 0
        self._halt = threading.Event()
        self._sock: socket.socket | None = None
        # Stiller Abbruch (z. B. Netzwerkkabel gezogen) – ab 0.8.12.8: kommt eine Weile nichts,
        # schickt GoGoHam eine Leerzeile; jeder Knoten antwortet darauf mit seiner Eingabezeile.
        # Bleibt auch die Antwort aus, gilt die Verbindung als unterbrochen.
        self.idle_probe = 45.0           # Sekunden ohne Daten bis zur Nachfrage
        self.probe_timeout = 15.0        # so lange auf die Antwort warten

    def stop(self) -> None:
        self._halt.set()
        s = self._sock
        if s:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def run(self) -> None:
        wait = 5.0
        while not self._halt.is_set():
            try:
                self._session()
                wait = 5.0
            except OSError as e:
                if not self._halt.is_set():
                    self.error = connect_error(e)
            self.connected = False
            if self._halt.wait(wait):
                break
            wait = min(wait * 2, 120.0)

    def _session(self) -> None:
        s = socket.create_connection((self.host, self.port), timeout=10)
        self._sock = s
        s.settimeout(1.0)
        _keepalive(s)
        buf = b""
        logged_in = False
        started = time.monotonic()
        last_rx = started
        probe_at = 0.0
        try:
            while not self._halt.is_set():
                try:
                    data = s.recv(4096)
                except socket.timeout:
                    data = None
                if data == b"" and self._halt.is_set():
                    return                          # gewollt getrennt
                if data == b"":
                    raise ConnectionError(tr("Der Knoten hat die Verbindung beendet"))
                now = time.monotonic()
                if data:
                    buf += data
                    last_rx, probe_at = now, 0.0
                elif logged_in:
                    if probe_at and now - probe_at > self.probe_timeout:
                        raise ConnectionError(tr("Verbindung unterbrochen – keine Antwort vom "
                                                 "Knoten (Internet weg?)"))
                    if not probe_at and now - last_rx > self.idle_probe:
                        s.sendall(b"\r\n")        # Lebenszeichen anfordern
                        probe_at = now
                if not logged_in:
                    low = buf.lower()
                    if (b"login" in low or b"call" in low or time.monotonic() - started > 6):
                        s.sendall(self.call.encode() + b"\r\n")
                        logged_in = True
                        self.connected, self.error = True, ""
                        self.ever_connected = True
                        if self.history:
                            time.sleep(1.0)
                            s.sendall(f"sh/dx {int(self.history)}\r\n".encode())
                    continue
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self.lines += 1
                    spot = parse_line(line.decode("latin-1", "replace"))
                    if spot and (self.keep is None or self.keep(spot)):
                        self.spots.put(spot)
                if len(buf) > 8192:                 # Müll ohne Zeilenende verwerfen
                    buf = b""
        finally:
            self._sock = None
            try:
                s.close()
            except OSError:
                pass


def _keepalive(s: socket.socket) -> None:
    """Zusätzlich die Verbindungsüberwachung des Betriebssystems einschalten (wo vorhanden)."""
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        for name, val in (("TCP_KEEPIDLE", 30), ("TCP_KEEPINTVL", 10), ("TCP_KEEPCNT", 3)):
            if hasattr(socket, name):
                s.setsockopt(socket.IPPROTO_TCP, getattr(socket, name), val)
    except OSError:
        pass


def connect_error(e: Exception) -> str:
    if isinstance(e, socket.gaierror):
        return tr("Knoten nicht gefunden – keine Internetverbindung?")
    if isinstance(e, (TimeoutError, socket.timeout)):
        return tr("Knoten antwortet nicht")
    if isinstance(e, ConnectionRefusedError):
        return tr("Knoten lehnt die Verbindung ab")
    if isinstance(e, ConnectionError) and str(e):
        return str(e)
    return tr("keine Verbindung ({e})", e=e.__class__.__name__)
