#!/bin/bash
# GoGoHam-Live-Stick auf einen USB-Stick schreiben.  Start:  sudo bash schreiben.sh
# ACHTUNG: Alles auf dem gewählten Stick wird gelöscht.
set -euo pipefail
HIER="$(cd "$(dirname "$0")" && pwd -P)"   # echter Ort, auch über den Verweis ~/Projekte/gogoham-stick
# Größe des Austausch-Ordners: passt sich dem Stick an (2–16 GB), Rest = Datenteil.
# Von Hand vorgeben geht weiter:  sudo TAUSCH=8G bash schreiben.sh
TAUSCH=${TAUSCH:-}
ISO=$(ls -t "$HIER"/ausgabe/gogoham-live-*.iso 2>/dev/null | grep -v -- "-quellen\.iso$" | head -n1)   # neuestes, nicht nach Name (0.10.10 < 0.10.8); nie die Quellen-ISO

[ "$(id -u)" -eq 0 ] || { echo "Bitte so starten:  sudo bash $0"; exit 1; }
[ -n "$ISO" ] || { echo "Kein Abbild in $HIER/ausgabe – erst bauen (bauen.sh)."; exit 1; }

echo "Abbild: $ISO"
echo
echo "Angeschlossene USB-Laufwerke:"
mapfile -t STICKS < <(lsblk -dnpo NAME,TRAN | awk '$2=="usb" {print $1}')
[ "${#STICKS[@]}" -gt 0 ] || { echo "  keins gefunden – Stick einstecken und noch einmal starten."; exit 1; }
i=1
for d in "${STICKS[@]}"; do
    printf '  %d) %s  %s  %s  Seriennummer %s\n' "$i" "$d" \
        "$(lsblk -dno SIZE "$d" | tr -d ' ')" "$(lsblk -dno MODEL "$d")" "$(lsblk -dno SERIAL "$d")"
    i=$((i + 1))
done
echo
read -rp "Welcher Stick soll beschrieben werden? Nummer eingeben: " n
[[ "$n" =~ ^[0-9]+$ ]] && [ "$n" -ge 1 ] && [ "$n" -le "${#STICKS[@]}" ] || { echo "Abbruch."; exit 1; }
DEV=${STICKS[$((n - 1))]}

# Nie die Platte, auf der das laufende System liegt
if lsblk -nrpo NAME,MOUNTPOINTS "$DEV" | grep -qE ' (/|/home|/boot|/boot/efi)$'; then
    echo "$DEV enthält das laufende System – Abbruch."; exit 1
fi
GROESSE=$(lsblk -bdno SIZE "$DEV")
source "$HIER/aufteilung.sh"
if ! passt_auf "$GROESSE"; then
    echo "Der Stick ist zu klein ($(lsblk -dno SIZE "$DEV" | tr -d ' ')) – er braucht mindestens 16 GB."
    echo "Es wurde nichts verändert."
    exit 1
fi
[ -n "$TAUSCH" ] || TAUSCH=$(tausch_groesse "$GROESSE")

abbild_schreiben() {   # schreibt das Abbild und merkt sich das Tempo (TEMPO_SEQ in MB/s)
    local t0 t1
    t0=$(date +%s.%N)
    dd if="$ISO" of="$DEV" bs=4M oflag=direct conv=fsync status=progress
    sync
    t1=$(date +%s.%N)
    TEMPO_SEQ=$(mb_pro_s "$(stat -c %s "$ISO")" "$(awk -v a="$t0" -v b="$t1" 'BEGIN {print b - a}')")
}

tempo_hinweis() {   # ehrlicher Hinweis bei langsamen Sticks
    echo
    echo "Schreibtempo dieses Sticks (an diesem Anschluss): ${TEMPO_SEQ} MB/s${TEMPO_KLEIN:+, kleine Blöcke: ${TEMPO_KLEIN} pro Sekunde}"
    if [ "${TEMPO_SEQ:-0}" -lt 15 ] || { [ -n "${TEMPO_KLEIN:-}" ] && [ "$TEMPO_KLEIN" -lt 20 ]; }; then
        echo "!!! Dieser Stick ist LANGSAM. GoGoHam läuft, aber der erste Start und Installationen"
        echo "    (z. B. fldigi) dauern deutlich länger – an einem USB-2-Anschluss noch einmal mehr."
        echo "    Empfohlen: ein USB-3-Stick an einem blauen USB-3-Anschluss."
    fi
}
MODUS=neu
if lsblk -nrpo LABEL "$DEV" | grep -qx GGH-DATEN && teile_merken "$DEV" >/dev/null 2>&1; then
    read -r D_START D_SIZE T_START T_SIZE < <(teile_merken "$DEV")
    ISO_SEK=$(( ($(stat -c %s "$ISO") + 511) / 512 ))
    echo
    echo "Auf diesem Stick ist schon ein GoGoHam-Live-System."
    if [ "$ISO_SEK" -lt "$D_START" ]; then
        echo "  1) Aktualisieren – nur das System erneuern, Logs/Einstellungen/WLAN bleiben (empfohlen)"
        echo "  2) Neu – ALLES löschen und frisch anlegen"
        read -rp "Bitte 1 oder 2 eingeben: " m
        case "$m" in 1) MODUS=aktualisieren ;; 2) MODUS=neu ;; *) echo "Abbruch."; exit 1 ;; esac
    else
        echo "Das neue System ist größer als der Platz davor – Aktualisieren geht nicht, nur Neu."
    fi
