# GoGoHam – Änderungen

Was in jeder Version neu ist, die neueste zuerst. Die Versionsnummern: 0.Y = Sammlung, 0.Y.Z = einzelne Neuerung, 0.Y.Z.W = Kleinigkeiten.

*Changelog of GoGoHam, newest first (in German).*

## Neu in 0.10.47.5

* **Installation unter Arch/Garuda/Manjaro repariert:** Wer GoGoHam 0.10.47.4 nach der Anleitung
  installieren wollte, bekam von pacman „Signatur … ist ungültig“. Der Download-Server lieferte
  noch eine ältere Paketdatei zur neuen Unterschrift aus. Am Programm selbst hat sich nichts
  geändert, das Paket ist nur neu gebaut.

## Neu in 0.10.47.4

* **WS-Update unter Debian/Ubuntu repariert:** War WS noch aus den Paketquellen installiert
  (Paket „wsjtx-improved“), brach das Aktualisieren auf die neue Version vom Entwickler mit
  „dpkg … error code (1)“ ab. GoGoHam ersetzt das alte Paket jetzt im selben Schritt. Ist WSJT-X
  installiert, fragt GoGoHam vorher – beide Programme lassen sich dort nicht gleichzeitig
  installieren.

## Neu in 0.10.47.3

* Interne Vorbereitungen.

## Neu in 0.10.47.2

* Interne Vorbereitungen.

## Neu in 0.10.47.1

* **In der Software-Verwaltung zu finden:** GoGoHam bringt jetzt eine AppStream-Beschreibung mit
  (Deutsch und Englisch, mit Bildern). Mit der GoGoHam-Paketquelle zeigen Discover, GNOME Software
  & Co. es unter „Amateurfunk“ und bei der Suche nach „Contest“ oder „Logger“. Der
  Startmenü-Eintrag hat englische Texte und mehr Suchwörter bekommen.

## Neu in 0.10.47

* **Per Knopf aktualisieren – auch mit install.sh:** *Hilfe → Nach neuer Version suchen …* öffnet
  das Fenster „GoGoHam aktualisieren“. Ein Klick holt die neue Version von GitHub, lädt sie zur
  Probe und spielt sie beim Neustart ein. Fehlt dem Rechner etwas für die neue Version, bleibt
  alles, wie es ist. „Zurück zur vorigen Version“ tauscht beim nächsten Start zurück.

## Neu in 0.10.46.1

* Behoben: *Hilfe → Nach neuer Version suchen …* tat auf einem normalen Rechner nichts (nur auf
  dem Live-Stick ging es).
* Aufgeräumt: nicht mehr benutzte Programmteile entfernt; der Ausweich-Ordner unter `/tmp` (nur
  ohne eigenen Laufzeit-Ordner des Systems) wird nur benutzt, wenn er wirklich dir gehört.

## Neu in 0.10.46

* **Sende-Wächter:** Stürzt GoGoHam beim Senden ab oder hängt es sich auf, schaltet ein kleiner
  Wächter das Funkgerät auf Empfang – sofort beim Absturz, nach 10 Sekunden beim Hänger. Gilt für
  PTT über CAT und über DTR/RTS; sendet gerade ein anderes Programm, bleibt er still.
* **PTT über DTR/RTS auch bei mitbenutzten Diensten:** Benutzt GoGoHam den rigctld eines anderen
  Dienstes mit, der die Leitung nicht schaltet, fragt es einmal und trägt sie dort ein – mit
  Sicherungskopie und kurzem Neustart, nur wenn gerade niemand sendet.

## Neu in 0.10.45

* **PTT über DTR/RTS für alle Programme:** Ist im Funkgerät-Profil „PTT über die DTR- oder
  RTS-Leitung“ eingestellt, schaltet jetzt der rigctld die Leitung – GoGoHam öffnet die
  Schnittstelle nicht mehr selbst. So stört GoGoHam keine anderen Programme, und WSJT-X, fldigi,
  GoGoHome und GoGoHandy senden mit „PTT über CAT“ von selbst über dieselbe Leitung. Auch
  „PTT testen“ geht über den rigctld. Schaltet ein fremder rigctld die Leitung nicht, sagt
  GoGoHam das in der Statuszeile. Icom-Geräte mit PTT am selben USB-Anschluss senden über CAT.

## Neu in 0.10.44

* Interne Vorbereitungen – am Programm ändert sich für dich nichts.

## Neu in 0.10.43

* **GoGoHam, GoGoHome und GoGoHandy gleichzeitig:** Pro Funkgerät läuft nur noch ein rigctld.
  Hält schon ein anderer Dienst das Gerät, benutzt GoGoHam ihn mit, statt einen zweiten
  anzulegen – auch auf einem anderen Port. Ein hängender Dienst (z. B. vor der GoGoHandy-Brücke
  gestartet) wird beim Erkennen neu gestartet statt abgeschaltet.
* **WSJT-X & Co. für alle Programme:** GoGoHam richtet WS auf die Gruppe 224.0.0.1 über die interne
  Verbindung ein. So bekommen GoGoHam, GoGoHome und Log-Programme alle QSOs gleichzeitig, auch ohne
  Netzwerk, und jedes kann WS antworten. 127.0.0.1 wird einmal umgestellt.
* **fldigi für alle Programme:** Laufen GoGoHam und GoGoHome gleichzeitig, reicht das Programm, das
  ein QSO von fldigi bekommt, es an das andere weiter.

## Neu in 0.10.42.1

* Behoben: Unter KDE öffnete „E-Mail-Programm öffnen“ nichts, wenn Thunderbird als Flatpak
  installiert ist (KDE baute einen fehlerhaften Startbefehl). GoGoHam öffnet E-Mails unter Linux
  jetzt über `xdg-open` – das startet das eingestellte E-Mail-Programm so, wie es installiert ist.
  Gilt auch für „Kontakt zu DO2GGH“, den Fehlerbericht und die Adresse im Über-Fenster.

## Neu in 0.10.42

* **Bayerischer Bergtag ohne Zusatzprogramm:** Beim BBT schreibt GoGoHam statt EDI je Band eine
  Textdatei mit **BBT-Deckblatt** (nach dem Formular 01/2026) und **Logblatt**. Gesamt-km,
  QSO-Zahl, km/QSO, bestes DX und gearbeitete Länder rechnet GoGoHam aus. Standort, Höhe,
  Station und Gewichte trägst du einmal in einem kleinen Fenster ein. GoGoHam warnt über 10 kg
  bzw. 10 W. Danach öffnet „Wohin mit dem Log?“ die Mail an den BBT-Auswerter.
* Behoben: Logs, die vor 0.10.41 angelegt wurden, zeigten nach dem Export keinen Einsendeweg.

## Neu in 0.10.41.1

* **REF Contest CW und SSB entfernt (130 Contests):** Die Seite des Veranstalters lässt keine
  automatische Prüfung der Regeln und des Einsendewegs zu.
* Contests, die das Regel-Projekt nicht mehr führt, verschwinden beim nächsten Regel-Abgleich auch
  aus den heruntergeladenen Regeln. Eigene Regel-Dateien bleiben immer.

## Neu in 0.10.41

* **Wohin mit dem Log?** Nach dem Export zeigt GoGoHam den genauen Einsendeweg des Contests:
  E-Mail-Adresse und/oder Upload-Seite als Link, den Einsendeschluss mit Datum („noch … Tage“) und
  Hinweise wie einen vorgeschriebenen Dateinamen. Ein Klick öffnet das E-Mail-Programm mit Empfänger
  und Betreff bzw. die Upload-Seite – und zugleich den Ordner mit der markierten Log-Datei zum
  Hineinziehen.
* Einsendewege für 121 Contests aus den aktuellen Ausschreibungen. Wo der Weg nicht eindeutig
  gesichert ist, steht der Link zur Ausschreibung.

## Neu in 0.10.40

* **Funkgerät gleichzeitig am Handy und am PC:** Hält die GoGoHandy-PC-Brücke ein Icom-Gerät fest,
  geht GoGoHam von selbst über deren virtuelle Schnittstelle. Das gilt für „Gerät erkennen“,
  „Verbindung testen“, den eigenen rigctld und den Hintergrund-rigctld. Läuft die Brücke nicht,
  geht alles wie bisher direkt ans Gerät. Die Brücke wird nie angehalten.

## Neu in 0.10.39

* **Neues Design „Nightshift“** in zwei Varianten, hell und dunkel (Einstellungen → Darstellung →
  Design): Farbverläufe in Bernstein und Türkis-Blau, Menüleiste und Zusatzfenster-Titel mit
  Bernstein-Linie, abgerundete Knöpfe und Rahmen, schwacher Lichtschein im Fensterhintergrund.
* Auch bei Farbenblindheit gut lesbar: Im dunklen Nightshift nimmt GoGoHam hellere Warnfarben
  (Dupe, Multi, Fehler), im hellen ein kräftigeres Orange. Eine markierte Zeile hat links einen
  Türkis-Balken, und Dupe und Multi behalten dort ihre Farbe. Zeichen und Texte bleiben gleich.

## Neu in 0.10.38

* **5 neue deutsche Contests (132 Contests):** VFDB DLPX-Contest CW und SSB · AGCW
  Handtastenparty 80 m und 40 m · AGCW Schlackertasten-Abend. Alle nach den aktuellen
  Ausschreibungen; Contests mit unklaren Regeln sind bewusst nicht dabei.
* Neu dafür: Nummer, Klasse, Name und Alter im Austausch (Handtastenparty) und Sonderstationen
  als Multi (DLPX).
* Regel-Dateien: neues Format 24. Ältere GoGoHam-Versionen überspringen diese Dateien.

## Neu in 0.10.37

* **8 neue Contests (127 Contests):** North Carolina QSO Party · Washington State Salmon Run ·
  UN DX Contest · PODXS 070 Club St. Patrick's Day, New Member Jamboree, 160m Great Pumpkin
  Sprint, Triple Play Low Band Sprint und DOUBLEHEADER. Alle nach den aktuellen Ausschreibungen;
  Contests mit unklaren Regeln sind bewusst nicht dabei.
* Neu dafür: Bonuspunkte für Bonusstationen (je Station oder je Mode, Zusatzbonus für alle),
  der Buchstaben-Bonus „Erin Go Bragh“, Mitgliedsnummer + Beitrittsjahr mit Punkten nach
  Nummernbereich.
* Behoben: Bei Contests mit Zusatzbonus (Texas QSO Party) zeigte die Spalte „Gewinn“ ab dem
  ersten Bonus zu wenig an.
* Regel-Dateien: neues Format 23. Ältere GoGoHam-Versionen überspringen diese Dateien.

## Neu in 0.10.36

* **11 neue Contests (119 Contests):** Ohio, Michigan, Indiana, Texas und New York QSO Party ·
  RSGB 1.8 MHz Contests (Februar und November) · Oceania DX Contest (Phone und CW) · UK/EI DX
  Contest CW · PODXS 070 Club PSKFest. Alle nach den aktuellen Ausschreibungen; Contests mit
  unklaren Regeln sind bewusst nicht dabei.
* Neu dafür: County-Kürzel jeder Länge, höchstens zwei Countys an einer Grenze, der Bonus für
  Mobilstationen (Texas), Bonuspunkte statt Multis (RSGB), „nur QSOs mit Ozeanien“, die
  Punktetabelle UK/EI – Europa – Rest mit doppelten Nachtpunkten und die Bezirksspalte im
  Cabrillo (RSGB, UK/EI).
* Behoben: Bei den QSO-Partys zählte ein QSO mit zu vielen Countys in einer Zeile trotz Hinweis mit.
* Regel-Dateien: neues Format 22. Ältere GoGoHam-Versionen überspringen diese Dateien.

## Neu in 0.10.35

* **2 neue Contests (108 Contests):** New England QSO Party (NEQP, CW und SSB) · 7th Call Area
  QSO Party (7QP, CW, SSB und Digital). GoGoHam rechnet beide für Stationen außerhalb des
  Gebiets.
* Neu dafür: County-Kürzel im Austausch mit der vollständigen County-Liste, Stationen auf
  County-Grenzen (7QP: `UTRIC/IDBEA` zählt doppelt) und Mobilstationen, die im neuen County
  wieder gearbeitet werden dürfen.
* Regel-Dateien: neues Format 21. Ältere GoGoHam-Versionen überspringen diese Dateien.

## Neu in 0.10.34

* **4 neue Contests (106 Contests):** EA RTTY Contest · EA PSK63 Contest · JARL World Wide RTTY
  Contest · Alessandro Volta RTTY DX Contest. Alle nach den aktuellen Ausschreibungen; Contests
  mit unklaren Regeln sind bewusst nicht dabei.
* Neu dafür: Nummer + CQ-Zone im Austausch und Punkte nach der Zonen-Tabelle des Veranstalters,
  doppelte Punkte für andere Kontinente auf 80 und 10 m, „nicht im eigenen Land bzw.
  Rufzeichengebiet“, Ergebnis = QSOs × Punkte × Multis und der Zusatz-Multi für Länder anderer
  Kontinente auf 4 Bändern (Volta); die EADX-100-Länderliste (EA RTTY, EA PSK63); PSK63 als
  Betriebsart.
* Regel-Dateien: neues Format 20. Ältere GoGoHam-Versionen überspringen diese Dateien.

## Neu in 0.10.33

* **14 neue Contests (102 Contests):** ARRL November Sweepstakes CW und SSB · Africa All Mode
  International DX Contest · Baltic Contest · SARTG WW RTTY · SARTG New Year RTTY · Makrothen
  RTTY · ARRL June VHF und September VHF · CQ WW VHF (SSB/CW und Digital) · IARU Region 1
  50 MHz und 70 MHz · Alpe Adria UHF/SHF. Alle nach den aktuellen Ausschreibungen; Contests mit
  unklaren Regeln sind bewusst nicht dabei.
* Neu dafür: der Sweepstakes-Austausch (Nummer, Precedence, Rufzeichen, Check, Section – die
  Precedence ergibt sich aus den Kategorien), „jede Station nur einmal im Contest“, Nummer +
  Vorname (SARTG Neujahr), Punkte nach Kilometern × Bandfaktor (Makrothen), 4-stellige
  Locator-Quadrate als Multi (CQ WW VHF, ARRL VHF) und die US-Bänder 222 MHz und 902 MHz.
* Regel-Dateien: neues Format 19. Ältere GoGoHam-Versionen überspringen diese Dateien.

## Neu in 0.10.32

* **15 neue Contests (88 Contests):** JIDX CW und SSB · Scandinavian Activity Contest CW und
  SSB · RAC Canada Day · North American QSO Party (NAQP) CW, SSB und RTTY · Alpe Adria VHF ·
  ARRL International Digital (FT8/FT4) · BARTG HF RTTY · DIG-QSO-Party Kurzwelle SSB und CW ·
  Deutscher Telegrafie Contest (DTC) · All Austrian 160m Contest (AOEC). Alle nach den aktuellen
  Ausschreibungen; Contests mit unklaren Regeln sind bewusst nicht dabei.
* Neu dafür: Vorname im Austausch (NAQP – GoGoHam nimmt das erste Wort aus *Name* in den
  Log-Einstellungen), Uhrzeit im Austausch (BARTG), Kontinente als eigener Faktor, feste Punkte
  für Klub- und Verbandsstationen (RAC, DTC), Kfz-Kennzeichen beim DTC (auch mit Umlaut).
* Behoben: In den UBA-Contests wurde der Berg Athos nicht als EU-Land erkannt; im ARRL 160 m
  zählt Swains Island jetzt richtig als W/VE.
* Regel-Dateien: neues Format 18. Ältere GoGoHam-Versionen überspringen diese Dateien.

## Neu in 0.10.31

* **Zwei neue Contests für 160 m (73 Contests):**
  * **ARRL 160 m** (erstes volles Wochenende im Dezember, nur CW): Als DX-Station arbeitest du
    nur USA und Kanada; sie senden ihre ARRL/RAC-Section (z. B. EMA, ONS). GoGoHam kennt alle
    85 Sections, prüft die Eingabe und belegt sie vor, wenn sie aus dem Rufzeichen eindeutig
    folgt (z. B. KH6 = PAC). Alaska, Hawaii, Puerto Rico und die übrigen US-Gebiete zählen hier
    als W/VE.
  * **Stew Perry Topband Challenge** (letztes volles Wochenende im Dezember, nur CW):
    Austausch ist der 4-stellige Locator, Punkte nach Entfernung (1 + 1 je volle 500 km). Der
    Faktor für die eigene Leistung (LOW ×1,5, QRP ×3) kommt aus *Kategorie Leistung*.
