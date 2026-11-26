"""Export als Cabrillo 3.0 und ADIF 3."""

from __future__ import annotations

from . import __version__
from .bands import CABRILLO_VHF, adif_band, adif_mode, cabrillo_mode, has_unit
from .contests.base import Contest, Qso, Scorer


def _cab_freq(q: Qso) -> str:
    if q.band in CABRILLO_VHF:
        return CABRILLO_VHF[q.band]
    if q.freq:
        return str(int(round(q.freq / 1000)))
    from .bands import DEFAULT_FREQ
    return str(DEFAULT_FREQ.get(q.band, 0) // 1000)


def cabrillo_qso_line(c: Contest, q: Qso, mycall: str, tx_id: bool = False) -> str:
    date, _, t = q.time.partition(" ")
    hhmm = t.replace(":", "")[:4]
    mo = cabrillo_mode(q.mode)
    exch_s, exch_r = q.exch_s, q.exch_r
    fmt = getattr(c, "cabrillo_exchange", None)
    if fmt is not None:                      # DARC 10 m: Nummer und DOK in zwei Spalten
        exch_s = fmt(q.exch_s, c.sent_kind())
        exch_r = fmt(q.exch_r, c.expected_kind(c.lookup(q.call)))
    if c.uses_rst:
        sent = f"{q.rst_s:<3} {exch_s:<6}"
        rcvd = f"{q.rst_r:<3} {exch_r:<6}"
    else:
        sent = f"{exch_s:<6}"
        rcvd = f"{exch_r:<6}"
    return (f"QSO: {_cab_freq(q):>5} {mo} {date} {hhmm} {mycall:<13} {sent} "
            f"{q.call:<13} {rcvd} {(q.tx or '0') if tx_id else '0'}").rstrip()


def cabrillo(c: Contest, meta: dict, qsos: list[Qso], scorer: Scorer, qtcs=None) -> str:
    """Cabrillo 3.0. qtcs: empfangene QTCs (WAE) – stehen als „QTC:“-Zeilen nach den QSOs."""
    mycall = meta.get("mycall", "").upper()
    modes = {cabrillo_mode(q.mode) for q in qsos}
    cat_mode = {"PH": "SSB", "CW": "CW", "RY": "RTTY", "DG": "DIGI"}
    if len(modes) == 1:
        mode = cat_mode.get(modes.pop(), "MIXED")
    elif not modes:
        mode = cat_mode.get(next(iter(c.modes)), "MIXED")
    else:
        mode = "MIXED"
    lines = [
        "START-OF-LOG: 3.0",
        f"CONTEST: {c.cabrillo_name}",
        f"CALLSIGN: {mycall}",
        f"CATEGORY-OPERATOR: {meta.get('cat_operator', 'SINGLE-OP')}",
        f"CATEGORY-ASSISTED: {meta.get('cat_assisted', 'NON-ASSISTED')}",
        f"CATEGORY-BAND: {meta.get('cat_band', 'ALL')}",
        f"CATEGORY-MODE: {mode}",
        f"CATEGORY-POWER: {meta.get('cat_power', 'HIGH')}",
        f"CATEGORY-TRANSMITTER: {meta.get('cat_transmitter', 'ONE')}",
    ]
    pts = (getattr(c, "rules", None) or {}).get("points") or {}
    if pts.get("type") == "portable":         # Fieldday: portabel oder feste Station
        from .contests.rulebased import is_portable_call
        lines.append("CATEGORY-STATION: " + ("PORTABLE" if is_portable_call(mycall) else "FIXED"))
    if meta.get("cat_overlay"):
        lines.append(f"CATEGORY-OVERLAY: {meta['cat_overlay']}")
    if getattr(c, "_iota", False):             # IOTA: Insel- oder Weltstation
        island = bool(meta.get("my_iota"))
        loc = ("DXPEDITION" if meta.get("my_iota_dxped") else "NON-DXPEDITION") if island \
            else "WORLD"
        lines.append(f"CATEGORY-LOCATION: {loc}")
        if island and (meta.get("my_iota_island") or "").strip():
            lines.append(f"IOTA-ISLAND-NAME: {meta['my_iota_island'].strip()}")
    if getattr(c, "sent_kind", None) and c.sent_kind() == "oblast" and meta.get("my_oblast"):
        lines.append(f"LOCATION: {meta['my_oblast'].upper()}")   # Russian DX: eigener Oblast
    if meta.get("my_grid"):
        lines.append(f"GRID-LOCATOR: {meta['my_grid'].upper()}")
    lines.append(f"CLAIMED-SCORE: {scorer.score}")
    # Stationslog (ab 0.10): auch alle Operatoren, die an einem Platz QSOs geloggt haben
    ops = [o for o in str(meta.get("operators") or "").replace(",", " ").upper().split()]
    for q in qsos:
        o = (getattr(q, "operator", "") or "").upper()
        if o and o not in ops:
            ops.append(o)
    lines.append(f"OPERATORS: {' '.join(ops) or mycall}")
    for key, tag in (("club", "CLUB"), ("name", "NAME"), ("email", "EMAIL")):
        if meta.get(key):
            lines.append(f"{tag}: {meta[key]}")
    for addr in (meta.get("address") or "").splitlines():
        if addr.strip():
            lines.append(f"ADDRESS: {addr.strip()}")
    lines.append(f"CREATED-BY: GoGoHam {__version__}")
    for s in (meta.get("soapbox") or "").splitlines():
        if s.strip():
            lines.append(f"SOAPBOX: {s.strip()}")
    from . import multiop
    tx_id = multiop.needs_tx_id(c, multiop.category(meta))    # Sendernummer 0/1 (Multi-OP)
    for q in qsos:
        lines.append(cabrillo_qso_line(c, q, mycall, tx_id))
    if getattr(c, "qtc", None):
        from .qtc import cabrillo_line
        for t in qtcs or []:
            fq = Qso(band=t.band, freq=t.freq)
            lines.append(cabrillo_line(t, mycall, _cab_freq(fq), cabrillo_mode(t.mode)))
    lines.append("END-OF-LOG:")
    return "\n".join(lines) + "\n"


def _f(tag: str, val) -> str:
    val = "" if val is None else str(val)
    if val == "":
        return ""
    return f"<{tag}:{len(val.encode('utf-8'))}>{val} "


def adif(c: Contest, meta: dict, qsos: list[Qso], callbook: dict | None = None) -> str:
    """ADIF 3 mit allem, was GoGoHam weiß – für den Import in ein Log-Programm (z. B. QLog, CQRLOG, KLog).

    callbook: {Rufzeichen: {"name", "qth", "grid"}} aus HamQTH/QRZ.com.
    """
    from .contests.wpx import wpx_prefix
    from .locator import is_grid
    from .regions import normalize_province, normalize_section, normalize_state, normalize_xe_state

    callbook = callbook or {}
    cty = c.cty
    mycall = meta.get("mycall", "").upper()
    my_grid = meta.get("my_grid", "")
    out = [f"GoGoHam {__version__} ADIF-Export\n", _f("ADIF_VER", "3.1.4"),
           _f("PROGRAMID", "GoGoHam"), _f("PROGRAMVERSION", __version__), "<EOH>\n"]
    for q in qsos:
        date, _, t = q.time.partition(" ")
        mode, sub = adif_mode(q.mode)
        lk = cty.lookup(q.call) if cty else None
        kind = c.expected_kind(lk) if hasattr(c, "expected_kind") else ""
        rec = [
            _f("CALL", q.call),
            _f("QSO_DATE", date.replace("-", "")),
            _f("TIME_ON", t.replace(":", "")[:6]),
            _f("BAND", adif_band(q.band)),
            _f("FREQ", f"{q.freq / 1e6:.6f}" if q.freq else ""),
            _f("MODE", mode),
            _f("SUBMODE", sub),
            _f("RST_SENT", q.rst_s),
            _f("RST_RCVD", q.rst_r),
            _f("STX_STRING", q.exch_s),
            # freies Log (0.10.18): die Bemerkung gehört in COMMENT, nicht in den Austausch
            _f("COMMENT" if getattr(c, "free", False) else "SRX_STRING", q.exch_r),
            _f("CONTEST_ID", c.cabrillo_name),
            _f("STATION_CALLSIGN", mycall),
            _f("OPERATOR", (meta.get("operators") or mycall).split()[0] if (meta.get("operators") or mycall) else ""),
            _f("MY_GRIDSQUARE", my_grid if is_grid(my_grid) else ""),
            _f("MY_CQ_ZONE", meta.get("my_zone", "")),
        ]
        if c.uses_serial:
            parse = getattr(c, "sent_serial", None)
            n = parse(q.exch_s) if parse else (int(q.exch_s) if q.exch_s.isdigit() else None)
            if n is not None:
                rec.append(_f("STX", str(n)))
            rs = q.exch_r.split()[0] if q.exch_r.split() else ""
            if rs.isdigit():
                rec.append(_f("SRX", str(int(rs))))
        # --- DOK (DARC-Conteste)
        rd = c.rcvd_dok(q, lk) if hasattr(c, "rcvd_dok") else ""
        if rd and rd != "NM":
            rec.append(_f("DARC_DOK", rd))
        if getattr(c, "_has_dok", False) and meta.get("my_dok") and meta["my_dok"].upper() != "NM":
            rec.append(_f("MY_DARC_DOK", meta["my_dok"].upper()))
        # --- Land, Kontinent, Zonen
        if lk is not None and not lk.maritime and lk.entity:
            num, name = cty.dxcc_info(lk)
            rec.append(_f("COUNTRY", name))
            if num:
                rec.append(_f("DXCC", num))
            rec.append(_f("CONT", lk.cont))
            if kind == "iaru" and q.exch_r.isdigit():
                rec.append(_f("ITUZ", str(int(q.exch_r))))             # gehört = sicher
            elif not cty.multi_itu(lk) or (lk.itu and lk.itu != lk.entity.itu):
                rec.append(_f("ITUZ", lk.itu))
        cqz = ""
        if kind == "state" and normalize_state(q.exch_r):
            rec.append(_f("STATE", normalize_state(q.exch_r)))
        elif kind == "xe_state" and normalize_xe_state(q.exch_r):
            rec.append(_f("STATE", normalize_xe_state(q.exch_r)))
        elif kind == "province" and normalize_province(q.exch_r):
            rec.append(_f("VE_PROV", normalize_province(q.exch_r)))
        elif kind == "arrl_section" and normalize_section(q.exch_r):
            rec.append(_f("ARRL_SECT", normalize_section(q.exch_r)))      # ARRL 160 (0.10.31)
        elif kind == "power" and q.exch_r:
            rec.append(_f("RX_PWR", {"KW": "1000", "K": "1000"}.get(q.exch_r.upper(), q.exch_r)
                          if q.exch_r.isdigit() or q.exch_r.upper() in ("KW", "K") else ""))
        if kind == "cq_zone" and q.exch_r.isdigit():
            cqz = str(int(q.exch_r))                       # gehört = sicher
        elif lk is not None and lk.cq and not cty.multi_zone(lk):
            cqz = str(lk.cq)                               # Land mit nur einer Zone
        rec.append(_f("CQZ", cqz))
        rec.append(_f("PFX", wpx_prefix(q.call) or ""))
        # --- Locator, Name, QTH
        cb = callbook.get(q.call.upper(), {})
        grid = q.exch_r if getattr(c, "exchange_kind", "") == "grid4" and is_grid(q.exch_r) else cb.get("grid", "")
        rec.append(_f("GRIDSQUARE", grid if is_grid(grid) else ""))
        rec.append(_f("NAME", cb.get("name", "")))
        rec.append(_f("QTH", cb.get("qth", "")))
        out.append("".join(r for r in rec if r) + "<EOR>\n")
    return "".join(out)


# ------------------------------------------------------------ EDI (UKW, ab 0.8.8)
# Formatbeschreibung REG1TEST;1 (IARU Region 1, vom DARC verlinkt: ok2kkw.com/ediformat.htm)
EDI_BAND = {"6": "50 MHz", "4": "70 MHz", "2": "144 MHz", "70cm": "432 MHz",
            "23cm": "1,3 GHz", "13cm": "2,3 GHz", "9cm": "3,4 GHz", "6cm": "5,7 GHz",
            "3cm": "10 GHz", "1.25cm": "24 GHz", "6mm": "47 GHz", "4mm": "76 GHz",
            "2.5mm": "122 GHz", "2mm": "134 GHz", "1mm": "248 GHz", "submm": "300 GHz"}
EDI_SECTIONS = {"SO": "SINGLE", "MO": "MULTI", "SO-LP": "SINGLE-LP", "MO-LP": "MULTI-LP",
                "6H": "6H", "TR": "TRAINEE"}
_EDI_MODE = {"SSB": "1", "USB": "1", "LSB": "1", "PH": "1", "CW": "2", "CWR": "2", "CW-R": "2",
             "AM": "5", "FM": "6", "RTTY": "7", "RTTYR": "7"}
_ASCII = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
                        "ß": "ss", "ø": "o", "Ø": "O", "æ": "ae", "Æ": "Ae", "đ": "d", "ł": "l", "Ł": "L", "–": "-", "—": "-", "„": '"', "“": '"', "”": '"', "’": "'"})


