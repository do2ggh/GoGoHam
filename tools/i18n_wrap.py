#!/usr/bin/env python3
"""Anzeigetexte im Quelltext in tr(...) einpacken (Hilfe für die Übersetzung, ab 0.8.0).

Aufruf:  python3 tools/i18n_wrap.py [--dry] datei.py …

* Einfache Texte:   "Log speichern"            -> tr("Log speichern")
* f-Strings:        f"{n} QSOs gespeichert"    -> tr("{n} QSOs gespeichert", n=n)
Eingepackt wird, was deutsche Wörter enthält oder als Argument einer Anzeige-Funktion
(setText, showMessage, QLabel, …) steht. Nicht angefasst werden Docstrings, Dict-Schlüssel,
Vergleiche, Texte schon in tr(…) und alles, was keine Buchstaben enthält.
Auf Deutsch ändert sich am Ergebnis nichts: tr() gibt den deutschen Text zurück.
"""

from __future__ import annotations

import ast
import keyword
import re
import sys

GER = re.compile(
    r"[äöüÄÖÜß„“]|\b(der|die|das|den|dem|des|und|oder|nicht|bitte|kein|keine|keinen|mit|für|"
    r"von|vom|zum|zur|ist|sind|wird|werden|zählt|nur|noch|schon|auch|eine|einen|einem|ein|"
    r"Rufzeichen|Datei|Fehler|Einstellungen|Funkgerät|speichern|öffnen|laden|gefunden|"
    r"verbunden|getrennt|aus|neu|Neu|erfragen|Austausch|Punkte|Pkt|Länder|Zonen|Präfix|"
    r"Gerät|Profil|Leistung|Jahr|Lizenz|Sicherung|Prüfung|Übersicht|Hilfe|Handbuch|"
    r"Abbrechen|Schließen|Beenden|Ansicht|Contest-Regeln|Regeln|Regel|Kategorie|Sender|"
    r"Name|Adresse|Betriebszeit|Pausen|Beginn|läuft|Stunde|Stunden|Minuten|Sekunden|"
    r"Wert|Multi|Dupe|empf|ges|Nr|Land|Kontinent|Entfernung|Richtung|Locator|Zone)\b")
UI_CALLS = {
    "setText": [0], "showMessage": [0], "setWindowTitle": [0], "setPlaceholderText": [0],
    "setToolTip": [0], "setStatusTip": [0], "addRow": [0], "QLabel": [0], "QPushButton": [0],
    "QCheckBox": [0], "QAction": [0], "addMenu": [0], "_act": [1], "_set_status": [0],
    "QGroupBox": [0], "addTab": [1], "information": [1, 2], "warning": [1, 2],
    "question": [1, 2], "critical": [1, 2], "getSaveFileName": [1, 3],
    "getOpenFileName": [1, 3], "QProgressDialog": [0, 1], "setLabelText": [0],
    "addButton": [0], "setHorizontalHeaderLabels": [0], "setSuffix": [0], "setPrefix": [0],
}
HAS_WORD = re.compile(r"[A-Za-zÄÖÜäöüß]{2,}")


def _call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


