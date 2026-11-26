"""CAT-Steuerung über Hamlib rigctld (TCP, Standard-Port 4532).

rigctld läuft als eigener Prozess und spricht per USB mit dem Funkgerät.
Vorteil: WSJT-X kann gleichzeitig dasselbe rigctld benutzen
(in WSJT-X als Rig "Hamlib NET rigctl" mit 127.0.0.1:4532 einstellen).

Jedes Funkgerät hat seinen eigenen rigctld (eigener Port). Ein Geräte-Profil sagt
GoGoHam nur, mit welchem rigctld es spricht – andere Programme sind davon nicht betroffen.
"""

from __future__ import annotations

from .i18n import tr

import queue
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass


# Hamlib RIG_PASSBAND_NORMAL: beim Wechsel der Betriebsart den Standardfilter des Funkgeräts
# nehmen – welcher das ist, entscheidet das Gerät selbst (Wunsch Nutzer 0.8.12.7; 0.8.12.1–0.8.12.6
# schickte -1 = „Filter nicht ändern“, das hat sich im Betrieb nicht bewährt)
RIG_FILTER = 0


@dataclass
class RigState:
    connected: bool = False
    freq: int = 0
    mode: str = ""
    error: str = ""
    model: int = 0          # Hamlib-Modell, das rigctld wirklich benutzt (0 = unbekannt)
    notice: str = ""        # Hinweis für die Statuszeile, z. B. „Sprachspeicher abgelehnt“
    notice_id: int = 0      # zählt hoch, damit derselbe Hinweis nicht doppelt erscheint
    notice_long: str = ""   # ausführlicher Text (untere Statuszeile, Tooltip) – ab 0.8.12.9
    wpm: int = 0            # CW-Tempo am Funkgerät (0 = unbekannt / kann das Gerät nicht)
    query_ms: float = 0.0   # so lange braucht eine Frequenzabfrage (gemessen, ab 0.8.29.1)
    poll_ms: int = 0        # Abstand der Abfragen, den GoGoHam gerade benutzt
    ptt: bool = False       # GoGoHam hat Senden eingeschaltet und das Gerät hat es bestätigt
    ptt_id: int = 0         # zählt bei jedem bestätigten PTT-Befehl hoch (ab 0.8.11)


class RigctldClient:
    """Einfacher, blockierender Client für das rigctld-Textprotokoll."""

    def __init__(self, host: str = "127.0.0.1", port: int = 4532, timeout: float = 1.5):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock: socket.socket | None = None
        self._buf = b""

    def connect(self) -> None:
        self.close()
        s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        s.settimeout(self.timeout)
        self.sock = s
        self._buf = b""

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
                raise ConnectionError(tr("rigctld hat die Verbindung geschlossen"))
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode("ascii", "replace").strip()

    def command(self, cmd: str, lines: int = 1) -> list[str]:
        if not self.sock:
            self.connect()
        assert self.sock
        self.sock.sendall((cmd + "\n").encode())
        out = [self._readline() for _ in range(lines)]
        if out and out[0].startswith("RPRT") and out[0] != "RPRT 0":
            raise RuntimeError(tr("rigctld meldet Fehler: {p1} ({cmd})", p1=out[0], cmd=cmd))
        return out

    def get_freq(self) -> int:
        return int(float(self.command("f")[0]))

    def get_mode(self) -> str:
        first = self.command("m", 1)[0]
        if first.startswith("RPRT"):
            return ""
        self._readline()  # Passband
        return first

    def set_cache(self, ms: int) -> None:
        """Zwischenspeicher von Hamlib (Standard 1000 ms: so lange meldet rigctld die alte
        Frequenz). 0.8.29.1: GoGoHam stellt ihn klein, damit die Anzeige dem VFO folgt."""
        self.command(f"\\set_cache {int(ms)}")

    def set_freq(self, hz: int) -> None:
        self.command(f"F {int(hz)}")

    def set_mode(self, mode: str, passband: int = RIG_FILTER) -> None:
        """Betriebsart setzen – mit dem Standardfilter, den das Funkgerät dafür vorsieht."""
        self.command(f"M {mode} {passband}")

    def get_keyspd(self) -> int:
        """CW-Tempo in WpM lesen (Hamlib-Level KEYSPD)."""
        first = self.command("l KEYSPD")[0]
        if first.startswith("RPRT"):
            raise RuntimeError(first)
        return int(float(first))

    def set_keyspd(self, wpm: int) -> None:
        """CW-Tempo setzen – ändert nur die Einstellung, sendet nichts."""
        self.command(f"L KEYSPD {int(wpm)}")

    def send_morse(self, text: str) -> None:
        self.command(f"b {text}")

    def stop_morse(self) -> None:
        self.command("\\stop_morse")

    def send_voice_mem(self, n: int) -> None:
        self.command(f"\\send_voice_mem {int(n)}")

    def ptt(self, on: bool) -> None:
        self.command(f"T {1 if on else 0}")


