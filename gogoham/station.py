"""Stationslog mit mehreren Plätzen im selben Netzwerk (ab 0.10) – ohne Qt.

Ein Rechner ist der **Hauptplatz** (er hat das Stationslog angelegt), die anderen sind
**Plätze**. Alle haben das komplette Log als eigene Datei; jede Änderung geht über den
Hauptplatz an alle. Bricht die Verbindung ab, wird weitergeloggt und danach abgeglichen.

- Finden: Der Hauptplatz ruft alle 2 s per UDP (Broadcast + Multicast) „hier läuft das
  Stationslog …“. Plätze hören zu (`Discovery`).
- Verbindung: TCP. Zuerst beweisen sich beide gegenseitig, dass sie das Stationskennwort
  kennen (HMAC-Herausforderung, das Kennwort selbst geht nie über die Leitung). Danach ist
  jede Nachricht verschlüsselt und gegen Verändern/Wiederholen geschützt (aus dem Kennwort
  und Zufallszahlen beider Seiten abgeleitete Schlüssel; SHAKE-256 als Schlüsselstrom,
  HMAC-SHA256 als Prüfsumme – nur Python-Bordmittel).
- Netz-Threads lesen und schreiben nur; alles, was das Log betrifft, landet in einer
  Warteschlange (`events`) und wird im Programm-Thread verarbeitet (`HostSync`/`PlaceSync`).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import queue
import socket
import struct
import threading
import time

UDP_PORT = 47374
TCP_PORT = 47375                    # Hauptplatz; ist er belegt, die nächsten bis +10
MCAST_GROUP = "239.255.47.74"
PROTO = 3                           # 2 = ab 0.10.2 (Schlüsselstrom), 3 = ab 0.10.3 (Nachrichten)
BEACON_EVERY = 2.0
PING_EVERY = 4.0
DEAD_AFTER = 15.0                   # so lange nichts gehört = Verbindung tot
MAX_FRAME = 8 * 1024 * 1024
KDF_ROUNDS = 200_000


# ================================================================ Schlüssel und Verschlüsselung
def password_key(password: str, log_id: str) -> bytes:
    """Schlüssel aus dem Stationskennwort (langsam gerechnet, damit Raten teuer ist)."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                               b"gogoham-station:" + log_id.encode(), KDF_ROUNDS)


def _mac(key: bytes, *parts: bytes) -> bytes:
    return hmac.new(key, b"|".join(parts), hashlib.sha256).digest()


def _keystream(key: bytes, ctr: int, n: int) -> bytes:
    """Schlüsselstrom für eine Nachricht: SHAKE-256 über (Schlüssel, Zähler) – ein Aufruf je
    Nachricht, beliebig lang (0.10.2; vorher HMAC je 32 Bytes, für große Logs zu langsam)."""
    return hashlib.shake_256(b"gogoham-ks|" + key + struct.pack(">Q", ctr)).digest(n)


def _xor(a: bytes, b: bytes) -> bytes:
    return (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).to_bytes(len(a), "big")


class Channel:
    """Eine Verbindung nach dem Anmelden: Nachrichten als JSON, verschlüsselt + geprüft."""

    def __init__(self, sock: socket.socket, session: bytes, is_host: bool):
        self.sock = sock
        tx, rx = (b"h2p", b"p2h") if is_host else (b"p2h", b"h2p")
        self.k_tx_enc, self.k_tx_mac = _mac(session, b"enc", tx), _mac(session, b"mac", tx)
        self.k_rx_enc, self.k_rx_mac = _mac(session, b"enc", rx), _mac(session, b"mac", rx)
        self.tx_ctr = 0
        self.rx_ctr = 0
        self.lock = threading.Lock()
        self.closed = False

    def send(self, msg: dict) -> bool:
        data = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode()
        with self.lock:
            if self.closed:
                return False
            self.tx_ctr += 1
            ctr = struct.pack(">Q", self.tx_ctr)
            ct = _xor(data, _keystream(self.k_tx_enc, self.tx_ctr, len(data)))
            tag = _mac(self.k_tx_mac, ctr, ct)
            frame = ctr + ct + tag
            try:
                self.sock.sendall(struct.pack(">I", len(frame)) + frame)
                return True
            except OSError:
                self.closed = True
                return False

    def recv(self) -> dict:
        frame = _recv_frame(self.sock)
        if len(frame) < 8 + 32:
            raise ConnectionError("frame too short")
        ctr_b, ct, tag = frame[:8], frame[8:-32], frame[-32:]
        if not hmac.compare_digest(tag, _mac(self.k_rx_mac, ctr_b, ct)):
            raise ConnectionError("bad tag")
        ctr = struct.unpack(">Q", ctr_b)[0]
        if ctr != self.rx_ctr + 1:                 # Wiederholung oder Lücke
            raise ConnectionError("bad counter")
        self.rx_ctr = ctr
        return json.loads(_xor(ct, _keystream(self.k_rx_enc, ctr, len(ct))))

    def close(self) -> None:
        with self.lock:
            self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return bytes(buf)


def _recv_frame(sock: socket.socket) -> bytes:
    n = struct.unpack(">I", _recv_exact(sock, 4))[0]
    if n > MAX_FRAME:
        raise ConnectionError("frame too large")
    return _recv_exact(sock, n)


def _send_plain(sock: socket.socket, msg: dict) -> None:
    data = json.dumps(msg).encode()
    sock.sendall(struct.pack(">I", len(data)) + data)


def _recv_plain(sock: socket.socket) -> dict:
    f = _recv_frame(sock)
    if len(f) > 4096:
        raise ConnectionError("hello too large")
    return json.loads(f)


class AuthError(Exception):
    """Kennwort falsch (oder die Gegenseite kennt es nicht)."""


