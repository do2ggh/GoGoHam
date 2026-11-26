#!/usr/bin/env python3
"""Grundstock der Call-History (gogoham/assets/callhistory-base.csv) aus Logs erzeugen.

Aufruf:  python3 tools/make_callhistory_base.py LOG.cbr [LOG2.cbr …] [--add]
Übernommen werden nur Rufzeichen und feste Angaben (Zone, DOK, Locator …) mit Datum –
nie der Kopf des Logs (Name, Adresse, E-Mail). Mit --add bleibt der alte Grundstock
erhalten und die neuen Logs kommen dazu.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gogoham import callhistory as ch  # noqa: E402
from gogoham.cty import CtyDB  # noqa: E402


def main(args: list[str]) -> int:
    add = "--add" in args
    files = [a for a in args if a != "--add"]
    if not files:
        print(__doc__)
        return 1
    cty = CtyDB.load_default()
    rows = list(ch._base_rows()) if add else []
    h = ch.CallHistory()
    for f in files:
        n, learned, name = h.learn_file(f, cty)
        print(f"{Path(f).name}: {n} QSOs ({name}), {learned} Angaben")
    for call in h.calls():
        for key, (v, t, _src) in h.get(call).values.items():
            rows.append((call, key, v, t))
    n = ch.write_base(rows)
    print(f"Grundstock: {n} Einträge in {ch.BASE_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
