#!/bin/bash
# Test-Stick als Datei für die virtuelle Maschine (ohne Administratorrechte).
# Gleiche Aufteilung wie schreiben.sh, nur kleiner: Abbild + Datenteil + Austausch-Ordner.
set -euo pipefail
HIER="$(cd "$(dirname "$0")" && pwd -P)"   # echter Ort, auch über den Verweis ~/Projekte/gogoham-stick
ISO=${ISO:-$(ls -t "$HIER"/ausgabe/gogoham-live-*.iso | grep -v -- "-quellen\.iso$" | head -n1)}
IMG="$HIER/vm/stick.img"
GROESSE=${GROESSE:-12G}
TAUSCH=${TAUSCH:-2G}
cp --sparse=always "$ISO" "$IMG"
truncate -s "$GROESSE" "$IMG"
source "$HIER/aufteilung.sh"
aufteilen "$IMG" "$TAUSCH"
# Dateisysteme als Einzeldateien bauen und an ihre Stelle schreiben
read -r d_start d_size t_start t_size < <(lage "$IMG")
tmp=$(mktemp -d)
echo "/ union" > "$tmp/persistence.conf"
rm -f "$HIER/vm/daten.img" "$HIER/vm/tausch.img"
truncate -s $((d_size * 512)) "$HIER/vm/daten.img"
mkfs.ext4 -q -F -L GGH-DATEN -E lazy_itable_init=0,lazy_journal_init=0 -d "$tmp" "$HIER/vm/daten.img"
daten_schonen "$HIER/vm/daten.img"
truncate -s $((t_size * 512)) "$HIER/vm/tausch.img"
mkfs.exfat -q -L GoGoHam "$HIER/vm/tausch.img" >/dev/null
dd if="$HIER/vm/daten.img" of="$IMG" bs=4M seek=$((d_start * 512)) oflag=seek_bytes conv=notrunc,sparse status=none
dd if="$HIER/vm/tausch.img" of="$IMG" bs=4M seek=$((t_start * 512)) oflag=seek_bytes conv=notrunc,sparse status=none
rm -rf "$tmp" "$HIER/vm/daten.img" "$HIER/vm/tausch.img"
sfdisk -l "$IMG"
