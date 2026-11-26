"""GPS-Empfänger (ab 0.10.25): Standort, Locator und Uhrzeit – am PC und auf dem Live-Stick.

Kleine USB-GPS-Empfänger melden sich als /dev/ttyACM* oder /dev/ttyUSB* und schicken Text im
NMEA-Format ($GPRMC, $GNGGA …). GoGoHam liest das selbst – ohne Zusatzprogramm. Läuft auf dem
Rechner schon ``gpsd``, kommen die Daten von dort (sonst streiten sich zwei Programme um den
Anschluss).

Sicherheit (Regel „nie senden“): An viele USB-Seriell-Adapter hängt man auch Funkgeräte und
Interfaces, die über die Steuerleitungen DTR/RTS **tasten** (PTT/CW). Deshalb
* öffnet GoGoHam von selbst nur Geräte, die eindeutig GPS-Empfänger sind (bekannter Hersteller
  oder „GPS/GNSS“ im Namen) – allgemeine Adapter-Chips nur, wenn der Nutzer das ausdrücklich will,
* nie einen Anschluss, der in einem Funkgeräte- oder Rotor-Profil steht,
* nur zum **Lesen**, Steuerleitungen gleich aus, und es wird **nie** etwas an das Gerät geschickt.

Uhrzeit: Ein NMEA-Satz kommt immer etwas *nach* der Sekunde an, die er meldet. Der beste Wert
ist darum der mit der kleinsten Verspätung (größter Wert von GPS-Zeit − PC-Zeit). Gleich nach
dem Einschalten kennen manche Empfänger die Schaltsekunden noch nicht (bis zu ~13 Minuten) –
kleine Abweichungen (unter 30 s) gelten deshalb erst danach als sicher.
"""

from __future__ import annotations

import errno
import glob
import os
import re
import socket
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from .i18n import tr
from .locator import from_latlon

# --- Geräte ---------------------------------------------------------------------------------
# Hersteller, die nur GPS bauen (USB-Kennung) – diese prüft GoGoHam von selbst
GPS_VENDORS = {"1546": "u-blox"}
GPS_DEVICES = {("0e8d", "3329"): "MediaTek GPS", ("1546", "01a7"): "u-blox 7",
               ("1546", "01a8"): "u-blox 8", ("1546", "01a9"): "u-blox 9",
               ("1546", "01a6"): "u-blox 6", ("1546", "01a5"): "u-blox 5"}
GPS_WORDS = re.compile(r"gps|gnss|glonass|galileo|beidou|u-?blox|sirf|navilock|globalsat|"
                       r"nmea|navigation", re.I)
# Allgemeine Adapter-Chips (stecken auch in Funkgeräten/Interfaces): nie von selbst öffnen
ADAPTER_VENDORS = {"10c4": "Silicon Labs CP210x", "0403": "FTDI", "1a86": "CH340",
                   "067b": "Prolific", "04d8": "Microchip", "2341": "Arduino"}

BAUDS = [9600, 4800, 38400, 115200, 19200, 57600]
LISTEN_S = 2.5            # so lange je Geschwindigkeit auf einen gültigen Satz warten
STALE_S = 5.0             # so lange ohne Daten = Empfänger antwortet nicht mehr
GPSD = ("127.0.0.1", 2947)
LEAP_SAFE_S = 13 * 60     # ab hier sind auch kleine Zeit-Abweichungen sicher (Schaltsekunden)
BIG_OFFSET_S = 30.0       # so große Abweichungen erklären Schaltsekunden nie


