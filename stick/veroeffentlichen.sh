#!/bin/bash
# Stick-Abbild auf der GitHub-Release-Seite der Version veröffentlichen (seit 2026-11-28; vorher
# SourceForge – Konto und Projekt dort am 2026-11-27 verschwunden).
#   bash stick/veroeffentlichen.sh             → nur vorbereiten (Probelauf), nichts hochladen
#   bash stick/veroeffentlichen.sh --hochladen → hochladen (darf wiederholt werden: gleich große
#                                                Dateien, die schon oben sind, werden übersprungen)
# Hauptseite v<Version> (legt der GitHub-Ablauf „Pakete bauen (OBS)“ beim Setzen der Versionsmarke
# an): nur Stick-Abbild, LIESMICH.txt, Prüfsumme; der Download-Link kommt in den Wegweiser oben
# (Marke <!-- gogoham-live-stick -->). Die Quelltexte (GPL) kommen auf eine EIGENE Seite
# quellen-<Version> (Nutzer 2026-11-28: sonst zu unübersichtlich). Diese Marke ohne „v“ löst
# keinen Paketbau aus und zählt nicht als Version (versioncheck sucht nur v…).
# GitHub nimmt je Datei höchstens 2 GiB: das Quellen-Abbild wird in Stücke geteilt.
# Braucht: gh (angemeldet), split, sha256sum.
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
SLTAR="$A/gogoham-live-$VER-quellen-startlader.tar"
[ -f "$SLTAR" ] || { echo "Es fehlen die Quellen des Startladers ($SLTAR) – beim Bau mit QUELLEN=1 entstehen sie."; exit 1; }
[ "$(stat -c %s "$ISO")" -le "$GRENZE" ] || { echo "Stick-Abbild ist 2 GiB oder größer – passt nicht auf GitHub."; exit 1; }

D="$A/github-$VER"            # → Hauptseite v$VER
Q="$A/github-$VER-quellen"    # → Seite quellen-$VER
QTAG="quellen-$VER"
URL="https://github.com/$REPO/releases/download"
rm -rf "$D" "$Q"; mkdir -p "$D" "$Q"
ln "$ISO" "$D/" 2>/dev/null || cp "$ISO" "$D/"
cp "$SLTAR" "$Q/"
QNAME="gogoham-live-$VER-quellen.iso"
echo "==> Quellen-Abbild in Stücke zu $TEIL teilen …"
split -b "$TEIL" -d -a 2 "$QISO" "$Q/$QNAME.teil"
TEILE=$(cd "$Q" && ls "$QNAME".teil* | tr '\n' ' ')
GROESSE=$(awk -v b="$(stat -c %s "$ISO")" 'BEGIN{printf "%.1f", b/1e9}' | tr . ,)
cat > "$D/LIESMICH.txt" <<EOF
GoGoHam $VER – Live-Stick (Debian 13 + LXQt) · Contest-Logger für Linux
=========================================================================

Dateien
  gogoham-live-$VER.iso   Das Stick-Abbild (startet per USB, UEFI und BIOS)
  SHA256SUMS              Prüfsummen – prüfen mit:  sha256sum -c --ignore-missing SHA256SUMS
  Quelltexte aller Pakete auf dem Stick (GPL): eigene Seite
    https://github.com/$REPO/releases/tag/$QTAG
  Quelltext von GoGoHam selbst: auf dieser Seite unter „Source code“ (Versionsmarke v$VER)

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

Handbuch, Fehler melden, Quelltext von GoGoHam: https://github.com/$REPO

-------------------------------------------------------------------------------
English: Write gogoham-live-$VER.iso to a USB stick (16 GB or more) with dd, balenaEtcher
or Rufus (DD mode!). The stick sets itself up at the first start. Sources of all packages on
the stick (GPL): https://github.com/$REPO/releases/tag/$QTAG
EOF
( cd "$D" && sha256sum "gogoham-live-$VER.iso" > SHA256SUMS )
( cd "$Q" && sha256sum $TEILE "gogoham-live-$VER-quellen-startlader.tar" > SHA256SUMS && \
  sha256sum "$QISO" | sed "s|  .*|  $QNAME|" >> SHA256SUMS )
cat > "$Q/.notes.md" <<EOF
**Quelltexte zum GoGoHam-Live-Stick $VER** (GPL)

