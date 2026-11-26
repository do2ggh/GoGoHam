"""Fenster „Call-History“ (ab 0.9.1): nachsehen, korrigieren, vergessen, alte Logs lernen."""

from __future__ import annotations

from pathlib import Path

from ..i18n import tr

from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from .. import callhistory as chmod

MAX_ROWS = 500


class CallHistoryDialog(QDialog):
    def __init__(self, history: chmod.CallHistory, cty=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Call-History"))
        self.history, self.cty = history, cty
        self.resize(640, 480)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("Rufzeichen:")))
        self.ed = QLineEdit()
        self.ed.setPlaceholderText(tr("Anfang des Rufzeichens, z. B. DL1"))
        self.ed.textChanged.connect(self.refresh)
        top.addWidget(self.ed)
        lay.addLayout(top)
        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels([tr("Rufzeichen"), tr("Angabe"), tr("Wert"),
                                            tr("Datum"), tr("Quelle")])
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl.doubleClicked.connect(lambda _i: self.change_value())
        lay.addWidget(self.tbl)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        row = QHBoxLayout()
        for text, slot in ((tr("Wert ändern …"), self.change_value),
                           (tr("Angabe vergessen"), self.forget_value),
                           (tr("Altes Log einlesen …"), self.learn_log),
                           (tr("N1MM-Datei importieren …"), self.import_n1mm)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        self.base_btn = QPushButton()
        self.base_btn.clicked.connect(self.toggle_base)
        row2.addWidget(self.base_btn)
        row2.addStretch(1)
        lay.addLayout(row2)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        help_btn = bb.addButton("?", QDialogButtonBox.ButtonRole.HelpRole)
        help_btn.setToolTip(tr("Hilfe zu diesem Fenster"))
        help_btn.clicked.connect(self._help)
        lay.addWidget(bb)
        self.refresh()

    def _help(self) -> None:
        from .dialogs import show_help
        show_help(self, "callhistory")

    # ------------------------------------------------------------ Tabelle
    def rows(self) -> list[tuple[str, str, str, str, str]]:
        """(Rufzeichen, Schlüssel, Wert, Datum, Quelle) passend zum Suchfeld."""
        pre = self.ed.text().strip().upper()
        out = []
        for call in self.history.calls():
            if pre and not call.startswith(pre):
                continue
            e = self.history.get(call)
            for key in chmod.KEYS:
                if key in e.values:
                    v, t, src = e.values[key]
                    out.append((call, key, v, t[:10], src))
            if len(out) >= MAX_ROWS:
                break
        return out

    def refresh(self) -> None:
        self.base_btn.setText(tr("Grundstock entfernen") if self.history.base_enabled()
                              else tr("Grundstock wieder einlesen"))
        rows = self.rows()
        self._rows = rows
        self.tbl.setRowCount(len(rows))
        for i, (call, key, v, date, src) in enumerate(rows):
            for j, text in enumerate((call, chmod.key_label(key), v, date,
                                      chmod.source_label(src))):
                self.tbl.setItem(i, j, QTableWidgetItem(text))
        txt = tr("Bekannt sind {n} Rufzeichen. Neue QSOs lernt GoGoHam von selbst dazu.",
                 n=len(self.history))
        if len(rows) >= MAX_ROWS:
            txt += " " + tr("Es werden nur die ersten {n} Zeilen gezeigt – bitte "
                            "Rufzeichen eingeben.", n=MAX_ROWS)
        self.info.setText(txt)

    def _selected(self):
        r = self.tbl.currentRow()
        return self._rows[r] if 0 <= r < len(self._rows) else None

    # ------------------------------------------------------------ Knöpfe
    def change_value(self) -> None:
        sel = self._selected()
        if not sel:
            return
        call, key, v = sel[:3]
        text, ok = QInputDialog.getText(self, tr("Wert ändern"),
                                        tr("{what} von {call}:", what=chmod.key_label(key),
                                           call=call), text=v)
        if ok and text.strip() and text.strip() != v:
            self.history.set_value(call, key, text)
            self.refresh()

    def forget_value(self) -> None:
        sel = self._selected()
        if not sel:
            return
        call, key, v = sel[:3]
        if QMessageBox.question(self, tr("Angabe vergessen"),
                                tr("{what} „{value}“ von {call} vergessen?",
                                   what=chmod.key_label(key), value=v, call=call)) \
                == QMessageBox.StandardButton.Yes:
            self.history.set_value(call, key, "")
            self.refresh()

    def learn_log(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("Altes Log einlesen"), str(Path.home()),
            tr("Logs (*.cbr *.CBR *.log *.LOG *.ggh);;Alle Dateien (*)"))
        if not paths:
            return
        before = len(self.history)
        lines = []
        for p in paths:
            try:
                n, learned, name = self.history.learn_file(p, self.cty)
                lines.append(tr("{file}: {n} QSOs ({name}), {learned} Angaben gelernt",
                                file=Path(p).name, n=n, name=name or "?", learned=learned))
            except (ValueError, OSError) as e:
                lines.append(f"{Path(p).name}: {e}")
        lines.append(tr("Neu bekannt: {n} Rufzeichen.", n=len(self.history) - before))
        QMessageBox.information(self, tr("Altes Log einlesen"), "\n".join(lines))
        self.refresh()

    def import_n1mm(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Call-History importieren"),
                                              str(Path.home() / "Downloads"),
                                              tr("Call-History (*.txt *.csv);;Alle Dateien (*)"))
        if not path:
            return
        try:
            target = chmod.import_file(path)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, tr("Call-History"), str(e))
            return
        self.history.load_n1mm(target)
        self.refresh()

    def toggle_base(self) -> None:
        if self.history.base_enabled():
            if QMessageBox.question(
                    self, tr("Grundstock entfernen"),
                    tr("Den mitgelieferten Grundstock entfernen? Deine eigenen QSOs, eingelesene "
                       "Logs und N1MM-Dateien bleiben. Du kannst ihn jederzeit wieder einlesen.")) \
                    != QMessageBox.StandardButton.Yes:
                return
            self.history.set_base_enabled(False)
        else:
            self.history.set_base_enabled(True)
        self.refresh()
