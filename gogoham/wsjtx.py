"""Empfang aus WSJT-X und kompatiblen FT8-Programmen (UDP, Standard-Port 2237).

WSJT-X schickt beim Loggen eine "Logged ADIF"-Nachricht (Typ 12) mit dem
kompletten ADIF-Datensatz. Unterstützt werden außerdem reine ADIF-Pakete
(z. B. vom "Secondary UDP Server", Port 2333).

Ab 0.6.4 wertet GoGoHam auch aus, ob ein FT8-Programm gerade läuft:
Heartbeat (Typ 0, alle 15 s), Status (Typ 1, bei jeder Änderung), Decode (Typ 2)
und Close (Typ 6, beim Beenden). Solange es läuft, steuert GoGoHam das Funkgerät
nicht (nur Anzeige) – siehe ``WsjtxListener.active_program``.
"""

from __future__ import annotations

from .i18n import tr

import ipaddress
import os
import queue
import re
import socket
import struct
import threading
import time

MAGIC = 0xADBCCBDA

# Mehrere Empfänger gleichzeitig (0.10.43, GoGoHam + GoGoHome): An 127.0.0.1 geschickte Pakete
# (fldigi kann nur das) bekommt immer nur EIN Programm. Wer eins bekommt, reicht es über die
# interne Verbindung (lo) an eine Gruppe weiter; alle anderen Empfänger desselben Ports hören dort
# mit. Klappt auch ohne Netzwerk. Kennung je Empfänger, damit niemand sein eigenes Paket nochmal
# verarbeitet; weitergereichte Pakete werden nie erneut weitergereicht.
RELAY_GROUP = "239.255.42.37"
RELAY_OFFSET = 30000                    # Gruppen-Port = Port + 30000 (2237 -> 32237, 2239 -> 32239)
RELAY_MAGIC = b"GGHRLY1"
LOOPBACK = "127.0.0.1"


def join_group(s: socket.socket, group: str) -> None:
    """Gruppe über die interne Verbindung (lo) beitreten – geht auch ohne Netzwerk; notfalls über
    die Standard-Schnittstelle (ältere Systeme ohne Gruppen auf lo)."""
    for iface in (LOOPBACK, "0.0.0.0"):
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                         struct.pack("4s4s", socket.inet_aton(group), socket.inet_aton(iface)))
            return
        except OSError as e:
            err = e
    raise err


def _reuse(s: socket.socket) -> None:
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass


def open_relay(port: int) -> socket.socket:
    if not 0 < port + RELAY_OFFSET <= 65535:
        raise OSError("relay port out of range")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    _reuse(s)
    s.bind(("", port + RELAY_OFFSET))
    join_group(s, RELAY_GROUP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(LOOPBACK))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 0)
    s.settimeout(0)
    return s
TYPE_LOGGED_ADIF = 12
TYPE_HEARTBEAT, TYPE_STATUS, TYPE_DECODE, TYPE_CLOSE = 0, 1, 2, 6
ALIVE_TYPES = {TYPE_HEARTBEAT, TYPE_STATUS, TYPE_DECODE}

# Wann gibt GoGoHam die Steuerung zurück?
HEARTBEAT_TIMEOUT = 30      # s ohne Lebenszeichen (Programme mit Heartbeat/Status)
QSO_ONLY_TIMEOUT = 120      # s nach dem letzten QSO (Programme, die nur QSOs schicken)

_ADIF_FIELD = re.compile(r"<([A-Za-z0-9_]+):(\d+)(?::[A-Za-z])?>", re.S)


def parse_adif_record(text: str) -> dict[str, str]:
    """Erstes ADIF-Record (nach <EOH>, falls vorhanden) in ein Dict wandeln."""
    low = text.lower()
    i = low.find("<eoh>")
    pos = i + 5 if i >= 0 else 0
    out: dict[str, str] = {}
    while True:
        m = _ADIF_FIELD.search(text, pos)
        if not m:
            break
        tag, n = m.group(1).upper(), int(m.group(2))
        start = m.end()
        out[tag] = text[start:start + n]
        pos = start + n
        if text[pos:pos + 5].lower() == "<eor>":
            break
    return out


def parse_adif_file(text: str) -> list[dict[str, str]]:
    low = text.lower()
    i = low.find("<eoh>")
    body = text[i + 5:] if i >= 0 else text
    recs = []
    for chunk in re.split(r"<eor>", body, flags=re.I):
        if "<" in chunk:
            r = parse_adif_record(chunk + "<EOR>")
            if r.get("CALL"):
                recs.append(r)
    return recs


def _read_qbytes(data: bytes, off: int) -> tuple[bytes | None, int]:
    (n,) = struct.unpack_from(">I", data, off)
    off += 4
    if n == 0xFFFFFFFF:
        return None, off
    return data[off:off + n], off + n