def host_handshake(sock: socket.socket, key: bytes) -> Channel | dict:
    """Hauptplatz: Anmeldung eines Platzes. Ergebnis: Channel – oder ein dict, wenn nur
    nach den Stationsdaten gefragt wurde („info“, für die Eingabe einer Adresse)."""
    hello = _recv_plain(sock)
    if hello.get("t") == "info":
        return hello
    if hello.get("t") != "hello" or hello.get("v") != PROTO:
        raise ConnectionError("bad hello")
    nc = bytes.fromhex(hello["nonce"])
    ns = os.urandom(16)
    _send_plain(sock, {"t": "challenge", "nonce": ns.hex(),
                       "proof": _mac(key, b"host", nc, ns).hex()})
    auth = _recv_plain(sock)
    if auth.get("t") == "auth_fail":
        raise AuthError()
    if auth.get("t") != "auth" or not hmac.compare_digest(
            bytes.fromhex(auth.get("proof", "")), _mac(key, b"place", nc, ns)):
        try:
            _send_plain(sock, {"t": "denied"})
        except OSError:
            pass
        raise AuthError()
    _send_plain(sock, {"t": "ok"})
    return Channel(sock, _mac(key, b"session", nc, ns), is_host=True)


def place_handshake(sock: socket.socket, key: bytes) -> Channel:
    nc = os.urandom(16)
    _send_plain(sock, {"t": "hello", "v": PROTO, "nonce": nc.hex()})
    ch = _recv_plain(sock)
    if ch.get("t") != "challenge":
        raise ConnectionError("bad challenge")
    ns = bytes.fromhex(ch["nonce"])
    if not hmac.compare_digest(bytes.fromhex(ch.get("proof", "")), _mac(key, b"host", nc, ns)):
        try:                                     # Kennwort passt nicht zusammen
            _send_plain(sock, {"t": "auth_fail"})
        except OSError:
            pass
        raise AuthError()
    _send_plain(sock, {"t": "auth", "proof": _mac(key, b"place", nc, ns).hex()})
    res = _recv_plain(sock)
    if res.get("t") != "ok":
        raise AuthError()
    return Channel(sock, _mac(key, b"session", nc, ns), is_host=False)


# ================================================================ Finden im Netzwerk
# Zwei Wege, die sich ergänzen (ab 0.10.1):
# - IPv4: Broadcast + Multicast – das normale Netz mit Router (Adressen per DHCP).
# - IPv6-Link-Local: Multicast je Netzwerkanschluss. Diese Adressen hat jeder Rechner von
#   selbst, sobald ein Kabel steckt – so geht es auch über einen Switch oder ein Kabel
#   direkt von Rechner zu Rechner, ohne Router.
MCAST6_GROUP = "ff02::4747:4774"


def _udp_socket_for_sending() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    return s


def beacon_targets() -> list[str]:
    return ["255.255.255.255", MCAST_GROUP]


def interfaces() -> list[tuple[int, str]]:
    """Netzwerkanschlüsse (ohne „lo“) – (Nummer, Name)."""
    try:
        return [(i, n) for i, n in socket.if_nameindex() if n != "lo"]
    except OSError:
        return []


def ipv6_ok() -> bool:
    return socket.has_ipv6


def _scoped(host: str, scope: int) -> str:
    """Link-Local-Adresse mit Anschluss: „fe80::1%enp5s0“ (nötig zum Verbinden)."""
    if "%" in host or not host.lower().startswith("fe80") or not scope:
        return host
    try:
        return f"{host}%{socket.if_indextoname(scope)}"
    except OSError:
        return host


def plain_addr(addr: str) -> str:
    """Für die Anzeige: „::ffff:192.168.1.5“ -> „192.168.1.5“."""
    return addr[7:] if addr.startswith("::ffff:") else addr


class Beacon(threading.Thread):
    """Hauptplatz: ruft regelmäßig „hier läuft das Stationslog …“ ins Netzwerk."""

    def __init__(self, info: dict):
        super().__init__(daemon=True, name="gogoham-beacon")
        self.info = dict(info)
        self.stop_ev = threading.Event()
        self.errors = 0

    def _send6(self, s6, data: bytes) -> None:
        for idx, _name in interfaces():          # jedes Mal neu: Kabel kann später stecken
            try:
                s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, idx)
                s6.sendto(data, (MCAST6_GROUP, UDP_PORT, 0, idx))
            except OSError:
                pass

    def run(self) -> None:
        s = _udp_socket_for_sending()
        s6 = None
        if ipv6_ok():
            try:
                s6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
                s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 1)
                s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_LOOP, 1)
            except OSError:
                s6 = None
        try:
            while not self.stop_ev.is_set():
                data = json.dumps(dict(self.info, app="gogoham", t="beacon", v=PROTO)).encode()
                for target in beacon_targets():
                    try:
                        s.sendto(data, (target, UDP_PORT))
                    except OSError:
                        self.errors += 1
                if s6 is not None:
                    self._send6(s6, data)
                self.stop_ev.wait(BEACON_EVERY)
        finally:
            s.close()
            if s6 is not None:
                s6.close()

    def stop(self) -> None:
        self.stop_ev.set()


def _reuse(s: socket.socket) -> None:
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass


class Discovery(threading.Thread):
    """Hört auf die Rufe der Hauptplätze. `found()` = {log_id: Angaben + Adresse(n)}."""

    def __init__(self, keep: float = 8.0):
        super().__init__(daemon=True, name="gogoham-discovery")
        self.keep = keep
        self.stop_ev = threading.Event()
        self.lock = threading.Lock()
        self._found4: dict[str, dict] = {}
        self._found6: dict[str, dict] = {}
        self.ok = False                      # Port zum Zuhören bekommen?
        self._joined6: set[int] = set()

    def _open4(self) -> socket.socket | None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _reuse(s)
        try:
            s.bind(("", UDP_PORT))
        except OSError:
            s.close()
            return None
        try:
            mreq = struct.pack("4s4s", socket.inet_aton(MCAST_GROUP), socket.inet_aton("0.0.0.0"))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError:
            pass                              # dann eben nur Broadcast
        return s

    def _open6(self) -> socket.socket | None:
        if not ipv6_ok():
            return None
        try:
            s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        except OSError:
            return None
        _reuse(s)
        try:
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s.bind(("::", UDP_PORT))
        except OSError:
            s.close()
            return None
        self._join6(s)
        return s

    def _join6(self, s: socket.socket) -> None:
        group = socket.inet_pton(socket.AF_INET6, MCAST6_GROUP)
        for idx, _name in interfaces():
            if idx in self._joined6:
                continue
            try:
                s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP,
                             group + struct.pack("@I", idx))
                self._joined6.add(idx)
            except OSError:
                pass

    def run(self) -> None:
        import select
        s4, s6 = self._open4(), self._open6()
        socks = [x for x in (s4, s6) if x is not None]
        self.ok = bool(socks)
        if not socks:
            return
        last_join = time.monotonic()
        try:
            while not self.stop_ev.is_set():
                if s6 is not None and time.monotonic() - last_join > 5:
                    self._join6(s6)               # neu eingesteckte Kabel mitnehmen
                    last_join = time.monotonic()
                try:
                    ready, _w, _x = select.select(socks, [], [], 0.5)
                except (OSError, ValueError):
                    break
                for sock in ready:
                    try:
                        data, addr = sock.recvfrom(4096)
                    except OSError:
                        continue
                    self._on_beacon(data, addr, sock is s6)
        finally:
            for x in socks:
                x.close()

    # Name bewusst nicht „_handle“: das benutzt threading.Thread ab Python 3.13 selbst
    # (sonst fand die Suche unter 3.13 nie einen Hauptplatz – 0.10.3.2)
    def _on_beacon(self, data: bytes, addr, v6: bool) -> None:
        try:
            info = json.loads(data)
        except ValueError:
            return
        if info.get("app") != "gogoham" or info.get("t") != "beacon" \
                or not info.get("log_id") or info.get("v") != PROTO:
            return
        info["addr"] = _scoped(addr[0], addr[3]) if v6 else addr[0]
        info["seen"] = time.monotonic()
        with self.lock:
            (self._found6 if v6 else self._found4)[info["log_id"]] = info

    def found(self) -> dict[str, dict]:
        """Je Stationslog: Angaben mit „addr“ (bevorzugt IPv4) und „addrs“ (alle Wege)."""
        now = time.monotonic()
        out: dict[str, dict] = {}
        with self.lock:
            for table in (self._found4, self._found6):
                for k, v in table.items():
                    if now - v["seen"] >= self.keep:
                        continue
                    if k not in out:
                        out[k] = dict(v, addrs=[])
                    out[k]["addrs"].append((v["addr"], int(v.get("port", TCP_PORT))))
        return out

    def stop(self) -> None:
        self.stop_ev.set()


def ask_info(addr: str, port: int = TCP_PORT, timeout: float = 3.0) -> dict | None:
    """Notweg „Adresse eingeben“: Stationsdaten direkt beim Hauptplatz erfragen."""
    for p in range(port, port + 11) if port == TCP_PORT else (port,):
        try:
            with socket.create_connection((addr, p), timeout=timeout) as s:
                s.settimeout(timeout)
                _send_plain(s, {"t": "info"})
                info = _recv_plain(s)
                if info.get("app") == "gogoham" and info.get("log_id"):
                    info["addr"], info["port"] = addr, p
                    return info
        except (OSError, ValueError, ConnectionError):
            continue
    return None


# ================================================================ Hauptplatz
def _listen(port: int) -> socket.socket | None:
    """TCP-Anschluss für IPv4 und IPv6 zugleich (ohne IPv6: nur IPv4)."""
    if ipv6_ok():
        try:
            s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            s.bind(("::", port))
            s.listen(16)
            return s
        except OSError:
            try:
                s.close()
            except OSError:
                pass
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("", port))
        s.listen(16)
        return s
    except OSError:
        s.close()
        return None


class HostServer:
    """Nimmt Plätze an. Ereignisse in `events`: ("join", conn_id, msg), ("msg", conn_id, msg),
    ("gone", conn_id, None), ("denied", addr, None)."""

    def __init__(self, info: dict, key: bytes, port: int = TCP_PORT):
        self.key = key
        self.events: queue.Queue = queue.Queue()
        self.conns: dict[int, Channel] = {}
        self.lock = threading.Lock()
        self._next = 1
        self.stop_ev = threading.Event()
        self.sock = None
        for p in range(port, port + 11):
            s = _listen(p)
            if s is not None:
                self.sock, self.port = s, p
                break
        if self.sock is None:
            raise OSError("no free port")
        self.info = dict(info, port=self.port)
        self.beacon = Beacon(self.info)
        threading.Thread(target=self._accept, daemon=True, name="gogoham-host").start()
        threading.Thread(target=self._pinger, daemon=True, name="gogoham-host-ping").start()
        self.beacon.start()

    def _pinger(self) -> None:
        while not self.stop_ev.wait(PING_EVERY):
            self.ping_all()

    def _accept(self) -> None:
        self.sock.settimeout(0.5)
        while not self.stop_ev.is_set():
            try:
                s, addr = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve, args=(s, addr), daemon=True).start()

    def _serve(self, s: socket.socket, addr) -> None:
        s.settimeout(10)
        try:
            res = host_handshake(s, self.key)
        except AuthError:
            self.events.put(("denied", plain_addr(addr[0]), None))
            s.close()
            return
        except (OSError, ValueError, ConnectionError, KeyError):
            s.close()
            return
        if isinstance(res, dict):                  # nur Stationsdaten gefragt
            try:
                _send_plain(s, dict(self.info, app="gogoham"))
            except OSError:
                pass
            s.close()
            return
        ch = res
        s.settimeout(None)
        with self.lock:
            cid = self._next
            self._next += 1
            self.conns[cid] = ch
        s.settimeout(DEAD_AFTER)
        first = True
        try:
            while not self.stop_ev.is_set():
                msg = ch.recv()
                if msg.get("t") == "ping":
                    continue
                if msg.get("t") == "time?":          # Uhrzeit-Abgleich: sofort antworten
                    ch.send({"t": "time", "t0": msg.get("t0"), "th": time.time()})
                    continue
                self.events.put(("join" if first else "msg", cid, msg))
                first = False
        except (OSError, ValueError, ConnectionError):
            pass
        finally:
            ch.close()
            with self.lock:
                self.conns.pop(cid, None)
            self.events.put(("gone", cid, None))

    def send(self, cid: int, msg: dict) -> None:
        with self.lock:
            ch = self.conns.get(cid)
        if ch:
            ch.send(msg)

    def broadcast(self, msg: dict, skip: int | None = None) -> None:
        with self.lock:
            chans = [(c, ch) for c, ch in self.conns.items() if c != skip]
        for _c, ch in chans:
            ch.send(msg)

    def ping_all(self) -> None:
        self.broadcast({"t": "ping"})

    def update_info(self, **kw) -> None:
        self.info.update(kw)
        self.beacon.info.update(kw)

    def stop(self) -> None:
        self.stop_ev.set()
        self.beacon.stop()
        try:
            self.sock.close()
        except OSError:
            pass
        with self.lock:
            chans = list(self.conns.values())
        for ch in chans:
            ch.close()


