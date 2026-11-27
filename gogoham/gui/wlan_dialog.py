"""Fenster „Mit dem Internet verbinden“ (ab 0.10.48, Live-Stick): WLAN wählen, Passwort, fertig.

Öffnet sich auf dem Stick beim Start von selbst, wenn kein Internet da ist und der Rechner WLAN
hat (MainWindow._stick_wlan), und jederzeit über Einstellungen → USB-Stick → „WLAN verbinden …“.
Die Arbeit macht gogoham/wlan.py (nmcli) im Hintergrund, das Fenster bleibt bedienbar.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout)

from .. import wlan
from ..i18n import tr


class _Bridge(QObject):
    scanned = Signal(object)
    connected = Signal(object)


def reason_text(reason: str) -> str:
    return {
        "password": tr("Das Passwort stimmt nicht – bitte noch einmal eingeben."),
        "not_found": tr("Dieses WLAN ist gerade nicht zu finden. „Neu suchen“ und noch einmal "
                        "versuchen."),
        "timeout": tr("Das WLAN hat nicht rechtzeitig geantwortet. Bitte noch einmal versuchen."),
    }.get(reason, tr("Die Verbindung hat nicht geklappt. Bitte noch einmal versuchen."))


class WlanDialog(QDialog):
    def __init__(self, cfg: dict | None = None, parent=None, at_start: bool = False,
                 scan_fn=None, connect_fn=None):
        super().__init__(parent)
        self.cfg = cfg if cfg is not None else {}
        self._scan = scan_fn or wlan.scan
        self._connect = connect_fn or wlan.connect
        self.networks: list[wlan.Network] = []
        self.ok_ssid = ""
        self.setWindowTitle(tr("Mit dem Internet verbinden"))
        self.resize(480, 460)
        self._bridge = _Bridge()
        self._bridge.scanned.connect(self._show_networks)
        self._bridge.connected.connect(self._connected)
        lay = QVBoxLayout(self)
        intro = QLabel(tr("Wähle dein WLAN aus und gib das Passwort ein. Mit einem Netzwerkkabel "
                          "ist der Rechner schon von selbst verbunden. Der Stick merkt sich das "
                          "WLAN für die nächsten Starts."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._selected)
        self.list.itemDoubleClicked.connect(lambda _i: self.start_connect())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Passwort:")))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.returnPressed.connect(self.start_connect)
        row.addWidget(self.password, 1)
        lay.addLayout(row)
        self.chk_show = QCheckBox(tr("Passwort anzeigen"))
        self.chk_show.toggled.connect(lambda on: self.password.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        lay.addWidget(self.chk_show)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.chk_ask = QCheckBox(tr("Beim Start fragen, wenn kein Internet da ist"))
        self.chk_ask.setChecked(bool(self.cfg.get("stick_wlan_ask", True)))
        self.chk_ask.setVisible(at_start)
        lay.addWidget(self.chk_ask)
        buttons = QHBoxLayout()
        self.btn_scan = QPushButton(tr("Neu suchen"))
        self.btn_scan.clicked.connect(self.start_scan)
        self.btn_connect = QPushButton(tr("Verbinden"))
        self.btn_connect.setDefault(True)
        self.btn_connect.clicked.connect(self.start_connect)
        self.btn_close = QPushButton(tr("Später") if at_start else tr("Schließen"))
        self.btn_close.clicked.connect(self.reject)
        buttons.addWidget(self.btn_scan)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_connect)
        buttons.addWidget(self.btn_close)
        lay.addLayout(buttons)
        self.btn_connect.setEnabled(False)
        self.start_scan()

    # ------------------------------------------------------------ Suchen
    def start_scan(self) -> None:
        self._busy(True)
        self.status.setText(tr("Suche WLANs …"))

        def work():
            try:
                nets = self._scan()
            except Exception:  # noqa: BLE001 – lieber leere Liste als Absturz
                nets = []
            self._bridge.scanned.emit(nets)
        threading.Thread(target=work, daemon=True).start()

    def _show_networks(self, nets) -> None:
        self.networks = list(nets)
        self.list.clear()
        for n in self.networks:
            lock = tr("🔒 mit Passwort") if n.secure else tr("offen")
            text = f"{n.ssid}    {wlan.bars(n.signal)} {n.signal} %    {lock}"
            if n.in_use:
                text += "    " + tr("✓ verbunden")
            QListWidgetItem(text, self.list)
        self._busy(False)
        if self.networks:
            self.list.setCurrentRow(0)
            self.status.setText(tr("{n} WLANs gefunden.", n=len(self.networks)))
        else:
            self.status.setText(tr("Kein WLAN gefunden. Ist WLAN am Rechner eingeschaltet (manche "
                                   "Laptops haben dafür eine Taste)? Dann „Neu suchen“."))

    def _selected(self, row: int) -> None:
        n = self.networks[row] if 0 <= row < len(self.networks) else None
        self.btn_connect.setEnabled(n is not None)
        self.password.setEnabled(bool(n and n.secure))
        if n is not None and n.secure:
            self.password.setFocus()

    # ------------------------------------------------------------ Verbinden
    def start_connect(self) -> None:
        row = self.list.currentRow()
        if not (0 <= row < len(self.networks)) or not self.btn_connect.isEnabled():
            return
        n = self.networks[row]
        pw = self.password.text() if n.secure else ""
        if n.secure and not pw:
            self.status.setText(tr("Bitte das Passwort für „{ssid}“ eingeben.", ssid=n.ssid))
            self.password.setFocus()
            return
        self._busy(True)
        self.status.setText(tr("Verbinde mit „{ssid}“ … (das kann bis zu einer halben Minute "
                               "dauern)", ssid=n.ssid))

        def work():
            try:
                res = self._connect(n.ssid, pw)
            except Exception:  # noqa: BLE001
                res = (False, "other")
            self._bridge.connected.emit((n.ssid, res))
        threading.Thread(target=work, daemon=True).start()

    def _connected(self, data) -> None:
        ssid, (ok, reason) = data
        self._busy(False)
        if ok:
            self.ok_ssid = ssid
            self.status.setText(tr("✓ Verbunden mit „{ssid}“.", ssid=ssid))
            self.btn_close.setText(tr("Fertig"))
            self.btn_close.setFocus()
            return
        self.status.setText("⚠ " + reason_text(reason))
        if reason == "password":
            self.password.selectAll()
            self.password.setFocus()

    def _busy(self, on: bool) -> None:
        for w in (self.btn_scan, self.list, self.password):
            w.setEnabled(not on)
        self.btn_connect.setEnabled(not on and 0 <= self.list.currentRow() < len(self.networks))
        if not on:
            self._selected(self.list.currentRow())
        self.setCursor(Qt.CursorShape.BusyCursor if on else Qt.CursorShape.ArrowCursor)

    def done(self, r: int) -> None:  # noqa: D401 – Einstellung „beim Start fragen“ merken
        if self.chk_ask.isVisible():
            self.cfg["stick_wlan_ask"] = self.chk_ask.isChecked()
        super().done(r)
