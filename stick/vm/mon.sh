#!/bin/bash
# Befehl an den QEMU-Monitor schicken: mon.sh "screendump bild.png -f png"
cd "$(dirname "$0")"
printf '%s\n' "$@" | python3 -c '
import socket, sys, time
s = socket.socket(socket.AF_UNIX); s.connect("mon.sock"); time.sleep(0.2); s.recv(65536)
for line in sys.stdin:
    s.sendall(line.encode()); time.sleep(0.4)
time.sleep(0.3)
try:
    s.settimeout(0.5); print(s.recv(65536).decode(errors="replace")[-500:])
except Exception: pass'