# ================================================================ Platz
class PlaceClient(threading.Thread):
    """Verbindet sich mit dem Hauptplatz und bleibt verbunden (wiederverbinden von selbst).

    Ereignisse in `events`: ("connected", None), ("msg", msg), ("lost", None),
    ("denied", None). `hello()` liefert die erste Nachricht nach dem Anmelden („join“)."""

    def __init__(self, key: bytes, where, hello):
        super().__init__(daemon=True, name="gogoham-place")
        self.key = key
        self.where = where                 # Funktion -> (addr, port) oder None
        self.hello = hello
        self.events: queue.Queue = queue.Queue()
        self.ch: Channel | None = None
        self.stop_ev = threading.Event()
        self.connected = False
        self.clock_offset: float | None = None   # Uhr des Hauptplatzes minus eigene Uhr (s)
        self.clock_rtt: float | None = None
        self.via = ""                             # Adresse, über die verbunden ist

    def _connect(self, targets):
        """Alle bekannten Wege der Reihe nach versuchen (IPv4 zuerst, dann IPv6)."""
        last = None
        for t in targets:
            try:
                s = socket.create_connection(t, timeout=3)
            except OSError as e:
                last = e
                continue
            self.via = t[0]
            return s
        raise last or OSError("unreachable")

    def run(self) -> None:
        while not self.stop_ev.is_set():
            targets = self.where()
            if isinstance(targets, tuple):
                targets = [targets]
            if not targets:
                self.stop_ev.wait(1.0)
                continue
            try:
                s = self._connect(targets)
                s.settimeout(10)
                ch = place_handshake(s, self.key)
            except AuthError:
                self.events.put(("denied", None))
                self.stop_ev.wait(5.0)
                continue
            except (OSError, ValueError, ConnectionError, KeyError):
                self.stop_ev.wait(1.5)
                continue
            s.settimeout(DEAD_AFTER)
            self.ch = ch
            ch.send(self.hello())
            self.connected = True
            self.events.put(("connected", None))
            pinger = threading.Thread(target=self._ping, args=(ch,), daemon=True)
            pinger.start()
            try:
                while not self.stop_ev.is_set():
                    msg = ch.recv()
                    if msg.get("t") == "time":
                        self._clock(msg)
                    elif msg.get("t") != "ping":
                        self.events.put(("msg", msg))
            except (OSError, ValueError, ConnectionError):
                pass
            ch.close()
            self.connected = False
            self.ch = None
            self.clock_offset = self.clock_rtt = None
            self.events.put(("lost", None))
            self.stop_ev.wait(1.0)

    def _clock(self, msg: dict) -> None:
        t1 = time.time()
        try:
            t0, th = float(msg["t0"]), float(msg["th"])
        except (KeyError, TypeError, ValueError):
            return
        rtt = t1 - t0
        if rtt < 0 or rtt > 2:                    # zu langsam für eine brauchbare Messung
            return
        if self.clock_rtt is None or rtt <= self.clock_rtt * 2 or rtt < 0.05:
            self.clock_offset, self.clock_rtt = th - (t0 + t1) / 2, rtt

    def _ping(self, ch: Channel) -> None:
        n = 0
        while not ch.closed and not self.stop_ev.is_set():
            ch.send({"t": "ping"})
            if n % 8 == 0:                        # etwa alle 30 s die Uhr vergleichen
                ch.send({"t": "time?", "t0": time.time()})
            n += 1
            self.stop_ev.wait(PING_EVERY)

    def send(self, msg: dict) -> bool:
        ch = self.ch
        return bool(ch and ch.send(msg))

    def stop(self) -> None:
        self.stop_ev.set()
        ch = self.ch
        if ch:
            ch.close()


# ================================================================ Log-Abgleich (Programm-Thread)
STATION_META_PREFIX = "station_"        # nur für diesen Rechner, wird nicht abgeglichen


STATUS_KEYS = ("op", "band", "freq", "mode", "tx")
CHAT_MAX = 500                      # Zeichen je Nachricht


def utc_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def make_chat(sender: str, to: str, text: str, mid: str = "", when: str = "") -> dict:
    """Eine Nachricht zwischen den Plätzen (0.10.3). to = Platzname, leer = an alle."""
    import uuid
    return {"t": "chat", "mid": mid or uuid.uuid4().hex, "from": sender, "to": to,
            "text": " ".join(str(text).split())[:CHAT_MAX], "time": when or utc_now()}