fi

if [ "$MODUS" = aktualisieren ]; then
    echo
    echo "Das System auf $DEV wird erneuert. Datenteil und Austausch-Ordner bleiben."
    read -rp "Zum Bestätigen JA eintippen: " ok
    [ "$ok" = "JA" ] || { echo "Abbruch – nichts verändert."; exit 1; }
    for p in $(lsblk -nrpo NAME "$DEV" | tail -n +2) "$DEV"; do umount "$p" 2>/dev/null || true; done
    echo "==> Abbild schreiben (dauert einige Minuten) ..."
    abbild_schreiben
    teile_wieder_eintragen "$DEV" "$D_START" "$D_SIZE" "$T_START" "$T_SIZE"
    partprobe "$DEV" 2>/dev/null || blockdev --rereadpt "$DEV" || true
    udevadm settle
    P4=$(lsblk -nrpo NAME "$DEV" | sed -n 5p)
    [ -b "$P4" ] && daten_schonen "$P4" || echo "(Hinweis: Datenteil-Einstellung nicht gesetzt)"
    sync
    tempo_hinweis
    echo
    lsblk -o NAME,SIZE,FSTYPE,LABEL "$DEV"
    echo
    echo "Fertig! System erneuert, Daten erhalten. Der Stick kann jetzt abgezogen werden."
    exit 0
fi

echo
echo "Aufteilung: System bis 8 GB · Datenteil $(( (GROESSE - DATEN_START * 512 - $(numfmt --from=iec "$TAUSCH")) / GIB )) GB · Austausch-Ordner $(( $(numfmt --from=iec "$TAUSCH") / GIB )) GB"
echo "!!! ALLES auf $DEV ($(lsblk -dno SIZE "$DEV" | tr -d ' ') $(lsblk -dno MODEL "$DEV"), Seriennummer $(lsblk -dno SERIAL "$DEV")) wird GELÖSCHT !!!"
read -rp "Zum Bestätigen JA eintippen: " ok
[ "$ok" = "JA" ] || { echo "Abbruch – nichts verändert."; exit 1; }

echo "==> Stick aushängen ..."
for p in $(lsblk -nrpo NAME "$DEV" | tail -n +2) "$DEV"; do umount "$p" 2>/dev/null || true; done

echo "==> Abbild schreiben (dauert einige Minuten) ..."
abbild_schreiben

echo "==> Datenteil und Austausch-Ordner anlegen ..."
aufteilen "$DEV" "$TAUSCH"
partprobe "$DEV" 2>/dev/null || blockdev --rereadpt "$DEV" || true
udevadm settle
P4=$(lsblk -nrpo NAME "$DEV" | sed -n 5p)
P5=$(lsblk -nrpo NAME "$DEV" | sed -n 6p)
[ -b "$P4" ] && [ -b "$P5" ] || { echo "Teile 4/5 nicht gefunden – bitte Stick neu einstecken und melden."; exit 1; }
# Tempo bei vielen kleinen Schreibzugriffen (so arbeitet das System im Betrieb) – höchstens 30 s
t0=$(date +%s.%N)
if timeout 30 dd if=/dev/zero of="$P4" bs=4k count=64 oflag=direct,dsync status=none; then
    t1=$(date +%s.%N)
    TEMPO_KLEIN=$(awk -v a="$t0" -v b="$t1" 'BEGIN { s = b - a; if (s <= 0) s = 0.001; printf "%d", 64 / s }')
else
    TEMPO_KLEIN=2                          # nach 30 s nicht fertig: sehr langsam
fi
echo "==> Datenteil einrichten (vollständig, damit der Stick das nicht beim ersten Start nachholt) ..."
mkfs.ext4 -q -F -L GGH-DATEN -E lazy_itable_init=0,lazy_journal_init=0 "$P4"
daten_schonen "$P4"
mkfs.exfat -q -L GoGoHam "$P5" >/dev/null
tmp=$(mktemp -d)
mount "$P4" "$tmp"
echo "/ union" > "$tmp/persistence.conf"
umount "$tmp"
rmdir "$tmp"
sync
echo
lsblk -o NAME,SIZE,FSTYPE,LABEL "$DEV"
tempo_hinweis
echo
echo "Fertig! Der Stick kann jetzt abgezogen werden."
