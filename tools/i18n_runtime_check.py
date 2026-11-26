#!/usr/bin/env python3
"""Englische Oberfläche im Betrieb prüfen: deutsche Reste finden (ab 0.8.1).

Startet GoGoHam unsichtbar (offscreen) auf Englisch mit vorübergehenden Einstellungen,
legt für jeden Contest ein Probe-Log in einem Testordner an, tippt Rufzeichen ein, loggt
QSOs, lässt Log-Prüfung, Übersicht und Contest-Uhr laufen und durchsucht alle sichtbaren
Texte nach deutschen Wörtern. Deine echten Logs und Einstellungen werden nicht berührt.

Aufruf:  python3 tools/i18n_runtime_check.py [sprache]     (Standard: en; ab 0.10.27 jede Sprache)
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GER = re.compile(
    r"[äöüÄÖÜß„]|\b(und|nicht|bitte|kein|keine|mit|für|von|ist|wird|zählt|auf|bei|nach|noch|schon|"
    r"gearbeitet|gesendet|empfangen|erfragen|Rufzeichen|Datei|Fehler|Funkgerät|aus|neu|NEU|Austausch|"
    r"Punkte|Pkt|Länder|Zonen|Provinz|Gerät|Profil|Leistung|Jahr|Lizenz|Sicherung|Hinweis|Wert|"
    r"empf|ges|Land|Entfernung|Richtung|Zeit|Stunde|Wechsel|Verband|Europa|eigene|Gegenstation)\b")
# Für Sprachen mit eigenen Umlauten (fi, sv, da, nb …) zählen ä/ö nicht als deutsch
GER_NO_UMLAUT = re.compile(GER.pattern.replace("[äöüÄÖÜß„]", "[üÜß„]"))
# Zeichen/Wörter, die in der Zielsprache selbst vorkommen (keine deutschen Reste)
OWN_CHARS = {"fi": "äöÄÖ", "sv": "äöÄÖ", "da": "äöÄÖ", "nb": "äöÄÖ", "hu": "öüÖÜ„", "tr": "öüÖÜ",
             "sk": "äÄ„", "pl": "„", "cs": "„", "hr": "„", "nl": "äöüÄÖÜ"}
OWN_WORDS = {"nl": {"Land", "Europa", "Zeit"}, "pl": {"Europa", "Pkt"}, "hr": {"Europa"},
             "cs": {"Europa"}, "sk": {"Europa"}, "sv": {"Land", "Europa"}, "da": {"Land", "Europa"},
             "nb": {"Land", "Europa"}, "es": {"Europa"}, "it": {"Europa"}, "pt": {"Europa"},
             "id": {"Europa"}, "fi": {"Europa"}}


def make_pattern(lang: str) -> re.Pattern:
    chars = "".join(c for c in "äöüÄÖÜß„" if c not in OWN_CHARS.get(lang, ""))
    words = GER.pattern.split(r"\b(", 1)[1].rsplit(r")\b", 1)[0].split("|")
    words = [w for w in words if w not in OWN_WORDS.get(lang, set())]
    return re.compile((f"[{chars}]|" if chars else "") + r"\b(" + "|".join(words) + r")\b")


CALLS = ["W1AW", "VE3XX", "DL1ABC", "OE1XYZ", "JA1XX", "KH6XX", "K1ABC/MM", "DA0HQ", "XE1AA", "4X1AB"]


def main() -> int:
    lang = sys.argv[1] if len(sys.argv) > 1 else "en"
    ger = make_pattern(lang)
    tmp = Path(tempfile.mkdtemp(prefix="gogoham-i18n-"))
    (tmp / "cfg" / "gogoham").mkdir(parents=True)
    (tmp / "logs").mkdir()
    (tmp / "cfg" / "gogoham" / "config.json").write_text(json.dumps({
        "rig_enabled": False, "wsjtx_enabled": False, "livescore_enabled": False, "last_log": "",
        "rules_auto_update": False, "language": lang}), encoding="utf-8")
    os.environ["XDG_CONFIG_HOME"] = str(tmp / "cfg")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from gogoham import i18n
    i18n.set_language(lang)
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QTableWidget
    app = QApplication([])  # noqa: F841
    from gogoham import logcheck
    from gogoham.contests import CONTESTS
    from gogoham.db import DEFAULT_META, LogDB
    from gogoham.gui.main_window import MainWindow
    from gogoham import callhistory     # erfundene QSOs nie in die echte Call-History
    callhistory.history_dir = lambda: tmp / "callhistory"
    callhistory.BASE_FILE = tmp / "kein-grundstock.csv"

    w = MainWindow()
    found: dict[str, str] = {}

    def scan(where: str) -> None:
        for widget in [w] + ([w.stats_win] if w.stats_win else []):
            texts = [x.text() for x in widget.findChildren(QLabel)]
            texts += [x.text() for x in widget.findChildren(QAbstractButton)]
            for t in widget.findChildren(QTableWidget):
                for r in range(min(t.rowCount(), 30)):
                    for c in range(t.columnCount()):
                        it = t.item(r, c)
                        if it:
                            texts.append(it.text())
                texts += [t.horizontalHeaderItem(i).text() for i in range(t.columnCount())
                          if t.horizontalHeaderItem(i)]
            texts.append(w.statusBar().currentMessage())
            for tx in texts:
                plain = re.sub(r"<[^>]+>", " ", tx or "").strip()
                if ger.search(plain):
                    found.setdefault(plain[:110], where)

    for cid, cls in CONTESTS.items():
        meta = dict(DEFAULT_META, contest=cid, mycall="DO2GGH", my_grid="JN59me", my_licyear="82",
                    my_zone="14")
        p = tmp / "logs" / f"{cid}.ggh"
        db = LogDB(p)
        db.set_meta(meta)
        db.close()
        w.open_log(str(p))
        band = cls.bands[0] if len(cls.bands) == 1 else "20"
        mode = "FT8" if cid == "ww-digi" else ("CW" if "CW" in cls.modes else "USB")
        w._updating = True
        w.cb_band.setCurrentText(band)
        w.cb_mode.setCurrentText(mode)
        w._updating = False
        w._band_offer = None
        for i, call in enumerate(CALLS):
            w.clear_entry()
            w.ed_call.setText(call)
            w.update_check()
            scan(f"{cid} tippen {call}")
            ex = {"cq_zone": "05", "serial": "001", "grid4": "FN31", "iaru": "08",
                  "lic_year": "95"}.get(cls.exchange_kind, "CT")
            if w.ed_exch.text() == "":
                w.ed_exch.setText(ex)
            w.update_check()
            scan(f"{cid} mit Austausch {call}")
            w.enter_pressed()
            scan(f"{cid} geloggt {call}")
            if i == 2:
                w.ed_call.setText(CALLS[0])
                w.update_check()
                scan(f"{cid} Dupe")
        for f in logcheck.check(w.contest, w.qsos, w.scorer):
            if ger.search(f.text):
                found.setdefault(f.text[:110], f"{cid} Log-Prüfung")
        w.show_stats()
        w.stats_win.refresh(w.contest, w.scorer, w.qsos)
        scan(f"{cid} Übersicht")
        w._update_contest_time()
        scan(f"{cid} Contest-Uhr")
    w.close()
    print(f"Geprüft: {len(CONTESTS)} Contests × {len(CALLS)} Rufzeichen")
    for t, where in sorted(found.items(), key=lambda x: x[1]):
        print(f"  {where:32} | {t}")
    print("Deutsche Reste:", len(found))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
