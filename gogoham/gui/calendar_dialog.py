"""Fenster „Contest-Kalender“ (ab 0.8.21): nächste Termine aller GoGoHam-Contests.

Doppelklick oder „Log anlegen“ = neues Log für diesen Contest. Filter CW/SSB/Digi/UKW,
Suche ab 2 Zeichen (0.8.29.1), Export als .ics – alle oder per Rechtsklick nur die markierten
(0.8.29.1), Erinnerung beim Programmstart an-/abschaltbar. Alles offline berechnet.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from .. import contestcal as cc
from ..i18n import language, num, tr

GREEN = "#1b8a3a"
_TZ_DE = {"CET": "MEZ", "CEST": "MESZ"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def weekday(d: datetime) -> str:
    return (tr("Mo"), tr("Di"), tr("Mi"), tr("Do"), tr("Fr"), tr("Sa"), tr("So"))[d.weekday()]


def date_text(d: datetime) -> str:
    """„Sa 28.11.2026“ (deutsch) bzw. „Sat 2026-11-28“ (sonst)."""
    if language() == "de":
        return f"{weekday(d)} {d:%d.%m.%Y}"
    return f"{weekday(d)} {d:%Y-%m-%d}"


def local_text(start_utc: datetime) -> str:
    loc = start_utc.replace(tzinfo=timezone.utc).astimezone()
    tz = loc.tzname() or ""
    if language() == "de":
        tz = _TZ_DE.get(tz, tz)
    return f"{date_text(loc)}  {loc:%H:%M} {tz}".strip()


def duration_text(hours: float) -> str:
    return tr("{n} h", n=int(hours) if hours == int(hours) else num(hours, 1))


def kinds_text(kinds) -> str:
    names = {"CW": "CW", "SSB": "SSB", "RTTY": "RTTY", "DIGI": tr("Digi"), "UKW": tr("UKW")}
    return ", ".join(names[k] for k in cc.KINDS if k in kinds)


_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "é": "e", "è": "e"})


def fold(text: str) -> str:
    """Für die Suche: klein, Umlaute ausgeschrieben."""
    return (text or "").lower().translate(_FOLD)


def matches(query: str, *fields: str) -> bool:
    """Suche ab 2 Zeichen: steckt der Text in Name oder Kurzbezeichnung? Leerzeichen und
    Bindestriche zählen nicht („cqww“ findet „CQ WW“, „cq-ww“ findet „cqww-cw“)."""
    q = fold(query).strip()
    if len(q) < 2:
        return True
    hay = " ".join(fold(f) for f in fields)
    squeeze = lambda t: "".join(ch for ch in t if ch.isalnum())     # noqa: E731
    return q in hay or squeeze(q) in squeeze(hay)


class SearchEdit(QLineEdit):
    """Esc leert das Suchfeld (erst wenn es leer ist, schließt Esc das Fenster)."""

    def keyPressEvent(self, ev):  # noqa: N802
        if ev.key() == Qt.Key.Key_Escape and self.text():
            self.clear()
            return
        super().keyPressEvent(ev)


class CalendarDialog(QDialog):
    COLS = ("local", "utc", "dur", "name", "kinds", "status")

    def __init__(self, contests: dict, cfg: dict, on_new_log=None, on_change=None,
                 parent=None, now=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Contest-Kalender"))
        self.contests = contests
        self.cfg = cfg
        self.on_new_log = on_new_log           # (contest-id, Jahr)
        self.on_change = on_change             # cfg speichern
        self._now = now                        # für Tests feste Zeit
        self.rows: list[cc.Entry] = []
        lay = QVBoxLayout(self)

        info = QLabel(tr("Nächste Termine aller Contests, die GoGoHam loggen kann – berechnet "
                         "aus den Regeln, ohne Internet. Veranstalter verschieben Termine "
                         "selten; im Zweifel die Ausschreibung prüfen."))
        info.setWordWrap(True)
        lay.addWidget(info)

        frow = QHBoxLayout()
        frow.addWidget(QLabel(tr("Zeigen:")))
        self.filters = {}
        want = set(cfg.get("calendar_filter", cc.KINDS))
        if "calendar_filter" in cfg and "RTTY" not in cfg.get("calendar_kinds_known", ()):
            want.add("RTTY")                  # neu in 0.10.7: bei gespeichertem Filter dazunehmen
        # „Alle“ schaltet alle Filter an bzw. aus; ist selbst an, wenn alle an sind
        self.chk_all = QCheckBox(tr("Alle"))
        self.chk_all.setToolTip(tr("Alle Filter ein- oder ausschalten"))
        self.chk_all.clicked.connect(self._all_clicked)
        frow.addWidget(self.chk_all)
        tips = {"CW": tr("Contests mit CW"), "SSB": tr("Contests mit SSB (Sprache)"),
                "RTTY": tr("RTTY-Contests (gefunkt wird in fldigi)"),
                "DIGI": tr("Digitale Contests (FT4/FT8)"),
                "UKW": tr("Contests auf UKW und Mikrowelle (2 m, 70 cm …)")}
        for k in cc.KINDS:
            chk = QCheckBox(kinds_text({k}))
            chk.setToolTip(tips[k])
            chk.setChecked(k in want)
            chk.toggled.connect(lambda _v: self._filter_changed())
            frow.addWidget(chk)
            self.filters[k] = chk
        frow.addStretch(1)
        frow.addWidget(QLabel(tr("Suchen:")))
        self.search = SearchEdit()
        self.search.setPlaceholderText(tr("ab 2 Buchstaben, z. B. DARC"))
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(220)
        self.search.textChanged.connect(lambda _t: self.refresh())
        frow.addWidget(self.search)
        lay.addLayout(frow)
        self.empty = QLabel(tr("Kein Filter gewählt – Häkchen setzen, um Contests zu sehen."))
        self.empty.setStyleSheet("color:#888888;")
        self.empty.hide()

        self.tbl = QTableWidget(0, len(self.COLS))
        self.tbl.setHorizontalHeaderLabels([tr("Beginn (Ortszeit)"), tr("Beginn UTC"),
                                            tr("Dauer"), tr("Contest"), tr("Art"),
                                            tr("Wann")])
        self.tbl.verticalHeader().hide()
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # mehrere markieren (Strg/Umschalt) – für „Ausgewählte als ICS-Datei speichern“
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl.customContextMenuRequested.connect(self._context_menu)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tbl.doubleClicked.connect(lambda _i: self.new_log())
        self.tbl.itemSelectionChanged.connect(self._update_buttons)
        lay.addWidget(self.tbl, 1)
        lay.addWidget(self.empty)

        self.remind = QCheckBox(tr("Beim Programmstart an Contests erinnern, die laufen oder in "
                                   "den nächsten {n} Tagen beginnen", n=cc.REMIND_DAYS))
        self.remind.setChecked(bool(cfg.get("calendar_remind", True)))
        self.remind.toggled.connect(self._remind_changed)
        lay.addWidget(self.remind)

        brow = QHBoxLayout()
        self.btn_log = QPushButton(tr("Log anlegen …"))
        self.btn_log.setToolTip(tr("Neues Log für den gewählten Contest (auch per Doppelklick)"))
        self.btn_log.clicked.connect(self.new_log)
        self.btn_rules = QPushButton(tr("Ausschreibung öffnen"))
        self.btn_rules.clicked.connect(self.open_rules)
        self.btn_ics = QPushButton(tr("Als Kalenderdatei speichern …"))
        self.btn_ics.setToolTip(tr("Termine als .ics-Datei für Thunderbird, Google- oder "
                                   "Handy-Kalender (diesen und nächsten Termin je Contest, "
                                   "mit Filter)"))
        self.btn_ics.clicked.connect(lambda _c=False: self.export_ics())
        # 0.10.15: Termin per QR-Code aufs Handy
        self.btn_qr = QPushButton(tr("QR-Code fürs Handy …"))
        self.btn_qr.setToolTip(tr("Den gewählten Contest mit der Handy-Kamera in den Kalender "
                                  "übernehmen – ohne Datei"))
        self.btn_qr.clicked.connect(lambda _c=False: self.show_qr())
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.accept)
        for b in (self.btn_log, self.btn_rules, self.btn_qr, self.btn_ics):
            brow.addWidget(b)
        brow.addStretch(1)
        brow.addWidget(close)
        lay.addLayout(brow)

        self.resize(980, 620)
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(30_000)               # „Wann“ und „läuft“ aktuell halten

    # ------------------------------------------------------------------ Daten
    def now(self) -> datetime:
        return self._now or utc_now()

    def kinds(self) -> set:
        return {k for k, chk in self.filters.items() if chk.isChecked()}

    def refresh(self) -> None:
        now = self.now()
        sel = self.selected()
        kinds = self.kinds()
        q = self.search.text()
        self.rows = [x for x in cc.filtered(cc.entries(self.contests, now), kinds)
                     if matches(q, x.name, x.cid)]
        self.chk_all.setChecked(len(kinds) == len(cc.KINDS))
        self.empty.setVisible(not kinds)
        self.tbl.setRowCount(len(self.rows))
        bold = QFont(self.tbl.font())
        bold.setBold(True)
        for r, x in enumerate(self.rows):
            vals = (local_text(x.start), f"{date_text(x.start)}  {x.start:%H:%M}",
                    duration_text(x.hours), x.name, kinds_text(x.kinds), cc.status(x, now))
            run = x.running(now)
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c in (2, 4):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if run:
                    it.setFont(bold)
                    it.setForeground(QBrush(QColor(GREEN)))
                if c == 3 and x.rules_url:
                    it.setToolTip(x.rules_url)
                self.tbl.setItem(r, c, it)
        if sel is not None:
            for r, x in enumerate(self.rows):
                if (x.cid, x.start) == (sel.cid, sel.start):
                    self.tbl.selectRow(r)
                    break
        self._update_buttons()

    def selected(self) -> cc.Entry | None:
        """Der angeklickte (aktuelle) Contest – für „Log anlegen“ und „Ausschreibung“."""
        many = self.selected_all()
        if not many:
            return None
        cur = self.tbl.currentRow()
        if 0 <= cur < len(self.rows) and self.rows[cur] in many:
            return self.rows[cur]
        return many[0]

    def selected_all(self) -> list[cc.Entry]:
        sm = self.tbl.selectionModel()
        rows = sorted(i.row() for i in sm.selectedRows()) if sm else []
        return [self.rows[r] for r in rows if r < len(self.rows)]

    def _update_buttons(self) -> None:
        x = self.selected()
        self.btn_log.setEnabled(x is not None and self.on_new_log is not None)
        self.btn_rules.setEnabled(bool(x and x.rules_url))
        self.btn_qr.setEnabled(x is not None)
        self.btn_ics.setEnabled(bool(self.rows))

    def _all_clicked(self, on: bool) -> None:
        for chk in self.filters.values():
            chk.blockSignals(True)
            chk.setChecked(on)
            chk.blockSignals(False)
        self._filter_changed()

    def _filter_changed(self) -> None:
        self.cfg["calendar_filter"] = [k for k in cc.KINDS if k in self.kinds()]
        self.cfg["calendar_kinds_known"] = list(cc.KINDS)
        self._save()
        self.refresh()

    def _remind_changed(self, on: bool) -> None:
        self.cfg["calendar_remind"] = bool(on)
        self._save()

    def _save(self) -> None:
        if self.on_change:
            self.on_change()

    # ------------------------------------------------------------------ Knöpfe
    def new_log(self) -> None:
        x = self.selected()
        if x is None or self.on_new_log is None:
            return
        self.accept()                          # erst schließen, dann der Log-Dialog
        self.on_new_log(x.cid, x.start.year)

    def open_rules(self) -> None:
        x = self.selected()
        if x and x.rules_url:
            QDesktopServices.openUrl(QUrl(x.rules_url))

    def _context_menu(self, pos) -> None:
        """Rechtsklick: markierte Contests (oder den angeklickten) als ICS-Datei."""
        row = self.tbl.rowAt(pos.y())
        if row < 0:
            return
        if row not in {i.row() for i in self.tbl.selectionModel().selectedRows()}:
            self.tbl.selectRow(row)                  # Klick außerhalb der Auswahl: nur diese
        chosen = self.selected_all()
        if not chosen:
            return
        menu = QMenu(self)
        text = tr("Als ICS-Datei speichern …") if len(chosen) == 1 else \
            tr("Ausgewählte ({n}) als ICS-Datei speichern …", n=len(chosen))
        act = menu.addAction(text)
        act.triggered.connect(lambda _c=False: self.export_ics(chosen))
        if len(chosen) == 1:
            qr = menu.addAction(tr("QR-Code fürs Handy …"))
            qr.triggered.connect(lambda _c=False: self.show_qr(chosen[0]))
        self._exec_menu(menu, self.tbl.viewport().mapToGlobal(pos))

    def _exec_menu(self, menu, where) -> None:
        menu.exec(where)

    def show_qr(self, entry=None) -> None:
        """Den gewählten Contest als QR-Code zeigen (0.10.15)."""
        from .qr_dialog import QrDialog
        x = entry or self.selected()
        if x is None:
            return
        when = f"{local_text(x.start)} · {duration_text(x.hours)}"
        self._qr = QrDialog(x, when, self.cfg, self._save, self)
        self._qr.exec()

    def export_ics(self, only: list | None = None) -> None:
        """Alle angezeigten Contests (Filter und Suche) – oder nur „only“ (Rechtsklick)."""
        now = self.now()
        items = cc.filtered(cc.entries(self.contests, now, count=2), self.kinds())
        if only is not None:
            ids = {x.cid for x in only}
            items = [x for x in cc.entries(self.contests, now, count=2) if x.cid in ids]
        elif self.search.text().strip():
            ids = {x.cid for x in self.rows}
            items = [x for x in items if x.cid in ids]
        if not items:
            return
        if only is not None and len({x.cid for x in only}) == 1:
            slug = "".join(ch if ch.isalnum() else "-" for ch in fold(only[0].name)).strip("-")
            name = "-".join(t for t in slug.split("-") if t) + ".ics"
        elif only is not None:
            name = tr("contests-auswahl.ics")
        else:
            name = tr("contests-gogoham.ics")
        path = self._save_path(str(Path.home() / name))
        if not path:
            return
        if not path.lower().endswith(".ics"):
            path += ".ics"
        try:
            alarm = int(self.cfg.get("calendar_alarm", cc.ALARM_DEFAULT))
            Path(path).write_text(cc.to_ics(items, now, alarm=alarm), encoding="utf-8",
                                  newline="")
        except OSError as e:
            QMessageBox.warning(self, tr("Kalenderdatei"),
                                tr("Speichern ging nicht: {e}", e=e))
            return
        self._saved(len(items), path)

    def _save_path(self, start: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, tr("Kalenderdatei speichern"), start,
                                              tr("iCalendar (*.ics)"))
        return path

    def _saved(self, n: int, path: str) -> None:
        QMessageBox.information(self, tr("Kalenderdatei"),
                                tr("{n} Termine gespeichert:\n{path}\n\nIn Thunderbird, Google- "
                                   "oder Handy-Kalender über „Importieren“ einlesen. Erneutes "
                                   "Importieren aktualisiert die Termine.",
                                   n=n, path=path))

