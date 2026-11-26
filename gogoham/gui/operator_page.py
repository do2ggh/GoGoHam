"""Einstellungen → Operator (ab 0.10.11): deine eigenen Angaben an einer Stelle.

Daraus füllt GoGoHam neue Logs vor (je nachdem, was der Contest braucht) und richtet die
Zusatzprogramme ein (Rufzeichen, Locator). Gespeichert in cfg["station_defaults"] – dort lagen die
gemerkten Angaben schon vorher, es muss also nichts umgezogen werden.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QLabel, QLineEdit, QVBoxLayout)

from ..i18n import tr

LICENCE_CLASSES = ("A", "E", "N")


def parse_birthdate(text: str) -> date | None:
    """„24.12.1965“ oder „1965-12-24“ → date; None = leer oder ungültig."""
    t = (text or "").strip()
    if not t:
        return None
    try:
        if "." in t:
            d, m, y = (int(x) for x in t.split("."))
        else:
            y, m, d = (int(x) for x in t.split("-"))
        if y < 100:
            return None
        return date(y, m, d)
    except ValueError:
        return None


def age_on(birth: date, day: date) -> int:
    """Alter an einem Tag (z. B. dem Contesttag)."""
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def age_from(sd: dict, day: date | None = None) -> str:
    """Alter aus dem gespeicherten Geburtsdatum – "" ohne Datum."""
    b = parse_birthdate(sd.get("my_birthdate", ""))
    return str(age_on(b, day or date.today())) if b else ""


class OperatorPage(QDialog):
    """Bereich „Operator“: Rufzeichen, Name, Locator, DOK, Lizenz, Geburtsdatum, Club …"""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        sd = cfg.get("station_defaults") or {}
        lay = QVBoxLayout(self)
        info = QLabel(tr("Deine eigenen Angaben. Damit füllt GoGoHam neue Logs vor (je nachdem, was "
                         "der Contest braucht) und richtet die Zusatzprogramme ein. Im einzelnen "
                         "Log kannst du alles ändern, z. B. für /P. Gespeichert wird nur auf diesem "
                         "Rechner."))
        info.setWordWrap(True)
        lay.addWidget(info)
        form = QFormLayout()

        def field(key: str, label: str, hint: str = "") -> QLineEdit:
            e = QLineEdit(str(sd.get(key, "") or ""))
            if hint:
                e.setPlaceholderText(hint)
            form.addRow(label, e)
            return e
        self.call = field("mycall", tr("Rufzeichen:"), tr("z. B. DO2GGH"))
        self.name = field("name", tr("Name:"))
        self.grid = field("my_grid", tr("Locator:"), tr("6-stellig, z. B. JN59me"))
        self.dok = field("my_dok", tr("DOK:"), tr("DARC/VFDB-Mitglieder, z. B. B36 – sonst leer"))
        self.licyear = field("my_licyear", tr("Jahr der ersten Lizenz:"), tr("z. B. 1982"))
        self.licclass = QComboBox()
        self.licclass.setEditable(True)
        self.licclass.addItem("")
        for c in LICENCE_CLASSES:
            self.licclass.addItem(c)
        self.licclass.setCurrentText(sd.get("my_licclass", ""))
        self.licclass.lineEdit().setPlaceholderText(tr("z. B. A, E oder N"))
        # 0.10.12: breit genug für den Hinweis (vorher nur „z…“ zu sehen)
        self.licclass.setMinimumContentsLength(16)
        self.licclass.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        form.addRow(tr("Lizenzklasse:"), self.licclass)
        b = parse_birthdate(sd.get("my_birthdate", ""))
        self.birth = field("", tr("Geburtsdatum:"), tr("TT.MM.JJJJ – fürs Alter in manchen Contests"))
        self.birth.setText(b.strftime("%d.%m.%Y") if b else "")
        self.cq = field("my_zone", tr("CQ-Zone:"), tr("leer = aus dem Rufzeichen"))
        self.itu = field("my_itu", tr("ITU-Zone:"), tr("leer = aus dem Rufzeichen"))
        self.club = field("club", tr("Club:"), tr("für den Cabrillo-Kopf, z. B. Bavarian Contest Club"))
        self.address = field("address", tr("Adresse:"), tr("für den Cabrillo-Kopf"))
        self.email = field("email", tr("E-Mail:"), tr("für den Cabrillo-Kopf"))
        lay.addLayout(form)
        self.bad = QLabel("")
        self.bad.setStyleSheet("color:#c62828;")
        self.bad.setWordWrap(True)
        lay.addWidget(self.bad)
        lay.addStretch(1)

    def apply(self) -> bool:
        from .. import locator
        grid = self.grid.text().strip()
        if grid and not locator.is_grid(grid):
            self.bad.setText(tr("Der Locator stimmt so nicht (Beispiel: JN59me)."))
            self.grid.setFocus()
            return False
        btext = self.birth.text().strip()
        b = parse_birthdate(btext)
        if btext and (b is None or b > date.today()):
            self.bad.setText(tr("Das Geburtsdatum bitte so eingeben: TT.MM.JJJJ, z. B. 24.12.1965."))
            self.birth.setFocus()
            return False
        for e, lo, hi, what in ((self.cq, 1, 40, tr("CQ-Zone")), (self.itu, 1, 90, tr("ITU-Zone"))):
            t = e.text().strip()
            if t and not (t.isdigit() and lo <= int(t) <= hi):
                self.bad.setText(tr("{what}: bitte eine Zahl von {lo} bis {hi} – oder leer lassen.",
                                    what=what, lo=lo, hi=hi))
                e.setFocus()
                return False
        self.bad.setText("")
        sd = dict(self.cfg.get("station_defaults") or {})
        if grid:
            grid = grid[:2].upper() + grid[2:4] + grid[4:6].lower()
        vals = {
            "mycall": self.call.text().strip().upper(),
            "name": self.name.text().strip(),
            "my_grid": grid,
            "my_dok": self.dok.text().strip().upper(),
            "my_licyear": self.licyear.text().strip(),
            "my_licclass": self.licclass.currentText().strip().upper(),
            "my_birthdate": b.isoformat() if b else "",
            "my_zone": self.cq.text().strip(),
            "my_itu": self.itu.text().strip(),
            "club": self.club.text().strip(),
            "address": self.address.text().strip(),
            "email": self.email.text().strip(),
        }
        for k, v in vals.items():
            if v:
                sd[k] = v
            else:
                sd.pop(k, None)
        self.cfg["station_defaults"] = sd
        return True
