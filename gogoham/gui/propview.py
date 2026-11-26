"""Fenster „Bandöffnung (Vorschau)“ (ab 0.8.27): geschätzt, welches Band wohin offen ist.

Zwei Ansichten, umschaltbar: „Jetzt“ = Bänder × Kontinente, „Nächste 12 Stunden“ = Bänder ×
Stunden für einen gewählten Kontinent. Die Rechnung steht in propagation.py. Laufen DX-Cluster
oder RBN, zeigt ✓, was in den letzten 30 Minuten tatsächlich gehört wurde.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import propagation as pr
from ..bands import band_label
from ..dxcluster import CONTINENT_NAMES
from ..i18n import tr

COLORS = {pr.GOOD: ("#1b8a3a", "white"), pr.FAIR: ("#f2c200", "black"),
          pr.POOR: ("#f0a050", "black")}
SYMBOL = {pr.GOOD: "●●●", pr.FAIR: "●●", pr.POOR: "●", pr.CLOSED: "–"}
HEARD = "✓"


def level_name(level: int) -> str:
    return {pr.GOOD: tr("gut"), pr.FAIR: tr("mäßig"), pr.POOR: tr("schwach"),
            pr.CLOSED: tr("zu")}[level]


def cont_name(c: str) -> str:
    return tr(CONTINENT_NAMES.get(c, c))


def region_name(key: str) -> str:
    """Bezugspunkte aus propagation.REGIONS (0.8.27.1)."""
    return {
        "eu_c": tr("Mitteleuropa"), "eu_w": tr("Spanien/Portugal"), "eu_n": tr("Skandinavien"),
        "eu_e": tr("Russland (europäischer Teil)"), "eu_s": tr("Südosteuropa"),
        "na_e": tr("Ostküste USA/Kanada"), "na_m": tr("Mittlerer Westen"),
        "na_w": tr("Westküste USA"), "na_c": tr("Karibik"),
        "sa_n": tr("nördliches Südamerika"), "sa_b": tr("Brasilien"),
        "sa_s": tr("Argentinien/Chile"),
        "af_nw": tr("Kanaren/Marokko"), "af_w": tr("Westafrika"), "af_c": tr("Zentralafrika"),
        "af_e": tr("Ostafrika"), "af_s": tr("Südafrika"),
        "as_me": tr("Naher Osten"), "as_r": tr("Russland (asiatischer Teil)"),
        "as_in": tr("Indien"), "as_cn": tr("China"), "as_jp": tr("Japan"),
        "as_se": tr("Südostasien"),
        "oc_ae": tr("Ostaustralien"), "oc_aw": tr("Westaustralien"), "oc_nz": tr("Neuseeland"),
        "oc_id": tr("Indonesien"), "oc_hi": tr("Hawaii"),
    }.get(key, key)


class PropagationView(QWidget):
    def __init__(self, cfg: dict | None = None, on_change=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg if cfg is not None else {}
        self.on_change = on_change
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        top = QHBoxLayout()
        self.cb_view = QComboBox()
        self.cb_view.addItem(tr("Jetzt: Bänder × Kontinente"), "now")
        self.cb_view.addItem(tr("Nächste 12 Stunden"), "hours")
        self.cb_cont = QComboBox()
        for c in pr.CONTINENTS:
            self.cb_cont.addItem(cont_name(c), c)
        self.cb_cont.setToolTip(tr("Nach welchem Kontinent?"))
        i = self.cb_view.findData(self.cfg.get("prop_view", "now"))
        self.cb_view.setCurrentIndex(max(0, i))
        i = self.cb_cont.findData(self.cfg.get("prop_cont", "NA"))
        self.cb_cont.setCurrentIndex(max(0, i))
        self.cb_view.currentIndexChanged.connect(self._changed)
        self.cb_cont.currentIndexChanged.connect(self._changed)
        top.addWidget(self.cb_view)
        top.addWidget(self.cb_cont)
        top.addStretch(1)
        lay.addLayout(top)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-weight:bold;")
        self.status.setToolTip(tr(
            "Grobe Schätzung aus Sonnenfluss (SFI), K-Wert und Tag/Nacht auf dem Weg – nur "
            "Short Path, nur Kurzwelle. Je Kontinent werden mehrere Gegenden gerechnet, es zählt "
            "die beste. Ob ein Band wirklich offen ist, zeigt nur das Hören: ✓ = in den letzten "
            "30 Minuten von Meldern bis 1000 km um dich tatsächlich gehört (DX-Cluster oder Baken "
            "über das RBN, wenn sie laufen)."))
        lay.addWidget(self.status)
        self.tbl = QTableWidget(0, 0)
        self.tbl.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 6)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay.addWidget(self.tbl, 1)
        self.legend = QLabel(tr("●●● gut · ●● mäßig · ● schwach · – zu · ✓ tatsächlich gehört"))
        self.legend.setWordWrap(True)
        lay.addWidget(self.legend)
        self.setMinimumWidth(self.fontMetrics().averageCharWidth() * 56)
        self._sig = None
        self._args = None
        self._sync_cont()

    # ------------------------------------------------------------------ Bedienung
    @property
    def mode(self) -> str:
        return self.cb_view.currentData() or "now"

    @property
    def cont(self) -> str:
        return self.cb_cont.currentData() or "NA"

    def _sync_cont(self) -> None:
        self.cb_cont.setVisible(self.mode == "hours")

    def _changed(self, _i: int = 0) -> None:
        self.cfg["prop_view"], self.cfg["prop_cont"] = self.mode, self.cont
        self._sync_cont()
        if self.on_change:
            self.on_change()
        if self._args:
            self.show_estimate(*self._args, force=True)

    # ------------------------------------------------------------------ Anzeige
    def show_message(self, text: str) -> None:
        self._sig, self._args = None, None
        self.status.setText(text)
        self.tbl.clear()
        self.tbl.setRowCount(0)
        self.tbl.setColumnCount(0)

    def show_estimate(self, home, bands: list[str], sfi, k, heard: dict | None = None,
                      when: datetime | None = None, force: bool = False) -> None:
        when = when or datetime.now(timezone.utc)
        heard = heard or {}
        self._args = (home, bands, sfi, k, heard)
        sig = (home, tuple(bands), sfi, k, tuple(sorted(heard.items())), self.mode, self.cont,
               int(when.timestamp() // 60))
        if sig == self._sig and not force:
            return
        self._sig = sig
        head = tr("Schätzung – keine Garantie")
        if sfi is None:
            head += " · " + tr("ohne aktuelles Funkwetter, nur Tag/Nacht")
        else:
            head += " · " + tr("SFI {sfi}", sfi=sfi)
            if k is not None:
                head += " · " + tr("K {k}", k=k)
        if self.mode == "hours":
            head += " · " + tr("nach {cont}, Zeiten in UTC", cont=cont_name(self.cont))
        self.status.setText(head)
        if self.mode == "hours":
            times = pr.hours(when, 12)
            grid = pr.grid_hours(home, bands, self.cont, times, sfi, k)
            cols = [tr("jetzt")] + [t.strftime("%H") for t in times[1:]]
            keys = list(range(len(times)))
            cont_of_col = [self.cont] * len(times)
        else:
            grid = pr.grid_now(home, bands, when, sfi, k)
            cols = list(pr.CONTINENTS)
            keys = list(pr.CONTINENTS)
            cont_of_col = list(pr.CONTINENTS)
        self.tbl.setRowCount(len(bands))
        self.tbl.setColumnCount(len(cols))
        self.tbl.setHorizontalHeaderLabels(cols)
        self.tbl.setVerticalHeaderLabels([band_label(b) for b in bands])
        for c, key in enumerate(keys):
            hi = self.tbl.horizontalHeaderItem(c)
            if hi is not None:
                if self.mode == "hours":
                    hi.setToolTip(tr("jetzt") if c == 0 else
                                  tr("{h}:30 UTC", h=times[c].strftime("%H")))
                else:
                    hi.setToolTip(cont_name(key))
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for r, band in enumerate(bands):
            for c, key in enumerate(keys):
                est = grid[(band, key)]
                n = heard.get((band, cont_of_col[c]), 0) if (self.mode == "now" or c == 0) else 0
                text = SYMBOL[est.level] + (" " + HEARD if n else "")
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if est.level in COLORS:
                    bg, fg = COLORS[est.level]
                    it.setBackground(QBrush(QColor(bg)))
                    it.setForeground(QBrush(QColor(fg)))
                elif not n:                        # gehört trotz „zu“: gut sichtbar lassen
                    it.setForeground(QBrush(QColor("#9e9e9e")))
                when_txt = tr("jetzt") if (self.mode == "now" or c == 0) else \
                    tr("um {h}:30 UTC", h=times[c].strftime("%H"))
                it.setToolTip(self.cell_tip(band, cont_of_col[c], est, n, when_txt))
                self.tbl.setItem(r, c, it)

    @staticmethod
    def cell_tip(band: str, cont: str, est, n: int, when_txt: str) -> str:
        lines = [tr("{band} nach {cont} {when}: {level} (geschätzt)", band=band_label(band),
                    cont=cont_name(cont), when=when_txt, level=level_name(est.level)),
                 tr("Am besten: {region}", region=region_name(est.region)),
                 tr("Höchste brauchbare Frequenz etwa {muf} MHz, tiefste etwa {luf} MHz",
                    muf=f"{est.muf:.0f}", luf=f"{est.luf:.0f}"),
                 tr("Weg etwa {km} km, {hops} Sprung/Sprünge", km=est.km, hops=est.hops)]
        if est.polar:
            lines.append(tr("Der Weg führt durch die Polarlicht-Zone – bei Unruhe auf dem "
                            "Magnetfeld schlechter"))
        if est.k_penalty:
            lines.append(tr("Wegen des hohen K-Werts abgewertet"))
        if n:
            lines.append(tr("Tatsächlich gehört: {n} Meldungen in den letzten 30 Minuten "
                            "(Melder bis 1000 km von dir)", n=n))
        return "\n".join(lines)