* Im Fenster *Log* nimmt das Feld *Eigener State/Provinz/Section* jetzt auch ARRL-Sections an.
* Im ADIF steht die Section im Feld `ARRL_SECT`.
* Regel-Dateien: neues Format 17 (Sections, „nur Rapport“, Punkte W/VE–DX, Leistungsfaktor).
  Ältere GoGoHam-Versionen überspringen diese Dateien.

## Neu in 0.10.30.1

* **Kein Nachinstallieren mehr für den Ton:** GoGoHam spricht jetzt direkt mit dem Tonsystem
  (PipeWire/PulseAudio). Die Netzwerk-Soundkarte für Icom-Geräte und die Erkennung der
  Funkgerät-Soundkarte brauchen das Programm `pactl` nicht mehr (es bleibt nur als Notweg).
* **Soundkarte für die Sprachspeicher wird automatisch gewählt** – dieselbe, die GoGoHam auch
  für WS und fldigi findet, passend zum gerade benutzten Funkgerät. Im Fenster Sprachaufnahmen
  steht dann „Automatisch: …“; eine Wahl von Hand geht weiterhin und hat Vorrang.

## Neu in 0.10.30

* **Funkgeräte über das Netzwerk (LAN/WLAN), Beta:** In *Einstellungen → Funkgerät* gibt es
  „Verbunden über“:
  * **Netzwerk – Icom** (IC-705, IC-7610, IC-9700, IC-905 …): GoGoHam spricht Icoms
    Netzwerk-Fernsteuerung selbst, ohne Zusatzprogramm. „Im Netz suchen“ findet das Gerät,
    dazu Benutzername und Passwort aus dem Funkgerät. WSJT-X, fldigi & Co. verbinden sich wie
    gewohnt über rigctld. Der **Ton** kommt als eigene Soundkarte ins System; GoGoHam trägt sie
    bei WSJT-X/fldigi ein und nutzt sie für die Sprachspeicher.
  * **Netzwerk – andere Hersteller**: Geräte, die Hamlib selbst über das Netz steuert (z. B.
    Elecraft K4, FlexRadio), mit Adresse und Port.
  * **Funkgerät an einem anderen Rechner**: rigctld auf einem anderen Rechner im Heimnetz
    (z. B. Raspberry Pi) – „Im Netz suchen“ findet ihn.
* Verbindungstest und PTT-Test funktionieren auch übers Netzwerk; klare Meldungen bei falschem
  Passwort oder wenn das Gerät schon mit einem anderen Programm verbunden ist.
* Die Icom-Anbindung ist bisher nur gegen ein nachgebautes Gerät geprüft – Rückmeldungen mit
  echten Geräten sind sehr willkommen.

## Neu in 0.10.29

* **Acht neue Sprachen (Beta):** Polnisch, Tschechisch, Slowakisch, Ukrainisch, Niederländisch,
  Ungarisch, Kroatisch und Türkisch – nur die Oberfläche, das Handbuch bleibt Deutsch/Englisch.
  Noch nicht von Muttersprachlern durchgesehen; Hinweise und Verbesserungen sind willkommen.
  Damit gibt es GoGoHam in 20 Sprachen.
* **Sprachauswahl** (Einstellungen → Darstellung): die Liste ist jetzt alphabetisch sortiert und
  klappt als kurze, scrollbare Liste auf statt über den ganzen Bildschirm.

## Neu in 0.10.28.2

* **Frankencontest:** Stationen außerhalb Deutschlands senden jetzt `NM` statt ihres DOKs, auch
  wenn sie DARC-Mitglied sind – so verlangt es die Ausschreibung 2026. Das 70-cm-FM-Segment der
  Klasse L endet wie in der Ausschreibung bei 433,9875 MHz.
* Nachgeprüft und bestätigt: Termine, Frequenzen, Austausch und Wertung aller acht
  Franken-Klassen, der Cabrillo-Name des DARC-Fieldday CW und die Kilometer-Wertung der
  DARC-UKW-Conteste und des Marconi Memorial (Kilometer + 1 nach IARU-Methode).

## Neu in 0.10.28.1

* **Russian DX:** Russische Stationen in der Antarktis (RI1AN…) zählen wie das europäische
  Russland (10 Punkte für Stationen außerhalb Russlands) und senden ihren Bezirk `AN`. Sie bringen
  zwei Multis: das Land Antarktis und den Bezirk AN (Reglement 2026, Punkt 7.3).

## Neu in 0.10.28

* **Regeln geprüft und korrigiert:** Alle Contest-Regeln wurden mit den aktuellen Ausschreibungen
  verglichen. Korrigiert:
  * **CQ WW 160 m CW:** Der Termin ist das letzte volle Wochenende im Januar (Beginn Freitag
    22 UTC). Bisher rechnete GoGoHam in Jahren mit fünf Januar-Samstagen eine Woche zu früh –
    2027 zum Beispiel 22. statt 29. Januar.
  * **WAE DX CW und SSB:** Die Frequenzbereiche der Ausschreibung sind die *contestfreien*
    Bereiche. GoGoHam hatte sie als erlaubte Bereiche geführt und warnte deshalb an der falschen
    Stelle. Beim WAE RTTY ist 14099–14101 kHz contestfrei.
  * **OK/OM DX:** QSOs mit Russland und Belarus zählen nicht, Maritime Mobile bringt 5 Punkte
    (ohne Multi). Die Bezirke prüft GoGoHam jetzt gegen die offizielle Liste (165 Kürzel).
  * **REF Contest:** Französische Stationen zählen wie im Règlement – Frankreich gleicher
    Kontinent 6, anderer Kontinent 15, Ausland 1 bzw. 2. Maritime Mobile bringt 3 Punkte (auch
    für Stationen außerhalb Frankreichs). Länder-Multis nur nach DXCC.
  * **AGCW QRP/QRP-Party:** Multis sind DXCC-Länder; WAE-Sondergebiete zählen nicht extra.
  * **PACC:** Kanadische Gebiete VE1, VO1 und VY1 zählen als getrennte Multis.
  * **All Asian:** Für Stationen in Asien zählt Maritime Mobile wie ein QSO in Asien.
  * **Cabrillo-Namen:** Ostercontest `EASTER`, Weihnachtswettbewerb `XMAS`, DARC FT4 `FT4`,
    YO DX `YO-DX-HF`.
* Die korrigierten Regeln kommen auch über das Regel-Update (*Contest-Regeln jetzt aktualisieren*). Ältere GoGoHam-Versionen
  bekommen REF und PACC erst nach dem Update auf 0.10.28 (neues Regel-Format 16).

## Neu in 0.10.27

* **Zehn neue Sprachen für die Oberfläche (Beta):** Spanisch, Französisch, Portugiesisch,
  Russisch, Indonesisch, Italienisch, Dänisch, Schwedisch, Norwegisch und Finnisch – zusammen mit
  Deutsch und Englisch jetzt zwölf. Die neuen sind noch nicht von Muttersprachlern durchgesehen und
  tragen deshalb „(Beta)“ in der Auswahl (*Einstellungen → Darstellung → Sprache*).
* Fehlt in einer Sprache ein Text, erscheint jetzt Englisch statt Deutsch. Das Handbuch gibt es
  weiter auf Deutsch und Englisch; bei allen anderen Sprachen öffnet sich das englische.
* Ansagen: Gibt es für die eingestellte Sprache keine Piper-Stimme, spricht die Sprachausgabe des
  Systems – vorher las die englische Stimme z. B. französischen Text.
* Sprachaufnahmen: Die Gruppe heißt jetzt *Aussenden* (über das Funkgerät) statt *Senden*.

## Neu in 0.10.26

* **Zwei neue deutsche Contests (jetzt 71):**
  * **HSC CW Contest** des High Speed Club – zweimal im Jahr (letzter Sonntag im Februar, erster
    Sonntag im November, 14–17 UTC). Austausch RST + HSC-Nummer oder `NM`; Mitglieder 5 Punkte,
    Nichtmitglieder 2, Länder je Band als Multi. Deine Nummer kommt aus *Log → Mitgliedsnummer*.
  * **Schwaben-Contest** des DARC-Distrikts Schwaben (erster Samstag im Januar, nie an Neujahr) – getrennt für
    **Kurzwelle** (80/40 m) und **UKW** (2 m/70 cm). Austausch DOK (ohne DOK die laufende Nummer),
    auf UKW dazu der Locator. Schwaben-DOKs (T, Z30) 5 Punkte, Klubstationen und
    Ausbildungsrufzeichen aus Schwaben 10. Jede Betriebsart hat ihr Zeitfenster; auf UKW zählen SSB
    und FM getrennt.
* Contest-Kalender, Countdown und Erinnerung kennen jetzt Contests mit **mehreren verschiedenen
  Terminen im Jahr** (HSC).

## Neu in 0.10.25

* **GPS-Empfänger per USB** – für den Portabelbetrieb, am PC und auf dem Live-Stick. Einstecken
  genügt, egal an welche Buchse: GoGoHam erkennt den Empfänger und fragt *„GPS-Empfänger gefunden –
  verwenden?“* (Verwenden / Jetzt nicht / Nie für dieses Gerät). Danach kommt er ohne Frage wieder,
  auch an einer anderen Buchse.
  * **Standort und Locator:** Anzeige unten in der Statuszeile (🛰 GPS JN59me · 9 Sat). Passt der
    Locator im Log nicht zum Standort, fragt GoGoHam, ob er übernommen werden soll. Ein neues Log
    bekommt den GPS-Locator gleich mit. Karte, Rotor-Richtung und Baken rechnen mit dem GPS-Standort.
  * **Uhrzeit:** GoGoHam vergleicht die GPS-Zeit mit der PC-Uhr und bietet an, die Uhr nach GPS zu
    stellen – auch ohne Internet.
  * Alle Satellitensysteme (GPS, GLONASS, Galileo, BeiDou), Geschwindigkeit automatisch; läuft
    `gpsd`, kommen die Daten von dort. Neuer Bereich *Einstellungen → GPS* mit Live-Anzeige.
  * Sicherheit: Allgemeine USB-Adapter (wie in Funkgeräten und Interfaces) und Anschlüsse aus einem
    Funkgeräte-Profil öffnet GoGoHam nie von selbst – es wird nur gelesen, nie gesendet.
* **USB-Geräte sofort freigeben:** Funkgerät-Kabel, GPS-Empfänger, WinKeyer und Rotor-Steuerung
  gehören jetzt dem angemeldeten Benutzer – ohne Gruppe und ohne neu anmelden. Die Pakete und der
  Live-Stick bringen die Freigabe mit; beim AppImage bietet GoGoHam sie einmal beim Start an
  (*Jetzt freigeben*, Systempasswort).

## Neu in 0.10.24.1

* Live-Stick: Beim Aktualisieren bleibt nur noch die neueste Version liegen, ältere werden gleich
  gelöscht. Der Rückweg ist die Version, die mit dem Stick kam (*Zurück zur Fassung des Sticks*).

## Neu in 0.10.24

* **GoGoHam auf dem Live-Stick per Knopf aktualisieren:** *Hilfe → Nach neuer Version suchen …*
  holt auf dem Stick die neueste Version aus der GoGoHam-Paketquelle und spielt sie in den
  Datenteil ein – ein neues Stick-Abbild ist dafür nicht mehr nötig. Logs und Einstellungen
  bleiben erhalten. Die Paketquelle muss richtig unterschrieben sein; fehlen auf dem Stick
  Programme, die die neue Version braucht, wird nichts eingespielt. Ein neueres Stick-Abbild
  gewinnt von selbst, *Zurück zur Fassung des Sticks* löscht die Aktualisierungen wieder.

## Neu in 0.10.23

* **Neue Contests für deutsche Funkamateure:**
  * **AGCW QRP-Contest** (2. Samstag im März) – Austausch mit Leistungsklasse und
    Mitgliedsnummer, Punkte nach den Klassen beider Stationen.
  * **AGCW QRP/QRP-Party** (1. Mai) – Klasse A oder B, gerechnet wird je Band.
  * **Frankencontest** (2. volles Wochenende im Mai) – je Teilnehmerklasse A bis L ein eigener
    Eintrag, auf UKW DOK + Locator und Kilometer, QSOs im eigenen DOK zählen 0, Multis sind die
    fränkischen DOKs und alle Sonder-DOKs.
  * **Bayerischer Bergtag** – vier Einträge, je Wochenende einer (Winter und Sommer), mit den
    Zeitfenstern je Band.
* **Leistungsklasse** im Fenster *Log*: Auswahlliste mit den Klassen der Ausschreibung (nur bei
  Contests, die eine Klasse verlangen).
* Regel-Dateien: neues Format 14 (Leistungsklassen, DOK + Locator, Wertung je Band). Ältere
  GoGoHam-Versionen überspringen diese Dateien; die Bergtag-Dateien laufen auch dort.

## Neu in 0.10.22

* **Live-Stick richtet sich beim ersten Start selbst ein:** Das Stick-Abbild lässt sich jetzt mit
  jedem üblichen Programm schreiben (balenaEtcher, Fedora Media Writer, dd, Rufus im DD-Modus). Beim
  ersten Start legt der Stick im freien Platz Datenteil und Austausch-Ordner an – einmalig, mit
  Hinweis im Startbild. Angefasst wird nur der Stick, von dem gestartet wird, und nur freier Platz.
* **Warnung „Dieser Stick speichert nichts“:** Fehlt der Datenteil (Stick zu klein oder im
  ISO-Modus geschrieben), sagt GoGoHam das bei jedem Start deutlich.

## Neu in 0.10.21.1

* **Installation über die Paketquellen:** GoGoHam gibt es jetzt als Paket für openSUSE Tumbleweed und
  Leap 16, Fedora 43 und 44, Debian 13, Ubuntu 26.04 und Arch – mit dem normalen Systemupdate immer
  aktuell. Die Befehle stehen in der README (Abschnitt „Installation“); getestet auf frischen Systemen.
* Pakete: openSUSE bringt jetzt das vollständige Python mit (ohne sqlite3 startete GoGoHam dort
  nicht), Arch die SVG-Unterstützung von Qt.

## Neu in 0.10.21

* Interne Vorbereitungen – am Programm ändert sich für dich nichts.

## Neu in 0.10.20.1

* **Neuen Stick erstellen – Start-Stick sicherer erkannt:** Das System hängt den Stick oft über einen
  Umweg ein (`/dev/loop0`). GoGoHam und das Hilfsprogramm des Sticks folgen diesem Umweg jetzt und
  erkennen den Stick, von dem gerade gestartet wurde, auch daran (gefunden beim Test in der
  virtuellen Maschine; geschützt war er schon vorher über seine Einhängepunkte).

## Neu in 0.10.20

* **Live-Stick: Neuen Stick erstellen.** Unter *Einstellungen → USB-Stick* macht GoGoHam aus einem
  anderen USB-Stick (ab 16 GB) einen frischen GoGoHam-Stick – ohne Internet und ohne PC, z. B. für
  einen Funkfreund, der seinen eigenen Stick mitbringt. Der neue Stick bekommt dieselbe Version, aber
  keine Logs, Einstellungen oder Passwörter. Angeboten werden nur USB-Sticks, nie die eingebaute
  Festplatte und nie der Stick, von dem GoGoHam läuft; vor dem Löschen fragt GoGoHam deutlich nach.
  Nach dem Schreiben wird alles geprüft, am Ende steht das Schreibtempo des neuen Sticks da.
  Braucht einen Stick ab 0.10.20.
* **Live-Stick: „Datei → Beenden und herunterfahren …“** – auf dem Stick heißt der Menüpunkt
  so und schaltet nach einer Rückfrage gleich den Rechner aus. Der Knopf „Rechner herunterfahren …“
  unter Einstellungen → USB-Stick ist dafür entfallen. Auf einem normalen PC bleibt es bei „Beenden“.

## Neu in 0.10.19.1

* **Gelber Übungsrand verdeckt nichts mehr:** Er lag über der Menüleiste und unten über dem
  Funkwetter (SFI, A, K). Jetzt rückt der Fensterinhalt während der Übung ein Stück nach innen, und der
  Rand liegt außen herum.

## Neu in 0.10.19

