# Gemeinsame Aufteilung für Test-Stick und echten Stick (wird per „source“ geladen).
# Nach dem Abbild: Teil 4 = Datenteil (ext4 „GGH-DATEN“), Teil 5 = Austausch-Ordner (exFAT „GoGoHam“).
# Der Datenteil beginnt fest bei 8 GiB: So passt auch ein größeres neues Abbild davor, und der
# Stick lässt sich aktualisieren, ohne Daten zu verlieren (schreiben.sh → „Aktualisieren“).
# Die Lückenteile des Abbilds bekommen den Typ „Linux“, damit Windows sie nicht als
# unlesbares Laufwerk anzeigt (und zum Formatieren auffordert).
LINUX=0FC63DAF-8483-4772-8E79-3D69D8477DE4
MSDATA=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7
DATEN_START=$((8 * 1024 * 1024 * 2))      # 8 GiB in 512-Byte-Sektoren
GIB=$((1024 * 1024 * 1024))
DATEN_MIN=$((4 * GIB))                    # Datenteil mindestens 4 GiB (fldigi allein 1,4 GB)
TAUSCH_MIN=$((2 * GIB))                   # Austausch-Ordner 2 … 16 GiB, je nach Stick
TAUSCH_MAX=$((16 * GIB))
RAND=$((8 * 1024 * 1024))                 # Ausrichtung + Sicherungs-Partitionstabelle am Ende

# Datenteil schonend einbinden (steht im Dateisystem selbst, gilt also bei jedem Start):
# Daten alle 30 statt 5 s wegschreiben. Das GoGoHam-Log (SQLite) schreibt jedes QSO trotzdem
# sofort fest (fsync). „noatime“ setzt live-boot schon selbst – und darf hier NICHT stehen: Der
# Kernel kennt es an dieser Stelle nicht und verwirft dann die ganze Zeile (VM-Test 13. Bau).
DATEN_OPTIONEN="commit=30"

daten_schonen() { debugfs -w -R "ssv mount_opts $DATEN_OPTIONEN" "$1" >/dev/null 2>&1; }

# Schreibtempo des Sticks: $1 = Byte, $2 = Sekunden (mit Komma oder Punkt) → MB/s (ganzzahlig)
mb_pro_s() { awk -v b="$1" -v s="${2/,/.}" 'BEGIN { if (s <= 0) s = 0.001; printf "%d", b / s / 1000000 }'; }

tausch_groesse() {   # $1 = Stickgröße in Byte → Größe des Austausch-Ordners (z. B. „4096M“)
    local rest t
    rest=$(( $1 - DATEN_START * 512 - RAND ))
    t=$(( rest / 4 ))                      # ein Viertel vom Platz hinter dem System …
    [ "$t" -ge "$TAUSCH_MIN" ] || t=$TAUSCH_MIN
    [ "$t" -le "$TAUSCH_MAX" ] || t=$TAUSCH_MAX
    echo "$(( t / 1024 / 1024 ))M"
}

passt_auf() {   # $1 = Stickgröße in Byte: 0 = groß genug (mindestens „16 GB“)
    local t
    t=$(numfmt --from=iec "$(tausch_groesse "$1")")
    [ $(( $1 - DATEN_START * 512 - RAND - t )) -ge "$DATEN_MIN" ]
}

abbild_tabelle() {   # Partitionstabelle des frisch geschriebenen Abbilds herrichten
    local ziel=$1
    sfdisk -q --relocate gpt-bak-std "$ziel"
    sfdisk -q --part-type "$ziel" 1 "$LINUX"
    sfdisk -q --part-type "$ziel" 3 "$LINUX"
}

aufteilen() {   # $1 = Gerät oder Datei, $2 = Größe Austausch-Ordner (z. B. 16G)
    local ziel=$1 tausch=$2 ende t_sek d_sek
    abbild_tabelle "$ziel"
    ende=$(LC_ALL=C sfdisk -q -F "$ziel" | awk 'NR>1 {e=$2} END {print e}')   # letzter freier Sektor
    t_sek=$(( $(numfmt --from=iec "$tausch") / 512 ))
    d_sek=$(( ende - DATEN_START - t_sek - 2048 ))
    [ "$d_sek" -gt $((1024 * 1024 * 2)) ] || { echo "Stick zu klein"; return 1; }
    printf 'start=%s, size=%s, type=%s, name="GGH-DATEN"\nstart=%s, size=%s, type=%s, name="GoGoHam"\n' \
        "$DATEN_START" "$d_sek" "$LINUX" "$((DATEN_START + d_sek))" "$t_sek" "$MSDATA" | sfdisk -q --append "$ziel"
}

teile_merken() {    # Start/Größe von Teil 4 und 5 (für „Aktualisieren“)
    sfdisk -J "$1" | python3 -c '
import json, sys
p = json.load(sys.stdin)["partitiontable"]["partitions"]
print(p[3]["start"], p[3]["size"], p[4]["start"], p[4]["size"])'
}

teile_wieder_eintragen() {   # $1 Ziel, $2..$5 = d_start d_size t_start t_size
    abbild_tabelle "$1"
    printf 'start=%s, size=%s, type=%s, name="GGH-DATEN"\nstart=%s, size=%s, type=%s, name="GoGoHam"\n' \
        "$2" "$3" "$LINUX" "$4" "$5" "$MSDATA" | sfdisk -q --append "$1"
}

lage() { teile_merken "$1"; }
