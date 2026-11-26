"""Sende-Wächter (0.10.46): schaltet das Funkgerät auf Empfang, wenn GoGoHam beim Senden
abstürzt oder hängen bleibt.

rigctld merkt nicht, wenn ein Programm mitten im Senden verschwindet – das Gerät bliebe auf
Senden. Deshalb startet der RigWorker dieses kleine Programm als eigenen Prozess (eigene
Sitzung, damit Strg+C oder ein Absturz es nicht mitreißt). Es bekommt über seine Eingabe:

* ``1`` – GoGoHam schaltet gleich auf Senden
* ``0`` – GoGoHam ist wieder auf Empfang
* ``.`` – Lebenszeichen des RigWorkers (regelmäßig)
* ``g`` – Lebenszeichen der Oberfläche (regelmäßig, falls sie welche schickt)

Endet die Eingabe (GoGoHam beendet – auch abgestürzt oder hart abgeschossen, dann schließt das
System die Leitung) und war zuletzt ``1``, schickt der Wächter ``T 0`` an den rigctld. Ebenso,
wenn beim Senden länger als ``HANG`` Sekunden kein Lebenszeichen kommt; dann meldet er ``off``
auf seiner Ausgabe. Sendet gerade ein anderes Programm (z. B. WSJT-X), hat GoGoHam zuletzt ``0``
gemeldet – dann tut der Wächter nichts.

Nur Standardbibliothek: läuft als Skript (``python3 -I pttguard.py HOST PORT``), ohne GoGoHam
zu laden.
"""
from __future__ import annotations

import os
import select
import socket
import sys
import time

HANG = 10.0          # Sekunden ohne Lebenszeichen beim Senden = hängt
TRIES = 6            # Versuche, auf Empfang zu schalten (rigctld startet evtl. gerade neu)


def unkey(host: str, port: int, tries: int = TRIES, gap: float = 1.0) -> bool:
    """``T 0`` an den rigctld – mehrfach versuchen. True = angenommen."""
    for i in range(tries):
        try:
            with socket.create_connection((host, port), timeout=2.0) as s:
                s.sendall(b"T 0\n")
                s.settimeout(2.0)
                if s.recv(64).startswith(b"RPRT 0"):
                    return True
        except OSError:
            pass
        if i + 1 < tries:
            time.sleep(gap)
    return False


def watch(host: str, port: int, fd_in: int = 0, out=None, hang: float = HANG,
          gap: float = 1.0) -> str:
    """Hauptschleife. Rückgabe, warum sie endet: "eof", "eof-unkey"."""
    out = out or sys.stdout
    on = False
    last = {".": time.monotonic(), "g": None}
    buf = b""
    while True:
        r, _w, _x = select.select([fd_in], [], [], 0.5)
        if r:
            data = os.read(fd_in, 256)
            if not data:                                  # GoGoHam ist weg
                if on:
                    unkey(host, port, gap=gap)
                    return "eof-unkey"
                return "eof"
            buf += data
            *lines, buf = buf.split(b"\n")
            now = time.monotonic()
            for ln in lines:
                c = ln.strip().decode("ascii", "replace")
                if c == "1":
                    on = True
                    last["."] = now
                    if last["g"] is not None:
                        last["g"] = now
                elif c == "0":
                    on = False
                elif c in (".", "g"):
                    last[c] = now
        if on:
            now = time.monotonic()
            quiet = now - last["."] > hang or (last["g"] is not None and now - last["g"] > hang)
            if quiet:
                unkey(host, port, gap=gap)
                on = False
                try:
                    out.write("off\n")
                    out.flush()
                except (OSError, ValueError):
                    pass


def main(argv: list[str]) -> int:
    host, port = argv[1], int(argv[2])
    hang = float(argv[3]) if len(argv) > 3 else HANG
    watch(host, port, hang=hang)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
