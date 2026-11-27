#!/bin/bash
# Läuft im Debian-13-Container: erst GoGoHam als Debian-Paket bauen, dann das Live-Abbild.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
STICK=/stick
SRC=/src
OUT=$STICK/ausgabe

apt-get update
apt-get install -y --no-install-recommends live-build debootstrap xorriso squashfs-tools mtools \
    dosfstools grub-efi-amd64-bin grub-pc-bin grub-common cpio ca-certificates rsync \
    build-essential dpkg-dev debhelper dh-python pybuild-plugin-pyproject python3-all python3-setuptools \
    python3-wheel

# ---------------------------------------------------------------- 1. GoGoHam-Paket
VER=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/gogoham/__init__.py")
P=/tmp/paket/gogoham-$VER
rm -rf /tmp/paket
mkdir -p "$P"
rsync -a --exclude CLAUDE.md --exclude docs/VERLAUF.md --exclude /stick \
    --exclude __pycache__ --exclude '*.ggh' --exclude build --exclude '*.egg-info' \
    --exclude .pytest_cache --exclude dist "$SRC/" "$P/"
mkdir -p "$P/debian/source"
cp "$P/packaging/obs/debian.control" "$P/debian/control"
cp "$P/packaging/obs/debian.rules" "$P/debian/rules"
cp "$P/packaging/obs/debian.copyright" "$P/debian/copyright"
chmod +x "$P/debian/rules"
echo "3.0 (native)" > "$P/debian/source/format"
cat > "$P/debian/changelog" <<CL
gogoham ($VER) unstable; urgency=medium

  * Paket für den GoGoHam-Live-Stick (siehe CHANGELOG.md).

 -- Franz DO2GGH <do2ggh.de@gmail.com>  $(date -R)
CL
(cd "$P" && dpkg-buildpackage -us -uc -b)
DEB=$(ls /tmp/paket/gogoham_"$VER"_all.deb)
cp "$DEB" "$OUT/"

# ---------------------------------------------------------------- 2. Live-Abbild
# Arbeitsordner auf der Festplatte: der Paket-Zwischenspeicher (cache) bleibt für den nächsten Bau
W=$STICK/arbeit
mkdir -p "$W"
cd "$W"
find . -mindepth 1 -maxdepth 1 ! -name cache -exec rm -rf {} +
QUELL_OPT=()
if [ "${QUELLEN:-0}" = 1 ]; then          # Veröffentlichung: alle Quelltexte als eigenes Abbild (GPL)
    QUELL_OPT=(--source true --source-images iso)
fi
lb config "${QUELL_OPT[@]}" \
    --distribution trixie \
    --archive-areas "main contrib non-free non-free-firmware" \
    --binary-image iso-hybrid \
    --bootloaders "grub-pc grub-efi" \
    --debian-installer none \
    --firmware-binary false \
    --firmware-chroot false \
    --memtest none \
    --chroot-squashfs-compression-type zstd \
    --apt-indices true \
    --iso-application "GoGoHam Live" \
    --iso-publisher "GoGoHam" \
    --iso-volume "GOGOHAM_LIVE" \
    --mirror-bootstrap http://deb.debian.org/debian/ \
    --mirror-chroot http://deb.debian.org/debian/ \
    --mirror-binary http://deb.debian.org/debian/ \
    --mirror-chroot-security http://security.debian.org/debian-security/ \
    --mirror-binary-security http://security.debian.org/debian-security/ \
    --bootappend-live "boot=live components quiet loglevel=3 systemd.show_status=false splash persistence persistence-label=GGH-DATEN username=gogoham user-fullname=GoGoHam hostname=gogoham user-default-groups=audio,cdrom,dip,floppy,video,plugdev,netdev,dialout,bluetooth"
cp -a "$STICK/config/." config/
# Aufteilung (Teile, Größen) gemeinsam mit schreiben.sh – auf dem Stick für „Neuen Stick erstellen“
install -D -m 0644 "$STICK/aufteilung.sh" config/includes.chroot/usr/local/lib/gogoham-stick/aufteilung.sh
mkdir -p config/packages.chroot
cp "$DEB" config/packages.chroot/
lb build 2>&1 | tee "$OUT/bau.log"
ISO=$(ls "$W"/*.iso | grep -v -i source | head -n1)
cp "$ISO" "$OUT/gogoham-live-$VER.iso"
if [ "${QUELLEN:-0}" = 1 ]; then
    QISO=$(ls "$W"/*.iso | grep -i source | head -n1)
    if [ -n "$QISO" ]; then
        cp "$QISO" "$OUT/gogoham-live-$VER-quellen.iso"
        echo "Quellcode-Abbild: $OUT/gogoham-live-$VER-quellen.iso"
    else
        echo "WARNUNG: kein Quellcode-Abbild entstanden – siehe bau.log"
    fi
fi
# Reste des Baus wegräumen (sonst ~11 GB); der Paket-Zwischenspeicher bleibt für den nächsten Bau.
# Nur wenn im Arbeitsordner nichts mehr eingehängt ist.
if ! grep -q " $W/" /proc/mounts; then
    find "$W" -mindepth 1 -maxdepth 1 ! -name cache -exec rm -rf {} +
fi
echo "FERTIG: $OUT/gogoham-live-$VER.iso"
