"""fldigi für RTTY (ab 0.10.5, ab 0.10.6: gefunkt wird in fldigi, geloggt in GoGoHam).

GoGoHam richtet fldigi vor jedem Start selbst ein – alles, was Verbindung und RTTY-Betrieb
betrifft: Funkgerät über rigctld, PTT über CAT, Soundkarte, Rufzeichen, Locator, RTTY 45,45/170,
Weitergabe geloggter QSOs per UDP und Contest-Makros. Über XML-RPC (127.0.0.1:7362) liest
GoGoHam das Rufzeichenfeld mit, setzt die laufende Nummer und beendet fldigi wieder.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import xmlrpc.client
from pathlib import Path

XMLRPC_HOST = "127.0.0.1"
XMLRPC_PORT = 7362
HAMLIB_NET_RIGCTL = 2          # Hamlib-Modell „NET rigctl“
BACKUP_SUFFIX = ".gogoham-original.bak"


FLATPAK_ID = "com.w1hkj.fldigi"


def config_dir(home: str | None = None, flatpak: bool | None = None) -> Path:
    """Einstellungsordner – beim Flatpak von Flathub (0.10.14) unter ~/.var/app/…/.fldigi."""
    h = Path(home or os.path.expanduser("~"))
    if flatpak is None:
        from .extapps import flatpak_installed
        flatpak = flatpak_installed(FLATPAK_ID, str(h))
    return h / ".var" / "app" / FLATPAK_ID / ".fldigi" if flatpak else h / ".fldigi"


def def_path(home: str | None = None) -> Path:
    return config_dir(home) / "fldigi_def.xml"


def installed(which=shutil.which) -> str | None:
    return which("fldigi")


def _esc(v: str) -> str:
    return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wanted(host: str, port: int, mycall: str = "", locator: str = "", tx: str = "afsk",
           fsk_port: str = "", fsk_line: str = "DTR", txatten: float | None = None) -> dict[str, str]:
    """Die Einstellungen, die GoGoHam in fldigi_def.xml einträgt (Name -> Wert)."""
    w = {
        # Funkgerät über rigctld (dasselbe Profil wie in GoGoHam), PTT über CAT
        "CHKUSEHAMLIBIS": "1", "CHKUSERIGCATIS": "0", "CHKUSEXMLRPCIS": "0",
        "CLIENT_TO_FLRIG": "0", "FLRIG_FSK": "0",
        "HAMRIGMODEL": str(HAMLIB_NET_RIGCTL), "HAMRIGNAME": "NET rigctl",
        "HAMRIGDEVICE": f"{host}:{port}", "HAMLIBCMDPTT": "1",
        "RIGCATCMDPTT": "0", "RTSPTT": "0", "DTRPTT": "0",
        # RTTY wie im Contest üblich: 45,45 Baud, 170 Hz, 5 Bit (Baudot), 1,5 Stoppbits
        "RTTYSHIFT": "3", "RTTYBAUD": "1", "RTTYBITS": "0", "RTTYSTOP": "1",
        # Ton über PulseAudio/PipeWire; welche Soundkarte, sagt GoGoHam beim Start
        "AUDIOIO": "2", "PULSESERVER": "",
        # GoGoHam beendet fldigi ohne Rückfrage
        "CONFIRMEXIT": "0",
        # FSK über eine Steuerleitung (sonst Ton über die Soundkarte = AFSK)
        "USEFSK": "1" if tx == "fsk" else "0", "PSEUDOFSK": "0",
        "FSK_PORT": fsk_port if tx == "fsk" else "",
        "FSK_ON_DTR": "1" if fsk_line.upper() == "DTR" else "0",
        "FSK_SHARES_PORT": "0", "FSK_REVERSE": "0", "FSK_STOPBITS": "1",
    }
    if txatten is not None:                  # eingemessener Sendepegel (0.10.7)
        w["TXATTEN"] = f"{float(txatten):g}"
        w["TXLEVEL_BY_MODE"] = "0"
    if mycall:
        w["MYCALL"] = mycall.upper()
    if locator:
        w["MYLOC"] = locator.upper()
    return w


_TAG = re.compile(r"<([A-Za-z0-9_]+)>(.*?)</\1>")


def current(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    return {m.group(1): m.group(2) for m in _TAG.finditer(text)}


def changes(path: Path, want: dict[str, str]) -> list[tuple[str, str, str]]:
    """(Name, bisher, neu) für alles, was nicht schon stimmt."""
    cur = current(path)
    return [(k, cur.get(k, ""), v) for k, v in want.items() if cur.get(k) != _esc(v)]


def apply(path: Path, want: dict[str, str]) -> Path | None:
    """Einstellungen eintragen. Beim ersten Ändern wird der Stand von vorher als
    „fldigi_def.xml.gogoham-original.bak“ aufgehoben (Rückgabe: deren Pfad, sonst None)."""
    todo = {k: _esc(v) for k, v in want.items()}
    if path.is_file():
        text = path.read_text(encoding="utf-8", errors="surrogateescape")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "<FLDIGI_DEFS>\n</FLDIGI_DEFS>\n"
    cur = current(path) if path.is_file() else {}
    if all(cur.get(k) == v for k, v in todo.items()):
        return None
    backup = None
    if path.is_file():
        b = path.with_name(path.name + BACKUP_SUFFIX)
        if not b.exists():
            shutil.copy2(path, b)
            backup = b

    def repl(m: re.Match) -> str:
        k = m.group(1)
        return f"<{k}>{todo.pop(k)}</{k}>" if k in todo else m.group(0)
    text = _TAG.sub(repl, text)
    if todo:                                  # fehlende Einträge vor dem Schluss-Tag
        extra = "".join(f"<{k}>{v}</{k}>\n" for k, v in todo.items())
        i = text.rfind("</FLDIGI_DEFS>")
        text = text[:i] + extra + text[i:] if i >= 0 else text + extra
    tmp = path.with_name(path.name + ".gogoham-tmp")
    tmp.write_text(text, encoding="utf-8", errors="surrogateescape")
    os.replace(tmp, path)
    return backup


def logging_settings(udp_port: int) -> dict[str, str]:
    """fldigi schickt jedes geloggte QSO als ADIF an GoGoHam; Contest-Felder (Rufzeichen, RST,
    Austausch, Nummer) anzeigen; nach dem Loggen Felder leeren."""
    return {"ENABLE_UDP_LOGGING": "1", "UDP_LOG_ADDRESS": "127.0.0.1",
            "UDP_LOG_PORT": str(udp_port), "LOGGING": "1", "CLEARONSAVE": "1",
            "FIXED599": "1", "USELEADINGZEROS": "1", "CONTESTDIGITS": "3"}


# ------------------------------------------------------------------ Contest-Makros
MACRO_HEADER = ("//fldigi macro definition file extended\n"
                "// Von GoGoHam für den Contest angelegt. Die vorherigen Makros liegen in\n"
                "// macros.mdf.gogoham-original.bak.\n")


def macros_path(home: str | None = None) -> Path:
    return config_dir(home) / "macros" / "macros.mdf"


def contest_macros(exch: str) -> list[tuple[str, str]]:
    """(Beschriftung, Makrotext) für die ersten acht fldigi-Tasten. ``exch`` = eigener
    Austausch, laufende Nummer als <CNTR>. Nach jedem Text zurück auf Empfang (<RX>)."""
    x = " ".join(exch.split())
    ex2 = f"{x} {x}" if x else ""
    return [
        ("CQ", "<TX>\nCQ TEST <MYCALL> <MYCALL> CQ\n<RX>"),
        ("EXCH", f"<TX>\n<CALL> 599 {ex2} <CALL>\n<RX>".replace("  ", " ")),
        ("TU+LOG", "<TX>\nTU <MYCALL> TEST\n<RX><LOG><INCR>"),
        ("MYCALL", "<TX>\n<MYCALL> <MYCALL>\n<RX>"),
        ("599+LOG", f"<TX>\nTU 599 {ex2}\n<RX><LOG><INCR>".replace("  ", " ")),
        ("AGN", "<TX>\nAGN AGN\n<RX>"),
        ("NR?", "<TX>\nNR? NR?\n<RX>"),
        ("CALL?", "<TX>\nCALL? CALL?\n<RX>"),
    ]


def write_macros(path: Path, exch: str) -> Path | None:
    """Contest-Makros schreiben; die Makros von vorher werden beim ersten Mal als
    „macros.mdf.gogoham-original.bak“ aufgehoben (Rückgabe: deren Pfad, sonst None)."""
    from .levelcal import level_macros
    macros = list(enumerate(contest_macros(exch)))
    macros += [(i, (label, body)) for i, label, body in level_macros()]  # fürs Einmessen
    text = MACRO_HEADER + "".join(f"\n// Macro # {i}\n/$ {i} {label}\n{body}\n"
                                  for i, (label, body) in macros)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.is_file():
        if path.read_text(encoding="utf-8", errors="replace") == text:
            return None
        b = path.with_name(path.name + BACKUP_SUFFIX)
        if not b.exists():
            shutil.copy2(path, b)
            backup = b
    tmp = path.with_name(path.name + ".gogoham-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return backup


# ------------------------------------------------------------------ Soundkarte
def _run(args: list[str], timeout: float = 5) -> tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return -1, ""


def source_for_sink(sink: str, run=_run) -> str:
    """Zur Ausgabe „alsa_output.usb-…-00.analog-stereo“ den passenden Eingang derselben
    Soundkarte finden ("" = nicht gefunden)."""
    if not sink.startswith("alsa_output."):
        return ""
    card = sink[len("alsa_output."):].rsplit(".", 1)[0]
    names = None
    if run is _run:                       # 0.10.30.1: direkt über libpulse, pactl als Notweg
        from . import pulse
        devs = pulse.devices("sources")
        names = [n for n, _c in devs] if devs is not None else None
    if names is None:
        code, out = run(["pactl", "list", "short", "sources"])
        if code != 0:
            return ""
        names = [ln.split("\t")[1] for ln in out.splitlines() if "\t" in ln]
    exact = [n for n in names if n == "alsa_input." + sink[len("alsa_output."):]]
    if exact:
        return exact[0]
    same = [n for n in names if n.startswith("alsa_input." + card + ".")]
    return same[0] if same else ""


def environment(sink: str, run=_run, base: dict | None = None) -> dict[str, str]:
    """Umgebung für fldigi: PulseAudio/PipeWire soll die Soundkarte des Funkgeräts nehmen."""
    env = dict(os.environ if base is None else base)
    env["LC_NUMERIC"] = "C"          # sonst meldet fldigi Zahlen mit Komma („145000000,0“)
    if sink:
        env["PULSE_SINK"] = sink
        src = source_for_sink(sink, run)
        if src:
            env["PULSE_SOURCE"] = src
    return env


def running(run=_run) -> bool:
    return run(["pgrep", "-x", "fldigi"])[0] == 0


# ------------------------------------------------------------------ Fernsteuerung
class _Transport(xmlrpc.client.Transport):
    def __init__(self, timeout: float):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class Client:
    """Dünne Hülle um die XML-RPC-Befehle von fldigi."""

    def __init__(self, host: str | None = None, port: int | None = None, timeout: float = 2.0):
        host, port = host or XMLRPC_HOST, port or XMLRPC_PORT     # Tests stellen den Port um
        self.proxy = xmlrpc.client.ServerProxy(f"http://{host}:{port}/RPC2",
                                               transport=_Transport(timeout), allow_none=True)
        self.rx_pos = 0

    def version(self) -> str:
        return str(self.proxy.fldigi.version())

    def set_rtty(self) -> None:
        self.proxy.modem.set_by_name("RTTY")

    def modem(self) -> str:
        return str(self.proxy.modem.get_name())

    def terminate(self) -> None:
        self.proxy.fldigi.terminate(0)       # 0 = nichts zusätzlich speichern

