"""Dialoge: Log-Einstellungen, Funkgerät, WSJT-X, Makros, QSO bearbeiten."""

from __future__ import annotations

import os

from .. import APP_NAME
from ..i18n import available as _languages, tr

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QGroupBox, QHBoxLayout, QPushButton, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QGridLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QSpinBox, QVBoxLayout)

from ..bands import BAND_NAMES, RIG_MODES
from ..contests import CONTESTS
from ..contests.base import Qso
from ..locator import is_grid, is_grid4, normalize


def _buttons(dlg: QDialog, help_anchor: str = "") -> QDialogButtonBox:
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                          | QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    if help_anchor:
        btn = bb.addButton("?", QDialogButtonBox.ButtonRole.HelpRole)
        btn.setToolTip(tr("Hilfe zu diesem Fenster"))
        btn.clicked.connect(lambda: show_help(dlg, help_anchor))
    return bb


def show_help(parent, anchor: str = "") -> None:
    from .help import HelpDialog
    HelpDialog.open_at(parent, anchor)


def contest_matches(query: str, *fields: str) -> bool:
    """Suche ab dem ersten Buchstaben (0.8.31.2): steckt der Text in Name, Kurzname oder
    Cabrillo-Name? Leerzeichen, Bindestriche und Umlaute zählen nicht."""
    from .calendar_dialog import fold
    q = fold(query).strip()
    if not q:
        return True
    squeeze = lambda t: "".join(ch for ch in t if ch.isalnum())     # noqa: E731
    sq = squeeze(q)
    # je Feld einzeln suchen – sonst passt „iar“ über die Feldgrenze „…digi arrl…“ (0.10.32)
    return any(q in fold(f) or (bool(sq) and sq in squeeze(fold(f))) for f in fields)


class _ContestSearch(QLineEdit):
    """Suchfeld im Fenster „Neues Contest-Log“: Pfeil hoch/runter blättert in der Liste
    darunter, Enter übernimmt den markierten Contest und springt weiter (statt das Fenster zu
    schließen), Esc leert das Feld."""

    def __init__(self, target):
        super().__init__()
        self._target = target

    def keyPressEvent(self, ev):  # noqa: N802
        k = ev.key()
        if k == Qt.Key.Key_Escape and self.text():
            self.clear()
            return
        if k in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            n = self._target.count()
            if n:
                row = self._target.currentRow() + (1 if k == Qt.Key.Key_Down else -1)
                self._target.setCurrentRow(max(0, min(n - 1, row)))
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            nxt = getattr(self, "next_field", None)       # weiter zum eigenen Rufzeichen
            nxt.setFocus() if nxt is not None else self.focusNextChild()
            return
        super().keyPressEvent(ev)


def _combo(items, current: str) -> QComboBox:
    cb = QComboBox()
    cb.addItems(items)
    if current in items:
        cb.setCurrentText(current)
    return cb


MIN_LOG_WIDTH = 640               # Fenster „Neues Contest-Log“ / „Log-Einstellungen“ (0.8.32.1)


class LogSettingsDialog(QDialog):
    """Contest, eigene Station und Cabrillo-Kategorien."""

    def __init__(self, meta: dict, parent=None, new_log: bool = False):
        super().__init__(parent)
        self.setWindowTitle(tr("Neues Contest-Log") if new_log else tr("Log-Einstellungen"))
        # 0.8.32.1: Mindestbreite – sonst bricht der Regelstand um und Zeilen rutschen übereinander
        self.setMinimumWidth(MIN_LOG_WIDTH)
        self.meta = dict(meta)
        form = QFormLayout()

        self.contest = QComboBox()
        # 0.10.21: das freie Log nur, wenn unter Entwicklung eingeschaltet (oder dieses Log es ist)
        from .. import devmode
        from ..contests import is_free
        self._show_free = devmode.enabled("free_log")
        for cid, cls in CONTESTS.items():
            if is_free(cls) and not self._show_free and meta.get("contest") != cid:
                continue
            self.contest.addItem(cls.name, cid)
        idx = self.contest.findData(meta.get("contest", "cqww-ssb"))
        self.contest.setCurrentIndex(max(idx, 0))
        self.contest.setEnabled(new_log)
        self.new_log = new_log
        if new_log:
            # 0.8.31.2: Suchfeld mit Liste darunter – sie zeigt immer alle passenden Contests
            # und wird mit jedem Buchstaben kürzer (die Auswahlbox bleibt intern im Hintergrund)
            from PySide6.QtWidgets import QListWidget
            self.contest_list = QListWidget()
            self.contest_list.setMinimumHeight(170)
            self.contest_list.currentItemChanged.connect(self._list_picked)
            self.search = _ContestSearch(self.contest_list)
            self.search.setPlaceholderText(tr("Name tippen, z. B. IARU oder DARC"))
            self.search.setClearButtonEnabled(True)
            self.search.textChanged.connect(self._filter_contests)
            self.search_hint = QLabel("")
            self.search_hint.setStyleSheet("color:#c62828;")
            self.count_label = QLabel("")             # 0.8.31.3: wie viele Contests es gibt
            hrow = QHBoxLayout()
            hrow.addWidget(self.count_label)
            hrow.addStretch(1)
            hrow.addWidget(self.search_hint)
            box = QVBoxLayout()
            box.addWidget(self.search)
            box.addWidget(self.contest_list)
            box.addLayout(hrow)
            form.addRow(tr("Contest:"), box)
            self._filter_contests("")
        else:
            form.addRow(tr("Contest:"), self.contest)
        self.rules_label = QLabel("")
        self.rules_label.setWordWrap(True)
        # Platz für zwei Zeilen fest einplanen (Qt rechnet umbrechende Texte im Formular zu knapp)
        self.rules_label.setMinimumHeight(2 * self.rules_label.fontMetrics().lineSpacing() + 4)
        self.rules_btn = QPushButton(tr("Ausschreibung öffnen"))
        self.rules_btn.clicked.connect(self.open_rules)
        row = QHBoxLayout()
        row.addWidget(self.rules_label, 1)
        row.addWidget(self.rules_btn)
        form.addRow("", row)
        self.newer_label = QLabel("")
        self.newer_label.setWordWrap(True)
        self.newer_btn = QPushButton(tr("Neuere Regeln übernehmen"))
        self.newer_btn.clicked.connect(self._take_newer)
        row = QHBoxLayout()
        row.addWidget(self.newer_label, 1)
        row.addWidget(self.newer_btn)
        form.addRow("", row)
        self.contest.currentIndexChanged.connect(lambda _i: self._update_rules())
        self.contest.currentIndexChanged.connect(lambda _i: self._update_fields())
        self.form = form
        self._update_rules()

        self.mycall = QLineEdit(meta.get("mycall", ""))
        self.operators = QLineEdit(meta.get("operators", ""))
        self.zone = QSpinBox()
        self.zone.setRange(1, 40)
        self.zone.setValue(int(meta.get("my_zone") or 14))
        self.grid = QLineEdit(meta.get("my_grid", ""))
        self.grid.setPlaceholderText(tr("6-stellig, z. B. JN59me – für Richtung und WW Digi"))
        form.addRow(tr("Eigenes Rufzeichen:"), self.mycall)
        if new_log:
            self.search.next_field = self.mycall
            self.contest_list.itemDoubleClicked.connect(lambda _it: self.mycall.setFocus())
        form.addRow(tr("Operator(en):"), self.operators)
        form.addRow(tr("Eigene CQ-Zone:"), self.zone)
        form.addRow(tr("Eigener Locator:"), self.grid)
        self.power_ex = QLineEdit(meta.get("my_power", ""))
        self.power_ex.setPlaceholderText(tr("ARRL DX: z. B. 100 oder KW – leer = aus „Kategorie Leistung“"))
        self.state = QLineEdit(meta.get("my_state", ""))
        self.state.setPlaceholderText(tr("nur Stationen in USA/Kanada, z. B. CT oder ON – "
                                         "ARRL 160: Section, z. B. EMA"))
        self.itu = QLineEdit(meta.get("my_itu", ""))
        self.itu.setPlaceholderText(tr("IARU HF – leer = aus der Länderdatei (DL: 28); "
                                    "Verbandsstationen: Kürzel, z. B. DARC"))
        self.licyear = QLineEdit(meta.get("my_licyear", ""))
        self.licyear.setPlaceholderText(tr("EU HF – Jahr deiner allerersten Lizenz, z. B. 1982"))
        form.addRow(tr("Leistung im Austausch:"), self.power_ex)
        form.addRow(tr("ITU-Zone / Verband:"), self.itu)
        form.addRow(tr("Jahr der ersten Lizenz:"), self.licyear)
        form.addRow(tr("Eigener State/Provinz/Section:"), self.state)
        self.dok = QLineEdit(meta.get("my_dok", ""))
        self.dok.setPlaceholderText(tr("DARC/VFDB: DOK deines Ortsverbands, z. B. B36 – "
                                       "Nichtmitglieder und Stationen außerhalb DL: leer (= NM)"))
        form.addRow(tr("Eigener DOK:"), self.dok)
        self.oblast = QLineEdit(meta.get("my_oblast", ""))
        self.oblast.setPlaceholderText(tr("Russian DX – nur Stationen in Russland, z. B. MA"))
        form.addRow(tr("Eigener Oblast:"), self.oblast)
        self.iota = QLineEdit(meta.get("my_iota", ""))
        self.iota.setPlaceholderText(tr("IOTA – nur Inselstationen, z. B. EU-005; "
                                        "auf dem Festland leer lassen"))
        form.addRow(tr("Eigene IOTA-Referenz:"), self.iota)
        self.iota_kind = QComboBox()
        self.iota_kind.addItem(tr("Feste Station (Wohnort auf der Insel)"), "")
        self.iota_kind.addItem(tr("DXpedition"), "1")
        self.iota_kind.setCurrentIndex(1 if meta.get("my_iota_dxped") else 0)
        form.addRow(tr("Art der Inselstation:"), self.iota_kind)
        self.iota_island = QLineEdit(meta.get("my_iota_island", ""))
        self.iota_island.setPlaceholderText(tr("IOTA – Name der Insel, z. B. Great Britain; "
                                               "nur für Inselstationen"))
        form.addRow(tr("Name der Insel:"), self.iota_island)
        self.age = QLineEdit(meta.get("my_age", ""))
        self.age.setPlaceholderText(tr("All Asian – dein Alter, z. B. 59; leer = 01 "
                                       "(Alter nicht nennen)"))
        form.addRow(tr("Alter des Operators:"), self.age)
        self.district = QLineEdit(meta.get("my_district", ""))
        self.district.setPlaceholderText(tr("Nur Stationen im Gastgeberland des Contests: dein "
                                            "Kürzel (Provinz, Bezirk, Sektion …)"))
        form.addRow(tr("Eigenes Kürzel (Gastgeberland):"), self.district)
        self.member = QLineEdit(meta.get("my_member", ""))
        self.member.setPlaceholderText(tr("Club-Mitgliedsnummer (AGCW, HSC), z. B. 2583; leer = kein "
                                          "Mitglied"))
        form.addRow(tr("Mitgliedsnummer:"), self.member)
        self.pclass = QComboBox()                # Leistungsklasse (AGCW QRP, QRP-Party; 0.10.23)
        self._pclass_saved = (meta.get("my_class") or "").strip().upper()
        form.addRow(tr("Leistungsklasse:"), self.pclass)
        self.edi_section = QComboBox()
        for key, label in (("SO", tr("Single-OP")), ("MO", tr("Multi-OP")),
                           ("SO-LP", tr("Single-OP, Low Power (bis 100 W, eine Antenne)")),
                           ("MO-LP", tr("Multi-OP, Low Power (bis 100 W, eine Antenne)")),
                           ("6H", tr("6 Stunden")),
                           ("TR", tr("Trainee (Ausbildungsrufzeichen DN1–DN8 oder /T)"))):
            self.edi_section.addItem(label, key)
        i = self.edi_section.findData(meta.get("edi_section", "SO"))
        self.edi_section.setCurrentIndex(max(i, 0))
        form.addRow(tr("UKW-Sektion:"), self.edi_section)
        self.power_w = QLineEdit(meta.get("my_power_w", ""))
        self.power_w.setPlaceholderText(tr("UKW (EDI): Sendeleistung in Watt, z. B. 100"))
        form.addRow(tr("Sendeleistung (Watt):"), self.power_w)
        self.antenna = QLineEdit(meta.get("my_antenna", ""))
        self.antenna.setPlaceholderText(tr("UKW (EDI): Antenne, z. B. 9-Element-Yagi"))
        form.addRow(tr("Antenne:"), self.antenna)
        self._optional = {"zone": self.zone, "power": self.power_ex, "state": self.state,
                          "itu": self.itu, "licyear": self.licyear, "dok": self.dok,
                          "oblast": self.oblast,
                          "iota": (self.iota, self.iota_kind, self.iota_island),
                          "age": self.age, "district": self.district, "member": self.member,
                          "pclass": self.pclass,
                          "edi": (self.edi_section, self.power_w, self.antenna)}
        self.visible_fields: set[str] = set()
        self._update_fields()

        self.cat_operator = _combo(["SINGLE-OP", "MULTI-OP", "CHECKLOG"],
                                   meta.get("cat_operator", "SINGLE-OP"))
        self.cat_band = _combo(["ALL", "160M", "80M", "40M", "20M", "15M", "10M", "6M", "4M",
                                "2M", "432", "1.2G", "2.3G", "3.4G", "5.7G", "10G"],
                               meta.get("cat_band", "ALL"))
        self.cat_power = _combo(["HIGH", "LOW", "QRP"], meta.get("cat_power", "HIGH"))
        self.cat_assisted = _combo(["NON-ASSISTED", "ASSISTED"],
                                   meta.get("cat_assisted", "NON-ASSISTED"))
        # 0.10.2: Sender in Klartext – im Cabrillo-Log steht weiter ONE / TWO / UNLIMITED
        from .. import multiop
        self.cat_transmitter = QComboBox()
        for val, txt in (("ONE", tr("ONE – ein Sender (Single-OP, Multi-Single)")),
                         ("TWO", tr("TWO – Multi-Two")),
                         ("UNLIMITED", tr("UNLIMITED – Multi-Multi"))):
            self.cat_transmitter.addItem(txt, val)
        self.cat_transmitter.setCurrentIndex(max(0, self.cat_transmitter.findData(
            meta.get("cat_transmitter", "ONE"))))
        self.lbl_multi = QLabel("")
        self.lbl_multi.setWordWrap(True)
        self.lbl_multi.setStyleSheet("color:#777777;")
        self._multiop = multiop
        self.cat_operator.currentTextChanged.connect(lambda _t: self._update_multi())
        self.cat_transmitter.currentIndexChanged.connect(lambda _i: self._update_multi())
        self.contest.currentIndexChanged.connect(lambda _i: self._update_multi())
        self._update_multi()
        self.cat_overlay = _combo(["", "CLASSIC", "ROOKIE", "TB-WIRES", "YOUTH",
                                   "NOVICE-TECH", "OVER-50"], meta.get("cat_overlay", ""))
        form.addRow(tr("Kategorie Operator:"), self.cat_operator)
        form.addRow(tr("Kategorie Band:"), self.cat_band)
        form.addRow(tr("Kategorie Leistung:"), self.cat_power)
        form.addRow(tr("Assisted:"), self.cat_assisted)
        form.addRow(tr("Sender:"), self.cat_transmitter)
        form.addRow("", self.lbl_multi)
        form.addRow(tr("Overlay:"), self.cat_overlay)

        self.name = QLineEdit(meta.get("name", ""))
        self.email = QLineEdit(meta.get("email", ""))
        self.club = QLineEdit(meta.get("club", ""))
        self.address = QPlainTextEdit(meta.get("address", ""))
        self.address.setFixedHeight(60)
        self.soapbox = QPlainTextEdit(meta.get("soapbox", ""))
        self.soapbox.setFixedHeight(50)
        form.addRow(tr("Name:"), self.name)
        form.addRow(tr("E-Mail:"), self.email)
        form.addRow(tr("Club:"), self.club)
        form.addRow(tr("Adresse:"), self.address)
        form.addRow(tr("Soapbox:"), self.soapbox)

        self.station_password = ""
        if new_log:                      # Stationslog für mehrere Plätze (ab 0.10)
            self.cb_station = QCheckBox(tr("Stationslog für mehrere Plätze (Multi-OP im "
                                           "Netzwerk)"))
            self.ed_station_pw = QLineEdit()
            self.ed_station_pw.setEchoMode(QLineEdit.EchoMode.Password)
            self.ed_station_pw.setPlaceholderText(tr("Stationskennwort – die anderen Plätze "
                                                     "brauchen es zum Mitmachen"))
            # immer sichtbar, nur ausgegraut – sonst rutschen beim Anklicken die Zeilen
            # übereinander (Fenster wächst nicht mit)
            self.ed_station_pw.setEnabled(False)
            self.cb_station.toggled.connect(self.ed_station_pw.setEnabled)
            # 0.10.2: Stationslog = mehrere Operatoren -> MULTI-OP gleich vorbelegen
            self.cb_station.toggled.connect(
                lambda on: on and self.cat_operator.setCurrentText("MULTI-OP"))
        # 0.10.12: Formular scrollt, wenn der Bildschirm zu niedrig ist – Stationslog-Haken und
        # Knöpfe bleiben darunter immer sichtbar
        from .fitscreen import scroll_wrap
        lay = QVBoxLayout(self)
        lay.addWidget(scroll_wrap(form), 1)
        if new_log:
            lay.addWidget(self.cb_station)
            lay.addWidget(self.ed_station_pw)
        lay.addWidget(_buttons(self, "log"))

    def _update_multi(self) -> None:
        """Unter „Sender“ in Klartext: welche Multi-OP-Kategorie das ist und was gilt."""
        mo = self._multiop
        meta = {"cat_operator": self.cat_operator.currentText(),
                "cat_transmitter": self.cat_transmitter.currentData() or "ONE"}
        cat = mo.category(meta)
        if not cat:
            self.lbl_multi.setText("")
            return
        from ..contests import CONTESTS
        cls = CONTESTS.get(self.contest.currentData())
        r = mo.rules(cls, cat) if cls else {}
        parts = [mo.label(cat)]
        if r.get("dwell"):
            parts.append(tr("{m}-Minuten-Regel", m=r["dwell"].get("minutes", 10)))
        if r.get("per_hour"):
            parts.append(tr("höchstens {n} Bandwechsel je Stunde", n=r["per_hour"]))
        if r.get("serial") == "band":
            parts.append(tr("Nummern je Band"))
        if r.get("tx_id"):
            parts.append(tr("Sendernummer im Log"))
        if cls is not None and not getattr(cls, "multi", None):
            parts.append(tr("für diesen Contest sind in GoGoHam keine Multi-OP-Regeln hinterlegt"))
        self.lbl_multi.setText(" · ".join(parts))

    def _filter_contests(self, text: str) -> None:
        """Liste unter dem Suchfeld: alle Contests, mit jedem Buchstaben weniger (Name,
        Kurzname oder Cabrillo-Name; Leerzeichen, Bindestriche und Umlaute egal). Der gewählte
        Contest bleibt gewählt, solange er passt, sonst der erste Treffer."""
        from PySide6.QtWidgets import QListWidgetItem
        from ..contests import contest_count, is_free
        hits = [(cid, cls) for cid, cls in CONTESTS.items()
                if (self._show_free or not is_free(cls)) and contest_matches(text, cls.name, cid, getattr(cls, "cabrillo_name", "") or "",
                                   tr("Alltag") if is_free(cls) else "")]
        self.search_hint.setText("" if hits else tr("kein Contest gefunden"))
        total = contest_count()                   # das freie Log zählt nicht als Contest
        k = sum(1 for _cid, c in hits if not is_free(c))
        self.count_label.setText(tr("{n} Contests in GoGoHam", n=total)
                                 if k == total else
                                 tr("{k} von {n} Contests", k=k, n=total))
        cur = self.contest.currentData()
        lst = self.contest_list
        lst.blockSignals(True)
        lst.clear()
        self._list_ids = []
        for cid, cls in hits:
            it = QListWidgetItem(cls.name)
            it.setData(Qt.ItemDataRole.UserRole, cid)
            lst.addItem(it)
            self._list_ids.append(cid)
        lst.blockSignals(False)
        if hits:
            row = self._list_ids.index(cur) if cur in self._list_ids else 0
            lst.setCurrentRow(row)
            self._pick(self._list_ids[row])

    def _list_picked(self, item, _prev=None) -> None:
        if item is not None:
            self._pick(item.data(Qt.ItemDataRole.UserRole))

    def _pick(self, cid) -> None:
        """Gewählten Contest in die (interne) Auswahlbox – dort hängen Felder und Regelstand."""
        i = self.contest.findData(cid)
        if i >= 0 and i != self.contest.currentIndex():
            self.contest.setCurrentIndex(i)

    def _contest_cls(self):
        """Regeln dieses Logs: bei einem bestehenden Log die im Log gespeicherten."""
        if not self.new_log:
            from ..contests import class_from_log
            stored, _note = class_from_log(self.meta)
            if stored is not None:
                return stored
        return CONTESTS.get(self.contest.currentData())

    def _update_rules(self) -> None:
        cls = self._contest_cls()
        if cls is None:
            return
        text, old = rules_status(cls)
        text += " · " + rules_source_text(cls)
        self.rules_label.setText(text)
        self.rules_label.setStyleSheet("color:#e08a00; font-weight:bold;" if old else "")
        self.rules_btn.setEnabled(bool(getattr(cls, "rules_url", "")))
        newer = None if self.new_log else newer_rules(cls)
        self.newer_label.setText(newer_text(newer) if newer else "")
        self.newer_label.setVisible(newer is not None)
        self.newer_btn.setVisible(newer is not None)
        self._newer = newer

    def _update_fields(self) -> None:
        """Nur die Felder zeigen, die der gewählte Contest im Austausch braucht.
        Eingetragene Werte bleiben erhalten, auch wenn ein Feld gerade versteckt ist."""
        if not hasattr(self, "_optional"):
            return
        from ..contests.rulebased import station_fields
        cls = self._contest_cls()
        need = station_fields(cls) if cls is not None else set(self._optional)
        self.visible_fields = need
        self._fill_classes(cls)
        for key, w in self._optional.items():
            for x in (w if isinstance(w, tuple) else (w,)):
                self.form.setRowVisible(x, key in need)

    def _fill_classes(self, cls) -> None:
        """Auswahl der Leistungsklassen aus der Regel-Datei (gewählte Klasse bleibt)."""
        cur = self.pclass.currentData() if self.pclass.count() else self._pclass_saved
        self.pclass.clear()
        self.pclass.addItem(tr("– bitte wählen –"), "")
        for c in getattr(cls, "own_classes", ()) or ():
            self.pclass.addItem(c, c)
        i = self.pclass.findData(cur or self._pclass_saved)
        self.pclass.setCurrentIndex(max(i, 0))

    def _take_newer(self) -> None:
        import json
        if not getattr(self, "_newer", None):
            return
        self.meta["rules_json"] = json.dumps(self._newer.rules, ensure_ascii=False)
        self._update_rules()
        self.rules_label.setText(self.rules_label.text() +
                                 tr(" – wird beim Klick auf OK übernommen, die Punkte werden neu "
                                 "berechnet"))

    def open_rules(self) -> None:
        cls = self._contest_cls()
        if cls is not None and cls.rules_url:
            QDesktopServices.openUrl(QUrl(cls.rules_url))

    def accept(self) -> None:
        call = self.mycall.text().strip().upper()
        if not call:
            QMessageBox.warning(self, tr("Rufzeichen fehlt"), tr("Bitte das eigene Rufzeichen eintragen."))
            return
        if self.new_log and self.cb_station.isChecked():
            pw = self.ed_station_pw.text()
            if len(pw) < 4:
                QMessageBox.warning(self, tr("Stationskennwort"), tr(
                    "Bitte ein Stationskennwort mit mindestens 4 Zeichen eingeben – die "
                    "anderen Plätze brauchen es zum Mitmachen."))
                self.ed_station_pw.setFocus()
                return
            self.station_password = pw
        raw = self.grid.text().strip()
        if raw and not is_grid(raw):
            QMessageBox.warning(self, tr("Locator"),
                                tr("Bitte einen 4- oder 6-stelligen Locator eingeben, z. B. JN59me."))
            return
        grid = raw[:4].upper() + raw[4:].lower()
        from ..regions import normalize_province, normalize_section, normalize_state
        st_raw = self.state.text().strip()
        st = normalize_state(st_raw) or normalize_province(st_raw) \
            or normalize_section(st_raw) or ""
        if st_raw and not st:
            QMessageBox.warning(self, tr("State/Provinz"),
                                tr("Bitte die Abkürzung eines US-States (z. B. CT), einer "
                                "kanadischen Provinz (z. B. ON) oder einer ARRL-Section "
                                "(z. B. EMA) eintragen – oder leer lassen."))
            return
        itu = self.itu.text().strip().upper()
        if itu and not ((itu.isdigit() and 1 <= int(itu) <= 90)
                        or (itu.isalnum() and itu[0].isalpha() and len(itu) <= 6)):
            QMessageBox.warning(self, tr("ITU-Zone"), tr("Bitte eine ITU-Zone (1–90) oder ein "
                                "Verbandskürzel (z. B. DARC) eintragen – oder leer lassen."))
            return
        ly = self.licyear.text().strip()
        if ly and not (ly.isdigit() and len(ly) in (2, 4)):
            QMessageBox.warning(self, tr("Jahr der ersten Lizenz"),
                                tr("Bitte das Jahr eintragen, z. B. 1982 oder 82."))
            return
        ly = ly[-2:]
        from .. import dok as dokmod
        dk = dokmod.normalize(self.dok.text())
        if dk and dokmod.form_error(dk):
            QMessageBox.warning(self, tr("DOK"), dokmod.form_error(dk))
            return
        if dk and len(dk) > 6:
            QMessageBox.warning(self, tr("DOK"), tr("Sonder-DOKs mit mehr als 6 Zeichen sind in "
                                                    "DARC-Contesten nicht erlaubt."))
            return
        from ..contests.rulebased import normalize_iota
        from ..regions import normalize_oblast
        ob_raw = self.oblast.text().strip()
        ob = normalize_oblast(ob_raw) or ""
        if ob_raw and not ob:
            QMessageBox.warning(self, tr("Oblast"), tr("Bitte das Kürzel deines Oblasts eintragen "
                                                     "(z. B. MA oder SP) – oder leer lassen."))
            return
        io_raw = self.iota.text().strip()
        io = normalize_iota(io_raw)
        if io_raw and not io:
            QMessageBox.warning(self, tr("IOTA-Referenz"), tr("Bitte die IOTA-Referenz deiner "
                                "Insel eintragen (z. B. EU-005) – oder leer lassen."))
            return
        ag = self.age.text().strip()
        if ag and not (ag.isdigit() and 1 <= len(ag) <= 2):
            QMessageBox.warning(self, tr("Alter"), tr("Bitte dein Alter als Zahl eintragen "
                                                    "(z. B. 59) – oder leer lassen."))
            return
        ag = ag.zfill(2) if ag else ""
        mem = self.member.text().strip()
        if mem and not mem.isdigit():
            QMessageBox.warning(self, tr("Mitgliedsnummer"), tr(
                "Bitte die Mitgliedsnummer nur mit Ziffern eintragen (z. B. 2583) – oder leer "
                "lassen, wenn du kein Mitglied bist."))
            return
        dist = self.district.text().strip().upper()
        host = getattr(self._contest_cls(), "host", None)
        if dist and host and "district" in self.visible_fields:
            from ..contests.rulebased import normalize_district
            if not normalize_district(dist, host):
                codes = host.get("codes")
                QMessageBox.warning(self, tr("Kürzel"), tr(
                    "Dieses Kürzel kennt der Contest nicht. Erlaubt sind: {codes}",
                    codes=", ".join(codes) if codes else tr("drei Buchstaben"))
                    + tr(" – oder leer lassen."))
                return
        pw = self.power_ex.text().strip().upper()
        if pw and not (pw.isalnum() and len(pw) <= 5):
            QMessageBox.warning(self, tr("Leistung"), tr("Bitte z. B. 100, 5 oder KW eintragen."))
            return
        cid = self.contest.currentData()
        cls = self._contest_cls()
        if cls is not None and getattr(cls, "exchange_kind", "") == "grid4" \
                and not is_grid4(normalize(grid)):
            QMessageBox.warning(self, tr("Locator fehlt"),
                                tr("Für {name} wird der eigene 4-stellige Locator gebraucht.", name=cls.name))
            return
        if cls is not None and getattr(cls, "exchange_kind", "") in ("serial_grid6", "dok_grid6") \
                and len(grid) != 6:
            QMessageBox.warning(self, tr("Locator fehlt"),
                                tr("Für {name} wird der eigene 6-stellige Locator gebraucht "
                                   "(z. B. JN59ME) – er wird gesendet und ergibt die Kilometer.",
                                   name=cls.name))
            return
        pw_w = self.power_w.text().strip()
        if pw_w and not pw_w.replace(",", ".").replace(".", "", 1).isdigit():
            QMessageBox.warning(self, tr("Sendeleistung"), tr("Bitte die Leistung als Zahl in Watt "
                                                            "eintragen, z. B. 100."))
            return
        if "pclass" in self.visible_fields and not self.pclass.currentData():
            QMessageBox.warning(self, tr("Leistungsklasse fehlt"),
                                tr("Für {name} wird deine Leistungsklasse gesendet – sie "
                                   "bestimmt auch die Punkte. Bitte auswählen.", name=cls.name))
            return
        if cls is not None and getattr(cls, "exchange_kind", "") == "lic_year" and not ly:
            QMessageBox.warning(self, tr("Jahr der ersten Lizenz fehlt"),
                                tr("Für {name} wird das Jahr deiner allerersten Lizenz gesendet (z. "
                                   "B. 1982). Bitte eintragen.", name=cls.name))
            return
        self.meta.update({
            "contest": cid,
            "mycall": call,
            "operators": self.operators.text().strip().upper(),
            "my_zone": str(self.zone.value()),
            "my_grid": grid,
            "my_state": st,
            "my_power": pw,
            "my_itu": itu,
            "my_licyear": ly,
            "my_dok": dk,
            "my_oblast": ob,
            "my_iota": io,
            "my_age": ag,
            "my_iota_dxped": self.iota_kind.currentData() or "",
            "my_iota_island": self.iota_island.text().strip(),
            "my_district": dist,
            "my_member": self.member.text().strip(),
            "my_class": self.pclass.currentData() or self._pclass_saved,
            "edi_section": self.edi_section.currentData() or "SO",
            "my_power_w": pw_w,
            "my_antenna": self.antenna.text().strip(),
            "cat_operator": self.cat_operator.currentText(),
            "cat_band": self.cat_band.currentText(),
            "cat_power": self.cat_power.currentText(),
            "cat_assisted": self.cat_assisted.currentText(),
            "cat_transmitter": self.cat_transmitter.currentData() or "ONE",
            "cat_overlay": self.cat_overlay.currentText(),
            "name": self.name.text().strip(),
            "email": self.email.text().strip(),
            "club": self.club.text().strip(),
            "address": self.address.toPlainText().strip(),
            "soapbox": self.soapbox.toPlainText().strip(),
        })
        super().accept()


