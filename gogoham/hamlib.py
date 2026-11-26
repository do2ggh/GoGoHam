"""Hamlib befragen: Geräteliste, Fähigkeiten eines Geräts, Schnittstellen, Verbindungstest.

Alles hier ist **nur lesend** – es wird nie gesendet (kein PTT, kein CW, kein
Sprachspeicher). Der Verbindungstest liest einmal Frequenz und Mode.

Die Daten kommen direkt aus dem installierten Hamlib (``rigctl -l`` und
``rigctl -m <Nr> --dump-caps``). Kommt mit einem Hamlib-Update ein neues Gerät
dazu, steht es automatisch in der Liste.
"""

from __future__ import annotations

from .i18n import tr

import glob
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache

from .bands import BANDS

STANDARD_BAUDS = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]

STATUS_DE = {
    "Stable": "",
    "Beta": tr("Beta – in Hamlib noch nicht ganz ausgereift"),
    "Alpha": tr("Alpha – in Hamlib noch in Entwicklung, eher unzuverlässig"),
    "Untested": tr("in Hamlib ungetestet"),
    "Buggy": tr("in Hamlib als fehlerhaft bekannt"),
}


@dataclass
class RigModel:
    model: int
    mfg: str
    name: str
    status: str = "Stable"

    @property
    def label(self) -> str:
        return f"{self.mfg} – {self.name}"


@dataclass
class RigCaps:
    model: int
    name: str = ""
    mfg: str = ""
    status: str = ""
    port_type: str = ""
    speed_min: int = 0
    speed_max: int = 0
    tx_ranges: list[tuple[int, int]] = field(default_factory=list)
    can_morse: bool = False
    can_voice: bool = False

    @property
    def serial(self) -> bool:
        """Serielle/USB-Schnittstelle (sonst z. B. Netzwerk wie FLRig, NET rigctl)."""
        return self.port_type.upper().startswith(("RS-232", "SERIAL", "USB"))

    def bauds(self) -> list[int]:
        if not self.speed_max:
            return list(STANDARD_BAUDS)
        lo = self.speed_min or 0
        out = [b for b in STANDARD_BAUDS if lo <= b <= self.speed_max]
        return out or list(STANDARD_BAUDS)

    def bands(self) -> list[str]:
        """Bänder, auf denen das Gerät laut Hamlib senden kann (leer = unbekannt)."""
        if not self.tx_ranges:
            return []
        return [name for name, lo, hi in BANDS
                if any(a <= hi and b >= lo for a, b in self.tx_ranges)]


def rigctl_exe() -> str | None:
    return shutil.which("rigctl")


# Zeile aus "rigctl -l":  "  3073  Icom   IC-7300   20250517.14   Stable   RIG_MODEL_IC7300"
_LIST_RE = re.compile(r"^\s*(\d+)\s+(.+?)\s{2,}(.+?)\s{2,}(\S+)\s+(\S+)\s+(RIG_MODEL_\S+)\s*$")


def parse_list(text: str) -> list[RigModel]:
    out = []
    for line in text.splitlines():
        m = _LIST_RE.match(line)
        if m:
            out.append(RigModel(int(m.group(1)), m.group(2).strip(), m.group(3).strip(),
                                m.group(5)))
    out.sort(key=lambda r: (r.mfg.lower(), r.name.lower()))
    return out