* **Übungsmodus unübersehbar markiert:** Damit man die Übung nicht mit dem Ernstfall verwechselt
  (und zum Mikrofon greift), hat das Hauptfenster während der Übung einen **leuchtend gelben Rand**,
  vorn im Fenstertitel steht „⚠ ÜBUNGSMODUS – es wird nichts gesendet“ (auch in der Taskleiste), der
  Balken oben ist gelb mit großer Schrift, und das Rufzeichenfeld ist gelb hinterlegt.
* **Karte im Übungsmodus:** Bei S&P und Gemischt zeigt die Karte jetzt die nachgebildeten Spots der
  Übung (wie die Bandmap); in der Run-Übung steht dort „Spots: in der Run-Übung gibt es keine“. Die
  Baken laufen auch in der Übung – das Reverse Beacon Network wird nur gehört.
* **Live-Stick: Zusatzprogramme auf dem Desktop.** Installierst du WS oder fldigi, liegt danach eine
  Verknüpfung auf dem Desktop; beim Deinstallieren verschwindet sie wieder.
* **Handbuch-Suche mit Trefferliste:** Kapitel, deren Überschrift passt, stehen ganz oben, darunter
  jede Fundstelle mit Kapitel und Textausschnitt. Bindestriche, Leerzeichen und Groß-/Kleinschreibung
  sind egal – „autocq“ findet „Auto-CQ“.
* **Handbuch durchgesehen:** veraltete Menünamen (Ansicht, Log) und eine längst überholte
  Menü-Beschreibung in Kapitel 2 entfernt, die Bereiche der Einstellungen richtig aufgezählt,
  Regel-Formate 12 und 13 ergänzt; Hinweise „kommt in einer späteren Version“ beim WAE RTTY und beim
  Stationslog entfernt – beides gibt es längst. Auch die Datei „LIESMICH.txt“ auf dem Stick nennt
  jetzt den richtigen Weg (Log & Contest → Log öffnen).

## Neu in 0.10.18

* **Handbuch, Kapitel Live-Stick:** neuer Abschnitt „Welcher Stick?“ (mindestens 16 GB, besser
  USB 3; was bei langsamen Sticks zu erwarten ist). Secure Boot muss nicht ausgeschaltet werden –
  der Stick startet auch damit (getestet).

## Neu in 0.10.17

* **Zusatzprogramme deinstallieren:** Neben jedem installierten Programm (WS, fldigi) steht jetzt
  „Deinstallieren …“. GoGoHam entfernt das Programm auf demselben Weg, auf dem es gekommen ist
  (Paketverwaltung oder Flatpak), fragt vorher nach und nur, wenn das Programm geschlossen ist.
  Entfernt wird nur das Programm selbst – braucht ein anderes Programm es noch, bricht GoGoHam ab.
  Bei fldigi werden nicht mehr gebrauchte Flatpak-Bestandteile mit entfernt (gibt bis gut 1 GB
  frei). **Einstellungen und Logs des Programms bleiben erhalten.**
* **JTDX ist nicht mehr dabei.** Es gab keine Quelle, aus der es sich auf allen Systemen sicher
  installieren ließ. Ein schon installiertes JTDX bleibt auf dem Rechner; war es als FT8-Programm
  gewählt, nimmt GoGoHam jetzt WS.

## Neu in 0.10.16

* **JTDX improved** (2.2.159) installiert GoGoHam jetzt auf allen gängigen Systemen: unter Fedora
  und openSUSE direkt von SourceForge (`.rpm`, Prüfsumme geprüft), unter Arch/Garuda aus dem AUR
  (`jtdx-improved`), unter Debian/Ubuntu aus den Paketquellen (dort ist es schon die neueste
  Fassung). Mit „Aktualisieren“, sobald es eine neuere Version gibt.
* **Fehler behoben:** „Zur Downloadseite“ bei JTDX öffnete eine fremde Seite – die alte Adresse
  gehört nicht mehr zum JTDX-Projekt. Jetzt: SourceForge (jtdx-improved); bei fldigi die
  Flathub-Seite.
* **WS auf älteren Systemen** (Debian 12, Ubuntu 22.04, Mint 21 …): GoGoHam nimmt automatisch die
  dafür gebaute Variante von DG2YCB.

## Neu in 0.10.15

* **Contest-Kalender: QR-Code fürs Handy.** Neuer Knopf (auch per Rechtsklick): Der gewählte
  Contest erscheint als QR-Code – mit der Handy-Kamera scannen und „Zum Kalender hinzufügen“,
  ohne Datei und ohne Internet. Mit **Erinnerung**, einstellbar (keine bis 1 Tag vorher,
  Voreinstellung 1 Stunde); die Erinnerung steckt jetzt auch in der Kalenderdatei (.ics).
* Für die QR-Codes liegt die kleine Bibliothek **segno** (BSD-Lizenz) bei – sie funktioniert so
  auf jedem System ohne Nachinstallieren.

## Neu in 0.10.14

* **fldigi immer in der neuesten Version – von Flathub.** „Installieren“ holt fldigi jetzt von
  Flathub (die Paketquellen hinken oft hinterher: Debian 13 hat 4.2.06, Flathub 4.2.13). Fehlt
  `flatpak`, installiert GoGoHam es mit. GoGoHam startet und richtet das Flatpak genauso ein wie
  bisher (Soundkarte, Funkgerät, Makros, Weitergabe der QSOs).
* **„Neue Version verfügbar“:** Bei WS und fldigi zeigt *Einstellungen → Zusatzprogramme* die
  installierte Version und – wenn es eine neuere gibt – z. B. „installiert 4.2.06 – neu: 4.2.13“
  mit dem Knopf **Aktualisieren**.

## Neu in 0.10.13

* **WS von DG2YCB statt WSJT-X:** Bei den Zusatzprogrammen steht jetzt **WS** („WS – Digital
  Mode Suite“, früher WSJT-X Improved, von Uwe Risse DG2YCB) ganz oben – mit FT2 und deutscher
  Oberfläche. „Installieren“ holt immer die **neueste Version direkt bei DG2YCB**: unter Debian,
  Ubuntu und auf dem Live-Stick das `.deb`, unter Fedora/openSUSE das `.rpm` (Prüfsumme wird
  geprüft), unter Arch/Garuda aus dem AUR (`paru`/`yay`, in einem Konsolenfenster).
* Das **Original-WSJT-X** ist nicht mehr dabei. Ein schon installiertes bleibt auf dem Rechner;
  war es als FT8-Programm gewählt, nimmt GoGoHam jetzt WS (oder JTDX). Geloggte QSOs nimmt GoGoHam
  weiterhin von jedem Programm an, das sie per UDP meldet.
* Zusatzprogramme jetzt: WS, JTDX, fldigi.

## Neu in 0.10.12

* **Alle Fenster passen auf den Bildschirm** – auch auf Laptops (Full HD mit Skalierung, 1366×768)
  und mit Taskleiste. Zu viel Inhalt lässt sich scrollen, die Knöpfe unten bleiben immer sichtbar.
  Im Fenster „Neues Contest-Log“ rutschen keine Zeilen mehr in die Contest-Liste; der Haken
  „Stationslog für mehrere Plätze“ steht fest über den Knöpfen.
* **Willkommensfenster beim ersten Start** statt der Fragen nach Station, Länderdatei, SCP und
  Flaggen: was man der Reihe nach einrichtet – Internet verbinden, Operator, Funkgerät, Daten &
  Updates („Alles herunterladen“), danach nach Bedarf. „Einstellungen öffnen“ springt zu Operator.
* **WSJT-X Improved in der Systemsprache:** GoGoHam stellt die Sprache beim Einrichten mit ein,
  wenn dort noch keine gewählt ist. Die anderen Zusatzprogramme nehmen die Systemsprache selbst,
  soweit sie übersetzt sind.
* Einstellungen → Operator: Feld **Lizenzklasse** breit genug für den Hinweis.

## Neu in 0.10.11.1

* **Neue Kontaktadresse:** do2ggh.de@gmail.com – im Knopf „Kontakt zu DO2GGH“, im
  Über-Fenster, im Handbuch und in den Paketen.

## Neu in 0.10.11

* **Einstellungen → Operator:** deine eigenen Angaben an einer Stelle – Rufzeichen, Name, Locator,
  DOK, Jahr der ersten Lizenz, Lizenzklasse, Geburtsdatum, CQ-/ITU-Zone, Club, Adresse, E-Mail.
  Neue Logs füllt GoGoHam daraus vor (das Alter rechnet es aus dem Geburtsdatum aus); die
  Zusatzprogramme bekommen Rufzeichen und Locator von hier. Ein /P-Log ändert die Angaben nicht.
* **Einstellungen neu geordnet** – wie beim Einrichten: Operator, Funkgerät, Rotor,
  Funktionstasten, Daten & Updates, Ton & Ansagen, Online-Dienste, Zusatzprogramme, Darstellung
  (auf dem Live-Stick zuletzt USB-Stick).
* Zusatzprogramme: Der Knopf heißt jetzt **„Einstellungen übertragen“** (vorher „Verbindung
  einrichten“) – er überträgt ja auch Rufzeichen, Locator und Soundkarte.
* Live-Stick: Wechselt GoGoHam die Zeitzone, zeigt es die Ortszeit sofort richtig an.

## Neu in 0.10.10

* **„Deine Station“ beim ersten Start:** GoGoHam fragt gleich nach Rufzeichen und Locator. Neue Logs
  sind damit schon ausgefüllt, und die Zusatzprogramme werden auch ohne offenes Log richtig
  eingerichtet.
* **Live-Stick – Uhrzeit ohne Internet:** Die Zeitzone stellt GoGoHam jetzt aus deinem Locator
  (nur wenn die Uhrzeit sonst anders wäre, z. B. in England oder den USA). Statt einer Warnung
  gibt es nur noch einen ruhigen Hinweis „Uhrzeit vom Rechner übernommen“; sobald die Uhr mit dem
  Internet abgeglichen ist, verschwindet er von selbst. Die eingebaute Uhr des Rechners wird nur
  gelesen, nie verändert.

## Neu in 0.10.9

* **Zusatzprogramme fertig eingerichtet:** Beim Einrichten von WSJT-X, WSJT-X Improved, JTDX und
  fldigi trägt GoGoHam jetzt auch **dein Rufzeichen, deinen Locator** und die **Soundkarte des
  Funkgeräts** (Empfang und Senden) ein – du musst dort nichts mehr selbst einstellen.
* **Soundkarte des Funkgeräts wird erkannt:** Funkgeräte mit eingebauter USB-Soundkarte (z. B.
  IC-7300, FT-991A) findet GoGoHam über den USB-Anschluss selbst – auch bei mehreren Funkgeräten
  die jeweils richtige. Im Funkgeräte-Profil (Erweiterte Einstellungen) lässt sie sich unter
  „Soundkarte des Funkgeräts“ auch selbst wählen, z. B. ein Ton-Interface.
* **Funkgeräte ohne eigene Soundkarte** (z. B. FT-891): GoGoHam trägt dann keine falsche Soundkarte
  ein, sondern sagt, dass ein Ton-Interface an der DATA-Buchse nötig ist.

## Neu in 0.10.8.1

* **Live-Stick – Ordner „Export“:** Beim Speichern von Cabrillo, ADIF oder EDI schlägt GoGoHam auf
  dem Stick den Ordner „Export“ im Austausch-Ordner vor. So liegen dort nur deine Exporte, getrennt
  von der automatischen Sicherung im Ordner „GoGoHam-Sicherung“.
* Im Ordner „GoGoHam-Sicherung“ erklärt eine kurze Datei „LIESMICH.txt“, wie man ein Log
  wiederherstellt.
* **DOK-Liste wird mitgeliefert:** DARC e.V. und VFDB e.V. haben die Weitergabe der Liste der
  Ortsverbände erlaubt – danke!

## Neu in 0.10.8

* **GoGoHam vom Live-Stick:** Läuft GoGoHam von einem USB-Stick, gibt es in den Einstellungen den
  neuen Bereich **USB-Stick** (direkt nach „Daten & Updates“; auf einem normal installierten PC
  fehlt er):
  * **Platz auf dem Stick** für Datenteil und Austausch-Ordner – wird es knapp, warnt die
    Hinweisleiste.
  * **Austausch-Ordner öffnen** – den Teil des Sticks, den auch Windows lesen kann.
  * **Logs auch in den Austausch-Ordner sichern** (von sich aus an): bei jeder Sicherung eine
    Kopie als ADIF und als GoGoHam-Datei im Ordner „GoGoHam-Sicherung“.
  * **Uhrzeit stellen …** von Hand in UTC – nur die Uhr des laufenden Systems, nie die
    eingebaute Uhr des fremden Rechners.
  * **Rechner herunterfahren …** und **Stick auf Werkseinstellungen zurücksetzen …** (mit
    Sicherheitsfrage; der Austausch-Ordner bleibt erhalten).
* **Uhrzeit-Warnung auf dem Stick:** Ohne Internet kann die Uhr fremder Rechner eine oder zwei
  Stunden falsch gehen (Windows stellt die eingebaute Uhr auf Ortszeit). GoGoHam warnt dann
  „Uhrzeit konnte nicht abgeglichen werden“ und bietet das Stellen an.
* **Hinweis beim ersten Start vom Stick:** den Stick erst abziehen, wenn der Rechner aus ist.
* Handbuch: neues Kapitel 31 „Live-Stick“.
* **Natürliche Stimmen (Piper) laden wieder:** Der Anbieter hat am 9. November alle Stimmen neu
  trainiert, danach passte die Prüfsumme nicht mehr („Prüfsumme stimmt nicht“). GoGoHam lädt die
  Stimmen jetzt aus einem festen Stand.
* **speech-dispatcher unter Debian/Ubuntu:** Beim Installieren kommt jetzt auch das
  Verbindungsstück für Qt mit (`qt6-speech-speechd-plugin`) – ohne das fand GoGoHam
  speech-dispatcher nicht, obwohl es installiert war.
* **Startfragen nacheinander:** Willkommen, Länderdatei, MASTER.SCP, Flaggen usw. erscheinen beim
  ersten Start jetzt eine nach der anderen statt übereinander – vorher konnte das oberste Fenster
  (unter KDE/Wayland) keine Klicks annehmen.

## Neu in 0.10.7.2

* **Log-Ordner bleibt aufgeräumt:** Die Hilfsdateien der Datenbank (`.ggh-wal`, `.ggh-shm`) gibt es
  nur noch beim gerade offenen Log. Beim Schließen verschwinden sie, beim Lesen anderer Logs
  (Call-History, Prüfung) entstehen keine mehr, und alle 5 Minuten räumt GoGoHam selbst auf:
  Reste gelöschter Logs werden entfernt, liegen gebliebene sauber abgeschlossen – ohne dass ein
  QSO verloren geht.

## Neu in 0.10.7.1

* **Log & Contest → Log-Ordner öffnen …** öffnet den Ordner mit den Log-Dateien im Dateimanager
  (z. B. Dolphin) – zum Aufräumen, Kopieren oder Löschen alter Logs.

## Neu in 0.10.7

* **Vier RTTY-Contests:** CQ WW DX RTTY (Zone, bei W/VE dazu State/Provinz), CQ WPX RTTY, ARRL RTTY
  Roundup und WAE DX RTTY. Beim Öffnen eines RTTY-Logs startet fldigi von selbst – fertig
  eingerichtet.
* **WAE RTTY:** jeder arbeitet jeden; QTCs gibt und empfängt jede Station (nur zwischen
  Kontinenten, höchstens 10 je Stationspaar). Strg+Q fragt „Empfangen oder Geben?“, gegebene
  QTCs gehen über fldigi raus.
* **Sendepegel einmessen:** Einstellungen → Zusatzprogramme → RTTY (fldigi). fldigi sendet nach
  Zustimmung kurz einen Dauerton, GoGoHam liest die ALC und stellt den lautesten sauberen Pegel ein.
* Regel-Dateien: Format 13 (Zone + State/Provinz, „nie am 1. Januar“, QTCs in beide Richtungen).

## Neu in 0.10.6.1

* Zusatzprogramme: die eigene Auswahl „Funkgerät für die Verbindung“ ist entfallen – verbunden wird
  immer das aktive Funkgerät-Profil (Station → Funkgerät-Profil).

## Neu in 0.10.6

