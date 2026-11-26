"""Live-Score: Punktestand während des Contests an ein Online-Scoreboard senden.

Format: XML „dynamicresults“ nach der Spezifikation von contestonlinescore.com.
Ziel standardmäßig https://contestonlinescore.com/post/ (Anmeldung dort nötig,
Benutzername = Rufzeichen, Passwort aus deinem Konto). Alternativ der
Score Distributor (scoredistributor.net), der an mehrere Scoreboards weiterleitet.
"""

from __future__ import annotations

from .i18n import tr

import base64
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from . import __version__

DEFAULT_URL = "https://contestonlinescore.com/post/"
INTERVAL = 120          # Sekunden

MULT_TYPE = {"zone": "zone", "country": "country", "prefix": "wpxprefix", "field": "gridsquare",
             "state": "state", "province": "province"}
MODE = {"PH": "PH", "CW": "CW", "RY": "RTTY", "DG": "DIGI"}


def build_xml(contest, meta: dict, scorer, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    call = meta.get("mycall", "").upper()
    ops = (meta.get("operators") or call).replace(" ", ",")
    modes = sorted(contest.modes)
    mode = MODE.get(modes[0], "MIXED") if len(modes) == 1 else "MIXED"
    me = scorer.contest.station.lookup
    lines = [
        '<?xml version="1.0"?>',
        "<dynamicresults>",
        f"<contest>{escape(contest.cabrillo_name)}</contest>",
        f"<call>{escape(call)}</call>",
        f"<ops>{escape(ops)}</ops>",
        (f'<class power="{escape(meta.get("cat_power", "HIGH"))}" '
         f'assisted="{escape(meta.get("cat_assisted", "NON-ASSISTED"))}" '
         f'transmitter="{escape(meta.get("cat_transmitter", "ONE"))}" '
         f'ops="{escape(meta.get("cat_operator", "SINGLE-OP"))}" '
         f'bands="{escape(meta.get("cat_band", "ALL"))}" mode="{mode}" '
         f'overlay="{escape(meta.get("cat_overlay") or "N/A")}"/>'),
        f"<club>{escape(meta.get('club', ''))}</club>",
        "<soft>GoGoHam</soft>",
        f"<version>{__version__}</version>",
        "<qth>",
        f"<dxcccountry>{escape(me.country.lstrip('*') if me and me.country else '')}</dxcccountry>",
        f"<cqzone>{escape(meta.get('my_zone', ''))}</cqzone>",
        f"<iaruzone>{me.itu if me and me.itu else ''}</iaruzone>",
        f"<grid6>{escape(meta.get('my_grid', ''))}</grid6>",
        "</qth>",
        "<breakdown>",
    ]
    for band in [b for b in contest.bands if b in scorer.band_stats]:
        bs = scorer.band_stats[band]
        lines.append(f'<qso band="{band}" mode="ALL">{bs["qsos"]}</qso>')
        lines.append(f'<point band="{band}" mode="ALL">{bs["points"]}</point>')
        for k, _lab in contest.mult_types:
            n = len(scorer.mults.get((k, band), set())) if contest.mults_per_band \
                else bs["mults"].get(k, 0)
            lines.append(f'<mult band="{band}" mode="ALL" type="{MULT_TYPE.get(k, k)}">{n}</mult>')
    lines.append(f'<qso band="total" mode="ALL">{scorer.total_qsos}</qso>')
    lines.append(f'<point band="total" mode="ALL">{scorer.total_points}</point>')
    for k, _lab in contest.mult_types:
        lines.append(f'<mult band="total" mode="ALL" type="{MULT_TYPE.get(k, k)}">'
                     f'{scorer.mult_count(k)}</mult>')
    lines += ["</breakdown>", f"<score>{scorer.score}</score>",
              f"<timestamp>{now.strftime('%Y-%m-%d %H:%M:%S')}</timestamp>",
              "</dynamicresults>"]
    return "\n".join(lines)


def post(url: str, user: str, password: str, xml: str, timeout: float = 15) -> str:
    """Sendet das XML. Gibt die Antwort des Servers zurück, wirft bei HTTP-Fehlern.

    Zuerst als XML im Rumpf; lehnt der Server das ab, als Formularfeld „xml“.
    """
    headers = {"User-Agent": f"GoGoHam/{__version__}"}
    if user and password:
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    attempts = [
        (xml.encode("utf-8"), "text/xml; charset=utf-8"),
        (urllib.parse.urlencode({"xml": xml}).encode(), "application/x-www-form-urlencoded"),
    ]
    last = ""
    for body, ctype in attempts:
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={**headers, "Content-Type": ctype})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            last = r.read().decode("utf-8", "replace")
        if "invalid data" not in last.lower() and "no xml" not in last.lower():
            return last
    return last


class LiveScore(threading.Thread):
    """Sendet alle INTERVAL Sekunden den Stand, den get_xml() liefert."""

    def __init__(self, url: str, user: str, password: str, get_xml, interval: int = INTERVAL):
        super().__init__(daemon=True, name="livescore")
        self.url, self.user, self.password = url, user, password
        self.get_xml = get_xml
        self.interval = interval
        self.status = tr("wartet auf ersten Upload")
        self.last_ok: float = 0
        self._halt = threading.Event()
        self._now = threading.Event()

    def stop(self) -> None:
        self._halt.set()
        self._now.set()

    def trigger(self) -> None:
        self._now.set()

    def run(self) -> None:
        while not self._halt.is_set():
            xml = self.get_xml()
            if xml:
                try:
                    answer = post(self.url, self.user, self.password, xml)
                    ok = '"status":200' in answer.replace(" ", "") or "ok" in answer.lower()
                    self.status = tr("gesendet {time}", time=time.strftime("%H:%M")) if ok \
                        else tr("Antwort: {answer}", answer=answer[:80])
                    if ok:
                        self.last_ok = time.time()
                except Exception as e:  # noqa: BLE001
                    self.status = tr("Fehler: {e}", e=e)
            self._now.wait(self.interval)
            self._now.clear()
