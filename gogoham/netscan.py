"""rigctld auf anderen Rechnern im eigenen Netz finden (ab 0.10.30).

Fragt alle Adressen des eigenen Netzes (das /24 der eigenen Adresse) auf den üblichen
rigctld-Ports 4532–4536 ab und prüft, ob dort wirklich ein rigctld antwortet. Es wird nur
gelesen (Modell abfragen), nie gesendet.
"""

from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor

PORTS = tuple(range(4532, 4537))


def own_ipv4() -> str:
    """Eigene Adresse im Heimnetz (ohne Pakete zu verschicken)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))           # Testnetz, UDP-connect sendet nichts
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


def candidates(ip: str) -> list[str]:
    """Alle anderen Adressen im /24 der eigenen Adresse (nur private Netze)."""
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return []
    if not addr.is_private or addr.is_loopback:
        return []
    net = ipaddress.IPv4Network(f"{ip}/24", strict=False)
    return [str(h) for h in net.hosts() if str(h) != ip]


def _open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def find_rigctld(hosts: list[str] | None = None, ports=PORTS, timeout: float = 0.3,
                 query=None) -> list[tuple[str, int, str]]:
    """[(Adresse, Port, Gerätename)] – nur Stellen, an denen ein rigctld antwortet."""
    from .hamlib import find_model
    from .rig import query_model
    query = query or (lambda h, p: query_model(h, p, timeout=1.5))
    hosts = hosts if hosts is not None else candidates(own_ipv4())
    pairs = [(h, p) for h in hosts for p in ports]
    with ThreadPoolExecutor(max_workers=64) as ex:
        open_ = [hp for hp, ok in zip(pairs, ex.map(lambda hp: _open(*hp, timeout), pairs)) if ok]
    out = []
    for h, p in open_:
        model = query(h, p)
        if not model:
            continue
        r = find_model(model)
        out.append((h, p, r.name if r else f"Hamlib {model}"))
    return out
