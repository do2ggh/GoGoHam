"""Icom-Funkgeräte über LAN/WLAN – ohne Zwischenprogramm (ab 0.10.30).

Icoms Netzwerk-Fernsteuerung (wie RS-BA1, IC-705/7610/9700/905 …) läuft über UDP auf drei
Ports: Steuerung (Standard 50001), CI-V (50002) und Ton (50003). Icom hat das Verfahren
nicht veröffentlicht; die Paketaufbauten folgen der freien Umsetzung in wfview
(GPL-3.0-only, Phil Taylor M0VSE u. a.), die ihrerseits auf kappanhang (MIT, HA2NON,
ES1AKOS, W6EL) beruht – siehe THIRD-PARTY.md.

So bindet GoGoHam das Gerät ein (Bauweise wie kappanhang):

* Dieser Baustein meldet sich am Funkgerät an und reicht den CI-V-Datenstrom an eine
  **unsichtbare serielle Schnittstelle** (Pseudo-Terminal) weiter.
* Darauf läuft ein ganz normaler **rigctld** mit dem Icom-Modell – für GoGoHam, WSJT-X,
  fldigi usw. sieht alles aus wie ein Funkgerät am USB-Kabel.
* Der Ton kommt als eigene **Soundkarte „GoGoHam Icom …“** ins System (PipeWire/PulseAudio,
  pipe-source/pipe-sink, direkt über libpulse), PCM 16 bit mono.

Start als eigener Prozess: ``python3 -m gogoham.icomlan`` – die Einstellungen kommen als JSON
über die Standardeingabe (das Passwort steht so nicht in der Prozessliste). Meldungen gehen
zeilenweise als JSON auf die Standardausgabe: {"state": …, "text": …}.

Achtung: Benutzername und Passwort überträgt das Icom-Verfahren nur **verschleiert**, nicht
verschlüsselt – nur im eigenen Netz benutzen, nicht offen ins Internet stellen.
"""

from __future__ import annotations

import json
import os
import random
import selectors
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
import tty
from dataclasses import dataclass, field
from pathlib import Path

from .i18n import tr

CONTROL_PORT = 50001
HEADER = struct.Struct("<IHHII")          # Länge, Typ, Folgenummer, Absender-ID, Empfänger-ID

# Paketgrößen (feste Größen kennzeichnen den Pakettyp)
CONTROL_SIZE = 0x10
PING_SIZE = 0x15
OPENCLOSE_SIZE = 0x16
AUDIO_HEAD = 0x18
TOKEN_SIZE = 0x40
STATUS_SIZE = 0x50
LOGIN_RESPONSE_SIZE = 0x60
LOGIN_SIZE = 0x80
CONNINFO_SIZE = 0x90
CAPABILITIES_SIZE = 0x42
RADIO_CAP_SIZE = 0x66
CIV_HEAD = 0x15

# Steuer-Typen
T_DATA, T_RETRANSMIT, T_ARE_YOU_THERE, T_I_AM_HERE, T_DISCONNECT, T_ARE_YOU_READY, T_PING = \
    0x00, 0x01, 0x03, 0x04, 0x05, 0x06, 0x07

PING_PERIOD = 0.5
IDLE_PERIOD = 0.1
AYT_PERIOD = 0.5
TOKEN_RENEWAL = 60.0
RETRANSMIT_PERIOD = 0.1
STALE = 8.0                               # so lange nichts gehört -> neu verbinden
TXBUF = 500

# Ton: 0x04 = PCM 16 bit mono (little endian); Opus kann nur ein wfview-Server
CODEC_PCM16 = 0x04
AUDIO_RATE = 48000
AUDIO_CHUNK = 1364                        # größtes Tonstück je Paket (wie wfview)
TX_FRAME = AUDIO_RATE * 2 // 50           # 20 ms

_PASSCODE = bytes(32) + bytes([
    0x47, 0x5d, 0x4c, 0x42, 0x66, 0x20, 0x23, 0x46, 0x4e, 0x57, 0x45, 0x3d, 0x67, 0x76, 0x60, 0x41,
    0x62, 0x39, 0x59, 0x2d, 0x68, 0x7e, 0x7c, 0x65, 0x7d, 0x49, 0x29, 0x72, 0x73, 0x78, 0x21, 0x6e,
    0x5a, 0x5e, 0x4a, 0x3e, 0x71, 0x2c, 0x2a, 0x54, 0x3c, 0x3a, 0x63, 0x4f, 0x43, 0x75, 0x27, 0x79,
    0x5b, 0x35, 0x70, 0x48, 0x6b, 0x56, 0x6f, 0x34, 0x32, 0x6c, 0x30, 0x61, 0x6d, 0x7b, 0x2f, 0x4b,
    0x64, 0x38, 0x2b, 0x2e, 0x50, 0x40, 0x3f, 0x55, 0x33, 0x37, 0x25, 0x77, 0x24, 0x26, 0x74, 0x6a,
    0x28, 0x53, 0x4d, 0x69, 0x22, 0x5c, 0x44, 0x31, 0x36, 0x58, 0x3b, 0x7a, 0x51, 0x5f, 0x52,
]) + bytes(32)


