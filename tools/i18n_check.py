#!/usr/bin/env python3
"""Übersetzungen prüfen: welche Texte fehlen in einer Sprachdatei, welche sind veraltet?

Aufruf:
  python3 tools/i18n_check.py en              # Bericht
  python3 tools/i18n_check.py en --update     # fehlende Texte (leer) ergänzen, veraltete entfernen
Leere Einträge bedeuten „noch nicht übersetzt“ – GoGoHam zeigt dann den deutschen Text.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "gogoham"
LANG_DIR = PKG / "i18n"


def collect() -> dict[str, str]:
    """Alle Texte aus tr("…")-Aufrufen: Text -> erste Fundstelle."""
    out: dict[str, str] = {}
    for p in sorted(PKG.rglob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr" \
                    and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                out.setdefault(node.args[0].value, f"{p.relative_to(ROOT)}:{node.lineno}")
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    lang = sys.argv[1]
    path = LANG_DIR / f"{lang}.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    meta = data.pop("_meta", {"name": lang})
    keys = collect()
    missing = [k for k in keys if not data.get(k)]
    obsolete = [k for k in data if k not in keys]
    print(f"{len(keys)} Texte im Programm · {len(keys) - len(missing)} übersetzt · "
          f"{len(missing)} fehlen · {len(obsolete)} veraltet")
    for k in missing[:40]:
        print(f"  fehlt: {k!r}  ({keys[k]})")
    if "--update" in sys.argv:
        new = {"_meta": meta}
        for k in keys:
            new[k] = data.get(k, "")
        LANG_DIR.mkdir(exist_ok=True)
        path.write_text(json.dumps(new, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"geschrieben: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
