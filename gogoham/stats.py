"""Statistik: QSOs pro Stunde und Band (für die Rate-Grafik)."""

from __future__ import annotations

from datetime import datetime


def rate_by_hour(qsos, bands: list[str], include_dupes: bool = False,
                 dupes: set[int] | None = None) -> list[tuple[str, dict[str, int]]]:
    """[(\"24.10. 13 UTC\", {\"20\": 55, \"40\": 3}), …] – lückenlos von der ersten
    bis zur letzten Stunde mit QSOs."""
    buckets: dict[datetime, dict[str, int]] = {}
    for q in qsos:
        if not include_dupes and dupes and q.id in dupes:
            continue
        try:
            t = datetime.strptime(q.time[:13], "%Y-%m-%d %H")
        except ValueError:
            continue
        b = buckets.setdefault(t, {})
        b[q.band] = b.get(q.band, 0) + 1
    if not buckets:
        return []
    from datetime import timedelta
    out = []
    t, last = min(buckets), max(buckets)
    while t <= last:
        out.append((t.strftime("%d.%m. %H") + " UTC", buckets.get(t, {})))
        t += timedelta(hours=1)
    return out


def mult_matrix(contest, scorer, qsos) -> dict:
    """Je Multi-Typ: welche Werte auf welchen Bändern gearbeitet sind.

    Rückgabe {typ: {"label": "Zonen", "rows": [werte…], "cols": [bänder…],
                    "worked": {(wert, band)}}}.
    Zonen werden immer vollständig (1–40) aufgeführt, damit man sieht, was fehlt.
    Bei Multis, die nur einmal zählen (WPX), gibt es eine Spalte je Band des
    ersten QSOs.
    """
    out = {}
    first_band: dict[tuple, str] = {}
    for q in qsos:
        ev = scorer.evals.get(q.id)
        if ev:
            for t, v in ev.new_mults:
                first_band.setdefault((t, v), q.band)
    for key, label in contest.mult_types:
        worked = set()
        per = getattr(contest, "mult_per", None)
        if contest.mults_per_band or per == "band_mode":
            for (t, b), vals in scorer.mults.items():
                if t == key:
                    worked |= {(v, b.split(":", 1)[0]) for v in vals}
        else:
            for (t, v), b in first_band.items():
                if t == key:
                    worked.add((v, b))
        values = {v for v, _b in worked}
        if key == "zone":
            rows = [str(z) for z in range(1, 41)]
        else:
            rows = sorted(values)
        out[key] = {"label": label, "rows": rows, "cols": list(contest.bands),
                    "worked": worked}
    return out


def changes_in_hour(qsos, q=None) -> tuple[int, str]:
    """Band-/Modewechsel in der Uhrstunde des QSOs q (bzw. des letzten QSOs).

    Nach EU-HF-Regel 9: Band und Mode gleichzeitig = ein Wechsel; ein Wechsel beim
    Übergang in eine neue Stunde zählt als erster Wechsel dieser Stunde.
    Ergebnis: (Anzahl Wechsel einschließlich q, Stunde "JJJJ-MM-TT HH").
    """
    from .bands import cabrillo_mode
    log = sorted((x for x in qsos if x.time), key=lambda x: x.time)
    if q is not None:
        log = [x for x in log if x.id is None or x.id != q.id] + [q]
        log.sort(key=lambda x: x.time)
    if not log:
        return 0, ""
    ref = q if q is not None else log[-1]
    hour = ref.time[:13]
    n = 0
    prev = None
    for x in log:
        if x.time[:13] > hour:
            break
        key = (x.band, cabrillo_mode(x.mode))
        if prev is not None and key != prev and x.time[:13] == hour:
            n += 1
        prev = key
    return n, hour


def change_points(qsos, q=None) -> list:
    """QSOs, mit denen ein Band- oder Modewechsel beginnt (zeitlich sortiert), q mitgezählt.

    Weihnachten/Ostern: „höchstens 20 Wechsel der Betriebsart oder des Bandes während der
    gesamten Contestzeit“ – Band und Mode gleichzeitig = ein Wechsel."""
    from .bands import cabrillo_mode
    log = sorted((x for x in qsos if x.time), key=lambda x: x.time)
    if q is not None:
        log = [x for x in log if x.id is None or x.id != q.id] + [q]
        log.sort(key=lambda x: x.time)
    out, prev = [], None
    for x in log:
        key = (x.band, cabrillo_mode(x.mode))
        if prev is not None and key != prev:
            out.append(x)
        prev = key
    return out


def changes_total(qsos, q=None) -> int:
    """Anzahl Band-/Modewechsel im ganzen Log (einschließlich q, wenn angegeben)."""
    return len(change_points(qsos, q))


def hours_over_limit(qsos, limit: int) -> list[tuple[str, int]]:
    """Alle Uhrstunden mit mehr als ``limit`` Band-/Modewechseln (für die Log-Prüfung)."""
    from .bands import cabrillo_mode
    log = sorted((x for x in qsos if x.time), key=lambda x: x.time)
    counts: dict[str, int] = {}
    prev = None
    for x in log:
        key = (x.band, cabrillo_mode(x.mode))
        if prev is not None and key != prev:
            counts[x.time[:13]] = counts.get(x.time[:13], 0) + 1
        prev = key
    return [(h, n) for h, n in sorted(counts.items()) if n > limit]
