"""Nur ein GoGoHam gleichzeitig (ab 0.8.7).

Beim Start holt sich GoGoHam eine Sperrdatei. Hat schon ein laufendes GoGoHam die Sperre,
schickt der zweite Start ihm über einen lokalen Kanal „nach vorne“ und beendet sich sofort –
noch bevor der Ladebildschirm erscheint. Nach einem Absturz bleibt keine Sperre hängen: Qt
erkennt an der gespeicherten Prozessnummer, dass das alte Programm nicht mehr läuft.
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


class SingleInstance:
    """lock() = True: wir sind das einzige GoGoHam. False: ein anderes läuft schon und wurde
    gebeten, sein Fenster nach vorne zu holen."""

    def __init__(self) -> None:
        path, self.server_name = _names()
        self._lock = QLockFile(str(path))
        self._lock.setStaleLockTime(0)       # nie nach Alter, nur nach Prozessnummer aufräumen
        self._server: QLocalServer | None = None
        self.window = None

    def lock(self) -> bool:
        if self._lock.tryLock(0):
            return True
        self._wake_other()
        return False

    def _wake_other(self) -> None:
        sock = QLocalSocket()
        sock.connectToServer(self.server_name)
        if sock.waitForConnected(1000):
            sock.write(b"raise\n")
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
            conn.readyRead.connect(conn.readAll)
            conn.disconnected.connect(conn.deleteLater)
            self.bring_to_front()

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
