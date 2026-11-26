"""Soundkarte des Funkgeräts finden (ab 0.10.9).

Viele Funkgeräte (z. B. IC-7300, FT-991A, IC-705) haben eine eingebaute USB-Soundkarte
(„USB Audio CODEC“). Sie hängt im Funkgerät am selben kleinen USB-Verteiler wie die
CAT-Schnittstelle. Daran erkennt GoGoHam, welche Soundkarte zu welchem Funkgerät gehört –
auch wenn mehrere Funkgeräte angeschlossen sind.

Andere Funkgeräte (z. B. FT-891) haben keine eigene Soundkarte; der Ton läuft dort über ein
Ton-Interface an der DATA-Buchse. Das wählt man einmal im Funkgeräte-Profil aus.

Namen: PulseAudio/PipeWire-Namen („alsa_output.usb-…“). Diese Namen benutzen auch WS
(SoundOutName/SoundInName) und fldigi (über PULSE_SINK/PULSE_SOURCE).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_USB_DEV = re.compile(r"^\d+-[\d.]+$")          # USB-Gerät, z. B. „5-4.1“ (nicht „usb5“, nicht „5-4.1:1.0“)


def _run(args: list[str], timeout: float = 5) -> tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return -1, ""


def _usb_device(path: Path) -> Path | None:
    """Vom sysfs-Pfad einer Schnittstelle zum USB-Gerät hochgehen („…/5-4/5-4.1“)."""
    for p in (path, *path.parents):
        if _USB_DEV.match(p.name):
            return p
    return None


def _hub(usb_dev: Path) -> Path | None:
    """Der Verteiler, an dem das Gerät hängt – None, wenn es direkt am Rechner steckt
    (dann gehören andere Geräte dort nicht zum Funkgerät)."""
    parent = usb_dev.parent
    return parent if _USB_DEV.match(parent.name) else None


def serial_usb_device(device: str, sysfs: str = "/sys") -> Path | None:
    """USB-Gerät zur CAT-Schnittstelle (/dev/serial/by-id/…, /dev/ttyUSB0 …)."""
    if not device:
        return None
    try:
        name = Path(os.path.realpath(device)).name          # → ttyUSB0 / ttyACM0
    except OSError:
        return None
    tty = Path(sysfs) / "class" / "tty" / name / "device"
    try:
        real = Path(os.path.realpath(tty))
    except OSError:
        return None
    return _usb_device(real) if real.exists() else None


def cards(sysfs: str = "/sys") -> list[tuple[int, str, Path]]:
    """(Nummer, Name, USB-Gerät) aller USB-Soundkarten."""
    out = []
    for c in sorted(Path(sysfs, "class", "sound").glob("card*")):
        m = re.fullmatch(r"card(\d+)", c.name)
        if not m:
            continue
        try:
            real = Path(os.path.realpath(c / "device"))
        except OSError:
            continue
        dev = _usb_device(real)
        if dev is None:
            continue
        name = ""
        for f in (c / "id", dev / "product"):
            try:
                name += " " + f.read_text(errors="replace").strip()
            except OSError:
                pass
        out.append((int(m.group(1)), name.strip(), dev))
    return out


def card_for_device(device: str, sysfs: str = "/sys") -> int | None:
    """Nummer der eingebauten Soundkarte des Funkgeräts an dieser CAT-Schnittstelle –
    None, wenn keine eindeutig dazugehört (dann lieber nicht raten)."""
    dev = serial_usb_device(device, sysfs)
    hub = _hub(dev) if dev is not None else None
    if hub is None:
        return None
    same = [(n, name) for n, name, d in cards(sysfs) if d.parent == hub]
    if len(same) != 1:
        return None
    n, name = same[0]
    # Nur die typische Funkgeräte-Soundkarte – ein USB-Headset am selben Tisch-Verteiler
    # soll nicht als „Soundkarte des Funkgeräts“ durchgehen.
    return n if "CODEC" in name.upper() else None


def _blocks(text: str, head: str) -> list[dict[str, str]]:
    """`pactl list sinks|sources` in Blöcke zerlegen: Name + alsa.card."""
    out: list[dict[str, str]] = []
    for ln in text.splitlines():
        s = ln.strip()
        if ln.startswith(head):
            out.append({})
        elif out and s.startswith("Name:"):
            out[-1]["name"] = s.split(":", 1)[1].strip()
        elif out and s.startswith("alsa.card ="):
            out[-1]["card"] = s.split("=", 1)[1].strip().strip('"')
    return out


def pulse_names(card: int, run=_run) -> tuple[str, str]:
    """(Ausgang, Eingang) in PulseAudio/PipeWire zur ALSA-Karte – "" = nicht gefunden.

    Ab 0.10.30.1 direkt über libpulse; pactl nur noch als Notweg (oder in Tests über run)."""
    if run is _run:
        from . import pulse
        sinks, sources = pulse.devices("sinks"), pulse.devices("sources")
        if sinks is not None and sources is not None:
            pick = [next((n for n, c in devs if c == str(card) and not n.endswith(".monitor")), "")
                    for devs in (sinks, sources)]
            return pick[0], pick[1]
    res = []
    for kind, head in (("sinks", "Sink #"), ("sources", "Source #")):
        code, out = run(["env", "LC_ALL=C", "pactl", "list", kind])
        name = ""
        if code == 0:
            for b in _blocks(out, head):
                n = b.get("name", "")
                if b.get("card") == str(card) and not n.endswith(".monitor"):
                    name = n
                    break
        res.append(name)
    return res[0], res[1]


def source_for(sink: str, run=_run) -> str:
    """Eingang derselben Soundkarte zu einem Ausgang (siehe fldigi.source_for_sink)."""
    from .fldigi import source_for_sink
    return source_for_sink(sink, run)


def for_profile(prof: dict | None, fallback: str = "", run=_run,
                sysfs: str = "/sys") -> tuple[str, str, str]:
    """(Ausgang, Eingang, Herkunft) für ein Funkgeräte-Profil.

    Herkunft: "profile" = im Profil gewählt, "auto" = über USB gefunden, "fallback" = die
    Soundkarte des Sprachspeichers, "" = keine gefunden."""
    prof = prof or {}
    if prof.get("conn") == "icom" and prof.get("net_audio", True):
        # 0.10.30: Ton übers Netz – die virtuelle Soundkarte der Icom-Brücke
        from .icomlan import sound_names
        return (*sound_names(int(prof.get("port", 4532))), "profile")
    chosen = (prof.get("audio_out") or "").strip()
    if chosen:
        return chosen, source_for(chosen, run), "profile"
    n = card_for_device(prof.get("device", ""), sysfs)
    if n is not None:
        out, inp = pulse_names(n, run)
        if out:
            return out, inp or source_for(out, run), "auto"
    if fallback:
        return fallback, source_for(fallback, run), "fallback"
    return "", "", ""


def voice_out(cfg: dict, finder=None) -> tuple[str, str]:
    """Soundkarte, über die GoGoHam Sprachspeicher zum Funkgerät schickt (ab 0.10.30.1).

    (Geräte-ID, Herkunft): Herkunft "net" = Icom übers Netzwerk (immer dessen Soundkarte),
    "chosen" = von Hand gewählt, "auto" = zum aktiven Funkgerät-Profil gefunden (wie für
    WSJT-X/fldigi), "" = keine."""
    from .rigprofiles import active
    prof = active(cfg) or {}
    if prof.get("conn") == "icom" and prof.get("net_audio", True):
        from .icomlan import sound_names
        return sound_names(int(prof.get("port", 4532)))[0], "net"
    chosen = cfg.get("voice_rig_out", "")
    if chosen:
        return chosen, "chosen"
    if not prof:
        return "", ""
    out, _inp, origin = (finder or for_profile)(prof)
    return (out, "auto") if out and origin in ("profile", "auto") else ("", "")