* **Das passende Programm startet von selbst:** Öffnest du ein RTTY-Contest-Log, startet GoGoHam
  fldigi; bei FT8/FT4-Contests das bevorzugte FT8-Programm (WSJT-X, WSJT-X Improved oder JTDX) –
  jeweils fertig eingerichtet. Beim Wechsel des Logs oder Beenden von GoGoHam wird es wieder
  geschlossen (nur, wenn GoGoHam es gestartet hat). Von Hand: Station → Digitalprogramm starten.
* **RTTY: gefunkt wird in fldigi, geloggt in GoGoHam** (wie bei WSJT-X). Jedes in fldigi
  geloggte QSO landet sofort in GoGoHam; das Rufzeichen aus fldigi zeigt GoGoHam gleich mit Dupe,
  neuem Multi und Infobox. GoGoHam legt in fldigi die Contest-Makros an und gibt die laufende
  Nummer vor. Das RTTY-Fenster und die RTTY-Texte auf F1–F8 aus 0.10.5 sind dafür entfallen.
* **Bevorzugtes FT8-Programm** unter Einstellungen → Zusatzprogramme.

## Neu in 0.10.5

* **RTTY über fldigi:** Fenster → RTTY startet fldigi und richtet es selbst ein (Funkgerät des
  Profils über rigctld, PTT über CAT, Soundkarte des Funkgeräts, Rufzeichen, Locator, RTTY 45,45
  Baud / 170 Hz); Fenster schließen beendet fldigi. Empfangstext mit Rufzeichen per Klick, neue
  Multis grün, Dupes grau. F1–F8, „Enter sendet“ und Auto-CQ mit eigenen RTTY-Texten, Esc bricht
  das Senden ab.
* **AFSK oder FSK:** unter Einstellungen → Zusatzprogramme → RTTY (fldigi).
* „Verbindung einrichten“ jetzt auch für fldigi.

## Neu in 0.10.4

* **Aufgeräumte Menüleiste:** Datei · Log & Contest · Station · Fenster · Hilfe. Alles rund ums Log
  und den Contest (Kalender, neues Log, öffnen, prüfen, QTC, Export) steht unter „Log & Contest“,
  Funkgerät-Profil, Operator, Uhrzeit und Stationslog unter „Station“, alle Zusatzfenster unter
  „Fenster“ (vorher „Ansicht“). „Info“ ist in „Hilfe“ aufgegangen. Alle Tastenkürzel bleiben gleich.
* **Einstellungen mit Liste links:** acht Bereiche statt elf Reiter – „Ton & Ansagen“
  (Sprachaufnahmen und Ansagen) und „Online-Dienste“ (DX-Cluster, Name/QTH, Live-Score) fassen
  Zusammengehöriges zusammen.
* **Neuer Bereich „Zusatzprogramme“:** WSJT-X, WSJT-X Improved, JTDX und fldigi per Klick
  installieren (über die Paketverwaltung, sonst Downloadseite). „Verbindung einrichten“ trägt im
  FT8-Programm nur die Verbindung zu GoGoHam ein (Funkgerät, PTT, geloggte QSOs) – mit
  Sicherungskopie; vorhandene Einstellungen werden erst nach Rückfrage geändert.
* **Fünf Funkgerät-Profile** statt drei.

## Neu in 0.10.3.2

* **Stationslog mit Python 3.13:** Auf Systemen mit Python 3.13 (z. B. Debian 13, openSUSE Leap 16,
  Beta-AppImage) fanden die Plätze den Hauptplatz im Netzwerk nicht. Behoben.

## Neu in 0.10.3.1

* **Reparatur beschädigter Logs korrigiert:** Auf Rechnern ohne das Programm „sqlite3“ rettete die
  Reparatur seit 0.10 keine QSOs mehr. Jetzt wieder alles, was lesbar ist.

## Neu in 0.10.3

* **Fenster „Station“** (Ansicht → Station, Klick auf die Stationslog-Anzeige unten rechts oder
  Strg+T): alle Plätze mit Operator, Sender, Band, Frequenz, Betriebsart, QSOs und Rate (10/60 min).
  Getrennte Plätze bleiben grau stehen.
* **Warnung bei gleichem Band:** Plätze auf demselben Band werden rot; ist ein anderer Platz auf dem
  eigenen Band, warnt die Hinweiszeile einmal. Bandwechsel sind sofort bei allen zu sehen.
* **Nachrichten zwischen den Plätzen** – an alle oder an einen Platz, mit „zugestellt“/„nicht
  zugestellt“; bleiben im Log dieses Rechners, nie im Export.
* **Zwei neue Ansagen** (von sich aus aus): „Band belegt“ und Nachrichten vorlesen.
* Hinweis: Alle Plätze brauchen diese Version – mit 0.10.2 verbinden sie sich nicht mehr.

## Neu in 0.10.2

* **Multi-OP-Kategorien:** Multi-Single, Multi-Two und Multi-Multi in Klartext (Log-Einstellungen →
  Sender); das Häkchen „Stationslog“ trägt MULTI-OP gleich ein. Regeln für CQ WW, CQ WPX, ARRL DX und
  IARU HF (Regel-Dateien Format 12).
* **Sender je Platz** (Run/Multi bzw. Sender 0/1) – im Cabrillo-Log in der letzten Spalte, wo der
  Contest es verlangt.
* **Warnungen beim Tippen** vor Verstößen gegen die 10-Minuten-Regel und die Bandwechsel je Stunde;
  CQ WW Multi-Single: das Multi-Signal nur für neue Multis. Die Log-Prüfung zeigt alle Verstöße.
* **Nummern je Band**, wo der Contest es verlangt (CQ WPX Multi-Two/Multi-Multi).
* **Operator wechseln** mit Auswahlliste der bisherigen Operatoren und Rückfrage bei neuem
  Rufzeichen; Liste der Operatoren in der Log-Prüfung.
* **Start ohne offenes Log:** GoGoHam fragt beim Start, ob es mit dem zuletzt benutzten Log weitergeht
  (Weitermachen = Enter), statt es von selbst zu öffnen. Ein Platz mit einem alten Stationslog ohne
  Hauptplatz bekommt ein neues Stationslog im Netz angeboten.
* **Schneller bei großen Stationen:** QSOs anderer Plätze werden einzeln übernommen statt das ganze
  Log neu zu rechnen; getestet mit 12 Plätzen und 5000 QSOs. Hinweis: Alle Plätze brauchen diese
  Version – mit 0.10.1 verbinden sie sich nicht mehr.

## Neu in 0.10.1

* **Stationslog ohne Router:** Die Plätze finden sich jetzt auch über einen Netzwerk-Switch oder ein
  Kabel direkt von Rechner zu Rechner – ganz ohne Router und ohne Einrichtung (IPv6-Link-Local).
* GoGoHam fragt einmal, ob der Kabelanschluss auch ohne Router arbeiten soll – sonst schaltet die
  Netzwerkverwaltung ihn nach ein paar Minuten ab. Mit Router ändert sich nichts. Fehlt am Kabel
  die Adresse, bietet GoGoHam das Einrichten von selbst mit einem Klick an.
* **Netzwerk-Check** im Fenster Log → Stationslog …: in einfachen Worten, wie der Rechner verbunden
  ist.
* **Uhrzeit-Abgleich:** Die Plätze vergleichen ihre Uhr mit dem Hauptplatz und warnen ab 2 Sekunden
  Abweichung; Knopf „Uhr nach dem Hauptplatz stellen“ – auch ohne Internet.
* **USB-Berechtigung:** Fehlt die Berechtigung für die Schnittstelle, richtet der Knopf
  „Berechtigung einrichten …“ sie mit einem Klick ein; der Befehl steht dort zum Kopieren – mit
  deinem Benutzernamen, ohne Sonderzeichen.

## Neu in 0.10

* **Stationslog für mehrere Plätze (Multi-OP im Netzwerk):** Mehrere Rechner mit GoGoHam am selben
  Standort schreiben ein gemeinsames Log. Am Hauptplatz beim neuen Log das Häkchen „Stationslog für
  mehrere Plätze“ setzen und ein Kennwort wählen – die anderen Rechner finden das Stationslog von
  selbst und fragen „Mitmachen?“.
* Jedes QSO geht sofort an alle Plätze; Dupes, Multis und Punkte gelten für die ganze Station.
  Laufende Nummern vergibt der Hauptplatz. Ohne Verbindung wird weitergeloggt und danach abgeglichen.
* Operator je QSO (Log → Operator wechseln …), alle Operatoren im Cabrillo-Log.
* Neues Fenster Log → Stationslog … mit allen Plätzen, Firewall-Freigabe per Knopf und Notweg
  „Mit Adresse verbinden“. Verbindung verschlüsselt, nur mit Stationskennwort.

## Neu in 0.9.4

* **QTCs geben im WAE DX Contest** (eigene Station außerhalb Europas): Strg+Q öffnet das Fenster
  „QTC geben“. GoGoHam sucht die QSOs selbst aus (jedes nur einmal, nie an die Station selbst,
  höchstens 10 je Station) und zählt die eigenen Serien fortlaufend („QTC 4/10“).
* In **CW** sendet Enter Zeile für Zeile über WinKey oder Funkgerät, F2 wiederholt – gesendet wird
  nur auf Tastendruck. In **SSB** steht die Zeile groß im Fenster; auf Wunsch wird sie über die
  Soundkarte angesagt (neue Ansage „QTC geben in SSB“, von sich aus aus).
* Nur bestätigte QTCs zählen. Gegebene QTCs stehen in der **QTC-Liste** (vorher „Empfangene QTCs“)
  und im Cabrillo-Log.

## Neu in 0.9.3

* **Hinweis auf neue Versionen:** Einmal am Tag beim Start fragt GoGoHam bei GitHub nach, ob es
  eine neuere Version gibt. Wenn ja, steht unten in der Hinweiszeile, dass sie erschienen ist und
  wie du sie bekommst (als Paket: mit dem nächsten Systemupdate). Je Version nur einmal und nicht,
  während der Contest des geöffneten Logs läuft.
* Neu im Menü **Hilfe → Nach neuer Version suchen …**; abschalten unter Einstellungen →
  Daten & Updates.

## Neu in 0.9.2

Vorbereitung für die Pakete der Linux-Distributionen – am Programm selbst ändert sich nichts.

* **Python-Paket:** GoGoHam lässt sich jetzt als normales Python-Paket bauen (`pyproject.toml`), mit
  Startbefehl `gogoham`, Startmenü-Eintrag und Symbolen. Die Versionsnummer steht weiterhin nur an
  einer Stelle. Daraus entstehen mit 0.9.3 die Pakete für openSUSE, Fedora, Debian/Ubuntu und Arch.
* **Automatische Tests auf GitHub:** Bei jedem Hochladen laufen alle Tests mit Python 3.12, 3.13 und
  3.14, danach wird das Paket gebaut und geprüft.
* Vier Tests, die auf langsamen Rechnern ab und zu zufällig fehlschlugen, warten jetzt, bis das
  Erwartete wirklich eingetreten ist.
* Die DOK-Liste kommt erst mit Erlaubnis von DARC und VFDB ins Paket; bis dahin lässt sie sich wie
  bisher herunterladen (Einstellungen → Daten & Updates).


* **Die Call-History schreibt sich selbst:** Jedes geloggte QSO lernt die festen Angaben der
  Gegenstation (CQ- und ITU-Zone, Locator, DOK, State, Provinz, Bezirk, Lizenzjahr,
  Mitgliedsnummer, IOTA) und speichert sie dauerhaft in einer eigenen Datei, auch wenn das Log
  später gelöscht wird. Laufende Nummern und Rapporte werden nie gemerkt, Übungs-QSOs auch nicht.
* Es gilt immer der **neueste** Eintrag, damit ein einmaliger Tippfehler nicht hängen bleibt.
  Gelöschte oder geänderte QSOs werden auch in der Call-History vergessen bzw. geändert.
* **Vorschläge für alle Contests:** Bisher schlug GoGoHam nur Zone und DOK vor, jetzt jeden
  bekannten festen Austausch. Bei „Nummer + DOK/Locator/Bezirk“ steht der bekannte Wert als
  Hinweis in der Infobox.
* **Neues Fenster Log → Call-History …:** nachsehen, Werte ändern oder vergessen, **alte Logs
  einlesen** (Cabrillo, auch von anderen Programmen, oder GoGoHam-Logs) und N1MM-Dateien importieren.
  Aus dem Kopf eines Logs (Name, Adresse, E-Mail) wird nichts übernommen.
* **Grundstock:** GoGoHam bringt gut 400 Stationen mit CQ-Zone mit, damit die Call-History auch
  bei einer neuen Installation nicht leer ist. Im Fenster „Call-History“ lässt er sich entfernen
  (und wieder einlesen), wenn man nur eigene Logs oder eine N1MM-Datei nutzen möchte.
* Logs, die schon vorher im Ordner `~/GoGoHam` lagen, liest GoGoHam einmal beim ersten Start ein.

## Neu in 0.9

Aufräumen für die Veröffentlichung – am Programm selbst ändert sich nichts.

* **Lizenz:** GPL-3.0, **nur Version 3**, der Originaltext liegt als `LICENSE` bei. Dazu zwei
  Zusatzbedingungen (`ADDITIONAL-TERMS.md`): Der Urhebervermerk muss erhalten bleiben, und veränderte
  Fassungen müssen als verändert gekennzeichnet sein. Steht auch in „Über GoGoHam“ und oben in
  beiden Handbüchern.
* **Fremde Teile** mit Herkunft und Bedingungen: `THIRD-PARTY.md` (Kartendaten, DOK-Liste,
  Downloads, benutzte Programme).
* **Neue GitHub-Startseite** auf Deutsch (`README.md`) und Englisch (`README.en.md`) mit
  Bildschirmfoto, Funktionen, allen Contests und Installation. Die Befehle für die Paketquellen der
  Distributionen folgen mit 0.9.2.
* **Änderungen** jeder Version stehen jetzt in `CHANGELOG.md` (bisher im README).
* **Mitmachen** (`CONTRIBUTING.md`): Fehlerberichte und Ideen sind willkommen, fremder Programmcode
  nicht. Auf GitHub gibt es Formulare für „Fehler melden“ und „Idee oder Wunsch“; Pull Requests von
  anderen werden automatisch freundlich geschlossen.
* Urhebervermerk jetzt „© 2026 Franz, DO2GGH“; nichts Privates mehr im Projekt.

## Neu in 0.8.32.1

* **Behoben:** Im Fenster „Neues Contest-Log“ rutschten beim Verkleinern die Anzeige der
  Contest-Anzahl und der Regelstand übereinander und wurden abgeschnitten. Das Fenster hat jetzt
  eine Mindestbreite, und für den Regelstand sind zwei Zeilen fest eingeplant.

## Neu in 0.8.32

* **Drei neue Contests:** **YO DX HF Contest** (Rumänien, August, SSB und CW) und
  **S.M. El Rey de España / King of Spain** CW (Mai) und SSB (Juni). Regeln von 2026 direkt bei
  den Veranstaltern (yodx.ro, concursos.ure.es). Alle auch im Übungsmodus und im Contest-Kalender.

## Neu in 0.8.31.3

* **Neues Contest-Log:** Unter der Contest-Liste steht, wie viele Contests GoGoHam kennt
  („47 Contests in GoGoHam“), beim Suchen „6 von 47 Contests“.

## Neu in 0.8.31.2

* **Contest-Suche bei „Neues Contest-Log“ mit Liste:** Unter dem Suchfeld steht immer eine Liste
  aller Contests, die mit jedem getippten Buchstaben kürzer wird (z. B. „iar“ → nur die
  IARU-Contests) – kein Aufklappen mehr. Pfeil hoch/runter wählt, Enter übernimmt und springt
  zum eigenen Rufzeichen, Esc leert das Suchfeld.

## Neu in 0.8.31.1

* **Funkgerät-Profil:** GoGoHam startet jetzt mit dem **zuletzt benutzten** Profil – samt allen
  seinen Einstellungen. Das Start-Profil gibt es nicht mehr, die drei Plätze sind gleichwertig.
  Behoben: Nach dem Neustart war das zuletzt benutzte Profil im Menü markiert, verbunden wurde aber
  halb mit Profil 1 („CAT nicht verbunden“). Ist das Gerät beim Start nicht angeschlossen, wechselt
  GoGoHam nicht von selbst auf ein anderes.
* **Suche bei „Neues Contest-Log“:** Suchfeld über der Contest-Auswahl wie im Contest-Kalender
  (ab 2 Buchstaben, Enter springt in die Auswahl, Esc leert).