def _edi_text(v) -> str:
    """Nur 7-Bit-ASCII ist erlaubt: Umlaute umschreiben, Rest durch „?“ ersetzen."""
    import unicodedata
    s = str(v or "").translate(_ASCII).replace("\r", " ").replace("\n", " ")
    s = unicodedata.normalize("NFKD", s)                 # é -> e + Akzent, Akzent fällt weg
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.encode("ascii", "replace").decode("ascii")


def edi_filename(path: str, band: str) -> str:
    """„…/cq.edi“ + Band -> „…/cq_2m.edi“ bzw. „…/cq_70cm.edi“."""
    from pathlib import Path
    p = Path(path)
    stem = p.stem if p.suffix.lower() == ".edi" else p.name
    suffix = band if has_unit(band) else f"{band}m"
    return str(p.with_name(f"{stem}_{suffix}.edi"))


def _nr(exch: str) -> str:
    first = (exch or "").strip().split()
    n = first[0] if first and first[0].isdigit() else ""
    return n.zfill(3) if n else ""


def edi(c: Contest, meta: dict, qsos: list[Qso], scorer: Scorer, band: str) -> bytes:
    """EDI-Datei (REG1TEST;1) für ein Band – Zeilenende CR LF, nur ASCII."""
    from .contests.rulebased import split_serial_grid
    mine = [q for q in qsos if q.band == band]
    mycall = (meta.get("mycall") or "").upper()
    ops = [o for o in (meta.get("operators") or "").replace(",", " ").split() if o]
    rcall = ops[0] if ops else mycall
    addr = [a.strip() for a in (meta.get("address") or "").splitlines() if a.strip()]
    dates = sorted(q.time[:10].replace("-", "") for q in mine if q.time)
    recs, wwls, dxccs, points, valid, odx = [], set(), set(), 0, 0, None
    for q in mine:
        ev = scorer.evals.get(q.id)
        dupe = bool(ev and ev.dupe)
        pts = 0 if dupe or ev is None or not ev.valid else ev.points
        _nr_r, grid = split_serial_grid(q.exch_r)
        new_wwl = new_dxcc = ""
        lk = ev.lookup if ev else None
        if not dupe and pts:
            valid += 1
            points += pts
            if grid[:4] and grid[:4] not in wwls:
                wwls.add(grid[:4])
                new_wwl = "N"
            if lk is not None and lk.country and lk.country not in dxccs:
                dxccs.add(lk.country)
                new_dxcc = "N"
            km = c.qso_km(q) if hasattr(c, "qso_km") else None
            if km is not None and (odx is None or km > odx[2]):
                odx = (q.call, grid, km)
        d, t = q.time[2:10].replace("-", ""), q.time[11:16].replace(":", "")
        recs.append(";".join([d, t, q.call.upper(), _EDI_MODE.get(q.mode.upper(), "0"),
                              q.rst_s, _nr(q.exch_s), q.rst_r, _nr(q.exch_r), "", grid,
                              str(pts), "", new_wwl, new_dxcc, "D" if dupe else ""]))
    head = {
        "TName": c.name,
        "TDate": f"{dates[0]};{dates[-1]}" if dates else "",
        "PCall": mycall,
        "PWWLo": (meta.get("my_grid") or "").upper(),
        "PExch": "",
        "PAdr1": addr[0] if addr else "",
        "PAdr2": addr[1] if len(addr) > 1 else "",
        "PSect": EDI_SECTIONS.get(meta.get("edi_section") or "", "")
        or ("MULTI" if meta.get("cat_operator") == "MULTI-OP" else "SINGLE"),
        "PBand": EDI_BAND.get(band, band),
        "PClub": meta.get("club", ""),
        "RName": meta.get("name", ""),
        "RCall": rcall,
        "RAdr1": addr[0] if addr else "",
        "RAdr2": addr[1] if len(addr) > 1 else "",
        "RPoCo": "", "RCity": "", "RCoun": "", "RPhon": "",
        "RHBBS": meta.get("email", ""),
        "MOpe1": ";".join(o for o in ops if o != rcall),
        "MOpe2": "",
        "STXEq": "",
        "SPowe": meta.get("my_power_w", ""),
        "SRXEq": "",
        "SAnte": meta.get("my_antenna", ""),
        "SAntH": "",
        "CQSOs": f"{valid};1",
        "CQSOP": str(points),
        "CWWLs": f"{len(wwls)};0;1", "CWWLB": "0",
        "CExcs": "0;0;1", "CExcB": "0",
        "CDXCs": f"{len(dxccs)};0;1", "CDXCB": "0",
        "CToSc": str(points),
        "CODXC": f"{odx[0]};{odx[1]};{int(odx[2]) + 1}" if odx else "",
    }
    lines = ["[REG1TEST;1]"] + [f"{k}={_edi_text(v)}" for k, v in head.items()]
    lines.append("[Remarks]")
    lines += [_edi_text(s) for s in (meta.get("soapbox") or "").splitlines() if s.strip()]
    lines.append(f"[QSORecords;{len(recs)}]")
    lines += [_edi_text(r) for r in recs]
    return ("\r\n".join(lines) + "\r\n").encode("ascii")