def passcode(text: str) -> bytes:
    """Benutzername/Passwort so verschleiern, wie es das Funkgerät erwartet (max. 16 Zeichen)."""
    out = bytearray()
    for i, ch in enumerate(text.encode("latin-1", "replace")[:16]):
        p = ch + i
        if p > 126:
            p = 32 + p % 127
        out.append(_PASSCODE[p] if p < len(_PASSCODE) else 0)
    return bytes(out)


def _cstr(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("latin-1", "replace").strip()


def _put(buf: bytearray, off: int, data: bytes) -> None:
    buf[off:off + len(data)] = data


def control_packet(ptype: int, seq: int, sent: int, rcvd: int) -> bytes:
    return HEADER.pack(CONTROL_SIZE, ptype, seq & 0xffff, sent, rcvd)


def endpoint_id(ip: str, port: int) -> int:
    a = socket.inet_aton(ip)
    return (a[2] << 24) | (a[3] << 16) | (port & 0xffff)


@dataclass
class RadioInfo:
    name: str = ""
    audio: str = ""
    civ: int = 0
    rxsample: int = 0
    txsample: int = 0
    commoncap: int = 0
    mac: bytes = b""
    guid: bytes = b""
    baud: int = 0


def parse_capabilities(r: bytes) -> list[RadioInfo]:
    out = []
    for off in range(CAPABILITIES_SIZE, len(r) - RADIO_CAP_SIZE + 1, RADIO_CAP_SIZE):
        c = r[off:off + RADIO_CAP_SIZE]
        out.append(RadioInfo(
            name=_cstr(c[0x10:0x30]), audio=_cstr(c[0x30:0x50]), civ=c[0x52],
            rxsample=struct.unpack_from("<H", c, 0x53)[0],
            txsample=struct.unpack_from("<H", c, 0x55)[0],
            commoncap=struct.unpack_from("<H", c, 0x07)[0], mac=bytes(c[0x0a:0x10]),
            guid=bytes(c[0:16]), baud=struct.unpack_from(">I", c, 0x5a)[0]))
    return out


class Stream:
    """Ein UDP-Kanal zum Funkgerät (Steuerung, CI-V oder Ton): Anmelden („Bist du da?“),
    Ping beantworten, Folgenummern, verlorene Pakete nachfordern und wiederholen."""

    def __init__(self, radio_ip: str, port: int, local_port: int = 0, request_missing=True):
        self.radio = (radio_ip, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", local_port))
        self.sock.setblocking(False)
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(self.radio)
            local_ip = probe.getsockname()[0]
        finally:
            probe.close()
        self.local_port = self.sock.getsockname()[1]
        self.my_id = endpoint_id(local_ip, self.local_port)
        self.remote_id = 0
        self.send_seq = 1
        self.ping_seq = 0
        self.txbuf: dict[int, bytes] = {}
        self.rx_last: int | None = None
        self.missing: dict[int, int] = {}
        self.request_missing = request_missing
        self.here = False                    # „Ich bin hier“ empfangen
        self.last_rx = time.monotonic()
        self.t_ayt = self.t_ping = self.t_idle = self.t_retr = 0.0
        self.sent = self.lost = 0

    # ---- Senden
    def raw(self, data: bytes) -> None:
        try:
            self.sock.sendto(data, self.radio)
        except OSError:
            pass

    def control(self, ptype: int, seq: int = 0) -> None:
        self.raw(control_packet(ptype, seq, self.my_id, self.remote_id))

    def tracked(self, data: bytes) -> None:
        """Paket mit Folgenummer senden und für Wiederholungen aufheben."""
        d = bytearray(data)
        struct.pack_into("<H", d, 6, self.send_seq)
        b = bytes(d)
        self.txbuf[self.send_seq] = b
        if len(self.txbuf) > TXBUF:
            self.txbuf.pop(next(iter(self.txbuf)))
        self.send_seq = (self.send_seq + 1) & 0xffff
        self.sent += 1
        self.t_idle = time.monotonic()
        self.raw(b)

    def ping(self) -> None:
        now_ms = int((time.time() % 86400) * 1000)
        self.raw(HEADER.pack(PING_SIZE, T_PING, self.ping_seq, self.my_id, self.remote_id)
                 + struct.pack("<BI", 0, now_ms))

    # ---- Empfangen (gemeinsamer Teil aller Kanäle)
    def handle(self, r: bytes) -> None:
        if len(r) < 0x10:
            return
        self.last_rx = time.monotonic()
        length, ptype, seq, sent, _rcvd = HEADER.unpack_from(r)
        if len(r) == CONTROL_SIZE:
            if ptype == T_RETRANSMIT:
                self._resend(seq)
            elif ptype == T_I_AM_HERE:
                self.here = True
                self.remote_id = sent
                self.control(T_ARE_YOU_READY, 1)
        elif len(r) == PING_SIZE and ptype == T_PING:
            if r[0x10] == 0:                       # Ping vom Funkgerät -> beantworten
                self.raw(HEADER.pack(PING_SIZE, T_PING, seq, self.my_id, self.remote_id)
                         + b"\x01" + r[0x11:0x15])
            elif r[0x10] == 1 and seq == self.ping_seq:
                self.ping_seq = (self.ping_seq + 1) & 0xffff
            return
        if ptype == T_RETRANSMIT and len(r) > CONTROL_SIZE:
            for s in sorted({struct.unpack_from("<H", r, i)[0]
                             for i in range(0x10, len(r) - 1, 2)}):
                self._resend(s)
        elif ptype == T_DATA and seq != 0 and len(r) != PING_SIZE:
            self._track_rx(seq)

    def _resend(self, seq: int) -> None:
        d = self.txbuf.get(seq)
        if d is not None:
            self.lost += 1
            self.raw(d)
        else:
            self.control(T_DATA, seq)             # nicht mehr da: Leerpaket statt Lücke

    def _track_rx(self, seq: int) -> None:
        if self.rx_last is None:
            self.rx_last = seq
            return
        diff = (seq - self.rx_last) & 0xffff
        if diff == 0:
            return
        if diff > 0x8000:                           # älteres Paket (Wiederholung) angekommen
            self.missing.pop(seq, None)
            return
        if diff > 50:                               # großer Sprung: neu anfangen
            self.missing.clear()
        elif self.request_missing:
            for k in range(1, diff):
                self.missing.setdefault((self.rx_last + k) & 0xffff, 0)
        self.rx_last = seq

    def request_retransmits(self) -> None:
        if not self.missing:
            return
        if len(self.missing) > 50:
            self.missing.clear()
            return
        want = []
        for s in list(self.missing):
            self.missing[s] += 1
            if self.missing[s] > 4:
                del self.missing[s]
            else:
                want.append(s)
        if len(want) == 1:
            self.control(T_RETRANSMIT, want[0])
        elif want:
            body = b"".join(struct.pack("<HH", s, s) for s in want)
            self.raw(HEADER.pack(CONTROL_SIZE + len(body), T_RETRANSMIT, 0, self.my_id,
                                 self.remote_id) + body)

    def tick(self, now: float, idle: bool) -> None:
        if not self.here:
            if now - self.t_ayt >= AYT_PERIOD:
                self.t_ayt = now
                self.control(T_ARE_YOU_THERE)
            return
        if now - self.t_ping >= PING_PERIOD:
            self.t_ping = now
            self.ping()
        if idle and now - self.t_idle >= IDLE_PERIOD:
            self.tracked(control_packet(T_DATA, 0, self.my_id, self.remote_id))
        if now - self.t_retr >= RETRANSMIT_PERIOD:
            self.t_retr = now
            self.request_retransmits()

    def close(self) -> None:
        self.control(T_DISCONNECT)
        self.sock.close()


class LoginError(Exception):
    pass


@dataclass
class Settings:
    host: str
    user: str
    password: str
    port: int = CONTROL_PORT
    audio: bool = True
    client_name: str = "GoGoHam"
    rx_rate: int = AUDIO_RATE
    tx_rate: int = AUDIO_RATE
    tx_latency: int = 150


@dataclass
class Session:
    """Verbindung zu einem Icom-Funkgerät: Steuerkanal + CI-V + Ton.

    on_civ(bytes): CI-V-Daten vom Funkgerät · on_audio(bytes): Ton (PCM16 mono) vom Funkgerät ·
    on_state(state, text): Statusmeldungen."""
    cfg: Settings
    on_civ: object = None
    on_audio: object = None
    on_state: object = None
    radio: RadioInfo | None = None
    ctrl: Stream | None = None
    civ: Stream | None = None
    aud: Stream | None = None
    token: bytes = b"\0\0\0\0"
    tokrequest: int = 0
    auth_seq: int = 0x30
    civ_seq: int = 0
    audio_seq: int = 0
    authenticated: bool = False
    stream_open: bool = False
    civ_flowing: bool = False
    t_token: float = 0.0
    t_open: float = 0.0
    t_civ_rx: float = 0.0
    t_request: float = -10.0
    tx_ok: bool = False
    error: str = ""
    busy_by: str = ""
    _civ_local: int = 0
    _audio_local: int = 0
    states: list = field(default_factory=list)

    def _state(self, state: str, text: str = "") -> None:
        self.states.append(state)
        if callable(self.on_state):
            self.on_state(state, text)

    # ---- Aufbau
    def start(self) -> None:
        self.ctrl = Stream(self.cfg.host, self.cfg.port)
        self._state("connecting", self.cfg.host)

    def sockets(self) -> list[tuple[socket.socket, Stream]]:
        return [(s.sock, s) for s in (self.ctrl, self.civ, self.aud) if s is not None]

    def _inner(self, size: int, rtype: int) -> bytearray:
        p = bytearray(size)
        HEADER.pack_into(p, 0, size, 0, 0, self.ctrl.my_id, self.ctrl.remote_id)
        struct.pack_into(">I", p, 0x10, size - 0x10)
        p[0x14] = 0x01
        p[0x15] = rtype
        struct.pack_into(">H", p, 0x16, self.auth_seq)
        self.auth_seq = (self.auth_seq + 1) & 0xffff
        struct.pack_into("<H", p, 0x1a, self.tokrequest)
        _put(p, 0x1c, self.token)
        return p

    def _login(self) -> None:
        self.tokrequest = random.randint(1, 0xffff)
        p = self._inner(LOGIN_SIZE, 0x00)
        _put(p, 0x40, passcode(self.cfg.user))
        _put(p, 0x50, passcode(self.cfg.password))
        _put(p, 0x60, self.cfg.client_name.encode()[:16])
        self.ctrl.tracked(bytes(p))
        self._state("login")

    def _send_token(self, magic: int) -> None:
        p = self._inner(TOKEN_SIZE, magic)
        struct.pack_into(">H", p, 0x24, 0x0798)
        self.ctrl.tracked(bytes(p))
        self.t_token = time.monotonic()

    def _request_stream(self) -> None:
        r = self.radio
        if r is None or time.monotonic() - self.t_request < 2.0:
            return
        self.t_request = time.monotonic()
        if not self._civ_local:
            self._civ_local, self._audio_local = _free_udp_port(), _free_udp_port()
        p = self._inner(CONNINFO_SIZE, 0x03)
        if r.commoncap == 0x8010:
            struct.pack_into("<H", p, 0x27, 0x8010)
            _put(p, 0x2a, r.mac)
        else:
            _put(p, 0x20, r.guid)
        _put(p, 0x40, r.name.encode()[:32])
        _put(p, 0x60, passcode(self.cfg.user))
        p[0x70] = 1
        self.tx_ok = self.cfg.audio and r.txsample > 1
        if self.tx_ok:
            p[0x71] = 1
            p[0x73] = CODEC_PCM16
        p[0x72] = CODEC_PCM16 if self.cfg.audio else 0
        struct.pack_into(">IIIII", p, 0x74, self.cfg.rx_rate if self.cfg.audio else 0,
                         self.cfg.tx_rate if self.tx_ok else 0, self._civ_local,
                         self._audio_local, self.cfg.tx_latency)
        p[0x88] = 1
        self.ctrl.tracked(bytes(p))
        self._state("stream-request", r.name)

    # ---- Empfang
    def receive(self, stream: Stream, r: bytes) -> None:
        if stream is self.ctrl:
            self._ctrl_packet(r)
        elif stream is self.civ:
            self._civ_packet(r)
        elif stream is self.aud:
            self._audio_packet(r)
        stream.handle(r)

    def _ctrl_packet(self, r: bytes) -> None:
        n = len(r)
        ptype = struct.unpack_from("<H", r, 4)[0] if n >= 6 else 0
        if n == CONTROL_SIZE and ptype == T_ARE_YOU_READY:
            self._login()
        elif n == LOGIN_RESPONSE_SIZE and ptype != T_RETRANSMIT:
            err = struct.unpack_from("<I", r, 0x30)[0]
            if err == 0xfeffffff:
                self.error = "auth"
                self._state("error-auth", "")
                raise LoginError("auth")
            if not self.authenticated and struct.unpack_from("<H", r, 0x1a)[0] == self.tokrequest:
                self.token = bytes(r[0x1c:0x20])
                self.authenticated = True
                self._send_token(0x02)
                self._state("authenticated", _cstr(r[0x40:0x50]))
        elif n == TOKEN_SIZE and ptype != T_RETRANSMIT:
            if r[0x15] == 0x05 and r[0x14] == 0x02:
                resp = struct.unpack_from("<I", r, 0x30)[0]
                if resp == 0 and not self.stream_open:
                    self._request_stream()
                elif resp == 0xffffffff:
                    self.ctrl.remote_id = struct.unpack_from("<I", r, 8)[0]
                    self.tokrequest = struct.unpack_from("<H", r, 0x1a)[0]
                    self.token = bytes(r[0x1c:0x20])
                    self.stream_open = False
                    self._request_stream()
        elif n == STATUS_SIZE and ptype != T_RETRANSMIT:
            err = struct.unpack_from("<I", r, 0x30)[0]
            if err == 0xffffffff and not self.stream_open:
                self.error = "refused"
                self._state("error-refused", "")
            elif err == 0 and r[0x40] == 0x01:
                self._close_streams()
                self._state("radio-disconnected", "")
            else:
                civ_port = struct.unpack_from(">H", r, 0x42)[0]
                audio_port = struct.unpack_from(">H", r, 0x46)[0]
                if not self.stream_open and civ_port:
                    self.civ = Stream(self.cfg.host, civ_port, self._civ_local)
                    if self.cfg.audio and audio_port:
                        self.aud = Stream(self.cfg.host, audio_port, self._audio_local,
                                          request_missing=False)
                    self.stream_open = True
                    self._state("streams", f"{civ_port}/{audio_port}")
        elif n == CONNINFO_SIZE:
            busy = struct.unpack_from("<I", r, 0x60)[0]
            computer = _cstr(r[0x64:0x74])
            if busy and computer and computer != self.cfg.client_name[:16]:
                if not self.stream_open:
                    self.busy_by = computer
                    self._state("busy", computer)
            elif not self.stream_open and self.radio is not None:
                self._request_stream()
        elif n >= CAPABILITIES_SIZE + RADIO_CAP_SIZE and \
                (n - CAPABILITIES_SIZE) % RADIO_CAP_SIZE == 0 and ptype != T_RETRANSMIT:
            radios = parse_capabilities(r)
            if radios:
                self.radio = radios[0]
                self._state("radio", self.radio.name)

    def _civ_packet(self, r: bytes) -> None:
        n = len(r)
        ptype = struct.unpack_from("<H", r, 4)[0] if n >= 6 else 0
        if n == CONTROL_SIZE and ptype == T_ARE_YOU_READY:
            self.civ.remote_id = struct.unpack_from("<I", r, 8)[0]
            self._open_civ(True)
            if not self.civ_flowing:              # CI-V-Kanal offen: ab jetzt verbunden
                self.civ_flowing = True
                self._state("connected", self.radio.name if self.radio else "")
        elif n > CIV_HEAD and ptype != T_RETRANSMIT:
            dlen = struct.unpack_from("<H", r, 0x11)[0]
            if dlen + CIV_HEAD == struct.unpack_from("<I", r, 0)[0] and r[0x10] == 0xc1:
                self.t_civ_rx = time.monotonic()
                if callable(self.on_civ):
                    self.on_civ(bytes(r[CIV_HEAD:]))

    def _open_civ(self, open_: bool) -> None:
        if self.civ is None:
            return
        p = bytearray(OPENCLOSE_SIZE)
        HEADER.pack_into(p, 0, OPENCLOSE_SIZE, 0, 0, self.civ.my_id, self.civ.remote_id)
        struct.pack_into("<H", p, 0x10, 0x01c0)
        struct.pack_into(">H", p, 0x13, self.civ_seq)
        p[0x15] = 0x04 if open_ else 0x00
        self.civ_seq = (self.civ_seq + 1) & 0xffff
        self.civ.tracked(bytes(p))
        self.t_open = time.monotonic()

    def _audio_packet(self, r: bytes) -> None:
        if len(r) < 0x20 or struct.unpack_from("<H", r, 4)[0] == T_RETRANSMIT:
            return
        if callable(self.on_audio):
            self.on_audio(bytes(r[AUDIO_HEAD:]))

    # ---- Senden an das Funkgerät
    def send_civ(self, data: bytes) -> None:
        if self.civ is None or not self.civ.here:
            return
        p = bytearray(CIV_HEAD)
        HEADER.pack_into(p, 0, CIV_HEAD + len(data), 0, 0, self.civ.my_id, self.civ.remote_id)
        p[0x10] = 0xc1
        struct.pack_into("<H", p, 0x11, len(data))
        struct.pack_into(">H", p, 0x13, self.civ_seq)
        self.civ_seq = (self.civ_seq + 1) & 0xffff
        self.civ.tracked(bytes(p) + data)

    def send_audio(self, pcm: bytes) -> None:
        if self.aud is None or not self.aud.here or not self.tx_ok:
            return
        for i in range(0, len(pcm), AUDIO_CHUNK):
            part = pcm[i:i + AUDIO_CHUNK]
            p = bytearray(AUDIO_HEAD)
            HEADER.pack_into(p, 0, AUDIO_HEAD + len(part), 0, 0, self.aud.my_id,
                             self.aud.remote_id)
            struct.pack_into("<H", p, 0x10, 0x9781 if len(part) == 0xa0 else 0x0080)
            struct.pack_into(">H", p, 0x12, self.audio_seq)
            struct.pack_into(">H", p, 0x16, len(part))
            self.audio_seq = (self.audio_seq + 1) & 0xffff
            self.aud.tracked(bytes(p) + part)

    # ---- Takt
    def tick(self) -> None:
        now = time.monotonic()
        self.ctrl.tick(now, idle=True)
        if self.authenticated and now - self.t_token >= TOKEN_RENEWAL:
            self._send_token(0x05)
        if self.civ is not None:
            self.civ.tick(now, idle=True)
            if self.civ.here and now - self.t_civ_rx > 2.0 and now - self.t_open > 2.0:
                self._open_civ(True)              # (noch) keine CI-V-Daten: Start wiederholen
        if self.aud is not None:
            self.aud.tick(now, idle=False)

    def stale(self) -> bool:
        """Lange nichts vom Funkgerät gehört?"""
        return self.ctrl is not None and time.monotonic() - self.ctrl.last_rx > STALE

    def _close_streams(self) -> None:
        if self.civ is not None:
            self._open_civ(False)
            self.civ.close()
            self.civ = None
        if self.aud is not None:
            self.aud.close()
            self.aud = None
        self.stream_open = False
        self.civ_flowing = False

    def close(self) -> None:
        self._close_streams()
        if self.ctrl is not None:
            if self.authenticated:
                self._send_token(0x01)
            self.ctrl.close()
            self.ctrl = None


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def discover(timeout: float = 1.5, port: int = CONTROL_PORT,
             targets: list[str] | None = None) -> list[str]:
    """Icom-Funkgeräte im Netz suchen: „Bist du da?“ an alle (Broadcast), Antworten sammeln.

    Liefert die IP-Adressen der Geräte, die geantwortet haben (Netzwerk-Fernsteuerung muss im
    Funkgerät eingeschaltet sein)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.bind(("", 0))
    s.settimeout(0.2)
    my_id = random.randint(1, 0xffffffff)
    found: list[str] = []
    pkt = control_packet(T_ARE_YOU_THERE, 0, my_id, 0)
    end = time.monotonic() + timeout
    t_send = 0.0
    try:
        while time.monotonic() < end:
            if time.monotonic() - t_send > 0.5:
                t_send = time.monotonic()
                for t in targets or ["255.255.255.255"]:
                    try:
                        s.sendto(pkt, (t, port))
                    except OSError:
                        pass
            try:
                r, (ip, _p) = s.recvfrom(2048)
            except (socket.timeout, OSError):
                continue
            if len(r) == CONTROL_SIZE and struct.unpack_from("<H", r, 4)[0] == T_I_AM_HERE:
                if ip not in found:
                    found.append(ip)
                    # sofort wieder abmelden, damit das Gerät nicht auf uns wartet
                    s.sendto(control_packet(T_DISCONNECT, 0, my_id,
                                            struct.unpack_from("<I", r, 8)[0]), (ip, port))
    finally:
        s.close()
    return found


# ------------------------------------------------------------------ Ton übers System
def runtime_dir(tmp_root: str = "/tmp") -> Path:
    """Ordner für Laufzeit-Dateien. Ohne XDG_RUNTIME_DIR (selten) ein eigener Ordner unter /tmp –
    der muss dann wirklich uns gehören und für andere zu sein (sonst könnte ihn jemand vorab
    anlegen und die Dateien umlenken)."""
    base = os.environ.get("XDG_RUNTIME_DIR")
    if not base:
        base = os.path.join(tmp_root, f"gogoham-{os.getuid()}")
        try:
            os.mkdir(base, 0o700)
        except FileExistsError:
            pass
        st = os.lstat(base)
        import stat
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise OSError(tr("Unsicherer Ordner {d} (gehört nicht dir oder ist für andere "
                             "offen) – bitte löschen.", d=base))
    d = Path(base) / "gogoham"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sound_names(rig_port: int) -> tuple[str, str]:
    """(Ausgang = Senden zum Funkgerät, Eingang = Empfang) – PulseAudio/PipeWire-Namen."""
    return f"gogoham_icom_{rig_port}_tx", f"gogoham_icom_{rig_port}_rx"


class SoundDevices:
    """Virtuelle Soundkarte (PipeWire/PulseAudio): Empfang als Eingang (pipe-source), Senden
    als Ausgang (pipe-sink). Ab 0.10.30.1 direkt über libpulse (gogoham.pulse), Notweg pactl."""

    def __init__(self, rig_port: int, name: str, backend=None):
        self.backend = backend
        self.sink, self.source = sound_names(rig_port)
        d = runtime_dir()
        self.rx_path = d / f"icom-{rig_port}-rx"
        self.tx_path = d / f"icom-{rig_port}-tx"
        self.name = name
        self.modules: list[int] = []
        self.rx_fd = self.tx_fd = -1

    def open(self) -> bool:
        if self.backend is None:
            from . import pulse
            self.backend = pulse.backend()
        if self.backend is None:
            return False
        self.unload_stale()
        label = (self.name or "Icom").replace(" ", "-")
        common = f"format=s16le rate={AUDIO_RATE} channels=1"
        for module, args in (
                ("module-pipe-source", f"source_name={self.source} file={self.rx_path} {common} "
                                       f"source_properties=device.description=GoGoHam-{label}-Empfang"),
                ("module-pipe-sink", f"sink_name={self.sink} file={self.tx_path} {common} "
                                     f"sink_properties=device.description=GoGoHam-{label}-Senden")):
            idx = self.backend.load(module, args)
            if idx is None:
                self.close()
                return False
            self.modules.append(idx)
        # Empfang: GoGoHam schreibt hinein (ohne zu blockieren); Senden: GoGoHam liest
        self.rx_fd = os.open(self.rx_path, os.O_RDWR | os.O_NONBLOCK)
        self.tx_fd = os.open(self.tx_path, os.O_RDONLY | os.O_NONBLOCK)
        return True

    def unload_stale(self) -> None:
        """Reste eines abgestürzten Laufs mit denselben Namen entfernen."""
        for idx, _name, args in self.backend.modules():
            words = args.split()
            if f"sink_name={self.sink}" in words or f"source_name={self.source}" in words:
                self.backend.unload(idx)

    def write_rx(self, pcm: bytes) -> None:
        if self.rx_fd >= 0:
            try:
                os.write(self.rx_fd, pcm)
            except (BlockingIOError, OSError):
                pass                              # niemand hört zu: Ton verwerfen

    def close(self) -> None:
        for fd in (self.rx_fd, self.tx_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self.rx_fd = self.tx_fd = -1
        for m in self.modules:
            try:
                self.backend.unload(m)
            except Exception:  # noqa: BLE001 – beim Aufräumen nie abbrechen
                pass
        self.modules = []


# ------------------------------------------------------------------ Brücke (eigener Prozess)
class Bridge:
    """Funkgerät (UDP) <-> Pseudo-Terminal (für rigctld) und <-> virtuelle Soundkarte."""

    def __init__(self, conf: dict, out=None, sound_factory=SoundDevices):
        self.conf = conf
        self.out = out or sys.stdout
        self.settings = Settings(host=conf["host"], user=conf.get("user", ""),
                                 password=conf.get("password", ""),
                                 port=int(conf.get("ctrl_port") or CONTROL_PORT),
                                 audio=bool(conf.get("audio", True)),
                                 client_name=conf.get("client_name", "GoGoHam"))
        self.rig_port = int(conf.get("rig_port") or 0)
        self.master, self.slave = os.openpty()
        tty.setraw(self.slave)
        tty.setraw(self.master)
        os.set_blocking(self.master, False)
        self.pty_path = os.ttyname(self.slave)
        self.link = None
        if self.rig_port:
            self.link = runtime_dir() / f"icom-{self.rig_port}"
            try:
                self.link.unlink()
            except FileNotFoundError:
                pass
            try:
                self.link.symlink_to(self.pty_path)
            except OSError:
                self.link = None
        self.sound = None
        if self.settings.audio and self.rig_port and sound_factory is not None:
            self.sound = sound_factory(self.rig_port, conf.get("model_name", ""))
        self.rigctld: subprocess.Popen | None = None
        self.session: Session | None = None
        self.running = True
        self.fatal = ""

    def emit(self, state: str, text: str = "") -> None:
        try:
            self.out.write(json.dumps({"state": state, "text": text}) + "\n")
            self.out.flush()
        except (OSError, ValueError):
            pass

    def _on_state(self, state: str, text: str) -> None:
        self.emit(state, text)
        if state == "connected":
            self._start_rigctld()

    def _start_rigctld(self) -> None:
        if self.rigctld is not None or not self.rig_port or not self.conf.get("model"):
            return
        exe = shutil.which("rigctld")
        if not exe:
            self.emit("error-rigctld", "rigctld")
            return
        cmd = [exe, "-m", str(self.conf["model"]), "-r", self.pty_path, "-s", "115200",
               "-t", str(self.rig_port)] + str(self.conf.get("extra", "")).split()
        self.rigctld = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.emit("rigctld", str(self.rig_port))

    def _new_session(self) -> None:
        if self.session is not None:
            self.session.close()
        self.session = Session(self.settings, on_civ=self._to_pty,
                               on_audio=self.sound.write_rx if self.sound else None,
                               on_state=self._on_state)
        self.session.start()

    def _to_pty(self, data: bytes) -> None:
        try:
            os.write(self.master, data)
        except (BlockingIOError, OSError):
            pass

    def run(self, max_seconds: float | None = None) -> int:
        if self.sound is not None:
            if self.sound.open():
                self.emit("sound", f"{self.sound.sink} {self.sound.source}")
            else:
                self.emit("sound-missing", "")
                self.sound = None
        self._new_session()
        sel = selectors.DefaultSelector()
        sel.register(self.master, selectors.EVENT_READ, "pty")
        if self.sound is not None:
            sel.register(self.sound.tx_fd, selectors.EVENT_READ, "tx")
        registered: dict[int, Stream] = {}
        txbuf = b""
        start = time.monotonic()
        try:
            while self.running:
                if max_seconds is not None and time.monotonic() - start > max_seconds:
                    break
                # Kanäle können während des Laufs dazukommen/wegfallen
                current = {s.fileno(): st for s, st in self.session.sockets()}
                for fd in set(registered) - set(current):
                    try:
                        sel.unregister(fd)
                    except (KeyError, ValueError):
                        pass
                for fd, st in current.items():
                    if fd not in registered:
                        sel.register(fd, selectors.EVENT_READ, st)
                registered = current
                for key, _ev in sel.select(timeout=0.02):
                    if key.data == "pty":
                        try:
                            data = os.read(self.master, 4096)
                        except (BlockingIOError, OSError):
                            data = b""
                        if data:
                            self.session.send_civ(data)
                    elif key.data == "tx":
                        try:
                            data = os.read(self.sound.tx_fd, 8192)
                        except (BlockingIOError, OSError):
                            data = b""
                        txbuf += data
                        while len(txbuf) >= TX_FRAME:
                            frame, txbuf = txbuf[:TX_FRAME], txbuf[TX_FRAME:]
                            if frame.count(0) != len(frame):     # Stille nicht senden
                                self.session.send_audio(frame)
                    else:
                        try:
                            r = key.data.sock.recv(65535)
                        except (BlockingIOError, OSError):
                            continue
                        try:
                            self.session.receive(key.data, r)
                        except LoginError:
                            self.fatal = "auth"
                            self.running = False
                            break
                if not self.running:
                    break
                self.session.tick()
                if self.session.stale():
                    self.emit("reconnect", "")
                    self._new_session()
                    registered = {}
                    sel.close()
                    sel = selectors.DefaultSelector()
                    sel.register(self.master, selectors.EVENT_READ, "pty")
                    if self.sound is not None:
                        sel.register(self.sound.tx_fd, selectors.EVENT_READ, "tx")
        finally:
            self.shutdown()
        return 2 if self.fatal else 0

    def stop(self, *_a) -> None:
        self.running = False

    def shutdown(self) -> None:
        if self.rigctld is not None:
            self.rigctld.terminate()
            try:
                self.rigctld.wait(2)
            except subprocess.TimeoutExpired:
                self.rigctld.kill()
            self.rigctld = None
        if self.session is not None:
            self.session.close()
            self.session = None
        if self.sound is not None:
            self.sound.close()
            self.sound = None
        if self.link is not None:
            try:
                self.link.unlink()
            except OSError:
                pass
        for fd in (self.master, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass
        self.emit("stopped", self.fatal)


def bridge_command() -> list[str]:
    return [sys.executable, "-m", "gogoham.icomlan"]


def start_bridge(prof: dict, rig_port: int, extra: str = "", cwd: str | None = None):
    """Brücke als eigenen Prozess starten (Popen). Die Einstellungen (samt Passwort) gehen
    über die Standardeingabe, nicht über die Befehlszeile."""
    from .hamlib import find_model
    m = find_model(int(prof.get("model") or 0))
    conf = {"host": prof.get("net_host", ""), "ctrl_port": int(prof.get("net_port") or CONTROL_PORT),
            "user": prof.get("net_user", ""), "password": prof.get("net_pass", ""),
            "audio": bool(prof.get("net_audio", True)), "model": int(prof.get("model") or 0),
            "model_name": m.name if m else "", "rig_port": int(rig_port), "extra": extra}
    env = dict(os.environ)
    root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    proc = subprocess.Popen(bridge_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, env=env, cwd=cwd or root)
    proc.stdin.write(json.dumps(conf))
    proc.stdin.close()
    return proc


def main() -> int:
    try:
        conf = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        print(json.dumps({"state": "error-config", "text": ""}), flush=True)
        return 2
    if not conf.get("host"):
        print(json.dumps({"state": "error-config", "text": "host"}), flush=True)
        return 2
    b = Bridge(conf)
    signal.signal(signal.SIGTERM, b.stop)
    signal.signal(signal.SIGINT, b.stop)
    return b.run()


if __name__ == "__main__":
    sys.exit(main())