def parse_packet(data: bytes) -> dict[str, str] | None:
    """WSJT-X-UDP-Paket auswerten. Gibt ADIF-Felder zurück, sonst None."""
    if data[:1] == b"<":
        rec = parse_adif_record(data.decode("utf-8", "replace"))
        return rec or None
    if len(data) < 12:
        return None
    magic, _schema, mtype = struct.unpack_from(">III", data, 0)
    if magic != MAGIC or mtype != TYPE_LOGGED_ADIF:
        return None
    off = 12
    _id, off = _read_qbytes(data, off)
    adif, off = _read_qbytes(data, off)
    if not adif:
        return None
    rec = parse_adif_record(adif.decode("utf-8", "replace"))
    return rec or None


def parse_header(data: bytes) -> tuple[int, str] | None:
    """(Nachrichtentyp, Programm-ID) eines WSJT-X-Pakets, sonst None."""
    if len(data) < 12:
        return None
    magic, _schema, mtype = struct.unpack(">III", data[:12])
    if magic != MAGIC:
        return None
    raw, _off = _read_qbytes(data, 12)
    cid = raw.decode("utf-8", "replace") if raw else ""
    return mtype, cid


def build_packet(mtype: int, client_id: str = "WSJT-X") -> bytes:
    """Kleines Paket ohne Inhalt (für Tests: Heartbeat, Close …)."""
    cid = client_id.encode()
    return struct.pack(">III", MAGIC, 3, mtype) + struct.pack(">I", len(cid)) + cid