* **Über GoGoHam** und **Handbuch** auf den aktuellen Stand gebracht (u. a. Regel-Formate 9–11,
  Übungs-Einstellungen, Mitgliedsnummer).

## Neu in 0.8.31

* **Fünf neue Contests (Contest-Paket für die nächsten Monate):** **LZ DX Contest** (21.–22. 11.,
  SSB und CW), **9A DX Contest / Croatian DX** (19.–20. 12., SSB und CW, mit Nachtbonus),
  **AGCW Happy New Year Contest** (1. 1., CW) und **REF Contest** CW (30.–31. 1.) und SSB
  (27.–28. 2.). Alle auch im Übungsmodus und im Contest-Kalender.
* **Mitgliedsnummer** im Fenster *Log* (für den AGCW-Contest; leer = kein Mitglied).
* Bei Departements darf man „1“ statt „01“ tippen.
* Regel-Dateien jetzt Format 11 (neu: ITU-Zone je Herkunft, Mitgliedsnummer, Zeitbonus). Ältere
  GoGoHam-Versionen überspringen die neuen Dateien.

## Neu in 0.8.30

* **Gemischte Übung (CW und SSB):** *Datei → Übungsmodus → Übung: Gemischt.* Du rufst auf deiner
  eigenen Run-Frequenz CQ und drehst zwischendurch zum Suchen weg, wie im echten Contest. Die
  Run-Frequenz ist dort, wo du CQ rufst (CW ± 150 Hz, SSB ± 400 Hz), und wandert mit. Wer dich
  anrufen wollte, wartet nicht lange, wenn du weg bist. „Enter sendet“ schaltet beim Weg- und
  Zurückdrehen von selbst zwischen Run und S&P um, Strg+Tab geht trotzdem. Auf Wunsch übernimmt
  eine andere Station deine Frequenz, wenn du länger als 1–2 Minuten weg bist (Häkchen, Standard
  aus). Die Auswertung zeigt Run und S&P getrennt.
* **SSB-Übung deutlicher:** Das Rauschen ist leiser und die Stimmen der Gegenstationen sind etwas
  lauter. Vorher waren sie schon bei leichtem Rauschen schwer zu verstehen.

## Neu in 0.8.29.1

* **Frequenz flüssig:** GoGoHam misst beim Verbinden, wie schnell das Funkgerät antwortet, und
  fragt so oft wie möglich – höchstens 50-mal pro Sekunde (IC-7300: 4 ms je Abfrage → 50-mal),
  bei langsamen Geräten seltener; die Betriebsart einmal pro Sekunde. Den Zwischenspeicher von
  rigctld stellt GoGoHam dabei auf 10 ms (Hamlib meldete sonst bis zu 1 s lang die alte Frequenz).
  Eigener Wert: *Funkgerät → Erweiterte Einstellungen → Abfrage-Intervall*.
* **S&P-Übung:** viel mehr Stationen (CW 15–100, SSB 10–55 je nach „Betrieb“), kürzere Pausen; in
  SSB werden die Stimmen zuerst für Stationen nahe der VFO-Frequenz berechnet, und keine Station
  fällt mehr aus, nur weil ihre Stimme noch nicht fertig ist.
* **Contest-Kalender:** Suchfeld (ab 2 Buchstaben, Esc leert); **Rechtsklick → Als ICS-Datei
  speichern** für einen einzelnen Contest oder alle markierten (Strg+Klick).
* **Behoben:** SSB-S&P-Übung mit „Enter sendet“ schickt deinen Austausch wieder mit (vorher nur
  „TU“). In der Übung geht nie Ton an die Soundkarte des Funkgeräts – auch nicht mit eigenen
  Aufnahmen und „Enter sendet“ auf S&P (mit VOX hätte das Gerät sonst senden können). „Enter
  sendet“ wird auch beim Schließen während der S&P-Übung zurückgestellt.

## Neu in 0.8.29

* **S&P-Übung (CW und SSB):** *Datei → Übungsmodus → Übung: S&P.* Auf einem Bandstück rufen
  erfundene Stationen CQ, jede auf ihrer eigenen Frequenz. Du **drehst am VFO-Knopf deines
  Funkgeräts**, suchst sie und rufst sie an. GoGoHam liest dabei nur Frequenz und Betriebsart –
  **Senden ist gesperrt** (kein PTT, kein CW, keine Sprachspeicher, kein WinKey). Das Band kommt
  vom Funkgerät. Der Ton (über die PC-Soundkarte) folgt dem VFO: daneben höher/tiefer, außerhalb
  des Filters still; in SSB klingt eine Station daneben verzerrt. Stationen verstehen dein
  Rufzeichen manchmal falsch oder halb, andere rufen dazwischen, Stationen kommen und gehen.
  Auf Wunsch **nachgebildete Spots in der Bandmap**. Die Auswertung zeigt zusätzlich, wer dich
  falsch geloggt hat, und unnötige Doppel-QSOs.

## Neu in 0.8.28.4

* **☕ Spendier DO2GGH einen Kaffee:** neuer Eintrag im Menü *Info*. Ein Klick öffnet im Browser
  die PayPal-Seite <https://paypal.me/GoGoHam> für eine kleine, **freiwillige** Spende. GoGoHam
  bleibt ohne Einschränkung kostenlos; das Programm überträgt dabei nichts.

## Neu in 0.8.28.3

* **Alles herunterladen:** *Einstellungen → Daten & Updates* hat ganz oben den Knopf **„Alles
  herunterladen / aktualisieren“** – Contest-Regeln, Länderdatei, MASTER.SCP, DOK-Liste, Flaggen
  und beide Kartenbilder nacheinander im Hintergrund, mit Häkchen auch die natürlichen Stimmen
  (Standard aus), zum Schluss speech-dispatcher (mit Passwortabfrage). Fortschritt unter dem Knopf,
  am Ende eine Zusammenfassung. Die Einzelknöpfe bleiben.

## Neu in 0.8.28.2

* **„Über GoGoHam“ aufgefrischt:** „Schneller Contest-Logger für Linux – Rufzeichen, Leertaste,
  Austausch, Enter.“ Die Liste der Funktionen ist auf dem Stand von heute (u. a. Übungsmodus,
  Bandöffnungs-Vorschau, Ansagen, Rotor, WinKey/DXP, QTC, EDI). Bei den Datenquellen sind
  dazugekommen: DOK-Listen (DARC, VFDB), DX-Cluster DB0SUE, NTP Pool (Uhrzeit-Prüfung) und die
  Piper-Stimmen mit Namensnennung (u. a. LibriTTS-R, CC BY 4.0); bei den Bausteinen NumPy sowie
  auf Wunsch Piper, espeak-ng und speech-dispatcher.

## Neu in 0.8.28.1

* **Übungsmodus jetzt auch in SSB:** Die Gegenstationen sprechen Englisch mit Buchstabieralphabet,
  jede mit eigener Stimme (Piper, Stimme „libritts_r“ mit 904 Sprechern, einmalig ca. 79 MB;
  ohne Download espeak-ng), mit Funkklang (300–2700 Hz), Rauschen und Schwund. Eigene
  Sprachaufnahmen spielt GoGoHam bei F1–F8/Enter ab – nur über die Soundkarte des PCs; sonst
  sprichst du selbst und drückst die Taste („Sprich jetzt: …“). Stimme: LibriTTS-R, CC BY 4.0.
* **Fehler behoben:** Ging die Uhr nach „Synchronisieren“ immer noch falsch, brach die Meldung
  darüber mit einem Programmfehler ab (seit 0.8.18.3).

## Neu in 0.8.28

* **Übungsmodus (CW):** *Datei → Übungsmodus …* – Contest üben, **ohne zu senden**. Erfundene
  Stationen (echte Rufzeichen aus der Super-Check-Partial-Liste) rufen dich über die Soundkarte
  an, mit eigener Tonhöhe, eigenem Tempo und eigener Lautstärke, mit Rauschen, Schwund (QSB),
  Störern und Doppelanrufen nach Wahl. Du arbeitest sie wie im echten Contest mit F1–F8 oder
  Enter (ESM): falsches Rufzeichen → die Station korrigiert, „ABC?“ → nur passende antworten,
  AGN/?/NR? → Wiederholung. Welche Kontinente rufen, folgt der Bandöffnungs-Vorschau; es rufen nur
  Stationen, die dich nach den Regeln arbeiten dürfen. Am Ende: QSOs, Rate, **Fehlerliste**
  („DL1ABD geloggt – richtig war DL1ABC“) und Vergleich mit früheren Übungen. Funkgerät, WSJT-X,
  Cluster und Live-Score sind währenddessen getrennt, das Übungslog liegt in `~/GoGoHam/Übung/`.
  23 CW-Contests auf Kurzwelle; SSB folgt mit 0.8.28.1.

## Neu in 0.8.27.2

* **Neue Kontaktadresse:** gogoham@bluemailx.com – im Knopf „Kontakt zu DO2GGH“, im
  Fehlerbericht, unter „Über GoGoHam“ und im Handbuch.

## Neu in 0.8.27.1

* **Bandöffnungs-Vorschau genauer:** Nach Sonnenuntergang baut sich die Schicht jetzt langsam ab
  (etwa 3 Stunden) – abends bleiben die hohen Bänder wie in Wirklichkeit noch offen. Je Kontinent
  werden mehrere Gegenden gerechnet (z. B. Ostküste, Mittlerer Westen, Westküste, Karibik), es
  zählt die beste; der Tooltip zeigt „Am besten: …“. „Zu“ erst, wenn das Band deutlich über der
  geschätzten Grenze liegt. **✓ nur noch von Meldern bis 1000 km um dich**, Verbindungen unter
  300 km (Bodenwelle) zählen nicht.

## Neu in 0.8.27

* **Bandöffnungs-Vorschau:** *Ansicht → Bandöffnung (Vorschau)* schätzt, welches Kurzwellenband
  von deinem Standort aus wohin offen ist – umschaltbar zwischen **Jetzt** (Bänder × Kontinente)
  und den **nächsten 12 Stunden** für einen gewählten Kontinent. Gerechnet wird offline mit
  Faustregeln aus Sonnenfluss (SFI), K-Wert und Tag/Nacht auf dem Weg – ausdrücklich als
  **Schätzung, keine Garantie** gekennzeichnet; nur Short Path, nur 160–10 m (für UKW gibt es
  keine Vorschau). **✓ = tatsächlich gehört:** Laufen DX-Cluster oder Bakenanzeige, zeigt das
  Fenster, wohin in den letzten 30 Minuten wirklich etwas gehört wurde (Cluster: nur Melder auf
  dem eigenen Kontinent). Zusatzfenster wie alle: offen = an, beim Start nur per Häkchen.

## Neu in 0.8.26.4

* **Ansagen:** Die Auswahl „Rufzeichen vorlesen als“ zeigt als Beispiel DO2GGH.

## Neu in 0.8.26.3

* **Ansagen:** keine Bandansage mehr beim Programmstart, nach dem Öffnen eines Logs und nach
  dem Verbinden mit dem Funkgerät. Die Probe liest „DO2GGH“ vor.

## Neu in 0.8.26.2

* **Natürliche Stimme für die Ansagen (Piper):** Ein Knopf lädt Piper und je eine deutsche
  („Thorsten“, CC0) und englische Stimme („Cori“, gemeinfrei), ca. 150 MB, ohne Passwort, nur
  in GoGoHams eigenen Ordner, mit Prüfsummen. „Automatisch“ nimmt danach Piper.

## Neu in 0.8.26.1

* **speech-dispatcher per Klick installieren:** Knopf unter *Einstellungen → Daten & Updates*
  und im Reiter *Ansagen*. GoGoHam installiert speech-dispatcher und espeak-ng über die
  Paketverwaltung (Arch, Debian/Ubuntu, Fedora, openSUSE; Linux fragt nach dem Passwort) und
  nimmt es für die Ansagen sofort in Gebrauch.

## Neu in 0.8.26

* **Ansagen per Sprachausgabe** – vor allem für sehbehinderte Funkamateure
  (*Einstellungen → Ansagen*, Standard aus). GoGoHam sagt von selbst Dupe, neuen Multi,
  „zählt nicht“, Band- und Modewechsel, geloggte QSOs sowie Warnungen an – jede Ansage
  einzeln abschaltbar. Auf Tastendruck: Alt+1 Frequenz, Alt+2 Rufzeichen mit Wertung,
  Alt+3 letztes QSO, Alt+4 Punktestand, Alt+5 Uhrzeit/Contest-Zeit, Alt+6 wiederholen.
  Sprachausgabe über speech-dispatcher oder espeak-ng, nie über das Funkgerät.

## Neu in 0.8.25

* **DARC-UKW-Paket:** DARC VHF-/UHF-/SHF-Wettbewerb (März, Mai, Juli), UKW-Frühlingswettbewerb,
  Mikrowellen-Wettbewerb (Juni), Marconi Memorial (2 m, CW), UKW-Winter- und Sommer-Fieldday –
  1 Punkt je km, EDI-Log je Band, alle im Contest-Kalender.
* **Mikrowellenbänder bis über 300 GHz** (24, 47, 76, 122, 134, 245 GHz, >300 GHz).
* **UKW-Fieldday:** Jedes Band zählt nur in seinem Zeitfenster – GoGoHam warnt, sonst „zählt nicht“.
  Fehlt das „/p“ am eigenen Rufzeichen, gibt es einen Hinweis.
* **UKW-Sektion „Trainee“** für Ausbildungsrufzeichen; in der Sektion „6 Stunden“ zeigt die
  Contest-Uhr die Betriebszeit.
* **Neue Bausteine (Regel-Format 10):** Bänder ab 24 GHz, `band_windows`, `require_portable`.

## Neu in 0.8.24.1

* **Yaesu FT-991A wird automatisch erkannt.** Es meldet sich mit einer eigenen Kennung und
  verstand die bisherige Frage nicht – GoGoHam fragt jetzt in diesem Fall noch einmal einfacher.
  Eingetragen wird das Hamlib-Modell „FT-991“.

## Neu in 0.8.24

* **DARC-Contest-Paket 2:** IARU Region 1 Fieldday CW und SSB (DARC-Wertung, portabel/fest
  am Rufzeichen erkannt, Cabrillo mit CATEGORY-STATION), DARC FT4 Contest (mit WSJT-X),
  DARC CW-Ausbildungscontest und DARC Ausbildungscontest (Einsteiger zählen doppelt).
  Alle stehen auch im Contest-Kalender.
* **Neue Bausteine (Regel-Format 9):** Termine an einem Wochentag in mehreren Monaten
  (z. B. 2. Dienstag im Februar, Mai, August und November), Punkte „portabel/fest“
  (Fieldday), Sonderpunkte für Einsteiger-Rufzeichen.

## Neu in 0.8.23.5

* **Andere Programme laufen weiter.** Wird ein Profil mit dauerhaftem rigctld gelöscht oder
  umgestellt (bzw. der Rotor abgeschaltet), fragt GoGoHam, ob der Dienst weiterlaufen soll
  (Standard: ja) – er wird dann als eigenständiger Dienst übergeben.
* **Deinstallieren:** `bash ~/.local/share/gogoham/uninstall.sh` – übergibt die rigctld/
  rotctld-Dienste statt sie zu entfernen; Logs in `~/GoGoHam` bleiben immer erhalten.

## Neu in 0.8.23.4

* **Übernommener rigctld-Systemdienst:** Steht ein Profil auf dessen Port auf „nur solange
  GoGoHam läuft“, fragt GoGoHam beim Speichern einmal nach „dauerhaft“ – sonst verlieren
  andere Programme (Log-Programme, WSJT-X) die Verbindung, wenn GoGoHam zu ist.

## Neu in 0.8.23.3

* **Beam-Keil mit Verlauf:** in der Mitte kräftig, zu den Rändern hin durchsichtig – zeigt, wo
  die Hauptenergie liegt.

## Neu in 0.8.23.2

* **Beam-Keil über die ganze Strecke** bis zum Gegenpunkt (auch über die Datumsgrenze gefüllt)
  und **Öffnungswinkel der Antenne einstellbar** (*Einstellungen → Rotor*, Standard 30°).

## Neu in 0.8.23.1

* **Rotor auf der Karte:** oranger Beam-Keil vom eigenen Standort (Häkchen „Beam“), beim Drehen
  das Ziel gestrichelt. Rechtsklick in die Karte (freie Stelle, Bake, Spot) → „Rotor drehen“.
