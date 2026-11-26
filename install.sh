#!/usr/bin/env bash
# GoGoHam installieren (Garuda / Arch / Manjaro)
set -e

APPDIR="$HOME/.local/share/gogoham/app"
BINDIR="$HOME/.local/bin"
SRC="$(cd "$(dirname "$0")" && pwd)"

echo "==> Benötigte Pakete installieren (PySide6, Qt-Ton, NumPy, Hamlib) …"
if command -v pacman >/dev/null; then
    # qt6-multimedia: Aufnahme/Wiedergabe für die Sprachausgabe (ab 0.8.11), numpy: Klang
    sudo pacman -S --needed --noconfirm pyside6 qt6-multimedia qt6-multimedia-ffmpeg \
        python-numpy hamlib sqlite
else
    echo "Kein pacman gefunden – bitte PySide6 (mit QtMultimedia), NumPy und Hamlib selbst installieren"
    echo "(Debian/Ubuntu: sudo apt install python3-pyside6.qtwidgets python3-pyside6.qtmultimedia python3-numpy libhamlib-utils)"
fi

echo "==> Programm nach $APPDIR kopieren …"
mkdir -p "$APPDIR" "$BINDIR" "$HOME/.local/share/applications"
rm -rf "$APPDIR/gogoham"
cp -r "$SRC/gogoham" "$APPDIR/"

install -m755 "$SRC/uninstall.sh" "$HOME/.local/share/gogoham/uninstall.sh"   # ab 0.8.23.5

cat > "$BINDIR/gogoham" <<EOF
#!/usr/bin/env bash
cd "$APPDIR" && exec python3 -m gogoham "\$@"
EOF
chmod +x "$BINDIR/gogoham"

echo "==> Symbole und Startmenü-Eintrag installieren …"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
mkdir -p "$DATA/applications"
for d in "$SRC"/data/icons/hicolor/*/apps; do
    size="$(basename "$(dirname "$d")")"
    install -Dm644 "$d/gogoham.png" "$DATA/icons/hicolor/$size/apps/gogoham.png"
done
# Eintrag aus data/gogoham.desktop, Exec mit vollem Pfad (~/.local/bin ist nicht überall im PATH)
sed "s|^Exec=.*|Exec=$BINDIR/gogoham|" "$SRC/data/gogoham.desktop" \
    > "$DATA/applications/gogoham.desktop"
chmod 644 "$DATA/applications/gogoham.desktop"
# 0.10.47.1: Beschreibung für Software-Verwaltungen (AppStream)
install -Dm644 "$SRC/data/io.github.do2ggh.GoGoHam.metainfo.xml" \
    "$DATA/metainfo/io.github.do2ggh.GoGoHam.metainfo.xml"
# Symbol-Zwischenspeicher und Menü auffrischen (Fehler sind hier egal)
gtk-update-icon-cache -f -t "$DATA/icons/hicolor" 2>/dev/null || true
update-desktop-database "$DATA/applications" 2>/dev/null || true
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 2>/dev/null || true

# 0.10.25: USB-Geräte (Funkgerät-Kabel, GPS, WinKeyer, Rotor) freigeben – sofort, ohne Gruppe
RULE=/etc/udev/rules.d/70-gogoham.rules
if [ -t 0 ] && [ ! -f "$RULE" ] && [ ! -f /usr/lib/udev/rules.d/70-gogoham.rules ]; then
    echo
    echo "==> USB-Geräte (Funkgerät-Kabel, GPS-Empfänger, WinKeyer) für dich freigeben?"
    echo "    (gilt sofort, ohne neu anmelden)"
    read -r -p "    [J/n] " a
    if [[ ! "$a" =~ ^[nN] ]]; then
        sudo install -Dm644 "$SRC/gogoham/assets/70-gogoham.rules" "$RULE"
        sudo udevadm control --reload-rules
        sudo udevadm trigger --action=change --subsystem-match=tty || true
        echo "    Erledigt."
    fi
fi

echo
echo "Fertig! Starten über das Startmenü (GoGoHam) oder im Terminal mit: gogoham"
echo "(Deinstallieren: bash ~/.local/share/gogoham/uninstall.sh)"
