"""Geräte-Profile: bis zu fünf Funkgeräte einrichten und umschalten.

Jedes Funkgerät hat seinen **eigenen rigctld** mit eigener Port-Nummer
(z. B. IC-7300 auf 4532, IC-9700 auf 4533). Ein Profil sagt GoGoHam nur,
mit welchem rigctld es spricht. Umschalten wirkt deshalb **nur in GoGoHam** –
WSJT-X, Log-Programme usw. bleiben bei ihrem eingestellten rigctld und merken nichts.

Ein Profil enthält: Name, Hamlib-Modell, Schnittstelle, Baudrate, weitere
rigctld-Optionen, Host/Port des rigctld und ob GoGoHam rigctld selbst startet
(``start``) oder einen vorhandenen benutzt (z. B. einen Systemdienst).

GoGoHam startet immer mit Profil 1. Das aktive Profil wird in die bisherigen
Felder rig_model, rig_device, rig_baud, rig_extra, rig_host, rig_port und
rig_autostart kopiert – der Rest des Programms arbeitet damit.
"""

from __future__ import annotations

import os
import re

from .i18n import tr

MAX_PROFILES = 5               # 0.10.4: fünf Plätze (Ports 4532–4536, Rotor 4540)
DEFAULT_PORT = 4532
CONNECTIONS = ("usb", "icom", "net", "remote")
ICOM_PORT = 50001             # Steuer-Port der Icom-Netzwerk-Fernsteuerung


def conn(p: dict | None) -> str:
    c = (p or {}).get("conn", "usb")
    return c if c in CONNECTIONS else "usb"


def default_name(model: int) -> str:
    from .hamlib import find_model
    r = find_model(int(model))
    return r.name if r else f"Hamlib {model}"


def _normalize(p: dict, i: int, cfg: dict) -> dict:
    p.setdefault("name", tr("Funkgerät {p1}", p1=i + 1))
    p.setdefault("device", "")
    p.setdefault("baud", 0)
    p.setdefault("extra", "")
    p.setdefault("host", cfg.get("rig_host", "127.0.0.1") or "127.0.0.1")
    p.setdefault("port", int(cfg.get("rig_port", DEFAULT_PORT) or DEFAULT_PORT) + i)
    p.setdefault("start", bool(cfg.get("rig_autostart", True)))
    p.setdefault("service", False)          # 0.8.17: Hintergrund-rigctld von GoGoHam
    p.setdefault("winkey", "")              # 0.8.18: Schnittstelle des WinKey ("" = CW übers Gerät)
    p.setdefault("ptt_line", "")            # 0.8.18: "" = PTT über CAT, sonst "DTR"/"RTS"
    p.setdefault("ptt_device", "")
    p.setdefault("lines", "")               # 0.8.22: DTR/RTS fürs Interface (LINE_STATES)
    p.setdefault("civaddr", "")             # 0.8.22: Icom CI-V-Adresse, "" = Standard des Modells
    p.setdefault("poll_ms", 0)              # 0.8.29.1: Abfrage-Abstand, 0 = automatisch (gemessen)
    p.setdefault("audio_out", "")           # 0.10.9: Soundkarte des Funkgeräts, "" = automatisch
    # 0.10.30: Verbindung – "usb" (Kabel/Schnittstelle), "icom" (Icom über LAN/WLAN, eigene
    # Brücke), "net" (Gerät mit Netzwerk über Hamlib, Adresse:Port), "remote" (rigctld auf
    # einem anderen Rechner)
    p.setdefault("conn", "usb")
    p.setdefault("net_host", "")
    p.setdefault("net_port", 0)
    p.setdefault("net_user", "")
    p.setdefault("net_pass", "")
    p.setdefault("net_audio", True)
    if p["conn"] not in CONNECTIONS:
        p["conn"] = "usb"
    p["model"] = int(p["model"])
    p["port"] = int(p["port"])
    p["baud"] = int(p.get("baud") or 0)
    return p