def _parse_utc(t: str) -> float | None:
    import calendar
    try:
        return calendar.timegm(time.strptime(t[:19], "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError):
        return None


def place_stats(qsos, now: float | None = None) -> dict[str, dict]:
    """QSOs je Platz aus dem gemeinsamen Log (0.10.3): Anzahl und Rate (QSOs pro Stunde)
    über die letzten 10 und 60 Minuten. Jeder Platz rechnet das selbst – das Log hat ja jeder."""
    now = time.time() if now is None else now
    out: dict[str, dict] = {}
    for q in qsos:
        name = getattr(q, "place", "") or ""
        d = out.setdefault(name, {"qsos": 0, "r10": 0, "r60": 0})
        d["qsos"] += 1
        t = _parse_utc(getattr(q, "time", ""))
        if t is None or t > now + 60:
            continue
        age = now - t
        if age <= 600:
            d["r10"] += 6
        if age <= 3600:
            d["r60"] += 1
    return out


def band_conflicts(rows: list[dict]) -> dict[str, set[str]]:
    """Welche verbundenen Plätze sind auf demselben Band? Ergebnis: Band -> Platznamen
    (nur Bänder mit mindestens zwei Plätzen)."""
    by_band: dict[str, set[str]] = {}
    for r in rows:
        if r.get("band") and not r.get("gone"):
            by_band.setdefault(r["band"], set()).add(r.get("place", "?"))
    return {b: names for b, names in by_band.items() if len(names) > 1}


def shared_meta(meta: dict) -> dict:
    return {k: v for k, v in meta.items() if not k.startswith(STATION_META_PREFIX)}


def _serial_of(exch_s: str) -> int:
    first = str(exch_s or "").split()
    return int(first[0]) if first and first[0].isdigit() else 0


class SerialBook:
    """Laufende Nummern der ganzen Station: Jeder Platz bekommt beim Hauptplatz eine Nummer
    reserviert; fragt er wieder, ohne sie benutzt zu haben, bekommt er dieselbe."""

    def __init__(self):
        self.reserved: dict[tuple[str, str], int] = {}     # (Platz, Band oder "") -> Nummer

    def next_for(self, place: str, band_key: str, used: set[int]) -> int:
        n = self.reserved.get((place, band_key))
        if n and n not in used:
            return n
        others = [v for (p, b), v in self.reserved.items() if b == band_key and p != place
                  and v not in used]
        n = max([max(used, default=0)] + others) + 1
        self.reserved[(place, band_key)] = n
        return n


class HostSync:
    """Hauptplatz: wendet Änderungen auf das Log an, führt das Änderungsbuch, verteilt."""

    def __init__(self, db, server: HostServer, place: str, op: str = "",
                 serial_per_band=False):
        self.db = db
        self.server = server
        self.place = place
        self.op = op
        self.places: dict[int, dict] = {}        # conn_id -> {"place", "op", …}
        self.own: dict = {}                      # eigener Stand: band, freq, mode, tx (0.10.3)
        self.serials = SerialBook()
        self.serial_per_band = serial_per_band
        self.denied: list[str] = []
        db.ensure_uids()
        if db.journal_empty():                   # erstes Mal: alles ins Änderungsbuch
            for kind, data in db.all_records():
                db.journal_add(kind, data["uid"], False, data)

    # --- eigene Änderungen (vom Hauptplatz selbst)
    def put(self, kind: str, data: dict) -> None:
        seq = self.db.journal_add(kind, data["uid"], False, data)
        self.server.broadcast({"t": "rec", "seq": seq, "kind": kind, "uid": data["uid"],
                               "del": False, "data": data})

    def delete(self, kind: str, uid: str) -> None:
        seq = self.db.journal_add(kind, uid, True, None)
        self.server.broadcast({"t": "rec", "seq": seq, "kind": kind, "uid": uid, "del": True,
                               "data": {}})

    def meta_changed(self, meta: dict) -> None:
        self.server.broadcast({"t": "meta", "data": shared_meta(meta)})

    def _used(self, band_key: str) -> set[int]:
        sql = "SELECT exch_s FROM qso" + (" WHERE band=?" if band_key else "")
        rows = self.db.conn.execute(sql, (band_key,) if band_key else ())
        return {n for (v,) in rows if (n := _serial_of(v))}

    def serial(self, band: str = "") -> int:
        key = band if self.serial_per_band else ""
        return self.serials.next_for("host", key, self._used(key))

    def place_list(self) -> list[dict]:
        return [dict(self.own, place=self.place, op=self.op, host=True)] + \
            [dict(p) for p in self.places.values()]

    def set_own(self, **kw) -> bool:
        """Eigenen Stand übernehmen (0.10.3). True = alle Plätze sollten es gleich erfahren
        (Band, Betriebsart, Operator oder Sender gewechselt); die Frequenz allein nicht."""
        new = {k: kw.get(k, "") for k in STATUS_KEYS if k != "op"}
        op = kw.get("op", self.op)
        big = op != self.op or any(new.get(k) != self.own.get(k) for k in ("band", "mode", "tx"))
        self.own, self.op = new, op
        return big

    def broadcast_places(self) -> None:
        self.server.broadcast({"t": "places", "list": self.place_list()})

    # --- Nachrichten zwischen den Plätzen (0.10.3)
    def _route(self, m: dict, skip: int | None = None) -> bool:
        """Nachricht an die Plätze weiterreichen. True = mindestens ein Empfänger erreicht."""
        to = m.get("to", "")
        if not to:
            self.server.broadcast(m, skip=skip)
            return any(c != skip for c in self.places)
        hit = False
        for cid, p in list(self.places.items()):
            if p.get("place") == to and cid != skip:
                self.server.send(cid, m)
                hit = True
        return hit

    def send_chat(self, to: str, text: str) -> tuple[dict, bool]:
        """Vom Hauptplatz aus schreiben. Ergebnis: (Nachricht, zugestellt?)."""
        m = make_chat(self.place, to, text)
        return m, self._route(m)

    def _catch_up(self, cid: int, meta: dict, seq: int, recs: list[dict]) -> None:
        """(Hintergrund) Stand des Logs an einen Platz, der sich gerade angemeldet hat."""
        self.server.send(cid, {"t": "welcome", "meta": meta, "seq": seq})
        for r in recs:
            self.server.send(cid, dict(r, t="rec"))
        self.server.send(cid, {"t": "synced", "seq": seq})

    # --- Nachrichten der Plätze
    def process(self) -> dict:
        """Warteschlange abarbeiten. Ergebnis: {"changed": bool, "meta": dict|None,
        "places": bool, "denied": [Adressen]}."""
        res = {"changed": False, "meta": None, "places": False, "denied": [], "recs": [],
               "chats": []}
        journal: dict[int, list] = {}            # mehrere Anmeldungen zugleich: einmal lesen
        while True:
            try:
                ev, cid, msg = self.server.events.get_nowait()
            except queue.Empty:
                break
            if ev == "denied":
                res["denied"].append(cid)
                continue
            if ev == "gone":
                if self.places.pop(cid, None) is not None:
                    res["places"] = True
                for k in [k for k in self.serials.reserved if k[0] == f"#{cid}"]:
                    del self.serials.reserved[k]          # Nummer wird wieder frei
                continue
            t = msg.get("t")
            if ev == "join" and msg.get("probe"):       # nur Kennwort prüfen (Beitreten)
                self.server.send(cid, {"t": "welcome", "meta": shared_meta(self.db.get_meta()),
                                       "seq": self.db.journal_seq()})
                continue
            if ev == "join":
                self.places[cid] = {"place": msg.get("place", "?"), "op": msg.get("op", "")}
                res["places"] = True
                meta = shared_meta(self.db.get_meta())
                seq = self.db.journal_seq()
                last = int(msg.get("last_seq", 0))
                if last not in journal:
                    journal[last] = self.db.journal_since(last)
                recs = journal[last]
                # Nachschicken im Hintergrund: ein großes Log (tausende QSOs) an mehrere
                # Plätze würde sonst das Fenster des Hauptplatzes sekundenlang anhalten (0.10.2)
                threading.Thread(target=self._catch_up, args=(cid, meta, seq, recs),
                                 daemon=True).start()
                continue
            if t in ("put", "del"):
                kind, uid = msg.get("kind"), msg.get("uid")
                if kind not in ("qso", "qtc") or not uid:
                    continue
                existed = self.db.record(kind, uid) is not None
                if t == "put":
                    data = dict(msg.get("data") or {}, uid=uid)
                    self.db.put_record(kind, data)
                    self.put(kind, data)
                    res["recs"].append((kind, uid, False) if not existed else (kind, uid, True))
                else:
                    self.db.delete_record(kind, uid)
                    self.delete(kind, uid)
                    res["recs"].append((kind, uid, True))
                if msg.get("oid"):
                    self.server.send(cid, {"t": "ack", "oid": msg["oid"]})
                res["changed"] = True
            elif t == "meta":
                data = shared_meta(msg.get("data") or {})
                self.db.set_meta(data)
                self.meta_changed(dict(self.db.get_meta()))
                res["meta"] = data
            elif t == "serial?":
                band = msg.get("band", "")
                key = band if self.serial_per_band else ""
                n = self.serials.next_for(f"#{cid}", key, self._used(key))
                self.server.send(cid, {"t": "serial", "band": band, "n": n})
            elif t == "status":
                p = self.places.get(cid)
                if p is not None:
                    p.update({k: msg.get(k, "") for k in STATUS_KEYS})
                    res["places"] = True
            elif t == "chat":
                p = self.places.get(cid)
                if p is None or not str(msg.get("text", "")).strip():
                    continue
                m = make_chat(p.get("place", "?"), str(msg.get("to", "")), str(msg["text"]),
                              mid=str(msg.get("mid", "")), when=str(msg.get("time", "")))
                ok = self._route(m, skip=cid)
                if m["to"] in ("", self.place):
                    res["chats"].append(m)
                    ok = True
                self.server.send(cid, {"t": "chat_state", "mid": m["mid"], "ok": ok})
        if res["places"]:
            self.broadcast_places()
        return res


class PlaceSync:
    """Platz: eigene Änderungen an den Hauptplatz (oder in die Warteschlange, solange keine
    Verbindung besteht), fremde Änderungen ins eigene Log."""

    def __init__(self, db, client: PlaceClient):
        self.db = db
        self.client = client
        self.synced = False
        self.places: list[dict] = []
        self.serial_cache: dict[str, int] = {}
        self.denied = False
        try:                                   # Stand des Abgleichs (auch für den Netz-Thread)
            self.seq = int(db.get_meta().get("station_seq", "0") or 0)
        except ValueError:
            self.seq = 0

    @property
    def connected(self) -> bool:
        return self.client.connected and self.synced

    def last_seq(self) -> int:
        """Darf aus dem Netz-Thread gerufen werden (liest nicht aus der Log-Datei)."""
        return self.seq

    def _set_seq(self, seq) -> None:
        self.seq = int(seq or 0)
        self.db.set_meta({"station_seq": str(self.seq)})

    def _send_or_queue(self, msg: dict) -> None:
        oid = self.db.outbox_add(msg)
        if self.client.connected:
            self.client.send(dict(msg, oid=oid))

    def put(self, kind: str, data: dict) -> None:
        self._send_or_queue({"t": "put", "kind": kind, "uid": data["uid"], "data": data})

    def delete(self, kind: str, uid: str) -> None:
        self._send_or_queue({"t": "del", "kind": kind, "uid": uid})

    def meta_changed(self, meta: dict) -> None:
        if self.client.connected:
            self.client.send({"t": "meta", "data": shared_meta(meta)})

    def ask_serial(self, band: str = "") -> None:
        if self.client.connected:
            self.client.send({"t": "serial?", "band": band})

    def status(self, **kw) -> None:
        if self.client.connected:
            self.client.send(dict(kw, t="status"))

    def send_chat(self, sender: str, to: str, text: str) -> tuple[dict, bool | None]:
        """Nachricht schreiben (0.10.3). Ergebnis: (Nachricht, False = keine Verbindung,
        None = unterwegs – die Antwort des Hauptplatzes kommt mit process())."""
        m = make_chat(sender, to, text)
        if not self.client.connected:
            return m, False
        return m, (None if self.client.send(m) else False)

    def process(self) -> dict:
        res = {"changed": False, "meta": None, "places": False, "connected": None,
               "denied": False, "serial": None, "recs": [], "chats": [], "chat_states": []}
        mine = None                                   # Kennungen, die noch unterwegs sind
        new_seq = None
        done = 0
        with self.db.batch():                         # eine Speicherung je Portion statt je QSO
            res = self._process(res, mine, new_seq, done)
        if res.pop("_seq", None) is not None:
            self._set_seq(res.pop("_seq_val"))
        return res

    MAX_PER_TICK = 200                    # große Nachlieferung in Portionen – Fenster bleibt flüssig

    def _process(self, res, mine, new_seq, done) -> dict:
        while done < self.MAX_PER_TICK:
            done += 1
            try:
                ev, msg = self.client.events.get_nowait()
            except queue.Empty:
                break
            if ev == "connected":
                self.synced = False
                self.denied = False
                for oid, m in self.db.outbox():           # Unversandtes nachschicken
                    self.client.send(dict(m, oid=oid))
                continue
            if ev == "lost":
                self.synced = False
                res["connected"] = False
                continue
            if ev == "denied":
                self.denied = True
                res["denied"] = True
                continue
            t = msg.get("t")
            if t == "welcome":
                meta = msg.get("meta") or {}
                self.db.set_meta(shared_meta(meta))
                res["meta"] = meta
            elif t == "rec":
                kind, uid = msg.get("kind"), msg.get("uid")
                if kind in ("qso", "qtc") and uid:
                    if mine is None:
                        mine = {m.get("uid") for _o, m in self.db.outbox()}
                    if uid not in mine:                   # eigener Stand ist noch unterwegs
                        existed = self.db.record(kind, uid) is not None
                        if msg.get("del"):
                            self.db.delete_record(kind, uid)
                        else:
                            self.db.put_record(kind, dict(msg.get("data") or {}, uid=uid))
                        res["changed"] = True
                        # (Art, Kennung, „kein reines Anhängen“): Ändern/Löschen = neu laden
                        res["recs"].append((kind, uid, bool(msg.get("del")) or existed))
                new_seq = msg.get("seq", 0)
            elif t == "ack":
                self.db.outbox_done(int(msg.get("oid", 0)))
                mine = None
            elif t == "synced":
                self.synced = True
                self._set_seq(msg.get("seq", 0))
                res["connected"] = True
            elif t == "meta":
                self.db.set_meta(shared_meta(msg.get("data") or {}))
                res["meta"] = msg.get("data")
            elif t == "places":
                self.places = msg.get("list") or []
                res["places"] = True
            elif t == "chat":
                res["chats"].append(make_chat(str(msg.get("from", "?")), str(msg.get("to", "")),
                                              str(msg.get("text", "")), mid=str(msg.get("mid", "")),
                                              when=str(msg.get("time", ""))))
            elif t == "chat_state":
                res["chat_states"].append((str(msg.get("mid", "")), bool(msg.get("ok"))))
            elif t == "serial":
                self.serial_cache[msg.get("band", "")] = int(msg.get("n", 0))
                res["serial"] = msg.get("band", "")
        if new_seq is not None and int(new_seq or 0) > self.seq:
            res["_seq"], res["_seq_val"] = True, new_seq
        return res


def probe(addr: str, port: int, key: bytes, hello: dict, timeout: float = 5.0) -> dict:
    """Beitreten prüfen: anmelden, „welcome“ abwarten, wieder trennen. Ergebnis: die
    Log-Angaben des Hauptplatzes. AuthError = Kennwort falsch, OSError = nicht erreichbar."""
    with socket.create_connection((addr, port), timeout=timeout) as s:
        s.settimeout(timeout)
        try:
            ch = place_handshake(s, key)
        except (ValueError, KeyError) as e:
            raise ConnectionError(str(e)) from e
        ch.send(hello)
        while True:
            msg = ch.recv()
            if msg.get("t") == "welcome":
                ch.close()
                return msg.get("meta") or {}


def firewall() -> str | None:
    """Welche Firewall läuft? „firewalld“, „ufw“ oder None."""
    import shutil
    import subprocess
    for name in ("firewalld", "ufw"):
        if not shutil.which("systemctl"):
            return None
        try:
            r = subprocess.run(["systemctl", "is-active", "--quiet", name], timeout=3)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0:
            return name
    return None


def firewall_command(kind: str) -> list[str] | None:
    """Befehl, der die Ports für das Stationslog freigibt (mit pkexec: Systempasswort)."""
    tcp = f"{TCP_PORT}-{TCP_PORT + 10}"
    if kind == "firewalld":
        script = (f"firewall-cmd --permanent --add-port={UDP_PORT}/udp "
                  f"--add-port={tcp}/tcp && firewall-cmd --reload")
    elif kind == "ufw":
        script = f"ufw allow {UDP_PORT}/udp && ufw allow {tcp.replace('-', ':')}/tcp"
    else:
        return None
    return ["pkexec", "sh", "-c", script]


# ================================================================ Netzwerk-Check (ab 0.10.1)
_VIRTUAL = ("docker", "virbr", "veth", "br-", "vnet", "lxc", "tap")
_VPN = ("tun", "wg", "tailscale", "zt", "ppp", "nordlynx", "proton")


def network_state(run=None) -> list[dict]:
    """Netzwerkanschlüsse in einfachen Worten: je Anschluss {name, kind ("cable"/"wifi"/"vpn"),
    up, v4 (Adressen mit Router), ll4, ll6 (Link-Local)}. Virtuelle Anschlüsse fehlen."""
    import subprocess
    run = run or (lambda: subprocess.run(["ip", "-j", "addr"], capture_output=True, text=True,
                                         timeout=3).stdout)
    try:
        data = json.loads(run() or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    out = []
    for d in data:
        name = d.get("ifname", "")
        if not name or name == "lo" or name.startswith(_VIRTUAL):
            continue
        if name.startswith(_VPN):
            kind = "vpn"
        elif os.path.isdir(f"/sys/class/net/{name}/wireless") or name.startswith("wl"):
            kind = "wifi"
        else:
            kind = "cable"
        v4, ll4, ll6 = [], [], []
        for a in d.get("addr_info", []):
            ip = a.get("local", "")
            if a.get("family") == "inet":
                (ll4 if ip.startswith("169.254.") else v4).append(ip)
            elif a.get("family") == "inet6" and a.get("scope") == "link":
                ll6.append(ip)
        flags = d.get("flags", [])
        up = "LOWER_UP" in flags or d.get("operstate") == "UP"
        out.append({"name": name, "kind": kind, "up": up, "v4": v4, "ll4": ll4, "ll6": ll6})
    return out


def network_summary(state: list[dict]) -> tuple[list[str], dict | None]:
    """Klartext-Zeilen zum Netzwerk und – falls ein Kabel steckt, der Rechner dort aber gar
    keine Adresse hat – dieser Anschluss (dann hilft „Kabelverbindung ohne Router“)."""
    from .i18n import tr
    lines, broken = [], None
    phys = [s for s in state if s["kind"] in ("cable", "wifi") and s["up"]]
    if not phys:
        lines.append(tr("✘ Keine Netzwerkverbindung: kein Kabel eingesteckt und kein WLAN "
                        "verbunden."))
    for s in phys:
        what = tr("Kabel") if s["kind"] == "cable" else tr("WLAN")
        if s["v4"]:
            lines.append(tr("✔ {what} ({name}): im Netz mit Router – {ip}", what=what,
                            name=s["name"], ip=", ".join(s["v4"])))
        elif s["ll6"] or s["ll4"]:
            lines.append(tr("✔ {what} ({name}): ohne Router – Direktverbindung (Switch oder "
                            "Kabel) geht trotzdem", what=what, name=s["name"]))
        else:
            lines.append(tr("✘ {what} ({name}): verbunden, aber der Rechner hat dort keine "
                            "Adresse", what=what, name=s["name"]))
            if s["kind"] == "cable" and broken is None:
                broken = s
    for s in state:
        if s["kind"] == "vpn" and s["up"]:
            lines.append(tr("⚠ VPN eingeschaltet ({name}) – das kann die Verbindung zu den anderen "
                            "Plätzen stören. Im Zweifel für den Contest ausschalten.",
                            name=s["name"]))
    return lines, broken


# --- Kabel ohne Router vorbereiten (NetworkManager, ab 0.10.1) --------------------------
# Ohne Router wartet NetworkManager am Kabel vergeblich auf eine Adresse, erklärt die Verbindung
# nach 45 s für gescheitert und schaltet den Anschluss ab – mitsamt der Link-Local-Adresse (im
# Test 2026-11-08 gesehen, auch mit „ipv4.link-local fallback“ allein). Deshalb beides:
# „ipv4.link-local fallback“ (eigene Adresse 169.254.x.x, wenn kein Router antwortet) und
# „ipv4.dhcp-timeout“ ohne Grenze (nie aufgeben, Anschluss bleibt an). Mit Router ändert sich
# nichts. Das wird einmal je Kabelverbindung eingestellt.
CABLE_SETTINGS = ["ipv4.link-local", "fallback", "ipv4.dhcp-timeout", "2147483647"]
CABLE_PREPARE_VERSION = 2          # 1 = nur link-local (reichte nicht), 2 = mit dhcp-timeout
def _nmcli(args, run=None):
    import subprocess
    run = run or (lambda a: subprocess.run(a, capture_output=True, text=True, timeout=15))
    try:
        return run(["nmcli"] + args)
    except (OSError, subprocess.SubprocessError):
        return None


def cable_profiles(run=None) -> list[tuple[str, bool]]:
    """Kabelverbindungen von NetworkManager, die per Router (DHCP) arbeiten:
    [(Name, schon vorbereitet?)]. Leer, wenn es NetworkManager nicht gibt."""
    r = _nmcli(["-t", "-f", "NAME,TYPE", "connection", "show"], run)
    if r is None or r.returncode != 0:
        return []
    out = []
    for line in r.stdout.splitlines():
        name, _, typ = line.rpartition(":")
        if typ != "802-3-ethernet" or not name:
            continue
        name = name.replace("\\:", ":")
        g = _nmcli(["-g", "ipv4.method,ipv4.link-local,ipv4.dhcp-timeout", "connection", "show",
                    name], run)
        if g is None or g.returncode != 0:
            continue
        vals = [v.strip() for v in g.stdout.split("\n")] + ["", "", ""]
        method, ll, timeout = vals[0], vals[1], vals[2]
        if method == "auto":
            out.append((name, ll in ("4", "fallback") and
                        timeout in ("2147483647", "infinity")))
    return out


def cable_prepared(run=None) -> bool | None:
    """True = alle Kabelverbindungen vorbereitet, False = mindestens eine nicht,
    None = kein NetworkManager / keine Kabelverbindung (dann gibt es nichts zu tun)."""
    prof = cable_profiles(run)
    if not prof:
        return None
    return all(ok for _n, ok in prof)


def prepare_cable(device: str | None = None, run=None, pkexec_run=None) -> bool:
    """Alle Kabelverbindungen vorbereiten; hängt ``device`` gerade ohne Adresse am Kabel,
    gleich neu verbinden. Ohne Berechtigung: mit pkexec (Systempasswort)."""
    import subprocess
    ok = True
    for name, done in cable_profiles(run):
        if done:
            continue
        args = ["connection", "modify", name] + CABLE_SETTINGS
        r = _nmcli(args, run)
        if r is None or r.returncode != 0:
            pr = pkexec_run or (lambda a: subprocess.run(a, capture_output=True, text=True,
                                                         timeout=180))
            try:
                r = pr(["pkexec", "nmcli"] + args)
            except (OSError, subprocess.SubprocessError):
                r = None
        ok = ok and r is not None and r.returncode == 0
    # Rest aus einer Vorabversion von 0.10.1 (eigene Verbindung „GoGoHam direkt“) wegräumen
    r = _nmcli(["-t", "-f", "NAME", "connection", "show"], run)
    if r is not None and r.returncode == 0 and "GoGoHam direkt" in r.stdout.splitlines():
        _nmcli(["connection", "delete", "GoGoHam direkt"], run)
    if ok and device:
        _nmcli(["device", "connect", device], run)
    return ok


def clock_command(offset: float) -> list[str]:
    """Uhr um ``offset`` Sekunden verstellen (pkexec: Systempasswort). Gerechnet wird erst,
    wenn das Passwort eingegeben ist – die Wartezeit verfälscht nichts."""
    script = ('t=$(date +%s.%N); n=$(awk -v t="$t" -v o="$1" \'BEGIN{printf "%.3f", t+o}\'); '
              'date -s "@$n" >/dev/null')
    return ["pkexec", "sh", "-c", script, "sh", f"{offset:.3f}"]
