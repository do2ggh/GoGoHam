"""Multi-OP-Kategorien (ab 0.10.2): Multi-Single, Multi-Two, Multi-Multi – ohne Qt.

Die Regeln je Contest stehen in der Regel-Datei unter „multi“ (Format 12), z. B. CQ WW:

    "multi": {
      "MS": {"tx_id": true, "dwell": {"minutes": 10}, "mult_station": true},
      "M2": {"tx_id": true, "per_hour": 8},
      "MM": {}
    }

- tx_id: Sendernummer (0/1) in der letzten Spalte der Cabrillo-QSO-Zeile.
- dwell: so viele Minuten auf einem Band bleiben (ab dem ersten QSO dort), je Sender;
  "mode": true = auch Betriebsart (IARU).
- per_hour: höchstens so viele Bandwechsel je Uhrstunde (00–59) und Sender.
- mult_station: Multi-Single mit zweitem Signal (Sender 1) – nur neue Multis, nur auf einem
  anderen Band als der Run-Sender (CQ WW).
- serial: "station" (eine Folge, Standard), "band" (je Band eigene Folge, WPX M2/MM).

Wer welcher Sender ist, steht beim QSO im Feld „tx“ ("0"/"1"); ohne Angabe gilt "0".
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .i18n import tr

# Cabrillo CATEGORY-TRANSMITTER je Kategorie
TRANSMITTER = {"MS": "ONE", "M2": "TWO", "MM": "UNLIMITED"}
FROM_TRANSMITTER = {v: k for k, v in TRANSMITTER.items()}


def label(cat: str) -> str:
    return {"MS": tr("Multi-Single (ein Signal, ggf. ein Multi-Signal)"),
            "M2": tr("Multi-Two (zwei Signale auf verschiedenen Bändern)"),
            "MM": tr("Multi-Multi (ein Signal je Band)")}.get(cat, cat)


def category(meta: dict) -> str | None:
    """Multi-OP-Kategorie aus den Log-Angaben – None bei Single-OP."""
    if (meta.get("cat_operator") or "").upper() != "MULTI-OP":
        return None
    return FROM_TRANSMITTER.get((meta.get("cat_transmitter") or "ONE").upper(), "MS")


def rules(contest, cat: str | None) -> dict:
    multi = getattr(contest, "multi", None) or {}
    return dict(multi.get(cat) or {}) if cat else {}


def tx_roles(contest, cat: str | None) -> list[tuple[str, str]]:
    """Auswahl „Sender“ je Platz: [(Wert, Anzeige)]."""
    r = rules(contest, cat)
    if cat == "MS":
        if r.get("mult_station"):
            return [("0", tr("Run (Sender 0)")), ("1", tr("Multi (Sender 1)"))]
        return [("0", tr("Sender 0"))]
    if cat == "M2":
        return [("0", tr("Sender 0")), ("1", tr("Sender 1"))]
    return [("0", tr("Sender 0"))]


def needs_tx_id(contest, cat: str | None) -> bool:
    return bool(rules(contest, cat).get("tx_id"))


def serial_mode(contest, cat: str | None) -> str:
    return rules(contest, cat).get("serial", "station")


def _t(q) -> datetime:
    return datetime.strptime(q.time[:19], "%Y-%m-%d %H:%M:%S")


def _tx(q) -> str:
    return getattr(q, "tx", "") or "0"


def band_notes(contest, cat: str | None, qsos: list, band: str, mode: str, tx: str,
               now: datetime, is_new_mult: bool | None = None,
               soft: bool = True) -> list[str]:
    """Hinweise zum geplanten QSO auf ``band``/``mode`` von Sender ``tx`` (leer = alles gut)."""
    r = rules(contest, cat)
    if not r:
        return []
    tx = tx or "0"
    mine = sorted((q for q in qsos if _tx(q) == tx), key=lambda q: q.time)
    notes: list[str] = []
    dw = r.get("dwell")
    if dw and mine:
        with_mode = bool(dw.get("mode"))
        last = mine[-1]
        key = (lambda q: (q.band, q.mode)) if with_mode else (lambda q: q.band)
        new_key = (band, mode) if with_mode else band
        if key(last) != new_key:
            start = last
            for q in reversed(mine):          # erstes QSO der laufenden Zeit auf diesem Band
                if key(q) != key(last):
                    break
                start = q
            until = _t(start) + timedelta(minutes=int(dw.get("minutes", 10)))
            if now < until:
                what = tr("Band und Betriebsart") if with_mode else tr("Band")
                notes.append(tr("{m}-Minuten-Regel: Sender {tx} muss bis {hhmm} UTC auf {band} "
                                "bleiben ({what})", m=int(dw.get("minutes", 10)), tx=tx,
                                hhmm=until.strftime("%H:%M"), band=last.band, what=what))
    ph = r.get("per_hour")
    if ph and mine:
        hour = now.replace(minute=0, second=0, microsecond=0)
        prev, changes = None, 0
        for q in mine:
            if prev is not None and q.band != prev.band and _t(q) >= hour:
                changes += 1
            prev = q
        if mine[-1].band != band:
            n = changes + 1
            nxt = (hour + timedelta(hours=1)).strftime("%H:%M")
            if n > int(ph):
                notes.append(tr("Bandwechsel Nr. {n} in dieser Stunde – Sender {tx} darf nur "
                                "{limit}; wieder ab {nxt} UTC", n=n, tx=tx, limit=int(ph),
                                nxt=nxt))
            elif n == int(ph) and soft:
                notes.append(tr("Letzter erlaubter Bandwechsel in dieser Stunde für Sender {tx} "
                                "({n} von {limit})", tx=tx, n=n, limit=int(ph)))
    if r.get("mult_station") and tx == "1":
        run = sorted((q for q in qsos if _tx(q) == "0"), key=lambda q: q.time)
        if run and run[-1].band == band:
            notes.append(tr("Multi-Signal: nicht auf dem Band des Run-Senders ({band})",
                            band=band))
        if is_new_mult is False:
            notes.append(tr("Multi-Signal darf nur neue Multis arbeiten – diese Station ist "
                            "kein neuer Multi"))
    return notes


def check_log(contest, cat: str | None, qsos: list) -> list[str]:
    """Für die Log-Prüfung: alle Verstöße gegen die Bandwechsel-Regeln im ganzen Log."""
    r = rules(contest, cat)
    out: list[str] = []
    if not r:
        return out
    by_tx: dict[str, list] = {}
    for q in sorted(qsos, key=lambda q: q.time):
        by_tx.setdefault(_tx(q), []).append(q)
    for tx, lst in sorted(by_tx.items()):
        for i in range(1, len(lst)):
            q = lst[i]
            others = [x for x in qsos if _tx(x) != tx and x.time <= q.time]
            notes = band_notes(contest, cat, lst[:i] + others, q.band, q.mode, tx, _t(q),
                               soft=False)
            for n in notes:
                out.append(f"{q.time[:16]} {q.call} ({q.band}): {n}")
    return out
