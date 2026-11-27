"""WLAN verbinden ohne Linux-Kenntnisse (ab 0.10.48, Live-Stick).

Wer vom Stick startet und kein Netzwerkkabel hat, soll nicht erst suchen müssen, wo man unter
Linux das WLAN einrichtet. GoGoHam fragt dafür NetworkManager über ``nmcli`` – das gibt es auf dem
Stick und auf fast jedem Linux mit Oberfläche. Die gewählte Verbindung speichert NetworkManager
für alle Benutzer (samt Passwort, kein Schlüsselbund nötig); beim nächsten Start verbindet der
Rechner sich von selbst. Hier nur Abfragen und Auswerten – das Fenster steht in gui/wlan_dialog.py.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

TIMEOUT_LIST = 20
TIMEOUT_CONNECT = 45


@dataclass
class Network:
    ssid: str
    signal: int            # 0–100
    secure: bool           # Passwort nötig
    in_use: bool = False


def _env() -> dict:
    env = dict(os.environ)
    env["LC_ALL"] = "C"                    # Meldungen englisch → verlässlich auswerten
    return env


def _run(args: list[str], timeout: float) -> tuple[int, str, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=_env())
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -2, "", "timeout"
    except OSError as e:
        return -1, "", str(e)


def available(which=shutil.which) -> bool:
    return bool(which("nmcli"))


def split_terse(line: str) -> list[str]:
    """Eine Zeile von „nmcli -t“: Felder mit „:“ getrennt, „\\:“ und „\\\\“ sind Zeichen."""
    out, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def has_wifi(devices: str) -> bool:
    """Ausgabe von „nmcli -t -f TYPE,STATE device“: gibt es ein WLAN-Gerät, das nicht aus ist?"""
    for line in devices.splitlines():
        f = split_terse(line)
        if len(f) >= 2 and f[0] == "wifi" and f[1] not in ("unavailable", "unmanaged"):
            return True
    return False


def online(state: str) -> bool:
    """Ausgabe von „nmcli -t -f STATE general“: mit dem Internet verbunden (Kabel oder WLAN)?"""
    return state.strip() == "connected"


def parse_networks(text: str) -> list[Network]:
    """Ausgabe von „nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY device wifi list“: je Name das stärkste
    Netz, verborgene Netze (ohne Namen) weg, stärkstes zuerst."""
    best: dict[str, Network] = {}
    for line in text.splitlines():
        f = split_terse(line)
        if len(f) < 4 or not f[1]:
            continue
        try:
            sig = int(f[2])
        except ValueError:
            sig = 0
        sec = f[3].strip() not in ("", "--")
        n = Network(f[1], sig, sec, f[0].strip() == "*")
        old = best.get(n.ssid)
        if old is None or n.signal > old.signal:
            n.in_use = n.in_use or bool(old and old.in_use)
            best[n.ssid] = n
        elif n.in_use:
            old.in_use = True
    return sorted(best.values(), key=lambda n: (not n.in_use, -n.signal, n.ssid.lower()))


def bars(signal: int) -> str:
    """Empfangsstärke als Balken (nicht nur Farbe – lesbar auch bei Farbschwäche)."""
    full = 1 + (signal >= 30) + (signal >= 55) + (signal >= 80)
    return "▂▄▆█"[:full] + "·" * (4 - full)


def failure(code: int, out: str, err: str) -> str:
    """Grund für ein fehlgeschlagenes „nmcli device wifi connect“: password, not_found, timeout
    oder other."""
    text = (out + "\n" + err).lower()
    if code == -2 or "timeout" in text and "secrets" not in text:
        return "timeout"
    if ("secrets were required" in text or "psk" in text and "invalid" in text
            or "no secrets" in text or "802-1x" in text and "secret" in text):
        return "password"
    if "no network with ssid" in text or "not found" in text:
        return "not_found"
    return "other"


# ------------------------------------------------------------------ mit nmcli
def state(run=_run) -> tuple[bool, bool]:
    """(WLAN-Gerät vorhanden, schon online) – beides False, wenn nmcli fehlt oder nicht antwortet."""
    code, out, _ = run(["nmcli", "-t", "-f", "TYPE,STATE", "device"], 5)
    if code != 0:
        return False, False
    wifi = has_wifi(out)
    code, out, _ = run(["nmcli", "-t", "-f", "STATE", "general"], 5)
    return wifi, code == 0 and online(out)


def scan(run=_run) -> list[Network]:
    code, out, _ = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi",
                        "list", "--rescan", "yes"], TIMEOUT_LIST)
    return parse_networks(out) if code == 0 else []


def _profiles(run=_run) -> set[str]:
    code, out, _ = run(["nmcli", "-t", "-f", "NAME", "connection", "show"], 5)
    return {split_terse(x)[0] for x in out.splitlines() if x} if code == 0 else set()


def connect(ssid: str, password: str = "", run=_run) -> tuple[bool, str]:
    """Verbinden. (True, "") oder (False, Grund aus failure()). Eine dabei neu angelegte, aber nicht
    funktionierende Verbindung wird wieder entfernt – sonst probiert NetworkManager beim nächsten
    Start das falsche Passwort erneut."""
    before = _profiles(run)
    args = ["nmcli", "--wait", str(TIMEOUT_CONNECT - 5), "device", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    code, out, err = run(args, TIMEOUT_CONNECT)
    if code == 0:
        return True, ""
    if ssid not in before and ssid in _profiles(run):
        run(["nmcli", "connection", "delete", "id", ssid], 10)
    return False, failure(code, out, err)
