"""GPS im Hauptfenster (ab 0.10.25): Anzeige in der Statuszeile, Erkennen beim Einstecken
(„GPS-Empfänger gefunden – verwenden?“), Hinweis bei anderem Locator, Uhr-Vergleich.

Alles Lesende läuft im Hintergrund-Thread (gps.GpsWorker); hier nur der Takt der Oberfläche.
"""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QMessageBox, QPushButton

from .. import applog
from .. import clockcheck as ck
from .. import gps
from ..i18n import tr

COLORS = {"ok": "#1b8a3a", "wait": "#d97706", "off": "#808080", "error": "#c62828"}
SCAN_S = 3.0              # so oft nach neu eingesteckten Geräten schauen
GRID_STABLE_S = 20.0      # so lange muss der neue Locator gleich bleiben (kein Zappeln)
FIRST_SCAN_S = 8.0        # erst nach den Startfragen


class GpsWatch:
    def __init__(self, win, scan_fn=gps.scan, gpsd_fn=gps.gpsd_available, worker_cls=None,
                 ask=True):
        self.win = win
        self.cfg = win.cfg
        self.scan_fn, self.gpsd_fn = scan_fn, gpsd_fn
        self.worker_cls = worker_cls or gps.GpsWorker
        self.ask_enabled = ask
        self.worker: gps.GpsWorker | None = None
        self.source: gps.Source | None = None
        self.label = QPushButton("")
        self.label.setFlat(True)
        self.label.clicked.connect(lambda: win.open_settings("gps"))
        self.label.hide()
        self._seen: set[str] | None = None        # Kennungen beim letzten Suchen
        self._declined: set[str] = set()          # „Jetzt nicht“ (nur dieser Programmlauf)
        self._next_scan = time.monotonic() + FIRST_SCAN_S
        self._next_tick = 0.0
        self._asking = False
        self._grid_cand, self._grid_since = "", 0.0
        self._grid_done: set[tuple[str, str]] = set()
        self._clock_asked = False
        self._access_asked = False
        self._last_grid = ""
        self.proc: QProcess | None = None

    # ------------------------------------------------------------------ Start/Stopp
    def settings(self) -> dict:
        return gps.gps_settings(self.cfg)

    def blocked(self, path: str) -> bool:
        return gps.is_profile_port(path, self.cfg)

    def start(self) -> None:
        self.stop()
        g = self.settings()
        if not g["enabled"]:
            self.label.hide()
            return
        ports = self.scan_fn(verified=g.get("verified", []))
        self.source = gps.source_from_cfg(g, ports, gpsd=self.gpsd_fn(), blocked=self.blocked)
        self.label.show()
        if self.source is None:
            self._show(tr("GPS: kein Empfänger"), "off",
                       tr("Kein GPS-Empfänger gefunden – bitte einstecken."))
            return
        applog.message(f"GPS: starte ({self.source.kind} {self.source.key or self.source.path})")
        self.worker = self.worker_cls(self.source, scan_fn=lambda: self.scan_fn(
            verified=g.get("verified", [])), blocked=self.blocked)
        self.worker.start()

    def stop(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.worker = None
        self.source = None

    def snapshot(self) -> gps.GpsState | None:
        return self.worker.snapshot() if self.worker is not None else None

    def position(self) -> tuple[float, float] | None:
        """Eigener Standort vom GPS (für Karte, Rotor, Baken) – nur mit frischem Fix."""
        g = self.settings()
        st = self.snapshot()
        if not (g["enabled"] and g["map"]) or st is None or not st.has_fix:
            return None
        if time.monotonic() - st.updated > 30:
            return None
        return st.lat, st.lon

    def grid(self) -> str:
        st = self.snapshot()
        return st.grid if st is not None and st.has_fix else ""

    # ------------------------------------------------------------------ Takt
    def tick(self) -> None:
        now = time.monotonic()
        if now < self._next_tick:
            return
        self._next_tick = now + 1.0
        if now >= self._next_scan:
            self._next_scan = now + SCAN_S
            self._hotplug()
        st = self.snapshot()
        if st is None:
            return
        text, level = gps.status_text(st)
        self._show(text, level, self.details(st))
        if st.error_kind == "access" and not self._access_asked and not self._asking:
            self._access_asked = True
            self._offer_access()
        if st.has_fix and st.grid != self._last_grid:
            self._last_grid = st.grid
            if self.settings()["map"]:
                try:
                    self.win._map_home()
                except Exception:  # noqa: BLE001 – Anzeige darf nie stören
                    pass
        self._grid_check(st, now)
        self._clock_check(st)

    def _show(self, text: str, level: str, tip: str = "") -> None:
        self.label.setText("🛰 " + text)
        self.label.setStyleSheet(f"color:{COLORS.get(level, '#808080')}; font-weight:bold;")
        self.label.setToolTip((tip + "\n\n" if tip else "") + tr("Klicken: Einstellungen → GPS"))

    @staticmethod
    def details(st: gps.GpsState) -> str:
        """Mehrzeilige Beschreibung (Tooltip, Einstellungsseite)."""
        from datetime import datetime, timezone
        from ..i18n import num
        rows = []
        if st.error and not st.connected:
            rows.append(st.error)
        if st.source:
            rows.append(tr("Quelle: {s}", s=st.source) +
                        (f" · {st.baud} Baud" if st.baud else ""))
        if st.connected:
            fix = {0: tr("kein Fix"), 2: tr("2D-Fix"), 3: tr("3D-Fix")}.get(st.fix, "?")
            rows.append(tr("{fix} · {u} Satelliten benutzt, {v} in Sicht", fix=fix, u=st.used,
                           v=st.view))
        if st.has_fix:
            rows.append(tr("Locator {g} · Breite {lat}°, Länge {lon}°", g=st.grid,
                           lat=num(st.lat, 5), lon=num(st.lon, 5)) +
                        (tr(" · Höhe {h} m", h=num(st.alt)) if st.alt is not None else ""))
        if st.gps_time is not None and st.connected:
            t = datetime.fromtimestamp(st.gps_time, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            rows.append(tr("GPS-Zeit {t} UTC", t=t))
        if st.bad_date:
            rows.append(tr("Der Empfänger meldet ein falsches Datum (alter Empfänger) – die "
                           "Uhrzeit wird nicht benutzt."))
        elif st.offset is not None and st.has_fix:
            if not ck.is_wrong(st.offset):
                rows.append(tr("PC-Uhr stimmt (Abweichung {s} s)",
                               s=("+" if st.offset >= 0 else "−") + num(abs(st.offset), 1)))
            else:
                rows.append(ck.describe(st.offset))
            if not st.time_trusted():
                rows.append(tr("(GPS-Zeit noch vorläufig – nach dem Einschalten bis zu "
                               "13 Minuten)"))
        return "\n".join(rows)

    # ------------------------------------------------------------------ Einstecken
    def _hotplug(self) -> None:
        g = self.settings()
        try:
            ports = self.scan_fn(verified=g.get("verified", []))
        except Exception:  # noqa: BLE001
            return
        keys = {p.key for p in ports}
        new = keys if self._seen is None else keys - self._seen
        self._seen = keys
        if g["enabled"] and self.worker is None and any(p.kind == "gps" for p in ports):
            self.start()                          # an, aber noch kein Gerät: jetzt eins da
            return
        if not self.ask_enabled or self._asking:
            return
        for p in ports:
            if p.key not in new or p.kind != "gps" or p.key in g["ignored"] or \
                    p.key in self._declined or self.blocked(p.path):
                continue
            if g["enabled"] and self.source is not None and self.source.key == p.key:
                continue                          # das benutzte Gerät – läuft von selbst weiter
            st = self.snapshot()
            if g["enabled"] and st is not None and st.connected:
                continue                          # anderes GPS läuft schon
            self.ask_use(p)
            return

    def ask_use(self, p: gps.Port) -> None:
        self._asking = True
        try:
            box = QMessageBox(self.win)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle(tr("GPS-Empfänger gefunden"))
            box.setText(tr("GPS-Empfänger gefunden: {name}\n\nSoll GoGoHam ihn verwenden? "
                           "Dann kommen Standort, Locator und Uhrzeit vom GPS.", name=p.label))
            b_yes = box.addButton(tr("Verwenden"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(tr("Jetzt nicht"), QMessageBox.ButtonRole.RejectRole)
            b_never = box.addButton(tr("Nie für dieses Gerät"), QMessageBox.ButtonRole.DestructiveRole)
            box.setDefaultButton(b_yes)
            box.exec()
            clicked = box.clickedButton()
        finally:
            self._asking = False
        g = self.settings()
        if clicked is b_yes:
            self.use(p)
        elif clicked is b_never:
            g["ignored"] = sorted(set(g["ignored"]) | {p.key})
            self._save()
        else:
            self._declined.add(p.key)

    def use(self, p: gps.Port) -> None:
        g = self.settings()
        g.update(enabled=True, source="serial", device=p.key, label=p.label, path="")
        self._save()
        applog.message(f"GPS: Gerät gewählt {p.key}")
        if not os.access(p.path, os.R_OK):
            self._offer_access()
        self.start()
        self.win.statusBar().showMessage(tr("GPS-Empfänger wird benutzt: {name}", name=p.label),
                                         8000)

    def _save(self) -> None:
        from .. import config as cfgmod
        cfgmod.save(self.cfg)

    def _offer_access(self) -> None:
        from .dialogs import PermissionDialog
        dlg = PermissionDialog("", self.win)
        dlg.exec()
        if dlg.done_ok:
            self.start()

    # ------------------------------------------------------------------ Locator
    def _grid_check(self, st: gps.GpsState, now: float) -> None:
        win = self.win
        if not self.settings()["grid_hint"] or not st.has_fix or not st.grid or self._asking:
            return
        if st.grid != self._grid_cand:
            self._grid_cand, self._grid_since = st.grid, now
            return
        if now - self._grid_since < GRID_STABLE_S:
            return
        if not getattr(win, "db", None) or getattr(win, "practice", None) is not None:
            return
        cur = (win.meta.get("my_grid") or "").strip()
        if cur.upper() == st.grid.upper():
            return
        key = (str(win.db.path), st.grid)
        if key in self._grid_done:
            return
        self._grid_done.add(key)
        self.ask_grid(st.grid, cur)

    def ask_grid(self, grid: str, cur: str) -> None:
        win = self.win
        n = len(getattr(win, "qsos", []) or [])
        text = tr("Laut GPS stehst du im Locator {g}.", g=grid) + "\n" + (
            tr("Im Log steht {c}.", c=cur) if cur else tr("Im Log ist noch kein Locator "
                                                         "eingetragen."))
        if n:
            text += "\n\n" + tr("Das Log hat schon {n} QSOs. Der Locator gilt für das ganze Log – "
                                "auch für Entfernung und Punkte der bisherigen QSOs. Hast du den "
                                "Standort gewechselt, lege besser ein neues Log an.", n=n)
        text += "\n\n" + tr("Locator {g} ins Log übernehmen?", g=grid)
        self._asking = True
        try:
            ans = QMessageBox.question(win, tr("Locator vom GPS"), text,
                                       QMessageBox.StandardButton.Yes |
                                       QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No if n else
                                       QMessageBox.StandardButton.Yes)
        finally:
            self._asking = False
        if ans == QMessageBox.StandardButton.Yes:
            win.apply_my_grid(grid)

    # ------------------------------------------------------------------ Uhrzeit
    def _clock_check(self, st: gps.GpsState) -> None:
        if not self.settings()["clock"] or self._clock_asked or self._asking or self.proc:
            return
        if not st.time_trusted() or not ck.is_wrong(st.offset):
            return
        last = getattr(getattr(self.win, "clock", None), "last", None)
        if last is not None and not ck.is_wrong(last):
            return                           # Zeitserver (Internet) sagt: stimmt – der ist genauer
        self._clock_asked = True
        self._asking = True
        try:
            ans = QMessageBox.question(
                self.win, tr("Uhrzeit vom GPS"),
                tr("Laut GPS-Empfänger: {d}\n\nDas ist fürs Log wichtig. Die PC-Uhr jetzt nach "
                   "GPS stellen?", d=ck.describe(st.offset)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
        finally:
            self._asking = False
        if ans == QMessageBox.StandardButton.Yes:
            self.set_clock()

    def can_set_clock(self) -> bool:
        st = self.snapshot()
        return st is not None and st.time_trusted() and self.proc is None

    def set_clock(self, done=None) -> bool:
        """PC-Uhr um die GPS-Abweichung verstellen (pkexec; auf dem Stick ohne Passwort)."""
        from .. import station
        st = self.snapshot()
        if st is None or st.offset is None or not st.time_trusted() or self.proc is not None:
            return False
        cmd = station.clock_command(st.offset)
        applog.message(f"Uhr nach GPS stellen: {st.offset:+.2f} s")
        proc = QProcess(self.win)
        self.proc = proc

        def finished(code: int, _status) -> None:
            err = bytes(proc.readAllStandardError()).decode(errors="replace").strip()
            proc.deleteLater()
            self.proc = None
            sb = self.win.statusBar()
            if code == 0:
                if self.worker is not None:
                    self.worker.reset_time()
                sb.showMessage(tr("PC-Uhr nach GPS gestellt ✓"), 10000)
            else:
                applog.message(f"Uhr nach GPS fehlgeschlagen ({code}): {err}", "warn")
                sb.showMessage(tr("Uhr stellen ging nicht: {e}", e=err or code), 15000,
                               level="warn")
            if done:
                done(code == 0)
        proc.finished.connect(finished)
        proc.start(cmd[0], cmd[1:])
        return True