class PermissionDialog(QDialog):
    """Keine Berechtigung für die Schnittstelle (0.10.1). Ab 0.10.25 zuerst „Freigeben“: eine
    udev-Regel gibt alle USB-Seriell-Geräte dem angemeldeten Benutzer – sofort, ohne neu
    anmelden. Wo das nicht geht: wie bisher die Gruppe (pkexec) und der Befehl zum Kopieren."""

    def __init__(self, group: str = "", parent=None):
        super().__init__(parent)
        from .. import permissions
        self.group = group or ("uucp" if _group_exists("uucp") else "dialout")
        group = self.group
        self.rule_mode = permissions.uaccess_supported()
        self.done_ok = False
        self.setWindowTitle(tr("USB-Geräte freigeben"))
        lay = QVBoxLayout(self)
        if self.rule_mode:
            txt = tr("Linux lässt Programme nicht ohne Weiteres an USB-Geräte wie Funkgerät-Kabel, "
                     "GPS-Empfänger, WinKeyer oder Rotor-Steuerung. Mit „Freigeben“ gehören diese "
                     "Geräte dem Benutzer, der gerade am Rechner angemeldet ist – sofort, ohne neu "
                     "anmelden, auch beim Einstecken im Betrieb. Du wirst einmal nach dem "
                     "Systempasswort gefragt.")
        elif permissions.member_not_active(group):
            txt = tr("Du bist schon in der Gruppe „{g}“ eingetragen – das gilt aber erst nach dem "
                     "nächsten Anmelden. Bitte einmal ab- und wieder anmelden (oder den Rechner "
                     "neu starten).", g=group)
        else:
            txt = tr("Linux erlaubt die Schnittstellen zum Funkgerät nur Mitgliedern der Gruppe "
                     "„{g}“. Mit „Einrichten“ nimmt GoGoHam dich in diese Gruppe auf – du wirst "
                     "nach dem Systempasswort gefragt. Danach einmal ab- und wieder anmelden.",
                     g=group)
        lab = QLabel(txt)
        lab.setWordWrap(True)
        lay.addWidget(lab)
        lay.addWidget(QLabel(tr("Oder selbst im Terminal eingeben (danach einmal ab- und wieder "
                                "anmelden):") if self.rule_mode else
                             tr("Oder selbst im Terminal eingeben:")))
        self.cmd = QLineEdit(permissions.command(group))
        self.cmd.setReadOnly(True)
        row = QHBoxLayout()
        row.addWidget(self.cmd, 1)
        btn_copy = QPushButton(tr("Befehl kopieren"))
        btn_copy.clicked.connect(self._copy)
        row.addWidget(btn_copy)
        lay.addLayout(row)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        lay.addWidget(self.result)
        bl = QHBoxLayout()
        self.btn_fix = QPushButton(tr("Freigeben") if self.rule_mode else tr("Einrichten"))
        self.btn_fix.clicked.connect(self._fix)
        self.btn_fix.setEnabled(self.rule_mode or not permissions.member_not_active(group))
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.accept)
        bl.addStretch(1)
        bl.addWidget(self.btn_fix)
        bl.addWidget(close)
        lay.addLayout(bl)
        self.resize(600, 0)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.cmd.text())
        self.result.setText(tr("Befehl kopiert – im Terminal mit Strg+Umschalt+V einfügen."))

    def _fix(self) -> None:
        import subprocess
        from .. import permissions
        from .. import applog
        cmd = permissions.rule_command() if self.rule_mode else permissions.fix_command(self.group)
        try:
            r = subprocess.run(cmd, timeout=180, capture_output=True, text=True)
            ok = r.returncode == 0
            err = (r.stderr or "").strip()
        except (OSError, subprocess.SubprocessError) as e:
            ok, err = False, str(e)
        applog.message(f"USB-Freigabe ({'Regel' if self.rule_mode else 'Gruppe'}): "
                       f"{'ok' if ok else 'fehlgeschlagen ' + err}", "info" if ok else "warn")
        if ok:
            self.done_ok = True
            self.result.setText(
                tr("Erledigt – die USB-Geräte sind jetzt freigegeben. Ein Gerät, das gerade "
                   "nicht geht, einmal ab- und wieder einstecken.") if self.rule_mode else
                tr("Erledigt. Bitte jetzt einmal ab- und wieder anmelden (oder den "
                   "Rechner neu starten) – danach darf GoGoHam die Schnittstelle "
                   "benutzen."))
            self.result.setStyleSheet("color:#1b8a3a; font-weight:bold;")
            self.btn_fix.setEnabled(False)
        else:
            self.result.setText(tr("Das hat nicht geklappt (abgebrochen oder falsches Passwort). "
                                   "Du kannst den Befehl oben kopieren und im Terminal eingeben."))
            self.result.setStyleSheet("color:#c62828;")


def _group_exists(name: str) -> bool:
    import grp
    try:
        grp.getgrnam(name)
        return True
    except KeyError:
        return False


def net_problem(p: dict) -> str:
    """Passen die Netzwerk-Angaben des Profils? "" = in Ordnung (0.10.30)."""
    c = p.get("conn", "usb")
    if c == "usb":
        return ""
    if not (p.get("net_host") or "").strip():
        return tr("Bitte die Adresse des Funkgeräts bzw. Rechners eintragen.")
    if c == "icom":
        from .. import hamlib
        r = hamlib.find_model(int(p.get("model") or 0))
        if r and "icom" not in (r.mfg or "").lower():
            return tr("„Netzwerk – Icom“ geht nur mit Icom-Geräten – bitte ein Icom-Modell wählen.")
        if not (p.get("net_user") or "") or not (p.get("net_pass") or ""):
            return tr("Bitte Benutzername und Passwort eintragen, wie im Funkgerät angelegt "
                      "(Network User).")
    return ""