* **Rotor-Fenster** (*Ansicht → Rotor*): Kompassrose, Klick dreht dorthin, Gradzahl eingeben,
  SP/LP zum Rufzeichen, Stopp.

## Neu in 0.8.23

* **Rotorsteuerung** über Hamlib rotctld (alle Rotoren und Interfaces aus der Hamlib-Liste, z. B.
  GS-232B, ERC, K3NG, SPID, Rotor-EZ). Neuer Reiter *Einstellungen → Rotor* (rotctld dauerhaft
  als Standard, Port 4540). **Alt+R** = Short Path zum Rufzeichen, **Alt+Shift+R** = Long Path,
  **Alt+S** = Stopp, Bandmap-Rechtsklick „Rotor drehen“, wahlweise automatisch beim Tippen.
  Statuszeile „Rotor: 287° → 312°“. Bei Überlappung (z. B. 450°) der kürzere Weg.

## Neu in 0.8.22.1

* **Neue Funkgerät-Profile richten rigctld dauerhaft ein** (wo systemd vorhanden ist) – nach
  „Gerät erkennen“ und OK funktionieren WSJT-X & Co. sofort mit. Bestehende Profile bleiben,
  wie sie sind.

## Neu in 0.8.22

* **Funkgeräte-Reiter aufgeräumt.** Vorne nur Profil, Gerät, Schnittstelle mit „Gerät erkennen“,
  Baudrate, „Verbindung testen“ und „PTT testen“. Alles Weitere (Interface, WinKey, PTT-Leitung,
  rigctld, eigene Optionen) unter **„Erweiterte Einstellungen …“** – eine Zeile daneben zeigt,
  was dort vom Standard abweicht.
* **Ältere Geräte ohne USB** (Interface, USB-Seriell-Adapter): Strom fürs Interface über
  DTR/RTS (mit Warnung, Konflikt mit PTT wird abgelehnt), CI-V-Adresse für Icom, eingebaute
  COM-Schnittstellen und Bluetooth in der Liste, „Gerät erkennen“ probiert auch 1200/2400 Baud.
* **Verständliche Meldungen** bei fehlender Berechtigung (Gruppe uucp/dialout samt Befehl),
  belegter oder fehlender Schnittstelle und bei älteren Geräten ohne Namensabfrage.

## Neu in 0.8.21.1

* **Contest-Kalender: Filter.** Kein Häkchen gesetzt = nichts angezeigt (vorher: alles). Neues
  Häkchen „Alle“ schaltet alle Filter auf einmal an oder aus.

## Neu in 0.8.21

* **Contest-Kalender** (*Datei → Contest-Kalender …*, Strg+K): nächste Termine aller Contests,
  die GoGoHam loggen kann – offline aus den Regeln berechnet, mit Ortszeit/UTC, Dauer und
  Countdown. Filter CW/SSB/Digi/UKW, Doppelklick legt ein Log für den Contest an, Export als
  .ics-Datei für Thunderbird/Google/Handy, Erinnerung beim Programmstart (abschaltbar).

## Neu in 0.8.20.1

* **Karte unabhängig von Bandmap und Bakenanzeige.** Sind die Häkchen „Baken“ bzw.
  „Cluster-Spots“ an, verbindet sich die Karte selbst mit dem Reverse Beacon Network bzw. dem
  DX-Cluster – die anderen Fenster dürfen zu sein.

## Neu in 0.8.20

* **Baken und Cluster-Spots auf der Karte** (je ein eigenes Häkchen über der Karte).
  Baken als Dreiecke in den Farben der Bakenanzeige, Spots des aktiven Bandes als Punkte am
  Standort ihres Landes in den Farben der Bandmap. Klick auf einen Spot stellt ein wie in der
  Bandmap, Rechtsklick öffnet QRZ.com.
* **QRZ.com: Rufzeichen mit Präfix richtig erkannt.** Auch bei gleich langen Teilen wie
  VP2E/W1AW wird jetzt mit der Länderdatei erkannt, welcher Teil nur ein Länderpräfix ist.

## Neu in 0.8.19.2

* **Rufzeichen bei QRZ.com ansehen.** Rechtsklick auf ein QSO im Log oder auf einen Spot in der
  Bandmap → „… bei QRZ.com ansehen“ öffnet die Seite der Station im Browser. Zusätze wie /P oder
  ein vorangestelltes Gastland (EA8/DL1ABC) werden weggelassen.

## Neu in 0.8.19.1

* **Punktestand: Spaltenköpfe vollständig lesbar.** In den Designs „Franken hell“ und „Franken
  dunkel“ war z. B. „Länder“ in der kleinen Punktetabelle an beiden Rändern abgeschnitten. Die
  Spalten richten sich jetzt nach ihrem Inhalt, der übrige Platz wird gleichmäßig verteilt.

## Neu in 0.8.19

* **Band-übergreifender Multi-Hinweis in der Bandmap.** Ein Spot, der auf dem aktuellen Band
  keinen neuen Multiplikator bringt (oder schon gearbeitet ist), aber **auf einem anderen Band
  noch ein fehlender Multi** wäre, erscheint jetzt **orange mit ↕**. Im Tooltip steht, auf welchen
  Bändern der Multi noch fehlt – so siehst du sofort, ob sich ein Bandwechsel lohnt. Grün mit ★
  (neuer Multi auf diesem Band) bleibt wie gehabt. Nur bei Contests, die Multiplikatoren je Band
  zählen.

## Neu in 0.8.18.3

* **Fehlerbericht** (Hilfe → Fehlerbericht erstellen …): Version, System, Schnittstellen,
  Funkgeräte-Einstellungen und letzte Meldungen in einem Text – ohne Passwörter und QSOs. Speichern,
  kopieren oder per E-Mail an DO2GGH. Dafür gibt es jetzt eine Protokolldatei
  (`~/.local/state/gogoham/gogoham.log`), die auch Abstürze festhält.
* **Kontakt zu DO2GGH** direkt in der Menüleiste (nur vor 1.0): öffnet eine E-Mail.
* **Uhrzeit-Prüfung:** beim Start und stündlich über einen Zeitserver. Geht die Uhr mehr als
  2 Sekunden falsch, stellt „Synchronisieren“ sie mit einem Klick (Linux fragt nach dem Passwort).

## Neu in 0.8.18.2

* **Fehler behoben:** Der WinKey lief unter Python 3.13 nicht (Namensgleichheit mit einem
  internen Python-Namen) – unter 3.14 fiel es nicht auf.
* **Beta-AppImage** (nur für Beta-Tester): `tools/build_appimage.sh` baut eine einzelne Datei mit
  Python, Qt, NumPy und Hamlib (läuft ab glibc 2.34, z. B. Fedora). Dort gibt es „rigctld dauerhaft
  einrichten“ nur, wenn auf dem PC ein eigenes Hamlib installiert ist.

## Neu in 0.8.18.1

* **microHAM DXP automatisch erkennen:** „Gerät erkennen“ findet das DXP an seiner USB-Kennung,
  bestimmt CAT-, WinKey- und FSK-Anschluss selbst und trägt Funkgerät, Baudrate und „CW senden
  über: WinKey“ ein. Es wird nichts gesendet.
* **Schutz:** Die Geräteerkennung schickt einem WinKey nie die CAT-Fragen (er würde sie als CW
  senden) und sagt, wenn für CAT versehentlich ein WinKey-Anschluss gewählt ist.
* Läuft der ModemManager oder fehlen Rechte für die Schnittstellen, zeigt GoGoHam die passenden
  Befehle zum Kopieren.
* *Nach Handbuch gebaut, mit nachgebautem DXP getestet – mit echtem Gerät noch nicht.*

## Neu in 0.8.18

* **CW über einen WinKey** (K1EL WinKeyer 2/3, z. B. WinKeyer USB oder im **microHAM DXP**):
  Funkgeräte-Einstellungen → „CW senden über: WinKey“ mit eigener Schnittstelle. Funktionstasten,
  ESM und Auto-CQ gehen an den WinKey, Esc bricht ab, Bild auf/ab und der Tempo-Knopf am WinKey
  stellen das Tempo, das Paddle unterbricht. Knopf „WinKey prüfen“ fragt nur die Version ab.
* **PTT über die DTR- oder RTS-Leitung** einer Schnittstelle statt über CAT (z. B. DXP: „DTR =
  PTT“ im Gerätemenü). „PTT testen“ benutzt die gewählte Leitung; bei Verbindungsabbruch geht
  sie sofort aus.
* Handbuch: neuer Abschnitt „CW über WinKey und PTT über DTR/RTS“ mit Einrichtung des DXP.
* *Nach Datenblatt gebaut, mit nachgebautem WinKey getestet – mit echtem Gerät noch nicht.*

## Neu in 0.8.17.3

* **Zeile „Andere Programme“** in den Funkgerät-Einstellungen: zeigt, was man in WSJT-X & Co.
  einträgt (z. B. „Hamlib NET rigctl“ mit 127.0.0.1:4533) – mit Hinweis, wenn das nur geht,
  solange GoGoHam läuft.

## Neu in 0.8.17.2

* **PTT testen:** Neuer Knopf neben „Verbindung testen“. Nach einer Rückfrage geht das Gerät
  für 1 Sekunde auf Senden und von selbst wieder auf Empfang (PTT wird in jedem Fall wieder
  ausgeschaltet); meldet das Gerät seinen Zustand, sagt GoGoHam, ob es wirklich gesendet hat.
* **Profilplätze frei belegbar:** Profil 1–3 lassen sich in beliebiger Reihenfolge anlegen –
  ein Gerät auf Platz 2 bleibt auf Platz 2. Start-Profil ist der niedrigste belegte Platz.

## Neu in 0.8.17.1

* **„Gerät erkennen“ findet jetzt auch Yaesu-Geräte mit Werkseinstellung „CAT RTS = ON“**
  (z. B. FT-891): Antwortet am ersten Yaesu-Anschluss nichts, fragt GoGoHam ein zweites Mal mit
  eingeschalteter RTS-Leitung – dort ist RTS nur die Freigabe für CAT, PTT liegt bei Yaesu auf
  dem zweiten Anschluss. Bei allen anderen Geräten bleibt RTS aus, damit nie gesendet wird.

## Neu in 0.8.17

* **rigctld dauerhaft im Hintergrund:** Je Profil neu wählbar *„GoGoHam richtet rigctld dauerhaft
  ein“*. rigctld läuft dann ab der Anmeldung immer – auch wenn GoGoHam zu ist –, damit WSJT-X,
  Log-Programme usw. jederzeit über den Port des Profils mit dem Gerät sprechen. Kein Passwort,
  keine Terminal-Befehle: GoGoHam legt beim Klick auf OK einen Dienst für deinen Benutzer an,
  passt ihn bei Änderungen an und entfernt ihn mit dem Profil. Immer mit dem festen
  Schnittstellen-Namen; ist das Gerät abgesteckt, wartet rigctld.
* **„Gerät erkennen“ narrensicher:** Ein laufender rigctld wird **nachgeprüft** statt ihm zu
  glauben. Steckt an seiner Stelle inzwischen ein anderes Gerät, bietet GoGoHam an, die
  Steuerung zu **übernehmen** (bei einem Systemdienst einmal das Passwort) – Profile, die den
  alten rigctld benutzt haben, bekommen sofort einen eigenen auf demselben Port, WSJT-X & Co.
  müssen nichts umstellen. Bei leerem Feld werden **alle** Schnittstellen durchsucht
  (bei mehreren Treffern zur Auswahl), Schnittstellen anderer Profile übersprungen, und
  eingetragen wird immer der feste Name aus `/dev/serial/by-id/`.

## Neu in 0.8.16

* **Gerät erkennen:** In *Einstellungen → Funkgerät (CAT)* steht neben der Schnittstelle der
  Knopf **„Gerät erkennen“**. GoGoHam fragt das Gerät „Wer bist du?“ und trägt **Funkgerät,
  Schnittstelle und Baudrate** ein – alles bleibt änderbar. Erkannt werden gängige Icom-
  (CI-V), Kenwood- und Yaesu-Geräte; Elecraft wird als „Elecraft“ erkannt, das genaue Modell
  wählst du selbst. Es werden **nur lesende Befehle** geschickt, **nie gesendet**. Läuft für
  die Schnittstelle schon ein rigctld (z. B. als Systemdienst), wird sie nicht angefasst:
  GoGoHam übernimmt Modell, Baudrate und Port des rigctld und benutzt ihn mit. Ist keine
  Schnittstelle gewählt, werden alle angeschlossenen durchsucht.

## Neu in 0.8.15

* **Grayline-Karte:** *Ansicht → Karte (Grayline)* öffnet ein eigenes Fenster (per Doppelklick
  auf die Titelleiste andockbar). Zwei Kartenarten zum Umschalten: **Weltkarte** und
  **Kreiskarte** um den eigenen Locator (gerade Linie von der Mitte = Beamrichtung, Gradring,
  Entfernungsringe). Einzeln schaltbar: **Tag/Nacht** (läuft mit der Uhrzeit, Sonne markiert),
  **Dämmerung** (weicher Streifen bis 12° unter dem Horizont) und **Weg zur Gegenstation**
  zum Rufzeichen in der Eingabezeile – Short Path durchgezogen, Long Path gestrichelt, mit Grad
  und km. Maus über der Karte: Richtung und Entfernung. **Mausrad zoomt** (Ziehen verschiebt,
  Doppelklick = ganze Karte); gezoomt zeigt der Tooltip auch den Locator (2-, 4-, dann
  6-stellig, je nach Vergrößerung). Dazu einzeln schaltbar: **Locator-Gitter** (beim Zoomen
  Großfelder → Felder → Kleinfelder, beschriftet), **Flüsse** und **Städte** (deutsche Namen,
  je nach Zoom mehr, ohne Überdeckung); Seen immer. Kartendaten von **Natural Earth** 1:10 Mio.
  (gemeinfrei, 3,5 MB) sind dabei – kein Internet nötig.
* **Kartenhintergrund wählbar:** **Satellit (NASA)** – Blue Marble des aktuellen Monats, nachts
  die Stadtlichter (Black Marble) – oder **Relief (Natural Earth)** oder **Einfach**. Die Bilder
  werden beim ersten Wählen nach Rückfrage heruntergeladen (NASA ~40 MB, Relief ~90 MB, auch unter
  *Einstellungen → Daten & Updates*), in Kacheln zerlegt und gehen danach offline; das NASA-Bild
  des neuen Monats holt das tägliche Update. Locator-Gitter und -Beschriftung grau mit hellem
  Rand, Kleinfelder erst, wenn sie ins Bild passen. Beim Start öffnen per Häkchen unter
  *Einstellungen → Darstellung*.

## Neu in 0.8.14.1

* **Zusatzfenster: offen = an, zu = aus.** Für Super Check Partial, Bandmap und Baken gilt
  jetzt dieselbe Regel, egal ob man das Fenster über das Menü *Ansicht*, das Rechtsklick-Menü
  eines Fensters oder das X öffnet bzw. schließt. Bandmap öffnen verbindet mit dem DX-Cluster,
  schließen trennt; Baken genauso mit dem Reverse Beacon Network. (Vorher blieb ein über das
  Rechtsklick-Menü geöffnetes Fenster leer.)
* Der Eintrag *Ansicht → DX-Cluster verbinden* und das Häkchen „DX-Cluster verbinden“ in den
  Einstellungen entfallen – *Ansicht → Bandmap* reicht.
* **Beim Programmstart öffnen:** neue Häkchen unter *Datei → Einstellungen → Darstellung*.
  Standard: kein Zusatzfenster offen (auch Super Check Partial nicht).

## Neu in 0.8.14

* **Bakenanzeige (NCDXF/IARU):** *Ansicht → Baken* zeigt, welches Band gerade wohin offen ist.
  GoGoHam liest dafür beim **Reverse Beacon Network** mit (Anmeldung mit deinem Rufzeichen, nur
  lesend) und zählt nur, was Empfänger im **Umkreis von 1000 km** um deinen Locator hören (die
  Baken selbst stehen weltweit – jede steht für eine Richtung). 18 Baken mit
  Standort und Richtung, Spalten = Bakenbänder des Contests (20 / 15 / 10 m). Grün = in den
  letzten 15 Minuten gut gehört (ab 10 dB), gelb = schwach oder 15–30 Minuten her, grau =
  nicht gehört. Maus auf ein Feld: welche Empfänger, wie weit, wann, wie stark. Nur bei
  Contests mit 20, 15 oder 10 m; ohne Internet nicht einschaltbar (klare Meldung). Nach dem
  Einschalten füllt sich die Tabelle in 10–15 Minuten. Das Funkgerät bleibt unberührt.
  Steht das Log auf NON-ASSISTED, warnt GoGoHam wie beim DX-Cluster (manche Contests zählen das
  RBN als Unterstützung).