class ProgramActivity:
    """Merkt sich, welche FT8-Programme sich gemeldet haben und wann."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.seen: dict[str, tuple[float, bool]] = {}   # ID -> (Zeit, meldet sich laufend?)

    def packet(self, mtype: int | None, cid: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        cid = cid or "FT8-Programm"
        with self.lock:
            if mtype == TYPE_CLOSE:
                self.seen.pop(cid, None)
                return
            _t, alive = self.seen.get(cid, (0.0, False))
            self.seen[cid] = (now, alive or mtype in ALIVE_TYPES)

    def active(self, now: float | None = None) -> str | None:
        now = time.monotonic() if now is None else now
        with self.lock:
            for cid, (t, alive) in sorted(self.seen.items(), key=lambda kv: -kv[1][0]):
                limit = HEARTBEAT_TIMEOUT if alive else QSO_ONLY_TIMEOUT
                if now - t <= limit:
                    return cid
        return None


def build_logged_adif_packet(adif: str, client_id: str = "WSJT-X") -> bytes:
    """Für Tests: ein Typ-12-Paket wie von WSJT-X erzeugen."""
    cid = client_id.encode()
    body = adif.encode()
    return (struct.pack(">III", MAGIC, 3, TYPE_LOGGED_ADIF)
            + struct.pack(">I", len(cid)) + cid + struct.pack(">I", len(body)) + body)


class WsjtxListener(threading.Thread):
    def __init__(self, port: int = 2237, address: str = "127.0.0.1", program: str = ""):
        super().__init__(daemon=True, name="wsjtx" if not program else f"udp-{program}")
        self.port = port
        self.address = address
        self.program = program          # "" = FT8-Programme; "fldigi" = nur ADIF, sperrt nichts
        self.clients: dict[str, tuple] = {}     # Kennung -> Absender (für „Close“, 0.10.6)
        self.records: queue.Queue = queue.Queue()
        self.error = ""
        self._halt = threading.Event()
        self.sock: socket.socket | None = None
        self.relay: socket.socket | None = None
        self.relay_id = os.urandom(8)
        self.activity = ProgramActivity()

    def active_program(self) -> str | None:
        """Name des FT8-Programms, das gerade läuft (oder None)."""
        return self.activity.active()

    def stop(self) -> None:
        self._halt.set()

    def close_clients(self) -> int:
        """Allen FT8-Programmen, die sich gemeldet haben, „Close“ schicken (WSJT-X-Protokoll,
        Nachricht 6) – sie beenden sich dann selbst und speichern ihre Einstellungen."""
        n = 0
        for cid, addr in list(self.clients.items()):
            try:
                if self.sock is not None:
                    self.sock.sendto(build_packet(6, cid), addr)
                    n += 1
            except OSError:
                pass
        return n

    def _open(self) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        _reuse(s)
        multicast = False
        try:
            multicast = ipaddress.ip_address(self.address).is_multicast
        except ValueError:
            pass
        s.bind(("" if multicast else self.address, self.port))
        if multicast:
            join_group(s, self.address)          # 0.10.43: über lo – auch ohne Netzwerk
        else:
            try:                                 # 0.10.43: an andere Empfänger weiterreichen
                self.relay = open_relay(self.port)
            except (OSError, OverflowError):
                self.relay = None
        s.settimeout(0.5)
        return s

    def run(self) -> None:
        try:
            self.sock = self._open()
        except OSError as e:
            self.error = (tr("UDP-Port {port} belegt ({e}) – läuft ein Log-Programm oder GridTracker auf "
                             "demselben Port? Lösung: Multicast 224.0.0.1 (siehe Anleitung)", port=self.port, e=e))
            return
        while not self._halt.is_set():
            try:
                data, _addr = self.sock.recvfrom(65535)
            except socket.timeout:
                self._drain_relay()
                continue
            except OSError as e:
                self.error = str(e)
                break
            self.handle(data, _addr)
            self._forward(data)
            self._drain_relay()
        self.sock.close()
        if self.relay is not None:
            self.relay.close()

    def handle(self, data: bytes, addr, relayed: bool = False) -> None:
        try:
            hdr = parse_header(data)
            rec = parse_packet(data)
        except (struct.error, ValueError):
            hdr, rec = None, None
        if hdr:
            self.activity.packet(hdr[0], hdr[1])
            if not relayed:                      # Antworten nur an den echten Absender
                self.clients[hdr[1]] = addr
        elif rec and not self.program:
            self.activity.packet(None, "FT8-Programm")     # reines ADIF ohne Kopf
        if rec and rec.get("CALL"):
            self.records.put(rec)

    def _forward(self, data: bytes) -> None:
        if self.relay is None:
            return
        try:
            self.relay.sendto(RELAY_MAGIC + self.relay_id + data,
                              (RELAY_GROUP, self.port + RELAY_OFFSET))
        except OSError:
            pass

    def _drain_relay(self) -> None:
        """Von anderen Empfängern weitergereichte Pakete verarbeiten (nie erneut weiterreichen)."""
        if self.relay is None:
            return
        n = len(RELAY_MAGIC)
        while True:
            try:
                data, addr = self.relay.recvfrom(65535)
            except (BlockingIOError, socket.timeout):
                return
            except OSError:
                return
            if data[:n] != RELAY_MAGIC or data[n:n + 8] == self.relay_id:
                continue
            self.handle(data[n + 8:], addr, relayed=True)


def adif_to_qso(rec: dict[str, str]):
    """ADIF-Felder (aus WSJT-X oder einer ADIF-Datei) -> Qso."""
    from .bands import band_for_freq, band_from_adif
    from .contests.base import Qso
    from .locator import normalize

    freq = 0
    if rec.get("FREQ"):
        try:
            freq = int(round(float(rec["FREQ"]) * 1_000_000))
        except ValueError:
            freq = 0
    band = band_for_freq(freq) or band_from_adif(rec.get("BAND", ""))
    mode = (rec.get("SUBMODE") or rec.get("MODE") or "").upper()
    d = rec.get("QSO_DATE", "")
    t = (rec.get("TIME_ON", "") + "000000")[:6]
    time_s = f"{d[:4]}-{d[4:6]}-{d[6:8]} {t[:2]}:{t[2:4]}:{t[4:6]}" if len(d) == 8 else ""
    grid = normalize(rec.get("GRIDSQUARE", ""))
    exch_r = grid or (rec.get("SRX_STRING") or rec.get("SRX") or "").strip().upper()
    return Qso(
        time=time_s,
        call=rec.get("CALL", "").upper(),
        band=band,
        mode=mode,
        freq=freq,
        rst_s=rec.get("RST_SENT", ""),
        rst_r=rec.get("RST_RCVD", ""),
        exch_s=(rec.get("STX_STRING") or rec.get("STX") or "").upper(),
        exch_r=exch_r,
        source="wsjtx",
    )


def wsjtx_direct_cat(config_dir: str | None = None) -> list[tuple[str, str, str]]:
    """FT8-Programme (WSJT-X, JTDX …), die das Funkgerät direkt über die Leitung steuern.

    Liest nur die Einstellungsdateien (~/.config/*.ini mit „Rig=“ und „CATSerialPort=“)
    und ändert nichts. Ergebnis: [(Datei, Rig, Schnittstelle)] für alle, die nicht
    über „Hamlib NET rigctl“ (bzw. „None“) gehen.
    """
    import glob
    import os
    base = config_dir or os.path.join(os.path.expanduser("~"), ".config")
    out = []
    for path in sorted(glob.glob(os.path.join(base, "*.ini"))):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read(200_000)
        except OSError:
            continue
        if "CATSerialPort=" not in text:
            continue
        rig = re.search(r"^Rig=(.*)$", text, re.M)
        port = re.search(r"^CATSerialPort=(.*)$", text, re.M)
        name = rig.group(1).strip() if rig else ""
        if not name or name in ("None", "Hamlib NET rigctl") or "NET rigctl" in name:
            continue
        out.append((path, name, port.group(1).strip() if port else ""))
    return out
