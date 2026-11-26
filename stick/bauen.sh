#!/bin/bash
# GoGoHam-Live-Stick bauen (Debian 13 + KDE). Start:  sudo bash bauen.sh
# Baut in einem Debian-Container; das Ergebnis liegt danach im Ordner „ausgabe“.
# Für eine Veröffentlichung zusätzlich das Quellcode-Abbild (GPL, einige GB, dauert länger):
#   sudo QUELLEN=1 bash bauen.sh
set -euo pipefail
HIER="$(cd "$(dirname "$0")" && pwd -P)"   # echter Ort, auch über den Verweis ~/Projekte/gogoham-stick
SRC="${GOGOHAM_SRC:-$HIER/..}"          # der Stick liegt im GoGoHam-Projekt (stick/)
if [ "$(id -u)" -ne 0 ]; then
    echo "Bitte so starten:  sudo bash $0"
    exit 1
fi
mkdir -p "$HIER/ausgabe"
podman run --rm --privileged --network host -e QUELLEN="${QUELLEN:-0}" \
    -v "$HIER:/stick" -v "$SRC:/src:ro" \
    docker.io/library/debian:trixie bash /stick/im-container.sh
chown -R "$(stat -c %u:%g "$HIER")" "$HIER/ausgabe"
# Platz sparen (Nutzer 2026-11-13): nur das neue und das vorherige Abbild behalten
ls -t "$HIER"/ausgabe/gogoham-live-*.iso 2>/dev/null | grep -v -- '-quellen\.iso$' | tail -n +3 | while read -r alt; do
    v=${alt##*/gogoham-live-}; v=${v%.iso}
    echo "Altes Abbild entfernt: ${alt##*/}"
    rm -f "$alt" "$HIER/ausgabe/gogoham_${v}_all.deb"
done
# vom Quellcode-Abbild nur das neueste behalten
ls -t "$HIER"/ausgabe/gogoham-live-*-quellen.iso 2>/dev/null | tail -n +2 | while read -r alt; do
    echo "Altes Quellcode-Abbild entfernt: ${alt##*/}"; rm -f "$alt"
done
echo
echo "Fertig. Das Abbild liegt in: $HIER/ausgabe"