def ensure_profiles(cfg: dict) -> list[dict]:
    """Profile prüfen; aus einer alten Einstellung (vor 0.6.3) wird Profil 1.

    Ohne eingerichtetes Gerät bleibt die Liste leer.
    """
    profs = cfg.get("rig_profiles")
    if not isinstance(profs, list) or not profs:
        profs = []
        if int(cfg.get("rig_model") or 0):
            profs = [{
                "name": default_name(cfg["rig_model"]),
                "model": int(cfg["rig_model"]),
                "device": cfg.get("rig_device", ""),
                "baud": int(cfg.get("rig_baud") or 0),
                "extra": cfg.get("rig_extra", ""),
                "host": cfg.get("rig_host", "127.0.0.1"),
                "port": int(cfg.get("rig_port", DEFAULT_PORT)),
                "start": bool(cfg.get("rig_autostart", True)),
            }]
    profs = [p for p in profs if isinstance(p, dict) and int(p.get("model") or 0)][:MAX_PROFILES]
    # 0.8.17.2: jedes Profil hat seinen festen Platz 1–5 ("slot" 0–4), frei belegbar.
    # Die Liste bleibt nach Platz sortiert; GoGoHam startet mit dem zuletzt benutzten Profil
    # (0.8.31.1 – vorher immer mit dem niedrigsten belegten Platz).
    used: set[int] = set()
    for p in profs:
        s = p.get("slot")
        ok = isinstance(s, int) and 0 <= s < MAX_PROFILES and s not in used
        p["slot"] = s if ok else None
        if ok:
            used.add(s)
    for p in profs:                         # alte Profile ohne Platz: der Reihe nach
        if p["slot"] is None:
            p["slot"] = min(x for x in range(MAX_PROFILES) if x not in used)
            used.add(p["slot"])
    idx = cfg.get("rig_profile", 0)
    if not isinstance(idx, int) or not 0 <= idx < len(profs):
        idx = 0
    act = profs[idx] if profs else None
    profs.sort(key=lambda p: p["slot"])
    idx = profs.index(act) if act is not None else 0
    cfg["rig_profiles"] = [_normalize(p, i, cfg) for i, p in enumerate(profs)]
    if profs:
        apply_profile(cfg, idx)
    else:
        cfg["rig_profile"] = 0
    return cfg["rig_profiles"]


def apply_profile(cfg: dict, idx: int) -> dict:
    """Profil Nr. idx aktiv machen (in die rig_*-Felder kopieren)."""
    p = cfg["rig_profiles"][idx]
    cfg["rig_profile"] = idx
    cfg["rig_model"] = int(p["model"])
    cfg["rig_device"] = device(p)
    cfg["rig_baud"] = int(p.get("baud") or 0)
    cfg["rig_extra"] = full_extra(p)          # 0.8.22: samt DTR/RTS und CI-V-Adresse
    cfg["rig_host"] = rigctld_host(p)
    cfg["rig_port"] = int(p.get("port", DEFAULT_PORT))
    cfg["rig_autostart"] = bool(p.get("start", True))
    return p


def device(p: dict) -> str:
    """Was rigctld als „Schnittstelle“ bekommt: bei Netzwerk-Geräten über Hamlib
    „Adresse:Port“ (0.10.30), sonst die Schnittstelle des Profils."""
    if conn(p) == "net" and p.get("net_host"):
        return f"{p['net_host']}:{int(p.get('net_port') or 0)}"
    return p.get("device", "")


def rigctld_host(p: dict) -> str:
    """Wo der rigctld des Profils läuft: bei „anderer Rechner“ dessen Adresse."""
    if conn(p) == "remote" and p.get("net_host"):
        return p["net_host"]
    return p.get("host", "127.0.0.1") or "127.0.0.1"


def active(cfg: dict) -> dict | None:
    profs = cfg.get("rig_profiles") or []
    i = cfg.get("rig_profile", 0)
    return profs[i] if 0 <= i < len(profs) else None


def free_port(cfg: dict, exclude: int | None = None) -> int:
    """Nächste freie Port-Nummer für ein neues Profil (4532, 4533 …)."""
    used = {int(p.get("port", 0)) for i, p in enumerate(cfg.get("rig_profiles") or [])
            if i != exclude}
    port = DEFAULT_PORT
    while port in used:
        port += 1
    return port


# --- Interface älterer Geräte (0.8.22) ---------------------------------------------------
# Viele einfache CI-V-/CAT-Pegelwandler holen ihren Strom aus DTR und/oder RTS. Hamlib lässt
# die Leitungen sonst, wie Linux sie beim Öffnen setzt. (DTR, RTS) je Auswahl:
LINE_STATES = {"": None, "both": ("ON", "ON"), "dtr": ("ON", "OFF"), "rts": ("OFF", "ON"),
               "off": ("OFF", "OFF")}


