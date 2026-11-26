"""Rotorsteuerung über Hamlib rotctld (ab 0.8.23).

Wie beim Funkgerät spricht GoGoHam nie direkt mit der Schnittstelle, sondern mit einem
**rotctld** (Textprotokoll über TCP). Den startet GoGoHam selbst, richtet ihn dauerhaft als
Benutzerdienst ein (Standard) oder benutzt einen vorhandenen.

Viele Rotor-Steuergeräte (Yaesu G-450/G-1000, Kenpro, Hy-Gain/CDE Ham IV …) haben keinen
PC-Anschluss; dafür gibt es Interfaces, die ein bekanntes Protokoll sprechen: GS-232A/B
(Yaesu, ERC von DF9GR, K3NG-Arduino …), Easycomm, Rotor-EZ/DCU-1, SPID Rot2Prog usw. – alle
in der Hamlib-Liste.

Drehbereich: Hamlib kennt Minimum/Maximum des Modells (z. B. GS-232B −180…450°). Ziele werden
in diesen Bereich gelegt; gibt es zwei Möglichkeiten (Überlappung), nimmt GoGoHam den
kürzeren Weg von der aktuellen Richtung aus.
"""

from __future__ import annotations

import glob
import os
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from functools import lru_cache

from .i18n import tr

DEFAULT_PORT = 4540              # 4532/4533 … sind für Funkgerät-Profile
UNIT_PREFIX = "gogoham-rotctld-"
REACHED_DEG = 2.0                # so nah = angekommen


# --------------------------------------------------------------------- Modelle
@dataclass(frozen=True)
class RotorModel:
    model: int
    mfg: str
    name: str
    status: str = "Stable"

    @property
    def label(self) -> str:
        return f"{self.mfg} – {self.name}"


@dataclass
class RotorCaps:
    model: int
    port_type: str = ""
    speed_min: int = 0
    speed_max: int = 0
    min_az: float = 0.0
    max_az: float = 360.0
    can_stop: bool = True

    @property
    def serial(self) -> bool:
        return self.port_type.upper().startswith(("RS-232", "SERIAL", "USB"))

    def bauds(self) -> list[int]:
        from .hamlib import STANDARD_BAUDS
        if not self.speed_max:
            return list(STANDARD_BAUDS)
        lo = self.speed_min or 0
        return [b for b in STANDARD_BAUDS if lo <= b <= self.speed_max] or list(STANDARD_BAUDS)


def rotctl_exe() -> str:
    return shutil.which("rotctl") or ""


_LIST_RE = re.compile(r"^\s*(\d+)\s{2,}(.+?)\s{2,}(.+?)\s{2,}(\S+)\s{2,}(\S+)")


def parse_list(text: str) -> list[RotorModel]:
    out = []
    for line in text.splitlines():
        m = _LIST_RE.match(line)
        if m:
            out.append(RotorModel(int(m.group(1)), m.group(2).strip(), m.group(3).strip(),
                                  m.group(5).strip()))
    return out