@dataclass
class Port:
    path: str                 # /dev/ttyACM0
    key: str                  # feste Kennung (bleibt beim Umstecken gleich)
    vid: str = ""
    pid: str = ""
    manufacturer: str = ""
    product: str = ""
    serial: str = ""
    kind: str = "other"       # gps = sicher GPS · adapter = allgemeiner Chip · other

    @property
    def label(self) -> str:
        name = " ".join(x for x in (self.manufacturer, self.product) if x).strip()
        name = name or GPS_DEVICES.get((self.vid, self.pid)) or \
            GPS_VENDORS.get(self.vid) or ADAPTER_VENDORS.get(self.vid) or tr("USB-Gerät")
        return f"{name} ({os.path.basename(self.path)})"


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def _usb_info(tty: str, sysroot: str = "/sys") -> dict:
    """Hersteller/Modell aus /sys – vom tty nach oben bis zum USB-Gerät."""
    d = os.path.realpath(os.path.join(sysroot, "class", "tty", tty, "device"))
    for _ in range(5):
        if os.path.isfile(os.path.join(d, "idVendor")):
            return {k: _read(os.path.join(d, f)) for k, f in
                    (("vid", "idVendor"), ("pid", "idProduct"), ("manufacturer", "manufacturer"),
                     ("product", "product"), ("serial", "serial"))}
        d = os.path.dirname(d)
    return {}


def classify(vid: str, pid: str, manufacturer: str, product: str) -> str:
    vid, pid = vid.lower(), pid.lower()
    if (vid, pid) in GPS_DEVICES or vid in GPS_VENDORS:
        return "gps"
    if GPS_WORDS.search(f"{manufacturer} {product}"):
        return "gps"
    return "adapter" if vid in ADAPTER_VENDORS else "other"


def scan(dev: str = "/dev", sysroot: str = "/sys", verified=()) -> list[Port]:
    """Alle USB-Seriell-Anschlüsse. ``verified``: Kennungen, die der Nutzer schon als GPS
    bestätigt hat (Knopf „Diesen Anschluss prüfen“) – die gelten dann auch als GPS."""
    by_id = {}
    for p in sorted(glob.glob(os.path.join(dev, "serial", "by-id", "*"))):
        by_id[os.path.realpath(p)] = os.path.basename(p)
    out = []
    for path in sorted(glob.glob(os.path.join(dev, "ttyACM*")) +
                       glob.glob(os.path.join(dev, "ttyUSB*"))):
        tty = os.path.basename(path)
        info = _usb_info(tty, sysroot)
        key = by_id.get(os.path.realpath(path)) or \
            "usb-{}:{}{}".format(info.get("vid", "?"), info.get("pid", "?"),
                                 "-" + info["serial"] if info.get("serial") else "")
        kind = classify(info.get("vid", ""), info.get("pid", ""), info.get("manufacturer", ""),
                        info.get("product", ""))
        if key in verified:
            kind = "gps"
        out.append(Port(path, key, info.get("vid", ""), info.get("pid", ""),
                        info.get("manufacturer", ""), info.get("product", ""),
                        info.get("serial", ""), kind))
    return out


def find(key: str, ports: list[Port]) -> Port | None:
    return next((p for p in ports if p.key == key), None)


def profile_ports(cfg: dict) -> set[str]:
    """Anschlüsse aus Funkgeräte- und Rotor-Profilen (echte Pfade) – die fasst GPS nie an."""
    paths = []
    for prof in cfg.get("rig_profiles") or []:
        for k in ("device", "ptt_device", "winkey"):
            if prof.get(k):
                paths.append(prof[k])
    rot = cfg.get("rotor") or {}
    if rot.get("device"):
        paths.append(rot["device"])
    return {os.path.realpath(p) for p in paths if isinstance(p, str) and p.startswith("/")}


def is_profile_port(path: str, cfg: dict) -> bool:
    return os.path.realpath(path) in profile_ports(cfg)


# --- NMEA ------------------------------------------------------------------------------------
def checksum_ok(line: str) -> bool:
    line = line.strip()
    if not line.startswith("$") or "*" not in line:
        return False
    body, _, cs = line[1:].rpartition("*")
    try:
        want = int(cs[:2], 16)
    except ValueError:
        return False
    x = 0
    for c in body.encode("ascii", "replace"):
        x ^= c
    return x == want


