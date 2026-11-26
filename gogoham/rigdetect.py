"""Funkgerät an einer Schnittstelle erkennen (Knopf „Gerät erkennen“, seit 0.8.16).

Reihenfolge:
1. Läuft schon ein rigctld für diese Schnittstelle (z. B. Systemdienst)? Dann wird die
   Schnittstelle **nicht** angefasst – Modell, Baudrate und Port kommen aus dessen
   Befehlszeile (/proc), das Profil benutzt den vorhandenen rigctld mit.
2. Hält ein anderes Programm die Schnittstelle offen (soweit sichtbar)? Dann auch nicht
   abfragen, nur den USB-Namen auswerten.
3. Sonst vorsichtig fragen „Wer bist du?“ – nacheinander mit den üblichen Baudraten:
   Icom CI-V „Transceiver-ID lesen“ (19 00) und Kenwood/Elecraft/Yaesu „ID;“.
   **Nur lesende Befehle.** DTR/RTS werden gleich nach dem Öffnen abgeschaltet (manche
   Geräte tasten darüber), und keines der gesendeten Bytes ist bei alten Yaesu-Geräten
   mit 5-Byte-Befehlen ein Sende-Befehl (0x08 = PTT, 0x0F/0x8F = Ein/Aus).
4. Antwortet nichts, hilft eventuell der USB-Name (z. B. „…IC-7300…“).

Die Kennungen stammen aus den CAT-Anleitungen der Hersteller. Echt getestet ist nur
das IC-7300. Alle Werte bleiben im Profil änderbar.
"""

from __future__ import annotations

import glob
import os
import re
import time
from dataclasses import dataclass

from .i18n import tr

# Icom: Antwort auf „19 00“ = Standard-CI-V-Adresse des Geräts
ICOM_IDS = {
    0x94: "IC-7300", 0xA4: "IC-705", 0xA2: "IC-9700", 0x98: "IC-7610", 0xAC: "IC-905",
    0x88: "IC-7100", 0x7A: "IC-7600", 0x80: "IC-7410", 0x7C: "IC-9100", 0x70: "IC-7000",
    0x76: "IC-7200", 0x74: "IC-7700", 0x6A: "IC-7800", 0x8E: "IC-7851", 0x96: "IC-R8600",
    0x5E: "IC-718", 0x66: "IC-746PRO", 0x6E: "IC-756PROIII",
}
# Kenwood (3 Ziffern) und Yaesu (4 Ziffern): Antwort auf „ID;“
KENWOOD_IDS = {"019": "TS-2000", "020": "TS-480", "021": "TS-590S", "022": "TS-990S",
               "023": "TS-590SG", "024": "TS-890S"}
YAESU_IDS = {"0310": "FT-950", "0251": "FT-2000", "0362": "FTDX-5000", "0460": "FTDX-3000",
             "0583": "FTDX-1200", "0570": "FT-991", "0650": "FT-891", "0681": "FTDX-101D",
             "0682": "FTDX-101MP", "0761": "FTDX-10", "0800": "FT-710", "0670": "FT-991A"}
# Geräte ohne eigenes Hamlib-Modell: Anzeige-Name -> Hamlib-Name (0.8.24.1)
HAMLIB_ALIAS = {"FT-991A": "FT-991"}
# „ID017;“ melden Elecraft K3/K3S/KX3/K4 (und das alte TS-570) – nicht eindeutig
AMBIGUOUS_IDS = {"017": "Elecraft"}
# Geräte, die ihren Namen im USB-Namen tragen
USB_NAMES = ["IC-7300", "IC-7610", "IC-9700", "IC-705", "IC-905", "IC-7100", "IC-R8600"]

# 0.8.22: 2400 und 1200 für alte Geräte (z. B. frühe Icom/Kenwood über Interface) zuletzt
PROBE_BAUDS = [115200, 19200, 38400, 9600, 57600, 4800, 2400, 1200]
CIV_QUERY = bytes([0xFE, 0xFE, 0x00, 0xE0, 0x19, 0x00, 0xFD])
CAT_QUERY = b";ID;"          # „;“ davor räumt Reste (z. B. die Icom-Frage) im Gerät weg
# Das FT-991A versteht das leere „;“ nicht, antwortet „?;“ und verwirft die Frage –
# dann noch einmal ohne „;“ davor fragen (0.8.24.1)
CAT_QUERY_PLAIN = b"ID;"


