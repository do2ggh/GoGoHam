"""Inhalt der Infobox zur Gegenstation (ohne Qt, damit testbar)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .bands import BAND_NAMES, band_label, cabrillo_mode, short_label
from .i18n import num, tr

MODE_NAME = {"PH": "SSB", "CW": "CW", "RY": "RTTY", "DG": "Digital"}
from .countries import flag_code, german_name
from .locator import is_grid, latlon, paths

NEW, WORKED, ASK = "new", "worked", "ask"   # Farb-Klassen für die Zeilen

MULT_LABEL = {"zone": tr("Zone"), "country": tr("Land"), "prefix": tr("Präfix"), "field": tr("Großfeld"),
              "state": tr("State"), "province": tr("Provinz"), "dok": tr("DOK"),
              "district": tr("Distrikt"), "area": tr("Gebiet"), "oblast": tr("Oblast"),
                 "iota": "IOTA"}
BAND_ORDER = BAND_NAMES


@dataclass
class InfoBox:
    name: str = ""
    prefix: str = ""          # Hauptpräfix (für das Ersatz-Schild)
    flag: str = ""            # Flaggen-Code, z. B. "au"
    cont: str = ""
    lines: list[tuple[str, str]] = field(default_factory=list)   # (Text, Klasse)
    path: str = ""            # SP/LP-Zeile
    empty: bool = True


def _bands_txt(bands) -> str:
    # Meter-Bänder kurz ("20, 40"), Zentimeter-Bänder mit Einheit ("2, 70 cm")
    ordered = sorted(bands, key=lambda b: BAND_ORDER.index(b) if b in BAND_ORDER else 99)
    return ", ".join(short_label(b) for b in ordered)


def _fmt_km(km: float) -> str:
    return num(km) + " km"


def build(contest, scorer, q, ev, my_grid: str) -> InfoBox:
    box = InfoBox()
    lk = ev.lookup if ev else None
    if not q.call:
        return box
    box.empty = False

    if lk is None:
        box.name = tr("Unbekanntes Präfix")
    elif lk.maritime:
        box.name = "Maritime Mobile"
        box.prefix = "MM"
    else:
        ent = lk.entity
        box.prefix = ent.prefix.lstrip("*")
        box.name = german_name(ent.prefix, ent.name)
        box.flag = flag_code(ent.prefix)
        box.cont = lk.cont or ""

    # --- Multi-Status
    new = set(ev.new_mults) if ev else set()
    mults = list(ev.mults) if ev else []
    cty = contest.cty
    if contest.expected_kind(lk) == "cq_zone" and lk and not lk.maritime and cty:
        if not any(t == "zone" for t, _v in mults):
            zones = sorted(cty.zones_for(lk))
            if len(zones) > 1:
                box.lines.append((tr("CQ-Zone: erfragen ({join})", join=' / '.join(map(str, zones))), ASK))
            else:
                box.lines.append((tr("CQ-Zone: {p1}", p1=zones[0] if zones else lk.cq), ASK))
    ask = contest.ask_text(q, lk) if hasattr(contest, "ask_text") else None
    if ask and not (q.exch_r or "").strip():
        box.lines.append((ask, ASK))
    for mtype, val in mults:
        label = MULT_LABEL.get(mtype, mtype)
        shown = box.name if mtype == "country" else val
        if (mtype, val) in new:
            other = _worked_bands(contest, scorer, mtype, val)
            per = getattr(contest, "mult_per", None) or ("band" if contest.mults_per_band else "once")
            mode_name = MODE_NAME.get(cabrillo_mode(q.mode), q.mode)
            where = {"band": tr(" auf {band}", band=band_label(q.band)),
                     "mode": tr(" in {mode}", mode=mode_name),
                     "band_mode": tr(" auf {band} in {mode}", band=band_label(q.band), mode=mode_name),
                     }.get(per, "")
            txt = tr("{label} {shown}: NEU", label=label, shown=shown) + where
            if other:
                txt += tr(" (schon auf {bands_txt})", bands_txt=_bands_txt(other))
            box.lines.append((txt, NEW))
        else:
            bands = _worked_bands(contest, scorer, mtype, val)
            if (contest.mults_per_band or getattr(contest, "mult_per", None) == "band_mode") \
                    and bands:
                box.lines.append((tr("{label} {shown}: gearbeitet auf {bands}", label=label, shown=shown, bands=_bands_txt(bands)), WORKED))
            else:
                box.lines.append((tr("{label} {shown}: schon gearbeitet", label=label, shown=shown), WORKED))

    # --- Richtung und Entfernung
    if is_grid(my_grid):
        p = path_info(contest, q, lk, my_grid)
        if p:
            box.path = (f"SP {p['sp_deg']:.0f}° · {_fmt_km(p['sp_km'])}     "
                        f"LP {p['lp_deg']:.0f}° · {_fmt_km(p['lp_km'])}")
    else:
        box.path = tr("Eigenen Locator eintragen, dann gibt's Richtung und Entfernung")
    return box


def path_info(contest, q, lk, my_grid: str) -> dict | None:
    """SP/LP-Richtung und Entfernung – im WW Digi aus dem Locator, sonst vom Land."""
    if not is_grid(my_grid):
        return None
    target = target_pos(contest, q, lk)
    if not target:
        return None
    me = latlon(my_grid)
    return paths(me[0], me[1], target[0], target[1])


def target_pos(contest, q, lk) -> tuple[float, float] | None:
    """Standort der Gegenstation: empfangener Locator, sonst aus cty.dat (Land/Gebiet)."""
    target = None
    exch = (q.exch_r or "").strip().upper()
    grid = contest.rcvd_grid6(q) if hasattr(contest, "rcvd_grid6") else ""
    if getattr(contest, "exchange_kind", "") == "grid4" and is_grid(exch):
        target = latlon(exch)
    elif grid:                                   # UKW: empfangener 6-stelliger Locator
        target = latlon(grid)
    elif lk and lk.lat is not None and lk.lon is not None:
        target = (lk.lat, lk.lon)
    elif lk and lk.entity:
        target = (lk.entity.lat, lk.entity.lon)
    return target


def _worked_bands(contest, scorer, mtype: str, val: str) -> set[str]:
    if not scorer:
        return set()
    out = set()
    for (t, b), vals in scorer.mults.items():
        if t == mtype and val in vals:
            out.add(b.split(":", 1)[0])
    out.discard("ALL")
    return out
