"""Nur ein GoGoHam gleichzeitig (ab 0.8.7).

Beim Start holt sich GoGoHam eine Sperrdatei. Hat schon ein laufendes GoGoHam die Sperre,
schickt der zweite Start ihm über einen lokalen Kanal „nach vorne“ und beendet sich sofort –
noch bevor der Ladebildschirm erscheint. Nach einem Absturz bleibt keine Sperre hängen: Qt
erkennt an der gespeicherten Prozessnummer, dass das alte Programm nicht mehr läuft; eine Sperre
aus einem früheren Systemstart räumt GoGoHam selbst weg (0.10.47.6, siehe _from_earlier_boot).
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def _names() -> tuple[Path, str]:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = data_home / "gogoham"
    d.mkdir(parents=True, exist_ok=True)
    return d / "gogoham.lock", f"gogoham-{os.getuid()}"


RAISE = b"raise\n"
POWEROFF = b"poweroff\n"


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def _from_earlier_boot(path: Path, boot_id: str | None = None) -> bool:
    """Stammt die Sperre aus einem früheren Systemstart? (0.10.47.6) Qt prüft nur, ob die
    gespeicherte Prozessnummer noch lebt – nach einem Neustart kann sie einem anderen Programm
    gehören (Rechner aus, während GoGoHam lief). Dann hielt sich GoGoHam für „läuft schon“ und
    beendete sich still; auf dem Live-Stick wiederholen sich die Nummern bei jedem Start fast
    gleich (VM-Test). Qt schreibt die Kennung des Systemstarts in Zeile 5 der Sperrdatei."""
    boot_id = _boot_id() if boot_id is None else boot_id
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    return bool(boot_id) and len(lines) >= 5 and bool(lines[4].strip()) \
        and lines[4].strip() != boot_id


class SingleInstance:
    """lock() = True: wir sind das einzige GoGoHam. False: ein anderes läuft schon und wurde
    gebeten, sein Fenster nach vorne zu holen."""

    def __init__(self) -> None:
        path, self.server_name = _names()
        self.path = path
        self._lock = QLockFile(str(path))
        self._lock.setStaleLockTime(0)       # nie nach Alter, nur nach Prozessnummer aufräumen
        self._server: QLocalServer | None = None
        self.window = None
        self.on_poweroff = None              # vom Hauptfenster gesetzt (0.10.48)

    def lock(self, message: bytes = RAISE) -> bool:
        """message: was das laufende GoGoHam tun soll (RAISE = nach vorne, POWEROFF = beenden und
        herunterfahren, ab 0.10.48 – Schreibtisch-Symbol „Herunterfahren“ auf dem Stick)."""
        if self._lock.tryLock(0):
            return True
        if _from_earlier_boot(self.path) and self._lock.removeStaleLockFile() \
                and self._lock.tryLock(0):
            return True
        self._wake_other(message)
        return False

    def _wake_other(self, message: bytes = RAISE) -> None:
        sock = QLocalSocket()
        sock.connectToServer(self.server_name)
        if sock.waitForConnected(1000):
            sock.write(message)
            sock.waitForBytesWritten(1000)
            sock.disconnectFromServer()

    def listen(self, window) -> None:
        """Ab jetzt auf „nach vorne“-Bitten weiterer Starts hören."""
        self.window = window
        QLocalServer.removeServer(self.server_name)   # Rest nach einem Absturz
        self._server = QLocalServer()
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(self.server_name)

    def _on_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            conn.readyRead.connect(lambda c=conn: self._on_data(c))
            conn.disconnected.connect(conn.deleteLater)

    def _on_data(self, conn) -> None:
        data = bytes(conn.readAll())
        self.bring_to_front()
        if POWEROFF.strip() in data and self.on_poweroff is not None:
            self.on_poweroff()

    def bring_to_front(self) -> None:
        w = self.window
        if w is None:
            return
        if w.isMinimized():
            w.showNormal()
        w.show()
        w.raise_()
        w.activateWindow()

    def release(self) -> None:
        """Sperre freigeben (vor einem Neustart, sonst sperrt sich GoGoHam selbst aus)."""
        if self._server is not None:
            self._server.close()
            self._server = None
        self._lock.unlock()
