"""0.10.3.2: Keine Thread-Unterklasse darf Namen benutzen, die threading.Thread selbst belegt.

Python 3.13 legt in jedem Thread z. B. „_handle“ an und überdeckt damit eine gleichnamige
Methode – unter 3.13 fand die Stationslog-Suche deshalb nie einen Hauptplatz (beim WinKey war
es 0.8.18.2 schon einmal so). Der Test prüft das unter jeder Python-Version.
"""

import ast
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "gogoham"
# auch Namen, die erst neuere/ältere Python-Versionen im Thread belegen
KNOWN = {"_handle", "_started", "_is_stopped", "_tstate_lock", "_ident", "_native_id",
         "_target", "_args", "_kwargs", "_name", "_daemonic", "_stderr", "_invoke_excepthook",
         "_bootstrap", "_bootstrap_inner", "_delete", "_stop", "_wait_for_tstate_lock",
         "_set_ident", "_set_native_id", "_set_tstate_lock", "_initialized", "_os_thread_handle"}
ALLOWED = {"run", "__init__", "__repr__", "start", "join", "is_alive", "name", "daemon"}


def test_no_thread_subclass_shadows_thread_internals():
    reserved = (set(dir(threading.Thread())) | set(vars(threading.Thread())) | KNOWN) - ALLOWED
    bad = []
    for f in ROOT.rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for c in ast.walk(tree):
            if not isinstance(c, ast.ClassDef) or not any("Thread" in ast.unparse(b)
                                                          for b in c.bases):
                continue
            for n in ast.walk(c):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in reserved:
                    bad.append(f"{f.name}: {c.name}.{n.name}()")
                elif (isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)
                      and isinstance(n.value, ast.Name) and n.value.id == "self"
                      and n.attr in reserved):
                    bad.append(f"{f.name}: {c.name}.{n.attr} =")
    assert bad == []
