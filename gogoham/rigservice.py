"""rigctld dauerhaft im Hintergrund – von GoGoHam eingerichtet (seit 0.8.17).

Pro Profil mit „GoGoHam richtet rigctld dauerhaft ein“ legt GoGoHam einen **systemd-
Benutzerdienst** an (``~/.config/systemd/user/gogoham-rigctld-<Port>.service``). Er läuft ab
der Anmeldung, auch wenn GoGoHam zu ist – WSJT-X & Co. (Hamlib NET rigctl, Rechner:Port)
funktionieren also weiter. Kein Passwort nötig, weil es ein Dienst des Benutzers ist.

Der Dienst benutzt den festen Schnittstellen-Namen (/dev/serial/by-id/…): ein anderes Gerät
an „ttyUSB0“ wird nie mit dem falschen Modell angesprochen. Fehlt das Gerät, wartet rigctld
auf seinem Port; stürzt er ab, startet systemd ihn nach 5 s neu.

``take_over`` hält einen fremden rigctld an, der eine Schnittstelle blockiert (nur nach
ausdrücklicher Zustimmung im Fenster): einen Systemdienst über ``systemctl`` (Linux zeigt dann
selbst ein Passwortfenster), einen Benutzerdienst oder ein eigenes Programm ohne Passwort.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import signal
import subprocess
import time

from . import handybridge
from .i18n import tr

PREFIX = "gogoham-rigctld-"


def unit_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "systemd", "user")


def unit_name(port: int) -> str:
    return f"{PREFIX}{int(port)}.service"


def _run(cmd: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def system_rigctld(path: str | None = None) -> str:
    """rigctld des Systems – nie der aus dem AppImage (dessen Pfad ändert sich bei jedem Start).

    Im AppImage (Umgebung APPDIR, nur für Beta-Tester) wird der mitgelieferte rigctld übersprungen;
    "" = kein eigenes Hamlib auf dem System.
    """
    appdir = os.environ.get("APPDIR", "")
    for d in (path if path is not None else os.environ.get("PATH", "")).split(os.pathsep):
        exe = os.path.join(d, "rigctld")
        if not d or not os.access(exe, os.X_OK):
            continue
        if appdir and os.path.realpath(exe).startswith(os.path.realpath(appdir) + os.sep):
            continue
        return exe
    return ""


def available(run=_run) -> bool:
    """Gibt es einen systemd-Benutzerdienst-Manager (fast alle Distributionen)?

    Im AppImage zusätzlich nur, wenn das System ein eigenes Hamlib (rigctld) hat.
    """
    if not shutil.which("systemctl"):
        return False
    if os.environ.get("APPDIR") and not system_rigctld():
        return False
    r = run(["systemctl", "--user", "is-system-running"], 10)
    return (r.stdout or "").strip() in ("running", "degraded", "starting")


def _quote(arg: str) -> str:
    arg = arg.replace("%", "%%")                        # systemd: % ist ein Platzhalter
    if any(c in arg for c in " \t\"'\\;"):
        return '"' + arg.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return arg


def has_units(directory: str | None = None) -> bool:
    return bool(glob.glob(os.path.join(directory or unit_dir(), PREFIX + "*.service")))


_SAFE = re.compile(r"[\w@+=:,./-]+")


def _bridge_exec(prof: dict, cmd: list[str]) -> str:
    """Icom an fester Schnittstelle (0.10.40): läuft die GoGoHandy-Brücke, nimmt rigctld deren
    virtuelle Schnittstelle (Handy und PC gleichzeitig), sonst wie bisher das Gerät. "" = normal."""
    from .rigprofiles import conn
    dev = cmd[cmd.index("-r") + 1]
    link = handybridge.link_name(dev)
    if conn(prof) != "usb" or int(prof["model"]) // 1000 != 3 or not link \
            or not all(_SAFE.fullmatch(a) for a in cmd + [link]):
        return ""
    args = " ".join('"$D"' if a == dev else a for a in cmd)
    return f"/bin/sh -c 'D={link}; [ -e \"$D\" ] || D={dev}; exec {args}'"


def unit_text(prof: dict, exe: str | None = None) -> str:
    exe = exe or system_rigctld() or "/usr/bin/rigctld"
    from .rigprofiles import device
    cmd = [exe, "-m", str(int(prof["model"])), "-r", device(prof),
           "-s", str(int(prof.get("baud") or 0)), "-t", str(int(prof["port"]))]
    if not int(prof.get("baud") or 0):
        del cmd[5:7]
    from .rigprofiles import full_extra
    cmd += full_extra(prof).split()                 # 0.8.22: samt DTR/RTS, CI-V-Adresse
    name = (prof.get("name") or "").replace("\n", " ")
    shared = _bridge_exec(prof, cmd)
    return ("# Von GoGoHam angelegt – wird beim Speichern der Funkgerät-Einstellungen\n"
            "# überschrieben oder gelöscht. Bitte in GoGoHam ändern, nicht hier.\n"
            "[Unit]\n"
            f"Description=GoGoHam rigctld {name} (Port {int(prof['port'])})\n"
            + (f"After={handybridge.UNIT}\n" if shared else "") + "\n"
            "[Service]\n"
            f"ExecStart={shared or ' '.join(_quote(a) for a in cmd)}\n"
            "Restart=always\nRestartSec=5\n\n"
            "[Install]\nWantedBy=default.target\n")


# --- Regel A (0.10.43): pro Port und Gerät genau EIN rigctld ---------------------------------
# GoGoHam, GoGoHome und GoGoHandy teilen sich die Geräte. Hat schon ein anderer Dienst (z. B. der
# an das System übergebene rigctld-4534 oder rigctld-4532 mit Brücken-Drop-in) den Port oder das
# Gerät, legt GoGoHam keinen zweiten an, sondern benutzt ihn mit.
SYSTEM_DIRS = ("/etc/systemd/user", "/etc/systemd/system")
_PORT = re.compile(r"(?:\s-t\s*|\s--port[= ])(\d+)")
_DEV = re.compile(r"/(?:dev|run)/[^\s'\";]+")


def _exec_source(path: str) -> tuple[str, str]:
    """(Datei, ExecStart-Wert) der gültigen Zeile samt Drop-ins (die letzte nicht leere gewinnt)."""
    lines: list[tuple[str, str]] = []
    for f in [path] + sorted(glob.glob(path + ".d/*.conf")):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for ln in fh:
                    ln = ln.strip()
                    if ln.startswith("ExecStart="):
                        v = ln.split("=", 1)[1].strip()
                        lines = [] if not v else lines + [(f, v)]
        except OSError:
            continue
    return lines[-1] if lines else ("", "")


def _exec_line(path: str) -> str:
    """Gültige ExecStart-Zeile eines Dienstes samt Drop-ins (die letzte nicht leere gewinnt)."""
    return _exec_source(path)[1]


def foreign_units(directory: str | None = None, system_dirs=SYSTEM_DIRS) -> list[dict]:
    """Fremde rigctld-Dienste (nicht von GoGoHam angelegt): {unit, scope, port, devices}."""
    out = []
    for scope, d in [("user", directory or unit_dir())] + [
            ("user" if "user" in s else "system", s) for s in system_dirs]:
        for path in sorted(glob.glob(os.path.join(d, "*.service"))):
            unit = os.path.basename(path)
            if unit.startswith(PREFIX) or os.path.islink(path) and \
                    os.path.realpath(path) == "/dev/null":
                continue
            ex = _exec_line(path)
            if "rigctld" not in ex:
                continue
            m = _PORT.search(" " + ex)
            out.append({"unit": unit, "scope": scope, "port": int(m.group(1)) if m else 4532,
                        "devices": sorted(set(_DEV.findall(ex))), "path": path})
    return out


def _same_device(a: str, b: str) -> bool:
    """Gleiches Gerät – auch über die Brücke (gleicher by-id-Name) oder einen Verweis."""
    if not a or not b:
        return False
    if os.path.basename(a) == os.path.basename(b) and "by-id" in a + b:
        return True
    return os.path.realpath(a) == os.path.realpath(b)


def _active(u: dict, run) -> bool:
    flag = ["--user"] if u["scope"] == "user" else []
    for what in ("is-active", "is-enabled"):
        r = run(["systemctl", *flag, what, u["unit"]], 10)
        if (r.stdout or "").strip() in ("active", "activating", "enabled", "enabled-runtime"):
            return True
    return False


def foreign_for(prof: dict, units: list[dict], run=_run) -> dict | None:
    """Läuft (oder startet) schon ein fremder Dienst für Port oder Gerät dieses Profils?"""
    from .rigprofiles import device
    port, dev = int(prof["port"]), device(prof) if prof.get("device") else ""
    for u in units:
        if (u["port"] == port or any(_same_device(dev, d) for d in u["devices"])) and _active(u, run):
            return u
    return None


def sync(profiles: list[dict], run=_run, directory: str | None = None,
         notes: list[str] | None = None, system_dirs=SYSTEM_DIRS) -> list[str]:
    """Benutzerdienste an die Profile anpassen. Gibt Fehlermeldungen zurück (leer = alles gut).

    Nur geänderte Dienste werden neu gestartet (WSJT-X & Co. verlieren sonst kurz die Verbindung).
    Regel A (0.10.43): Hat ein fremder Dienst Port oder Gerät, wird er mitbenutzt (``notes``).
    """
    directory = directory or unit_dir()
    # Icom über LAN braucht die Brücke in GoGoHam, „anderer Rechner“ hat dort seinen rigctld
    want = {int(p["port"]): p for p in profiles
            if p and p.get("service") and p.get("conn", "usb") in ("usb", "net")}
    if want:
        units = foreign_units(directory, system_dirs)
        for port, prof in list(want.items()):
            u = foreign_for(prof, units, run)
            if u:
                del want[port]
                if notes is not None:
                    notes.append(tr("Port {port}: vorhandener Dienst {u} wird mitbenutzt.",
                                    port=port, u=u["unit"]))
    errors: list[str] = []
    existing = {os.path.basename(f) for f in glob.glob(os.path.join(directory, PREFIX + "*.service"))}
    gone = sorted(existing - {unit_name(p) for p in want})
    changed: list[str] = []
    for unit in gone:
        run(["systemctl", "--user", "disable", "--now", unit])
        try:
            os.remove(os.path.join(directory, unit))
        except OSError as e:
            errors.append(str(e))
    for port, prof in want.items():
        path = os.path.join(directory, unit_name(port))
        text = unit_text(prof)
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
                errors.append(str(e))
                continue
            changed.append(unit_name(port))
    if not (gone or changed or want):
        return errors
    run(["systemctl", "--user", "daemon-reload"])
    for port in want:
        unit = unit_name(port)
        if unit in changed:
            r = run(["systemctl", "--user", "enable", unit])
            r2 = run(["systemctl", "--user", "restart", unit])
        else:                                           # unverändert: nur sicherstellen, dass er läuft
            r = run(["systemctl", "--user", "enable", unit])
            r2 = run(["systemctl", "--user", "start", unit])
        for x in (r, r2):
            if x.returncode != 0:
                last = ((x.stderr or x.stdout or "").strip().splitlines() or ["?"])[-1]
                errors.append(tr("Hintergrund-rigctld {u}: {e}", u=unit, e=last))
                break
    return errors


# --- Fremden rigctld übernehmen -------------------------------------------------------------
def owner(pid: int, proc: str = "/proc") -> dict:
    """Wer hat den Prozess gestartet? {"kind": system|user|process, "unit", "uid"}."""
    unit, kind = "", "process"
    try:
        with open(os.path.join(proc, str(pid), "cgroup"), encoding="utf-8") as f:
            path = f.read().strip().splitlines()[-1].split(":", 2)[-1]
        segs = [s for s in path.split("/") if s]
        services = [s for s in segs if s.endswith(".service")]
        if services and not services[-1].startswith("user@"):
            unit = services[-1]
            kind = "user" if any(s.startswith("user@") for s in segs) else "system"
    except (OSError, IndexError):
        pass
    uid = -1
    try:
        with open(os.path.join(proc, str(pid), "status"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("Uid:"):
                    uid = int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return {"kind": kind, "unit": unit, "uid": uid}


def _gone(pid: int, proc: str, wait: float) -> bool:
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if not os.path.exists(os.path.join(proc, str(pid))):
            return True
        time.sleep(0.2)
    return not os.path.exists(os.path.join(proc, str(pid)))


def via_bridge(rd: dict, proc: str = "/proc", directory: str | None = None) -> bool:
    """Läuft dieser rigctld über die GoGoHandy-Brücke (pty) bzw. ist sein Dienst dafür
    eingerichtet (Drop-in, by-id der Brücke)? Dann nie abschalten – nur neu starten (Regel C)."""
    root = handybridge.root()
    if (rd.get("device") or "").startswith(root):
        return True
    o = owner(int(rd.get("pid") or 0), proc)
    if o["kind"] == "user" and o["unit"]:
        path = os.path.join(directory or unit_dir(), o["unit"])
        return "gogohandy" in _exec_line(path)
    return False


def restart(pid: int, run=_run, proc: str = "/proc") -> tuple[bool, str]:
    """Regel C (0.10.43): Hängt ein rigctld-Dienst ohne Gerät (z. B. vor der Brücke gestartet),
    wird er neu gestartet statt abgeschaltet. Nur Benutzerdienste (kein Passwort nötig).
    -> (ok, Dienstname)."""
    o = owner(pid, proc)
    if o["kind"] != "user" or not o["unit"] or o["uid"] != os.getuid():
        return False, ""
    r = run(["systemctl", "--user", "restart", o["unit"]], 30)
    return r.returncode == 0, o["unit"]


def take_over(pid: int, run=_run, proc: str = "/proc", kill=os.kill,
              wait: float = 6.0) -> tuple[bool, str]:
    """Fremden rigctld dauerhaft anhalten. -> (ok, Meldung). Nur nach Zustimmung aufrufen!"""
    o = owner(pid, proc)
    if o["kind"] == "system":
        cmd = ["systemctl", "disable", "--now", o["unit"]]
        r = run(cmd, 120)                               # Linux fragt selbst nach dem Passwort
        if r.returncode != 0 and shutil.which("pkexec"):
            r = run(["pkexec"] + cmd, 120)
        if r.returncode != 0:
            return False, tr("Der Dienst {u} ließ sich nicht anhalten (Passwort abgebrochen?).",
                             u=o["unit"])
    elif o["kind"] == "user" and o["uid"] == os.getuid():
        run(["systemctl", "--user", "disable", "--now", o["unit"]])
    elif o["uid"] == os.getuid():
        try:
            kill(pid, signal.SIGTERM)
        except OSError as e:
            return False, str(e)
    else:
        return False, tr("Der rigctld gehört einem anderen Benutzer und lässt sich von hier "
                         "nicht anhalten.")
    if not _gone(pid, proc, wait):
        return False, tr("Der rigctld läuft noch – bitte nochmal versuchen.")
    return True, o["unit"]


# --- Dienst ans System übergeben (0.8.23.5) ---------------------------------------------------
HANDOVER_NOTE = ("# Ursprünglich von GoGoHam eingerichtet und dann übergeben – GoGoHam ändert oder\n"
                 "# entfernt diesen Dienst nicht mehr. Andere Programme (Log-Programme, WSJT-X …)\n"
                 "# erreichen das Gerät weiter über den Port in der ExecStart-Zeile.\n")


def handover_name(unit: str) -> str:
    """gogoham-rigctld-4532.service -> rigctld-4532.service (gogoham-rotctld-… ebenso)."""
    return unit[len("gogoham-"):] if unit.startswith("gogoham-") else unit


def handover(unit: str, run=_run, directory: str | None = None) -> list[str]:
    """Einen GoGoHam-Benutzerdienst als eigenständigen Dienst weiterlaufen lassen: gleiche
    Befehlszeile, anderer Name – GoGoHams ``sync`` fasst ihn danach nicht mehr an. Kurze
    Unterbrechung (alter Dienst stoppt, neuer startet). Fehlermeldungen, leer = gut."""
    directory = directory or unit_dir()
    old = os.path.join(directory, unit)
    new_unit = handover_name(unit)
    try:
        with open(old, encoding="utf-8") as f:
            lines = f.read().splitlines(keepends=True)
    except OSError as e:
        return [str(e)]
    body = [ln for ln in lines if not ln.startswith("#")]
    body = [ln.replace("Description=GoGoHam ", "Description=") if ln.startswith("Description=")
            else ln for ln in body]
    errors: list[str] = []
    try:
        with open(os.path.join(directory, new_unit), "w", encoding="utf-8") as f:
            f.write(HANDOVER_NOTE + "".join(body))
    except OSError as e:
        return [str(e)]
    run(["systemctl", "--user", "disable", "--now", unit])
    try:
        os.remove(old)
    except OSError as e:
        errors.append(str(e))
    run(["systemctl", "--user", "daemon-reload"])
    r = run(["systemctl", "--user", "enable", "--now", new_unit])
    if r.returncode != 0:
        last = ((r.stderr or r.stdout or "").strip().splitlines() or ["?"])[-1]
        errors.append(tr("Dienst {u}: {e}", u=new_unit, e=last))
    return errors


# --- PTT-Leitung in einem mitbenutzten Dienst eintragen (0.10.46) -----------------------------
# Benutzt GoGoHam den rigctld eines anderen Dienstes mit (Regel A) und soll PTT über DTR/RTS
# gehen, muss DIESER rigctld die Leitung schalten – sonst senden weder GoGoHam noch WSJT-X & Co.
# darüber. Nur nach Rückfrage beim Nutzer, mit Sicherungskopie, Dienst startet kurz neu.
_RIGCTLD = re.compile(r"((?:^|(?<=[\s'\"]))(?:\S*/)?rigctld)(?=\s|$)")
_OLD_PTT = re.compile(r"\s(?:--ptt-type|--ptt-file)(?:=\S+|\s+[^\s'\"-]\S*)"
                      r"|\s-[Pp](?:\s+[^\s'\"-][^\s'\"]*|[^\s'\"]+)")
MARK = "# PTT-Leitung von GoGoHam eingetragen"


def ptt_exec(line: str, args: list[str]) -> str:
    """ExecStart-Wert mit diesen PTT-Optionen (alte PTT-Optionen raus). "" = kein rigctld drin."""
    m = _RIGCTLD.search(line)
    if not m or not args:
        return ""
    head, tail = line[:m.end()], _OLD_PTT.sub("", line[m.end():])
    return head + " " + " ".join(args) + tail


def ptt_in_unit(u: dict) -> str:
    """Welche PTT-Art steht im Dienst? "DTR"/"RTS"/…, "RIG" = keine Angabe (über CAT)."""
    line = _exec_source(u.get("path", ""))[1]
    m = re.search(r"(?:--ptt-type[= ]|\s-P\s*)([A-Za-z]+)", " " + line)
    return m.group(1).upper() if m else "RIG"


def add_ptt(u: dict, prof: dict, run=_run, stamp: str | None = None, which=shutil.which) -> list[str]:
    """PTT-Optionen des Profils in den Dienst ``u`` (aus foreign_units) schreiben und ihn neu
    starten. Sicherung ``<Datei>.gogoham-<Zeit>.bak`` daneben. Fehlermeldungen, leer = gut."""
    import tempfile
    from .rigprofiles import ptt_args
    args = ptt_args(prof)
    src, line = _exec_source(u.get("path", ""))
    new = ptt_exec(line, args) if src else ""
    if not new:
        return [tr("In {u} wurde keine rigctld-Zeile gefunden.", u=u.get("unit", "?"))]
    try:
        with open(src, encoding="utf-8") as f:
            old_text = f.read()
    except OSError as e:
        return [str(e)]
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    out, done = [], False
    for ln in old_text.splitlines(keepends=True):
        if ln.startswith(MARK):
            continue
        if not done and ln.strip() == "ExecStart=" + line:
            out.append(f"{MARK} ({stamp}; Sicherung: {os.path.basename(src)}.gogoham-{stamp}.bak)\n")
            out.append("ExecStart=" + new + "\n")
            done = True
            continue
        out.append(ln)
    if not done:
        return [tr("In {u} wurde keine rigctld-Zeile gefunden.", u=u.get("unit", "?"))]
    text, bak, unit = "".join(out), f"{src}.gogoham-{stamp}.bak", u["unit"]
    user_cmds = [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "restart", unit]]
    tmp = None
    if u.get("scope") == "user" and os.access(os.path.dirname(src) or ".", os.W_OK):
        try:
            shutil.copy2(src, bak)
            with open(src, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            return [str(e)]
        cmds = user_cmds
    else:            # unter /etc: Schreiben über pkexec (fragt nach dem Passwort)
        if not which("pkexec"):
            return [tr("Für den Dienst {u} fehlt pkexec – bitte von Hand ändern.", u=unit)]
        fd, tmp = tempfile.mkstemp(prefix="gogoham-ptt-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        script = 'cp -p "$1" "$2" && cp "$3" "$1" && chmod 644 "$1"'
        if u.get("scope") == "system":
            script += ' && systemctl daemon-reload && systemctl restart "$4"'
        cmds = [["pkexec", "/bin/sh", "-c", script, "sh", src, bak, tmp, unit]]
        if u.get("scope") != "system":                 # /etc/systemd/user: als Benutzer neu starten
            cmds += user_cmds
    errors = []
    try:
        for c in cmds:
            r = run(c, 120)
            if r.returncode != 0:
                last = ((r.stderr or r.stdout or "").strip().splitlines() or ["?"])[-1]
                errors.append(tr("Dienst {u}: {e}", u=unit, e=last))
                break
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return errors
