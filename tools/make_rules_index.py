#!/usr/bin/env python3
"""Inhaltsverzeichnis rules/index.json für GitHub erzeugen.

Aufruf:  python3 tools/make_rules_index.py <Ordner mit den Regel-Dateien>
Prüft jede Datei mit derselben Regel-Prüfung wie GoGoHam und bricht bei Fehlern ab.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gogoham.rulesupdate import make_index  # noqa: E402

folder = Path(sys.argv[1] if len(sys.argv) > 1 else "gogoham/rules")
index = make_index(folder)
(folder / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
print(f"{folder / 'index.json'}: {len(index['rules'])} Contests")
