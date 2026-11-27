#!/bin/bash
# Stick-Abbild auf der GitHub-Release-Seite der Version veröffentlichen (seit 2026-11-28; vorher
# SourceForge – Konto und Projekt dort am 2026-11-27 verschwunden).
#   bash stick/veroeffentlichen.sh             → nur vorbereiten (Probelauf), nichts hochladen
#   bash stick/veroeffentlichen.sh --hochladen → an die Release-Seite v<Version> hängen
# Die Release-Seite legt der GitHub-Ablauf „Pakete bauen (OBS)“ beim Setzen der Versionsmarke an.
# GitHub nimmt je Datei höchstens 2 GiB: das Stick-Abbild passt, das Quellen-Abbild (GPL) wird in
# Stücke geteilt (Zusammensetzen steht in LIESMICH.txt). Braucht: gh (angemeldet), split, sha256sum.
set -euo pipefail
HIER="$(cd "$(dirname "$0")" && pwd -P)"
A="$HIER/ausgabe"
REPO="do2ggh/GoGoHam"
GRENZE=$((2 * 1024 * 1024 * 1024 - 1))    # GitHub: unter 2 GiB je Datei
TEIL=1900M
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
[ "$(stat -c %s "$ISO")" -le "$GRENZE" ] || { echo "Stick-Abbild ist 2 GiB oder größer – passt nicht auf GitHub."; exit 1; }

D="$A/github-$VER"
rm -rf "$D"; mkdir -p "$D"
ln "$ISO" "$D/" 2>/dev/null || cp "$ISO" "$D/"
QNAME="gogoham-live-$VER-quellen.iso"
echo "==> Quellen-Abbild in Stücke zu $TEIL teilen …"
split -b "$TEIL" -d -a 2 "$QISO" "$D/$QNAME.teil"
TEILE=$(cd "$D" && ls "$QNAME".teil* | tr '\n' ' ')
cat > "$D/LIESMICH.txt" <<EOF
GoGoHam $VER – Live-Stick (Debian 13 + LXQt) · Contest-Logger für Linux
=========================================================================

Dateien
  gogoham-live-$VER.iso                  Das Stick-Abbild (startet per USB, UEFI und BIOS)
  $QNAME.teil00, .teil01 …  Quelltexte aller enthaltenen Debian-Pakete (GPL),
                                         in Stücke geteilt (GitHub nimmt höchstens 2 GB je Datei)
  SHA256SUMS                             Prüfsummen – prüfen mit:  sha256sum -c SHA256SUMS

Auf einen Stick schreiben (mindestens 16 GB, alles darauf wird gelöscht)
  Linux:   sudo dd if=gogoham-live-$VER.iso of=/dev/sdX bs=4M status=progress oflag=sync
           (sdX = der Stick! Mit  lsblk  nachsehen.)
  Windows: z. B. mit Rufus oder balenaEtcher. Bei Rufus unbedingt den „DD-Modus“ wählen
           (Rufus fragt danach) – im ISO-Modus geht es nicht.
  Beim ERSTEN Start richtet sich der Stick selbst ein: Er legt Datenteil (für Logs und
  Einstellungen) und Austausch-Ordner (auch unter Windows lesbar) an – das dauert einmalig eine
  bis einige Minuten, bitte nicht abziehen. Danach startet er normal.
  Alternativ unter Linux: das Skript  stick/schreiben.sh  aus dem GoGoHam-Quelltext, oder von
  einem laufenden GoGoHam-Stick aus: Einstellungen → USB-Stick → Neuen Stick erstellen.

Quellen-Abbild zusammensetzen (nur wer die Quelltexte braucht)
  Linux:   cat $QNAME.teil* > $QNAME
  Windows: copy /b $(echo $TEILE | sed 's/ /+/g') $QNAME

Handbuch, Fehler melden, Quelltext von GoGoHam: https://github.com/$REPO

-------------------------------------------------------------------------------
English: Write gogoham-live-$VER.iso to a USB stick (16 GB or more) with dd, balenaEtcher
or Rufus (DD mode!). The stick sets itself up at the first start. The source image (GPL) is
split into parts; join them with  cat $QNAME.teil* > $QNAME  (Linux) or  copy /b … (Windows).
EOF
( cd "$D" && sha256sum "gogoham-live-$VER.iso" $TEILE > SHA256SUMS && \
  sha256sum "$QISO" | sed "s|  .*|  $QNAME|" >> SHA256SUMS )
for f in "$D"/*; do
    [ "$(stat -c %s "$f")" -le "$GRENZE" ] || { echo "Zu groß für GitHub: $f"; exit 1; }
done
echo
ls -la --block-size=M "$D"
echo
if [ "$HOCH" != 1 ]; then
    echo "Probelauf fertig: $D"
    echo "Hochladen mit:  bash $HIER/veroeffentlichen.sh --hochladen"
    exit 0
fi

gh release view "v$VER" -R "$REPO" >/dev/null 2>&1 || {
    echo "Die Release-Seite v$VER gibt es noch nicht (legt der GitHub-Ablauf nach dem OBS-Bau an)."
    exit 1
}
echo "==> Lade an die Release-Seite v$VER (mehrere GB, das dauert) …"
( cd "$D" && gh release upload "v$VER" -R "$REPO" --clobber ./* )
MARKE="<!-- gogoham-live-stick -->"
BODY=$(gh release view "v$VER" -R "$REPO" --json body --jq .body)
if ! grep -qF "$MARKE" <<<"$BODY"; then
    cat > "$D/.notes.md" <<EOF
$BODY

$MARKE
### Live-Stick
GoGoHam zum Ausprobieren ohne Installation: **\`gogoham-live-$VER.iso\`** auf einen USB-Stick
(ab 16 GB) schreiben – mit balenaEtcher, \`dd\` oder Rufus (**DD-Modus**). Anleitung in
\`LIESMICH.txt\` und im Handbuch, Kapitel „Live-Stick“. Die Quelltexte aller Pakete auf dem Stick
(GPL) liegen in Stücken bei (\`$QNAME.teil…\`).

*English: write \`gogoham-live-$VER.iso\` to a USB stick (16 GB or more) – see \`LIESMICH.txt\`.*
EOF
    gh release edit "v$VER" -R "$REPO" --notes-file "$D/.notes.md"
fi
echo "Fertig: https://github.com/$REPO/releases/tag/v$VER"