👉 **Den Stick selbst gibt es hier: [GoGoHam $VER](https://github.com/$REPO/releases/tag/v$VER)** –
diese Seite braucht nur, wer die Quelltexte der Pakete auf dem Stick haben möchte.

- \`$QNAME.teil00\`, \`.teil01\` … – Quelltexte aller Debian-Pakete auf dem Stick, in Stücke
  geteilt (GitHub nimmt höchstens 2 GB je Datei)
- \`gogoham-live-$VER-quellen-startlader.tar\` – Quelltexte des Startladers (GRUB, shim)
- Quelltext von GoGoHam selbst: auf der Seite [GoGoHam $VER](https://github.com/$REPO/releases/tag/v$VER) unter „Source code“

**Zusammensetzen**
\`\`\`
Linux:    cat $QNAME.teil* > $QNAME
Windows:  copy /b $(echo $TEILE | sed 's/ /+/g') $QNAME
\`\`\`
Prüfen: \`sha256sum -c SHA256SUMS\`

*English: sources (GPL) of all packages on the GoGoHam live stick $VER. The stick image itself is on
the page [GoGoHam $VER](https://github.com/$REPO/releases/tag/v$VER). Join the parts with \`cat\` (Linux) or \`copy /b\` (Windows), see above.*
EOF
for f in "$D"/* "$Q"/*; do
    [ "$(stat -c %s "$f")" -le "$GRENZE" ] || { echo "Zu groß für GitHub: $f"; exit 1; }
done
echo
ls -la --block-size=M "$D" "$Q"
echo
if [ "$HOCH" != 1 ]; then
    echo "Probelauf fertig: $D und $Q"
    echo "Hochladen mit:  bash $HIER/veroeffentlichen.sh --hochladen"
    exit 0
fi

gh release view "v$VER" -R "$REPO" >/dev/null 2>&1 || {
    echo "Die Release-Seite v$VER gibt es noch nicht (legt der GitHub-Ablauf nach dem OBS-Bau an)."
    exit 1
}

# hochladen <Marke> <Ordner>: Dateien, die gleich groß schon oben sind, überspringen
hochladen() {
    local tag=$1 dir=$2 f n neu=()
    local da; da=$(gh release view "$tag" -R "$REPO" --json assets --jq '.assets[]|"\(.name) \(.size)"')
    for f in "$dir"/*; do
        n=${f##*/}
        if [ "$n" != SHA256SUMS ] && grep -qxF "$n $(stat -c %s "$f")" <<<"$da"; then
            echo "   schon oben: $n"
        else
            neu+=("$f")
        fi
    done
    [ ${#neu[@]} -eq 0 ] || gh release upload "$tag" -R "$REPO" --clobber "${neu[@]}"
}

# 1) Quelltext-Seite (zuerst, damit der Link auf der Hauptseite gleich stimmt)
if ! gh release view "$QTAG" -R "$REPO" >/dev/null 2>&1; then
    SHA=$(gh api "repos/$REPO/commits/v$VER" --jq .sha)
    gh release create "$QTAG" -R "$REPO" --target "$SHA" --latest=false \
        --title "Quelltexte Live-Stick $VER (GPL)" --notes-file "$Q/.notes.md"
else
    gh release edit "$QTAG" -R "$REPO" --latest=false --notes-file "$Q/.notes.md"
fi
echo "==> Quelltexte an $QTAG (mehrere GB, das dauert) …"
hochladen "$QTAG" "$Q"

# 2) Hauptseite: SHA256SUMS mit den Paketen (Release-Job) zusammenführen, nicht ersetzen
#    (2026-11-28: sonst fehlten die Prüfsummen der Pakete)
ALT=$(mktemp -d)
if gh release download "v$VER" -R "$REPO" -p SHA256SUMS -D "$ALT" 2>/dev/null; then
    { grep -v -E '  gogoham-live-' "$ALT/SHA256SUMS" || true; cat "$D/SHA256SUMS"; } > "$ALT/neu"
    mv "$ALT/neu" "$D/SHA256SUMS"
fi
rm -f "$ALT/SHA256SUMS"; rmdir "$ALT" 2>/dev/null || true
echo "==> Stick-Abbild an v$VER …"
hochladen "v$VER" "$D"
# Quelltexte, die früher auf der Hauptseite lagen (bis 0.10.48), dort entfernen
gh release view "v$VER" -R "$REPO" --json assets --jq '.assets[].name' | grep -E -- '-quellen' | \
    while read -r n; do echo "   entferne von v$VER: $n"; gh release delete-asset "v$VER" "$n" -R "$REPO" -y; done

# 3) Wegweiser oben auf der Hauptseite: Stick-Zeile an der Marke einsetzen
MARKE="<!-- gogoham-live-stick -->"
ZEILE="- 💾 **Live-Stick – ohne Installation, startet vom USB-Stick (ab 16 GB):** 👉 **[gogoham-live-$VER.iso herunterladen]($URL/v$VER/gogoham-live-$VER.iso)** ($GROESSE GB) · [Anleitung (LIESMICH)]($URL/v$VER/LIESMICH.txt)  
  Schreiben mit balenaEtcher, \`dd\` oder Rufus (**DD-Modus**). Quelltexte (GPL): [eigene Seite](https://github.com/$REPO/releases/tag/$QTAG)"
BODY=$(gh release view "v$VER" -R "$REPO" --json body --jq .body)
if grep -qF "$MARKE" <<<"$BODY"; then
    MARKE="$MARKE" ZEILE="$ZEILE" python3 -c '
import os, sys
m, z = os.environ["MARKE"], os.environ["ZEILE"]
b = sys.stdin.read()
b = b.split("\n" + m + "\n### Live-Stick")[0]        # alter Abschnitt am Ende (bis 0.10.48)
lines = b.split("\n")
i = lines.index(m)
if not lines[i + 1].startswith("- 💾"):
    lines.insert(i + 1, z)
else:
    lines[i + 1:i + 3] = z.split("\n")
sys.stdout.write("\n".join(lines).rstrip("\n") + "\n")' <<<"$BODY" > "$D/.notes.md"
    gh release edit "v$VER" -R "$REPO" --notes-file "$D/.notes.md"
else
    echo "⚠ Auf v$VER fehlt die Marke $MARKE – Seitentext bitte mit tools/release_pakete.py neu erzeugen."
fi
echo "Fertig: https://github.com/$REPO/releases/tag/v$VER"
echo "        https://github.com/$REPO/releases/tag/$QTAG"
