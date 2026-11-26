"""Fenster „BBT-Deckblatt“: Angaben, die nicht im Log stehen (ab 0.10.42)."""

from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QTabWidget, QVBoxLayout,
                               QWidget)

from .. import bbt
from ..bands import has_unit
from ..i18n import tr

def band_labels() -> tuple:
    return (("tx", tr("Sender (TX):")), ("pout", tr("Leistung Pout (W):")),
            ("rx", tr("Empfänger (RX):")), ("stage", tr("Eingangsstufe:")),
            ("ant", tr("Antenne:")), ("code", tr("Antennen-Code (z. B. Ya9):")),
            ("agl", tr("Antenne über Grund (m):")), ("kg_tx", tr("Gewicht TX (kg):")),
            ("kg_rx", tr("Gewicht RX (kg):")), ("kg_ant", tr("Gewicht Antenne (kg):")))


def band_name(band: str) -> str:
    return band if has_unit(band) else f"{band} m"


class BbtDialog(QDialog):
    """Standort, Höhe, Kombistation, Bemerkungen und je Band die Station mit Gewichten. Die
    Angaben bleiben im Log (Schlüssel „bbt“) und sind beim nächsten Export schon ausgefüllt."""

    def __init__(self, meta: dict, bands: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("BBT-Deckblatt"))
        self.bands = list(bands)
        self.data = bbt.load(meta)
        d = self.data
        lay = QVBoxLayout(self)
        info = QLabel(tr("Diese Angaben stehen nicht im Log. GoGoHam schreibt sie aufs BBT-Deckblatt "
                         "(je Band eine Textdatei mit Deckblatt und Logblatt). Name, Anschrift, DOK "
                         "und Locator kommen aus den Log-Einstellungen."))
        info.setWordWrap(True)
        lay.addWidget(info)
        form = QFormLayout()
        self.site = QLineEdit(d.get("site", ""))
        self.asl = QLineEdit(d.get("asl", ""))
        self.phone = QLineEdit(d.get("phone", ""))
        self.combi = QCheckBox(tr("Kombistation (mehrere Bänder mit einer Station)"))
        self.combi.setChecked(d.get("combi") == "ja")
        self.combi_max = QLineEdit(d.get("combi_max", ""))
        form.addRow(tr("BBT-Standort (Berg):"), self.site)
        form.addRow(tr("Höhe über NN (m):"), self.asl)
        form.addRow(tr("Telefon:"), self.phone)
        form.addRow("", self.combi)
        form.addRow(tr("Kombistation – höchste Frequenz:"), self.combi_max)
        lay.addLayout(form)
        self.tabs = QTabWidget()
        self.fields: dict[str, dict[str, QLineEdit]] = {}
        for band in self.bands:
            b = d["bands"].get(band, {})
            page = QWidget()
            f = QFormLayout(page)
            self.fields[band] = {}
            for key, label in band_labels():
                ed = QLineEdit(b.get(key, ""))
                f.addRow(label, ed)
                self.fields[band][key] = ed
            self.tabs.addTab(page, band_name(band))
        lay.addWidget(self.tabs)
        lay.addWidget(QLabel(tr("Bemerkungen (Wetter, Cond. usw.):")))
        self.remarks = QPlainTextEdit(d.get("remarks", ""))
        lay.addWidget(self.remarks)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def collect(self) -> dict:
        d = dict(self.data)
        d.update({"site": self.site.text().strip(), "asl": self.asl.text().strip(),
                  "phone": self.phone.text().strip(),
                  "combi": "ja" if self.combi.isChecked() else "nein",
                  "combi_max": self.combi_max.text().strip(),
                  "remarks": self.remarks.toPlainText().strip()})
        bands = dict(d.get("bands") or {})
        for band, eds in self.fields.items():
            bands[band] = {k: ed.text().strip() for k, ed in eds.items()}
        d["bands"] = bands
        return d

    def accept(self) -> None:
        d = self.collect()
        warn = bbt.warnings(d, self.bands)
        if warn and QMessageBox.question(
                self, tr("BBT-Deckblatt"),
                "\n".join(warn) + "\n\n" + tr("Trotzdem so übernehmen?")) != \
                QMessageBox.StandardButton.Yes:
            return
        self.data = d
        super().accept()
