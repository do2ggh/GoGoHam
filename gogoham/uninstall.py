"""GoGoHam deinstallieren (ab 0.8.23.5) – ``bash ~/.local/share/gogoham/uninstall.sh``.

Grundsatz: Andere Programme müssen danach weiterlaufen. Deshalb werden
die rigctld/rotctld-Dienste von GoGoHam **nicht entfernt, sondern ans System übergeben**
(eigenständige Benutzerdienste ``rigctld-<Port>.service`` bzw. ``rotctld-<Port>.service``).

Entfernt werden: Programm, Startbefehl, Startmenü-Eintrag, Symbole. Auf Wunsch zusätzlich
Einstellungen und heruntergeladene Daten. **Die Logs (``~/GoGoHam``) werden nie gelöscht.**
"""

from __future__ import annotations

import glob
import os
import shutil
import sys

from . import rigservice


def paths(home: str | None = None) -> dict:
    home = home or os.path.expanduser("~")
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    conf = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(home, ".local", "state")
    return {
        "program": [os.path.join(data, "gogoham", "app"),
                    os.path.join(data, "gogoham", "update"),        # bereitgelegtes Update (0.10.47)
                    os.path.join(home, ".local", "bin",
                                                                        "gogoham"),
                    os.path.join(data, "applications", "gogoham.desktop"),
                    os.path.join(data, "metainfo", "io.github.do2ggh.GoGoHam.metainfo.xml"),
                    os.path.join(data, "gogoham", "uninstall.sh")]
        + sorted(glob.glob(os.path.join(data, "icons", "hicolor", "*", "apps", "gogoham.png"))),
        "settings": [os.path.join(conf, "gogoham"), os.path.join(state, "gogoham"),
                     os.path.join(data, "gogoham")],
        "logs": os.path.join(home, "GoGoHam"),
    }


def gogoham_units(directory: str | None = None) -> list[str]:
    d = directory or rigservice.unit_dir()
    return sorted(os.path.basename(f) for f in
                  glob.glob(os.path.join(d, "gogoham-rigctld-*.service")) +
                  glob.glob(os.path.join(d, "gogoham-rotctld-*.service")))


def handover_all(run=rigservice._run, directory: str | None = None) -> tuple[list[str], list[str]]:
    """Alle GoGoHam-Dienste übergeben. -> (neue Dienstnamen, Fehler)."""
    done, errors = [], []
    for unit in gogoham_units(directory):
        e = rigservice.handover(unit, run, directory)
        errors += e
        if not e:
            done.append(rigservice.handover_name(unit))
    return done, errors


def remove(items: list[str]) -> list[str]:
    removed = []
    for p in items:
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p, ignore_errors=True)
            removed.append(p)
        elif os.path.lexists(p):
            try:
                os.remove(p)
                removed.append(p)
            except OSError:
                pass
    return removed


def run_uninstall(purge: bool, run=rigservice._run, home: str | None = None,
                  unit_directory: str | None = None) -> dict:
    p = paths(home)
    services, errors = handover_all(run, unit_directory)
    removed = remove(p["program"])
    if purge:
        removed += remove(p["settings"])
    return {"services": services, "errors": errors, "removed": removed, "logs": p["logs"]}


def _ask(prompt: str, default: bool, answer=input) -> bool:
    a = answer(prompt + (" [J/n] " if default else " [j/N] ")).strip().lower()
    return default if not a else a.startswith(("j", "y"))


def main(argv: list[str] | None = None, answer=input, run=rigservice._run) -> int:
    argv = sys.argv[1:] if argv is None else argv
    yes = "--yes" in argv
    print("GoGoHam deinstallieren")
    print("======================")
    units = gogoham_units()
    if units:
        print("\nDiese Hintergrunddienste bleiben für andere Programme (Log-Programme, WSJT-X …)")
        print("erhalten und laufen als eigenständige Dienste weiter:")
        for u in units:
            print(f"  {u}  ->  {rigservice.handover_name(u)}")
    if not yes and not _ask("\nGoGoHam jetzt deinstallieren?", False, answer):
        print("Abgebrochen – nichts geändert.")
        return 1
    purge = "--purge" in argv or (not yes and _ask(
        "Auch Einstellungen und heruntergeladene Daten (Länderdatei, Kartenbilder …) löschen?\n"
        "(Deine Logs in ~/GoGoHam bleiben in jedem Fall erhalten.)", False, answer))
    res = run_uninstall(purge, run)
    print()
    for s in res["services"]:
        print(f"Dienst übergeben, läuft weiter: {s}")
    for e in res["errors"]:
        print(f"Fehler: {e}")
    print(f"Entfernt: {len(res['removed'])} Dateien/Ordner")
    print(f"Deine Logs liegen weiter in: {res['logs']}")
    print("GoGoHam ist deinstalliert. 73!")
    return 0 if not res["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
