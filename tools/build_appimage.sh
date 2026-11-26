#!/usr/bin/env bash
# GoGoHam als AppImage bauen – NUR für Beta-Tester.
#
# Läuft ohne sudo und ohne Container. Alles Nötige wird mitgeliefert und so gewählt, dass es
# auch auf älteren Distributionen läuft (glibc ab 2.28):
#   - Python, Hamlib (rigctld/rigctl), NumPy von conda-forge (gebaut für glibc 2.17)
#   - PySide6 von PyPI (manylinux_2_28), nur die Qt-Teile, die GoGoHam braucht
# NICHT mitgeliefert (lädt der Nutzer wie bisher selbst): cty.dat, Flaggen, Kartenbilder usw.
# Regel-Dateien kommen weiter von GitHub (do2ggh/GoGoHam-rules).
#
# Aufruf:  tools/build_appimage.sh [Bauordner]     (Standard: ~/Projekte/gogoham-appimage)
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${1:-$HOME/Projekte/gogoham-appimage}"
PY=3.13
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/gogoham/__init__.py")"
APPDIR="$WORK/GoGoHam.AppDir"
OUT="$WORK/GoGoHam-$VERSION-beta-x86_64.AppImage"
TOOLS="$WORK/tools"
mkdir -p "$TOOLS"

echo "==> GoGoHam $VERSION – Bauordner $WORK"

# --- Werkzeuge (einmalig) ---------------------------------------------------------------
if [ ! -x "$TOOLS/bin/micromamba" ]; then
    echo "==> micromamba laden …"
    curl -fsSL https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj -C "$TOOLS" bin/micromamba
fi
if [ ! -x "$TOOLS/appimagetool" ]; then
    echo "==> appimagetool laden …"
    curl -fsSL -o "$TOOLS/appimagetool" \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOLS/appimagetool"
fi

# --- Laufzeit: Python + Hamlib + NumPy -----------------------------------------------------
rm -rf "$APPDIR"
export MAMBA_ROOT_PREFIX="$TOOLS/mamba"
echo "==> Python $PY, Hamlib, NumPy (conda-forge) …"
"$TOOLS/bin/micromamba" create -y -q -p "$APPDIR/usr" -c conda-forge --override-channels \
    "python=$PY" hamlib numpy pip ca-certificates
U="$APPDIR/usr"
"$U/bin/rigctld" --version

echo "==> PySide6 (PyPI) …"
"$U/bin/python3" -m pip install -q --no-cache-dir --no-compile PySide6-Essentials PySide6-Addons
SITE="$("$U/bin/python3" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"

# Nur die Qt-Teile behalten, die GoGoHam benutzt (Core, Gui, Widgets, Multimedia, Network, Svg)
echo "==> Unbenutzte Qt-Teile entfernen …"
P6="$SITE/PySide6"
KEEP_PY='^(QtCore|QtGui|QtWidgets|QtMultimedia|QtNetwork|QtSvg|QtDBus|QtTextToSpeech)\.'
for f in "$P6"/Qt*.abi3.so "$P6"/Qt*.pyi; do
    b="$(basename "$f")"
    [[ "$b" =~ $KEEP_PY ]] || rm -f "$f"
done
rm -rf "$P6"/{Qt/qml,Qt/translations,Qt/resources,Qt/libexec,Qt/metatypes,include,typesystems,glue,scripts}
rm -rf "$P6"/{assistant,designer,linguist,lrelease,lupdate,qmllint,qmlformat,qmlls,qsb,balsam,balsamui}
rm -rf "$P6"/Qt/plugins/{designer,qmltooling,sceneparsers,geometryloaders,renderers,renderplugins,sqldrivers,webview,assetimporters,position,sensors,canbus,help,qmllint,scxmldatamodel}
for pat in WebEngine Quick3D 3D Pdf Charts DataVisualization Graphs Designer Help Scxml \
           Sql Test Bluetooth Nfc Positioning Location Sensors SerialBus SerialPort \
           RemoteObjects WebSockets WebChannel WebView HttpServer SpatialAudio \
           VirtualKeyboard Lottie ShaderTools Concurrent StateMachine UiTools Xml Qml Quick \
           LabsQml Labs OpenGLWidgets Uic Linguist Insight Protobuf Grpc; do
    rm -f "$P6"/Qt/lib/libQt6"$pat"*.so*
