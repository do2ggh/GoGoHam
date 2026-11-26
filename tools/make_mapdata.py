"""Kartendaten für die Grayline-Karte (ab 0.8.15) aus Natural Earth (gemeinfrei) erzeugen.

Aufruf (alle Dateien aus https://github.com/nvkelso/natural-earth-vector, Ordner geojson/):

  python3 -I tools/make_mapdata.py ORDNER gogoham/assets/world.json

ORDNER enthält ne_10m_land, ne_10m_minor_islands, ne_10m_admin_0_boundary_lines_land,
ne_10m_lakes, ne_10m_rivers_lake_centerlines und ne_10m_populated_places (.geojson).
„Made with Natural Earth“ – gemeinfrei.

Ergebnis (Format 2): Linien/Flächen als [lon, lat, dlon, dlat, …] in 1/100 Grad (ganze Zahlen):
erster Punkt absolut, danach Abstand zum vorigen; Punkte näher als MIN_STEP am vorigen fallen
weg. Flüsse/Seen mit Rang vorn (0 = groß … 10 = klein), Orte als [Name englisch, lat, lon,
Rang, Hauptstadt, Name deutsch oder ""]. Lesen: gogoham/worldmap.py.
"""

import json
import sys
from pathlib import Path

MIN_STEP = 2          # 1/100 Grad: Punkte näher als ~2 km am vorigen fallen weg


def parts(geom: dict, kind: str):
    t, c = geom["type"], geom["coordinates"]
    if kind == "poly":
        if t == "Polygon":
            yield from c                   # Außenring + Löcher
        elif t == "MultiPolygon":
            for poly in c:
                yield from poly
    else:
        if t == "LineString":
            yield c
        elif t == "MultiLineString":
            yield from c


def pack(ring) -> list[int]:
    pts = [(round(lon * 100), round(lat * 100)) for lon, lat, *_ in ring]
    out, last = [], None
    for i, p in enumerate(pts):
        end = i == len(pts) - 1                       # Endpunkt immer behalten (Ring zu)
        if last is None or end or max(abs(p[0] - last[0]), abs(p[1] - last[1])) >= MIN_STEP:
            if p != last:
                # als Abstand zum vorigen Punkt (kleine Zahlen = kleine Datei)
                out.extend(p if last is None else (p[0] - last[0], p[1] - last[1]))
                last = p
    return out


def features(folder: Path, name: str) -> list[dict]:
    return json.loads((folder / f"{name}.geojson").read_text(encoding="utf-8"))["features"]


def collect(folder: Path, name: str, kind: str, ranked: bool = False) -> list:
    res = []
    for f in features(folder, name):
        rank = int(f["properties"].get("scalerank") or 0)
        for ring in parts(f["geometry"], kind):
            r = pack(ring)
            if len(r) >= 4:
                res.append([rank] + r if ranked else r)
    return res


def places(folder: Path) -> list:
    """Orte: [englischer Name, lat, lon, Rang, Hauptstadt, deutscher Name falls anders]."""
    out = []
    for f in features(folder, "ne_10m_populated_places"):
        p = f["properties"]
        en = p.get("NAME_EN") or p.get("NAME") or p.get("NAMEASCII")
        de = p.get("NAME_DE") or ""
        rank = p.get("SCALERANK")
        out.append([en, round(p["LATITUDE"] * 100), round(p["LONGITUDE"] * 100),
                    10 if rank is None else int(rank), 1 if p.get("ADM0CAP") else 0,
                    de if de and de != en else ""])
    out.sort(key=lambda x: (x[3], x[0]))
    return out


def main() -> None:
    folder, out_path = Path(sys.argv[1]), sys.argv[2]
    data = {"format": 2,
            "source": "Made with Natural Earth (public domain), naturalearthdata.com – 1:10m",
            "land": collect(folder, "ne_10m_land", "poly")
            + collect(folder, "ne_10m_minor_islands", "poly"),
            "borders": collect(folder, "ne_10m_admin_0_boundary_lines_land", "line"),
            "lakes": collect(folder, "ne_10m_lakes", "poly", ranked=True),
            "rivers": collect(folder, "ne_10m_rivers_lake_centerlines", "line", ranked=True),
            "places": places(folder)}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
    print(out_path, {k: len(v) for k, v in data.items() if isinstance(v, list)})


if __name__ == "__main__":
    main()
