#!/usr/bin/env python3
"""Regel-Dateien einheitlich und gut lesbar formatieren (kurze Listen in einer Zeile).

Aufruf:  python3 tools/format_rules.py gogoham/rules/*.json
"""
import json
import sys


def fmt(v, ind=0):
    pad = "  " * (ind + 1)
    if isinstance(v, dict):
        flat = all(not isinstance(x, (dict, list)) for x in v.values())
        one = json.dumps(v, ensure_ascii=False)
        if flat and len(one) <= 80 and ind > 0:
            return one
        items = [f"{pad}{json.dumps(k)}: {fmt(x, ind + 1)}" for k, x in v.items()]
        return "{\n" + ",\n".join(items) + "\n" + "  " * ind + "}"
    if isinstance(v, list):
        one = json.dumps(v, ensure_ascii=False)
        if len(one) <= 90:
            return one
        if all(not isinstance(x, (dict, list)) for x in v):
            lines, cur = [], []
            for x in v:
                cur.append(json.dumps(x, ensure_ascii=False))
                if len(", ".join(cur)) > 70:
                    lines.append(", ".join(cur))
                    cur = []
            if cur:
                lines.append(", ".join(cur))
            return "[\n" + ",\n".join(pad + ln for ln in lines) + "\n" + "  " * ind + "]"
        return "[\n" + ",\n".join(pad + fmt(x, ind + 1) for x in v) + "\n" + "  " * ind + "]"
    return json.dumps(v, ensure_ascii=False)


def write(path, data):
    text = fmt(data) + "\n"
    assert json.loads(text) == data
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        with open(p, encoding="utf-8") as fh:
            write(p, json.load(fh))
        print("formatiert:", p)