def _coord(v: str, hemi: str) -> float | None:
    if not v or not hemi:
        return None
    try:
        dot = v.index(".") if "." in v else len(v)
        deg = float(v[:dot - 2])
        val = deg + float(v[dot - 2:]) / 60.0
    except ValueError:
        return None
    return -val if hemi in "SW" else val


def _hms(v: str) -> tuple[int, int, float] | None:
    if len(v) < 6:
        return None
    try:
        return int(v[0:2]), int(v[2:4]), float(v[4:])
    except ValueError:
        return None


def _int(v: str, default: int = 0) -> int:
    try:
        return int(v)
    except ValueError:
        return default


def parse(line: str) -> dict | None:
    """Einen NMEA-Satz zerlegen – alle Satellitensysteme (GP, GN, GL, GA, GB, BD, GQ …)."""
    if not checksum_ok(line):
        return None
    body = line.strip()[1:].rpartition("*")[0]
    f = body.split(",")
    if len(f[0]) < 5:
        return None
    typ = f[0][-3:]
    f += [""] * 20
    if typ == "RMC":
        return {"type": typ, "time": _hms(f[1]), "valid": f[2] == "A",
                "lat": _coord(f[3], f[4]), "lon": _coord(f[5], f[6]), "date": f[9]}
    if typ == "GGA":
        return {"type": typ, "time": _hms(f[1]), "lat": _coord(f[2], f[3]),
                "lon": _coord(f[4], f[5]), "quality": _int(f[6]), "used": _int(f[7]),
                "alt": float(f[9]) if re.fullmatch(r"-?\d+(\.\d+)?", f[9]) else None}
    if typ == "GNS":
        mode = f[6]
        return {"type": typ, "time": _hms(f[1]), "lat": _coord(f[2], f[3]),
                "lon": _coord(f[4], f[5]), "quality": int(any(c not in "NV" for c in mode)
                                                         if mode else 0), "used": _int(f[7])}
    if typ == "GSA":
        return {"type": typ, "mode": _int(f[2], 1)}
    if typ == "GSV":
        return {"type": typ, "system": f[0][:2], "view": _int(f[3])}
    if typ == "ZDA":
        return {"type": typ, "time": _hms(f[1]),
                "date": f"{f[2]:0>2}{f[3]:0>2}{f[4][-2:]}" if f[2] and f[3] and f[4] else "",
                "year": _int(f[4])}
    return {"type": typ}


def _utc(hms, date: str, year: int = 0) -> float | None:
    if not hms or len(date) != 6:
        return None
    try:
        d, m, y = int(date[0:2]), int(date[2:4]), int(date[4:6])
        y = year if year > 1999 else 2000 + y
        h, mi, s = hms
        return datetime(y, m, d, h, mi, int(s), tzinfo=timezone.utc).timestamp() + (s - int(s))
    except (ValueError, OverflowError):
        return None


@dataclass
class GpsState:
    connected: bool = False        # Daten kommen an
    source: str = ""               # Anzeige: „u-blox 7 (ttyACM0)“ oder „gpsd“
    baud: int = 0
    fix: int = 0                   # 0 = kein Fix, 2 = 2D, 3 = 3D
    used: int = 0                  # Satelliten in der Lösung
    view: int = 0                  # Satelliten in Sicht
    lat: float | None = None
    lon: float | None = None
    alt: float | None = None
    grid: str = ""                 # 6-stellig, z. B. JN59me
    gps_time: float | None = None  # letzte GPS-Zeit (UTC, Unix-Sekunden)
    offset: float | None = None    # GPS − PC in Sekunden (> 0: PC-Uhr geht nach)
    samples: int = 0
    fix_since: float | None = None  # monotonic: seit wann durchgehend Fix
    bad_date: bool = False         # Empfänger meldet ein unsinniges Datum (Wochen-Überlauf)
    error: str = ""
    error_kind: str = ""           # missing / access / busy / nodata / gpsd
    updated: float = 0.0           # monotonic der letzten Daten

    @property
    def has_fix(self) -> bool:
        return self.connected and self.fix >= 2 and self.lat is not None

    def fix_age(self, now: float | None = None) -> float:
        if self.fix_since is None:
            return 0.0
        return (time.monotonic() if now is None else now) - self.fix_since

    def time_trusted(self, now: float | None = None) -> bool:
        """Darf GoGoHam nach dieser Zeit die PC-Uhr stellen?"""
        if not self.has_fix or self.offset is None or self.samples < 5 or self.bad_date:
            return False
        if abs(self.offset) >= BIG_OFFSET_S:
            return self.fix_age(now) >= 60
        return self.fix_age(now) >= LEAP_SAFE_S