def port_in_use(host: str, port: int, timeout: float = 0.5) -> bool:
    """Lauscht auf host:port schon ein Programm (z. B. ein anderer rigctld)?"""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def query_model(host: str, port: int, timeout: float = 1.5) -> int:
    """Hamlib-Modell des laufenden rigctld (2. Zeile von \\dump_state), 0 = unbekannt.

    Eigene, kurze Verbindung, damit die Abfrage-Verbindung nicht durcheinanderkommt.
    Liest nur – am Funkgerät ändert sich nichts.
    """
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(b"\\dump_state\n")
            buf = b""
            while buf.count(b"\n") < 2:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
    except OSError:
        return 0
    lines = buf.decode("ascii", "replace").splitlines()
    return int(lines[1]) if len(lines) > 1 and lines[1].strip().isdigit() else 0


class RigWorker(threading.Thread):
    """Hintergrund-Thread: fragt Frequenz/Mode ab und führt Befehle aus."""

    # Nur-Hören (S&P-Übung, 0.8.29): erlaubt sind nur diese Befehle – nie PTT, CW, Sprachspeicher
    LISTEN_OK = frozenset({"set_freq", "set_mode"})

    MIN_POLL = 0.02          # höchstens 50 Frequenzabfragen pro Sekunde (Nutzer 0.8.29.1)
    MAX_POLL = 1.0
    CACHE_MS = 10            # Hamlib-Zwischenspeicher, solange GoGoHam verbunden ist
    MODE_EVERY = 1.0         # Betriebsart nur einmal pro Sekunde

    def __init__(self, host: str, port: int, poll: float | None = None,
                 listen_only: bool = False):
        """poll=None: automatisch – GoGoHam misst, wie schnell das Gerät antwortet, und fragt
        so oft wie möglich (höchstens MIN_POLL). Sonst fester Abstand in Sekunden."""
        super().__init__(daemon=True, name="rig")
        self.listen_only = listen_only
        # PTT über DTR/RTS schaltet seit 0.10.45 der rigctld (--ptt-type), nie GoGoHam selbst:
        # so bleibt pro Gerät nur EIN Programm an der Schnittstelle (Regel A).
        self.client = RigctldClient(host, port)
        self.auto = poll is None
        self.poll = 0.2 if poll is None else max(self.MIN_POLL, float(poll))
        self._q_avg = 0.0                # gleitender Mittelwert der Abfragedauer (s)
        self._mode_next = 0.0
        self.state = RigState()
        self.lock = threading.Lock()
        self.commands: queue.Queue = queue.Queue()
        self._halt = threading.Event()
        self._wake = threading.Event()   # neuer Befehl: nicht bis zur nächsten Abfrage warten
        self._wpm_ok = True              # False, wenn das Gerät KEYSPD nicht kennt
        self._wpm_next = 0.0             # nächste Tempo-Abfrage (nur in CW)
        self.guard = None                # Sende-Wächter (0.10.46), eigener Prozess
        self._guard_lock = threading.Lock()
        self._beat_next = 0.0

    def stop(self) -> None:
        self._halt.set()
        self._wake.set()

    def submit(self, name: str, *args) -> None:
        """Befehl einreihen, z. B. submit('set_freq', 14025000)."""
        if self.listen_only and name not in self.LISTEN_OK:
            return                                     # Übung: es wird nie gesendet
        self.commands.put((name, args))
        self._wake.set()

    def snapshot(self) -> RigState:
        with self.lock:
            return RigState(**self.state.__dict__)

    def _set(self, **kw) -> None:
        with self.lock:
            for k, v in kw.items():
                setattr(self.state, k, v)

    def _notice(self, text: str, long: str = "") -> None:
        with self.lock:
            self.state.notice = text
            self.state.notice_long = long or text
            self.state.notice_id += 1

    # --- Sende-Wächter (0.10.46) -------------------------------------------------------
    def _start_guard(self) -> None:
        """Wächter-Prozess starten: schaltet auf Empfang, wenn GoGoHam beim Senden abstürzt
        oder hängt (rigctld merkt das nicht). Eigene Sitzung – Strg+C reißt ihn nicht mit."""
        import os
        import sys
        if self.listen_only or self.guard is not None:
            return
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pttguard.py")
        try:
            self.guard = subprocess.Popen(
                [sys.executable, "-I", script, self.client.host, str(self.client.port)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                start_new_session=True, close_fds=True)
            os.set_blocking(self.guard.stdout.fileno(), False)
        except (OSError, ValueError):
            self.guard = None

    def _guard_say(self, what: str) -> None:
        with self._guard_lock:
            g = self.guard
            if g is None or g.stdin is None:
                return
            try:
                g.stdin.write(what.encode("ascii") + b"\n")
                g.stdin.flush()
            except (OSError, ValueError):
                self.guard = None

    def alive(self) -> None:
        """Lebenszeichen der Oberfläche (z. B. QTimer jede Sekunde): Hängt sie beim Senden,
        schaltet der Wächter nach wenigen Sekunden auf Empfang."""
        self._guard_say("g")

    def _guard_poll(self) -> None:
        """Lebenszeichen schicken und lesen, ob der Wächter auf Empfang geschaltet hat."""
        g = self.guard
        if g is None:
            return
        now = time.monotonic()
        if now >= self._beat_next:
            self._beat_next = now + 1.0
            self._guard_say(".")
        try:
            data = g.stdout.read() if g.stdout else None
        except (OSError, ValueError):
            data = None
        if data and b"off" in data:
            with self.lock:
                self.state.ptt = False
                self.state.ptt_id += 1
            self._notice(tr("Sende-Wächter: GoGoHam hat beim Senden nicht reagiert – das "
                            "Funkgerät wurde auf Empfang geschaltet."))

    def _stop_guard(self, pending: bool = False) -> None:
        """Eingabe schließen: Wächter endet. pending=True: er schaltet erst noch auf Empfang
        (mehrere Versuche) – dann nicht abwürgen, sondern im Hintergrund auf ihn warten."""
        with self._guard_lock:
            g, self.guard = self.guard, None
        if g is None:
            return
        try:
            g.stdin.close()
        except (OSError, ValueError):
            pass
        if pending:
            threading.Thread(target=g.wait, daemon=True, name="pttguard-wait").start()
            return
        try:
            g.wait(2)
        except Exception:  # noqa: BLE001
            g.kill()

    def _idle(self) -> None:
        """Bis zur nächsten Abfrage warten – Lebenszeichen an den Wächter auch bei langen
        Abständen jede Sekunde."""
        end = time.monotonic() + self.poll
        while (left := end - time.monotonic()) > 0:
            if self._wake.wait(min(1.0, left)):
                return
            self._guard_poll()

    def run(self) -> None:
        retry_at = 0.0
        self._start_guard()
        while not self._halt.is_set():
            self._guard_poll()
            if not self.client.sock:
                if time.monotonic() < retry_at:
                    time.sleep(0.2)
                    continue
                try:
                    self.client.connect()
                    model = query_model(self.client.host, self.client.port)
                    self._set(connected=True, error="", model=model)
                    if self.state.ptt:                 # Verbindung war beim Senden weg
                        try:
                            self._ptt(False)
                        except RuntimeError:
                            pass
                        self._set(ptt=False)
                    self._wpm_ok, self._wpm_next = True, 0.0
                    self._mode_next = 0.0
                    self._tune_link(model)
                except OSError as e:
                    self._set(connected=False, error=tr("rigctld nicht erreichbar ({e})", e=e))
                    retry_at = time.monotonic() + 3
                    continue
            try:
                self._wake.clear()                     # vor dem Abholen: nichts geht verloren
                while True:
                    try:
                        name, args = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    if self.listen_only and name not in self.LISTEN_OK:
                        continue                       # doppelt gesichert
                    try:
                        if name == "ptt":
                            self._ptt(bool(args[0]))
                        else:
                            getattr(self.client, name)(*args)
                        if name == "set_keyspd":
                            self._wpm_next = 0.0       # neues Tempo gleich zurücklesen
                        if name == "ptt":
                            with self.lock:
                                self.state.ptt = bool(args[0])
                                self.state.ptt_id += 1
                    except RuntimeError as e:          # Gerät lehnt einen Befehl ab
                        if name == "ptt":
                            self._guard_say("0")
                            with self.lock:
                                self.state.ptt = False
                                self.state.ptt_id += 1
                        self._notice(command_notice(name, args, str(e)),
                                     command_notice_long(name, args))
                t0 = time.monotonic()
                freq = self.client.get_freq()
                self._learn(time.monotonic() - t0)
                mode = self.state.mode
                if time.monotonic() >= self._mode_next:
                    self._mode_next = time.monotonic() + self.MODE_EVERY
                    mode = self.client.get_mode() or mode
                self._set(connected=True, freq=freq, mode=mode, error="")
                self._poll_wpm(mode)
            except RuntimeError as e:
                self._set(error=str(e))
            except (OSError, ConnectionError, ValueError) as e:
                self.client.close()
                self._set(connected=False, error=tr("Verbindung verloren ({e})", e=e))
                retry_at = time.monotonic() + 2
                continue
            self._idle()
        if self.state.ptt and self.client.sock:     # nie im Senden stehen bleiben
            try:
                self._ptt(False)
            except (OSError, RuntimeError, ConnectionError):
                pass
        pending = bool(self.state.ptt)
        if pending:                                     # nicht sicher aus: Wächter übernimmt
            self._guard_say("1")
        self._stop_guard(pending)
        self.client.close()

    def _tune_link(self, model: int) -> None:
        """Nach dem Verbinden: Zwischenspeicher klein stellen (nur bei echtem rigctld, der sich
        mit seinem Modell meldet) und messen, wie schnell das Gerät antwortet."""
        if model:
            try:
                self.client.set_cache(0)
            except RuntimeError:
                pass                            # älteres Hamlib ohne set_cache
        times = []
        try:
            for _ in range(5):
                t0 = time.monotonic()
                self.client.get_freq()
                times.append(time.monotonic() - t0)
        except (RuntimeError, ValueError):
            times = times or [0.0]
        if model:
            try:
                self.client.set_cache(self.CACHE_MS)
            except RuntimeError:
                pass
        times.sort()
        self._q_avg = times[len(times) // 2]
        self._learn(None)

    def _learn(self, dt: float | None) -> None:
        """Abfragedauer mitteln; im Automatik-Betrieb den Abstand danach richten (das
        2,5-Fache – so bleibt die Schnittstelle frei, z. B. für WSJT-X)."""
        if dt is not None:
            self._q_avg = 0.8 * self._q_avg + 0.2 * dt if self._q_avg else dt
        if self.auto:
            self.poll = min(self.MAX_POLL, max(self.MIN_POLL, 2.5 * self._q_avg))
        with self.lock:
            self.state.query_ms = round(self._q_avg * 1000, 1)
            self.state.poll_ms = int(round(self.poll * 1000))

    def _ptt(self, on: bool) -> None:
        """Senden ein/aus – immer über rigctld (der schaltet je nach Einstellung CAT oder DTR/RTS).
        Der Sende-Wächter erfährt „Senden“ VOR dem Befehl und „Empfang“ erst, wenn er durch ist."""
        if on:
            self._guard_say("1")
        self.client.ptt(on)
        if not on:
            self._guard_say("0")

    def _poll_wpm(self, mode: str) -> None:
        """CW-Tempo lesen – nur in CW und nur alle paar Sekunden (Drehknopf am Gerät)."""
        if not self._wpm_ok or not (mode or "").upper().startswith("CW"):
            return
        if time.monotonic() < self._wpm_next:
            return
        self._wpm_next = time.monotonic() + 3.0
        try:
            self._set(wpm=self.client.get_keyspd())
        except (RuntimeError, ValueError, IndexError):
            self._wpm_ok = False             # Gerät kann es nicht – nicht weiter fragen
            self._set(wpm=0)


def command_notice(name: str, args: tuple, error: str) -> str:
    """Verständlicher Hinweis, wenn das Funkgerät einen Befehl ablehnt."""
    if name == "send_voice_mem":                # kurz fürs Meldefeld (0.8.12.9)
        return tr("Sprachspeicher {n} ist leer – am Funkgerät aufnehmen (IC-7300: VOICE)",
                  n=args[0] if args else "?")
    if name == "set_keyspd":
        return tr("Das Funkgerät hat das CW-Tempo {n} WpM abgelehnt", n=args[0] if args else "?")
    if name == "ptt":
        # seit 0.10.45 geht auch PTT über DTR/RTS über rigctld – also nicht nur „über CAT“
        return tr("Das Funkgerät hat das Umschalten auf Senden abgelehnt")
    if name == "send_morse":
        return tr("Das Funkgerät hat den CW-Text abgelehnt – steht es auf CW?")
    return error


def command_notice_long(name: str, args: tuple) -> str:
    """Ausführliche Fassung für die untere Statuszeile und den Tooltip ("" = wie die kurze)."""
    if name == "send_voice_mem":
        return tr("Das Funkgerät hat Sprachspeicher {n} abgelehnt – ist dort etwas aufgenommen? "
                  "(IC-7300: VOICE-Taste, Speicher aufnehmen)", n=args[0] if args else "?")
    return ""


def start_rigctld(model: int, device: str, baud: int, port: int = 4532,
                  extra: str = "") -> subprocess.Popen:
    exe = shutil.which("rigctld")
    if not exe:
        raise FileNotFoundError(tr("rigctld nicht gefunden – bitte Hamlib installieren "
                                "(sudo pacman -S hamlib)"))
    from . import handybridge
    device = handybridge.resolve(device)    # GoGoHandy-Brücke hält das Gerät (0.10.40)
    cmd = [exe, "-m", str(model), "-r", device, "-s", str(baud), "-t", str(port)]
    if extra.strip():
        cmd += extra.split()
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