class RigDialog(QDialog):
    """Funkgerät aus der Hamlib-Liste wählen, bis zu fünf Profile."""

    def __init__(self, cfg: dict, parent=None, test_fn=None, embedded: bool = False):
        super().__init__(parent)
        from .. import hamlib, rigprofiles
        self._hl = hamlib
        self.setWindowTitle(tr("Funkgerät (CAT)"))
        self.setMinimumWidth(620)
        self.cfg = cfg
        self.test_fn = test_fn
        self.detect_fn = None               # Tests: Ersatz für rigdetect.detect
        self.ptt_fn = None                  # Tests: Ersatz für hamlib.ptt_test
        self.tested = False
        rigprofiles.ensure_profiles(cfg)
        # Plätze 1–5 frei belegbar (0.8.17.2, fünf ab 0.10.4): Profil steht auf seinem Platz ("slot")
        self.slots: list[dict | None] = [None] * rigprofiles.MAX_PROFILES
        for p in cfg["rig_profiles"]:
            self.slots[p["slot"]] = dict(p)
        act = rigprofiles.active(cfg)
        self.cur = act["slot"] if act else 0
        self.rigs = list(hamlib.list_rigs())
        self._loading = False

        form = QFormLayout()
        self.enabled = QCheckBox(tr("CAT-Steuerung benutzen"))
        self.enabled.setChecked(cfg["rig_enabled"])
        form.addRow(self.enabled)

        self.profile = QComboBox()
        self.profile.currentIndexChanged.connect(self._profile_changed)
        self.btn_delete = QPushButton(tr("Profil löschen"))
        self.btn_delete.clicked.connect(self._delete_profile)
        row = QHBoxLayout()
        row.addWidget(self.profile, 1)
        row.addWidget(self.btn_delete)
        form.addRow(tr("Profil:"), row)
        self.name = QLineEdit()
        self.name.setPlaceholderText(tr("z. B. IC-7300 KW"))
        form.addRow(tr("Name des Profils:"), self.name)

        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Suchen: z. B. 9700, FT-991, Kenwood …"))
        self.search.textEdited.connect(self._search_changed)
        self.model = QComboBox()
        self.model.currentIndexChanged.connect(lambda _i: self._model_changed())
        form.addRow(tr("Gerät suchen:"), self.search)
        form.addRow(tr("Funkgerät:"), self.model)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        form.addRow("", self.info)
        if not self.rigs:
            self.info.setText(tr("Hamlib (rigctl) nicht gefunden – bitte installieren: "
                              "sudo pacman -S hamlib"))

        # 0.10.30: Verbindung – Kabel, Icom übers Netz, andere Netzwerk-Geräte, anderer Rechner
        self.conn = QComboBox()
        self.conn.addItem(tr("USB-Kabel / serielle Schnittstelle"), "usb")
        self.conn.addItem(tr("Netzwerk (LAN/WLAN) – Icom"), "icom")
        self.conn.addItem(tr("Netzwerk (LAN/WLAN) – andere Hersteller (über Hamlib)"), "net")
        self.conn.addItem(tr("Funkgerät an einem anderen Rechner im Netzwerk"), "remote")
        self.conn.currentIndexChanged.connect(lambda _i: self._conn_changed())
        form.addRow(tr("Verbunden über:"), self.conn)
        self._form = form

        self.device = QComboBox()
        self.device.setEditable(True)
        self.device.currentTextChanged.connect(lambda _t: self._device_changed())
        self.device.currentTextChanged.connect(lambda _t: self._update_audio_hint()
                                               if hasattr(self, "audio_hint") else None)
        self.btn_ports = QPushButton(tr("Neu suchen"))
        self.btn_ports.clicked.connect(self._fill_ports)
        row = QHBoxLayout()
        self.btn_detect = QPushButton(tr("Gerät erkennen"))
        self.btn_detect.setToolTip(tr("Fragt das Gerät an der Schnittstelle, wer es ist, und trägt "
                                      "Modell und Baudrate ein – es wird nichts gesendet"))
        self.btn_detect.clicked.connect(self._detect)
        row.addWidget(self.device, 1)
        row.addWidget(self.btn_ports)
        row.addWidget(self.btn_detect)
        form.addRow(tr("Schnittstelle:"), row)
        self._dev_row = row
        self.port_hint = QLabel("")
        form.addRow("", self.port_hint)
        self.baud = QComboBox()
        form.addRow(tr("Baudrate:"), self.baud)

        # 0.10.30: Netzwerk-Felder (je nach Verbindung sichtbar)
        self.net_host = QLineEdit()
        self.net_host.setPlaceholderText(tr("z. B. 192.168.178.40"))
        self.btn_find = QPushButton(tr("Im Netz suchen"))
        self.btn_find.clicked.connect(self._find_in_network)
        row = QHBoxLayout()
        row.addWidget(self.net_host, 1)
        row.addWidget(self.btn_find)
        form.addRow(tr("Adresse:"), row)
        self._host_row = row
        self.net_port = QSpinBox()
        self.net_port.setRange(1, 65535)
        self.net_port.setMaximumWidth(140)
        form.addRow(tr("Port:"), self.net_port)
        self.net_user = QLineEdit()
        form.addRow(tr("Benutzername:"), self.net_user)
        self.net_pass = QLineEdit()
        self.net_pass.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(tr("Passwort:"), self.net_pass)
        self.net_audio = QCheckBox(tr("Ton übers Netzwerk (eigene Soundkarte „GoGoHam …“ für "
                                      "WSJT-X, fldigi und Sprachspeicher)"))
        form.addRow("", self.net_audio)
        self.conn_hint = QLabel("")
        self.conn_hint.setWordWrap(True)
        self.conn_hint.setStyleSheet("color:#888888;")
        form.addRow("", self.conn_hint)

        # ---- Erweiterte Einstellungen (0.8.22): eigenes Fenster, damit die Hauptseite für
        # die meisten Geräte übersichtlich bleibt (Wunsch des Nutzers)
        self.adv = QDialog(self)
        self.adv.setWindowTitle(tr("Funkgerät – erweiterte Einstellungen"))
        self.adv.setMinimumWidth(720)
        adv_lay = QVBoxLayout(self.adv)
        adv_intro = QLabel(tr("Nur nötig für ältere Geräte mit Interface, einen WinKey, PTT über "
                              "eine Steuerleitung oder besondere rigctld-Wünsche. Im Zweifel "
                              "alles so lassen."))
        adv_intro.setWordWrap(True)
        adv_lay.addWidget(adv_intro)

        # 1) Älteres Gerät / Interface
        box = QGroupBox(tr("Älteres Gerät mit Interface (Pegelwandler, CI-V-Kabel)"))
        v1 = QVBoxLayout(box)
        f1 = QFormLayout()
        v1.addLayout(f1)
        self.lines = QComboBox()
        self.lines.addItem(tr("Nicht verändern (Standard)"), "")
        self.lines.addItem(tr("DTR und RTS einschalten"), "both")
        self.lines.addItem(tr("Nur DTR einschalten"), "dtr")
        self.lines.addItem(tr("Nur RTS einschalten"), "rts")
        self.lines.addItem(tr("DTR und RTS ausschalten"), "off")
        self.lines.setToolTip(tr("Viele einfache Interfaces holen ihren Strom aus den "
                                 "Steuerleitungen DTR/RTS – steht in der Anleitung des "
                                 "Interfaces"))
        f1.addRow(tr("Strom fürs Interface:"), self.lines)
        self.lines_warn = QLabel(tr("⚠ Bei manchen Interfaces schaltet RTS oder DTR das Gerät auf "
                                    "SENDEN. Nur einschalten, wenn die Anleitung des Interfaces "
                                    "es so sagt – danach „Verbindung testen“ und auf die "
                                    "Sendeanzeige achten."))
        self.lines_warn.setWordWrap(True)
        self.lines_warn.setStyleSheet("color:#c62828;")
        self.civaddr = QLineEdit()
        self.civaddr.setMaximumWidth(90)
        f1.addRow(tr("CI-V-Adresse (Icom):"), self.civaddr)
        self.civ_hint = QLabel("")
        self.civ_hint.setWordWrap(True)
        self.civ_hint.setStyleSheet("color:#888888;")
        # Erklärtexte unter das Formular (QFormLayout rechnet umbrechende Texte zu niedrig)
        v1.addWidget(self.lines_warn)
        v1.addWidget(self.civ_hint)
        adv_lay.addWidget(box)
        self.lines.currentIndexChanged.connect(lambda _i: self._update_adv())
        self.civaddr.textChanged.connect(lambda _t: self._update_adv())

        # 2) CW und PTT – 0.8.18: CW über einen WinKey, PTT über eine Steuerleitung (z. B. DXP)
        box = QGroupBox(tr("CW und PTT"))
        f2 = QFormLayout(box)
        self.cw_via = QComboBox()
        self.cw_via.addItem(tr("Funkgerät (über CAT)"), "cat")
        self.cw_via.addItem(tr("WinKey (eigene Schnittstelle)"), "winkey")
        self.wk_device = QComboBox()
        self.wk_device.setEditable(True)
        self.btn_wk = QPushButton(tr("WinKey prüfen"))
        self.btn_wk.setToolTip(tr("Fragt nur die Version des WinKey ab – es wird nichts gesendet"))
        self.btn_wk.clicked.connect(self._check_winkey)
        row = QHBoxLayout()
        row.addWidget(self.cw_via)
        row.addWidget(self.wk_device, 1)
        row.addWidget(self.btn_wk)
        f2.addRow(tr("CW senden über:"), row)
        self.ptt_via = QComboBox()
        self.ptt_via.addItem(tr("CAT (Befehl ans Funkgerät)"), "")
        self.ptt_via.addItem(tr("DTR-Leitung einer Schnittstelle"), "DTR")
        self.ptt_via.addItem(tr("RTS-Leitung einer Schnittstelle"), "RTS")
        self.ptt_device = QComboBox()
        self.ptt_device.setEditable(True)
        for c in (self.wk_device, self.ptt_device):     # lange by-id-Namen: nicht breiter machen
            c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(18)
        row = QHBoxLayout()
        row.addWidget(self.ptt_via)
        row.addWidget(self.ptt_device, 1)
        f2.addRow(tr("PTT (Senden):"), row)
        self.cw_via.currentIndexChanged.connect(lambda _i: self._update_cw_ptt())
        self.ptt_via.currentIndexChanged.connect(lambda _i: self._update_cw_ptt())
        adv_lay.addWidget(box)

        # 2a) Ton – 0.10.9: Soundkarte des Funkgeräts (für WS, fldigi)
        box = QGroupBox(tr("Ton (für WS und fldigi)"))
        f2a = QFormLayout(box)
        self.audio_out = QComboBox()
        self.audio_out.addItem(tr("Automatisch (über USB erkennen)"), "")
        try:
            from . import audio as _audio
            for dev_id, desc in _audio.outputs():
                if dev_id:
                    self.audio_out.addItem(desc, dev_id)
        except Exception:  # noqa: BLE001 – ohne Qt-Multimedia nur „Automatisch“
            pass
        self.audio_out.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.audio_out.setMinimumContentsLength(18)
        f2a.addRow(tr("Soundkarte des Funkgeräts:"), self.audio_out)
        self.audio_hint = QLabel()
        self.audio_hint.setWordWrap(True)
        f2a.addRow("", self.audio_hint)
        self.audio_out.currentIndexChanged.connect(lambda _i: self._update_audio_hint())
        adv_lay.addWidget(box)

        # 3) rigctld
        from .. import rigservice
        self._rs = rigservice
        box = QGroupBox(tr("rigctld (Verbindung zu Hamlib, auch für WS & Co.)").replace("&", "&&"))
        f3 = QFormLayout(box)
        self.startmode = QComboBox()
        self.startmode.addItem(tr("GoGoHam startet rigctld selbst (solange GoGoHam läuft)"), "self")
        self._svc_ok = rigservice.available()      # einmal fragen (startet systemctl)
        if self._svc_ok:
            self.startmode.addItem(tr("GoGoHam richtet rigctld dauerhaft ein (läuft immer – "
                                      "auch für WS & Co.)"), "service")
        self.startmode.addItem(tr("Vorhandenen rigctld benutzen (z. B. Systemdienst)"), "external")
        f3.addRow(tr("rigctld:"), self.startmode)
        self.host = QLineEdit("127.0.0.1")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        row = QHBoxLayout()
        row.addWidget(self.host, 1)
        row.addWidget(QLabel(tr("Port:")))
        row.addWidget(self.port)
        f3.addRow(tr("rigctld Rechner:"), row)
        # 0.8.17.3: was man in WSJT-X & Co. einträgt
        self.net_hint = QLabel("")
        self.net_hint.setWordWrap(True)
        self.net_hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        f3.addRow(tr("Andere Programme:"), self.net_hint)
        self.host.textChanged.connect(lambda _t: self._update_net_hint())
        self.port.valueChanged.connect(lambda _v: self._update_net_hint())
        self.startmode.currentIndexChanged.connect(lambda _i: self._update_net_hint())
        adv_lay.addWidget(box)

        # 3b) Abfrage (0.8.29.1): so oft fragt GoGoHam die Frequenz ab
        box = QGroupBox(tr("Abfrage der Frequenz"))
        v5 = QVBoxLayout(box)
        f5 = QFormLayout()
        v5.addLayout(f5)
        self.poll_ms = QSpinBox()
        self.poll_ms.setRange(0, 2000)
        self.poll_ms.setSingleStep(10)
        self.poll_ms.setSuffix(" ms")
        self.poll_ms.setSpecialValueText(tr("automatisch"))
        self.poll_ms.setMaximumWidth(160)
        f5.addRow(tr("Abfrage-Intervall:"), self.poll_ms)
        self.poll_hint = QLabel("")
        self.poll_hint.setWordWrap(True)
        self.poll_hint.setStyleSheet("color:#888888;")
        v5.addWidget(self.poll_hint)
        self.poll_ms.valueChanged.connect(lambda _v: self._update_adv())
        adv_lay.addWidget(box)

        # 4) Für Kenner
        box = QGroupBox(tr("Für Kenner"))
        f4 = QFormLayout(box)
        self.extra = QLineEdit()
        self.extra.setPlaceholderText(tr("z. B. --set-conf=serial_handshake=None"))
        f4.addRow(tr("Weitere rigctld-Optionen:"), self.extra)
        self.extra.textChanged.connect(lambda _t: self._update_adv())
        adv_lay.addWidget(box)
        adv_lay.addStretch(1)
        done = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        done.rejected.connect(self.adv.accept)
        done.button(QDialogButtonBox.StandardButton.Close).setText(tr("Fertig"))
        adv_lay.addWidget(done)

        self.btn_test = QPushButton(tr("Verbindung testen"))
        self.btn_test.setToolTip(tr("Liest einmal Frequenz und Mode – es wird nichts gesendet"))
        self.btn_test.clicked.connect(self._test)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        self.btn_ptt = QPushButton(tr("PTT testen"))
        self.btn_ptt.setToolTip(tr("Schaltet nach Rückfrage für 1 Sekunde auf Senden und wieder zurück"))
        self.btn_ptt.clicked.connect(self._test_ptt)
        row = QHBoxLayout()
        row.addWidget(self.btn_test)
        row.addWidget(self.btn_ptt)
        row.addWidget(self.test_result, 1)
        form.addRow("", row)
        # 0.10.1: keine Berechtigung für die Schnittstelle -> mit einem Klick einrichten
        self.btn_perm = QPushButton(tr("Berechtigung einrichten …"))
        self.btn_perm.setToolTip(tr("Nimmt dich in die Linux-Gruppe auf, die die Schnittstellen "
                                    "benutzen darf (fragt nach dem Systempasswort)"))
        self.btn_perm.clicked.connect(self._fix_permission)
        self.btn_perm.setVisible(False)
        form.addRow("", self.btn_perm)

        # Knopf zum Fenster + Zeile, was dort vom Standard abweicht (nichts bleibt unbemerkt)
        self.btn_adv = QPushButton(tr("Erweiterte Einstellungen …"))
        self.btn_adv.setToolTip(tr("Interface älterer Geräte (DTR/RTS, CI-V-Adresse), WinKey, "
                                   "PTT über Steuerleitung, rigctld, eigene Optionen"))
        self.btn_adv.clicked.connect(self.show_advanced)
        self.adv_summary = QLabel("")
        self.adv_summary.setWordWrap(True)
        self.adv_summary.setStyleSheet("color:#888888;")
        row = QHBoxLayout()
        row.addWidget(self.btn_adv)
        row.addWidget(self.adv_summary, 1)
        form.addRow("", row)

        hint = QLabel(tr("Für die meisten Geräte reicht: Funkgerät per USB anschließen, „Gerät "
                         "erkennen“, „Verbindung testen“. Baudrate und CAT-Einstellungen müssen zum "
                         "Menü im Funkgerät passen. GoGoHam startet immer mit Profil 1; das beim "
                         "Klick auf OK gewählte Profil gilt bis zum Beenden."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888888;")
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addStretch(1)
        if not embedded:
            lay.addWidget(_buttons(self, "cat"))
        self._fill_profiles()
        self._load_slot(self.cur)

    # --- Profile -------------------------------------------------------------
    def _slot_label(self, i: int) -> str:
        p = self.slots[i]
        if p:                            # 0.8.31.1: kein Start-Profil mehr – das zuletzt benutzte
            return tr("Profil {p1}: {p3}", p1=i + 1, p3=p['name'])
        return tr("Profil {p1}: (frei – neu anlegen)", p1=i + 1)

    def _fill_profiles(self) -> None:
        self._loading = True
        self.profile.clear()
        for i in range(len(self.slots)):
            self.profile.addItem(self._slot_label(i), i)
        self.profile.setCurrentIndex(self.cur)
        self._loading = False

    def _profile_changed(self, i: int) -> None:
        if self._loading or i < 0 or i == self.cur:
            return
        self._store_slot()
        self.cur = i
        self._load_slot(i)

    def _delete_profile(self) -> None:
        if self.slots[self.cur] is None:
            return
        self.slots[self.cur] = None
        self.cur = next((i for i, p in enumerate(self.slots) if p), 0)
        self._fill_profiles()
        self._load_slot(self.cur)

    def _load_slot(self, i: int) -> None:
        # 0.8.22.1: neue Profile richten rigctld dauerhaft ein (Nutzerwunsch: dann laufen
        # WSJT-X & Co. sofort mit) – wo das nicht geht, startet GoGoHam ihn selbst
        svc = self._svc_ok
        p = self.slots[i] or {"name": "", "model": 0, "device": "", "baud": 0, "extra": "",
                              "host": "127.0.0.1", "port": self._free_port(),
                              "start": not svc, "service": svc}
        self._loading = True
        self.name.setText(p["name"])
        self.extra.setText(p.get("extra", ""))
        self.lines.setCurrentIndex(max(0, self.lines.findData(p.get("lines", ""))))
        self.civaddr.setText(p.get("civaddr", ""))
        self.poll_ms.setValue(int(p.get("poll_ms") or 0))
        self.host.setText(p.get("host", "127.0.0.1"))
        self.port.setValue(int(p.get("port", 4532)))
        self._set_mode(self._mode_of(p))
        c = p.get("conn", "usb")
        self.conn.setCurrentIndex(max(0, self.conn.findData(c)))
        self.net_host.setText(p.get("net_host", ""))
        self.net_port.setValue(int(p.get("net_port") or self._default_net_port(c)))
        self.net_user.setText(p.get("net_user", ""))
        self.net_pass.setText(p.get("net_pass", ""))
        self.net_audio.setChecked(bool(p.get("net_audio", True)))
        self.search.setText("")
        self._fill_models(int(p.get("model") or 0))
        self._fill_ports(p.get("device", ""))
        self._fill_combo(self.wk_device, p.get("winkey", ""))
        self._fill_combo(self.ptt_device, p.get("ptt_device", ""))
        self.cw_via.setCurrentIndex(self.cw_via.findData("winkey" if p.get("winkey") else "cat"))
        self.ptt_via.setCurrentIndex(max(0, self.ptt_via.findData(p.get("ptt_line", ""))))
        self._update_cw_ptt()
        ao = p.get("audio_out", "")
        if ao and self.audio_out.findData(ao) < 0:          # gerade nicht angeschlossen
            from .. import extapps
            self.audio_out.addItem(extapps.nice_sound(ao), ao)
        self.audio_out.setCurrentIndex(max(0, self.audio_out.findData(ao)))
        self._loading = False
        self._update_audio_hint()
        self._model_changed(p.get("baud"))
        self.btn_delete.setEnabled(self.slots[i] is not None)
        self._conn_changed(keep_port=True)
        self._update_net_hint()
        self._update_adv()

    def _store_slot(self) -> None:
        model = self.model.currentData()
        if not model:
            return
        name = self.name.text().strip()
        if not name:
            r = self._hl.find_model(model)
            name = r.name if r else f"Hamlib {model}"
        self.slots[self.cur] = {
            "slot": self.cur,
            "name": name,
            "model": int(model),
            "device": self.device.currentText().strip(),
            "baud": int(self.baud.currentData() or 0),
            "extra": self.extra.text().strip(),
            "host": self.host.text().strip() or "127.0.0.1",
            "port": self.port.value(),
            "start": self.startmode.currentData() == "self",
            "service": self.startmode.currentData() == "service",
            "winkey": self.wk_device.currentText().strip()
            if self.cw_via.currentData() == "winkey" else "",
            "ptt_line": self.ptt_via.currentData() or "",
            "ptt_device": self.ptt_device.currentText().strip() if self.ptt_via.currentData() else "",
            "lines": self.lines.currentData() or "",
            "civaddr": self.civaddr.text().strip(),
            "poll_ms": (max(20, self.poll_ms.value()) if self.poll_ms.value() else 0),
            "audio_out": self.audio_out.currentData() or "",
            "conn": self.conn.currentData() or "usb",
            "net_host": self.net_host.text().strip(),
            "net_port": self.net_port.value(),
            "net_user": self.net_user.text(),
            "net_pass": self.net_pass.text(),
            "net_audio": self.net_audio.isChecked(),
        }
        c = self.slots[self.cur]["conn"]
        if c == "icom":            # Brücke läuft in GoGoHam: rigctld startet GoGoHam selbst
            self.slots[self.cur].update(start=True, service=False)
        elif c == "remote":        # rigctld läuft auf dem anderen Rechner
            self.slots[self.cur].update(start=False, service=False, port=self.net_port.value())

    # --- Netzwerk (0.10.30) ----------------------------------------------------
    @staticmethod
    def _default_net_port(c: str) -> int:
        from .. import rigprofiles
        return {"icom": rigprofiles.ICOM_PORT, "remote": 4532}.get(c, 4532)

    def _conn_changed(self, keep_port: bool = False) -> None:
        c = self.conn.currentData() or "usb"
        f = self._form
        usb = c == "usb"
        for item in (self._dev_row, self.port_hint, self.baud):
            f.setRowVisible(item, usb)
        for item in (self._host_row, self.net_port, self.conn_hint):
            f.setRowVisible(item, not usb)
        for item in (self.net_user, self.net_pass, self.net_audio):
            f.setRowVisible(item, c == "icom")
        self.btn_find.setVisible(c in ("icom", "remote"))
        self.btn_detect.setEnabled(usb)
        if not keep_port and not self._loading:
            self.net_port.setValue(self._default_net_port(c))
        hints = {
            "icom": tr("Im Funkgerät einschalten: Netzwerk → Fernsteuerung (Network Control) "
                       "und einen Benutzer mit Passwort anlegen (Network User). GoGoHam braucht "
                       "kein Zusatzprogramm. Nur im eigenen Netz benutzen – Icom überträgt das "
                       "Passwort nicht verschlüsselt."),
            "net": tr("Für Geräte, die Hamlib direkt über das Netzwerk steuern kann (z. B. "
                      "Elecraft K4, FlexRadio). Adresse und Port stehen in der Anleitung des "
                      "Geräts."),
            "remote": tr("Auf dem anderen Rechner läuft rigctld (z. B. GoGoHam mit dem Funkgerät "
                         "am Kabel, oder ein Raspberry Pi im Shack). „Im Netz suchen“ findet ihn."),
        }
        self.conn_hint.setText(hints.get(c, ""))
        if not self._loading:
            self._update_net_hint()

    def _find_in_network(self) -> None:
        from PySide6.QtCore import Qt as _Qt
        c = self.conn.currentData()
        self.test_result.setText(tr("Suche im Netzwerk …"))
        QApplication.setOverrideCursor(_Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            if c == "icom":
                from .. import icomlan
                found = [(ip, icomlan.CONTROL_PORT, "Icom") for ip in icomlan.discover(2.0)]
            else:
                from .. import netscan
                found = netscan.find_rigctld()
        finally:
            QApplication.restoreOverrideCursor()
        if not found:
            self.test_result.setText(
                tr("Nichts gefunden. Ist das Gerät eingeschaltet und im selben Netz? Bei Icom: "
                   "Netzwerk-Fernsteuerung im Funkgerät eingeschaltet?") if c == "icom" else
                tr("Kein rigctld im Netz gefunden. Läuft er auf dem anderen Rechner, und ist "
                   "er von außen erreichbar (rigctld -T 0.0.0.0)?"))
            self.test_result.setStyleSheet("color:#c62828;")
            return
        ip, port, what = found[0]
        if len(found) > 1:
            from PySide6.QtWidgets import QInputDialog
            items = [f"{a}:{b} – {w}" for a, b, w in found]
            choice, ok = QInputDialog.getItem(self, tr("Im Netz gefunden"),
                                              tr("Welches Gerät?"), items, 0, False)
            if not ok:
                return
            ip, port, what = found[items.index(choice)]
        self.net_host.setText(ip)
        self.net_port.setValue(int(port))
        self.test_result.setText(tr("Gefunden: {what} auf {addr}", what=what,
                                    addr=f"{ip}:{port}"))
        self.test_result.setStyleSheet("color:#1b8a3a;")

    def _update_audio_hint(self) -> None:
        """Unter „Soundkarte des Funkgeräts“: was automatisch gefunden wurde."""
        if self.audio_out.currentData():
            self.audio_hint.setText("")
            return
        from .. import extapps, rigaudio
        out, _inp, origin = rigaudio.for_profile({"device": self.device.currentText().strip()})
        if origin:
            self.audio_hint.setText(tr("Gefunden: {v}", v=extapps.nice_sound(out)))
        else:
            self.audio_hint.setText(tr(
                "Keine eingebaute Soundkarte gefunden (Funkgerät aus oder nicht angeschlossen – "
                "oder es hat keine, z. B. FT-891). Dann hier das Ton-Interface wählen."))
    def _update_net_hint(self) -> None:
        """Zeile „Andere Programme“: Einstellung für WSJT-X, Log-Programme usw."""
        host = self.host.text().strip() or "127.0.0.1"
        text = tr("WS & Co.: „Hamlib NET rigctl“ mit {addr}", addr=f"{host}:{self.port.value()}")
        if self.startmode.currentData() == "self":
            text += tr(" – nur solange GoGoHam läuft")
        self.net_hint.setText(text)
        self._update_adv()

    # --- Erweiterte Einstellungen (0.8.22) -----------------------------------
    def show_advanced(self) -> None:
        self._update_adv()
        self.fit_advanced()
        self.adv.exec()
        self._update_adv()

    def fit_advanced(self) -> None:
        """Fenstergröße passend zu den umbrechenden Texten (Qt rechnet die Startgröße sonst
        ohne Zeilenumbruch und quetscht die Gruppen zusammen)."""
        lay = self.adv.layout()
        w = max(self.adv.minimumWidth(), self.adv.width() if self.adv.isVisible() else 0)
        h = lay.heightForWidth(w) if lay.hasHeightForWidth() else lay.sizeHint().height()
        self.adv.resize(w, max(h, lay.sizeHint().height()))

    def _is_icom(self) -> bool:
        r = self._hl.find_model(self.model.currentData() or 0) if self.model.count() else None
        return bool(r and (getattr(r, "mfg", "") or "").lower().startswith("icom"))

    def _civ_default(self) -> str:
        """Standard-CI-V-Adresse des gewählten Icom-Modells (aus der Erkennungs-Tabelle)."""
        from ..rigdetect import ICOM_IDS, _norm
        r = self._hl.find_model(self.model.currentData() or 0) if self.model.count() else None
        if not r:
            return ""
        want = _norm(r.name)
        return next((f"{a:02X}" for a, n in ICOM_IDS.items() if _norm(n) == want), "")

    def _update_adv(self) -> None:
        """Warnung, CI-V-Feld und die Zusammenfassung auf der Hauptseite auffrischen."""
        if not hasattr(self, "adv_summary"):
            return
        line = self.lines.currentData() or ""
        self.lines_warn.setVisible(line in ("both", "dtr", "rts"))
        icom = self._is_icom()
        self.civaddr.setEnabled(icom)
        if icom:
            d = self._civ_default()
            self.civaddr.setPlaceholderText(d or tr("Standard"))
            self.civ_hint.setText(
                tr("CI-V-Adresse leer = Standard des Geräts{d}. Nur ändern, wenn sie im Gerät "
                   "verstellt ist oder mehrere Geräte am selben CI-V-Kabel hängen.",
                   d=tr(" ({d})", d=d) if d else ""))
        else:
            self.civaddr.setPlaceholderText("")
            self.civ_hint.setText(tr("CI-V-Adresse: nur bei Icom-Geräten"))
        from .. import rigprofiles
        parts = []
        if line:
            parts.append({"both": tr("Interface: DTR+RTS an"), "dtr": tr("Interface: DTR an"),
                          "rts": tr("Interface: RTS an"), "off": tr("Interface: DTR+RTS aus")}[line])
        civ = self.civaddr.text().strip()
        if civ and icom:
            v = rigprofiles.parse_civaddr(civ)
            parts.append(tr("CI-V {a}", a=f"{v:02X}") if v is not None
                         else tr("CI-V-Adresse ungültig"))
        if self.cw_via.currentData() == "winkey":
            parts.append(tr("CW über WinKey"))
        if self.ptt_via.currentData():
            parts.append(tr("PTT über {line}", line=self.ptt_via.currentData()))
        mode = self.startmode.currentData()
        # Standard ist „dauerhaft“, wo möglich (0.8.22.1) – sonst „selbst starten“
        if mode == "self" and getattr(self, "_svc_ok", False):
            parts.append(tr("rigctld nur mit GoGoHam"))
        elif mode == "service" and not getattr(self, "_svc_ok", False):
            parts.append(tr("rigctld dauerhaft"))
        elif mode == "external":
            parts.append(tr("vorhandener rigctld"))
        if self.extra.text().strip():
            parts.append(tr("eigene Optionen"))
        ms = self.poll_ms.value()
        if ms:
            parts.append(tr("Abfrage alle {ms} ms", ms=max(20, ms)))
        self.poll_hint.setText(self._poll_text(ms))
        host = self.host.text().strip() or "127.0.0.1"
        net = tr("WS & Co.: „Hamlib NET rigctl“ mit {addr}", addr=f"{host}:{self.port.value()}")
        self.adv_summary.setText((tr("Erweitert: {list}", list=", ".join(parts)) if parts
                                  else tr("Erweitert: alles Standard")) + "\n" + net)

    def _poll_text(self, ms: int) -> str:
        text = tr("Automatisch: GoGoHam misst beim Verbinden, wie schnell das Funkgerät "
                  "antwortet, und fragt so oft wie möglich – höchstens 50-mal pro Sekunde, bei "
                  "langsamen Geräten seltener. Eigener Wert: 20 bis 2000 ms.")
        if ms and ms < 20:
            text += " " + tr("Kleiner als 20 ms geht nicht – GoGoHam nimmt 20 ms.")
        win = self.parent()
        while win is not None and not hasattr(win, "start_rig"):    # bis zum Hauptfenster
            win = win.parent()
        rig = getattr(win, "rig", None)
        try:
            st = rig.snapshot() if rig is not None else None
        except (AttributeError, TypeError):
            st = None
        if st is not None and getattr(st, "connected", False) and getattr(st, "query_ms", 0):
            text += "\n" + tr("Gemessen am verbundenen Gerät: {q} ms je Abfrage – GoGoHam fragt "
                              "alle {p} ms ({n}-mal pro Sekunde).", q=f"{st.query_ms:.0f}",
                              p=st.poll_ms, n=round(1000 / max(1, st.poll_ms)))
        return text

    @staticmethod
    def _mode_of(p: dict) -> str:
        if p.get("service"):
            return "service"
        return "self" if p.get("start", True) else "external"

    def _set_mode(self, mode: str) -> None:
        idx = self.startmode.findData(mode)
        if idx < 0:                         # Hintergrunddienst hier nicht möglich
            idx = self.startmode.findData("self")
        self.startmode.setCurrentIndex(max(idx, 0))

    def _free_port(self) -> int:
        used = {int(p["port"]) for p in self.slots if p}
        port = 4532
        while port in used:
            port += 1
        return port

    def current_profile(self) -> dict | None:
        """Profil so, wie es gerade im Fenster steht (für den Verbindungstest)."""
        self._store_slot()
        return self.slots[self.cur]

    # --- Gerät ---------------------------------------------------------------
    def _fill_models(self, select: int = 0) -> None:
        self._loading = True
        self.model.clear()
        shown = self._hl.filter_rigs(self.rigs, self.search.text())
        if select and not any(r.model == select for r in shown):
            r = self._hl.find_model(select)
            if r:
                shown = [r] + shown
        # Erster Eintrag: noch kein Gerät – sonst würde beim Klick auf OK unbemerkt das
        # erste Gerät der Liste als Profil angelegt
        self.model.addItem(tr("– bitte wählen –"), 0)
        for r in shown:
            extra = "  (Beta)" if r.status == "Beta" else \
                    f"  ({r.status})" if r.status not in ("Stable", "") else ""
            self.model.addItem(f"{r.label}{extra}", r.model)
        idx = self.model.findData(select) if select else 0
        self.model.setCurrentIndex(max(idx, 0))
        self._loading = False

    def _search_changed(self, _t: str) -> None:
        cur = self.model.currentData()
        self._fill_models(0)
        idx = self.model.findData(cur) if cur else -1
        if idx < 0 and self.search.text().strip() and self.model.count() > 1:
            idx = 1                       # Suche: ersten Treffer vorschlagen
        if idx >= 0:
            self.model.setCurrentIndex(idx)
        self._model_changed()

    def _model_changed(self, want_baud=None) -> None:
        if self._loading:
            return
        model = self.model.currentData()
        caps = self._hl.rig_caps(model) if model else None
        bauds = caps.bauds() if caps else list(self._hl.STANDARD_BAUDS)
        # want_baud None = Gerät gewechselt -> höchste Baudrate des neuen Geräts vorwählen
        if want_baud and int(want_baud) not in bauds:
            # so im Profil gespeichert – nicht stillschweigend ändern
            bauds = sorted(set(bauds) | {int(want_baud)})
        self.baud.clear()
        for b in bauds:
            self.baud.addItem(str(b), b)
        pick = int(want_baud) if want_baud else (caps.speed_max if caps and caps.speed_max
                                                  else bauds[-1])
        idx = self.baud.findData(pick)
        self.baud.setCurrentIndex(idx if idx >= 0 else self.baud.count() - 1)
        self.info.setText(rig_info_text(model, caps, self._hl.find_model(model) if model else None))
        serial = caps.serial if caps else True
        self.baud.setEnabled(serial)
        self._update_adv()                  # CI-V-Feld nur bei Icom (0.8.22)

    def _fill_ports(self, keep: str | None = None) -> None:
        self._fill_combo(self.device, keep if isinstance(keep, str) else self.device.currentText())
        if not isinstance(keep, str):           # Knopf „Neu suchen“: alle Listen auffrischen
            self._fill_combo(self.wk_device, self.wk_device.currentText())
            self._fill_combo(self.ptt_device, self.ptt_device.currentText())
        self._device_changed()

    def _fill_combo(self, combo: QComboBox, cur: str) -> None:
        combo.clear()
        for p in self._hl.serial_ports():
            combo.addItem(p)
        if cur:
            if combo.findText(cur) < 0:
                combo.addItem(cur)
            combo.setCurrentText(cur)
        else:
            combo.setCurrentIndex(-1)

    def _update_cw_ptt(self) -> None:
        wk = self.cw_via.currentData() == "winkey"
        self.wk_device.setEnabled(wk)
        self.btn_wk.setEnabled(wk)
        self.ptt_device.setEnabled(bool(self.ptt_via.currentData()))
        self._update_adv()

    def _check_winkey(self) -> None:
        """Knopf „WinKey prüfen“: nur die Version abfragen – sendet kein CW."""
        from .. import rigdetect, winkey
        path = self.wk_device.currentText().strip()
        self.test_result.setStyleSheet("")
        if not path:
            self.test_result.setText(tr("Bitte die Schnittstelle des WinKey wählen."))
            return
        if winkey.held_here(path):
            self.test_result.setText(tr("GoGoHam benutzt diesen WinKey gerade selbst – ob er "
                                        "verbunden ist, steht in der Statuszeile."))
            return
        if rigdetect.port_held(path):
            self.test_result.setText(tr("✘ Ein anderes Programm hat die Schnittstelle offen – "
                                        "bitte dort schließen."))
            self.test_result.setStyleSheet("color:#c62828;")
            return
        self.test_result.setText(tr("Frage den WinKey …"))
        QApplication.processEvents()
        v = winkey.probe(path)
        if v:
            self.test_result.setText(tr("✔ WinKey gefunden: {v}", v=winkey.version_text(v)))
            self.test_result.setStyleSheet("color:#1b8a3a;")
        else:
            self.test_result.setText(tr("✘ An dieser Schnittstelle antwortet kein WinKey."))
            self.test_result.setStyleSheet("color:#c62828;")

    def _device_changed(self) -> None:
        self.port_hint.setText(self._hl.port_hint(self.device.currentText()))
        if hasattr(self, "btn_perm"):
            self._update_perm()

    # --- Erkennen ------------------------------------------------------------
    def _ports_to_scan(self) -> list[str]:
        """Feld leer: alle Schnittstellen – außer denen anderer Profile und zweiten Anschlüssen."""
        import os
        dev = self.device.currentText().strip()
        if dev:
            return [dev]
        from .. import dxp
        others = {os.path.realpath(p["device"]) for i, p in enumerate(self.slots)
                  if p and i != self.cur and p.get("device")}
        return [p for p in self._hl.serial_ports() if os.path.realpath(p) not in others
                and not ("if01" in os.path.basename(p) and self._hl.port_hint(p))
                and not dxp.is_dxp(p)]               # DXP: eigener Weg (_detect_dxp)

    def _run_detect(self, port: str, wk_guard: bool = True):
        from .. import rigdetect
        if self.detect_fn:
            return self.detect_fn(port)

        def progress(baud):
            self.test_result.setText(tr("Erkenne … ({b} Baud)", b=baud))
            QApplication.processEvents()
        from .. import rigprofiles
        power = frozenset(rigprofiles.lines_on({"lines": self.lines.currentData() or ""}))
        return rigdetect.detect(port, self.rigs, progress=progress, wk_guard=wk_guard,
                                power=power)

    def _dxp_unit(self):
        """Angeschlossenes DXP, das zu dieser Erkennung passt (None = keins)."""
        import os
        from .. import dxp
        units = dxp.find_units(self._hl.serial_ports())
        dev = self.device.currentText().strip()
        if dev:
            real = os.path.realpath(dev)
            return next((u for u in units if any(os.path.realpath(p) == real for _n, p, _m in u)),
                        None)
        others = {os.path.realpath(p[k]) for i, p in enumerate(self.slots) if p and i != self.cur
                  for k in ("device", "winkey") if p.get(k)}
        return next((u for u in units if not any(os.path.realpath(p) in others
                                                 for _n, p, _m in u)), None)

    def _detect_dxp(self, unit) -> None:
        """microHAM DXP: CAT-, WinKey- und FSK-Anschluss bestimmen und eintragen (0.8.18.1)."""
        import os
        from .. import dxp, rigdetect, winkey
        self.test_result.setText(tr("microHAM DXP gefunden – erkenne die Anschlüsse …"))
        QApplication.processEvents()
        saved = (self.slots[self.cur] or {}).get("winkey", "")

        def probe_wk(p):
            if winkey.held_here(p):          # GoGoHam benutzt ihn gerade: nicht dazwischenfunken
                return -1 if saved and os.path.realpath(p) == os.path.realpath(saved) else 0
            return winkey.probe(p)
        res = dxp.identify(unit, self.rigs, probe_wk=probe_wk,
                           detect=lambda p: self._run_detect(p, wk_guard=False))
        if res.winkey:
            self.cw_via.setCurrentIndex(self.cw_via.findData("winkey"))
            self._fill_combo(self.wk_device, res.winkey)
            self._update_cw_ptt()
        det = res.detection
        if det is not None:
            self.apply_detection(det)
        elif res.cat:
            self._fill_ports(res.cat)
        parts = []
        if res.ok:
            short = lambda p: os.path.basename(p) if p else "?"   # noqa: E731
            parts.append(tr("microHAM DXP: CAT {c} · WinKey {w} ({v}) · FSK {f}", c=short(res.cat),
                            w=short(res.winkey), v=winkey.version_text(res.version) if res.version
                            else "?", f=short(res.fsk)))
            if det is not None:
                parts.append(("✔ " if det.ok else "✘ ") + rigdetect.describe(det))
            if res.text:
                parts.append(res.text)
            parts.append(tr("PTT: im DXP-Menü bei einem Anschluss „DTR = PTT“ einstellen und hier "
                            "„DTR-Leitung“ mit diesem Anschluss wählen (oder PTT über CAT lassen)."))
        else:
            parts.append("✘ " + res.text)
        self.test_result.setText("\n".join(parts))
        self.test_result.setStyleSheet("" if res.ok and (det is None or det.ok) else "color:#c62828;")
        hints = dxp.linux_hints([p for _n, p, _m in unit])
        if hints:
            self._show_commands(tr("microHAM DXP unter Linux"), hints)

    def _show_commands(self, title: str, hints) -> None:
        """Hinweise mit Befehlen zum Kopieren zeigen (der Nutzer führt sie selbst aus)."""
        from PySide6.QtWidgets import QPlainTextEdit
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        lay = QVBoxLayout(dlg)
        for text, cmd in hints:
            lab = QLabel(text)
            lab.setWordWrap(True)
            lay.addWidget(lab)
            box = QPlainTextEdit(cmd)
            box.setReadOnly(True)
            box.setMaximumHeight(70)
            lay.addWidget(box)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.resize(640, 0)
        dlg.exec()

    def _detect(self) -> None:
        from .. import rigdetect
        self.test_result.setStyleSheet("")
        self.test_result.setText(tr("Erkenne …"))
        QApplication.processEvents()
        unit = self._dxp_unit() if not self.detect_fn else None
        if unit:
            self._detect_dxp(unit)
            return
        found, failed = [], []
        for p in self._ports_to_scan():
            det = self._run_detect(p)
            if det.blocker:                       # Regel C (0.10.43): erst neu starten
                det = self._restart_blocker(p, det)
            if det.blocker and not self._rs.via_bridge(det.blocker) and self._take_over(det):
                det = self._run_detect(p)
            (found if det.ok else failed).append(det)
        if not found:
            # aussagekräftigste Meldung zeigen: „Keine Antwort“ nur, wenn es nichts anderes gibt
            det = next((d for d in failed if d.blocker or d.search), None) or \
                (failed[0] if failed else rigdetect.Detection(
                    False, tr("Keine Schnittstelle gefunden – ist das Gerät per USB angeschlossen?")))
        elif len(found) == 1:
            det = found[0]
        else:
            det = self._choose(found)
            if det is None:
                self.test_result.setText("")
                return
        self.apply_detection(det)
        self._update_perm()

    def _choose(self, found):
        import os
        from PySide6.QtWidgets import QInputDialog
        labels = [f"{d.name or d.model} – {os.path.basename(d.device)}" for d in found]
        choice, ok = QInputDialog.getItem(self, tr("Gerät erkennen"),
                                          tr("Mehrere Geräte gefunden – welches gehört zu diesem "
                                             "Profil?"), labels, 0, False)
        return found[labels.index(choice)] if ok and choice in labels else None

    def _restart_blocker(self, port: str, det):
        """Regel C (0.10.43): Ein rigctld-Dienst hängt ohne Gerät (z. B. vor der GoGoHandy-Brücke
        gestartet) – neu starten statt abschalten. Läuft er über die Brücke, wird er nie
        abgeschaltet (sonst wären Handy und die anderen Programme ohne Funkgerät)."""
        import time
        b = det.blocker
        ok, unit = self._rs.restart(b["pid"])
        if not ok:
            return det
        self.test_result.setText(tr("Starte den Dienst {u} neu …", u=unit))
        QApplication.processEvents()
        new = det
        for _ in range(8):
            getattr(self, "_sleep", time.sleep)(1)
            QApplication.processEvents()
            new = self._run_detect(port)
            if not new.blocker:
                return new
        if self._rs.via_bridge(b):
            new.text = (det.text + "\n\n" + tr(
                "Der Dienst {u} wurde neu gestartet, das Gerät antwortet aber weiterhin nicht. "
                "Hat die GoGoHandy-Brücke das Gerät? Der Dienst bleibt an, weil er über die "
                "Brücke läuft.", u=unit))
        return new

    def _take_over(self, det) -> bool:
        """Fremder rigctld blockiert die Schnittstelle: nach Zustimmung übernehmen."""
        from .. import config as cfgmod
        b = det.blocker
        o = self._rs.owner(b["pid"])
        what = tr("Systemdienst {u}", u=o["unit"]) if o["kind"] == "system" else \
            tr("Dienst {u}", u=o["unit"]) if o["unit"] else tr("rigctld (Programm-Nr. {p})", p=b["pid"])
        text = (det.text + "\n\n" +
                tr("Soll {app} die Steuerung übernehmen? Der {w} wird dann angehalten und durch "
                   "einen rigctld von {app} ersetzt, der immer den festen Namen der Schnittstelle "
                   "benutzt. WS & Co. behalten ihren Port {port}.", w=what, port=b["port"],
                   app=APP_NAME))
        if o["kind"] == "system":
            text += "\n\n" + tr("Linux fragt dafür einmal nach deinem Passwort.")
        ans = QMessageBox.question(self, tr("rigctld übernehmen"), text)
        if ans != QMessageBox.StandardButton.Yes:
            return False
        self.test_result.setText(tr("Übernehme …"))
        QApplication.processEvents()
        ok, msg = self._rs.take_over(b["pid"])
        if not ok:
            QMessageBox.warning(self, tr("rigctld übernehmen"), msg)
            return False
        # Profile, die den alten rigctld benutzt haben, bekommen sofort einen eigenen
        # Hintergrund-rigctld auf demselben Port (sonst stünden WSJT-X & Co. ohne da)
        self._store_slot()
        for i, p in enumerate(self.slots):
            if not p or p.get("start", True) or p.get("service") or int(p["port"]) != b["port"] \
                    or p.get("host", "127.0.0.1") not in ("127.0.0.1", "localhost"):
                continue
            if not p.get("device"):
                p["device"] = b["device"]
            if i == self.cur:
                self._set_mode("service")       # wird gleich neu erkannt
            elif p["device"].startswith("/dev/serial/by-id/"):
                p.update(start=False, service=True)
            else:
                p.update(start=True, service=False)   # ohne festen Namen nicht dauerhaft
        saved = self.cfg.get("rig_profiles") or []
        for i, p in enumerate(self.slots):
            q = next((q for q in saved if q.get("slot") == i), None)
            if p and i != self.cur and q and q.get("port") == p["port"]:
                q.update(start=p["start"], service=p.get("service", False),
                                device=p["device"])
        cfgmod.save(self.cfg)
        self._rs.sync([p for i, p in enumerate(self.slots) if p and i != self.cur])
        if o["kind"] == "system":
            self.cfg.setdefault("rig_replaced_services", [])
            if o["unit"] not in self.cfg["rig_replaced_services"]:
                self.cfg["rig_replaced_services"].append(o["unit"])
            # 0.8.23.4: Port merken – andere Programme erwarten dort immer einen rigctld
            self.cfg.setdefault("rig_replaced_ports", [])
            if int(b["port"]) not in self.cfg["rig_replaced_ports"]:
                self.cfg["rig_replaced_ports"].append(int(b["port"]))
            cfgmod.save(self.cfg)
        self._takeover_port = b["port"]
        return True

    def apply_detection(self, det) -> None:
        """Ergebnis der Erkennung ins Fenster eintragen (alles bleibt änderbar)."""
        from .. import rigdetect
        if det.device:
            self._fill_ports(det.device)
        if det.ok and det.model:
            self.search.setText("")
            self._fill_models(det.model)
            self._model_changed(det.baud or None)
            if not self.name.text().strip():
                self.name.setText(det.name or f"Hamlib {det.model}")
            if det.rigctld_port:
                self._set_mode("external")
                self.host.setText("127.0.0.1")
                self.port.setValue(det.rigctld_port)
            elif getattr(self, "_takeover_port", 0):
                self._set_mode("service")
                self.host.setText("127.0.0.1")
                if not any(p and i != self.cur and int(p["port"]) == self._takeover_port
                           for i, p in enumerate(self.slots)):
                    self.port.setValue(self._takeover_port)
        elif det.search:
            self.search.setText(det.search)
            self._search_changed(det.search)
            if det.baud:
                self._model_changed(det.baud)
        self._takeover_port = 0
        self.test_result.setText(("✔ " if det.ok else "✘ ") + rigdetect.describe(det))
        self.test_result.setStyleSheet("color:#1b8a3a;" if det.ok else "color:#c62828;")

    # --- Test ----------------------------------------------------------------
    def _test(self) -> None:
        prof = self.current_profile()
        if not prof:
            self.test_result.setText(tr("Bitte zuerst ein Funkgerät wählen."))
            return
        self.test_result.setText(tr("Teste … (bis zu 8 Sekunden)"))
        QApplication.processEvents()
        res = self.test_fn(prof) if self.test_fn else self._hl.test_profile(prof)
        self.tested = True
        self.test_result.setText(("✔ " if res.ok else "✘ ") + res.text)
        self.test_result.setStyleSheet("color:#1b8a3a;" if res.ok else "color:#c62828;")
        self._update_perm()

    def _update_perm(self) -> None:
        """Knopf „Berechtigung einrichten“ nur zeigen, wenn eine Schnittstelle gesperrt ist."""
        from .. import permissions
        try:
            paths = self._ports_to_scan()
        except Exception:  # noqa: BLE001 – Anzeige darf nie stören
            paths = []
        self._perm_blocked = permissions.blocked(paths)
        self.btn_perm.setVisible(bool(self._perm_blocked))

    def _fix_permission(self) -> None:
        from .. import permissions
        if not getattr(self, "_perm_blocked", None):
            return
        group = permissions.group_of(self._perm_blocked[0])
        PermissionDialog(group, self).exec()

    def _test_ptt(self) -> None:
        prof = self.current_profile()
        if not prof:
            self.test_result.setText(tr("Bitte zuerst ein Funkgerät wählen."))
            return
        ans = QMessageBox.question(
            self, tr("PTT testen"),
            tr("Das Funkgerät geht jetzt für 1 Sekunde auf SENDEN und danach von selbst wieder auf "
               "Empfang.\n\nIst eine Antenne oder ein Dummy-Load angeschlossen, die Leistung "
               "passend eingestellt und die Frequenz frei?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.test_result.setStyleSheet("")
        self.test_result.setText(tr("Sende 1 Sekunde …"))
        QApplication.processEvents()
        # Auch PTT über DTR/RTS geht über rigctld (0.10.45) – nie die Schnittstelle selbst öffnen
        res = self.ptt_fn(prof) if self.ptt_fn else self._hl.ptt_test(prof)
        self.test_result.setText(("✔ " if res.ok else "✘ ") + res.text)
        self.test_result.setStyleSheet("color:#1b8a3a;" if res.ok else "color:#c62828;")

    def apply(self) -> bool:
        """Eingaben in die Einstellungen übernehmen; False = Eingabe fehlerhaft."""
        from .. import rigprofiles
        self._store_slot()
        profs = [dict(p, slot=i) for i, p in enumerate(self.slots) if p]
        ports = [p["port"] for p in profs if p.get("conn") != "remote"]
        if len(set(ports)) != len(ports):
            self.test_result.setText(tr("✘ Zwei Profile haben denselben Port – jedes Funkgerät "
                                     "braucht seinen eigenen rigctld-Port (4532, 4533 …)."))
            return False
        for p in profs:
            msg = cw_ptt_problem(p) or rigprofiles.interface_problem(p) or net_problem(p)
            if msg:
                self.test_result.setText("✘ " + tr("{name}: {msg}", name=p["name"], msg=msg))
                return False
        self._check_replaced(profs)
        self._offer_handover(profs)
        self.cfg["rig_profiles"] = profs
        self.cfg["rig_enabled"] = self.enabled.isChecked()
        if profs:
            idx = sum(1 for p in self.slots[:self.cur] if p) if self.slots[self.cur] else 0
            rigprofiles.apply_profile(self.cfg, idx)
        else:
            self.cfg.update(rig_profile=0, rig_model=0, rig_device="", rig_baud=0, rig_extra="")
        return True

    def replaced_ports(self) -> set[int]:
        """Ports, deren Systemdienst GoGoHam übernommen hat. Ältere Einstellungen kennen nur
        den Dienstnamen – dann gilt der Standard-Port 4532 (dort lief der Systemdienst)."""
        ports = {int(x) for x in (self.cfg.get("rig_replaced_ports") or [])}
        if not ports and self.cfg.get("rig_replaced_services"):
            ports = {4532}
        return ports

    def _check_replaced(self, profs: list[dict]) -> None:
        """0.8.23.4: Hat GoGoHam einen Systemdienst ersetzt, verlassen sich andere Programme
        (Log-Programme, WSJT-X …) auf einen immer laufenden rigctld auf diesem Port. Steht das
        Profil dort auf „nur solange GoGoHam läuft“, verlieren sie die Verbindung, sobald
        GoGoHam zu ist – dann einmal fragen und „dauerhaft“ vorschlagen."""
        if not self._svc_ok:
            return
        asked = {int(x) for x in (self.cfg.get("rig_selfmode_ok") or [])}
        for p in profs:
            port = int(p["port"])
            if port not in self.replaced_ports() or port in asked or not p.get("start", True) \
                    or p.get("service") or p.get("host", "127.0.0.1") not in ("127.0.0.1", "localhost"):
                continue
            ans = QMessageBox.question(
                self, tr("rigctld dauerhaft einrichten?"),
                tr("GoGoHam hat früher den Systemdienst ersetzt, der auf Port {port} immer einen "
                   "rigctld bereitgestellt hat. Andere Programme (Log-Programme, WSJT-X …) "
                   "erwarten ihn dort weiterhin.\n\nDas Profil „{name}“ startet rigctld aber nur, "
                   "solange GoGoHam läuft – ist GoGoHam zu, bekommen diese Programme keine "
                   "Verbindung (z. B. „Ein-/Ausgabefehler“).\n\nSoll GoGoHam den rigctld für "
                   "dieses Profil dauerhaft einrichten?", port=port, name=p["name"]),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if ans == QMessageBox.StandardButton.Yes:
                p.update(start=False, service=True)
                if self.slots[p["slot"]]:
                    self.slots[p["slot"]].update(start=False, service=True)
                if p["slot"] == self.cur:
                    self._set_mode("service")
            else:
                self.cfg.setdefault("rig_selfmode_ok", []).append(port)   # nicht wieder fragen

    def _offer_handover(self, profs: list[dict]) -> None:
        """0.8.23.5: Fällt ein dauerhafter rigctld weg (Profil gelöscht oder umgestellt), fragen,
        ob er für andere Programme weiterlaufen soll (Standard: ja) – dann wird er als
        eigenständiger Dienst übergeben und GoGoHam fasst ihn nicht mehr an."""
        keep = {int(p["port"]) for p in profs if p.get("service")}
        for old in self.cfg.get("rig_profiles") or []:
            port = int(old.get("port") or 0)
            if not old.get("service") or port in keep:
                continue
            unit = self._rs.unit_name(port)
            if not os.path.exists(os.path.join(self._rs.unit_dir(), unit)):
                continue
            ans = QMessageBox.question(
                self, tr("rigctld weiterlaufen lassen?"),
                tr("Für „{name}“ läuft ein dauerhafter rigctld auf Port {port}. Andere Programme "
                   "(Log-Programme, WSJT-X …) benutzen ihn vielleicht.\n\nJa: Er läuft als "
                   "eigenständiger Dienst weiter – GoGoHam ändert oder entfernt ihn nicht mehr.\n"
                   "Nein: Er wird beendet und entfernt.", name=old.get("name", ""), port=port),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if ans == QMessageBox.StandardButton.Yes:
                errors = self._rs.handover(unit)
                if errors:
                    QMessageBox.warning(self, tr("rigctld weiterlaufen lassen?"), "\n".join(errors))

    def accept(self) -> None:
        if self.apply():
            super().accept()
def cw_ptt_problem(p: dict) -> str:
    """Passen WinKey- und PTT-Schnittstelle zum Profil? "" = in Ordnung."""
    import os
    same = lambda a, b: bool(a) and bool(b) and os.path.realpath(a) == os.path.realpath(b)  # noqa: E731
    if p.get("ptt_line") and not p.get("ptt_device"):
        return tr("Für PTT über {line} bitte die Schnittstelle wählen.", line=p["ptt_line"])
    if same(p.get("winkey"), p.get("device")):
        return tr("WinKey und CAT brauchen verschiedene Schnittstellen.")
    return ""


def rig_info_text(model, caps, entry) -> str:
    """Infozeile unter der Geräteauswahl."""
    if not model:
        return ""
    from ..bands import band_label
    from ..hamlib import STATUS_DE
    parts = [tr("Hamlib-Nr. {model}", model=model)]
    status = (entry.status if entry else "") or (caps.status if caps else "")
    if STATUS_DE.get(status):
        parts.append("⚠ " + STATUS_DE[status])
    if caps:
        bands = caps.bands()
        if bands:
            parts.append(tr("Bänder: ") + ", ".join(band_label(b) for b in bands))
        parts.append(tr("Sprachspeicher über CAT: ") + ("ja" if caps.can_voice else "nein"))
        parts.append(tr("CW über CAT: ") + ("ja" if caps.can_morse else "nein"))
        if not caps.serial:
            parts.append(tr("keine serielle Schnittstelle – bei „Schnittstelle“ ggf. "
                         "Rechner:Port eintragen (z. B. localhost:12345)"))
    return " · ".join(parts)


class WsjtxDialog(QDialog):
    def __init__(self, cfg: dict, parent=None, embedded: bool = False):
        super().__init__(parent)
        self.setWindowTitle(tr("WS und andere FT8-Programme"))
        self.cfg = cfg
        form = QFormLayout()
        self.enabled = QCheckBox(tr("Geloggte QSOs aus WS übernehmen"))
        self.enabled.setChecked(cfg["wsjtx_enabled"])
        self.address = QLineEdit(cfg["wsjtx_address"])
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(cfg["wsjtx_port"]))
        form.addRow(self.enabled)
        form.addRow(tr("UDP-Adresse:"), self.address)
        form.addRow(tr("UDP-Port:"), self.port)
        self.lock = QCheckBox(tr("Funkgerät nur anzeigen, solange ein FT8-Programm aktiv ist "
                              "(GoGoHam steuert und sendet dann nicht)"))
        self.lock.setChecked(cfg.get("wsjtx_lock_rig", True))
        form.addRow(self.lock)
        hint = QLabel(tr("In WS unter Einstellungen → Berichten den UDP-Server auf diese "
                      "Adresse und diesen Port stellen.\n"
                      "Soll ein Log-Programm gleichzeitig mithören, in beiden Programmen die "
                      "Multicast-Adresse 224.0.0.1 verwenden.\n"
                      "Für den WW Digi in WS unter Erweitert → "
                      "„Special operating activity: WW Digi Contest“ aktivieren."))
        hint.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        if not embedded:
            lay.addWidget(_buttons(self, "wsjtx"))

    def apply(self) -> bool:
        """Eingaben in die Einstellungen übernehmen; False = Eingabe fehlerhaft."""
        self.cfg.update({
            "wsjtx_enabled": self.enabled.isChecked(),
            "wsjtx_address": self.address.text().strip() or "127.0.0.1",
            "wsjtx_port": self.port.value(),
            "wsjtx_lock_rig": self.lock.isChecked(),
        })
        return True

    def accept(self) -> None:
        if self.apply():
            super().accept()
class MacroDialog(QDialog):
    def __init__(self, cfg: dict, parent=None, embedded: bool = False):
        from ..voice import DEFAULT_SSB_TEXT
        super().__init__(parent)
        self.setWindowTitle(tr("Funktionstasten F1–F8"))
        self.cfg = cfg
        # Woher die SSB-Ansagen kommen (ab 0.8.11)
        self.cb_source = QComboBox()
        self.cb_source.addItem(tr("Sprachspeicher im Funkgerät"), "rig")
        self.cb_source.addItem(tr("Eigene Aufnahmen in GoGoHam (Einstellungen → Ton & Ansagen)"),
                               "gogoham")
        self.cb_source.setCurrentIndex(1 if cfg.get("voice_source") == "gogoham" else 0)
        src = QFormLayout()
        src.addRow(tr("SSB-Ansagen kommen aus:"), self.cb_source)
        grid = QGridLayout()
        grid.addWidget(QLabel(tr("<b>Taste</b>")), 0, 0)
        grid.addWidget(QLabel(tr("<b>SSB: Name</b>")), 0, 1)
        grid.addWidget(QLabel(tr("<b>Sprachspeicher</b>")), 0, 2)
        self.lbl_ssb_text = QLabel(tr("<b>SSB: eigene Aufnahmen</b>"))
        grid.addWidget(self.lbl_ssb_text, 0, 3)
        grid.addWidget(QLabel(tr("<b>CW: Name</b>")), 0, 4)
        grid.addWidget(QLabel(tr("<b>CW-Text</b>")), 0, 5)
        self.rows = []
        for i in range(1, 9):
            k = f"F{i}"
            ssb = cfg["macros_ssb"].get(k, {"label": "", "voice": i})
            cw = cfg["macros_cw"].get(k, {"label": "", "text": ""})
            sl = QLineEdit(ssb.get("label", ""))
            sv = QSpinBox()
            sv.setRange(0, 8)
            sv.setValue(int(ssb.get("voice", 0)))
            sv.setSpecialValueText(tr("aus"))
            st = QLineEdit(ssb.get("text", DEFAULT_SSB_TEXT.get(k, "")))
            st.setMinimumWidth(200)
            cl = QLineEdit(cw.get("label", ""))
            ct = QLineEdit(cw.get("text", ""))
            ct.setMinimumWidth(220)
            for col, w in enumerate((QLabel(k), sl, sv, st, cl, ct)):
                grid.addWidget(w, i, col)
            self.rows.append((k, sl, sv, st, cl, ct))
        hint = QLabel(tr("Platzhalter für CW und eigene Aufnahmen: {MYCALL} {CALL} {EXCH} {RST}. "
                         "Bei eigenen Aufnahmen stehen feste Ansagen in eckigen Klammern: [CQ] "
                         "[TU] [QRZ] [AGN] [NR] [CALLQ] [X1]–[X4]; alles andere wird "
                         "buchstabiert. Die Sprachspeicher (1–8) werden im IC-7300 unter VOICE "
                         "aufgenommen."))
        hint.setWordWrap(True)
        auto = QFormLayout()
        self.ac_msg = QSpinBox()
        self.ac_msg.setRange(1, 60)
        self.ac_msg.setSuffix(" s")
        self.ac_msg.setValue(int(cfg.get("autocq_msg_sec", 3)))
        self.ac_listen = QSpinBox()
        self.ac_listen.setRange(1, 120)
        self.ac_listen.setSuffix(" s")
        self.ac_listen.setValue(int(cfg.get("autocq_listen_sec", 8)))
        auto.addRow(QLabel(tr("<b>Auto-CQ</b> (Strg+R): F1 wird automatisch wiederholt")))
        auto.addRow(tr("Länge des CQ-Rufs:"), self.ac_msg)
        auto.addRow(tr("Hörpause danach:"), self.ac_listen)
        lay = QVBoxLayout(self)
        lay.addLayout(src)
        lay.addLayout(grid)
        lay.addWidget(hint)
        lay.addLayout(auto)
        if not embedded:
            lay.addWidget(_buttons(self, "fkeys"))
        self.cb_source.currentIndexChanged.connect(lambda _i: self._source_changed())
        self._source_changed()

    def _source_changed(self) -> None:
        own = self.cb_source.currentData() == "gogoham"
        for _k, _sl, sv, st, _cl, _ct in self.rows:
            sv.setEnabled(not own)
            st.setEnabled(own)
        # Mit eigenen Aufnahmen kennt GoGoHam die Länge des CQ-Rufs selbst
        self.ac_msg.setEnabled(not own)

    def apply(self) -> bool:
        """Eingaben in die Einstellungen übernehmen; False = Eingabe fehlerhaft."""
        for k, sl, sv, st, cl, ct in self.rows:
            self.cfg["macros_ssb"][k] = {"label": sl.text(), "voice": sv.value(),
                                         "text": st.text()}
            self.cfg["macros_cw"][k] = {"label": cl.text(), "text": ct.text()}
        self.cfg["voice_source"] = self.cb_source.currentData()
        self.cfg["autocq_msg_sec"] = self.ac_msg.value()
        self.cfg["autocq_listen_sec"] = self.ac_listen.value()
        return True

    def accept(self) -> None:
        if self.apply():
            super().accept()


class QsoEditDialog(QDialog):
    def __init__(self, q: Qso, exch_label: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("QSO bearbeiten – {call}", call=q.call))
        self.q = q
        form = QFormLayout()
        self.time = QLineEdit(q.time)
        self.call = QLineEdit(q.call)
        self.band = _combo(BAND_NAMES, q.band)
        modes = list(RIG_MODES)
        if q.mode and q.mode not in modes:
            modes.append(q.mode)
        self.mode = _combo(modes, q.mode)
        self.freq = QLineEdit(f"{q.freq / 1000:.2f}" if q.freq else "")
        self.rst_s = QLineEdit(q.rst_s)
        self.exch_s = QLineEdit(q.exch_s)
        self.rst_r = QLineEdit(q.rst_r)
        self.exch_r = QLineEdit(q.exch_r)
        form.addRow(tr("Zeit (UTC):"), self.time)
        form.addRow(tr("Rufzeichen:"), self.call)
        form.addRow(tr("Band (m):"), self.band)
        form.addRow(tr("Mode:"), self.mode)
        form.addRow(tr("Frequenz (kHz):"), self.freq)
        form.addRow(tr("RST gesendet:"), self.rst_s)
        form.addRow(tr("{exch} gesendet:", exch=exch_label), self.exch_s)
        form.addRow(tr("RST empfangen:"), self.rst_r)
        form.addRow(tr("{exch} empfangen:", exch=exch_label), self.exch_r)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(_buttons(self, "log-tabelle"))

    def accept(self) -> None:
        import re
        t = self.time.text().strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$", t):
            QMessageBox.warning(self, tr("Zeit"), tr("Format: JJJJ-MM-TT HH:MM:SS"))
            return
        if len(t) == 16:
            t += ":00"
        try:
            freq = int(round(float(self.freq.text().replace(",", ".")) * 1000)) \
                if self.freq.text().strip() else 0
        except ValueError:
            QMessageBox.warning(self, tr("Frequenz"), tr("Frequenz bitte in kHz angeben."))
            return
        q = self.q
        q.time = t
        q.call = self.call.text().strip().upper()
        q.band = self.band.currentText()
        q.mode = self.mode.currentText()
        q.freq = freq
        q.rst_s = self.rst_s.text().strip()
        q.exch_s = self.exch_s.text().strip().upper()
        q.rst_r = self.rst_r.text().strip()
        q.exch_r = self.exch_r.text().strip().upper()
        super().accept()


class CallbookDialog(QDialog):
    """Zugangsdaten für HamQTH und QRZ.com (Name/QTH beim ADIF-Export)."""

    def __init__(self, cfg: dict, parent=None, embedded: bool = False):
        super().__init__(parent)
        self.setWindowTitle(tr("Name und QTH (HamQTH / QRZ.com)"))
        self.cfg = cfg
        form = QFormLayout()
        self.enabled = QCheckBox(tr("Beim ADIF-Export Name und QTH nachschlagen"))
        self.enabled.setChecked(cfg.get("callbook_enabled", True))
        self.h_user = QLineEdit(cfg.get("hamqth_user", ""))
        self.h_pass = QLineEdit(cfg.get("hamqth_password", ""))
        self.q_user = QLineEdit(cfg.get("qrz_user", ""))
        self.q_pass = QLineEdit(cfg.get("qrz_password", ""))
        for w in (self.h_pass, self.q_pass):
            w.setEchoMode(QLineEdit.EchoMode.Password)
        self.order = QComboBox()
        self.order.addItem(tr("HamQTH zuerst, dann QRZ.com"), ["hamqth", "qrz"])
        self.order.addItem(tr("QRZ.com zuerst, dann HamQTH"), ["qrz", "hamqth"])
        if cfg.get("callbook_order", ["hamqth", "qrz"])[0] == "qrz":
            self.order.setCurrentIndex(1)
        form.addRow(self.enabled)
        form.addRow(QLabel(tr("<b>HamQTH</b> (kostenloses Konto auf hamqth.com)")))
        form.addRow(tr("Benutzer:"), self.h_user)
        form.addRow(tr("Passwort:"), self.h_pass)
        form.addRow(QLabel(tr("<b>QRZ.com</b> (für die Abfrage ist ein XML-Abo nötig)")))
        form.addRow(tr("Benutzer:"), self.q_user)
        form.addRow(tr("Passwort:"), self.q_pass)
        form.addRow(tr("Reihenfolge:"), self.order)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        from PySide6.QtWidgets import QPushButton
        test = QPushButton(tr("Zugangsdaten testen"))
        test.clicked.connect(self.test)
        hint = QLabel(tr("Die Zugangsdaten werden nur lokal in deiner Konfigurationsdatei "
                      "gespeichert (nur für dich lesbar)."))
        hint.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(test)
        lay.addWidget(self.result)
        lay.addWidget(hint)
        if not embedded:
            lay.addWidget(_buttons(self, "callbook"))

    def _values(self) -> dict:
        return {
            "callbook_enabled": self.enabled.isChecked(),
            "hamqth_user": self.h_user.text().strip(),
            "hamqth_password": self.h_pass.text(),
            "qrz_user": self.q_user.text().strip(),
            "qrz_password": self.q_pass.text(),
            "callbook_order": self.order.currentData(),
        }

    def test(self) -> None:
        from ..callbook import CallbookError, services_from_config
        services = services_from_config(self._values())
        if not services:
            self.result.setText(tr("Keine Zugangsdaten eingetragen."))
            return
        lines = []
        for svc in services:
            try:
                svc.login()
                lines.append(tr("✔ {name}: Anmeldung erfolgreich", name=svc.name))
            except (CallbookError, OSError, Exception) as e:  # noqa: BLE001
                lines.append(f"✘ {svc.name}: {e}")
        self.result.setText("\n".join(lines))

    def apply(self) -> bool:
        """Eingaben in die Einstellungen übernehmen; False = Eingabe fehlerhaft."""
        self.cfg.update(self._values())
        return True

    def accept(self) -> None:
        if self.apply():
            super().accept()
def _open_link(url: str) -> None:
    """Link aus einem Text öffnen; E-Mail-Links über xdg-open (siehe mailopen)."""
    from .. import mailopen
    if url.startswith("mailto:"):
        mailopen.open_mail(url, mailopen.qt_open)
    else:
        QDesktopServices.openUrl(QUrl(url))


EXPORT_FORMATS = {"cabrillo": "Cabrillo", "adif": "ADIF", "edi": "EDI"}


class ExportDialog(QDialog):
    """Log-Format wählen; das vom Contest verlangte ist vorausgewählt."""

    def __init__(self, contest, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Log exportieren"))
        wanted = getattr(contest, "log_format", "cabrillo") or "cabrillo"
        from .. import bbt
        if not getattr(contest, "free", False) and bbt.is_bbt(contest):
            wanted = "bbt"                        # Bayerischer Bergtag: Deckblatt + Log (0.10.42)
        self.format = QComboBox()
        keys = ("adif",) if getattr(contest, "free", False) else \
            ("bbt", "edi", "adif") if wanted == "bbt" else \
            ("edi", "adif") if wanted == "edi" else ("cabrillo", "adif")
        for key in keys:
            name = tr("BBT-Deckblatt + Log (Text)") if key == "bbt" else EXPORT_FORMATS[key]
            label = name + (tr("  (verlangt der Contest)") if key == wanted
                                           and not getattr(contest, "free", False) else "")
            self.format.addItem(label, key)
        idx = self.format.findData(wanted)
        self.format.setCurrentIndex(max(idx, 0))
        hint = QLabel(tr("Das freie Log wird als ADIF gespeichert – zum Hochladen bei LoTW, eQSL, "
                         "DCL oder QRZ.com und für dein Log-Programm.")
                      if getattr(contest, "free", False) else export_hint(contest.name, wanted))
        hint.setWordWrap(True)
        form = QFormLayout()
        form.addRow(tr("Format:"), self.format)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addWidget(_buttons(self, "export"))

    def choice(self) -> str:
        return self.format.currentData() or "cabrillo"


def export_hint(name: str, wanted: str) -> str:
    if wanted == "bbt":
        return (tr("{name} verlangt je Band ein BBT-Deckblatt mit Logblatt – kein EDI. GoGoHam "
                   "schreibt beides als Textdatei, eine je Band. EDI und ADIF sind für deine "
                   "eigenen Unterlagen.", name=name))
    if wanted == "edi":
        return (tr("{name} verlangt das EDI-Format (UKW): GoGoHam schreibt eine Datei je Band. "
                   "ADIF ist für dein Log-Programm (z. B. QLog, CQRLOG oder KLog).", name=name))
    if wanted == "cabrillo":
        return (tr("Für die Einreichung bei {name} braucht man Cabrillo. ADIF ist "
                   "für dein Log-Programm (z. B. QLog, CQRLOG oder KLog).", name=name))
    return tr("{name} verlangt {fmt}.", name=name, fmt=EXPORT_FORMATS.get(wanted, wanted))


def rules_source_text(cls) -> str:
    src = getattr(cls, "rules_source", "builtin")
    rev = getattr(cls, "rules_revision", 1)
    if src == "user":
        return tr("eigene Regel-Datei: {rules_path}", rules_path=cls.rules_path)
    if src == "download":
        return tr("von GitHub (Revision {rev})", rev=rev)
    if src == "log":
        return tr("im Log gespeichert (Revision {rev})", rev=rev)
    return tr("eingebaut (Revision {rev})", rev=rev)


def newer_rules(log_cls):
    """Aktuelle Regeln, falls sie sich von denen im Log unterscheiden (sonst None)."""
    cur = CONTESTS.get(log_cls.id)
    if cur is None or cur.rules == log_cls.rules:
        return None
    return cur


def newer_text(cur) -> str:
    when = ""
    if cur.rules_checked:
        y, m = cur.rules_checked.split("-")
        when = tr(", geprüft {int:02d}/{y}", int=int(m), y=y)
    where = {"builtin": "eingebaut", "download": tr("von GitHub"),
             "user": tr("eigene Regel-Datei")}.get(getattr(cur, "rules_source", ""), "")
    return (tr("Es gibt andere Regeln für diesen Contest (Revision "
               "{rules_revision}{when}{p3}). Das Log benutzt weiter seine "
               "gespeicherten Regeln, bis du sie übernimmst.", rules_revision=cur.rules_revision, when=when, p3=', ' + where if where else ''))


def rules_status(cls, today=None) -> tuple[str, bool]:
    """Text zum Regelstand und ob er älter als ein Jahr ist."""
    import datetime as _dt
    checked = getattr(cls, "rules_checked", "")
    if not checked:
        return tr("Regelstand unbekannt – bitte die Ausschreibung prüfen."), True
    y, m = (int(x) for x in checked.split("-"))
    months = [tr("Januar"), tr("Februar"), tr("März"), tr("April"), tr("Mai"), tr("Juni"),
              tr("Juli"), tr("August"), tr("September"), tr("Oktober"), tr("November"),
              tr("Dezember")]
    today = today or _dt.date.today()
    age = (today.year - y) * 12 + (today.month - m)
    text = tr("Regeln geprüft: {p1} {y}", p1=months[m - 1], y=y)
    if age >= 12:
        return (text + tr(" – das ist über ein Jahr her! Bitte die aktuelle Ausschreibung "
                "prüfen, bevor du loslegst.")), True
    return text, False


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        from .. import __version__
        self.setWindowTitle(tr("Über GoGoHam"))
        self.setMinimumWidth(560)
        features = "".join(f"<li>{t}</li>" for t in (
            tr("Live-Wertung beim Tippen: Dupe, neue Multis, QSO-Punkte und Wert fürs Gesamtergebnis"),
            tr("Super Check Partial mit Farben, Call-History, Infobox mit Flagge, Land, "
               "Multi-Status, Short/Long Path und Entfernung"),
            tr("{n} Contests auf Kurzwelle und UKW als lesbare Regel-Dateien – eigene Regeln "
               "möglich, neue und geänderte automatisch von GitHub; Contest-Kalender (Termine per "
               "QR-Code aufs Handy, mit Erinnerung) und Suche beim Anlegen eines Logs",
               n=len(CONTESTS) - 1),                 # ohne das freie Log
            tr("CAT über Hamlib (rigctld) für viele Funkgeräte, mit Geräteerkennung und bis zu fünf "
               "Profilen (das zuletzt benutzte startet wieder), gemeinsam mit WS nutzbar; "
               "QSOs aus WS (FT8/FT4/FT2) übernehmen"),
            tr("Funkgeräte auch über LAN/WLAN: Icom (IC-705, IC-7610, IC-9700 …) direkt ohne "
               "Zusatzprogramm, mit Ton übers Netz als eigene Soundkarte; andere Geräte über "
               "Hamlib oder an einem anderen Rechner im Netz (Beta)"),
            tr("Einstellungen → Operator: deine Angaben (Rufzeichen, Locator, DOK, Lizenz, "
               "Geburtsdatum …) an einer Stelle – neue Logs sind damit schon ausgefüllt"),
            tr("Zusatzprogramme WS (DG2YCB, immer die neueste Version direkt "
               "vom Entwickler bzw. aus dem AUR) und fldigi (neueste Version von Flathub) – auf "
               "Debian, Ubuntu, Fedora, openSUSE und Arch: per Klick installieren, "
               "aktualisieren und deinstallieren, "
               "die Verbindung zu GoGoHam, Rufzeichen, Locator und die Soundkarte des Funkgeräts "
               "richtet GoGoHam selbst ein (Soundkarte wird über USB erkannt); WS in der "
               "Systemsprache"),
            tr("Willkommensfenster beim ersten Start: was man der Reihe nach einrichtet"),
            tr("Alle Fenster passen auf den Bildschirm, auch auf Laptops mit Taskleiste – "
               "zu viel Inhalt lässt sich scrollen, die Knöpfe bleiben sichtbar"),
            tr("Passend zum Contest startet GoGoHam fldigi (RTTY) oder das FT8-Programm selbst – "
               "fertig eingerichtet; gefunkt wird dort, geloggt und gewertet in GoGoHam"),
            tr("RTTY über fldigi: geloggte QSOs landen sofort in GoGoHam, das Rufzeichen aus "
               "fldigi zeigt GoGoHam mit Dupe, neuem Multi und Infobox; Contest-Makros in fldigi, "
               "Sendepegel automatisch einmessen"),
            tr("RTTY-Contests: CQ WW RTTY, CQ WPX RTTY, ARRL RTTY Roundup und WAE RTTY (QTCs in "
               "beide Richtungen)"),
            tr("Live-Stick: GoGoHam vom USB-Stick an jedem Rechner – Platzanzeige, Austausch-Ordner "
               "(auch unter Windows lesbar) mit Ordnern für Exporte und Log-Sicherung, Uhrzeit passend zu "
               "Rechner und Standort (Zeitzone aus dem Locator), "
               "Herunterfahren und Zurücksetzen auf Werkseinstellungen, GoGoHam per Knopf aktualisieren"),
            tr("Mit install.sh installiert: GoGoHam per Knopf aktualisieren – vorher zur Probe "
               "geladen, Rückweg zur vorigen Version"),
            tr("CW über das Funkgerät oder einen WinKey (auch microHAM DXP), CW-Texte und "
               "Sprachspeicher auf F1–F8, Sprachausgabe mit der eigenen Stimme"),
            tr("Auto-CQ und „Enter sendet“ für Run und S&P"),
            tr("DX-Cluster mit Bandmap (Multis auf anderen Bändern markiert), Bakenanzeige, "
               "Funkwetter und Bandöffnungs-Vorschau"),
            tr("Grayline-Karte mit Short/Long Path, Baken und Spots; Rotorsteuerung mit "
               "Kompassrose"),
            tr("QTC für den WAE, DOK-Prüfung für DARC-Contests, Leistungsklassen für die AGCW-QRP-Contests, "
               "ARRL-Sections für ARRL 160 m"),
            tr("GPS-Empfänger per USB: einstecken genügt – Standort, Locator und Uhrzeit, auch "
               "portabel ohne Internet; USB-Geräte werden sofort freigegeben, ohne neu anmelden"),
            tr("Stationslog für Multi-OP: mehrere Rechner im selben Netzwerk, ein gemeinsames Log, "
               "auch ohne Router; Kategorien Multi-Single/Two/Multi mit Bandregeln; Fenster "
               "„Station“ mit allen Plätzen (Band, Frequenz, Operator, Rate), Warnung bei gleichem "
               "Band und Nachrichten zwischen den Plätzen"),
            tr("Export als Cabrillo, vollständiges ADIF und EDI (UKW), Name/QTH über HamQTH "
               "und QRZ.com, Log-Prüfung vor dem Einreichen; nach dem Export der Einsendeweg (E-Mail oder "
               "Upload, Einsendeschluss) mit Ordner und markierter Log-Datei"),
            tr("Bayerischer Bergtag: BBT-Deckblatt und Logblatt je Band als Textdatei – ohne "
               "Zusatzprogramm"),
            tr("Mit GoGoHome und GoGoHandy gleichzeitig: ein rigctld je Funkgerät, WSJT-X und "
               "fldigi für alle Programme; PTT über DTR/RTS schaltet der rigctld für alle"),
            tr("Sende-Wächter: Stürzt GoGoHam beim Senden ab oder hängt es, schaltet das "
               "Funkgerät von selbst auf Empfang"),
            tr("Übersicht der Multis je Band, Rate-Grafik, Contest-Uhr mit Betriebszeit, "
               "Live-Score an Online-Scoreboards"),
            tr("Übungsmodus für CW und SSB: Run (erfundene Stationen rufen an), S&P am VFO-Knopf "
               "und gemischt, mit Auswertung – nichts wird gesendet"),
            tr("Ansagen per Sprachausgabe – auch für sehbehinderte Funkamateure"),
            tr("Automatische Sicherungen mit Reparatur, Uhrzeit-Prüfung, Fehlerbericht"),
            tr("Einstellbare Log-Spalten je Contest, Designs hell und dunkel, Oberfläche in "
               "{n} Sprachen, Handbuch auf Deutsch und Englisch mit Suche",
               n=len(_languages())),
            tr("Designs „Franken“ und „Nightshift“ (je hell und dunkel), Warnfarben in "
               "jedem Design gut lesbar"),
            tr("Funkgerät gleichzeitig mit dem Handy nutzen: GoGoHam erkennt die "
               "GoGoHandy-Brücke und geht von selbst über sie"),
        ))
        sources = "".join(f"<li>{t}</li>" for t in (
            tr("Contest-Regeln: die Ausschreibungen der Veranstalter – ein Wächter auf GitHub prüft "
               "sie jede Woche auf Änderungen"),
            tr("Länderdatei cty.dat / cty.csv: Jim Reisert, AD1C – country-files.com"),
            tr("Super Check Partial (MASTER.SCP): supercheckpartial.com"),
            tr("Flaggen: Flagpedia / flagcdn.com"),
            tr("Rufzeichen-Daten: HamQTH.com und QRZ.com"),
            tr("Call-History-Dateien: N1MM Logger+ Community"),
            tr("DOK-Listen: DARC (darc.de, auch Sonder-DOKs) und VFDB (vfdb.org)"),
            tr("DX-Cluster: voreingestellt DB0SUE (db0sue.de), jeder andere Knoten möglich"),
            tr("Bakenanzeige: Reverse Beacon Network (reversebeacon.net)"),
            tr("Funkwetter: NOAA Space Weather Prediction Center (swpc.noaa.gov)"),
            tr("Live-Score: contestonlinescore.com, Score Distributor"),
            tr("Kartendaten und Reliefbild: Natural Earth (naturalearthdata.com, gemeinfrei)"),
            tr("Satellitenbilder: NASA Earth Observatory (Blue Marble: Next Generation von Reto "
               "Stöckli, Black Marble 2016)"),
            tr("Uhrzeit-Prüfung: NTP Pool Project (pool.ntp.org)"),
            tr("Natürliche Stimmen: Piper (github.com/rhasspy/piper, MIT-Lizenz) mit den Stimmen "
               "„Thorsten“ (Thorsten-Voice, CC0), „Cori“ (LibriVox, gemeinfrei) und „libritts_r“ "
               "(Datensatz LibriTTS-R, CC BY 4.0, openslr.org/141) von huggingface.co/rhasspy"),
        ))
        rules_link = ('<a href="https://github.com/do2ggh/GoGoHam-rules">'
                      'github.com/do2ggh/GoGoHam-rules</a>')
        html = (
            '<h1 style="margin-bottom:0">GoGoHam by DO2GGH</h1>'
            f'<p style="margin-top:2px"><b>Version {__version__}</b> · '
            f'{tr("Contest-Logger für Linux")}</p>'
            f'<p>{tr("Schneller Contest-Logger für Linux – Rufzeichen, Leertaste, Austausch, Enter.")}</p>'
            f'<p><b>{tr("Funktionen")}</b></p><ul>{features}</ul>'
            f'<p><b>{tr("Datenquellen – herzlichen Dank an")}</b></p><ul>{sources}</ul>'
            f'<p><b>{tr("Verwendete Bausteine")}</b>: Python · Qt / PySide6 (LGPL) · Hamlib (LGPL) · '
            f'NumPy (BSD) · {tr("auf Wunsch")}: Piper (MIT), espeak-ng (GPL), speech-dispatcher (GPL)</p>'
            f'<p><b>{tr("Lizenz")}</b>: '
            f'{tr("GoGoHam steht unter der GPL-3.0 (nur Version 3), die Contest-Regel-Dateien unter CC BY 4.0. Contest-Regeln: {link}", link=rules_link)}<br>'
            f'{tr("Logo, Symbole und Ladebildschirm gehören zum Programm und stehen ebenfalls unter der GPL-3.0.")}<br>'
            f'{tr("Zusatzbedingungen nach § 7 GPL-3.0: Der Urhebervermerk „GoGoHam by DO2GGH · © 2026 Franz, DO2GGH“ muss in „Über GoGoHam“ und im Handbuch erhalten bleiben; veränderte Fassungen müssen als verändert gekennzeichnet sein und dürfen nicht als das Original GoGoHam ausgegeben werden.")}</p>'
            "<hr>"
            '<p><b>© 2026 Franz, DO2GGH</b> · '
            '<a href="mailto:do2ggh.de@gmail.com">do2ggh.de@gmail.com</a></p>'
        )
        text = QLabel(html)
        text.setWordWrap(True)
        text.setOpenExternalLinks(False)          # 0.10.42.1: mailto über xdg-open (KDE + Flatpak)
        text.linkActivated.connect(_open_link)
        text.setTextFormat(Qt.TextFormat.RichText)
        from PySide6.QtWidgets import QScrollArea
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(text)
        area.setMinimumHeight(480)
        bb = QDialogButtonBox()
        bb.addButton(tr("Schließen"), QDialogButtonBox.ButtonRole.RejectRole)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay = QVBoxLayout(self)
        lay.addWidget(area)
        lay.addWidget(bb)


class ClusterPage(QDialog):
    """DX-Cluster (ab 0.8.12): Knoten, Anmeldung, Filter nach Regionen."""

    def __init__(self, cfg: dict, parent=None):
        from .. import dxcluster as dc
        super().__init__(parent)
        self.cfg = cfg
        self.dc = dc
        form = QFormLayout()
        # 0.8.14.1: kein eigenes Häkchen mehr – Bandmap offen (Fenster → Bandmap) = verbunden
        note = QLabel(tr("Verbunden wird, solange die Bandmap offen ist (Fenster → Bandmap)."))
        note.setWordWrap(True)
        form.addRow(note)
        self.node = QComboBox()
        for name, host, port in dc.NODES:
            self.node.addItem(f"{name} – {host}:{port}", f"{host}:{port}")
        self.node.addItem(tr("Eigener Knoten …"), "")
        self.custom = QLineEdit(cfg.get("cluster_custom", ""))
        self.custom.setPlaceholderText(tr("z. B. dxc.example.org:7300"))
        cur = cfg.get("cluster_node", dc.DEFAULT_NODE)
        i = self.node.findData(cur)
        self.node.setCurrentIndex(i if i >= 0 else self.node.count() - 1)
        if i < 0 and cur and not self.custom.text():
            self.custom.setText(cur)
        self.node.currentIndexChanged.connect(lambda _i: self._node_changed())
        form.addRow(tr("Cluster-Knoten:"), self.node)
        form.addRow(tr("Eigener Knoten:"), self.custom)
        self.call = QLineEdit(cfg.get("cluster_call", ""))
        self.call.setPlaceholderText(tr("leer = dein Rufzeichen aus dem Log"))
        form.addRow(tr("Anmelden als:"), self.call)
        self.age = QSpinBox()
        self.age.setRange(5, 120)
        self.age.setSuffix(tr(" min"))
        self.age.setValue(int(cfg.get("cluster_max_age", 30)))
        form.addRow(tr("Spots anzeigen bis zu einem Alter von:"), self.age)
        self.contest_only = QCheckBox(tr("Nur Spots auf Bändern und in der Betriebsart des Contests"))
        self.contest_only.setChecked(bool(cfg.get("cluster_contest_only", True)))
        form.addRow(self.contest_only)

        grid = QGridLayout()
        grid.addWidget(QLabel(tr("<b>Gespottet von</b> (wer die Station hört):")), 0, 0, 1, 4)
        grid.addWidget(QLabel(tr("<b>Gespottete Station aus:</b>")), 2, 0, 1, 4)
        want_sp = cfg.get("cluster_spotter_cont")
        want_sp = set(want_sp) if want_sp else set(parent.default_spotter_cont()
                                                   if hasattr(parent, "default_spotter_cont")
                                                   else ["EU"])
        want_dx = set(cfg.get("cluster_dx_cont") or dc.CONTINENTS)
        self.chk_sp, self.chk_dx = {}, {}
        for col, c in enumerate(dc.CONTINENTS):
            a = QCheckBox(tr(dc.CONTINENT_NAMES[c]))
            a.setChecked(c in want_sp)
            b = QCheckBox(tr(dc.CONTINENT_NAMES[c]))
            b.setChecked(c in want_dx)
            grid.addWidget(a, 1, col)
            grid.addWidget(b, 3, col)
            self.chk_sp[c], self.chk_dx[c] = a, b
        hint = QLabel(tr("Tipp: Bei „Gespottet von“ nur Europa ankreuzen – dann siehst du nur "
                         "Stationen, die bei uns zu hören sind. Wer den Cluster im Contest "
                         "nutzt, startet meist in der Kategorie ASSISTED (Log-Einstellungen). "
                         "GoGoHam liest nur mit und verschickt keine eigenen Spots."))
        hint.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(grid)
        lay.addWidget(hint)
        lay.addStretch(1)
        self._node_changed()

    def _node_changed(self) -> None:
        self.custom.setEnabled(not self.node.currentData())

    def apply(self) -> bool:
        node = self.node.currentData() or self.custom.text().strip()
        if not self.dc.parse_node(node):
            QMessageBox.warning(self, tr("DX-Cluster"),
                                tr("Bitte einen Knoten wählen oder „Adresse:Port“ eintragen."))
            return False
        sp = [c for c, b in self.chk_sp.items() if b.isChecked()]
        dx = [c for c, b in self.chk_dx.items() if b.isChecked()]
        if not sp or not dx:
            QMessageBox.warning(self, tr("DX-Cluster"),
                                tr("Bitte bei beiden Filtern mindestens eine Region ankreuzen."))
            return False
        self.cfg.update({
            "cluster_node": node or self.dc.DEFAULT_NODE,
            "cluster_custom": self.custom.text().strip(),
            "cluster_call": self.call.text().strip().upper(),
            "cluster_max_age": self.age.value(),
            "cluster_contest_only": self.contest_only.isChecked(),
            "cluster_spotter_cont": sp,
            "cluster_dx_cont": dx,
        })
        return True


class LiveScoreDialog(QDialog):
    """Live-Score: Punktestand während des Contests an ein Online-Scoreboard senden."""

    TARGETS = [
        ("Contest Online ScoreBoard (contestonlinescore.com)", "https://contestonlinescore.com/post/"),
        (tr("Score Distributor (an mehrere Scoreboards)"), "http://scoredistributor.net/"),
    ]

    def __init__(self, cfg: dict, parent=None, embedded: bool = False):
        super().__init__(parent)
        self.setWindowTitle(tr("Live-Score"))
        self.cfg = cfg
        form = QFormLayout()
        self.enabled = QCheckBox(tr("Punktestand während des Contests alle 2 Minuten senden"))
        self.enabled.setChecked(cfg.get("livescore_enabled", False))
        self.target = QComboBox()
        for label, url in self.TARGETS:
            self.target.addItem(label, url)
        self.target.addItem(tr("Eigene Adresse …"), "")
        self.url = QLineEdit(cfg.get("livescore_url", self.TARGETS[0][1]))
        idx = next((i for i, (_l, u) in enumerate(self.TARGETS) if u == self.url.text()), 2)
        self.target.setCurrentIndex(idx)
        self.target.currentIndexChanged.connect(self._target_changed)
        self.user = QLineEdit(cfg.get("livescore_user", ""))
        self.user.setPlaceholderText(tr("leer = dein Rufzeichen aus dem Log"))
        self.password = QLineEdit(cfg.get("livescore_password", ""))
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(self.enabled)
        form.addRow(tr("Ziel:"), self.target)
        form.addRow(tr("Adresse:"), self.url)
        form.addRow(tr("Benutzer:"), self.user)
        form.addRow(tr("Passwort:"), self.password)
        hint = QLabel(tr("Für contestonlinescore.com brauchst du dort ein (kostenloses) Konto; "
                      "Benutzername ist dein Rufzeichen. Gesendet wird nur, während der "
                      "Contest läuft."))
        hint.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        if not embedded:
            lay.addWidget(_buttons(self, "livescore"))

    def _target_changed(self, i: int) -> None:
        url = self.target.itemData(i) if hasattr(self.target, "itemData") else ""
        if url:
            self.url.setText(url)

    def apply(self) -> bool:
        """Eingaben in die Einstellungen übernehmen; False = Eingabe fehlerhaft."""
        self.cfg.update({
            "livescore_enabled": self.enabled.isChecked(),
            "livescore_url": self.url.text().strip() or self.TARGETS[0][1],
            "livescore_user": self.user.text().strip().upper(),
            "livescore_password": self.password.text(),
        })
        return True

    def accept(self) -> None:
        if self.apply():
            super().accept()


# ============================================================ Einstellungen (0.8.1)
class DisplayPage(QDialog):
    """Reiter „Darstellung“: Design, Sprache, Schriftgröße."""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        from .. import i18n
        self.cfg = cfg
        form = QFormLayout()
        self.theme = QComboBox()
        for key, text in (("system", tr("wie System")), ("light", tr("Hell")),
                          ("dark", tr("Dunkel")), ("franken", tr("Franken hell")),
                          ("franken-dark", tr("Franken dunkel")),
                          ("nightshift", tr("Nightshift hell")),
                          ("nightshift-dark", tr("Nightshift dunkel"))):
            self.theme.addItem(text, key)
        self.theme.setCurrentIndex(max(self.theme.findData(cfg.get("theme", "system")), 0))
        form.addRow(tr("Design:"), self.theme)
        self.language = QComboBox()
        sysname = i18n.available().get(i18n.resolve("auto"), i18n.resolve("auto"))
        self.language.addItem(tr("Automatisch (Sprache des Systems: {name})", name=sysname), "auto")
        for key, name in i18n.available().items():
            self.language.addItem(name, key)
        self.language.setCurrentIndex(max(self.language.findData(cfg.get("language", "auto")), 0))
        # 0.10.29: lange Sprachliste als scrollbare Klappliste statt Liste über den ganzen
        # Bildschirm (manche Designs zeigen sonst alle Einträge auf einmal)
        self.language.setStyleSheet("QComboBox { combobox-popup: 0; }")
        self.language.setMaxVisibleItems(10)
        form.addRow(tr("Sprache / Language:"), self.language)
        self.font_size = QSpinBox()
        self.font_size.setRange(9, 30)
        self.font_size.setValue(int(cfg.get("font_size", 15)))
        form.addRow(tr("Schriftgröße der Eingabe:"), self.font_size)
        self.splash_ton = QCheckBox(tr("Mithörton beim Startbildschirm (GGH in Morse, "
                                       "nur über die PC-Lautsprecher)"))
        self.splash_ton.setChecked(bool(cfg.get("splash_ton", False)))
        form.addRow(tr("Startbildschirm:"), self.splash_ton)
        hint = QLabel(tr("Sprache und Schriftgröße wirken nach einem Neustart von GoGoHam – "
                         "GoGoHam fragt danach. Das Design wirkt sofort."))
        hint.setWordWrap(True)
        # Zusatzfenster beim Start (0.8.14.1): Standard keins; offen = Funktion an
        box = QGroupBox(tr("Beim Programmstart öffnen"))
        bl = QVBoxLayout(box)
        self.open_docks = {}
        for key, text in (("open_scp", tr("Super Check Partial")),
                          ("open_bandmap", tr("Bandmap (verbindet mit dem DX-Cluster)")),
                          ("open_beacons", tr("Baken (NCDXF/IARU) – nur bei Contests mit "
                                              "20, 15 oder 10 m")),
                          ("open_map", tr("Karte (Grayline)")),
                          ("open_rotor", tr("Rotor")),
                          ("open_propagation", tr("Bandöffnung (Vorschau)")),
                          ("open_station", tr("Station (Plätze und Nachrichten) – nur "
                                              "im Stationslog"))):
            cb = QCheckBox(text)
            cb.setChecked(bool(cfg.get(key, False)))
            bl.addWidget(cb)
            self.open_docks[key] = cb
        dh = QLabel(tr("Alle Fenster lassen sich jederzeit über das Menü Fenster öffnen. "
                       "Ein offenes Fenster ist eingeschaltet, ein geschlossenes aus."))
        dh.setWordWrap(True)
        bl.addWidget(dh)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addWidget(box)
        lay.addStretch(1)

    def apply(self) -> bool:
        self.cfg["theme"] = self.theme.currentData() or "system"
        self.cfg["language"] = self.language.currentData() or "auto"
        self.cfg["font_size"] = self.font_size.value()
        self.cfg["splash_ton"] = self.splash_ton.isChecked()
        for key, cb in self.open_docks.items():
            self.cfg[key] = cb.isChecked()
        return True


class DataPage(QDialog):
    """Reiter „Daten & Updates“: Downloads, Contest-Regeln, Sicherungen, Call-History."""

    def __init__(self, cfg: dict, parent=None, actions: dict | None = None):
        super().__init__(parent)
        self.cfg = cfg
        actions = actions or {}
        lay = QVBoxLayout(self)
        # Alles auf einmal (0.8.28.3) – die Einzelknöpfe darunter bleiben
        allbox = QGroupBox(tr("Alles auf einmal"))
        al = QVBoxLayout(allbox)
        self.all_btn = QPushButton(tr("Alles herunterladen / aktualisieren"))
        self.all_btn.setToolTip(tr("Contest-Regeln, Länderdatei, MASTER.SCP, DOK-Liste, Flaggen, "
                                   "beide Kartenbilder und speech-dispatcher (fragt nach dem "
                                   "Passwort) – nacheinander im Hintergrund"))
        mb = self._voices_mb()
        self.all_voices = QCheckBox(tr("auch natürliche Stimmen (ca. {mb} MB)", mb=mb) if mb
                                    else tr("auch natürliche Stimmen (schon alle da)"))
        self.all_voices.setChecked(False)
        self.all_status = QLabel("")
        self.all_status.setWordWrap(True)
        al.addWidget(self.all_btn)
        al.addWidget(self.all_voices)
        al.addWidget(self.all_status)
        if "all" in actions:
            self.all_btn.clicked.connect(lambda: self._all_start(actions["all"]))
        else:
            self.all_btn.setEnabled(False)
        lay.addWidget(allbox)
        for key, text in (("rules", tr("Contest-Regeln jetzt aktualisieren")),
                          ("cty", tr("Länderdatei (cty.dat) aktualisieren")),
                          ("scp", tr("Super Check Partial (MASTER.SCP) aktualisieren")),
                          ("flags", tr("Flaggen herunterladen")),
                          ("map_nasa", tr("Kartenbild NASA (Satellit) herunterladen/erneuern")),
                          ("map_relief", tr("Kartenbild Natural Earth (Relief) herunterladen")),
                          ("doks", tr("DOK-Liste (DARC-Conteste) aktualisieren")),
                          ("history", tr("Call-History importieren …"))):
            btn = QPushButton(text)
            if key in actions:
                btn.clicked.connect(actions[key])
            else:
                btn.setEnabled(False)
            lay.addWidget(btn)
        # Sprachausgabe für die Ansagen (0.8.26.1): ein Klick installiert und richtet sie ein
        from .. import speech
        self.speechd_btn = QPushButton()
        self._speechd_state(speech.speechd_ok())
        if "speechd" in actions:
            self.speechd_btn.clicked.connect(lambda: self._speechd_start(actions["speechd"]))
        else:
            self.speechd_btn.setEnabled(False)
        lay.addWidget(self.speechd_btn)
        # natürliche Stimme (0.8.26.2): Piper + Stimmen, ohne Passwort
        from .. import piper
        self.piper_btn = QPushButton()
        self._piper_state(speech.piper_ok())
        if "piper" in actions and piper.supported():
            self.piper_btn.clicked.connect(lambda: self._piper_start(actions["piper"]))
        else:
            self.piper_btn.setEnabled(False)
        lay.addWidget(self.piper_btn)
        form = QFormLayout()
        self.auto_rules = QCheckBox(tr("Contest-Regeln beim Anlegen eines Logs automatisch "
                                       "von GitHub aktualisieren"))
        self.auto_rules.setChecked(cfg.get("rules_auto_update", True))
        form.addRow(self.auto_rules)
        self.daily = QCheckBox(tr("Beim Start einmal täglich aktualisieren"))
        self.daily.setToolTip(tr("Contest-Regeln, Länderdatei, MASTER.SCP, DOK-Liste und fehlende "
                                 "Flaggen. Läuft der Contest des geöffneten Logs gerade, bleiben "
                                 "Regeln und Länderdatei unverändert. Ohne Internet passiert nichts."))
        self.daily.setChecked(cfg.get("daily_update", True))
        form.addRow(self.daily)
        self.vcheck = QCheckBox(tr("Auf neue GoGoHam-Version prüfen"))
        self.vcheck.setToolTip(tr("Einmal am Tag beim Start fragt GoGoHam bei GitHub nach, ob es "
                                  "eine neuere Version gibt, und zeigt dann einen Hinweis – je "
                                  "Version nur einmal. Es wird nur gelesen."))
        self.vcheck.setChecked(cfg.get("version_check", True))
        form.addRow(self.vcheck)
        self.backup = QSpinBox()
        self.backup.setRange(1, 120)
        self.backup.setSuffix(tr(" min"))
        self.backup.setValue(int(cfg.get("backup_minutes", 10)))
        form.addRow(tr("Sicherung alle:"), self.backup)
        lay.addLayout(form)
        lay.addStretch(1)

    @staticmethod
    def _voices_mb() -> int:
        from .. import piper
        need = piper.missing_size("speech") + piper.missing_size("practice")
        if need and os.access(piper.exe_path(), os.X_OK) is False:
            need -= piper.PROGRAMS.get(piper.arch(), piper.PROGRAMS["x86_64"])[1]  # nur einmal
        return round(need / 1e6)

    def _all_start(self, action) -> None:
        def report(text: str) -> None:
            self.all_status.setText(text)

        def finished(results) -> None:
            from .. import speech
            self.all_btn.setEnabled(True)
            self._speechd_state(speech.speechd_ok())
            self._piper_state(speech.piper_ok())
            lines = [("✓ " if r.ok else "✗ ") + f"{r.name}: {r.text}" for r in results]
            QMessageBox.information(self, tr("Alles herunterladen"), "\n".join(lines))

        if action(self.all_voices.isChecked(), report, finished):
            self.all_btn.setEnabled(False)
        else:
            self.all_status.setText(tr("Läuft schon …"))

    def _speechd_state(self, installed: bool) -> None:
        b = self.speechd_btn
        if installed:
            b.setText(tr("Sprachausgabe speech-dispatcher ist installiert ✓"))
            b.setEnabled(False)
        else:
            b.setText(tr("Sprachausgabe speech-dispatcher installieren (für die Ansagen)"))
            b.setToolTip(tr("Installiert speech-dispatcher und espeak-ng über die "
                            "Paketverwaltung – Linux fragt nach dem Passwort."))

    def _piper_state(self, installed: bool) -> None:
        from .. import piper
        b = self.piper_btn
        if installed:
            b.setText(tr("Natürliche Stimme (Piper) ist geladen ✓"))
            b.setEnabled(False)
        else:
            b.setText(tr("Natürliche Stimme (Piper) für die Ansagen herunterladen, ca. {mb} MB",
                         mb=round(piper.total_size() / 1e6)))
            b.setToolTip(tr("Lädt Piper und je eine deutsche und englische Stimme – "
                            "ohne Passwort, nur für GoGoHam."))

    def _piper_start(self, action) -> None:
        self.piper_btn.setEnabled(False)
        self.piper_btn.setText(tr("Lade … (Fortschritt in der Hinweiszeile)"))

        def done(ok: bool) -> None:
            try:
                self._piper_state(ok)
                if not ok:
                    self.piper_btn.setEnabled(True)
            except RuntimeError:
                pass
        action(done)

    def _speechd_start(self, action) -> None:
        self.speechd_btn.setEnabled(False)
        self.speechd_btn.setText(tr("Installiere … (Linux fragt nach dem Passwort)"))

        def done(ok: bool) -> None:
            try:
                self._speechd_state(ok)
                if not ok:
                    self.speechd_btn.setEnabled(True)
            except RuntimeError:                 # Fenster schon zu – nichts mehr anzuzeigen
                pass
        action(done)

    def apply(self) -> bool:
        self.cfg["rules_auto_update"] = self.auto_rules.isChecked()
        self.cfg["daily_update"] = self.daily.isChecked()
        self.cfg["version_check"] = self.vcheck.isChecked()
        self.cfg["backup_minutes"] = self.backup.value()
        return True


class SettingsDialog(QDialog):
    """Alle Programm-Einstellungen in einem Fenster (ab 0.8.1). Ab 0.10.4 mit einer Liste
    links: acht Bereiche, zwei davon (Ton & Ansagen, Online-Dienste) mit Unterreitern."""

    # Seiten (Schlüssel für start=, Hilfe und Tests) – in der Reihenfolge der Liste
    TABS = ("operator", "rig", "rotor", "gps", "fkeys", "voice", "announce", "cluster", "callbook",
            "livescore", "wsjtx", "display", "data")

    def __init__(self, cfg: dict, parent=None, test_fn=None, actions: dict | None = None,
                 start: str = "rig", mycall: str = "", rotor_test_fn=None,
                 check_apps: bool = True):
        super().__init__(parent)
        from PySide6.QtWidgets import QListWidget, QStackedWidget, QTabWidget
        self.setWindowTitle(tr("Einstellungen"))
        self.setMinimumWidth(1280)  # Sprachaufnahmen: Liste + Regler nebeneinander, Liste links
        self.cfg = cfg
        from .voice_dialog import VoicePage
        from .rotor_page import RotorPage
        from .announce_page import AnnouncePage
        from .apps_page import AppsPage
        self.announce_page = AnnouncePage(cfg, self, install=(actions or {}).get("speechd"),
                                          piper_download=(actions or {}).get("piper"))
        self.rig_page = RigDialog(cfg, self, test_fn=test_fn, embedded=True)
        self.macro_page = MacroDialog(cfg, self, embedded=True)
        self.voice_page = VoicePage(cfg, mycall, self)     # ab 0.8.12.9 Reiter statt Fenster
        self.wsjtx_page = WsjtxDialog(cfg, self, embedded=True)
        self.apps_page = AppsPage(cfg, self.wsjtx_page, self, check=check_apps)
        from .operator_page import OperatorPage
        self.operator_page = OperatorPage(cfg, self)     # 0.10.11: eigene Angaben, ganz oben
        from .gps_page import GpsPage
        self.gps_page = GpsPage(cfg, self, watch=(actions or {}).get("gps_watch"))   # 0.10.25
        self.pages = [
            ("operator", tr("Operator"), self.operator_page, "operator"),
            ("rig", tr("Funkgerät"), self.rig_page, "cat"),
            ("rotor", tr("Rotor"), RotorPage(cfg, self, test_fn=rotor_test_fn), "rotor"),
            ("gps", tr("GPS"), self.gps_page, "gps"),
            ("fkeys", tr("Funktionstasten"), self.macro_page, "fkeys"),
            ("voice", tr("Sprachaufnahmen"), self.voice_page, "sprachausgabe"),
            ("announce", tr("Ansagen"), self.announce_page, "ansagen"),
            ("cluster", tr("DX-Cluster"), ClusterPage(cfg, parent), "dxcluster"),
            ("callbook", tr("Name/QTH"), CallbookDialog(cfg, self, embedded=True), "callbook"),
            ("livescore", tr("Live-Score"), LiveScoreDialog(cfg, self, embedded=True), "livescore"),
            ("wsjtx", tr("Zusatzprogramme"), self.apps_page, "zusatzprogramme"),
            ("display", tr("Darstellung"), DisplayPage(cfg, self), "design"),
            ("data", tr("Daten & Updates"), DataPage(cfg, self, actions), "regeln-github"),
        ]
        from .. import livestick
        stick = livestick.is_live()             # Bereich „USB-Stick“ nur auf dem Stick (0.10.8)
        if stick:
            from .stick_page import StickPage
            self.pages.append(("stick", tr("USB-Stick"), StickPage(cfg, self, actions), "usb-stick"))
        from .. import devmode
        dev = devmode.is_unlocked()             # 0.10.21: nur nach Passwort (Strg+Umschalt+E)
        if dev:
            from .dev_page import DevPage
            self.pages.append(("dev", tr("Entwicklung"), DevPage(cfg, self), ""))
        # Bereiche der Liste links: (Name, Seiten)
        # 0.10.11: Reihenfolge wie bei der Ersteinrichtung
        self.sections = [
            (tr("Operator"), ["operator"]),
            (tr("Funkgerät"), ["rig"]), (tr("Rotor"), ["rotor"]), (tr("GPS"), ["gps"]),
            (tr("Funktionstasten"), ["fkeys"]),
            (tr("Daten & Updates"), ["data"]),
            (tr("Ton & Ansagen"), ["voice", "announce"]),
            (tr("Online-Dienste"), ["cluster", "callbook", "livescore"]),
            (tr("Zusatzprogramme"), ["wsjtx"]),
            (tr("Darstellung"), ["display"]),
        ] + ([(tr("USB-Stick"), ["stick"])] if stick else []) \
            + ([(tr("Entwicklung"), ["dev"])] if dev else [])
        by_key = {p[0]: p for p in self.pages}
        self.nav = QListWidget()
        self.nav.setFixedWidth(200)
        self.nav.setStyleSheet("QListWidget::item { padding: 6px 8px; }")   # etwas Luft
        self.stack = QStackedWidget()
        self._inner: dict[int, QTabWidget] = {}
        # 0.10.12: jede Seite scrollt, wenn der Bildschirm zu niedrig ist (Laptop)
        from .fitscreen import scroll_widget
        for si, (title, keys) in enumerate(self.sections):
            self.nav.addItem(title)
            if len(keys) == 1:
                self.stack.addWidget(scroll_widget(by_key[keys[0]][2]))
            else:
                tabs = QTabWidget()
                for k in keys:
                    tabs.addTab(scroll_widget(by_key[k][2]), by_key[k][1].replace("&", "&&"))
                self._inner[si] = tabs
                self.stack.addWidget(tabs)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.select(start)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        help_btn = bb.addButton("?", QDialogButtonBox.ButtonRole.HelpRole)
        help_btn.setToolTip(tr("Hilfe zu diesem Bereich"))
        help_btn.clicked.connect(self._help)
        row = QHBoxLayout()
        row.addWidget(self.nav)
        row.addWidget(self.stack, 1)
        lay = QVBoxLayout(self)
        lay.addLayout(row, 1)
        lay.addWidget(bb)
        self._link_voice_source()
        from PySide6.QtGui import QKeySequence, QShortcut
        sc = QShortcut(QKeySequence("Ctrl+Shift+E"), self)
        sc.activated.connect(self.unlock_dev)

    def ask_password(self) -> str | None:
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        pw, ok = QInputDialog.getText(self, tr("Entwicklung"), tr("Passwort:"),
                                      QLineEdit.EchoMode.Password)
        return pw if ok else None

    def unlock_dev(self) -> None:
        """Strg+Umschalt+E: Passwort abfragen, dann den Bereich „Entwicklung“ anhängen."""
        from .. import devmode
        if any(p[0] == "dev" for p in self.pages):
            self.select("dev")
            return
        if not devmode.available():
            return                                 # kein Passwort eingerichtet: nichts zeigen
        pw = self.ask_password()
        if pw is None:
            return
        if not devmode.unlock(pw):
            QMessageBox.warning(self, tr("Entwicklung"), tr("Falsches Passwort."))
            return
        from .dev_page import DevPage
        from .fitscreen import scroll_widget
        page = DevPage(self.cfg, self)
        self.pages.append(("dev", tr("Entwicklung"), page, ""))
        self.sections.append((tr("Entwicklung"), ["dev"]))
        self.nav.addItem(tr("Entwicklung"))
        self.stack.addWidget(scroll_widget(page))
        self.select("dev")

    def select(self, key: str) -> None:
        """Bereich (und Unterreiter) einer Seite zeigen; unbekannt = erster Bereich."""
        for si, (_t, keys) in enumerate(self.sections):
            if key in keys:
                self.nav.setCurrentRow(si)
                if si in self._inner:
                    self._inner[si].setCurrentIndex(keys.index(key))
                return
        self.nav.setCurrentRow(0)

    def current_key(self) -> str:
        si = max(self.nav.currentRow(), 0)
        keys = self.sections[si][1]
        return keys[self._inner[si].currentIndex()] if si in self._inner else keys[0]

    def current_title(self) -> str:
        """Angezeigter Name: Bereich, bei Unterreitern „Bereich → Reiter“."""
        si = max(self.nav.currentRow(), 0)
        title = self.sections[si][0]
        if si in self._inner:
            title += " → " + dict((p[0], p[1]) for p in self.pages)[self.current_key()]
        return title

    def _link_voice_source(self) -> None:
        """„SSB-Ansagen kommen aus“ (Funktionstasten) entscheidet allein; der Reiter
        Sprachaufnahmen passt nur seine Warnung („Soundkarte wählen“) sofort daran an."""
        vp, cb = self.voice_page, self.macro_page.cb_source
        if not vp.ok:
            return
        cb.currentIndexChanged.connect(lambda _i: vp.set_source(cb.currentData()))

    def done(self, result: int) -> None:  # noqa: D102 – OK, Abbrechen und Fenster-X
        if self.apps_page._proc is not None:      # Installation läuft noch
            QMessageBox.information(self, tr("Einstellungen"), tr(
                "Ein Zusatzprogramm wird gerade installiert – bitte kurz warten."))
            return
        self.apps_page.shutdown()
        self.voice_page.shutdown()
        self.announce_page.shutdown()
        self.gps_page.shutdown()
        super().done(result)

    def _help(self) -> None:
        key = self.current_key()
        show_help(self, next(p[3] for p in self.pages if p[0] == key) or "menues")

    @property
    def tested(self) -> bool:
        return self.rig_page.tested

    def accept(self) -> None:
        for key, _title, page, _anchor in self.pages:
            if not page.apply():
                self.select(key)                      # Fehler zeigen, Fenster bleibt offen
                return
        super().accept()
