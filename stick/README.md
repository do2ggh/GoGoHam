# GoGoHam-Live-Stick

GoGoHam als startfähiger USB-Stick: Debian 13 mit KDE Plasma, GoGoHam fertig eingerichtet.
Logs, Einstellungen und nachinstallierte Programme bleiben auf dem Stick (Datenteil), dazu ein
Austausch-Ordner, den auch Windows lesen kann. Bedienung: Handbuch, Kapitel „Live-Stick“.

## Bauen

    sudo bash stick/bauen.sh

Baut in einem Debian-13-Container (podman): zuerst GoGoHam aus diesem Projekt als Debian-Paket,
dann mit live-build das Abbild `stick/ausgabe/gogoham-live-<Version>.iso` (rund 2,7 GB, etwa
15 Minuten; der Paket-Zwischenspeicher in `stick/arbeit/` macht weitere Bauten schneller).
Nach dem Bau räumt das Skript selbst auf: Die Reste in `arbeit/` verschwinden (der
Zwischenspeicher bleibt), und von den Abbildern bleiben nur das neue und das vorherige.

## Auf einen Stick schreiben

    sudo bash stick/schreiben.sh

Fragt nach dem Stick (nur USB-Laufwerke), mindestens 16 GB. **Neu** löscht alles und legt System,
Datenteil (`GGH-DATEN`, ext4) und Austausch-Ordner (`GoGoHam`, exFAT) an. **Aktualisieren** erneuert
nur das System; Logs und Einstellungen bleiben. Am Ende steht das gemessene Schreibtempo.

Von einem laufenden Stick aus geht es auch ohne PC: *Einstellungen → USB-Stick → Neuen Stick
erstellen …* (Hilfsprogramm `config/includes.chroot/usr/local/sbin/gogoham-stick-kopie`).

## Aufbau

| Datei / Ordner | Inhalt |
|---|---|
| `bauen.sh`, `im-container.sh` | Bau im Container |
| `schreiben.sh`, `aufteilung.sh` | Stick schreiben; Aufteilung (auch auf dem Stick benutzt) |
| `config/` | live-build: Paketliste, Einstellungen, Hilfsprogramme, Startbilder |
| `testbild.sh`, `vm/` | Test in einer virtuellen Maschine (QEMU), ohne echten Stick |
| `werkzeuge/bilder.py` | Startmenü- und Startbild erzeugen |

Nicht im Projekt (zu groß): `arbeit/`, `ausgabe/`, die Dateien der Testmaschine.
