"""Bereich „Entwicklung“ (ab 0.10.21) – nur nach Passwort, siehe devmode.py.

0.10.44: Strg+Umschalt+E öffnet ihn auch direkt im Hauptfenster als eigenes Fenster
(`open_dev_window`, auch von GoGoHome benutzt) – im Einstellungsfenster bleibt er zusätzlich.
Neu darin: WS im Nightshift-Design einrichten/entfernen (wsnightshift.py).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QVBoxLayout)

from .. import devmode, wsnightshift
from ..i18n import tr


class DevPage(QDialog):
    def __init__(self, cfg: dict, parent=None, features: bool = True):
        super().__init__(parent)
        self.cfg = cfg
        lay = QVBoxLayout(self)
        intro = QLabel(tr("Funktionen zum Ausprobieren, die noch nicht für alle gedacht sind. "
                          "Eingeschaltetes bleibt eingeschaltet, auch nach einem Neustart."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        on = cfg.get("dev_features") or {}
        self.boxes: dict[str, QCheckBox] = {}
        for key, name, info in (devmode.features() if features else []):
            ck = QCheckBox(name)
            ck.setChecked(bool(on.get(key)))
            lay.addWidget(ck)
            hint = QLabel(info)
            hint.setWordWrap(True)
            hint.setStyleSheet("color: gray; margin-left: 24px;")
            lay.addWidget(hint)
            self.boxes[key] = ck
        lay.addWidget(self._ws_box())
        lay.addStretch(1)

    # ------------------------------------------------------------ WS Nightshift (0.10.44)
    def _ws_box(self) -> QGroupBox:
        box = QGroupBox(tr("WS im Nightshift-Design"))
        v = QVBoxLayout(box)
        info = QLabel(tr("Stellt das normale WS-Symbol (Startmenü und Schreibtisch) so um, dass WS "
                         "in den Nightshift-Farben (dunkel) startet – kein zusätzliches Symbol. "
                         "Die farbig hinterlegten Dekodierzeilen bekommen schwarze Schrift (mit "
                         "Sicherungskopie von WS.ini). WS muss dafür geschlossen sein. "
                         "„Entfernen“ stellt WS wieder ganz normal."))
        info.setWordWrap(True)
        v.addWidget(info)
        self.ws_state = QLabel()
        v.addWidget(self.ws_state)
        row = QHBoxLayout()
        self.ws_install = QPushButton(tr("Einrichten"))
        self.ws_install.clicked.connect(self.install_ws)
        self.ws_remove = QPushButton(tr("Entfernen"))
        self.ws_remove.clicked.connect(self.remove_ws)
        row.addWidget(self.ws_install)
        row.addWidget(self.ws_remove)
        row.addStretch(1)
        v.addLayout(row)
        self._ws_refresh()
        return box

    def _ws_refresh(self) -> None:
        on = wsnightshift.is_installed()
        self.ws_state.setText(tr("Stand: eingerichtet") if on else tr("Stand: nicht eingerichtet"))
        self.ws_install.setText(tr("Erneuern") if on else tr("Einrichten"))
        self.ws_remove.setEnabled(on)

    def install_ws(self) -> None:
        res = wsnightshift.install()
        self._ws_refresh()
        text = "\n".join("• " + ln for ln in res.lines)
        if res.ok:
            QMessageBox.information(self, tr("WS im Nightshift-Design"),
                                    text + "\n\n" + tr("WS jetzt ganz normal über sein Symbol starten."))
        else:
            QMessageBox.warning(self, tr("WS im Nightshift-Design"), text)

    def remove_ws(self) -> None:
        res = wsnightshift.remove()
        self._ws_refresh()
        QMessageBox.information(self, tr("WS im Nightshift-Design"), "\n".join(res.lines))

    def apply(self) -> bool:
        if not self.boxes:
            return True
        feats = dict(self.cfg.get("dev_features") or {})
        for key, ck in self.boxes.items():
            if ck.isChecked():
                feats[key] = True
            else:
                feats.pop(key, None)
        if feats:
            self.cfg["dev_features"] = feats
        else:
            self.cfg.pop("dev_features", None)
        return True


class DevWindow(QDialog):
    """Eigenes Fenster „Entwicklung“ (Strg+Umschalt+E im Hauptfenster)."""

    def __init__(self, cfg: dict, parent=None, features: bool = True):
        super().__init__(parent)
        self.setWindowTitle(tr("Entwicklung"))
        self.setMinimumSize(600, 440)
        self.page = DevPage(cfg, self, features)
        self.page.setWindowFlags(Qt.WindowType.Widget)    # Seite einbetten, kein eigenes Fenster
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.page, 1)
        lay.addWidget(bb)

    def accept(self) -> None:
        if self.page.apply():
            super().accept()


def ask_password(parent) -> str | None:
    from PySide6.QtWidgets import QInputDialog, QLineEdit
    pw, ok = QInputDialog.getText(parent, tr("Entwicklung"), tr("Passwort:"),
                                  QLineEdit.EchoMode.Password)
    return pw if ok else None


def open_dev_window(parent, cfg: dict, save, features: bool = True, ask=None) -> bool:
    """Strg+Umschalt+E im Hauptfenster: Passwort (einmal je Programmstart, wie im
    Einstellungsfenster), dann das Fenster „Entwicklung“. Mit OK wird gespeichert (save(cfg)).
    -> True, wenn das Fenster mit OK geschlossen wurde."""
    if not devmode.is_unlocked():
        if not devmode.available():
            return False                          # kein Passwort eingerichtet: nichts zeigen
        pw = (ask or ask_password)(parent)
        if pw is None:
            return False
        if not devmode.unlock(pw):
            QMessageBox.warning(parent, tr("Entwicklung"), tr("Falsches Passwort."))
            return False
    dlg = DevWindow(cfg, parent, features)
    if not dlg.exec():
        return False
    save(cfg)
    return True