def parse_civaddr(text: str) -> int | None:
    """CI-V-Adresse aus „94“, „0x94“ oder „94h“ (immer hexadezimal wie im Icom-Menü).
    None = leer oder ungültig (gültig: 01–DF)."""
    t = (text or "").strip().lower()
    if t.startswith("0x"):
        t = t[2:]
    if t.endswith("h"):
        t = t[:-1]
    if not t or len(t) > 2:
        return None
    try:
        v = int(t, 16)
    except ValueError:
        return None
    return v if 0x01 <= v <= 0xDF else None


def conf_items(p: dict) -> list[str]:
    """Hamlib-Einstellungen (--set-conf) aus den erweiterten Feldern des Profils."""
    items = []
    st = LINE_STATES.get(p.get("lines") or "")
    if st and conn(p) == "usb":               # Steuerleitungen gibt es nur am Kabel
        items += [f"dtr_state={st[0]}", f"rts_state={st[1]}"]
    civ = parse_civaddr(p.get("civaddr", ""))
    if civ is not None:
        items.append(f"civaddr=0x{civ:02X}")
    return items


PTT_LINES = ("DTR", "RTS")
_OWN_PTT = re.compile(r"(?:^|\s)(?:-P|--ptt-type\b)")


def ptt_args(p: dict) -> list[str]:
    """PTT über DTR/RTS (0.10.45): schaltet der rigctld selbst (--ptt-type/--ptt-file), damit
    nur EIN Programm die Schnittstelle offen hat und WSJT-X, fldigi, GoGoHome & Co. über
    „PTT über CAT“ genauso senden. Leer = PTT über CAT. Eigene Optionen gehen vor."""
    line, dev = p.get("ptt_line") or "", (p.get("ptt_device") or "").strip()
    if line not in PTT_LINES or not dev or any(c.isspace() for c in dev) \
            or _OWN_PTT.search(p.get("extra") or ""):
        return []
    args = [f"--ptt-type={line}"]
    rig_dev = p.get("device") or ""
    same = conn(p) == "usb" and rig_dev and os.path.realpath(dev) == os.path.realpath(rig_dev)
    if same and int(p.get("model") or 0) // 1000 == 3:
        # Icom am selben USB-Anschluss: die GoGoHandy-Brücke hält ihn exklusiv (keine Leitung
        # erreichbar) – Icom sendet aber immer auch über CI-V, also PTT über CAT.
        return []
    if not same:                       # gleiche Schnittstelle: Hamlib nimmt die CAT-Schnittstelle
        args.append(f"--ptt-file={dev}")
    return args


def full_extra(p: dict) -> str:
    """Alle zusätzlichen rigctl/rigctld-Optionen: erweiterte Felder, PTT-Leitung, eigene Optionen."""
    items = conf_items(p)
    parts = [f"--set-conf={','.join(items)}"] if items else []
    parts += ptt_args(p)
    own = (p.get("extra") or "").strip()
    if own:
        parts.append(own)
    return " ".join(parts)


def lines_on(p: dict) -> set[str]:
    """Welche Leitungen das Profil dauerhaft einschaltet ({"DTR", "RTS"})."""
    st = LINE_STATES.get(p.get("lines") or "")
    if not st:
        return set()
    return {n for n, v in zip(("DTR", "RTS"), st) if v == "ON"}


def interface_problem(p: dict) -> str:
    """Passen die erweiterten Felder zusammen? "" = in Ordnung."""
    import os
    if (p.get("civaddr") or "").strip() and parse_civaddr(p["civaddr"]) is None:
        return tr("CI-V-Adresse „{a}“ ist ungültig – zwei Hex-Ziffern, z. B. 94 (leer = Standard).",
                  a=p["civaddr"])
    line = p.get("ptt_line")
    if line and line in lines_on(p) and p.get("ptt_device") and p.get("device") and \
            os.path.realpath(p["ptt_device"]) == os.path.realpath(p["device"]):
        return tr("{line} soll gleichzeitig das Interface versorgen und PTT schalten – das Gerät "
                  "würde dauernd senden. Bitte eins von beiden ändern.", line=line)
    return ""
