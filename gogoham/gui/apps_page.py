"""Bereich „Zusatzprogramme“ in den Einstellungen (ab 0.10.4): WS (DG2YCB) und fldigi –
installiert?, Installieren (Paketverwaltung) oder Downloadseite, „Einstellungen übertragen“ und
(ab 0.10.17) „Deinstallieren …“. Darunter die bisherigen FT8-Einstellungen."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout)

from .. import extapps, rigprofiles
from ..i18n import tr


class AppsPage(QDialog):
    def __init__(self, cfg: dict, wsjtx_page, parent=None, check: bool = True):
        super().__init__(parent)
        self.cfg = cfg
        self.wsjtx_page = wsjtx_page
        self.found: dict[str, str | None] = {}
        self.pkg: dict[str, str | None] = {}         # None = wird noch geprüft
        self.versions: dict[str, tuple[str, str]] = {}  # 0.10.14: (installiert, neueste)
        self._versions_done = True
        self.labels: dict[str, QLabel] = {}
        self.buttons: dict[str, QPushButton] = {}
        self.setup_buttons: dict[str, QPushButton] = {}
        self.remove_buttons: dict[str, QPushButton] = {}   # 0.10.17
        self._removing = ""
        self._check = check
        self._proc = None
        self._installing = ""
        self.open_url = lambda url: QDesktopServices.openUrl(QUrl(url))   # Tests: Ersatz
        self.ask = self._ask                                              # Tests: Ersatz
        self.tell = lambda title, text: QMessageBox.information(self, title, text)

        lay = QVBoxLayout(self)
        intro = QLabel(tr("Programme, die gut mit GoGoHam zusammenarbeiten. „Installieren“ holt "
                          "immer die neueste Version – je nach Linux direkt vom Entwickler, aus "
                          "dem AUR, aus den Paketquellen oder von Flathub. Gibt es eine neuere "
                          "Version, steht hier „Aktualisieren“. Linux fragt dabei nach dem "
                          "Passwort."))
        intro.setWordWrap(True)
        lay.addWidget(intro)

        box = QGroupBox(tr("Programme"))
        grid = QGridLayout(box)
        for row, app in enumerate(extapps.APPS):
            name = QLabel(f"<b>{app.name}</b>")
            what = QLabel(tr("FT8, FT4 und andere Digitalbetriebsarten") if app.ft8
                          else tr("RTTY – startet bei RTTY-Contests von selbst"))
            what.setStyleSheet("color:#888888;")
            st = self.labels[app.key] = QLabel("")
            btn = self.buttons[app.key] = QPushButton("")
            btn.clicked.connect(lambda _c=False, k=app.key: self._main_clicked(k))
            grid.addWidget(name, row, 0)
            grid.addWidget(what, row, 1)
            grid.addWidget(st, row, 2)
            grid.addWidget(btn, row, 3)
            if app.ft8 or app.key == "fldigi":
                sb = self.setup_buttons[app.key] = QPushButton(tr("Einstellungen übertragen"))
                sb.setToolTip(tr("Trägt im Programm nur die Verbindung zu GoGoHam ein: "
                                 "Funkgerät über rigctld, PTT über CAT, geloggte QSOs an "
                                 "GoGoHam. Vorher wird eine Sicherungskopie angelegt."))
                sb.clicked.connect(lambda _c=False, k=app.key: self.setup_connection(k))
                grid.addWidget(sb, row, 4)
            rb = self.remove_buttons[app.key] = QPushButton(tr("Deinstallieren …"))
            rb.setToolTip(tr("Entfernt das Programm wieder. Deine Einstellungen und Logs des "
                             "Programms bleiben erhalten."))
            rb.clicked.connect(lambda _c=False, k=app.key: self.uninstall(k))
            grid.addWidget(rb, row, 5)
        grid.setColumnStretch(1, 1)
        lay.addWidget(box)

        form = QFormLayout()
        self.ft8_pref = QComboBox(self)
        self.ft8_pref.addItem(tr("das erste installierte"), "")
        for a in extapps.APPS:
            if a.ft8:
                self.ft8_pref.addItem(a.name, a.key)
        i = self.ft8_pref.findData(cfg.get("ft8_program", ""))
        self.ft8_pref.setCurrentIndex(max(i, 0))
        self.ft8_pref.setToolTip(tr("Dieses Programm startet GoGoHam bei FT8/FT4-Contests von "
                                    "selbst"))
        if sum(a.ft8 for a in extapps.APPS) > 1:     # 0.10.17: nur noch WS – dann keine Wahl
            form.addRow(tr("Bevorzugtes FT8-Programm:"), self.ft8_pref)
        else:
            self.ft8_pref.hide()
        lay.addLayout(form)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#888888;")
        lay.addWidget(self.hint)

        # RTTY über fldigi (0.10.5): AFSK über die Soundkarte oder FSK über eine Steuerleitung
        box = QGroupBox(tr("RTTY (fldigi)"))
        rf = QFormLayout(box)
        self.rtty_tx = QComboBox()
        self.rtty_tx.addItem(tr("Soundkarte (AFSK) – Funkgerät auf LSB-Daten"), "afsk")
        self.rtty_tx.addItem(tr("FSK über eine Steuerleitung – Funkgerät auf RTTY"), "fsk")
        self.rtty_tx.setCurrentIndex(1 if cfg.get("rtty_tx") == "fsk" else 0)
        rf.addRow(tr("RTTY senden über:"), self.rtty_tx)
        from .. import hamlib
        self.fsk_port = QComboBox()
        self.fsk_port.setEditable(True)
        self.fsk_port.addItems(hamlib.serial_ports())
        self.fsk_port.setCurrentText(cfg.get("rtty_fsk_port", ""))
        self.fsk_line = QComboBox()
        self.fsk_line.addItems(["DTR", "RTS"])
        self.fsk_line.setCurrentText(cfg.get("rtty_fsk_line", "DTR"))
        frow = QHBoxLayout()
        frow.addWidget(self.fsk_port, 1)
        frow.addWidget(QLabel(tr("Leitung:")))
        frow.addWidget(self.fsk_line)
        rf.addRow(tr("FSK-Schnittstelle:"), frow)
        self.fsk_hint = QLabel(tr("FSK braucht eine eigene Schnittstelle, die nicht schon für CAT "
                                  "benutzt wird – z. B. die zweite USB-Schnittstelle bei Yaesu "
                                  "oder den FSK-Anschluss eines Interfaces. Im Zweifel AFSK nehmen."))
        self.fsk_hint.setWordWrap(True)
        self.fsk_hint.setStyleSheet("color:#888888;")
        rf.addRow(self.fsk_hint)
        rnote = QLabel(tr("Alles andere richtet GoGoHam in fldigi bei jedem Start selbst ein: "
                          "Funkgerät, PTT, Soundkarte des Funkgeräts (Ton & Ansagen), Rufzeichen, "
                          "Locator, RTTY 45,45 Baud / 170 Hz, Weitergabe der geloggten QSOs an "
                          "GoGoHam und Contest-Makros (F1–F8 in fldigi)."))
        rnote.setWordWrap(True)
        rnote.setStyleSheet("color:#888888;")
        rf.addRow(rnote)
        self.btn_level = QPushButton(tr("Sendepegel einmessen …"))
        self.btn_level.setToolTip(tr("fldigi sendet kurz einen Dauerton, GoGoHam liest die ALC des "
                                     "Funkgeräts und stellt den Pegel in fldigi passend ein – nur "
                                     "an Dummy-Load oder auf freier Frequenz mit kleiner Leistung"))
        self.btn_level.clicked.connect(self._calibrate)
        self.lbl_level = QLabel("")
        lrow = QHBoxLayout()
        lrow.addWidget(self.btn_level)
        lrow.addWidget(self.lbl_level, 1)
        rf.addRow(tr("Sendepegel:"), lrow)
        self._show_level()
        self.rtty_tx.currentIndexChanged.connect(lambda _i: self._update_fsk())
        self._update_fsk()
        lay.addWidget(box)

        box = QGroupBox(tr("QSOs aus FT8-Programmen"))
        QVBoxLayout(box).addWidget(wsjtx_page)
        lay.addWidget(box)
        lay.addStretch(1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._show)
        self._update_hint()
        self.refresh()
        if check:
            self.start_check()

    # ---------------------------------------------------------------- Stand anzeigen
    def refresh(self) -> None:
        for app in extapps.APPS:
            self.found[app.key] = extapps.find(app.key)
        self._show()

    def start_check(self) -> None:
        """Im Hintergrund fragen, welche Programme die Paketverwaltung anbietet (dauert
        bei manchen Distributionen ein paar Sekunden)."""
        todo = [a.key for a in extapps.APPS if not self.found.get(a.key)]
        # 0.10.14: bei WS und Flathub-Programmen auch die Version prüfen (GoGoHam hält sie aktuell)
        vers = [a.key for a in extapps.APPS if self.found.get(a.key)
                and (a.flatpak or a.sf)]
        for k in todo:
            self.pkg[k] = None
        self._versions_done = not vers

        def work() -> None:
            pm = extapps.package_manager()
            for k in todo:
                self.pkg[k] = extapps.available_package(k, pm)
            for k in vers:
                path = self.found.get(k)
                inst = extapps.installed_version(k, path, pm)
                new = extapps.newest_version(k, path, pm)
                self.versions[k] = (inst, new)
                if extapps.update_available(inst, new):
                    self.pkg[k] = extapps.available_package(k, pm)
            self._versions_done = True

        threading.Thread(target=work, daemon=True).start()
        self._timer.start(300)

    def _show(self) -> None:
        busy = False
        for app in extapps.APPS:
            k = app.key
            st, btn = self.labels[k], self.buttons[k]
            if self._installing == k:
                st.setText(tr("wird deinstalliert …") if self._removing == k else
                           getattr(self, "_dl_text", "") or tr("wird installiert …"))
                btn.setEnabled(False)
                busy = True
            elif self.found.get(k):
                inst, new = self.versions.get(k, ("", ""))
                if self._update(k):
                    st.setText("✔ " + tr("installiert {v} – neu: {n}", v=extapps.nice_version(inst),
                                         n=extapps.nice_version(new)))
                    st.setStyleSheet("color:#b26a00;")
                    btn.setText(tr("Aktualisieren"))
                    btn.setEnabled(not self._installing)
                else:
                    st.setText("✔ " + (tr("installiert {v}", v=extapps.nice_version(inst)) if inst
                                       else tr("installiert")))
                    st.setStyleSheet("color:#1b8a3a;")
                    btn.setText(tr("Downloadseite"))
                    btn.setEnabled(True)
            else:
                st.setStyleSheet("")
                pkg = self.pkg.get(k, "")
                if k in self.pkg and pkg is None:
                    st.setText(tr("nicht installiert – prüfe …"))
                    btn.setText(tr("Installieren"))
                    btn.setEnabled(False)
                    busy = True
                elif pkg:
                    st.setText(tr("nicht installiert"))
                    btn.setText(tr("Installieren"))
                    btn.setEnabled(not self._installing)
                else:
                    st.setText(tr("nicht installiert – kein Paket"))
                    btn.setText(tr("Zur Downloadseite"))
                    btn.setEnabled(True)
            if k in self.setup_buttons:
                self.setup_buttons[k].setEnabled(bool(self.found.get(k)) and self._installing != k)
            rb = self.remove_buttons[k]
            rb.setVisible(bool(self.found.get(k)))
            rb.setEnabled(not self._installing)
        if not self._versions_done:
            busy = True
        if not busy and self._timer.isActive():
            self._timer.stop()

    def _show_level(self) -> None:
        v = self.cfg.get("fldigi_txatten")
        self.lbl_level.setText(tr("eingemessen: {db} dB", db=f"{float(v):g}") if v is not None
                               else tr("noch nicht eingemessen (fldigi-Standard)"))

    def _calibrate(self) -> None:
        mw = self.parent()
        while mw is not None and not hasattr(mw, "calibrate_fldigi_level"):
            mw = mw.parent()
        if mw is None:
            return
        self.apply()                              # AFSK/FSK-Wahl gilt schon beim Einmessen
        mw.calibrate_fldigi_level(self)
        self._show_level()

    def _update_fsk(self) -> None:
        on = self.rtty_tx.currentData() == "fsk"
        for w in (self.fsk_port, self.fsk_line, self.fsk_hint):
            w.setEnabled(on)

    def _log_meta(self) -> dict | None:
        """Angaben des offenen Logs (Rufzeichen, Locator) – None ohne Log."""
        mw = self.parent()
        while mw is not None and not hasattr(mw, "meta"):
            mw = mw.parent()
        if mw is None or getattr(mw, "db", None) is None:
            return None
        meta = getattr(mw, "meta", None)
        return meta if isinstance(meta, dict) else None

    @staticmethod
    def _station_note(name: str, st: dict, origin: str, prof: dict) -> str:
        """Was zusätzlich eingetragen wurde – und was fehlt (0.10.9)."""
        from .companions import no_sound_text
        parts = []
        if st.get("mycall") or st.get("grid"):
            parts.append(tr("Rufzeichen und Locator: {v}", v=" · ".join(
                x for x in (st.get("mycall", "").upper(), st.get("grid", "").upper()) if x)))
        else:
            parts.append(tr("Rufzeichen und Locator fehlen noch – sie kommen beim nächsten "
                            "Einrichten aus deinem Log."))
        if origin:
            parts.append(tr("Soundkarte: {v}", v=extapps.nice_sound(st["sound_out"])))
        else:
            parts.append(no_sound_text(name, prof))
        return "\n".join(parts)

    def _profile(self) -> dict | None:
        """Das aktive Funkgerät-Profil (Station → Funkgerät-Profil) – keine eigene Auswahl."""
        return rigprofiles.active(self.cfg)

    def _update_hint(self) -> None:
        p = self._profile()
        if p is None:
            self.hint.setText(tr("Noch kein Funkgerät eingerichtet – bitte zuerst unter "
                                 "„Funkgerät“ ein Profil anlegen."))
            return
        text = tr("Verbunden wird das aktive Funkgerät: {name} (Port {port}) – umschalten unter "
                  "Station → Funkgerät-Profil.", name=p.get("name", ""), port=p.get("port"))
        if p.get("start", True) and not p.get("service"):
            text += " " + tr("Bei diesem Profil startet GoGoHam rigctld selbst – das "
                             "FT8-Programm erreicht das Funkgerät dann nur, solange GoGoHam "
                             "läuft.")
        self.hint.setText(text)

    # ---------------------------------------------------------------- Knöpfe
    def _update(self, key: str) -> bool:
        """Gibt es eine neuere Version, die GoGoHam installieren kann? (0.10.14)"""
        inst, new = self.versions.get(key, ("", ""))
        return bool(self.pkg.get(key)) and extapps.update_available(inst, new)

    def _main_clicked(self, key: str) -> None:
        if (not self.found.get(key) or self._update(key)) and self.pkg.get(key):
            self.install(key)
        else:
            self.open_url(extapps.BY_KEY[key].url)

    def install(self, key: str) -> None:
        from .. import applog
        if self._proc is not None:
            return
        app, pkg = extapps.BY_KEY[key], self.pkg.get(key) or ""
        if pkg.startswith(extapps.WS_AUR):             # WS auf Arch über das AUR
            self._install_aur(key, pkg[len(extapps.WS_AUR):])
            return
        if pkg.startswith(extapps.SF):                 # WS direkt von SourceForge
            self._install_dg2ycb(key, pkg[len(extapps.SF):])
            return
        cmd = extapps.install_command(pkg)
        if cmd is None:
            self.tell(tr("{name} installieren", name=app.name), tr(
                "GoGoHam kann {name} hier nicht selbst installieren (keine bekannte "
                "Paketverwaltung oder kein pkexec). Die Downloadseite wird geöffnet.",
                name=app.name))
            self.open_url(app.url)
            return
        applog.message(f"{app.name} installieren: {cmd[-1]}")
        self._run_install(key, cmd)

    # ---------------------------------------------------------------- Deinstallieren (0.10.17)
    def uninstall(self, key: str) -> None:
        from .. import applog
        if self._proc is not None or self._installing:
            return
        app = extapps.BY_KEY[key]
        title = tr("{name} deinstallieren", name=app.name)
        path = self.found.get(key)
        if not path:
            return
        if extapps.running(key):
            self.tell(title, tr("{name} läuft gerade – bitte zuerst schließen.", name=app.name))
            return
        pkg = extapps.removable_package(key, path)
        cmd = extapps.uninstall_command(pkg) if pkg else None
        if cmd is None:
            self.tell(title, tr("GoGoHam kann {name} hier nicht selbst entfernen – es wurde wohl "
                                "nicht über die Paketverwaltung installiert. Bitte auf demselben "
                                "Weg entfernen, auf dem es installiert wurde.", name=app.name))
            return
        inst = self.versions.get(key, ("", ""))[0] or extapps.installed_version(key, path)
        name = f"{app.name} {extapps.nice_version(inst)}".strip()
        text = tr("{name} jetzt deinstallieren?\n\nDeine Einstellungen und Logs des Programms "
                  "bleiben erhalten – nach erneutem Installieren ist alles wie vorher.", name=name)
        if pkg.startswith(extapps.FLATPAK):
            text += "\n\n" + tr("Nicht mehr gebrauchte Flatpak-Bestandteile werden mit entfernt "
                                 "(das gibt Speicherplatz frei).")
        if not self.ask(title, text):
            return
        applog.message(f"{app.name} deinstallieren: {cmd[-1]}")
        self._removing = key
        self._run_install(key, cmd, remove=True)

    def _run_install(self, key: str, cmd: list[str], aur: bool = False,
                     remove: bool = False) -> None:
        from PySide6.QtCore import QProcess
        from .. import applog
        app = extapps.BY_KEY[key]
        self._installing = key
        self._show()
        proc = self._proc = QProcess(self)

        def finished(code: int, _status=None) -> None:
            if self._proc is None:
                return
            err = bytes(proc.readAllStandardError()).decode(errors="replace").strip()
            proc.deleteLater()
            self._proc = None
            self._installing = ""
            self._removing = ""
            self.versions.pop(key, None)            # nach dem Aktualisieren nicht erneut anbieten
            self.refresh()
            if remove:
                self._removed(app, code, err)
                return
            if code == 0 and self.found.get(key):
                self._desktop_link(key, True)
                if app.ft8 or key == "fldigi":
                    self.setup_connection(key, fresh=True)
                else:
                    self.tell(app.name, tr("{name} ist installiert.", name=app.name))
            elif aur:
                self.tell(app.name, tr("{name} ist nicht installiert – im Konsolenfenster stand, "
                                       "woran es lag.", name=app.name))
            elif code in (126, 127):
                self.tell(app.name, tr("Abgebrochen – kein Passwort eingegeben."))
            else:
                applog.message(f"{app.name}: Installation fehlgeschlagen ({code}): {err[-500:]}",
                               "warn")
                self.tell(app.name, tr("{name} ließ sich nicht installieren: {e}", name=app.name,
                                       e=(err.splitlines() or [str(code)])[-1]))

        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda _e: finished(-1))
        proc.start(cmd[0], cmd[1:])

    def _desktop_link(self, key: str, on: bool) -> None:
        """Live-Stick (0.10.19, Nutzerwunsch): installierte Programme auf den Desktop legen."""
        from .. import applog, livestick
        if not livestick.is_live():
            return
        if on:
            link = extapps.add_desktop_link(key, self.found.get(key))
            applog.message(f"Desktop-Verknüpfung: {link or 'keine Startmenü-Datei gefunden'}")
        else:
            extapps.remove_desktop_link(key)

    def _removed(self, app, code: int, err: str) -> None:
        from .. import applog
        if code == 0 and not self.found.get(app.key):
            self._desktop_link(app.key, False)
            self.tell(app.name, tr("{name} ist deinstalliert.", name=app.name))
            if self._check:
                self.start_check()                  # „Installieren“ wieder anbieten
        elif code in (126, 127):
            self.tell(app.name, tr("Abgebrochen – kein Passwort eingegeben."))
        elif code == 0:                             # z. B. Flatpak weg, Paket der Distribution da
            self.tell(app.name, tr("{name} ist noch ein zweites Mal installiert (aus einer anderen "
                                   "Quelle). Zum Entfernen noch einmal „Deinstallieren …“.",
                                   name=app.name))
        else:
            applog.message(f"{app.name}: Deinstallieren fehlgeschlagen ({code}): {err[-500:]}",
                           "warn")
            self.tell(app.name, tr("{name} ließ sich nicht deinstallieren: {e}\n\nOft braucht "
                                   "ein anderes Programm es noch – dann bleibt es installiert.",
                                   name=app.name, e=(err.splitlines() or [str(code)])[-1]))

    # ------------------------------------------------ WS vom Entwickler (0.10.13)
    def _install_dg2ycb(self, key: str, kind: str) -> None:
        """Neuestes Paket beim Entwickler laden (Prüfsumme geprüft), dann über die Paketverwaltung
        installieren – die nötigen Bibliotheken kommen dabei aus den Paketquellen."""
        from PySide6.QtCore import QTimer
        from .. import applog, wsdl
        app = extapps.BY_KEY[key]
        remove: list[str] = []
        if kind.startswith("deb"):
            # 0.10.47.4: WS aus den Paketquellen (dasselbe Programm, älter) wird ersetzt;
            # WSJT-X hat dieselben Dateien – das nur nach Rückfrage entfernen.
            remove = wsdl.installed_debs(wsdl.REPLACE_DEBS)
            other = wsdl.installed_debs(wsdl.CONFLICT_DEBS)
            if other:
                if not self._ask(tr("{name} installieren", name=app.name), tr(
                        "WS und WSJT-X lassen sich hier nicht gleichzeitig installieren – beide "
                        "bringen dieselben Dateien mit.\n\nWSJT-X entfernen und WS installieren? "
                        "Deine Einstellungen bleiben erhalten.")):
                    return
                remove += other
        self._installing = key
        self._dl_text = tr("lädt herunter …")
        self._show()
        state: dict = {}

        def work() -> None:
            try:
                p = wsdl.latest(kind, project=app.sf)
                if p is None:
                    state["err"] = tr("Beim Entwickler war kein passendes Paket zu finden "
                                      "(Internet?).")
                    return
                state["ver"] = p.version

                def prog(done: int, total: int) -> None:
                    state["prog"] = (done, total)
                folder = Path(os.path.expanduser(f"~/.cache/gogoham/{app.sf}"))
                state["path"] = wsdl.download(p, folder, prog)
            except ValueError:
                state["err"] = tr("Die geladene Datei ist beschädigt (Prüfsumme stimmt nicht). "
                                  "Bitte später noch einmal versuchen.")
            except Exception as e:  # noqa: BLE001 – Netzfehler
                state["err"] = str(e)
            finally:
                state["done"] = True

        threading.Thread(target=work, daemon=True).start()
        timer = QTimer(self)

        def poll() -> None:
            if "prog" in state:
                d, t = state["prog"]
                self._dl_text = (tr("lädt herunter … {a} von {b} MB", a=d // 1048576,
                                    b=t // 1048576) if t else
                                 tr("lädt herunter … {a} MB", a=d // 1048576))
                self._show()
            if not state.get("done"):
                return
            timer.stop()
            timer.deleteLater()
            self._dl_text = ""
            if "err" in state:
                self._installing = ""
                self._show()
                applog.message(f"{app.name}: Laden fehlgeschlagen: {state['err']}", "warn")
                self.tell(app.name, tr("{name} ließ sich nicht laden: {e}", name=app.name,
                                       e=state["err"]))
                return
            shell = wsdl.install_shell(state["path"], extapps.package_manager(), remove)
            if shell is None:
                self._installing = ""
                self._show()
                return
            applog.message(f"{app.name} {state.get('ver', '')} vom Entwickler installieren: {shell}")
            self._installing = ""
            self._run_install(key, ["pkexec", "/bin/sh", "-c", shell])

        timer.timeout.connect(poll)
        timer.start(300)

    def _install_aur(self, key: str, helper: str) -> None:
        """Arch/Garuda: AUR-Paket in einem sichtbaren Konsolenfenster bauen lassen."""
        import shutil
        from .. import wsdl
        app = extapps.BY_KEY[key]
        line = f"{helper} -S --needed {wsdl.PROJECTS[app.sf].aur}"
        end = tr("Fertig – Fenster mit der Eingabetaste schließen.")
        cmd = wsdl.terminal_command(
            ["sh", "-c", f"{line}; echo; echo '{end}'; read x"], shutil.which)
        if cmd is None:
            self.tell(app.name, tr("Bitte in einem Terminal eingeben:\n\n{cmd}", cmd=line))
            return
        if not self._ask(app.name, tr(
                "{name} kommt aus dem AUR und wird dabei auf diesem Rechner gebaut – das kann "
                "einige Minuten dauern. Es öffnet sich ein Konsolenfenster, das nach dem "
                "Passwort fragt. Jetzt starten?", name=app.name)):
            return
        self._run_install(key, cmd, aur=True)

    def _ask(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes

    def setup_connection(self, key: str, fresh: bool = False) -> bool:
        """Verbindung zu GoGoHam im Programm eintragen. Bei vorhandener Einrichtung erst
        zeigen, was sich ändert, und fragen. True = eingetragen (oder schon richtig)."""
        app = extapps.BY_KEY[key]
        title = tr("{name}: Einstellungen übertragen", name=app.name)
        p = self._profile()
        if p is None:
            self.tell(title, tr("Noch kein Funkgerät eingerichtet – bitte zuerst unter "
                                "„Funkgerät“ ein Profil anlegen."))
            return False
        if extapps.running(key):
            self.tell(title, tr("{name} läuft gerade. Bitte erst {name} beenden – sonst "
                                "überschreibt es die Einstellungen beim Beenden wieder.",
                                name=app.name))
            return False
        if key == "fldigi":
            return self._setup_fldigi(p, title, fresh)
        w = self.wsjtx_page
        host = p.get("host", "127.0.0.1") or "127.0.0.1"
        udp_host = w.address.text().strip() or "127.0.0.1"
        st, origin = extapps.station_settings(self.cfg, self._log_meta(), p, key=key)
        args = (host, int(p["port"]), udp_host, w.port.value(), st)
        path = extapps.ini_path(key, binary=self.found.get(key))
        diff = extapps.changes(path, *args)
        if not diff:
            self.tell(title, tr("{name} ist schon mit GoGoHam verbunden – nichts zu ändern.",
                                name=app.name))
            ok = True
        else:
            if path.is_file() and not fresh:
                rows = "\n".join("• " + label + (tr(" (bisher: {old})", old=old) if old else "")
                                 for label, old in diff)
                if not self.ask(title, tr("GoGoHam würde in {name} nur Folgendes ändern:",
                                          name=app.name) + "\n\n" + rows + "\n\n" +
                                tr("Alles andere bleibt, wie es ist. Vorher wird eine "
                                   "Sicherungskopie angelegt. Ändern?")):
                    return False
            try:
                backup = extapps.apply(path, *args)
            except OSError as e:
                self.tell(title, tr("Ließ sich nicht eintragen: {e}", e=e))
                return False
            text = tr("{name} ist jetzt mit GoGoHam verbunden (Funkgerät {p}, Port {port}).",
                      name=app.name, p=p.get("name", ""), port=p["port"])
            if backup:
                text += "\n\n" + tr("Sicherungskopie: {f}", f=str(backup))
            text += "\n\n" + self._station_note(app.name, st, origin, p)
            self.tell(title, text)
            ok = True
        w.enabled.setChecked(True)        # GoGoHam nimmt die QSOs an (gespeichert mit OK)
        return ok

    def _setup_fldigi(self, p: dict, title: str, fresh: bool) -> bool:
        from .. import fldigi
        if fldigi.running():
            self.tell(title, tr("{name} läuft gerade. Bitte erst {name} beenden – sonst "
                                "überschreibt es die Einstellungen beim Beenden wieder.",
                                name="fldigi"))
            return False
        self.apply()
        st, _origin = extapps.station_settings(self.cfg, self._log_meta(), p)
        want = fldigi.wanted(p.get("host", "127.0.0.1") or "127.0.0.1", int(p["port"]),
                             st["mycall"], st["grid"],
                             self.cfg.get("rtty_tx", "afsk"), self.cfg.get("rtty_fsk_port", ""),
                             self.cfg.get("rtty_fsk_line", "DTR"))
        from .companions import FLDIGI_UDP_PORT
        want.update(fldigi.logging_settings(FLDIGI_UDP_PORT))
        path = fldigi.def_path()
        if not fldigi.changes(path, want):
            self.tell(title, tr("{name} ist schon mit GoGoHam verbunden – nichts zu ändern.",
                                name="fldigi"))
            return True
        try:
            backup = fldigi.apply(path, want)
        except OSError as e:
            self.tell(title, tr("Ließ sich nicht eintragen: {e}", e=e))
            return False
        text = tr("{name} ist jetzt mit GoGoHam verbunden (Funkgerät {p}, Port {port}).",
                  name="fldigi", p=p.get("name", ""), port=p["port"])
        if backup:
            text += "\n\n" + tr("Sicherungskopie: {f}", f=str(backup))
        text += "\n\n" + tr("Am einfachsten startest du fldigi über GoGoHam (bei RTTY-Contests "
                             "von selbst, sonst Station → Digitalprogramm starten). Dann stimmt "
                             "auch die Soundkarte, und die QSOs landen in GoGoHam.")
        self.tell(title, text)
        return True

    def apply(self) -> bool:
        self.cfg["ft8_program"] = self.ft8_pref.currentData() or ""
        self.cfg["rtty_tx"] = self.rtty_tx.currentData() or "afsk"
        self.cfg["rtty_fsk_port"] = self.fsk_port.currentText().strip()
        self.cfg["rtty_fsk_line"] = self.fsk_line.currentText()
        return self.wsjtx_page.apply()

    def shutdown(self) -> None:
        self._timer.stop()