class Tracker:
    """Wertet NMEA-Sätze aus und hält den Zustand. Ohne Qt und ohne Gerät testbar."""

    def __init__(self, clock=time.time, mono=time.monotonic, keep: int = 30):
        self.clock, self.mono = clock, mono
        self.state = GpsState()
        self._fix_flags = {"rmc": None, "gga": None, "gsa": None}
        self._view: dict[str, int] = {}
        self._samples: list[float] = []
        self._keep = keep

    def reset_time(self) -> None:
        """Nach dem Stellen der PC-Uhr: neu messen."""
        self._samples.clear()
        self.state.offset, self.state.samples = None, 0

    def feed(self, line: str, recv: float | None = None) -> bool:
        recv = self.clock() if recv is None else recv
        s = parse(line)
        if s is None:
            return False
        st = self.state
        st.connected, st.updated = True, self.mono()
        typ = s["type"]
        if typ == "RMC":
            self._fix_flags["rmc"] = s["valid"]
            if s["valid"]:
                self._pos(s["lat"], s["lon"])
            self._time(s.get("time"), s.get("date", ""), 0, recv, s["valid"])
        elif typ in ("GGA", "GNS"):
            self._fix_flags["gga"] = s["quality"] > 0
            st.used = s["used"]
            if s["quality"] > 0:
                self._pos(s["lat"], s["lon"])
                if s.get("alt") is not None:
                    st.alt = s["alt"]
        elif typ == "GSA":
            self._fix_flags["gsa"] = s["mode"]
        elif typ == "GSV":
            self._view[s["system"]] = s["view"]
            st.view = sum(self._view.values())
        elif typ == "ZDA":
            self._time(s.get("time"), s.get("date", ""), s.get("year", 0), recv,
                       bool(self._fix_flags["rmc"] or self._fix_flags["gga"]))
        self._update_fix()
        return True

    def _pos(self, lat, lon) -> None:
        if lat is None or lon is None:
            return
        self.state.lat, self.state.lon = lat, lon
        self.state.grid = from_latlon(lat, lon, 6)

    def _update_fix(self) -> None:
        st = self.state
        valid = [v for v in (self._fix_flags["rmc"], self._fix_flags["gga"]) if v is not None]
        ok = bool(valid) and all(valid)
        mode = self._fix_flags["gsa"]
        fix = (mode if isinstance(mode, int) and mode >= 2 else 3 if st.alt is not None else 2) \
            if ok else 0
        if fix and st.fix_since is None:
            st.fix_since = self.mono()
        if not fix:
            st.fix_since = None
        st.fix = fix

    def _time(self, hms, date: str, year: int, recv: float, valid: bool) -> None:
        t = _utc(hms, date, year)
        if t is None:
            return
        self.state.gps_time = t
        if not valid:
            return
        off = t - recv
        if abs(off) > 180 * 86400:          # GPS-Wochen-Überlauf alter Empfänger (19,6 Jahre)
            self.state.bad_date = True
            return
        self.state.bad_date = False
        self._samples.append(off)
        del self._samples[:-self._keep]
        self.state.samples = len(self._samples)
        self.state.offset = max(self._samples)

    def stale(self) -> None:
        """Keine Daten mehr: Anzeige auf „nicht verbunden“."""
        st = self.state
        st.connected, st.fix, st.fix_since = False, 0, None
        self._fix_flags = {"rmc": None, "gga": None, "gsa": None}
        self._view.clear()
        st.view = st.used = 0


