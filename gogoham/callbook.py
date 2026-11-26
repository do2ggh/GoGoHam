"""Name und QTH der Gegenstation über HamQTH und/oder QRZ.com nachschlagen.

Wird beim ADIF-Export benutzt, nicht während des Contests. Die Ergebnisse
werden in der Log-Datei zwischengespeichert, so dass ein zweiter Export
keine neuen Abfragen braucht.

* HamQTH:  https://www.hamqth.com/xml.php   (kostenloses Konto)
* QRZ.com: https://xmldata.qrz.com/xml/current/   (XML-Abo nötig)
"""

from __future__ import annotations

from .i18n import tr

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable

HAMQTH_URL = "https://www.hamqth.com/xml.php"
QRZ_URL = "https://xmldata.qrz.com/xml/current/"
AGENT = "GoGoHam"


@dataclass
class Entry:
    call: str
    name: str = ""
    qth: str = ""
    grid: str = ""
    source: str = ""


class CallbookError(Exception):
    pass


def _http_get(url: str, timeout: float = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _strip_ns(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _text(root: ET.Element, path: str) -> str:
    el = root.find(path)
    return (el.text or "").strip() if el is not None and el.text else ""


class HamQth:
    name = "HamQTH"

    def __init__(self, user: str, password: str, fetch: Callable[[str], str] = _http_get):
        self.user, self.password, self.fetch = user, password, fetch
        self.session = ""

    def login(self) -> None:
        url = HAMQTH_URL + "?" + urllib.parse.urlencode({"u": self.user, "p": self.password})
        root = _strip_ns(ET.fromstring(self.fetch(url)))
        sid = _text(root, ".//session/session_id")
        if not sid:
            raise CallbookError("HamQTH: " + (_text(root, ".//session/error") or tr("Anmeldung fehlgeschlagen")))
        self.session = sid

    def lookup(self, call: str, _retry: bool = True) -> Entry | None:
        if not self.session:
            self.login()
        url = HAMQTH_URL + "?" + urllib.parse.urlencode(
            {"id": self.session, "callsign": call, "prg": AGENT})
        root = _strip_ns(ET.fromstring(self.fetch(url)))
        err = _text(root, ".//session/error")
        if err:
            if _retry and ("expired" in err.lower() or "session" in err.lower()):
                self.session = ""
                return self.lookup(call, _retry=False)
            if "not found" in err.lower():
                return None
            raise CallbookError(f"HamQTH: {err}")
        s = root.find(".//search")
        if s is None:
            return None
        name = _text(s, "nick") or _text(s, "adr_name")
        return Entry(call=call, name=name, qth=_text(s, "qth") or _text(s, "adr_city"),
                     grid=_text(s, "grid").upper(), source=self.name)


class Qrz:
    name = "QRZ.com"

    def __init__(self, user: str, password: str, fetch: Callable[[str], str] = _http_get):
        self.user, self.password, self.fetch = user, password, fetch
        self.key = ""

    def _get(self, params: dict) -> ET.Element:
        url = QRZ_URL + "?" + ";".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
        return _strip_ns(ET.fromstring(self.fetch(url)))

    def login(self) -> None:
        root = self._get({"username": self.user, "password": self.password, "agent": AGENT})
        key = _text(root, ".//Session/Key")
        if not key:
            raise CallbookError("QRZ.com: " + (_text(root, ".//Session/Error") or tr("Anmeldung fehlgeschlagen")))
        self.key = key

    def lookup(self, call: str, _retry: bool = True) -> Entry | None:
        if not self.key:
            self.login()
        root = self._get({"s": self.key, "callsign": call})
        err = _text(root, ".//Session/Error")
        cs = root.find(".//Callsign")
        if cs is None:
            if err and "not found" in err.lower():
                return None
            if err and _retry and ("session" in err.lower() or "timeout" in err.lower()):
                self.key = ""
                return self.lookup(call, _retry=False)
            if err:
                raise CallbookError(f"QRZ.com: {err}")
            return None
        name = " ".join(x for x in (_text(cs, "fname"), _text(cs, "name")) if x)
        return Entry(call=call, name=name, qth=_text(cs, "addr2"),
                     grid=_text(cs, "grid").upper(), source=self.name)


def services_from_config(cfg: dict, fetch: Callable[[str], str] = _http_get) -> list:
    """Dienste in der eingestellten Reihenfolge (nur die mit Zugangsdaten)."""
    avail = {}
    if cfg.get("hamqth_user") and cfg.get("hamqth_password"):
        avail["hamqth"] = HamQth(cfg["hamqth_user"], cfg["hamqth_password"], fetch)
    if cfg.get("qrz_user") and cfg.get("qrz_password"):
        avail["qrz"] = Qrz(cfg["qrz_user"], cfg["qrz_password"], fetch)
    order = cfg.get("callbook_order", ["hamqth", "qrz"])
    return [avail[k] for k in order if k in avail]


def lookup_chain(services: list, call: str, errors: dict | None = None) -> Entry | None:
    """Erst den ersten Dienst fragen, bei „nicht gefunden“ oder Fehler den nächsten."""
    base = call.split("/")
    # bei DL/W1AW oder W1AW/P das eigentliche Rufzeichen nachschlagen
    main = max(base, key=len) if len(base) > 1 else call
    for svc in services:
        try:
            e = svc.lookup(main)
        except (CallbookError, ET.ParseError, OSError) as ex:
            if errors is not None:
                errors[svc.name] = str(ex)
            continue
        if e and (e.name or e.qth):
            e.call = call
            return e
    return None


class CallbookJob:
    """Schlägt eine Liste von Rufzeichen nacheinander nach (im Hintergrund-Thread).

    Fortschritt: .done / .total, Ergebnisse in .results, Abbruch mit .cancel().
    """

    def __init__(self, services: list, calls: list[str]):
        import threading
        self.services = services
        self.calls = list(dict.fromkeys(c.upper() for c in calls))
        self.total = len(self.calls)
        self.done = 0
        self.results: dict[str, Entry] = {}
        self.errors: dict[str, str] = {}
        self.not_found: list[str] = []
        self._cancel = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name="callbook")

    def start(self) -> None:
        self.thread.start()

    def is_alive(self) -> bool:
        return self.thread.is_alive()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> None:
        for call in self.calls:
            if self._cancel.is_set():
                break
            e = lookup_chain(self.services, call, self.errors)
            if e:
                self.results[call] = e
            else:
                self.not_found.append(call)
            self.done += 1
            # Abbrechen, wenn alle Dienste nicht erreichbar sind
            if self.errors and len(self.errors) == len(self.services) and not self.results \
                    and self.done >= 3:
                break