class Finder(ast.NodeVisitor):
    def __init__(self) -> None:
        self.targets: list[ast.AST] = []
        self.parents: dict[int, ast.AST] = {}
        self.skip: set[int] = set()
        self.ui: set[int] = set()

    def generic_visit(self, node):
        for child in ast.iter_child_nodes(node):
            self.parents[id(child)] = node
        super().generic_visit(node)

    def visit_Module(self, node):
        self._docstring(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self._docstring(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self._docstring(node)
        self.generic_visit(node)

    def _docstring(self, node):
        if node.body and isinstance(node.body[0], ast.Expr) and \
                isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
            self.skip.add(id(node.body[0].value))

    def visit_Dict(self, node):
        for k in node.keys:
            if k is not None:
                self.skip.add(id(k))
        self.generic_visit(node)

    def visit_Compare(self, node):
        for n in ast.walk(node):
            self.skip.add(id(n))
        self.generic_visit(node)

    def visit_Subscript(self, node):
        for n in ast.walk(node.slice):
            self.skip.add(id(n))
        self.generic_visit(node)

    def visit_Call(self, node):
        name = _call_name(node)
        if name == "tr":
            for n in ast.walk(node):
                self.skip.add(id(n))
        elif name in UI_CALLS:
            for i in UI_CALLS[name]:
                if i < len(node.args):
                    a = node.args[i]
                    if isinstance(a, (ast.List, ast.Tuple)):
                        for e in a.elts:
                            self.ui.add(id(e))
                    else:
                        self.ui.add(id(a))
        elif name in ("getattr", "setattr", "hasattr", "startswith", "endswith", "get",
                      "setdefault", "pop", "split", "replace", "join", "format", "strip",
                      "open", "compile", "match", "search", "fullmatch", "sub", "findall",
                      "Path", "glob", "environ", "getenv", "setProperty", "setObjectName",
                      "setStyleSheet", "QKeySequence", "translate"):
            for a in list(node.args) + [k.value for k in node.keywords]:
                if isinstance(a, ast.Constant):
                    self.skip.add(id(a))
        self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str) and id(node) not in self.skip:
            self.targets.append(node)

    def visit_JoinedStr(self, node):
        if id(node) not in self.skip:
            self.targets.append(node)
        for v in node.values:            # Teile eines f-Strings nicht einzeln einpacken
            self.skip.add(id(v))
            if isinstance(v, ast.FormattedValue) and v.format_spec is not None:
                for n in ast.walk(v.format_spec):
                    self.skip.add(id(n))
        self.generic_visit(node)


def _name_for(expr: ast.AST, used: set[str], i: int) -> str:
    if isinstance(expr, ast.Name):
        base = expr.id
    elif isinstance(expr, ast.Attribute):
        base = expr.attr
    elif isinstance(expr, ast.Call) and isinstance(expr.func, (ast.Name, ast.Attribute)):
        base = expr.func.id if isinstance(expr.func, ast.Name) else expr.func.attr
    else:
        base = f"p{i}"
    base = re.sub(r"\W", "_", base).strip("_") or f"p{i}"
    if keyword.iskeyword(base) or base in ("text", "kw") or base[0].isdigit():
        base = f"{base}_"
    name, n = base, 2
    while name in used:
        name, n = f"{base}{n}", n + 1
    used.add(name)
    return name


def _fstring_template(node: ast.JoinedStr, src: str) -> tuple[str, list[tuple[str, str]]] | None:
    parts, args, used = [], [], set()
    for i, v in enumerate(node.values):
        if isinstance(v, ast.Constant):
            parts.append(v.value.replace("{", "{{").replace("}", "}}"))
        elif isinstance(v, ast.FormattedValue):
            expr_src = ast.get_source_segment(src, v.value)
            if expr_src is None:
                return None
            name = _name_for(v.value, used, i)
            conv = {-1: "", 115: "!s", 114: "!r", 97: "!a"}[v.conversion]
            spec = ""
            if v.format_spec is not None:
                if not all(isinstance(x, ast.Constant) for x in v.format_spec.values):
                    return None
                spec = ":" + "".join(x.value for x in v.format_spec.values)
            parts.append("{" + name + conv + spec + "}")
            args.append((name, " ".join(expr_src.split())))
        else:
            return None
    return "".join(parts), args


def _literal(s: str, indent: int) -> str:
    """Python-Textliteral, lange Texte als implizite Verkettung über mehrere Zeilen."""
    r = repr(s)
    if r.startswith("'") and '"' not in s:
        r = '"' + r[1:-1].replace("\\'", "'") + '"'
    if len(r) <= 80:
        return r
    chunks, cur = [], ""
    for word in re.split(r"(?<= )", s):
        if len(cur) + len(word) > 64 and cur:
            chunks.append(cur)
            cur = ""
        cur += word
    if cur:
        chunks.append(cur)
    lits = [_literal(c, 0) if len(repr(c)) <= 80 else repr(c) for c in chunks]
    return ("\n" + " " * (indent + 3)).join(lits)


def wrap(src: str) -> tuple[str, int]:
    tree = ast.parse(src)
    f = Finder()
    f.visit(tree)
    lines = src.splitlines(keepends=True)
    offs = [0]
    for ln in lines:
        offs.append(offs[-1] + len(ln.encode("utf-8")))
    b = src.encode("utf-8")
    edits = []
    for node in f.targets:
        if isinstance(node, ast.Constant):
            text = node.value
            if not HAS_WORD.search(text):
                continue
            if not (GER.search(text) or id(node) in f.ui):
                continue
            seg = b[offs[node.lineno - 1] + node.col_offset: offs[node.end_lineno - 1] + node.end_col_offset].decode()
            new = f"tr({seg})"
        else:
            lit = "".join(v.value for v in node.values if isinstance(v, ast.Constant))
            if not HAS_WORD.search(lit) or not GER.search(lit):
                continue
            res = _fstring_template(node, src)
            if res is None:
                print(f"  ! übersprungen (zu verschachtelt), Zeile {node.lineno}", file=sys.stderr)
                continue
            tmpl, args = res
            indent = node.col_offset
            kw = ", ".join(f"{n}={e}" for n, e in args)
            new = f"tr({_literal(tmpl, indent)}" + (f", {kw})" if kw else ")")
        start = offs[node.lineno - 1] + node.col_offset
        end = offs[node.end_lineno - 1] + node.end_col_offset
        edits.append((start, end, new))
    for start, end, new in sorted(edits, reverse=True):
        b = b[:start] + new.encode("utf-8") + b[end:]
    out = b.decode("utf-8")
    ast.parse(out)                      # muss gültiges Python bleiben
    return out, len(edits)


def ensure_import(src: str, path: str) -> str:
    if re.search(r"^from \S*i18n import .*\btr\b", src, re.M):
        return src
    depth = path.replace("\\", "/").split("gogoham/", 1)[-1].count("/")
    mod = "." * (depth + 1) + "i18n"
    line = f"from {mod} import tr\n"
    m = re.search(r"^from __future__ import annotations\n", src, re.M)
    if m:
        return src[:m.end()] + "\n" + line + src[m.end():]
    return line + src


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    for p in [a for a in sys.argv[1:] if not a.startswith("--")]:
        src = open(p, encoding="utf-8").read()
        out, n = wrap(src)
        if n and not dry:
            out = ensure_import(out, p)
            open(p, "w", encoding="utf-8").write(out)
        print(f"{p}: {n} Texte {'(Probe)' if dry else 'eingepackt'}")