@lru_cache(maxsize=1)
def list_rigs() -> tuple[RigModel, ...]:
    exe = rigctl_exe()
    if not exe:
        return ()
    try:
        r = subprocess.run([exe, "-l"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ()
    return tuple(parse_list(r.stdout))


def find_model(model: int) -> RigModel | None:
    return next((r for r in list_rigs() if r.model == model), None)


def filter_rigs(rigs, text: str) -> list[RigModel]:
    """Suche: alle Wörter müssen in „Hersteller Modell Nummer“ vorkommen (ohne Bindestriche)."""
    words = [w for w in re.split(r"\s+", text.lower().replace("-", "")) if w]
    if not words:
        return list(rigs)
    out = []
    for r in rigs:
        hay = f"{r.mfg} {r.name} {r.model}".lower().replace("-", "")
        if all(w in hay for w in words):
            out.append(r)
    return out


_RANGE_RE = re.compile(r"^\s+(\d+) Hz - (\d+) Hz\s*$")


def parse_caps(model: int, text: str) -> RigCaps:
    caps = RigCaps(model)
    in_tx = False
    for line in text.splitlines():
        key, _, val = line.partition(":")
        val = val.strip()
        if line.startswith("Model name:"):
            caps.name = val
        elif line.startswith("Mfg name:"):
            caps.mfg = val
        elif line.startswith("Backend status:"):
            caps.status = val
        elif line.startswith("Port type:"):
            caps.port_type = val
        elif line.startswith("Serial speed:"):
            m = re.search(r"(\d+)\.\.(\d+)", val)
            if m:
                caps.speed_min, caps.speed_max = int(m.group(1)), int(m.group(2))
        elif line.startswith("Can send Morse:"):
            caps.can_morse = val.upper().startswith("Y")
        elif line.startswith("Can send Voice:"):
            caps.can_voice = val.upper().startswith("Y")
        if re.match(r"^(TX|RX) ranges #\d+ for", line):
            in_tx = line.startswith("TX") and "status" not in line
            continue
        if line and not line.startswith(("\t", " ")):
            in_tx = False
        if in_tx:
            m = _RANGE_RE.match(line)
            if m:
                rng = (int(m.group(1)), int(m.group(2)))
                if rng not in caps.tx_ranges:
                    caps.tx_ranges.append(rng)
    return caps


@lru_cache(maxsize=64)
def rig_caps(model: int) -> RigCaps | None:
    exe = rigctl_exe()
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-m", str(int(model)), "--dump-caps"], capture_output=True,
                           text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if "Model name:" not in r.stdout:
        return None
    return parse_caps(int(model), r.stdout)


def builtin_serial_ports(sys_dir: str = "/sys/class/tty", dev_dir: str = "/dev") -> list[str]:
    """Eingebaute COM-Schnittstellen (ttyS), die es wirklich gibt (0.8.22). Linux legt immer
    ttyS0–ttyS31 an; echte Hardware hat einen UART-Typ ungleich 0."""
    out = []
    for t in sorted(glob.glob(os.path.join(sys_dir, "ttyS*")),
                    key=lambda x: int(re.sub(r"\D", "", os.path.basename(x)) or 0)):
        try:
            with open(os.path.join(t, "type")) as f:
                if int(f.read().strip() or 0) == 0:
                    continue
        except (OSError, ValueError):
            continue
        dev = os.path.join(dev_dir, os.path.basename(t))
        if os.path.exists(dev):
            out.append(dev)
    return out


def serial_ports() -> list[str]:
    """Angeschlossene serielle/USB-Schnittstellen, feste Namen (by-id) zuerst; dann USB-Namen,
    eingebaute COM-Schnittstellen (ttyS) und Bluetooth (rfcomm)."""
    by_id = sorted(glob.glob("/dev/serial/by-id/*"))
    seen = {os.path.realpath(p) for p in by_id}
    plain = [p for p in sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
             if os.path.realpath(p) not in seen]
    return by_id + plain + builtin_serial_ports() + sorted(glob.glob("/dev/rfcomm*"))


def port_problem(path: str) -> str:
    """Typische Linux-Hürden vor dem Öffnen (0.8.22): fehlt, keine Berechtigung. "" = ok."""
    if not path or ":" in path and not path.startswith("/"):
        return ""                                       # Netzwerk (Rechner:Port)
    if not os.path.exists(path):
        return tr("Schnittstelle {p} gibt es nicht (mehr) – ist das Kabel/der Adapter "
                  "eingesteckt?", p=path)
    if not os.access(path, os.R_OK | os.W_OK):
        return access_hint(path)
    return ""


def access_hint(path: str) -> str:
    import grp
    try:
        group = grp.getgrgid(os.stat(path).st_gid).gr_name
    except (KeyError, OSError):
        group = "uucp"
    from . import permissions
    if permissions.member_not_active(group):
        return tr("Keine Berechtigung für {p}: Du bist schon in der Gruppe „{g}“, aber erst nach "
                  "dem nächsten Anmelden gilt das – bitte einmal ab- und wieder anmelden.",
                  p=path, g=group)
    if permissions.uaccess_supported():
        return tr("Keine Berechtigung für {p}. Knopf „Berechtigung einrichten“ gibt die "
                  "USB-Geräte frei – sofort, ohne neu anmelden. (Oder im Terminal: {cmd} – "
                  "danach ab- und wieder anmelden.)", p=path, cmd=permissions.command(group))
    return tr("Keine Berechtigung für {p}. Linux erlaubt Schnittstellen nur Mitgliedern der "
              "Gruppe „{g}“. Knopf „Berechtigung einrichten“ – oder im Terminal: {cmd} – danach "
              "ab- und wieder anmelden.", p=path, g=group, cmd=permissions.command(group))


def explain_error(err: str, path: str = "") -> str:
    """Rohe Hamlib-/Linux-Fehlermeldung in einen verständlichen Hinweis übersetzen."""
    low = (err or "").lower()
    if "permission denied" in low:
        return access_hint(path) if path else tr("Keine Berechtigung für die Schnittstelle "
                                                 "(Gruppe uucp bzw. dialout).")
    if "resource busy" in low or "device or resource busy" in low:
        return tr("Die Schnittstelle wird gerade von einem anderen Programm benutzt (z. B. "
                  "WSJT-X, flrig oder ein rigctld) – bitte dieses schließen.")
    if "no such file" in low:
        return tr("Schnittstelle {p} gibt es nicht (mehr) – ist das Kabel/der Adapter "
                  "eingesteckt?", p=path or "?")
    return ""


def port_hint(path: str) -> str:
    """Kurzer Hinweis zu einer Schnittstelle (z. B. Yaesu mit zwei Anschlüssen)."""
    p = os.path.basename(path)
    if "CP2105" in p or "Dual" in p:
        if "if00" in p:
            return tr("erster Anschluss (bei Yaesu meist „Enhanced“ = CAT)")
        if "if01" in p:
            return tr("zweiter Anschluss (bei Yaesu meist „Standard“ = PTT/Tasten)")
    return ""


@dataclass
class TestResult:
    ok: bool
    text: str


def test_connection(model: int, device: str, baud: int, extra: str = "",
                    timeout: float = 8.0) -> TestResult:
    """Einmal Frequenz und Mode lesen – **liest nur**, sendet nie."""
    exe = rigctl_exe()
    if not exe:
        return TestResult(False, tr("rigctl nicht gefunden – bitte Hamlib installieren"))
    problem = port_problem(device)
    if problem:
        return TestResult(False, problem)
    from . import handybridge
    device = handybridge.resolve(device)    # GoGoHandy-Brücke hält das Gerät (0.10.40)
    cmd = [exe, "-m", str(int(model))]
    if device:
        cmd += ["-r", device]
    if baud:
        cmd += ["-s", str(int(baud))]
    if extra.strip():
        cmd += extra.split()
    cmd += ["f", "m"]                       # get_freq, get_mode
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return TestResult(False, tr("Keine Antwort vom Funkgerät (Zeitüberschreitung). "
                                 "Stimmen Schnittstelle und Baudrate? Ist das Gerät an?"))
    except OSError as e:
        return TestResult(False, tr("rigctl ließ sich nicht starten: {e}", e=e))
    lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    if r.returncode != 0 or not lines or not lines[0].isdigit():
        err = (r.stderr.strip().splitlines() or [tr("unbekannter Fehler")])[-1]
        nice = explain_error(r.stderr, device)
        if nice:
            return TestResult(False, nice)
        return TestResult(False, tr("Keine Verbindung: {err}", err=err) + " " + tr(
            "Ältere Geräte über ein Interface: Baudrate wie im Gerätemenü? Braucht das Interface "
            "Strom über DTR/RTS (→ Erweiterte Einstellungen)?"))
    hz = int(lines[0])
    mode = lines[1] if len(lines) > 1 else "?"
    from .i18n import num
    khz = num(hz / 1000, 2)
    return TestResult(True, tr("Verbindung in Ordnung: {khz} kHz, {mode}", khz=khz, mode=mode))


def _read_via_rigctld(host: str, port: int, timeout: float = 8.0) -> TestResult:
    """Frequenz/Mode über einen laufenden rigctld lesen (Hamlib „NET rigctl“, Modell 2)."""
    return test_connection(2, f"{host}:{int(port)}", 0, timeout=timeout)


def test_profile(prof: dict, timeout: float = 8.0) -> TestResult:
    """Verbindungstest für ein Geräte-Profil – **liest nur**, sendet nie.

    * „Vorhandenen rigctld benutzen“: fragt den rigctld auf Rechner:Port, prüft das Gerät.
    * „GoGoHam startet rigctld selbst“: ist der Port belegt, wird der laufende rigctld
      gefragt (GoGoHam würde ihn mitbenutzen); sonst direkt über die Schnittstelle.
    """
    from .rig import port_in_use, query_model
    host, port = prof.get("host", "127.0.0.1"), int(prof.get("port", 4532))
    want = int(prof["model"])
    if port_in_use(host, port):
        res = _read_via_rigctld(host, port, timeout)
        if not res.ok:
            return res
        got = query_model(host, port)
        r = find_model(got) if got else None
        name = r.name if r else (f"Hamlib {got}" if got else "unbekannt")
        note = "" if prof.get("start", True) is False else \
            tr(" – auf diesem Port läuft schon ein rigctld, GoGoHam benutzt ihn mit")
        if got and got != want:
            w = find_model(want)
            return TestResult(False, tr("Auf {host}:{port} antwortet ein {name}, das Profil ist aber für "
                                        "{p7}. Port prüfen!", host=host, port=port, name=name, p7=w.name if w else want))
        return TestResult(True, tr("{text_} · Gerät: {name}{note}", text_=res.text, name=name, note=note))
    if not prof.get("start", True) and not prof.get("service"):
        # (Hintergrund-rigctld von GoGoHam noch nicht eingerichtet: direkt testen, siehe unten)
        return TestResult(False, tr("Auf {host}:{port} läuft kein rigctld. Läuft der Dienst? Oder "
                                    "„GoGoHam startet rigctld selbst“ wählen.", host=host, port=port))
    from .rigprofiles import conn, device, full_extra
    if conn(prof) == "icom":
        return test_icom(prof, timeout=max(timeout, 15.0))
    return test_connection(want, device(prof), int(prof.get("baud") or 0),
                           full_extra(prof), timeout)



def icom_message(state: str, text: str = "") -> str:
    """Meldung der Icom-Brücke als Text für die Anzeige ("" = nichts Besonderes)."""
    if state == "error-auth":
        return tr("Benutzername oder Passwort falsch (im Funkgerät unter Netzwerk → "
                  "Fernsteuerung/Network User eingetragen).")
    if state == "error-refused":
        return tr("Das Funkgerät lehnt die Verbindung ab – kurz aus- und wieder einschalten.")
    if state == "busy":
        return tr("Das Funkgerät ist gerade mit einem anderen Programm verbunden: {text}", text=text)
    if state == "error-rigctld":
        return tr("rigctld nicht gefunden – bitte Hamlib installieren.")
    if state == "sound-missing":
        return tr("Ton übers Netz nicht möglich: kein Tonsystem (PipeWire/PulseAudio) erreichbar.")
    if state == "reconnect":
        return tr("Verbindung zum Funkgerät unterbrochen – verbinde neu …")
    return ""


def wait_icom(proc, port: int, timeout: float, in_use=None) -> tuple[bool, str]:
    """Auf den rigctld der Icom-Brücke warten. (bereit?, Fehlermeldung)."""
    import json
    import select
    import time
    from .rig import port_in_use
    in_use = in_use or port_in_use
    end = time.monotonic() + timeout
    seen_any = False
    while time.monotonic() < end:
        if proc.poll() is not None and not in_use("127.0.0.1", port):
            break
        r, _w, _x = select.select([proc.stdout], [], [], 0.2)
        if r:
            line = proc.stdout.readline()
            try:
                msg = json.loads(line)
            except ValueError:
                msg = {}
            st = msg.get("state", "")
            seen_any = seen_any or st in ("authenticated", "radio")
            text = icom_message(st, msg.get("text", ""))
            if st.startswith("error") or st == "busy":
                return False, text
        if in_use("127.0.0.1", port):
            return True, ""
    if not seen_any:
        return False, tr("Das Funkgerät antwortet nicht. Stimmt die Adresse? Ist im Funkgerät "
                         "die Netzwerk-Fernsteuerung eingeschaltet?")
    return False, tr("Keine Verbindung zum Funkgerät (Zeit abgelaufen).")


def test_icom(prof: dict, timeout: float = 15.0, starter=None) -> TestResult:
    """Verbindungstest Icom über LAN/WLAN: Brücke kurz starten, über rigctld lesen."""
    from . import icomlan
    from .rig import port_in_use
    from .rigprofiles import full_extra
    if not prof.get("net_host"):
        return TestResult(False, tr("Bitte die Adresse des Funkgeräts eintragen."))
    port = int(prof.get("port", 4532))
    if port_in_use("127.0.0.1", port):
        return TestResult(False, tr("Port {port} ist schon belegt – läuft GoGoHam mit diesem "
                                    "Profil? Dann dort testen.", port=port))
    starter = starter or icomlan.start_bridge
    tprof = dict(prof, net_audio=False)               # für den Test ohne Soundkarte
    proc = starter(tprof, port, full_extra(prof))
    try:
        ok, text = wait_icom(proc, port, timeout)
        if not ok:
            return TestResult(False, text)
        res = _read_via_rigctld("127.0.0.1", port, 8.0)
        if res.ok:
            return TestResult(True, tr("{text_} · über das Netzwerk", text_=res.text))
        return res
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except Exception:  # noqa: BLE001
            proc.kill()


def ptt_test(prof: dict, seconds: float = 1.0, client_factory=None, starter=None,
             in_use=None, ptt_type=None) -> TestResult:
    """PTT kurz ein und **sicher wieder aus** – das Gerät SENDET dabei!

    Nur nach Zustimmung im Moment aufrufen (Knopf „PTT testen“ mit Rückfrage). Läuft für das
    Profil noch kein rigctld, wird er nur für den Test gestartet und danach beendet.
    """
    import time
    from .rig import RigctldClient, port_in_use, start_rigctld
    client_factory = client_factory or (lambda h, p: RigctldClient(h, p, timeout=3.0))
    starter = starter or start_rigctld
    in_use = in_use or port_in_use
    host, port = prof.get("host", "127.0.0.1"), int(prof.get("port", 4532))
    proc = None
    note = ""
    running = in_use(host, port)
    from .rigprofiles import ptt_args
    if running and ptt_args(prof) and host in ("127.0.0.1", "localhost"):
        # 0.10.45: PTT über DTR/RTS schaltet der rigctld – der laufende kennt sie evtl. noch nicht
        from .rigdetect import ptt_type_on_port
        have = (ptt_type or ptt_type_on_port)(port)
        if have and have != prof["ptt_line"]:
            note = tr(" · Achtung: Der laufende rigctld auf Port {port} sendet noch über CAT, "
                      "nicht über {line} – erst nach „OK“ (bei einem fremden rigctld: dort "
                      "„--ptt-type={line}“ ergänzen).", port=port, line=prof["ptt_line"])
    if not running:
        if not prof.get("start", True) and not prof.get("service"):
            return TestResult(False, tr("Auf {host}:{port} läuft kein rigctld. Läuft der Dienst? Oder "
                                        "„GoGoHam startet rigctld selbst“ wählen.", host=host, port=port))
        host = "127.0.0.1"
        try:
            from .rigprofiles import conn, device, full_extra
            if conn(prof) == "icom":
                from . import icomlan
                proc = icomlan.start_bridge(dict(prof, net_audio=False), port, full_extra(prof))
                ok, text = wait_icom(proc, port, 15.0, in_use)
                if not ok:
                    proc.terminate()
                    return TestResult(False, text)
            else:
                proc = starter(int(prof["model"]), device(prof), int(prof.get("baud") or 0),
                               port, full_extra(prof))
        except (OSError, FileNotFoundError) as e:
            return TestResult(False, tr("rigctld konnte nicht starten: {e}", e=e))
        end = time.monotonic() + 5
        while not in_use(host, port) and time.monotonic() < end:
            time.sleep(0.1)
    c = client_factory(host, port)
    state = None
    try:
        try:
            c.command("T 1")
        except (OSError, RuntimeError, ConnectionError) as e:
            return TestResult(False, tr("PTT ließ sich nicht einschalten: {e}", e=e))
        time.sleep(seconds)
        try:
            state = c.command("t")[0].strip()
        except (OSError, RuntimeError, ConnectionError, IndexError):
            state = None
    finally:
        _ptt_off(c, client_factory, host, port)
        if proc:
            proc.terminate()
            try:
                proc.wait(2)
            except Exception:  # noqa: BLE001
                proc.kill()
    if state == "1":
        return TestResult(True, tr("PTT in Ordnung: Das Gerät ging auf Senden und wieder auf Empfang.") + note)
    if state == "0":
        return TestResult(False, tr("Der Befehl wurde angenommen, aber das Gerät meldet kein Senden – "
                                    "PTT-Einstellungen im Gerät prüfen.") + note)
    return TestResult(True, tr("PTT wurde ein- und wieder ausgeschaltet (das Gerät meldet seinen "
                               "Zustand nicht zurück – bitte am Gerät schauen).") + note)


def _ptt_off(c, client_factory, host: str, port: int) -> None:
    """PTT aus – notfalls über eine neue Verbindung nochmal versuchen."""
    for attempt in range(3):
        try:
            if attempt:
                c.close()
                c = client_factory(host, port)
            c.command("T 0")
            break
        except Exception:  # noqa: BLE001
            continue
    try:
        c.close()
    except Exception:  # noqa: BLE001
        pass