* **Super Check Partial mehrspaltig:** Zieht man das Fenster breiter, stehen die Rufzeichen in
  mehreren Spalten nebeneinander (zeilenweise wie beim Lesen). Etwas kleinere Schrift.
* **Logtabelle passt sich an:** Der Punktestand steht fest daneben; die Spalten der Logtabelle
  füllen genau die verbleibende Breite (im Verhältnis), nichts verschwindet mehr darunter.
  Ziehen verschiebt nur die Grenze zwischen zwei Spalten; kein Titel wird abgeschnitten.
* **Bandmap in Zeitungsspalten:** Ist sie breit genug, läuft die Liste nach Frequenz von oben
  nach unten und dann in der nächsten Spalte weiter. Schmal bleibt es eine Spalte.

## Neu in 0.8.13

* **Funkwetter** unten links: **SFI** (Sonnenfluss), **A**- und **K-Index** vom
  US-Weltraumwetterdienst NOAA SWPC, alle 30 Minuten neu. Grün = gut, gelb = mittel, rot =
  schlecht. Die Farbe des SFI richtet sich nach dem aktiven Band (auf 10–15 m braucht es mehr
  Sonnenfluss als auf 20 m; auf 30–160 m und UKW steht er grau). Maus darüber zeigt die
  Messzeiten. Ohne Internet: grau „Funkwetter: –“.
* **Neue Hinweiszeile** unten (Platz für zwei Zeilen, farbige Schrift) über der Leiste mit Funkwetter und den dauernden
  Anzeigen: Meldungen vom Funkgerät, QSY, Fehler und die ⚠-Hinweise zum Rufzeichen stehen jetzt
  dort (blau = Hinweis, orange = Warnung, rot = Fehler) und verdecken nichts mehr. Unter dem
  Rufzeichen bleibt nur die Live-Wertung (DUPE, NEUER MULTI, Punkte).
* „Daten & Updates“ (Einstellungen) und der Knopf „S&P“ zeigen das „&“ jetzt richtig an.
* Ladebildschirm-Morsezeichen und Probehören der Sprachaufnahmen kommen in Stereo (auf manchen
  Systemen war Mono nur links zu hören). Zum Funkgerät bleibt es mono – Sendepegel unverändert.
* Logo ohne feinen Rahmen und eckige Ecken (Qt konnte die Rundung der Logo-Datei nicht zeichnen).

## Neu in 0.8.12.9

* Aufgeräumtes Menü: Im Menü *Datei* stehen nur noch *Neues Contest-Log*, *Funkgerät-Profil*,
  *Einstellungen* und *Beenden*. Alles rund ums Logbuch (öffnen, Log-Einstellungen, prüfen, QTCs,
  exportieren, Sicherung wiederherstellen) steht im neuen Menü **Log** zwischen *Datei* und
  *Ansicht*. Die Tastenkürzel bleiben gleich.
* **Sprachaufnahmen** sind jetzt ein Reiter in den Einstellungen (*Datei → Einstellungen →
  Sprachaufnahmen*). Alles auf diesem Reiter wird sofort gespeichert, auch bei „Abbrechen“.
  Ob F1–F8 die eigenen Aufnahmen senden, stellst du nur noch auf dem Reiter *Funktionstasten*
  ein („SSB-Ansagen kommen aus“).
* Lange Meldungen unter dem Rufzeichenfeld drücken das Fenster nicht mehr auseinander: Sie
  nutzen kurz die ganze Breite unter den Eingabefeldern, in etwas kleinerer Schrift. Die
  Meldung „Sprachspeicher … ist leer“ ist kürzer; den ausführlichen Text zeigt die Statuszeile
  unten und der Tooltip.

## Neu in 0.8.12.8

* DX-Cluster erkennt einen stillen Abbruch (z. B. Netzwerkkabel gezogen): Kommt 45 Sekunden nichts
  vom Knoten, fragt GoGoHam per Leerzeile nach; bleibt die Antwort 15 Sekunden aus, steht rot
  „Verbindung unterbrochen – keine Antwort vom Knoten“ in der Statuszeile. Danach verbindet
  GoGoHam sich von selbst neu, sobald das Internet wieder da ist.

## Neu in 0.8.12.7

* Filter wieder Sache des Funkgeräts: Beim Wechsel der Betriebsart nimmt GoGoHam den
  Standardfilter, den das jeweilige Gerät dafür vorsieht (wie vor 0.8.12.1). Beim Bandwechsel
  wird nur die Frequenz umgestellt.

## Neu in 0.8.12.6

* Infobox: Kontinent steht rechtsbündig am Rand, mit Abstand zum Ländernamen.

## Neu in 0.8.12.5

* Infobox (Flagge, Land, Kontinent, Hinweise) hängt fest am rechten Rand und hat eine feste
  Breite – die Flagge springt nicht mehr, wenn Ländernamen verschieden lang sind.

## Neu in 0.8.12.4

* Infobox (Flagge, Land, Kontinent) ohne Rahmen; der Inhalt bleibt oben links zusammen, egal wie
  groß das Fenster ist – der Kontinent steht direkt neben dem Land.
* Meldezeile unter dem Rufzeichen („DUPE“, „NEUER MULTI …“) ohne Rahmen – leer ist dort nichts
  mehr zu sehen.

## Neu in 0.8.12.3

* Menü *Ansicht*: Eintrag heißt jetzt einfach „Bandmap“ (ohne Band) – die Bandmap folgt ja immer
  dem aktuellen Band. Der Titel über der Bandmap zeigt weiterhin das Band.

## Neu in 0.8.12.2

* Statuszeile des Clusters verständlicher: „18 Spots (alle Contest-Bänder)“ – die Bandmap zeigt
  davon nur das aktuelle Band.

## Neu in 0.8.12.1

* **Filter bleibt erhalten:** Beim Wechsel der Betriebsart (Mode-Auswahl, Klick in der Bandmap)
  ändert GoGoHam den Filter am Funkgerät nicht mehr – bisher wurde der Standardfilter der
  Betriebsart gewählt.

## Neu in 0.8.12

* **DX-Cluster mit Bandmap:** GoGoHam liest Spots von einem Cluster-Knoten (voreingestellt der
  deutsche Knoten DB0SUE, weitere getestete Knoten zur Auswahl oder ein eigener) und zeigt sie
  in der Bandmap rechts neben dem Log – immer für das aktuelle Band, nach Frequenz sortiert, mit
  deiner eigenen Frequenz dazwischen.
* **Farben wie bei der Live-Wertung:** grün mit ★ = neuer Multi, normal = neues QSO, grau
  durchgestrichen = schon gearbeitet. Ältere Spots werden blasser, nach 30 Minuten verschwinden sie.
* **Filter nach Regionen:** „gespottet von“ (voreingestellt: dein eigener Kontinent) und
  „gespottete Station aus“; dazu nur Spots auf den Bändern und in der Betriebsart des Contests.
* **Klick auf eine Station:** Funkgerät auf Frequenz und Betriebsart (CW, LSB/USB), Rufzeichen
  ins Eingabefeld, Betrieb auf S&P – gesendet wird nichts.
* Hinweis in der Statuszeile, wenn der Cluster an ist, das Log aber auf NON-ASSISTED steht.
* GoGoHam liest nur mit; eigene Spots werden nicht verschickt. Ohne Internet: klare Meldung,
  GoGoHam versucht es später von selbst wieder.

## Neu in 0.8.11.3

* **Zwei eigene Klang-Profile** im Fenster Sprachaufnahmen: „Als eigenes Profil speichern …“
  sichert Grundart (Normal/Kräftig/Contest), alle Klangregler und die Lautstärke unter einem
  eigenen Namen. Wer zwischen den Voreinstellungen hin und her schaltet, holt seine Einstellung
  mit einem Klick zurück.

## Neu in 0.8.11.2

* **Neue Klang-Voreinstellung „Kräftig“** im Fenster Sprachaufnahmen – der Kompromiss aus Normal
  und Contest: Brummfilter unter ca. 120 Hz, weniger Bass und Dumpfes, mehr Präsenz, ohne eigene
  Kompression (dafür den Sprachprozessor im Funkgerät nutzen).
* **Neuer Regler „Tiefmitten“** (um 400 Hz) gegen dumpfen, „topfigen“ Klang.
* Entstanden aus einer Messung am IC-7300 (Dummy-Load): Das Gerät gibt beim Senden den
  bearbeiteten Ton über USB zurück, so ließ sich der wirklich gesendete Klang auswerten.

## Neu in 0.8.11.1

* **Pegelanzeige im Fenster Sprachaufnahmen reagiert sofort:** Der Balken folgt der Stimme ohne
  Verzögerung und fällt zügig ab; die Zahl zeigt die Spitze der letzten 1,5 Sekunden.
* **Stille wird zuverlässig abgeschnitten:** Die Schwelle richtet sich nach dem Rauschen der
  Aufnahme, kurze Knackser (Mausklick auf Aufnehmen/Stopp) zählen nicht mehr als Sprache. Gilt
  sofort auch für schon vorhandene Aufnahmen – neu aufnehmen ist nicht nötig.
* Sendepegel zum Funkgerät: Vorgabe 20 % statt 70 % (am IC-7300 gemessen: ab etwa 40 % steigt
  die Leistung nicht mehr, die ALC steht hoch).

## Neu in 0.8.11

* **Sprachausgabe mit deiner eigenen Stimme:** Neues Fenster *Datei → Einstellungen → Sprachaufnahmen*. Du nimmst
  feste Ansagen (CQ, Danke, QRZ?, Bitte wiederholen, Nummer?, Rufzeichen?, vier eigene) sowie
  einmal die Buchstaben A–Z (Buchstabieralphabet), die Ziffern 0–9 und den Schrägstrich auf.
  GoGoHam setzt daraus Rufzeichen und Nummern zusammen und sendet sie über die Soundkarte des
  Funkgeräts – F1–F8, „Enter sendet“ und Auto-CQ funktionieren damit in SSB wie in CW.
* **Aufnahme komplett in GoGoHam**, ohne weitere Programme: Geräteauswahl, Verstärkung,
  Pegelanzeige, Probehören (nie über das Funkgerät).
* Stille am Anfang und Ende wird abgeschnitten, alle Aufnahmen werden gleich laut.
  **Klang:** Voreinstellung „Normal“ oder „Contest“, dazu Bässe, Mitten, Höhen und Lautstärke –
  wirkt beim Abspielen, die Rohaufnahme bleibt. Eigener **Sendepegel** zum Funkgerät.
* Senden: PTT über CAT, Ansage erst, wenn das Funkgerät auf Senden ist, danach sofort zurück auf
  Empfang. Esc bricht ab. Fehlt eine Aufnahme oder die Soundkarte, wird nichts gesendet.
* Auto-CQ mit eigenen Aufnahmen: Die Hörpause beginnt, sobald der CQ-Ruf zu Ende ist.
* Funktionstasten: neue Spalte „SSB: eigene Aufnahmen“ und Auswahl, woher SSB-Ansagen kommen
  (Sprachspeicher im Funkgerät bleibt Standard).
* Neue Pakete: `qt6-multimedia`, `qt6-multimedia-ffmpeg`, `python-numpy` (das Installationsskript
  holt sie).

## Neu in 0.8.10.1

* **Anzeige, was gerade gesendet wird** – rechts neben „Gearbeitet auf:“. In CW läuft der Text
  Buchstabe für Buchstabe mit (aus dem Tempo berechnet), in SSB steht kurz z. B.
  „▶ Sprachspeicher 1 (CQ)“. Esc bricht ab und leert die Anzeige.
* **Design „Franken“ hell und dunkel:** Rot-Weiß wie der Frankenrechen im Logo; Rot nur für die
  Rahmen, damit Warnungen wie „DUPE“ weiter auffallen.
* Handbuch: überflüssiger Eintrag „Ein zweiter Start öffnet kein zweites GoGoHam“ unter
  Fehlerbehebung entfernt (das ist Absicht, kein Fehler).

## Neu in 0.8.10

* **Tägliches Update beim Start:** Einmal am Tag sieht GoGoHam während des Ladebildschirms nach
  Contest-Regeln, Länderdatei (cty.dat/cty.csv), MASTER.SCP, DOK-Liste und fehlenden Flaggen
  (Flaggen höchstens monatlich). cty.dat und MASTER.SCP werden nur geladen, wenn es eine neuere
  gibt. Der Ladebildschirm wartet höchstens etwa 10 Sekunden, der Rest läuft im Hintergrund.
* **Schutz im Contest:** Läuft der Contest des geöffneten Logs gerade, bleiben Contest-Regeln und
  Länderdatei unverändert – die Punkte verschieben sich nicht.
* Geladen wird nur, was schon einmal da war; ohne Internet passiert nichts (kurzer Hinweis in der
  Statuszeile). Abschaltbar unter *Daten & Updates → Beim Start einmal täglich aktualisieren*.
* **CW-Tempo mit Bild auf / Bild ab** (je 2 WpM) – ändert nur die Einstellung am Funkgerät,
  sendet nichts. Anzeige „CW 30 WpM“ in der Statuszeile, folgt auch dem Drehknopf am Gerät.

## Neu in 0.8.9

* **„Enter sendet“ (ESM) für Run und S&P:** Enter löst je nach Lage die passende Funktionstaste
  aus – Run: CQ → Rufzeichen + Austausch → TU und loggen; S&P: Mein Call → Austausch + TU und
  loggen. Knopf **ESM** (Standard aus) und Knopf **Run/S&P**, Umschalten mit **Strg+Tab**.
* In SSB spielt ESM die festen Sprachspeicher (CQ, Mein Call, TU); Rufzeichen und Nummer sprichst
  du vorerst selbst.
* Fehlt der Austausch, sendet GoGoHam nichts und loggt nicht.
* Lehnt das Funkgerät einen Sprachspeicher ab (meist: nichts aufgenommen), steht das in der
  Statuszeile.
* Die Felder für den gesendeten und empfangenen Austausch wachsen mit – z. B. „001 JN59ME“ (UKW)
  ist jetzt ganz zu sehen.
* Korrigiert: Nach einem Contest-Wechsel lagen bei „Gearbeitet auf:“ alte und neue Kästchen
  übereinander.

## Neu in 0.8.8

* **UKW-Contests:** **IARU Region 1 VHF** (145 MHz, September) und **UHF/Mikrowellen**
  (70 cm bis 3 cm, Oktober) – Austausch Nummer + 6-stelliger Locator, die Nummer zählt je Band
  ab 001, Punkte nach Kilometern (IARU-Regel), jedes Band ein eigenes Ergebnis.
* **EDI-Export:** das Log-Format der UKW-Contests, eine Datei je Band. Neue Felder unter
  *Log-Einstellungen*: **UKW-Sektion**, **Sendeleistung (Watt)** und **Antenne**.
* **„Gearbeitet auf:“** zeigt nur noch die Bänder des gewählten Contests (auch UKW-Bänder).
* Regel-Dateien **Format 8** – ältere GoGoHam-Versionen überspringen die neuen Dateien.

## Neu in 0.8.7

* **Sieben neue Contests:** **OK/OM DX** CW und SSB, **HA DX**, **UBA DX** SSB und CW, **PACC**
  und **SP DX** – mit Live-Punkten, Multis und Cabrillo-Export. Damit sind es 29 Contests.
* **Neues Feld unter *Log-Einstellungen*:** eigenes **Kürzel im Gastgeberland** (Bezirk, Komitat,
  Provinz, UBA-Sektion) – nur nötig, wenn du selbst dort funkst.
* **IOTA:** Auswahl **Feste Station / DXpedition** und **Name der Insel** – beides steht jetzt
  automatisch in der Cabrillo-Datei.
* **Nur ein GoGoHam gleichzeitig:** Ein zweiter Start holt das laufende Fenster nach vorne,
  ohne Ladebildschirm.
* Regel-Dateien **Format 7** (Baustein „Gastgeberland“) – ältere GoGoHam-Versionen überspringen
  die neuen Dateien.

