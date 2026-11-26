#!/usr/bin/env bash
# GoGoHam deinstallieren. rigctld/rotctld-Dienste laufen für andere Programme weiter,
# deine Logs (~/GoGoHam) bleiben immer erhalten. Optionen: --yes (ohne Fragen), --purge
# (auch Einstellungen und heruntergeladene Daten löschen).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -d "$HERE/gogoham" ]; then
    CODE="$HERE/gogoham"                                  # aus dem Quellordner
else
    CODE="${XDG_DATA_HOME:-$HOME/.local/share}/gogoham/app/gogoham"   # installiert
fi
if [ ! -d "$CODE" ]; then
    echo "GoGoHam ist nicht (mehr) installiert: $CODE fehlt."
    exit 1
fi
# Programm in einen Zwischenordner kopieren – das Original wird gleich gelöscht
TMP="$(mktemp -d)"
cp -r "$CODE" "$TMP/"
( cd "$TMP" && python3 -m gogoham.uninstall "$@" )
rc=$?
rm -rf "$TMP"
command -v update-desktop-database >/dev/null && \
    update-desktop-database "${XDG_DATA_HOME:-$HOME/.local/share}/applications" 2>/dev/null
exit $rc
