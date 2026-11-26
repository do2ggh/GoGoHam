"""QTC-Fenster (WAE DX Contest).

QtcDialog (ab 0.8.5): diktierte QTCs schnell mitschreiben – hier wird nichts gesendet.
Bedienung nur mit der Tastatur: Serie eintippen, Enter, dann je QTC eine Zeile
„1307 DL1ABC 042“ + Enter. Enter in einer leeren Zeile = Fertig.

QtcGiveDialog (ab 0.9.4): QTCs geben (eigene Station außerhalb Europas). GoGoHam wählt
die QSOs aus; in CW sendet Enter Zeile für Zeile über den Keyer – nur auf Tastendruck.
In SSB liest man selbst vor; die Zeile, die dran ist, steht groß im Fenster und kann
auf Wunsch über die Soundkarte angesagt werden (nie ans Funkgerät).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from .. import qtc as qtcmod
from ..bands import band_label
from ..i18n import tr

GREEN, RED, ORANGE, BLUE = "#1b8a3a", "#c62828", "#e08a00", "#1565c0"


def _no_default(btn: QPushButton) -> QPushButton:
    """Enter in den Eingabezeilen soll keine Schaltfläche auslösen."""
    btn.setAutoDefault(False)
    btn.setDefault(False)
    return btn


class QtcDialog(QDialog):
    """Eine QTC-Serie empfangen. Ergebnis: self.result (Liste von Qtc, ohne Zeit/Band)."""

    def __init__(self, contest, mycall: str, qtcs: list, sender: str, worked: set[str],
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("QTC empfangen"))
        self.contest = contest
        self.mycall = (mycall or "").upper()
        self.qtcs = list(qtcs)
        self.worked = {c.upper() for c in worked}
        self.limit = int((contest.qtc or {}).get("max_per_station", qtcmod.MAX_PER_STATION))
        self.result: list[qtcmod.Qtc] = []

        self.ed_sender = QLineEdit(sender.upper())
        self.ed_sender.setPlaceholderText(tr("Rufzeichen"))
        self.ed_series = QLineEdit()
        self.ed_series.setPlaceholderText(tr("z. B. 3/5"))
        self.ed_series.setMaximumWidth(110)
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("Von:")))
        top.addWidget(self.ed_sender, 1)
        top.addWidget(QLabel(tr("Serie:")))
        top.addWidget(self.ed_series)
        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)

        grid = QGridLayout()
        self.rows: list[QLineEdit] = []
        self.marks: list[QLabel] = []
        for i in range(self.limit):
            num = QLabel(f"{i + 1}.")
            ed = QLineEdit()
            ed.setPlaceholderText(tr("1307 DL1ABC 042") if i == 0 else "")
            mark = QLabel("")
            mark.setWordWrap(True)
            ed.textChanged.connect(lambda _t, n=i: self._check_row(n))
            ed.returnPressed.connect(lambda n=i: self._row_enter(n))
            grid.addWidget(num, i, 0)
            grid.addWidget(ed, i, 1)
            grid.addWidget(mark, i, 2)
            self.rows.append(ed)
            self.marks.append(mark)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 2)

        hint = QLabel(tr("Je QTC eine Zeile: Uhrzeit, Rufzeichen, Nummer – dann Enter. "
                         "Enter in einer leeren Zeile = Fertig. Esc = Abbrechen."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#777777;")
        self.btn_ok = _no_default(QPushButton(tr("Fertig")))
        self.btn_ok.clicked.connect(self.finish)
        btn_cancel = _no_default(QPushButton(tr("Abbrechen")))
        btn_cancel.clicked.connect(self.reject)
        btn_help = _no_default(QPushButton("?"))
        btn_help.setToolTip(tr("Hilfe zu diesem Fenster"))
        btn_help.clicked.connect(self._help)
        bl = QHBoxLayout()
        bl.addWidget(btn_help)
        bl.addStretch(1)
        bl.addWidget(btn_cancel)
        bl.addWidget(self.btn_ok)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.lbl_info)
        lay.addLayout(grid)
        lay.addWidget(hint)
        lay.addLayout(bl)
        self.resize(640, self.sizeHint().height())

        self.ed_sender.textChanged.connect(self._sender_changed)
        self.ed_sender.returnPressed.connect(lambda: self.ed_series.setFocus())
        self.ed_series.returnPressed.connect(lambda: self._focus_row(0))
        self._sender_changed()
        (self.ed_series if sender else self.ed_sender).setFocus()

    def _help(self) -> None:
        from .dialogs import show_help
        show_help(self, "qtc")

    # ------------------------------------------------------------ Prüfung
    def sender(self) -> str:
        return self.ed_sender.text().strip().upper()

    def remaining(self) -> int:
        return qtcmod.remaining(self.qtcs, self.sender(), self.limit,
                                self.contest.qtc_both_ways())

    def sender_problem(self) -> str:
        s = self.sender()
        if not s:
            return tr("Rufzeichen der Station eingeben, die die QTCs gibt")
        p = self.contest.qtc_sender_problem(self.contest.lookup(s))
        if p:
            return p
        if self.remaining() == 0:
            return tr("Von {sender} sind schon {limit} QTCs da – mehr sind nicht erlaubt",
                      sender=s, limit=self.limit)
        return ""

    def _sender_changed(self) -> None:
        s = self.sender()
        prob = self.sender_problem()
        n = self.remaining()
        for i, ed in enumerate(self.rows):
            ed.setEnabled(not prob and i < n)
        if prob:
            self.lbl_info.setText(prob)
            self.lbl_info.setStyleSheet(f"color:{RED}; font-weight:bold;")
        else:
            txt = tr("Noch {n} von {limit} QTCs von {sender} möglich", n=n, limit=self.limit,
                     sender=s)
            hint = qtcmod.next_series_hint(self.qtcs, s)
            if hint:
                txt += tr(" · zuletzt notierte Serie: {last}", last=hint - 1)
            style = ""
            if s not in self.worked:
                txt += "\n" + tr("⚠ Mit {sender} ist noch kein QSO im Log", sender=s)
                style = f"color:{ORANGE}; font-weight:bold;"
            self.lbl_info.setText(txt)
            self.lbl_info.setStyleSheet(style)
        for i in range(len(self.rows)):
            self._check_row(i)

    def _entries(self, upto: int | None = None) -> list[tuple[str, str, str]]:
        out = []
        for ed in self.rows[:upto]:
            e, err = qtcmod.parse_line(ed.text())
            if e and not err:
                out.append(e)
        return out

    def row_problem(self, i: int) -> tuple[tuple[str, str, str] | None, str]:
        e, err = qtcmod.parse_line(self.rows[i].text())
        if err or e is None:
            return e, err
        return e, qtcmod.line_problem(e, self.sender(), self.mycall, self.qtcs,
                                      self._entries(i))

    def _check_row(self, i: int) -> None:
        e, err = self.row_problem(i)
        mark = self.marks[i]
        if not self.rows[i].text().strip():
            mark.setText("")
        elif err:
            mark.setText(err)
            mark.setStyleSheet(f"color:{RED};")
        else:
            mark.setText("✔")
            mark.setStyleSheet(f"color:{GREEN}; font-weight:bold;")

    # ------------------------------------------------------------ Tastatur
    def _focus_row(self, i: int) -> None:
        if i < len(self.rows) and self.rows[i].isEnabled():
            self.rows[i].setFocus()
        else:
            self.finish()

    def _row_enter(self, i: int) -> None:
        if not self.rows[i].text().strip():
            self.finish()
            return
        _e, err = self.row_problem(i)
        if err:
            return                      # Zeile bleibt, Fehler steht daneben
        self._focus_row(i + 1)

    def reject(self) -> None:
        if any(ed.text().strip() for ed in self.rows):
            r = QMessageBox.question(self, tr("QTC empfangen"),
                                     tr("Die eingetragenen QTCs verwerfen?"))
            if r != QMessageBox.StandardButton.Yes:
                return
        super().reject()

    def finish(self) -> None:
        prob = self.sender_problem()
        if prob:
            self.ed_sender.setFocus()
            return
        ser = qtcmod.parse_series(self.ed_series.text())
        if ser is None:
            self.lbl_info.setText(tr("Serie eingeben, wie angesagt – z. B. 3/5 (Serie 3 mit 5 QTCs)"))
            self.lbl_info.setStyleSheet(f"color:{RED}; font-weight:bold;")
            self.ed_series.setFocus()
            return
        entries = []
        for i, ed in enumerate(self.rows):
            if not ed.text().strip():
                continue
            e, err = self.row_problem(i)
            if err:
                ed.setFocus()
                return
            entries.append(e)
        if not entries:
            self.lbl_info.setText(tr("Noch keine QTCs eingetragen"))
            self.lbl_info.setStyleSheet(f"color:{RED}; font-weight:bold;")
            if self.rows[0].isEnabled():
                self.rows[0].setFocus()
            return
        series, total = ser
        if total and total != len(entries):
            r = QMessageBox.question(
                self, tr("QTC empfangen"),
                tr("Angesagt waren {total} QTCs, eingetragen sind {n}. Trotzdem speichern?",
                   total=total, n=len(entries)))
            if r != QMessageBox.StandardButton.Yes:
                return
        s = self.sender()
        self.result = [qtcmod.Qtc(sender=s, series=series, total=total or len(entries),
                                  qso_time=t, qso_call=c, qso_nr=n) for t, c, n in entries]
        self.accept()


class QtcGiveDialog(QDialog):
    """Eine QTC-Serie geben. Ergebnis: self.result (bestätigte Qtc, ohne Zeit/Band)."""

    C_USE, C_TIME, C_CALL, C_NR, C_OK = range(5)

    def __init__(self, contest, mycall: str, qtcs: list, qsos: list, receiver: str,
                 cw: bool, send=None, stop=None, say=None, phonetic: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("QTC geben"))
        self.contest = contest
        self.mycall = (mycall or "").upper()
        self.qtcs = list(qtcs)
        self.qsos = list(qsos)
        self.worked = {q.call.upper() for q in qsos}
        self.cw = cw
        self._send, self._stop, self._say = send, stop, say
        self.phonetic = phonetic
        self.limit = int((contest.qtc or {}).get("max_per_station", qtcmod.MAX_PER_STATION))
        self.series = qtcmod.next_own_series(self.qtcs)
        self.result: list[qtcmod.Qtc] = []
        self.cands: list = []
        self.entries: list = []          # die gewählten QSOs, sobald die Serie läuft
        self.confirmed: list[bool] = []
        self.pos = -2                    # -2 = noch nicht begonnen, -1 = Serie angesagt

        self.ed_recv = QLineEdit(receiver.upper())
        self.ed_recv.setPlaceholderText(tr("Rufzeichen"))
        self.lbl_series = QLabel("")
        self.lbl_series.setStyleSheet("font-weight:bold;")
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("An:")))
        top.addWidget(self.ed_recv, 1)
        top.addWidget(self.lbl_series)
        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)

        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels(
            (tr("Mitgeben"), tr("QSO-Zeit"), tr("Rufzeichen"), tr("Nr"), tr("Bestätigt")))
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.itemChanged.connect(self._item_changed)

        self.lbl_now = QLabel("")
        self.lbl_now.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_now.setStyleSheet(f"font-size:22pt; font-weight:bold; color:{BLUE};")
        self.lbl_now.setWordWrap(True)

        if cw:
            txt = tr("Enter = Serie ansagen, danach nächste Zeile senden (die vorige gilt damit "
                     "als bestätigt) · F2 = noch einmal senden · Esc = Abbrechen. "
                     "Gesendet wird nur auf Tastendruck.")
        else:
            txt = tr("Lies die groß angezeigte Zeile vor. Enter = nächste Zeile (die vorige gilt "
                     "damit als bestätigt) · F2 = noch einmal ansagen · Esc = Abbrechen.")
        hint = QLabel(txt)
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#777777;")
        self.btn_ok = _no_default(QPushButton(tr("Fertig")))
        self.btn_ok.clicked.connect(self.finish)
        btn_cancel = _no_default(QPushButton(tr("Abbrechen")))
        btn_cancel.clicked.connect(self.reject)
        btn_help = _no_default(QPushButton("?"))
        btn_help.setToolTip(tr("Hilfe zu diesem Fenster"))
        btn_help.clicked.connect(self._help)
        bl = QHBoxLayout()
        bl.addWidget(btn_help)
        bl.addStretch(1)
        bl.addWidget(btn_cancel)
        bl.addWidget(self.btn_ok)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.lbl_info)
        lay.addWidget(self.tbl, 1)
        lay.addWidget(self.lbl_now)
        lay.addWidget(hint)
        lay.addLayout(bl)
        self.resize(620, 560)

        for key, fn in (("Return", self.enter), ("Enter", self.enter), ("F2", self.repeat)):
            QShortcut(QKeySequence(key), self, activated=fn)
        self.ed_recv.textChanged.connect(self._recv_changed)
        self._recv_changed()
        if receiver:
            self.tbl.setFocus()

    def _help(self) -> None:
        from .dialogs import show_help
        show_help(self, "qtc-give")

    # ------------------------------------------------------------ Auswahl
    def receiver(self) -> str:
        return self.ed_recv.text().strip().upper()

    def remaining(self) -> int:
        return qtcmod.give_remaining(self.qtcs, self.receiver(), self.limit,
                                     self.contest.qtc_both_ways())

    def receiver_problem(self) -> str:
        return qtcmod.receiver_problem(self.contest, self.receiver(), self.mycall, self.qtcs)

    def _recv_changed(self) -> None:
        if self.pos != -2:
            return
        r = self.receiver()
        prob = self.receiver_problem()
        self.cands = [] if prob else qtcmod.give_candidates(
            self.qsos, self.qtcs, r, getattr(self.contest, "dupe_key", None))
        if not prob and not self.cands:
            prob = tr("Keine QSOs mehr, die sich an {receiver} melden lassen", receiver=r)
        n = min(self.remaining(), len(self.cands))
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(len(self.cands))
        for row, q in enumerate(self.cands):
            use = QTableWidgetItem("")
            use.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            use.setCheckState(Qt.CheckState.Checked if row < n else Qt.CheckState.Unchecked)
            self.tbl.setItem(row, self.C_USE, use)
            for col, v in zip((self.C_TIME, self.C_CALL, self.C_NR), qtcmod.give_line(q)):
                self.tbl.setItem(row, col, QTableWidgetItem(v))
            self.tbl.setItem(row, self.C_OK, QTableWidgetItem(""))
        self.tbl.blockSignals(False)
        self.tbl.resizeColumnsToContents()
        if prob:
            self.lbl_info.setText(prob)
            self.lbl_info.setStyleSheet(f"color:{RED}; font-weight:bold;")
        else:
            txt = tr("Noch {n} von {limit} QTCs an {receiver} möglich", n=self.remaining(),
                     limit=self.limit, receiver=r)
            style = ""
            if r not in self.worked:
                txt += "\n" + tr("⚠ Mit {receiver} ist noch kein QSO im Log", receiver=r)
                style = f"color:{ORANGE}; font-weight:bold;"
            self.lbl_info.setText(txt)
            self.lbl_info.setStyleSheet(style)
        self._update_series()

    def chosen(self) -> list:
        return [q for row, q in enumerate(self.cands)
                if self.tbl.item(row, self.C_USE).checkState() == Qt.CheckState.Checked]

    def _item_changed(self, it: QTableWidgetItem) -> None:
        if it.column() == self.C_USE and self.pos == -2:
            if it.checkState() == Qt.CheckState.Checked and len(self.chosen()) > self.remaining():
                self.tbl.blockSignals(True)
                it.setCheckState(Qt.CheckState.Unchecked)
                self.tbl.blockSignals(False)
                self.lbl_info.setText(tr("Mehr als {n} QTCs gehen an {receiver} nicht",
                                         n=self.remaining(), receiver=self.receiver()))
                self.lbl_info.setStyleSheet(f"color:{RED}; font-weight:bold;")
            self._update_series()
        elif it.column() == self.C_OK and self.pos != -2:
            row = self._entry_row(it.row())
            if row is not None and row <= self.pos:
                self.confirmed[row] = it.checkState() == Qt.CheckState.Checked

    def _update_series(self) -> None:
        n = len(self.entries) if self.pos != -2 else len(self.chosen())
        self.lbl_series.setText(qtcmod.cw_header(self.series, n) if n else "")
        if self.pos == -2:
            h = qtcmod.cw_header(self.series, n)
            txt = (tr("Enter = {header} senden", header=h) if self.cw else
                   tr("Enter = los geht's mit {header}", header=h))
            self.lbl_now.setText(txt if n and not self.receiver_problem() else "")

    def _entry_row(self, table_row: int) -> int | None:
        q = self.cands[table_row]
        return next((i for i, e in enumerate(self.entries) if e is q), None)

    # ------------------------------------------------------------ Geben
    def _line(self, i: int) -> str:
        return qtcmod.cw_line(qtcmod.give_line(self.entries[i]))

    def _give(self) -> None:
        """Das, was gerade dran ist, groß zeigen und senden (CW) bzw. ansagen (SSB)."""
        if self.pos == -1:
            text = qtcmod.cw_header(self.series, len(self.entries))
            spoken = tr("Q T C {series} Strich {total}", series=self.series,
                        total=len(self.entries))
        else:
            text = self._line(self.pos)
            t, call, nr = qtcmod.give_line(self.entries[self.pos])
            from ..speech import spell_call
            spoken = ", ".join((" ".join(t), spell_call(call, self.phonetic),
                                " ".join(nr)))
            row = self.cands.index(self.entries[self.pos])
            self.tbl.selectRow(row)
            self.tbl.item(row, self.C_OK).setText(tr("gegeben"))
        self.lbl_now.setText(text)
        if self.cw:
            if self._send:
                self._send(text)
        elif self._say:
            self._say(spoken)

    def start(self) -> bool:
        if self.receiver_problem() or not self.chosen():
            return False
        self.entries = self.chosen()
        self.confirmed = [False] * len(self.entries)
        self.pos = -1
        self.ed_recv.setReadOnly(True)
        self.tbl.blockSignals(True)
        for row in range(len(self.cands)):
            it = self.tbl.item(row, self.C_USE)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        self.tbl.blockSignals(False)
        self._update_series()
        self._give()
        return True

    def _set_confirmed(self, i: int, on: bool = True) -> None:
        self.confirmed[i] = on
        row = self.cands.index(self.entries[i])
        it = self.tbl.item(row, self.C_OK)
        self.tbl.blockSignals(True)
        it.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        it.setText("")
        self.tbl.blockSignals(False)

    def enter(self) -> None:
        if self.ed_recv.hasFocus() and self.pos == -2:
            self.tbl.setFocus()
            return
        if self.pos == -2:
            self.start()
            return
        if self.pos >= 0:
            self._set_confirmed(self.pos)
        self.pos += 1
        if self.pos >= len(self.entries):
            self.pos = len(self.entries) - 1
            self.finish()
            return
        self._give()

    def repeat(self) -> None:
        if self.pos != -2:
            self._give()

    def finish(self) -> None:
        if self.pos == -2:
            if not self.start():
                return
            return
        i = self.pos
        if 0 <= i < len(self.entries) and not self.confirmed[i]:
            r = QMessageBox.question(self, tr("QTC geben"), tr(
                "Hat {receiver} die Zeile „{line}“ bestätigt?", receiver=self.receiver(),
                line=self._line(i)))
            if r == QMessageBox.StandardButton.Yes:
                self._set_confirmed(i)
        self._make_result()
        self.accept()

    def _make_result(self) -> None:
        total = len(self.entries)
        self.result = []
        for q, ok in zip(self.entries, self.confirmed):
            if ok:
                t, call, nr = qtcmod.give_line(q)
                self.result.append(qtcmod.Qtc(sender=self.mycall, receiver=self.receiver(),
                                              series=self.series, total=total, qso_time=t,
                                              qso_call=call, qso_nr=nr, qso_id=q.id or 0))

    def reject(self) -> None:
        if self._stop and self.cw and self.pos != -2:
            self._stop()
        n = sum(self.confirmed)
        if n:
            r = QMessageBox.question(
                self, tr("QTC geben"),
                tr("{n} QTCs hat {receiver} schon bestätigt. Speichern?", n=n,
                   receiver=self.receiver()),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                return
            if r == QMessageBox.StandardButton.Yes:
                self._make_result()
                self.accept()
                return
        super().reject()


class QtcListDialog(QDialog):
    """Alle QTCs ansehen (empfangene und gegebene), korrigieren oder löschen."""

    COLS = ("time", "band", "sender", "receiver", "series", "qso_time", "qso_call", "qso_nr")
    EDITABLE = {"series", "qso_time", "qso_call", "qso_nr"}

    def __init__(self, qtcs: list, parent=None, mycall: str = ""):
        super().__init__(parent)
        self.setWindowTitle(tr("QTCs"))
        self.qtcs = list(qtcs)
        self.deleted: list[int] = []
        self.changed: list[qtcmod.Qtc] = []
        heads = (tr("Zeit (UTC)"), tr("Band"), tr("Von"), tr("An"), tr("Serie"), tr("QSO-Zeit"),
                 tr("Rufzeichen"), tr("Nr"))
        self.tbl = QTableWidget(len(self.qtcs), len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(heads)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for r, q in enumerate(self.qtcs):
            vals = (q.time, band_label(q.band), q.sender, q.receiver or (mycall or "").upper(),
                    f"{q.series}/{q.total}", q.qso_time,
                    q.qso_call, q.qso_nr)
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if self.COLS[c] not in self.EDITABLE:
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.tbl.setItem(r, c, it)
        self.tbl.resizeColumnsToContents()
        self.lbl = QLabel(tr("{n} QTCs · Serie, Zeit, Rufzeichen und Nummer lassen sich per "
                             "Doppelklick ändern.", n=len(self.qtcs)))
        self.lbl.setWordWrap(True)
        btn_del = _no_default(QPushButton(tr("Markierte löschen")))
        btn_del.clicked.connect(self._delete)
        btn_ok = _no_default(QPushButton(tr("OK")))
        btn_ok.clicked.connect(self._ok)
        btn_cancel = _no_default(QPushButton(tr("Abbrechen")))
        btn_cancel.clicked.connect(self.reject)
        bl = QHBoxLayout()
        bl.addWidget(btn_del)
        bl.addStretch(1)
        bl.addWidget(btn_cancel)
        bl.addWidget(btn_ok)
        lay = QVBoxLayout(self)
        lay.addWidget(self.lbl)
        lay.addWidget(self.tbl)
        lay.addLayout(bl)
        self.resize(760, 480)

    def _delete(self) -> None:
        rows = sorted({i.row() for i in self.tbl.selectedIndexes()}, reverse=True)
        if not rows:
            return
        r = QMessageBox.question(self, tr("QTCs"), tr("{n} QTCs löschen?", n=len(rows)))
        if r != QMessageBox.StandardButton.Yes:
            return
        for row in rows:
            q = self.qtcs.pop(row)
            if q.id is not None:
                self.deleted.append(q.id)
            self.tbl.removeRow(row)

    def _ok(self) -> None:
        changed = []
        for r, q in enumerate(self.qtcs):
            cell = lambda c: self.tbl.item(r, self.COLS.index(c)).text().strip()  # noqa: E731
            ser = qtcmod.parse_series(cell("series"))
            e, err = qtcmod.parse_line(f"{cell('qso_time')} {cell('qso_call')} {cell('qso_nr')}")
            if ser is None or err or e is None:
                self.tbl.selectRow(r)
                QMessageBox.warning(self, tr("QTCs"),
                                    tr("Zeile {r}: {err}", r=r + 1,
                                       err=err or tr("Serie bitte als „3/5“ angeben")))
                return
            series, total = ser
            new = (series, total or q.total, *e)
            if new != (q.series, q.total, q.qso_time, q.qso_call, q.qso_nr):
                q.series, q.total, q.qso_time, q.qso_call, q.qso_nr = new
                changed.append(q)
        self.changed = changed
        self.accept()