## Neu in 0.8.6

* **Drei neue Contests:** **Russian DX Contest** (März), **RSGB IOTA Contest** (Juli) und
  **All Asian DX** CW (Juni) und SSB (September) – mit Live-Punkten, Multis und Cabrillo-Export.
* **IOTA:** Nummer und IOTA-Referenz in einem Feld, z. B. `12 EU005` → `EU-005`.
* **Neue Felder unter *Log-Einstellungen*:** eigener **Oblast** (nur Russland), eigene
  **IOTA-Referenz** (nur Inselstationen) und **Alter des Operators** (All Asian).
* **Über GoGoHam:** Titel „GoGoHam by DO2GGH“, „mehrsprachig“ statt Aufzählung der Sprachen,
  und der Hinweis, dass Logo, Symbole und Ladebildschirm zum Programm gehören (GPL-3.0).
* Regel-Dateien **Format 6** – ältere GoGoHam-Versionen überspringen die neuen Dateien.

## Neu in 0.8.5.2

* **Aufgeräumt:** Die Übernahme alter Daten aus dem Vorgänger KontestLog ist entfernt, ebenso
  die alte Datei-Endung `.klog`. Logs heißen nur noch `*.ggh`. (Die Übernahme lief bei jedem
  Start erneut und kopierte gelöschte Testlogs zurück.)

## Neu in 0.8.5.1

* **Startbildschirm** mit dem neuen Logo und einem Ladebalken, der **GGH** in Morse gibt
  (14 WpM, mindestens ein Durchlauf). Mithörton (650 Hz, nur PC-Lautsprecher) wahlweise unter
  *Einstellungen → Darstellung*, Standard aus.
* **Eigenes Symbol** im Startmenü, auf dem Desktop und in der Taskleiste (16–512 px, kleine
  Größen ohne Schrift); `install.sh` installiert Symbole und den neuen Startmenü-Eintrag.

## Neu in 0.8.5

* **WAE DX Contest (CW im August, SSB im September)** mit **QTC-Empfang**: Stationen außerhalb
  Europas geben dir ihre früheren QSOs durch, jedes QTC zählt 1 Punkt. **Strg+Q** öffnet das
  QTC-Fenster: Serie eintippen („3/5“), dann je QTC eine Zeile „1307 DL1ABC 042“ + Enter.
  GoGoHam prüft höchstens 10 QTCs je Station, eigenes Rufzeichen, doppelte Einträge und die
  Uhrzeit. *Log → Empfangene QTCs …* zum Nachbearbeiten. Cabrillo mit `QTC:`-Zeilen.
* **Wertung:** Rufzeichengebiete bei W, VE, VK, ZL, ZS, JA, BY, PY, RA8/9/0 (K3ABC/1 = W1),
  Multis 80 m ×4 / 40 m ×3 / sonst ×2 (steht in der Punktetabelle am Band), nur Europa ↔
  außerhalb Europas, Betriebszeit 36 von 48 h (QTCs zählen als Betrieb), Contest-Bereiche
  80/40/20 m mit Hinweis.
* **Strg+Q** ist jetzt das QTC-Fenster; *Beenden* geht über das Menü oder das Fenster-Kreuz.
* **Neue Bausteine (Regel-Format 5):** Rufzeichengebiet, Herkunft „eu“/„non_eu“, Kontakte
  „eu_dx“, Multi-Gewichtung je Band, QTC.
* Noch nicht: QTCs **geben** (Stationen außerhalb Europas) – kommt kurz vor Version 1.0; WAE RTTY später.

## Neu in 0.8.4

* **DARC-Contest-Paket:** WAG (Worked All Germany), DARC 10 m, Weihnachtswettbewerb und
  Ostercontest – die beliebtesten DARC-Conteste nach eingereichten Logs (WAE folgt mit QTC
  in 0.8.5).
* **DOK:** eigener DOK im Fenster *Log / Station* (leer = NM); empfangener DOK wird geprüft –
  gegen alle Ortsverbände von DARC und VFDB und, nach dem Herunterladen, gegen die
  Sonder-DOK-Liste (Rufzeichen und Gültigkeit). Unbekannte DOKs sind nur ein Hinweis.
  10 m: Nummer und DOK in einem Feld („12 B36“). DOKs auch aus der Call-History.
* **Neue Bausteine (Regel-Format 4):** Punkte je eigener Herkunft (WAG), „Ausland arbeitet nur
  DL“, Multis DOK und Distrikt, Zählung je Band und Mode, Dupe je Mode, Termine „n-ter Sonntag“,
  festes Datum und Ostern (mit Minuten), Höchstzahl Wechsel im ganzen Contest, erlaubte bzw.
  contestfreie Frequenzbereiche (Hinweis), DOK im ADIF (DARC_DOK, MY_DARC_DOK).

## Neu in 0.8.3

* **Wächter für die Ausschreibungen:** Im Regel-Projekt auf GitHub prüft jeden Montag ein
  automatischer Ablauf, ob sich eine offizielle Ausschreibung geändert hat (Vergleich der
  Wörter und Zahlen, nicht der Zeilen). Bei einer Änderung entsteht eine Meldung (Issue) mit
  E-Mail. GoGoHam selbst fragt dafür nie bei den Veranstaltern an.
* **Ruhige Kopfzeile:** Uhr und Frequenz haben eine feste Breite – die laufende Uhr schiebt
  Frequenz, Band, Mode und CAT-Anzeige bei kleinerem Fenster nicht mehr hin und her.

## Neu in 0.8.2

* **Handbuch auf Englisch** (`gogoham/help/handbook.en.html`): *Hilfe → Handbuch* und die
  „?“-Knöpfe zeigen das Handbuch in der eingestellten Sprache, mit denselben Kapiteln.
* Andere Log-Programme werden neutral genannt („ein Log-Programm, z. B. QLog, CQRLOG oder
  KLog“) – im Programm, im Handbuch und hier.

## Neu in 0.8.1

* **Neues Fenster „Einstellungen“** (*Datei → Einstellungen*, Strg+,) mit Reitern:
  Funkgerät · FT8-Programme · Funktionstasten · Name/QTH · Live-Score · Darstellung
  (Design, Sprache, Schriftgröße) · Daten & Updates (Downloads, Regel-Update, Sicherungen,
  Call-History-Import).
* **Menüs aufgeräumt:** Datei · Ansicht · Hilfe · Info. *Log-Einstellungen* (Strg+L) und das
  schnelle Umschalten des Funkgerät-Profils liegen unter *Datei*.
* „Über GoGoHam“ ohne die (immer länger werdende) Contest-Liste.
* Englische Oberfläche: letzte deutsche Reste behoben (Infobox „on 160 m“, QSO-Bearbeiten,
  Live-Score, Beschriftungen aus Regel-Dateien); neue Prüfung im Betrieb
  (`tools/i18n_runtime_check.py`) über alle Contests.

## Neu in 0.8.0

* **Deutsch und Englisch:** Die ganze Bedienoberfläche gibt es jetzt auch auf Englisch
  (rund 570 Texte). Beim ersten Start gilt die Sprache des Systems; umstellen unter
  *Einstellungen → Sprache / Language* (mit Neustart).
* Auf Englisch: Ländernamen aus der Länderdatei, englisches Zahlenformat (28,450.00 kHz).
* Übersetzungen als einfache Dateien (`gogoham/i18n/en.json`) – weitere Sprachen können
  ohne Programmierkenntnisse dazukommen; `tools/i18n_check.py` zeigt fehlende Texte.
* Das Handbuch auf Englisch kam mit 0.8.2.

## Neu in 0.7.2

* *Log / Station* zeigt **nur die Felder, die der gewählte Contest braucht**; Angaben wie
  Lizenzjahr oder ITU-Zone werden für spätere Logs gemerkt.
* **IARU HF:** Rufzeichen auf „…HQ“ bekommen keine Zonen-Vorbelegung, sondern den Hinweis
  „Verbandsstation? Kürzel erfragen“.
* **Erfrage-Hinweise in der Infobox** („State: erfragen“, „Nummer: erfragen“ …) – in 0.7.0/0.7.1
  waren sie berechnet, aber nicht zu sehen.
* **Ein-Band-Contests** (ARRL 10 m, CQ 160): Angebot, das Funkgerät aufs Contest-Band zu stellen
  (nur Frequenz, kein Senden).

## Neu in 0.7.1

* **Neue Contests:** ARRL 10 m (Regeln Version 2.0), IARU HF World Championship
  (Version 1.21) und EU HF Championship (Regeln vom 30.06.2026) – GoGoHam kennt jetzt 12.
* **SSB und CW gemischt** in einem Contest, **Punkte je Mode**, **Multis je Mode**.
* **ITU-Zone/Verband** (IARU), **Jahr der ersten Lizenz** (EU HF), **mexikanische States**,
  **ITU-Region** (Maritime Mobile), **Frequenzgrenze je Mode** (ARRL 10 m: CW unter 28,300).
* **Band-/Modewechsel je Stunde** werden gezählt (EU HF: Hinweis beim 10., Warnung ab dem 11.,
  Log-Prüfung nennt die Stunden).
* Neue Felder unter *Log / Station*: **ITU-Zone / Verband**, **Jahr der ersten Lizenz**.
* ITU-Zone wird bei Ländern mit mehreren ITU-Zonen (USA, Kanada, Russland …) nicht mehr
  vorbelegt und im ADIF nur noch geschrieben, wenn sie sicher ist.
* Behoben: doppeltes „Zählt nicht: Zählt nicht:“ in der Statuszeile.

## Neu in 0.7.0

* **Neue Contests:** CQ WW 160 m (SSB und CW) und ARRL International DX (SSB und CW) –
  nach den offiziellen Ausschreibungen 2026 (CQ 160) bzw. Version 2.0 (ARRL DX).
* **Austausch je nach Herkunft der Gegenstation** (State, Provinz, CQ-Zone, Leistung) mit
  Hinweis in der Infozeile; kanadische Provinz wird aus dem Rufzeichen vorbelegt.
* **Wer mit wem:** QSOs, die nach den Regeln nicht zählen (ARRL DX: DX–DX), werden markiert.
* **US-States und VE-Provinzen** nach der offiziellen ARRL-Liste; im ADIF als STATE/VE_PROV.
* **Neue Termin-Arten** (n-tes volles Wochenende, n-ter Samstag, Beginn Freitag).
* Neue Felder unter *Log / Station*: **Leistung im Austausch**, **eigener State/Provinz**.
* Regel-Dateien **Format 2** – ältere GoGoHam-Versionen überspringen sie sauber.

## Neu in 0.6.5

* **Contest-Regeln von GitHub:** neue Contests und geänderte Regeln kommen ohne neue
  Programmversion – beim Anlegen eines Logs (abschaltbar) oder über *Einstellungen →
  Contest-Regeln aktualisieren*. Jede Datei wird geprüft, ohne Internet passiert nichts.
  Sammlung: https://github.com/do2ggh/GoGoHam-rules (CC BY 4.0).
* **Das Log merkt sich seine Regeln:** Punkte eines bestehenden Logs ändern sich nie von
  allein. Neuere Regeln lassen sich unter *Log / Station* bewusst übernehmen.
* Regel-Dateien haben jetzt eine **Revision**; zwischen eingebauten und geladenen gilt die höhere.
* Lizenz: GoGoHam GPL-3.0 (nur Version 3) mit Zusatzbedingungen, Regel-Dateien CC BY 4.0.

## Neu in 0.6.4

* **Jedes Funkgerät hat seinen eigenen rigctld** (eigener Port). Ein Geräte-Profil sagt
  nur, mit welchem GoGoHam spricht – Umschalten wirkt nur in GoGoHam, WSJT-X, Log-Programme & Co.
  sind nicht betroffen. Je Profil: „GoGoHam startet rigctld selbst“ oder „vorhandenen
  rigctld benutzen“ (z. B. Systemdienst).
* **Nie ein zweiter rigctld auf einem belegten Port** – GoGoHam benutzt den vorhandenen mit.
* **CAT-Anzeige zeigt das Gerät, das wirklich antwortet**; Warnung, wenn es nicht zum
  Profil passt. Der Verbindungstest nennt das Gerät auf dem Port.
* **FT8-Programme (WSJT-X, JTDX …):** Solange eines läuft, zeigt GoGoHam Band/Frequenz nur
  an und sendet nichts (F1–F8, Auto-CQ gesperrt). Zurück sofort bei Abmeldung, sonst nach
  30 s ohne Lebenszeichen bzw. 2 min nach dem letzten QSO. Hinweis, wenn das FT8-Programm
  das Funkgerät direkt über die USB-Leitung anspricht.
* GoGoHam startet **immer mit Profil 1**. **Kein Funkgerät voreingestellt** für neue Nutzer.

## Neu in 0.6.3

* **Funkgerät aus der kompletten Hamlib-Liste** wählen (über 300 Geräte, direkt aus dem
  installierten Hamlib) – mit Suchfeld, Beta-Hinweis, Anzeige von Bändern, Sprachspeicher
  und CW über CAT. Baudrate nur aus den Werten, die das Gerät kann.
* **Schnittstelle** aus der Liste der angeschlossenen USB-Geräte.
* **Verbindung testen:** liest einmal Frequenz und Mode – sendet nichts.
* **Bis zu drei Geräte-Profile** (z. B. IC-7300 KW / IC-9700 UKW), umschalten über
  *Einstellungen → Funkgerät-Profil* oder Klick auf die CAT-Anzeige. Das bisherige
  Gerät wird automatisch Profil 1.
* **Bandauswahl passend zum Gerät** (nur Bänder, auf denen es laut Hamlib senden kann).
* Hinweis bei F1–F8, wenn ein Gerät Sprachspeicher/CW über CAT nicht kann.
* Titelleiste: **GoGoHam by DO2GGH**.

## Neu in 0.6.2

* **Bänder ab 70 cm:** 70 cm, 23 cm, 13 cm, 9 cm, 6 cm und 3 cm (bis 10 GHz) – Erkennung
  über die Frequenz, Anzeige „70 cm“, Cabrillo `432` / `1.2G` …, ADIF `70CM` / `23CM` …,
  auch in den Regel-Dateien und bei der Übernahme aus WSJT-X. Frequenzeingabe im
  Rufzeichenfeld jetzt bis 8 Stellen (z. B. `1296200`).
* Cabrillo-Kategorie Band: zusätzlich 6M, 4M, 2M, 432, 1.2G, 2.3G, 3.4G, 5.7G, 10G.
* Texte überarbeitet: keine Vergleiche mit anderen Programmen mehr.

## Neu in 0.6.1

* **Regel-Baukasten:** Die Regeln jedes Contests stehen jetzt in einer eigenen,
  lesbaren Datei (`gogoham/rules/*.json`) statt im Programm. Eigene oder geänderte
  Regeln kommen nach `~/.local/share/gogoham/rules/` und haben Vorrang. Fehlerhafte
  Dateien werden beim Start gemeldet, dann gilt die eingebaute Regel.
  Beschreibung aller Angaben: Handbuch, Kapitel „Regel-Dateien“.
* **Export nach Vorgabe:** *Log → Log exportieren* (Ctrl+E) mit vorausgewähltem
  Format des Contests (Cabrillo/ADIF; EDI für UKW ist vorgesehen).
* Die Punkte sind exakt dieselben wie in 0.6.0 (geprüft mit allen Tests und einem
  Vergleich alt/neu über rund 21 000 Fälle).

## Neu in 0.6

* **Ortszeit** (MEZ/MESZ) unter der UTC-Uhr
* **Auto-CQ** (Strg+R): F1 wird automatisch wiederholt (Standard 3 s Ruf + 8 s Hören)
* **Call-History** aus eigenen Logs und importierten N1MM-Dateien – schlägt die Zone vor
* **Log-Prüfung** (Strg+P, automatisch vor dem Cabrillo-Export)
* **Übersicht** (Strg+M): Zonen/Länder/Präfixe/Großfelder je Band und Rate-Grafik
* **Contest-Uhr** mit Countdown und Betriebszeit-Zähler (WPX: 36 h, Pausen ab 60 min)
* **Live-Score** an contestonlinescore.com bzw. den Score Distributor
* **Sicherungen** beim Öffnen und alle 10 Minuten, **Reparatur** beschädigter Logs
* **Handbuch** (Hilfe → Handbuch) mit Suche und „?“-Knöpfen in den Einstellungen
