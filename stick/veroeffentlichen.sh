#!/bin/bash
# Stick-Abbild auf SourceForge veröffentlichen (https://sourceforge.net/projects/gogoham/).
#   bash stick/veroeffentlichen.sh              → Probelauf: zeigt nur, was hochgeladen würde
#   bash stick/veroeffentlichen.sh --hochladen  → lädt wirklich hoch (Ordner <Version>/)
# Voraussetzung: Bau mit Quellcode-Abbild (sudo QUELLEN=1 bash stick/bauen.sh) – ohne das
# Quellcode-Abbild wird nicht hochgeladen (GPL: wer das Abbild weitergibt, gibt auch die Quellen).
# Hochladen über SSH als do2ggh (Schlüssel im SourceForge-Konto eingetragen).
set -euo pipefail
HIER="$(cd "$(dirname "$0")" && pwd -P)"
A="$HIER/ausgabe"
SF_USER=${SF_USER:-do2ggh}
SF_ZIEL="/home/frs/project/gogoham"
HOCH=0; [ "${1:-}" = "--hochladen" ] && HOCH=1

ISO=$(ls -t "$A"/gogoham-live-*.iso 2>/dev/null | grep -v -- '-quellen\.iso$' | head -n1 || true)
[ -n "$ISO" ] || { echo "Kein Abbild in $A – erst bauen."; exit 1; }
VER=${ISO##*/gogoham-live-}; VER=${VER%.iso}
QISO="$A/gogoham-live-$VER-quellen.iso"
if [ ! -f "$QISO" ]; then
    echo "Zu Version $VER fehlt das Quellcode-Abbild ($QISO)."
    echo "Bitte so bauen:  sudo QUELLEN=1 bash $HIER/bauen.sh"
    exit 1
fi

D="$A/sourceforge-$VER"
rm -rf "$D"; mkdir -p "$D"
ln "$ISO" "$D/" 2>/dev/null || cp "$ISO" "$D/"
ln "$QISO" "$D/" 2>/dev/null || cp "$QISO" "$D/"
# Quelltext von GoGoHam selbst (aus dem GitHub-Arbeitsstand, falls die Versionsmarke da ist)
GH="$HOME/Projekte/GoGoHam-github"
if git -C "$GH" rev-parse -q --verify "refs/tags/v$VER" >/dev/null 2>&1; then
    git -C "$GH" archive --format=tar.gz --prefix="gogoham-$VER/" -o "$D/gogoham-$VER.tar.gz" "v$VER"
else
    echo "Hinweis: keine Versionsmarke v$VER auf GitHub – Quelltext von GoGoHam nicht beigelegt."
fi

cat > "$D/LIESMICH.txt" <<EOF
GoGoHam $VER – Live-Stick (Debian 13 + KDE Plasma) · Contest-Logger für Linux
================================================================================

Dateien
  gogoham-live-$VER.iso          Das Stick-Abbild (startet per USB, UEFI und BIOS)
  gogoham-live-$VER-quellen.iso  Quelltexte aller enthaltenen Debian-Pakete (GPL)
  gogoham-$VER.tar.gz            Quelltext von GoGoHam
  SHA256SUMS                     Prüfsummen – prüfen mit:  sha256sum -c SHA256SUMS

Auf einen Stick schreiben (mindestens 16 GB, alles darauf wird gelöscht)
  Linux:   sudo dd if=gogoham-live-$VER.iso of=/dev/sdX bs=4M status=progress oflag=sync
           (sdX = der Stick! Mit  lsblk  nachsehen.)
  Windows: z. B. mit Rufus oder balenaEtcher („DD-Modus“ wählen).
  Bei Rufus unbedingt den „DD-Modus“ wählen (Rufus fragt danach) – im ISO-Modus geht es nicht.
  Beim ERSTEN Start richtet sich der Stick selbst ein: Er legt Datenteil (für Logs und
  Einstellungen) und Austausch-Ordner (auch unter Windows lesbar) an – das dauert einmalig eine
  bis einige Minuten, bitte nicht abziehen. Danach startet er normal.
  Alternativ unter Linux: das Skript  stick/schreiben.sh  aus dem GoGoHam-Quelltext, oder von
  einem laufenden GoGoHam-Stick aus: Einstellungen → USB-Stick → Neuen Stick erstellen.

Handbuch, Fehler melden, Quelltext: https://github.com/do2ggh/GoGoHam
Lizenz: GoGoHam GPL-3.0-only (mit Zusatzbedingungen, siehe ADDITIONAL-TERMS.md);
die übrigen Programme unter ihren eigenen freien Lizenzen (Debian).

--------------------------------------------------------------------------------
GoGoHam $VER – live stick (Debian 13 + KDE Plasma) · contest logger for Linux

Files
  gogoham-live-$VER.iso          The stick image (boots from USB, UEFI and BIOS)
  gogoham-live-$VER-quellen.iso  Sources of all included Debian packages (GPL)
  gogoham-$VER.tar.gz            Source code of GoGoHam
  SHA256SUMS                     Checksums – verify with:  sha256sum -c SHA256SUMS

Writing a stick (16 GB or more, everything on it will be erased)
  Linux:   sudo dd if=gogoham-live-$VER.iso of=/dev/sdX bs=4M status=progress oflag=sync
  Windows: e.g. Rufus or balenaEtcher ("DD mode").
  With Rufus be sure to choose "DD mode" (Rufus asks) – ISO mode does not work.
  On the FIRST boot the stick sets itself up: it creates the data part (logs, settings) and the
  exchange folder (readable on Windows too) – this takes one to a few minutes once, do not unplug.

Manual, bug reports, source code: https://github.com/do2ggh/GoGoHam
EOF
(cd "$D" && sha256sum -- *.iso *.tar.gz 2>/dev/null > SHA256SUMS)

echo "Version $VER – bereit in $D:"
ls -la --block-size=M "$D"
if [ "$HOCH" = 1 ]; then
    echo "==> Lade nach SourceForge: $SF_ZIEL/$VER/ (mehrere GB, das dauert) …"
    rsync -av --progress -e ssh "$D/" "$SF_USER@frs.sourceforge.net:$SF_ZIEL/$VER/"
    echo "Fertig: https://sourceforge.net/projects/gogoham/files/$VER/"
else
    echo
    echo "Probelauf – nichts hochgeladen. Zum Hochladen:  bash $0 --hochladen"
fi