@dataclass
class Detection:
    ok: bool
    text: str
    name: str = ""              # Gerätename wie in Hamlib (z. B. "IC-7300")
    model: int = 0              # Hamlib-Modell, 0 = nicht eindeutig
    baud: int = 0               # 0 = unbekannt (Dialog nimmt dann den Hamlib-Höchstwert)
    device: str = ""
    search: str = ""            # bei unklarem Ergebnis: Suchbegriff für die Geräteliste
    rigctld_port: int = 0       # > 0: vorhandenen rigctld auf diesem Port mitbenutzen
    blocker: dict | None = None  # fremder rigctld hält die Schnittstelle, Gerät antwortet ihm nicht
    bridge: bool = False        # über die GoGoHandy-Brücke erkannt (0.10.40)


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_]", "", s).upper()


def hamlib_model(name: str, rigs=None) -> int:
    """Hamlib-Modellnummer zu einem Gerätenamen (Bindestriche/Leerzeichen egal), 0 = fehlt."""
    if rigs is None:
        from .hamlib import list_rigs
        rigs = list_rigs()
    want = _norm(HAMLIB_ALIAS.get(name, name))
    return next((r.model for r in rigs if _norm(r.name) == want), 0)


# --- Antworten auswerten ---------------------------------------------------------------
def parse_civ(data: bytes) -> int | None:
    """Geräte-ID aus einer CI-V-Antwort „FE FE E0 <von> 19 00 <id> FD“ (Echo wird übersprungen)."""
    for m in re.finditer(rb"\xfe\xfe(.)(.)\x19\x00(.)\xfd", data, re.S):
        if m.group(2) != b"\xe0":           # nicht das eigene Echo
            return m.group(3)[0]
    return None


def parse_cat(data: bytes) -> str | None:
    m = re.search(rb"ID(\d{3,4});", data)
    return m.group(1).decode() if m else None


def usb_guess(path: str) -> str:
    base = _norm(os.path.basename(path))
    # längste Namen zuerst, damit IC-7300 nicht als IC-730… o. Ä. endet
    return next((n for n in sorted(USB_NAMES, key=len, reverse=True) if _norm(n) in base), "")


# --- Belegte Schnittstelle ---------------------------------------------------------------
def _args_of(argv: list[str], short: str, long: str) -> str:
    for i, a in enumerate(argv):
        if a == short and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(short) and len(a) > 2 and not a.startswith("--"):
            return a[2:]
        if a.startswith(long + "="):
            return a.split("=", 1)[1]
        if a == long and i + 1 < len(argv):
            return argv[i + 1]
    return ""