done
rm -f "$P6"/Qt/plugins/vectorimageformats/libqlottievectorimage.so
# QtMultimedia braucht einige der gelöschten Bibliotheken? Dann hier sofort scheitern.
"$U/bin/python3" -s -c "
from PySide6 import QtCore, QtGui, QtWidgets, QtMultimedia, QtNetwork, QtSvg
print('Qt', QtCore.qVersion(), 'ok')"

# --- GoGoHam selbst ------------------------------------------------------------------------
echo "==> GoGoHam kopieren …"
cp -r "$SRC/gogoham" "$SITE/"
find "$SITE/gogoham" -name __pycache__ -prune -exec rm -rf {} +
"$U/bin/python3" -m compileall -q "$SITE/gogoham" "$U/lib/python$PY" >/dev/null || true

# Aufräumen: Kopfdateien, statische Bibliotheken, Doku, Tests
rm -rf "$U"/{include,share/doc,share/man,share/info,conda-meta,man} "$U"/lib/*.a
rm -rf "$U/lib/python$PY"/{test,idlelib,tkinter,turtledemo,ensurepip,lib2to3}
rm -rf "$SITE"/numpy/{tests,*/tests,_core/tests} "$SITE"/pip "$SITE"/pip-*
mkdir -p "$U/lib/gogoham-bin"                     # nur rigctld/rigctl/rotctld/rotctl kommen in den PATH
ln -s ../../bin/rigctld "$U/lib/gogoham-bin/rigctld"
ln -s ../../bin/rigctl "$U/lib/gogoham-bin/rigctl"
ln -s ../../bin/rotctld "$U/lib/gogoham-bin/rotctld"    # Rotor (0.8.23)
ln -s ../../bin/rotctl "$U/lib/gogoham-bin/rotctl"

# Kein Ablaufdatum mehr (seit 0.10.24.2): das AppImage läuft ohne Zeitgrenze.

# --- AppImage-Rahmen -----------------------------------------------------------------------
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
# GoGoHam Beta-AppImage: mitgeliefertes Python/Qt/Hamlib benutzen, Rest vom System.
HERE="$(dirname "$(readlink -f "$0")")"
export APPDIR="${APPDIR:-$HERE}"
export PATH="$HERE/usr/lib/gogoham-bin:$PATH"   # mitgelieferter rigctld zuerst (passt zur Geräteliste)
export PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
if [ -z "${SSL_CERT_FILE:-}" ]; then              # Zertifikate fürs Internet (GitHub, Cluster, …)
    for f in /etc/pki/tls/certs/ca-bundle.crt /etc/ssl/certs/ca-certificates.crt /etc/ssl/cert.pem \
             "$HERE/usr/ssl/cacert.pem"; do
        [ -r "$f" ] && { export SSL_CERT_FILE="$f"; break; }
    done
fi
exec "$HERE/usr/bin/python3" -s -m gogoham "$@"
EOF
chmod +x "$APPDIR/AppRun"
sed -e "s|^Exec=.*|Exec=gogoham|" -e "s|^Name=GoGoHam|Name=GoGoHam (Beta)|" \
    "$SRC/data/gogoham.desktop" > "$APPDIR/gogoham.desktop"
cp "$SRC/data/icons/hicolor/256x256/apps/gogoham.png" "$APPDIR/gogoham.png"
for d in "$SRC"/data/icons/hicolor/*/apps; do
    install -Dm644 "$d/gogoham.png" "$U/share/icons/hicolor/$(basename "$(dirname "$d")")/apps/gogoham.png"
done

# Prüfen: braucht irgendein Teil eine zu neue glibc?
echo "==> Höchste benötigte glibc-Version:"
find "$U" -type f \( -name '*.so*' -o -perm -u+x \) -print0 2>/dev/null \
    | { xargs -0 objdump -T 2>/dev/null || true; } | grep -oE 'GLIBC_[0-9]+\.[0-9]+' | sort -Vu | tail -1

echo "==> AppImage packen …"
rm -f "$OUT"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOLS/appimagetool" --no-appstream -n "$APPDIR" "$OUT" >/dev/null
ls -lh "$OUT"
echo "Fertig: $OUT"
