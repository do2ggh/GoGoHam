# Fremde Teile in GoGoHam · Third-party components

GoGoHam selbst steht unter der **GNU General Public License, Version 3** (Datei `LICENSE`).
Das gilt auch für Logo, Symbole und Ladebildschirm. Hier steht, was **nicht** von GoGoHam stammt,
woher es kommt und unter welchen Bedingungen es genutzt wird.

*English summary below.*

## 1. Mitgeliefert (im Programm enthalten)

| Teil | Datei | Herkunft | Bedingungen |
|---|---|---|---|
| Kartenumrisse (Länder, Küsten, Seen, Flüsse, Grenzen) | `gogoham/assets/world.json` | [Natural Earth](https://www.naturalearthdata.com), umgewandelt mit `tools/make_mapdata.py` | gemeinfrei (public domain), keine Erlaubnis nötig. „Made with Natural Earth.“ |
| Liste der DOKs der Ortsverbände | `gogoham/dok_ov.txt` | zusammengestellt aus den öffentlichen Seiten von [DARC](https://www.darc.de/der-club/distrikte/) und [VFDB](https://www.vfdb.org) | **VFDB (Z-DOKs): Erlaubnis am 2026-11-11 erteilt** (durch den Vorsitzenden), Weitergabe ohne die Einschränkungen „nicht kommerziell“/„gleiche Lizenz“, Quelle VFDB e.V. wird genannt – Nachweis: `docs/erlaubnisse/vfdb-2026-11-11.txt`. **DARC (A–Y): Erlaubnis am 2026-11-12 erteilt** (nach Rücksprache mit dem Vorsitzenden; die Anfrage bat um Weitergabe mit dem Programm, auch über Linux-Distributionen, ohne Einschränkung auf nicht-kommerzielle Nutzung, mit Quellenangabe), Quelle DARC e.V. wird genannt – Nachweis: `docs/erlaubnisse/darc-2026-11-12.txt`. |
| Contest-Regeldateien | `gogoham/rules/*.json` | eigene Arbeit (GoGoHam-Projekt) | CC BY 4.0, auch einzeln unter [GoGoHam-rules](https://github.com/do2ggh/GoGoHam-rules) |
| Grundstock der Call-History | `gogoham/assets/callhistory-base.csv` | eigene Arbeit: Rufzeichen und CQ-Zonen aus eigenen Contest-Logs von DO2GGH | CC BY 4.0 |
| QR-Code-Bibliothek **segno** 1.6.6 (für die QR-Codes im Contest-Kalender) | `gogoham/_vendor/segno/` | [segno](https://github.com/heuer/segno) von Lars Heuer, PyPI | BSD-3-Clause – Lizenztext liegt bei (`gogoham/_vendor/segno/LICENSE`). Nur die nötigen Module; einzige Änderung: ein Import relativ gemacht (siehe `README.GoGoHam` dort). |
| Icom-Netzwerkverfahren (Paketaufbau, Passwort-Verschleierung) | `gogoham/icomlan.py`, Test-Nachbau `tests/fake_icom.py` | eigene Python-Umsetzung nach dem Vorbild von [wfview](https://github.com/wf-group/wfview) (Phil Taylor M0VSE u. a.), das seinerseits auf [kappanhang](https://github.com/nonoo/kappanhang) (HA2NON, ES1AKOS, W6EL) beruht; Icom hat das Verfahren nicht veröffentlicht | wfview: GPL-3.0-only (wie GoGoHam), kappanhang: MIT – mit Dank an die Autoren |

## 2. Nur in den Tests (wird nicht installiert)

| Teil | Datei | Herkunft |
|---|---|---|
| Kleine Länderdatei für Tests | `tests/cty_sample.dat` | kurzer Auszug im Format der cty.dat von AD1C ([country-files.com](https://www.country-files.com)), gekürzt und mit erfundenen Testeinträgen ergänzt |

## 3. Wird erst auf Wunsch aus dem Internet geladen (nicht mitgeliefert)

GoGoHam lädt diese Daten nur, wenn du es auslöst (oder das tägliche Update einschaltest). Sie
landen in `~/.local/share/gogoham/` und gehören weiter ihren Urhebern.

| Daten | Quelle | Bedingungen |
|---|---|---|
| Länderdatei cty.dat / cty.csv | AD1C, [country-files.com](https://www.country-files.com) | Bedingungen des Anbieters |
| MASTER.SCP (Super Check Partial) | [supercheckpartial.com](https://www.supercheckpartial.com) | Bedingungen des Anbieters |
| DOK-Listen, Sonder-DOKs | [darc.de](https://www.darc.de), [vfdb.org](https://www.vfdb.org) | Bedingungen des Anbieters |
| Flaggen | [flagcdn.com / Flagpedia](https://flagpedia.net) | laut Anbieter gemeinfrei |
| Kartenbild „Nachts“ (Black Marble) | NASA Earth Observatory | NASA-Bilder, frei nutzbar mit Quellenangabe |
| Kartenbild „Relief“ | [Natural Earth](https://www.naturalearthdata.com) | gemeinfrei |
| Weltraumwetter | NOAA SWPC | amtliche US-Daten, gemeinfrei |
| Sprachprogramm Piper | [rhasspy/piper](https://github.com/rhasspy/piper) | MIT-Lizenz |
| Stimme „Thorsten“ (Deutsch) | Thorsten-Voice | CC0 |
| Stimme „Cori“ (Englisch) | Aufnahmen von LibriVox | gemeinfrei |
| Stimmen im Übungsmodus | LibriTTS-R ([openslr.org/141](https://openslr.org/141)) | CC BY 4.0 |

## 4. Programme, die GoGoHam benutzt (installiert dein System, nicht mitgeliefert)

| Programm | Wofür | Lizenz |
|---|---|---|
| Python 3 | Grundlage | PSF-Lizenz |
| Qt 6 / PySide6 | Fenster | LGPL-3.0 |
| NumPy | Übungsmodus, Ton | BSD |
| Hamlib (rigctld, rotctld) | Funkgerät, Rotor | LGPL-2.1 / GPL-2.0 |
| espeak-ng | Computerstimme | GPL-3.0 |
| speech-dispatcher | Sprachausgabe | GPL-2.0 / LGPL-2.1 |

Die Namen der Funkgeräte, Contests und Verbände gehören ihren Inhabern und werden nur zur
Beschreibung genannt.

---

## English summary

GoGoHam is licensed under the **GNU GPL, version 3** (see `LICENSE`), including its logo, icons
and splash screen. Bundled third-party data: **Natural Earth** map outlines (public domain) and a
**DOK list** compiled from the public DARC and VFDB pages (permission granted by VFDB e.V. on 2026-11-11 and by DARC e.V. on
2026-11-12, sources credited; proofs in `docs/erlaubnisse/`). Contest rule files and the call history starter set (calls and CQ zones from DO2GGH's own
contest logs) are our own work under CC BY 4.0. The QR code library **segno** 1.6.6 (Lars Heuer,
BSD-3-Clause, licence text in `gogoham/_vendor/segno/LICENSE`) is bundled for the contest calendar QR codes. The Icom network protocol support
(`gogoham/icomlan.py`) is our own Python implementation modelled on **wfview** (GPL-3.0-only,
Phil Taylor M0VSE et al.), itself based on **kappanhang** (MIT, HA2NON, ES1AKOS, W6EL) – thanks to
their authors. The
test suite contains a small cty.dat-style sample (AD1C, country-files.com) that is not installed.
Everything in section 3 is only downloaded on request and stays the property of its owners.
The programs in section 4 are installed by your distribution, not shipped with GoGoHam.