# --- Schnittstelle (nur lesen) -------------------------------------------------------------
def _lines(fd: int, on: bool) -> None:
    import fcntl
    import struct
    import termios
    try:
        fcntl.ioctl(fd, termios.TIOCMBIS if on else termios.TIOCMBIC,
                    struct.pack("I", termios.TIOCM_DTR | termios.TIOCM_RTS))
    except OSError:
        pass                                   # z. B. Pseudo-Terminal ohne Steuerleitungen


def open_read(path: str, baud: int, dtr: bool = False) -> int:
    """Nur zum Lesen öffnen, 8N1, Steuerleitungen aus (bei ``dtr`` an – nur echte GPS-Geräte,
    manche schicken erst dann Daten)."""
    import termios
    fd = os.open(path, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        _lines(fd, dtr)
        a = termios.tcgetattr(fd)
        a[0] = termios.IGNPAR
        a[1] = 0
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL      # ohne HUPCL
        a[3] = 0
        speed = getattr(termios, f"B{int(baud)}", termios.B9600)
        a[4] = a[5] = speed
        termios.tcsetattr(fd, termios.TCSANOW, a)
        _lines(fd, dtr)
        termios.tcflush(fd, termios.TCIFLUSH)
    except Exception:
        os.close(fd)
        raise
    return fd


class LineReader:
    """Liest Zeilen aus einem fd oder Socket (nicht blockierend)."""

    def __init__(self, read):
        self._read = read
        self._buf = b""

    def lines(self, timeout: float) -> list[str]:
        data = self._read(timeout)
        if data is None:
            raise OSError(errno.EIO, "closed")
        self._buf += data
        if len(self._buf) > 65536:
            self._buf = self._buf[-4096:]
        *full, self._buf = self._buf.split(b"\n")
        return [x.decode("ascii", "replace").strip() for x in full if x.strip()]


def _fd_reader(fd: int):
    import select

    def read(timeout: float) -> bytes | None:
        r, _, _ = select.select([fd], [], [], max(0.0, timeout))
        if not r:
            return b""
        try:
            data = os.read(fd, 1024)
        except BlockingIOError:
            return b""
        return data or None                    # leer = Gerät abgezogen
    return read


def listen(path: str, bauds=None, dtr_retry: bool = False, listen_s: float = LISTEN_S,
           opener=open_read) -> tuple[int, bool] | None:
    """Kommt an diesem Anschluss GPS-Text an? -> (Geschwindigkeit, DTR an) oder None.
    Es wird nichts geschickt."""
    tries = [(b, False) for b in (bauds or BAUDS)]
    if dtr_retry:
        tries += [(b, True) for b in (bauds or BAUDS)[:2]]
    for baud, dtr in tries:
        fd = opener(path, baud, dtr)
        try:
            rd = LineReader(_fd_reader(fd))
            end = time.monotonic() + listen_s
            while time.monotonic() < end:
                if any(checksum_ok(x) for x in rd.lines(0.3)):
                    return baud, dtr
        finally:
            os.close(fd)
    return None


def gpsd_available(addr=GPSD, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection(addr, timeout=timeout):
            return True
    except OSError:
        return False


def explain(exc: OSError, path: str) -> tuple[str, str]:
    if exc.errno in (errno.EACCES, errno.EPERM):
        return "access", tr("Kein Zugriff auf {p} – Einstellungen → GPS → „USB-Geräte "
                            "freigeben …“", p=path)
    if exc.errno == errno.EBUSY:
        return "busy", tr("{p} ist von einem anderen Programm belegt (z. B. gpsd).", p=path)
    if exc.errno in (errno.ENOENT, errno.ENODEV, errno.ENXIO, errno.EIO):
        return "missing", tr("GPS-Empfänger nicht eingesteckt.")
    return "error", f"{path}: {exc.strerror or exc}"


@dataclass
class Source:
    kind: str = "serial"          # serial / gpsd
    key: str = ""                 # feste Kennung des Geräts (serial)
    path: str = ""                # fester Pfad statt Kennung (von Hand)
    baud: int = 0                 # 0 = automatisch
    label: str = ""
    known_gps: bool = True        # echtes GPS-Gerät (darf DTR an, wenn sonst nichts kommt)


class GpsWorker(threading.Thread):
    """Hält die Verbindung zum Empfänger (oder zu gpsd), verbindet nach Abziehen neu."""

    def __init__(self, source: Source, scan_fn=scan, opener=open_read, retry: float = 2.0,
                 gpsd_addr=GPSD, blocked=lambda path: False):
        super().__init__(daemon=True, name="gps")
        self.source = source
        self.scan_fn, self.opener, self.retry = scan_fn, opener, retry
        self.gpsd_addr = gpsd_addr
        self.blocked = blocked
        self.tracker = Tracker()
        self._lock = threading.Lock()
        self._halt = threading.Event()
        self._reset = threading.Event()

    # von der Oberfläche aus
    def snapshot(self) -> GpsState:
        with self._lock:
            return replace(self.tracker.state)

    def reset_time(self) -> None:
        self._reset.set()

    def stop(self) -> None:
        self._halt.set()

    # im Thread
    def _set_error(self, kind: str, text: str) -> None:
        with self._lock:
            self.tracker.stale()
            st = self.tracker.state
            st.error, st.error_kind = text, kind

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                if self.source.kind == "gpsd":
                    self._run_gpsd()
                else:
                    self._run_serial()
            except OSError as e:
                kind, text = explain(e, self.source.path or self.source.label or "GPS")
                self._set_error(kind, text)
            except Exception as e:  # noqa: BLE001 – der Thread darf nie sterben
                self._set_error("error", str(e))
            self._halt.wait(self.retry)

    def _path(self) -> str | None:
        if self.source.path:
            return self.source.path if os.path.exists(self.source.path) else None
        port = find(self.source.key, self.scan_fn())
        return port.path if port else None

    def _run_serial(self) -> None:
        path = self._path()
        if not path:
            self._set_error("missing", tr("GPS-Empfänger nicht eingesteckt."))
            return
        if self.blocked(path):
            self._set_error("blocked", tr("{p} gehört zu einem Funkgerät-Profil – GoGoHam liest "
                                          "dort kein GPS.", p=path))
            return
        bauds = [self.source.baud] if self.source.baud else BAUDS
        found = listen(path, bauds, dtr_retry=self.source.known_gps, opener=self.opener)
        if found is None:
            self._set_error("nodata", tr("Vom Empfänger kommen keine GPS-Daten an."))
            return
        baud, dtr = found
        fd = self.opener(path, baud, dtr)
        try:
            with self._lock:
                st = self.tracker.state
                st.source, st.baud, st.error, st.error_kind = \
                    self.source.label or os.path.basename(path), baud, "", ""
            self._pump(LineReader(_fd_reader(fd)))
        finally:
            os.close(fd)

    def _run_gpsd(self) -> None:
        sock = socket.create_connection(self.gpsd_addr, timeout=2.0)
        try:
            # Das geht an gpsd (Programm auf diesem Rechner), nicht an das Gerät
            sock.sendall(b'?WATCH={"enable":true,"nmea":true};\n')
            sock.setblocking(False)
            import select

            def read(timeout: float) -> bytes | None:
                r, _, _ = select.select([sock], [], [], max(0.0, timeout))
                if not r:
                    return b""
                try:
                    data = sock.recv(4096)
                except BlockingIOError:
                    return b""
                return data or None
            with self._lock:
                st = self.tracker.state
                st.source, st.baud, st.error, st.error_kind = "gpsd", 0, "", ""
            self._pump(LineReader(read))
        finally:
            sock.close()

    def _pump(self, rd: LineReader) -> None:
        last = time.monotonic()
        while not self._halt.is_set():
            if self._reset.is_set():
                self._reset.clear()
                with self._lock:
                    self.tracker.reset_time()
            got = False
            for line in rd.lines(0.5):
                if line.startswith("$"):
                    with self._lock:
                        got = self.tracker.feed(line) or got
            now = time.monotonic()
            if got:
                last = now
            elif now - last > STALE_S:
                self._set_error("nodata", tr("Vom Empfänger kommen keine GPS-Daten mehr an."))
                return


GPS_DEFAULTS = {
    "enabled": False,        # GPS benutzen
    "source": "auto",        # auto (gpsd, wenn er läuft, sonst Gerät) / serial / gpsd
    "device": "",            # feste Kennung des Geräts (Port.key)
    "label": "",             # Anzeige-Name des Geräts
    "path": "",              # fester Anschluss von Hand (statt Kennung)
    "baud": 0,               # 0 = automatisch
    "ignored": [],           # „Nie für dieses Gerät“
    "verified": [],          # vom Nutzer geprüfte Anschlüsse (gelten als GPS)
    "grid_hint": True,       # Hinweis, wenn der Locator nicht zum Log passt
    "map": True,             # eigener Standort auf Karte/Rotor/Baken vom GPS
    "clock": True,           # Uhrzeit mit GPS vergleichen
}


def gps_settings(cfg: dict) -> dict:
    """Einstellungen mit Vorgaben aufgefüllt (schreibt sie in cfg["gps"])."""
    g = cfg.get("gps")
    if not isinstance(g, dict):
        g = {}
    for k, v in GPS_DEFAULTS.items():
        g.setdefault(k, list(v) if isinstance(v, list) else v)
    cfg["gps"] = g
    return g


def auto_port(gcfg: dict, ports: list[Port], blocked=lambda path: False) -> Port | None:
    """Erster sicher erkannter GPS-Empfänger, der nicht abgelehnt ist und keinem Profil gehört."""
    for p in ports:
        if p.kind == "gps" and p.key not in gcfg.get("ignored", []) and not blocked(p.path):
            return p
    return None


def source_from_cfg(gcfg: dict, ports: list[Port] | None = None, gpsd: bool | None = None,
                    blocked=lambda path: False) -> Source | None:
    """Welche Quelle laut Einstellungen? None = (noch) keine.
    auto: gpsd, wenn er läuft – sonst das gemerkte Gerät – sonst der erste erkannte Empfänger."""
    mode = gcfg.get("source", "auto")
    if mode == "gpsd" or (mode == "auto" and (gpsd if gpsd is not None else gpsd_available())):
        return Source("gpsd", label="gpsd")
    if gcfg.get("path"):
        return Source("serial", path=gcfg["path"], baud=int(gcfg.get("baud") or 0),
                      label=gcfg.get("label") or os.path.basename(gcfg["path"]), known_gps=False)
    if ports is None:
        ports = scan(verified=gcfg.get("verified", []))
    key = gcfg.get("device", "")
    port = find(key, ports) if key else auto_port(gcfg, ports, blocked)
    if port is None and not key:
        return None
    key = key or port.key
    label = port.label if port else (gcfg.get("label") or key)
    return Source("serial", key=key, baud=int(gcfg.get("baud") or 0), label=label,
                  known_gps=(port.kind == "gps") if port else True)


def status_text(st: GpsState) -> tuple[str, str]:
    """Kurztext für die Statuszeile und Farbe (ok / wait / off / error)."""
    if st.has_fix:
        return tr("GPS {grid} · {n} Sat", grid=st.grid, n=st.used or st.view), "ok"
    if st.connected:
        return tr("GPS sucht Satelliten ({n} in Sicht)", n=st.view), "wait"
    if st.error_kind in ("access", "busy", "blocked", "error"):
        return tr("GPS: Problem"), "error"
    if st.error_kind == "missing":
        return tr("GPS: nicht eingesteckt"), "off"
    return tr("GPS: verbinde …"), "off"
