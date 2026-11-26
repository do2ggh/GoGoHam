"""Nachgebautes Icom-Funkgerät (Netzwerk-Fernsteuerung) für Tests – antwortet wie ein
IC-9700 auf Anmeldung, CI-V und Ton. Läuft in einem Thread auf 127.0.0.1."""

from __future__ import annotations

import select
import socket
import struct
import threading
import time

from gogoham import icomlan as il

H = il.HEADER


class FakeIcom:
    def __init__(self, user="franz", password="geheim", name="IC-9700", civ=0xA2,
                 busy_by: str = "", drop_civ_seq: int | None = None, answer_civ: bool = False):
        self.user, self.password = il.passcode(user), il.passcode(password)
        self.name, self.civaddr, self.busy_by = name, civ, busy_by
        self.drop_civ_seq = drop_civ_seq
        self.answer_civ = answer_civ
        self.freq = 145_000_000
        self.mode = 0x01                       # USB
        self.ptt = 0
        self.ctrl = self._sock()
        self.civ = self._sock()
        self.aud = self._sock()
        self.port = self.ctrl.getsockname()[1]
        self.ids = {self.ctrl: 0x11110001, self.civ: 0x11110002, self.aud: 0x11110003}
        self.peer: dict = {}
        self.peer_id: dict = {}
        self.seq = {self.ctrl: 1, self.civ: 1, self.aud: 1}
        self.civ_in: list[bytes] = []
        self.audio_in: list[bytes] = []
        self.civ_open = False
        self.logins = 0
        self.retransmit_requests: list[int] = []
        self.sent_civ: dict[int, bytes] = {}
        self.client_ports: tuple[int, int] = (0, 0)
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    @staticmethod
    def _sock():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        return s

    def stop(self):
        self.running = False
        self.thread.join(2)
        for s in (self.ctrl, self.civ, self.aud):
            s.close()

    # ---- senden
    def _send(self, s, data: bytes):
        if s in self.peer:
            s.sendto(data, self.peer[s])

    def _control(self, s, ptype, seq=0):
        self._send(s, H.pack(0x10, ptype, seq, self.ids[s], self.peer_id.get(s, 0)))

    def _tracked(self, s, data: bytearray) -> int:
        seq = self.seq[s]
        struct.pack_into("<HII", data, 6, seq, self.ids[s], self.peer_id.get(s, 0))
        self.seq[s] = seq + 1
        return seq

    def send_civ(self, frame: bytes, drop: bool = False):
        p = bytearray(il.CIV_HEAD)
        struct.pack_into("<I", p, 0, il.CIV_HEAD + len(frame))
        p[0x10] = 0xc1
        struct.pack_into("<H", p, 0x11, len(frame))
        seq = self._tracked(self.civ, p)
        pkt = bytes(p) + frame
        self.sent_civ[seq] = pkt
        if not drop:
            self._send(self.civ, pkt)

    def send_audio(self, pcm: bytes):
        p = bytearray(il.AUDIO_HEAD)
        struct.pack_into("<I", p, 0, il.AUDIO_HEAD + len(pcm))
        struct.pack_into(">H", p, 0x16, len(pcm))
        self._tracked(self.aud, p)
        self._send(self.aud, bytes(p) + pcm)

    def _inner_reply(self, size, req: bytes, rtype: int, reply=0x02) -> bytearray:
        p = bytearray(size)
        H.pack_into(p, 0, size, 0, 0, self.ids[self.ctrl], self.peer_id.get(self.ctrl, 0))
        struct.pack_into(">I", p, 0x10, size - 0x10)
        p[0x14] = reply
        p[0x15] = rtype
        p[0x16:0x18] = req[0x16:0x18]
        p[0x1a:0x1c] = req[0x1a:0x1c]
        return p

    # ---- empfangen
    def _loop(self):
        socks = [self.ctrl, self.civ, self.aud]
        while self.running:
            r, _w, _x = select.select(socks, [], [], 0.05)
            for s in r:
                try:
                    data, addr = s.recvfrom(65535)
                except OSError:
                    continue
                self.peer[s] = addr
                self._handle(s, data)

    def _handle(self, s, r: bytes):
        n = len(r)
        _l, ptype, seq, sent, _rc = H.unpack_from(r)
        if n == 0x10:
            if ptype == il.T_ARE_YOU_THERE:
                self.peer_id[s] = sent
                self._control(s, il.T_I_AM_HERE)
            elif ptype == il.T_ARE_YOU_READY:
                self._control(s, il.T_ARE_YOU_READY)
            elif ptype == il.T_RETRANSMIT and s is self.civ:
                self.retransmit_requests.append(seq)
                if seq in self.sent_civ:
                    self._send(s, self.sent_civ[seq])
            return
        if ptype == il.T_RETRANSMIT and s is self.civ:
            for i in range(0x10, n - 1, 2):
                q = struct.unpack_from("<H", r, i)[0]
                self.retransmit_requests.append(q)
                if q in self.sent_civ:
                    self._send(s, self.sent_civ[q])
            return
        if s is self.ctrl:
            self._ctrl(r)
        elif s is self.civ:
            if n == il.OPENCLOSE_SIZE:
                self.civ_open = r[0x15] == 0x04
            elif n > il.CIV_HEAD and r[0x10] == 0xc1:
                self.civ_in.append(r[il.CIV_HEAD:])
                if self.answer_civ:
                    for fr in r[il.CIV_HEAD:].split(b"\xfd"):
                        if fr.startswith(b"\xfe\xfe") and len(fr) >= 5:
                            self._answer(fr[4:])
        elif s is self.aud and n > il.AUDIO_HEAD:
            self.audio_in.append(r[il.AUDIO_HEAD:])

    def _answer(self, body: bytes):
        """Wenige CI-V-Befehle wie ein echtes Gerät beantworten (Frequenz, Mode, PTT)."""
        me, ctl = bytes([self.civaddr]), b"\xe0"
        head = b"\xfe\xfe" + ctl + me
        cmd = body[:1]
        if cmd == b"\x03":
            f = f"{self.freq:010d}"
            bcd = bytes(int(f[i - 2] + f[i - 1], 16) for i in range(10, 0, -2))
            self.send_civ(head + b"\x03" + bcd + b"\xfd")
        elif cmd == b"\x04":
            self.send_civ(head + bytes([0x04, self.mode, 0x01]) + b"\xfd")
        elif cmd == b"\x05" and len(body) >= 6:
            d = body[1:6]
            self.freq = int("".join(f"{b:02x}" for b in reversed(d)))
            self.send_civ(head + b"\xfb\xfd")
        elif body[:2] == b"\x1c\x00" and len(body) == 2:
            self.send_civ(head + bytes([0x1c, 0x00, self.ptt]) + b"\xfd")
        elif body[:2] == b"\x1c\x00":
            self.ptt = body[2]
            self.send_civ(head + b"\xfb\xfd")
        elif body[:2] == b"\x25\x00" and len(body) == 2:
            f = f"{self.freq:010d}"
            bcd = bytes(int(f[i - 2] + f[i - 1], 16) for i in range(10, 0, -2))
            self.send_civ(head + b"\x25\x00" + bcd + b"\xfd")
        elif body[:2] == b"\x25\x00" and len(body) >= 7:
            self.freq = int("".join(f"{b:02x}" for b in reversed(body[2:7])))
            self.send_civ(head + b"\xfb\xfd")
        elif body[:2] == b"\x26\x00" and len(body) == 2:
            self.send_civ(head + bytes([0x26, 0x00, self.mode, 0x00, 0x01]) + b"\xfd")
        elif body[:2] == b"\x26\x00":
            self.mode = body[2]
            self.send_civ(head + b"\xfb\xfd")
        elif body[:1] in (b"\x14", b"\x16") and len(body) == 2:
            self.send_civ(head + body + b"\x00\x00\xfd")
        elif body[:2] == b"\x19\x00":
            self.send_civ(head + b"\x19\x00" + me + b"\xfd")
        else:
            self.send_civ(head + b"\xfa\xfd")             # „kann ich nicht“

    def _ctrl(self, r: bytes):
        n = len(r)
        if n == il.LOGIN_SIZE:
            self.logins += 1
            ok = r[0x40:0x50].rstrip(b"\0") == self.user and \
                r[0x50:0x60].rstrip(b"\0") == self.password
            p = self._inner_reply(il.LOGIN_RESPONSE_SIZE, r, 0x00)
            p[0x1c:0x20] = b"TOKN"
            struct.pack_into("<I", p, 0x30, 0 if ok else 0xfeffffff)
            p[0x40:0x44] = b"FTTH"
            self._tracked(self.ctrl, p)
            self._send(self.ctrl, bytes(p))
        elif n == il.TOKEN_SIZE and r[0x15] == 0x02:
            # Anmeldung bestätigt -> Fähigkeiten und Verbindungsstand schicken
            cap = bytearray(il.CAPABILITIES_SIZE + il.RADIO_CAP_SIZE)
            struct.pack_into("<I", cap, 0, len(cap))
            struct.pack_into("<H", cap, 0x40, 1)
            o = il.CAPABILITIES_SIZE
            struct.pack_into("<H", cap, o + 7, 0x8010)
            cap[o + 0x0a:o + 0x10] = b"\x00\x90\xc7\x01\x02\x03"
            cap[o + 0x10:o + 0x10 + len(self.name)] = self.name.encode()
            cap[o + 0x30:o + 0x36] = b"ICOM_V"
            cap[o + 0x52] = self.civaddr
            struct.pack_into("<HH", cap, o + 0x53, 0x8b, 0x8b)
            struct.pack_into(">I", cap, o + 0x5a, 115200)
            self._tracked(self.ctrl, cap)
            self._send(self.ctrl, bytes(cap))
            ci = bytearray(il.CONNINFO_SIZE)
            struct.pack_into("<I", ci, 0, il.CONNINFO_SIZE)
            ci[0x40:0x40 + len(self.name)] = self.name.encode()
            if self.busy_by:
                struct.pack_into("<I", ci, 0x60, 1)
                ci[0x64:0x64 + len(self.busy_by)] = self.busy_by.encode()
            self._tracked(self.ctrl, ci)
            self._send(self.ctrl, bytes(ci))
        elif n == il.CONNINFO_SIZE and r[0x15] == 0x03:
            self.client_ports = struct.unpack_from(">II", r, 0x7c)
            st = self._inner_reply(il.STATUS_SIZE, r, 0x03)
            struct.pack_into(">H", st, 0x42, self.civ.getsockname()[1])
            struct.pack_into(">H", st, 0x46, self.aud.getsockname()[1])
            self._tracked(self.ctrl, st)
            self._send(self.ctrl, bytes(st))


def wait_for(cond, timeout=5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False
