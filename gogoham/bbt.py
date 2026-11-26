"""Bayerischer Bergtag (ab 0.10.42): BBT-Deckblatt und Logblatt als Textdatei, je Band eine.

Die Ausschreibung (7.1) verlangt ein BBT-Deckblatt (Auswertebogen) und Logblätter mit den
Spalten Zeit (UTC) | Rufzeichen | RST-gesendet | RST-empfangen | Locator | km | Bem. – ausdrücklich
kein EDI. Das Formular „Version 01/2026“ ist nur ein Muster; die vom Veranstalter empfohlene
(Windows-)Software schickt selbst ein nachgebautes Text-Deckblatt. GoGoHam baut das Formular
Zeile für Zeile nach; der Teil „vom Auswerter auszufüllen“ bleibt leer.

Die Angaben, die nicht im Log stehen (Standort, Höhe, Station, Gewichte …), liegen im Log unter
dem Schlüssel „bbt“ (JSON): {"site", "asl", "phone", "combi", "combi_max", "remarks",
"bands": {Band: {"tx", "pout", "rx", "stage", "ant", "code", "agl", "kg_tx", "kg_rx", "kg_ant"}}}.
Der Inhalt der Datei ist bewusst deutsch – er geht an den deutschen Auswerter (Windows-Zeichensatz).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .bands import has_unit

# Sektionen laut Ausschreibung (5) bzw. Deckblatt 01/2026
SECTIONS = {"2": ("A", "144 MHz"), "70cm": ("B", "432 MHz"), "23cm": ("C", "1296 MHz"),
            "13cm": ("D", "2320 MHz"), "9cm": ("E", "3400 MHz"), "6cm": ("F", "5760 MHz"),
            "3cm": ("G", "10 GHz"), "1.25cm": ("H", "24 GHz"), "6mm": ("I", "47 GHz"),
            "4mm": ("J", "76 GHz"), "2.5mm": ("K", "122-245 GHz"), "2mm": ("K", "122-245 GHz"),
            "1mm": ("K", "122-245 GHz"), "submm": ("L", ">=300 GHz")}
MAX_KG = 10.0
MAX_W = 10.0
LINES_PER_SHEET = 50
W = 78


def is_bbt(contest) -> bool:
    from .submit import current_rules             # auch für Logs von vor 0.10.42
    return any(r.get("cover_sheet") == "bbt" for r in current_rules(contest))


def load(meta: dict) -> dict:
    try:
        d = json.loads(meta.get("bbt") or "{}")
    except ValueError:
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("bands", {})
    return d


def dump(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


def number(v) -> float | None:
    """„1,5“ oder „1.5“ -> 1.5; leer/unlesbar -> None."""
    try:
        return float(str(v).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def total_kg(b: dict) -> float:
    return sum(number(b.get(k)) or 0.0 for k in ("kg_tx", "kg_rx", "kg_ant"))


def _fmt(x: float) -> str:
    return (f"{x:.1f}".rstrip("0").rstrip(".")).replace(".", ",")


def season(start) -> str:
    """Winter-BBT im Februar, sonst Sommer-BBT (Ausschreibung 10)."""
    return "Winter" if start.month <= 3 else "Sommer"


def home_call(call: str) -> str:
    """„DL1ABC/P“ -> „DL1ABC“ (das längste Stück ohne Zusatz)."""
    parts = [p for p in (call or "").upper().split("/") if p]
    return max(parts, key=len) if parts else ""


def stats(c, scorer, qsos, band: str) -> dict:
    """Zahlen fürs Deckblatt und die Logzeilen eines Bandes."""
    from .contests.rulebased import split_serial_grid
    rows, total, n, odx, countries = [], 0, 0, None, []
    for q in sorted((q for q in qsos if q.band == band), key=lambda q: (q.time, q.id or 0)):
        ev = scorer.evals.get(q.id)
        dupe = bool(ev and ev.dupe)
        km = 0 if dupe or ev is None or not ev.valid else int(ev.points)
        nr_r, grid = split_serial_grid(q.exch_r)
        nr_s = ((q.exch_s or "").split() or [""])[0]
        rem = "Dupe" if dupe else ("ohne Locator" if not grid else "")
        if km:
            n += 1
            total += km
            if odx is None or km > odx[0]:
                odx = (km, q.call.upper(), grid)
            ctry = ev.lookup.country if ev and ev.lookup else None
            if ctry and ctry not in countries:
                countries.append(ctry)
        elif not dupe and ev is not None and ev.valid and grid:
            n += 1                                  # gültig, aber 0 km (gleiches Feld)
        rows.append({"time": q.time[11:16].replace(":", ""), "date": q.time[:10],
                     "call": q.call.upper(),
                     "sent": f"{q.rst_s}{nr_s.zfill(3) if nr_s.isdigit() else nr_s}",
                     "rcvd": f"{q.rst_r}{nr_r.zfill(3) if nr_r else ''}",
                     "grid": grid, "km": km, "rem": rem})
    return {"rows": rows, "km": total, "qsos": n, "odx": odx, "countries": countries}


def _line(label: str, value: str = "", right: str = "") -> str:
    left = (f"{label:<20}" if len(label) < 20 else label + " ") + value
    return f"{left:<52}{right}".rstrip() if right else left.rstrip()


def cover_sheet(c, meta: dict, st: dict, band: str, start, today: date | None = None) -> list[str]:
    d = load(meta)
    b = d["bands"].get(band, {})
    sec, freq = SECTIONS.get(band, ("?", band))
    call = (meta.get("mycall") or "").upper()
    seas = season(start)
    day = st["rows"][0]["date"] if st["rows"] else start.strftime("%Y-%m-%d")
    y, m, dd = day.split("-")
    addr = ", ".join(a.strip() for a in (meta.get("address") or "").splitlines() if a.strip())
    combi = d.get("combi") == "ja"
    kg = total_kg(b)
    odx = st["odx"]
    per = round(st["km"] / st["qsos"]) if st["qsos"] else 0
    today = today or date.today()
    out = [
        "DARC/BBT - VHF - UHF - SHF - CONTEST".center(W).rstrip(),
        "BBT-Deckblatt (Auswertebogen) nach Formular Version 01/2026".center(W).rstrip(),
        "=" * W,
        "vom Auswerter auszufüllen:",
        "Log eingegangen am: ________  Poststempel vom: ________  Logabgabetermin: ________",
        "Kontroll-Log: ____   Bemerkungen: ____________________________________________",
        "Auswerter: __________  Call: ________  ausgewertet am: ________  Unterschrift: ______",
        "Auswertung:  vom Teilnehmer angegebene Gesamtkilometerzahl ........ km",
        "             abzüglich ........ km    (Kontroll-Log) ........ km",
        "             bewertete Gesamtkilometerzahl ........ km   Platz ....   Multiplikator ....",
        "             Wertungsliste gefordert: Ja / Nein",
        "             Gesamtpunktezahl für die gearbeitete Sektion ........",
        "-" * W,
        "vom Teilnehmer auszufüllen:",
        _line("BBT-Call:", call),
        _line("BBT:", ("[X] Winter  [ ] Sommer" if seas == "Winter" else "[ ] Winter  [X] Sommer"),
              f"BBT vom: {dd}.{m}.{y}"),
        _line("Sektion:", f"{sec}  {freq}"),
        _line("Name:", meta.get("name", ""), f"Telefon: {d.get('phone', '')}"),
        _line("Call:", home_call(call)),
        _line("Anschrift:", addr),
        _line("DOK:", (meta.get("my_dok") or "").upper()),
        _line("BBT-Standort:", d.get("site", ""), f"Locator: {(meta.get('my_grid') or '').upper()}"),
        _line("Höhe ASL:", f"{d.get('asl', '')} m" if d.get("asl") else ""),
        _line("Kombistation:", "ja" if combi else "nein",
              f"höchste Frequenz: {d.get('combi_max', '')}" if combi else ""),
        "",
        f"{'Station (max. 10 W)':<60}Gewicht",
        f"{'  TX:  ' + b.get('tx', '') + '   Pout: ' + (b.get('pout', '') + ' W' if b.get('pout') else ''):<60}"
        f"{_fmt(number(b.get('kg_tx')) or 0)} kg",
        f"{'  RX:  ' + b.get('rx', '') + '   Eing.st.: ' + b.get('stage', ''):<60}"
        f"{_fmt(number(b.get('kg_rx')) or 0)} kg",
        f"{'  ANT: ' + b.get('ant', '') + '   Code: ' + b.get('code', ''):<60}"
        f"{_fmt(number(b.get('kg_ant')) or 0)} kg",
        f"{'         über Grund: ' + (b.get('agl', '') + ' m' if b.get('agl') else '')}",
        f"{'  Gesamtgewicht (maximal 10 kg):':<60}{_fmt(kg)} kg",
        "",
        _line("Gesamtkilometerzahl:", f"{st['km']} km",
              f"Anzahl der Verbindungen: {st['qsos']}  km/QSO: {per}"),
        _line("Best DX:", f"{odx[0]} km" if odx else "",
              f"Call: {odx[1]}  Locator: {odx[2]}" if odx else ""),
        _line("gearbeitete Länder:", ", ".join(st["countries"]),
              f"Anzahl: {len(st['countries'])}"),
        "",
        "Ich bestätige die Richtigkeit dieser Angaben:",
        f"Datum: {today.strftime('%d.%m.%Y')}   {home_call(call)}   Unterschrift: ____________________",
        "",
        "Bemerkungen (Wetter, Cond. usw.):",
    ]
    rem = [r for r in (d.get("remarks") or meta.get("soapbox") or "").splitlines() if r.strip()]
    out += ["  " + r for r in rem] or [""]
    return out


def log_sheets(meta: dict, st: dict, band: str, start) -> list[str]:
    sec, freq = SECTIONS.get(band, ("?", band))
    call = (meta.get("mycall") or "").upper()
    grid = (meta.get("my_grid") or "").upper()
    day = st["rows"][0]["date"] if st["rows"] else start.strftime("%Y-%m-%d")
    y, m, dd = day.split("-")
    rows = st["rows"]
    pages = [rows[i:i + LINES_PER_SHEET] for i in range(0, len(rows), LINES_PER_SHEET)] or [[]]
    head = f"{'Time':<6}{'Call':<14}{'RST+Nr':<9}{'RST+Nr':<9}{'Locator':<9}{'km':>6}  Bem."
    sub = f"{'(UTC)':<6}{'':<14}{'gesendet':<9}{'empfang.':<9}"
    out = []
    for i, page in enumerate(pages, 1):
        if out:
            out.append("\f")                       # neues Blatt beim Ausdruck
        out += [f"{season(start)}-BBT   BBT-Log für Sektion {sec} ({freq})   Datum: {dd}.{m}.{y}",
                f"CALL: {call}   Locator: {grid}   Bl: {i}/{len(pages)}",
                "-" * W, head, sub.rstrip(), "-" * W]
        for r in page:
            out.append(f"{r['time']:<6}{r['call']:<14}{r['sent']:<9}{r['rcvd']:<9}{r['grid']:<9}"
                       f"{r['km']:>6}  {r['rem']}".rstrip())
        out += ["-" * W,
                f"{'Zwischensumme Blatt ' + str(i) + ':':<47}{sum(r['km'] for r in page):>6} km"]
    out.append(f"{'Summe:':<47}{st['km']:>6} km")
    return out


def sheet(c, meta: dict, qsos, scorer, band: str, start, today: date | None = None) -> bytes:
    """Deckblatt + Logblatt eines Bandes als Textdatei – CR LF und Windows-Zeichensatz (cp1252)
    wie die Windows-Software des Veranstalters; unbekannte Zeichen werden zu „?“."""
    st = stats(c, scorer, qsos, band)
    lines = cover_sheet(c, meta, st, band, start, today) + ["", "\f"] + log_sheets(meta, st, band, start)
    return ("\r\n".join(lines) + "\r\n").encode("cp1252", errors="replace")


def filename(path: str, call: str, band: str) -> str:
    """„…/log.txt“ + Band -> „…/DL1ABC_A_2m.txt“ (Rufzeichen, Sektion, Band)."""
    p = Path(path)
    sec = SECTIONS.get(band, ("X", ""))[0]
    b = band if has_unit(band) else f"{band}m"
    c = home_call(call) or "BBT"
    return str(p.with_name(f"{c}_{sec}_{b}.txt"))


def warnings(d: dict, bands) -> list[str]:
    """Hinweise für das Eingabefenster (nicht für die Datei)."""
    from .i18n import tr
    out = []
    for band in bands:
        b = d["bands"].get(band, {})
        kg = total_kg(b)
        if kg > MAX_KG:
            out.append(tr("⚠ {band}: Gesamtgewicht {kg} kg – erlaubt sind höchstens 10 kg.",
                          band=band if has_unit(band) else f"{band} m", kg=_fmt(kg)))
        w = number(b.get("pout"))
        if w is not None and w > MAX_W:
            out.append(tr("⚠ {band}: {w} W – erlaubt sind höchstens 10 W.",
                          band=band if has_unit(band) else f"{band} m", w=_fmt(w)))
    return out