@lru_cache(maxsize=1)
def list_rotors() -> tuple[RotorModel, ...]:
    exe = rotctl_exe()
    if not exe:
        return ()
    try:
        r = subprocess.run([exe, "-l"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ()
    return tuple(parse_list(r.stdout))


def find_model(model: int, rotors=None) -> RotorModel | None:
    return next((r for r in (rotors if rotors is not None else list_rotors())
                 if r.model == int(model or 0)), None)


def filter_rotors(rotors, text: str) -> list[RotorModel]:
    words = [w for w in re.split(r"\s+", (text or "").lower()) if w]
    norm = lambda s: re.sub(r"[\s\-_/]", "", s.lower())  # noqa: E731
    return [r for r in rotors
            if all(norm(w) in norm(r.label) or w in r.label.lower() for w in words)]


def parse_caps(model: int, text: str) -> RotorCaps:
    c = RotorCaps(model)
    for line in text.splitlines():
        key, _, val = line.partition(":")
        val = val.strip()
        if key == "Port type":
            c.port_type = val
        elif key == "Serial speed":
            m = re.match(r"(\d+)\.\.(\d+)", val)
            if m:
                c.speed_min, c.speed_max = int(m.group(1)), int(m.group(2))
        elif key == "Min Azimuth":
            c.min_az = float(val)
        elif key == "Max Azimuth":
            c.max_az = float(val)
        elif key == "Can Stop":
            c.can_stop = val.upper().startswith("Y")
    return c


@lru_cache(maxsize=64)
def rotor_caps(model: int) -> RotorCaps | None:
    exe = rotctl_exe()
    if not exe or not model:
        return None
    try:
        r = subprocess.run([exe, "-m", str(int(model)), "-u"], capture_output=True, text=True,
                           timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_caps(int(model), r.stdout)


# --------------------------------------------------------------------- Richtung
def normalize_az(target: float, current: float | None, min_az: float = 0.0,
                 max_az: float = 360.0) -> float | None:
    """Ziel (0–360°) in den Drehbereich des Rotors legen. Gibt es mehrere Möglichkeiten
    (Überlappung, z. B. 0–450°), die mit dem kürzesten Weg von ``current`` aus.
    None = Richtung liegt außerhalb des Bereichs."""
    t = target % 360.0
    cands = [t + k * 360.0 for k in (-2, -1, 0, 1)]
    ok = [a for a in cands if min_az - 0.01 <= a <= max_az + 0.01]
    if not ok:
        return None
    if current is None:
        return min(ok, key=lambda a: (abs(a - t), a))
    return min(ok, key=lambda a: (abs(a - current), a))


def bearing_to(home, pos, long_path: bool = False) -> int | None:
    """Beam-Richtung (ganze Grad, 0–359) vom eigenen Standort zum Ziel."""
    if not home or not pos:
        return None
    from .locator import bearing_deg
    b = bearing_deg(home[0], home[1], pos[0], pos[1])
    if long_path:
        b += 180.0
    return int(round(b)) % 360


# --------------------------------------------------------------------- rotctld
class RotctldClient:
    """Blockierender Client für das rotctld-Textprotokoll."""

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT, timeout: float = 2.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock: socket.socket | None = None
        self._buf = b""

    def connect(self) -> None:
        self.close()
        s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        s.settimeout(self.timeout)
        self.sock, self._buf = s, b""

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def _readline(self) -> str:
        assert self.sock
        while b"\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError(tr("rotctld hat die Verbindung geschlossen"))
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode("ascii", "replace").strip()

    def command(self, cmd: str, lines: int = 1) -> list[str]:
        if not self.sock:
            self.connect()
        assert self.sock
        self.sock.sendall((cmd + "\n").encode())
        out = [self._readline()]
        if out[0].startswith("RPRT"):
            if out[0] != "RPRT 0":
                raise RuntimeError(tr("rotctld meldet Fehler: {p1} ({cmd})", p1=out[0], cmd=cmd))
            return out
        out += [self._readline() for _ in range(lines - 1)]
        return out

    def get_position(self) -> tuple[float, float]:
        az, el = self.command("p", 2)
        return float(az), float(el)

    def set_position(self, az: float, el: float = 0.0) -> None:
        self.command(f"P {az:.1f} {el:.1f}")

    def stop(self) -> None:
        self.command("S")


@dataclass
class RotorState:
    connected: bool = False
    az: float | None = None          # Richtung, wie der Rotor sie meldet (kann > 360 sein)
    el: float = 0.0
    target: int | None = None        # Ziel 0–359 (None = steht)
    error: str = ""
    notice: str = ""
    notice_id: int = 0

    @property
    def heading(self) -> int | None:
        """Richtung 0–359 für die Anzeige."""
        return None if self.az is None else int(round(self.az)) % 360


class RotorWorker(threading.Thread):
    """Hintergrund-Thread: liest die Richtung (1 s, beim Drehen 0,5 s) und dreht/stoppt."""

    def __init__(self, host: str, port: int, min_az: float = 0.0, max_az: float = 360.0,
                 poll: float = 1.0):
        super().__init__(daemon=True, name="rotor")
        self.client = RotctldClient(host, port)
        self.min_az, self.max_az = min_az, max_az
        self.poll = poll
        self.state = RotorState()
        self.lock = threading.Lock()
        self.commands: queue.Queue = queue.Queue()
        self._halt = threading.Event()
        self._wake = threading.Event()
        self._raw_target: float | None = None

    def stop(self) -> None:
        self._halt.set()
        self._wake.set()

    def turn(self, az: float) -> None:
        self.commands.put(("turn", float(az)))
        self._wake.set()

    def halt_rotor(self) -> None:
        self.commands.put(("stop", None))
        self._wake.set()

    def snapshot(self) -> RotorState:
        with self.lock:
            return RotorState(**self.state.__dict__)

    def _set(self, **kw) -> None:
        with self.lock:
            for k, v in kw.items():
                setattr(self.state, k, v)

    def _notice(self, text: str) -> None:
        with self.lock:
            self.state.notice = text
            self.state.notice_id += 1

    def _do(self, name: str, arg) -> None:
        if name == "stop":
            self.client.stop()
            self._raw_target = None
            self._set(target=None)
            return
        cur = self.state.az
        raw = normalize_az(arg, cur, self.min_az, self.max_az)
        if raw is None:
            self._notice(tr("Rotor: {deg}° liegt außerhalb des Drehbereichs ({lo}…{hi}°)",
                            deg=int(round(arg)) % 360, lo=int(self.min_az), hi=int(self.max_az)))
            return
        self.client.set_position(raw, self.state.el)
        self._raw_target = raw
        self._set(target=int(round(arg)) % 360)

    def run(self) -> None:
        retry_at = 0.0
        while not self._halt.is_set():
            if not self.client.sock:
                if time.monotonic() < retry_at:
                    self._wake.wait(0.2)
                    continue
                try:
                    self.client.connect()
                    self._set(connected=True, error="")
                except OSError as e:
                    self._set(connected=False, error=tr("rotctld nicht erreichbar ({e})", e=e))
                    retry_at = time.monotonic() + 3
                    continue
            try:
                self._wake.clear()
                while True:
                    try:
                        name, arg = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        self._do(name, arg)
                    except RuntimeError as e:
                        self._notice(tr("Rotor hat den Befehl abgelehnt: {e}", e=e))
                az, el = self.client.get_position()
                target = self.state.target
                if self._raw_target is not None and abs(az - self._raw_target) <= REACHED_DEG:
                    self._raw_target, target = None, None          # angekommen
                self._set(connected=True, az=az, el=el, target=target, error="")
            except RuntimeError as e:
                self._set(error=str(e))
            except (OSError, ConnectionError, ValueError) as e:
                self.client.close()
                self._set(connected=False, error=tr("Verbindung verloren ({e})", e=e))
                retry_at = time.monotonic() + 2
                continue
            self._wake.wait(0.5 if self._raw_target is not None else self.poll)
        self.client.close()


def port_in_use(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def rotctld_cmd(prof: dict, exe: str | None = None) -> list[str]:
    exe = exe or shutil.which("rotctld") or "rotctld"
    cmd = [exe, "-m", str(int(prof["model"]))]
    if prof.get("device"):
        cmd += ["-r", prof["device"]]
    if int(prof.get("baud") or 0):
        cmd += ["-s", str(int(prof["baud"]))]
    cmd += ["-t", str(int(prof.get("port") or DEFAULT_PORT))]
    cmd += (prof.get("extra") or "").split()
    return cmd


def start_rotctld(prof: dict) -> subprocess.Popen:
    if not shutil.which("rotctld"):
        raise FileNotFoundError(tr("rotctld nicht gefunden – bitte Hamlib installieren"))
    return subprocess.Popen(rotctld_cmd(prof), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


@dataclass
class TestResult:
    ok: bool
    text: str


def test_profile(prof: dict, timeout: float = 8.0) -> TestResult:
    """Richtung einmal lesen – **dreht nie**. Läuft schon ein rotctld auf dem Port, über ihn."""
    from .hamlib import explain_error, port_problem
    host, port = prof.get("host", "127.0.0.1"), int(prof.get("port") or DEFAULT_PORT)
    if port_in_use(host, port):
        c = RotctldClient(host, port, timeout=3.0)
        try:
            az, _el = c.get_position()
        except (OSError, RuntimeError, ConnectionError, ValueError) as e:
            return TestResult(False, tr("rotctld auf {host}:{port} antwortet nicht richtig: {e}",
                                        host=host, port=port, e=e))
        finally:
            c.close()
        return TestResult(True, tr("Verbindung in Ordnung: Rotor steht auf {deg}° (über rotctld "
                                   "auf Port {port})", deg=int(round(az)) % 360, port=port))
    if prof.get("mode") == "external":
        return TestResult(False, tr("Auf {host}:{port} läuft kein rotctld. Läuft der Dienst? Oder "
                                    "„GoGoHam startet rotctld selbst“ wählen.", host=host, port=port))
    exe = rotctl_exe()
    if not exe:
        return TestResult(False, tr("rotctl nicht gefunden – bitte Hamlib installieren"))
    problem = port_problem(prof.get("device", ""))
    if problem:
        return TestResult(False, problem)
    cmd = [exe, "-m", str(int(prof["model"]))]
    if prof.get("device"):
        cmd += ["-r", prof["device"]]
    if int(prof.get("baud") or 0):
        cmd += ["-s", str(int(prof["baud"]))]
    cmd += (prof.get("extra") or "").split() + ["p"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return TestResult(False, tr("Keine Antwort vom Rotor-Interface (Zeitüberschreitung). "
                                    "Stimmen Schnittstelle und Baudrate? Ist es eingeschaltet?"))
    except OSError as e:
        return TestResult(False, tr("rotctl ließ sich nicht starten: {e}", e=e))
    lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    try:
        az = float(lines[0])
    except (IndexError, ValueError):
        err = (r.stderr.strip().splitlines() or [tr("unbekannter Fehler")])[-1]
        return TestResult(False, explain_error(r.stderr, prof.get("device", "")) or
                          tr("Keine Verbindung: {err}", err=err))
    return TestResult(True, tr("Verbindung in Ordnung: Rotor steht auf {deg}°",
                               deg=int(round(az)) % 360))


# --------------------------------------------------------------------- Hintergrunddienst
def unit_name(port: int) -> str:
    return f"{UNIT_PREFIX}{int(port)}.service"


def system_rotctld() -> str:
    """rotctld des Systems (nie der aus einem AppImage)."""
    appdir = os.environ.get("APPDIR", "")
    for d in os.environ.get("PATH", "").split(os.pathsep):
        exe = os.path.join(d, "rotctld")
        if d and os.access(exe, os.X_OK) and not (appdir and exe.startswith(appdir)):
            return exe
    return ""


def unit_text(prof: dict, exe: str | None = None) -> str:
    from .rigservice import _quote
    cmd = rotctld_cmd(prof, exe or system_rotctld() or "/usr/bin/rotctld")
    name = (prof.get("name") or "").replace("\n", " ")
    return ("# Von GoGoHam angelegt – wird beim Speichern der Rotor-Einstellungen\n"
            "# überschrieben oder gelöscht. Bitte in GoGoHam ändern, nicht hier.\n"
            "[Unit]\n"
            f"Description=GoGoHam rotctld {name} (Port {int(prof.get('port') or DEFAULT_PORT)})\n\n"
            "[Service]\n"
            f"ExecStart={' '.join(_quote(a) for a in cmd)}\n"
            "Restart=always\nRestartSec=5\n\n"
            "[Install]\nWantedBy=default.target\n")


def sync_service(prof: dict | None, run=None, directory: str | None = None) -> list[str]:
    """Benutzerdienst passend zum Rotor-Profil anlegen, ändern oder entfernen.
    ``prof`` None oder nicht „service“ = Dienst(e) entfernen. Fehlermeldungen, leer = gut."""
    from . import rigservice
    run = run or rigservice._run
    directory = directory or rigservice.unit_dir()
    want = prof if prof and prof.get("enabled") and prof.get("mode") == "service" \
        and int(prof.get("model") or 0) else None
    errors: list[str] = []
    existing = {os.path.basename(f) for f in glob.glob(os.path.join(directory, UNIT_PREFIX + "*"))}
    keep = unit_name(want.get("port") or DEFAULT_PORT) if want else ""
    for unit in sorted(existing - {keep}):
        run(["systemctl", "--user", "disable", "--now", unit])
        try:
            os.remove(os.path.join(directory, unit))
        except OSError as e:
            errors.append(str(e))
    if not want:
        if existing:
            run(["systemctl", "--user", "daemon-reload"])
        return errors
    path = os.path.join(directory, keep)
    text = unit_text(want)
    try:
        with open(path, encoding="utf-8") as f:
            same = f.read() == text
    except OSError:
        same = False
    if not same:
        try:
            os.makedirs(directory, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            return errors + [str(e)]
    run(["systemctl", "--user", "daemon-reload"])
    r = run(["systemctl", "--user", "enable", keep])
    r2 = run(["systemctl", "--user", "restart" if not same else "start", keep])
    for x in (r, r2):
        if x.returncode != 0:
            last = ((x.stderr or x.stdout or "").strip().splitlines() or ["?"])[-1]
            errors.append(tr("Hintergrund-rotctld {u}: {e}", u=keep, e=last))
            break
    return errors


def has_units(directory: str | None = None) -> bool:
    from . import rigservice
    return bool(glob.glob(os.path.join(directory or rigservice.unit_dir(), UNIT_PREFIX + "*")))


DEFAULTS = {"enabled": False, "name": "", "model": 0, "device": "", "baud": 0, "extra": "",
            "host": "127.0.0.1", "port": DEFAULT_PORT, "mode": "",
            "beamwidth": 30}            # Öffnungswinkel der Antenne in Grad (0.8.23.2, Karte)


def profile(cfg: dict) -> dict:
    """Rotor-Einstellungen mit Standardwerten. ``mode`` "" = noch nie gespeichert (das
    Fenster schlägt dann „dauerhaft“ vor, wo möglich)."""
    p = dict(DEFAULTS)
    p.update(cfg.get("rotor") or {})
    p["model"] = int(p.get("model") or 0)
    p["port"] = int(p.get("port") or DEFAULT_PORT)
    p["baud"] = int(p.get("baud") or 0)
    p["beamwidth"] = max(5, min(180, int(p.get("beamwidth") or 30)))
    return p


def handover(port: int, run=None, directory: str | None = None) -> list[str]:
    """Rotor-Dienst ans System übergeben (läuft als rotctld-<Port>.service weiter, 0.8.23.5)."""
    from . import rigservice
    return rigservice.handover(unit_name(port), run or rigservice._run, directory)