def running_rigctld(path: str, proc: str = "/proc") -> dict | None:
    """Läuft ein rigctld für diese Schnittstelle? -> {"model", "baud", "port"} aus der Befehlszeile."""
    want = os.path.realpath(path)
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return None
    for pid in pids:
        try:
            with open(os.path.join(proc, pid, "cmdline"), "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if not argv or os.path.basename(argv[0]) != "rigctld":
            continue
        dev = _args_of(argv, "-r", "--rig-file")
        if not dev or os.path.realpath(dev) != want:
            continue
        def num(s: str, default: int = 0) -> int:
            return int(s) if s.isdigit() else default
        return {"pid": int(pid), "device": dev, "model": num(_args_of(argv, "-m", "--model")),
                "baud": num(_args_of(argv, "-s", "--serial-speed")),
                "port": num(_args_of(argv, "-t", "--port"), 4532)}
    return None


def ptt_type_on_port(port: int, proc: str = "/proc") -> str | None:
    """Wie schaltet der rigctld auf diesem Port PTT? "DTR"/"RTS"/… aus --ptt-type, "RIG" ohne
    Angabe (= über CAT), None = kein rigctld mit diesem Port gefunden (0.10.45)."""
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return None
    for pid in pids:
        try:
            with open(os.path.join(proc, pid, "cmdline"), "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if not argv or os.path.basename(argv[0]) != "rigctld":
            continue
        p = _args_of(argv, "-t", "--port")
        if (int(p) if p.isdigit() else 4532) != int(port):
            continue
        return (_args_of(argv, "-P", "--ptt-type") or "RIG").upper()
    return None


def stable_name(path: str) -> str:
    """Festen Namen aus /dev/serial/by-id/ bevorzugen (ttyUSB-Nummern wechseln beim Umstecken)."""
    if path.startswith("/dev/serial/by-id/"):
        return path
    real = os.path.realpath(path)
    for p in sorted(glob.glob("/dev/serial/by-id/*")):
        if os.path.realpath(p) == real:
            return p
    return path


def _verify_rigctld(port: int) -> bool:
    """Antwortet das Gerät dem laufenden rigctld? (liest einmal Frequenz/Mode)"""
    from .hamlib import _read_via_rigctld
    return _read_via_rigctld("127.0.0.1", port, 4.0).ok


def port_held(path: str, proc: str = "/proc") -> bool:
    """Hat ein (für uns sichtbares) Programm die Schnittstelle offen?"""
    want = os.path.realpath(path)
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit() and int(p) != os.getpid()]
    except OSError:
        return False
    for pid in pids:
        fd_dir = os.path.join(proc, pid, "fd")
        try:
            for fd in os.listdir(fd_dir):
                if os.path.realpath(os.path.join(fd_dir, fd)) == want:
                    return True
        except OSError:
            continue                        # fremde Prozesse (z. B. root) sind nicht lesbar
    return False


# --- Abfrage über die Schnittstelle ------------------------------------------------------
def serial_exchange(path: str, baud: int, data: bytes, wait: float = 0.3, rts: bool = False,
                    power: frozenset = frozenset()) -> bytes:
    """Schnittstelle öffnen, DTR/RTS aus, ``data`` schicken, bis ``wait`` Sekunden lesen.

    ``rts=True`` nur für den ersten Yaesu-Anschluss (CAT): dort ist RTS die Freigabe für CAT
    („CAT RTS = ON“ ab Werk), PTT liegt bei Yaesu auf dem zweiten Anschluss.
    ``power`` (0.8.22): Leitungen ({"DTR", "RTS"}), die der Nutzer in den erweiterten
    Einstellungen für die Versorgung des Interfaces eingeschaltet hat – nur dann an.
    """
    import fcntl
    import select
    import struct
    import termios
    speed = getattr(termios, f"B{int(baud)}")
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        bits = struct.pack("I", termios.TIOCM_DTR | termios.TIOCM_RTS)

        def lines_off():
            try:
                fcntl.ioctl(fd, termios.TIOCMBIC, bits)    # DTR/RTS aus
            except OSError:
                pass                                       # Schnittstelle ohne DTR/RTS
        lines_off()
        a = termios.tcgetattr(fd)
        a[0] = 0                                           # iflag: roh
        a[1] = 0                                           # oflag
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL  # 8N1, kein HUPCL/CRTSCTS
        a[3] = 0                                           # lflag
        a[4] = a[5] = speed
        termios.tcsetattr(fd, termios.TCSANOW, a)
        lines_off()
        on = (termios.TIOCM_DTR if "DTR" in power else 0) | \
            (termios.TIOCM_RTS if ("RTS" in power or rts) else 0)
        if on:
            try:
                fcntl.ioctl(fd, termios.TIOCMBIS, struct.pack("I", on))
            except OSError:
                pass                                   # Schnittstelle ohne DTR/RTS
            time.sleep(0.2 if power else 0.05)         # Interface braucht kurz zum Anlaufen
        termios.tcflush(fd, termios.TCIOFLUSH)
        os.write(fd, data)
        out = b""
        end = time.monotonic() + wait
        while (left := end - time.monotonic()) > 0:
            r, _, _ = select.select([fd], [], [], left)
            if not r:
                break
            chunk = os.read(fd, 256)
            if not chunk:
                break
            out += chunk
        return out
    finally:
        os.close(fd)


def _passes(bauds, rts_retry: bool):
    for baud in bauds:
        yield baud, False
    if rts_retry:                       # 2. Runde: erster Yaesu-Anschluss mit RTS, nur „ID;“
        for baud in bauds:
            yield baud, True


def _ask_cat(exchange, path: str, baud: int, wait: float, **kw) -> str | None:
    """„ID;“-Frage; antwortet das Gerät nur „?;“ (FT-991A), ohne „;“ davor wiederholen."""
    data = exchange(path, baud, CAT_QUERY, wait, **kw)
    cat = parse_cat(data)
    if cat is None and b"?;" in data:
        cat = parse_cat(exchange(path, baud, CAT_QUERY_PLAIN, wait, **kw))
    return cat


def probe(path: str, exchange=serial_exchange, bauds=PROBE_BAUDS, progress=None,
          rts_retry: bool = False, power: frozenset = frozenset()) -> Detection:
    """Gerät an der Schnittstelle fragen – nur lesende Befehle."""
    kw = {"power": power} if power else {}
    for baud, rts in _passes(bauds, rts_retry):
        if progress:
            progress(baud)
        try:
            if rts:
                civ, cat = None, _ask_cat(exchange, path, baud, 0.4, rts=True, **kw)
            else:
                civ = parse_civ(exchange(path, baud, CIV_QUERY, 0.25, **kw))
                cat = None if civ is not None else _ask_cat(exchange, path, baud, 0.3, **kw)
        except OSError as e:
            from .hamlib import explain_error
            nice = explain_error(str(e), path)
            return Detection(False, nice or tr("Schnittstelle ließ sich nicht öffnen: {e}", e=e),
                             device=path)
        if civ is not None:
            name = ICOM_IDS.get(civ, "")
            if not name:
                return Detection(False, tr("Ein Icom-Gerät antwortet (CI-V-Adresse {a}), das Modell "
                                           "ist aber unbekannt – bitte selbst wählen.",
                                           a=f"0x{civ:02X}"), baud=baud, device=path, search="Icom")
            return Detection(True, "", name=name, baud=baud, device=path)
        if cat is not None:
            name = KENWOOD_IDS.get(cat) or YAESU_IDS.get(cat, "")
            if name:
                return Detection(True, "", name=name, baud=baud, device=path)
            hint = AMBIGUOUS_IDS.get(cat, "")
            return Detection(False, tr("Ein Gerät antwortet (Kennung ID{i}), das Modell ist aber nicht "
                                       "eindeutig – bitte selbst wählen.", i=cat),
                             baud=baud, device=path, search=hint)
    return Detection(False, tr("Keine Antwort. Ist das Gerät eingeschaltet und die CAT-Schnittstelle "
                               "im Menü des Geräts eingeschaltet? Ältere Geräte (z. B. FT-817/857/"
                               "897, ältere Icom und Kenwood) melden ihren Namen nicht – dann "
                               "Funkgerät und Baudrate von Hand wählen und „Verbindung testen“. "
                               "Interface mit Strom über DTR/RTS? → Erweiterte Einstellungen."),
                     device=path)


def detect(path: str, rigs=None, exchange=serial_exchange, proc: str = "/proc",
           progress=None, verify=_verify_rigctld, wk_guard: bool = True,
           power: frozenset = frozenset()) -> Detection:
    """Gerät an einer Schnittstelle erkennen – sendet nie (kein PTT, kein CW).

    ``wk_guard``: Könnte dort ein WinKey hängen (z. B. DXP), erst fragen, ob er es ist – ein
    WinKey würde die CAT-Fragen sonst als CW senden (0.8.18.1).
    """
    from .hamlib import find_model, port_hint
    if not path:
        return Detection(False, tr("Keine Schnittstelle gefunden – ist das Gerät per USB angeschlossen?"))
    if not os.path.exists(path):
        return Detection(False, tr("Schnittstelle {p} gibt es nicht (mehr).", p=path), device=path)
    if not os.access(path, os.R_OK | os.W_OK):
        from .hamlib import access_hint
        return Detection(False, access_hint(path), device=path)
    if "if01" in os.path.basename(path) and port_hint(path):
        return Detection(False, tr("Das ist der zweite Anschluss (PTT/Tasten). Für die Erkennung "
                                   "bitte den ersten Anschluss wählen."), device=path)
    path = stable_name(path)
    from . import handybridge
    via = handybridge.pty_for(path, proc=proc)    # GoGoHandy-Brücke hält das Gerät (0.10.40)
    rd = running_rigctld(path, proc) or (running_rigctld(via, proc) if via else None)
    if rd:
        r = find_model(rd["model"]) if rd["model"] else None
        name = r.name if r else ""
        # Nie blind glauben: antwortet das Gerät dem rigctld wirklich?
        if not verify(rd["port"]):
            return Detection(False, tr("An dieser Schnittstelle läuft ein rigctld für {m}, aber das "
                                       "Gerät antwortet ihm nicht – vermutlich hängt dort jetzt ein "
                                       "anderes Gerät.", m=name or tr("ein anderes Gerät")),
                             device=path, blocker=rd)
        return Detection(bool(rd["model"]), "" if rd["model"] else
                         tr("Für diese Schnittstelle läuft schon ein rigctld, sein Modell ist aber "
                            "unbekannt."), name=name, model=rd["model"], baud=rd["baud"],
                         device=path, rigctld_port=rd["port"])
    guess = usb_guess(path)
    if via:
        # über die virtuelle Schnittstelle der Brücke: nur CI-V, Baudrate dort egal – die Brücke
        # spricht fest mit 115200 zum Gerät; im Profil bleibt das echte Gerät stehen
        det = probe(via, exchange, bauds=[handybridge.BAUD], progress=progress)
        det.device = path
        if det.ok:
            det.baud, det.bridge = handybridge.BAUD, True
        elif not det.search:
            det.text = tr("Die GoGoHandy-Brücke hält das Gerät, es antwortet über sie aber nicht – "
                          "ist das Funkgerät eingeschaltet?")
        held = False
    else:
        held = port_held(path, proc)
    if not via and wk_guard and not held:
        from . import dxp, winkey
        if dxp.maybe_winkey(path) and winkey.probe(path):
            return Detection(False, tr("Das ist ein WinKey-Anschluss (CW-Geber, z. B. am microHAM "
                                       "DXP) – für CAT bitte einen anderen Anschluss wählen, den "
                                       "WinKey bei „CW senden über“."), device=path)
    if via:
        pass
    elif held:
        if guess:
            det = Detection(True, "", name=guess, device=path)
        else:
            return Detection(False, tr("Die Schnittstelle wird gerade von einem anderen Programm "
                                       "benutzt – bitte dieses kurz schließen."), device=path)
    else:
        yaesu_cat = "if00" in os.path.basename(path) and bool(port_hint(path))
        det = probe(path, exchange, progress=progress, rts_retry=yaesu_cat, power=power)
        if not det.ok and guess and not det.search:
            det = Detection(True, "", name=guess, device=path)
    if det.ok and not det.model:
        det.model = hamlib_model(det.name, rigs)
        if not det.model:
            return Detection(False, tr("Erkannt: {n} – das installierte Hamlib kennt es aber nicht.",
                                       n=det.name), name=det.name, baud=det.baud, device=path)
    return det


def describe(det: Detection) -> str:
    """Kurzer Text fürs Fenster."""
    if not det.ok:
        return det.text
    parts = [tr("Erkannt: {n}", n=det.name or f"Hamlib {det.model}")]
    if det.baud:
        parts.append(tr("{b} Baud", b=det.baud))
    if det.rigctld_port:
        parts.append(tr("läuft schon über rigctld (Port {p}) – wird mitbenutzt", p=det.rigctld_port))
    if det.bridge:
        parts.append(tr("über die GoGoHandy-Brücke (Handy und PC gleichzeitig)"))
    return " · ".join(parts)
