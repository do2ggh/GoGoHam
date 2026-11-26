"""Log-Prüfung vor dem Einreichen: verdächtige QSOs finden."""

from __future__ import annotations

from .i18n import tr

from dataclasses import dataclass

WARN, INFO = "warn", "info"


@dataclass
class Finding:
    qso_id: int
    call: str
    band: str
    time: str
    level: str
    text: str


def check(contest, qsos, scorer, scp=None, history=None, meta=None) -> list[Finding]:
    out: list[Finding] = []
    scp_calls = set(scp.calls) if scp is not None and len(scp) else None
    counts: dict[str, int] = {}
    for q in qsos:
        counts[q.call.upper()] = counts.get(q.call.upper(), 0) + 1

    def add(q, level, text):
        out.append(Finding(q.id, q.call, q.band, q.time, level, text))

    for q in qsos:
        ev = scorer.evals.get(q.id)
        call = q.call.upper()
        base = max(call.split("/"), key=len)
        if ev is None:
            continue
        if ev.dupe:
            add(q, INFO, tr("Dupe – zählt 0 Punkte (bitte NICHT löschen)"))
        if ev.warning:
            add(q, WARN, ev.warning)
        if ev.lookup is None:
            add(q, WARN, tr("Präfix unbekannt – Rufzeichen prüfen"))
        err = contest.validate_exchange(q.exch_r, ev.lookup)
        if err:
            add(q, WARN, tr("Austausch „{exch_r}“: {err}", exch_r=q.exch_r, err=err))
        for note in contest.notes(q, ev.lookup):
            add(q, WARN, note)
        if scp_calls is not None and base not in scp_calls and counts[call] == 1:
            add(q, WARN, tr("Nicht in der SCP-Datenbank und nur einmal im Log – Hörfehler?"))
        if history is not None and contest.expected_kind(ev.lookup) == "cq_zone":
            h = history.get(call)
            if h and h.zone and q.exch_r.isdigit() and int(q.exch_r) != int(h.zone):
                add(q, WARN, tr("Zone {int} – laut Call-History sonst Zone {zone}", int=int(q.exch_r), zone=h.zone))
        if contest.uses_serial and q.exch_r.isdigit() and int(q.exch_r) == 0:
            add(q, WARN, tr("Empfangene Nummer 0"))
    from . import multiop
    cat = multiop.category(meta or {})
    # gesendete Nummern lückenlos? (WPX) – bei Multi-OP mit Nummern je Band: je Band
    if contest.uses_serial:
        parse = getattr(contest, "sent_serial", None) or \
            (lambda e: int(e) if e.strip().isdigit() else None)
        per_band = multiop.serial_mode(contest, cat) == "band"
        groups: dict[str, list] = {}
        for q in qsos:
            groups.setdefault(q.band if per_band else "", []).append(q)
        for band, lst in sorted(groups.items()):
            nums = sorted(n for n in (parse(q.exch_s) for q in lst) if n is not None)
            missing = sorted(set(range(1, nums[-1] + 1)) - set(nums)) if nums else []
            if missing:
                q0 = lst[0]
                txt = ", ".join(map(str, missing[:10])) + (" …" if len(missing) > 10 else "")
                txt = f"{band} m: {txt}" if band else txt
                out.append(Finding(q0.id, "", "", "", INFO,
                                   tr("Gesendete Nummern fehlen im Log: {txt} (z. B. gelöschte QSOs)", txt=txt)))
    # Multi-OP (ab 0.10.2): Bandwechsel-Regeln und Liste der Operatoren
    if cat:
        by_key = {(q.time[:16], q.call): q for q in qsos}
        for line in multiop.check_log(contest, cat, qsos):
            key = (line[:16], line[17:].split(" ", 1)[0])
            q0 = by_key.get(key) or qsos[0]
            out.append(Finding(q0.id, q0.call, q0.band, q0.time, WARN, line[17:]))
    ops = []
    for q in qsos:
        o = (getattr(q, "operator", "") or "").upper()
        if o and o not in ops:
            ops.append(o)
    if ops and qsos:
        out.append(Finding(qsos[0].id, "", "", "", INFO,
                           tr("Operatoren im Log ({n}): {ops} – bitte prüfen (Tippfehler?)",
                              n=len(ops), ops=", ".join(ops))))
    limit = getattr(contest, "max_changes_per_hour", None)
    if limit and qsos:
        from .stats import hours_over_limit
        for hour, n in hours_over_limit(qsos, limit):
            q0 = next(q for q in qsos if q.time.startswith(hour))
            out.append(Finding(q0.id, q0.call, q0.band, q0.time, WARN,
                               tr("{n} Band-/Modewechsel in der Stunde {p2}:00 UTC – erlaubt sind "
                                  "{limit} (Abzug durch den Veranstalter)", n=n, p2=hour[11:13], limit=limit)))
    total = getattr(contest, "max_changes_total", None)
    if total and qsos:
        from .stats import change_points
        pts = change_points(qsos)
        if len(pts) > total:
            q0 = pts[total]
            out.append(Finding(q0.id, q0.call, q0.band, q0.time, WARN,
                               tr("{n} Band-/Modewechsel im Contest – erlaubt sind {limit}; "
                                  "ab diesem QSO ist es zu viel", n=len(pts), limit=total)))
    return out
