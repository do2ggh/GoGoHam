"""Zusatzprogramme passend zum Contest starten (ab 0.10.6).

RTTY-Contest → fldigi, FT8/FT4-Contest → das bevorzugte FT8-Programm. Gefunkt wird im
Zusatzprogramm, geloggt in GoGoHam (wie bei WSJT-X). GoGoHam richtet das Programm vorher ein
und beendet es wieder, wenn das Log gewechselt oder GoGoHam beendet wird – aber nur, wenn
GoGoHam es selbst gestartet hat.

fldigi: geloggte QSOs kommen als ADIF per UDP (Port FLDIGI_UDP_PORT), das Rufzeichenfeld von
fldigi liest GoGoHam über XML-RPC mit und zeigt Dupe/Multi/Infobox.
"""

from __future__ import annotations

import queue
import subprocess
import threading
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from .. import extapps, fldigi, rigprofiles
from ..i18n import tr

FLDIGI_UDP_PORT = 2239          # geloggte QSOs von fldigi (WSJT-X nimmt 2237)


def program_for(contest) -> str | None:
    """Welche Art Programm der Contest braucht: "fldigi", "ft8" oder None (CW/SSB/gemischt)."""
    modes = set(getattr(contest, "modes", set()) or set()) if contest else set()
    if modes == {"RY"}:
        return "fldigi"
    if modes == {"DG"}:
        return "ft8"
    return None


def ft8_choice(cfg: dict, find=extapps.find) -> str | None:
    """Das bevorzugte FT8-Programm, sonst das erste installierte."""
    keys = [a.key for a in extapps.APPS if a.ft8]
    pref = cfg.get("ft8_program", "")
    if pref in keys and find(pref):
        return pref
    return next((k for k in keys if find(k)), None)


def serial_template(contest, own_call: str = "") -> str:
    """Eigener Austausch für die fldigi-Makros; die laufende Nummer wird zu <CNTR>."""
    if contest is None:
        return ""
    a, b = contest.sent_exchange(7391), contest.sent_exchange(8462)
    if a == b:
        return a
    out = a
    for s in ("7391", "07391"):
        out = out.replace(s, "<CNTR>")
    return out



def no_sound_text(name: str, prof: dict | None) -> str:
    """Hinweis: zum Funkgerät gehört keine eigene Soundkarte (z. B. FT-891)."""
    return tr("{rig}: keine Soundkarte des Funkgeräts gefunden – {name} hört und sendet so "
              "nichts. Ist das Funkgerät eingeschaltet und per USB angeschlossen? Funkgeräte "
              "ohne eigene USB-Soundkarte (z. B. FT-891) brauchen ein Ton-Interface an der "
              "DATA-Buchse; dann einmal unter Einstellungen → Funkgerät → „Soundkarte des "
              "Funkgeräts“ wählen.", rig=(prof or {}).get("name", ""), name=name)

class FldigiLink(threading.Thread):
    """Verbindung zu fldigi über XML-RPC: Rufzeichenfeld mitlesen, Nummer setzen, beenden.
    Ergebnisse in ``events`` als (Art, Wert)."""

    def __init__(self, client_factory=fldigi.Client, connect_timeout: float = 40.0,
                 poll: float = 0.3):
        super().__init__(daemon=True, name="fldigi-link")
        self.client_factory = client_factory
        self.connect_timeout = connect_timeout
        self.poll = poll
        self.jobs: queue.Queue = queue.Queue()
        self.events: queue.Queue = queue.Queue()
        self._halt = threading.Event()       # nicht _stop – das gehört threading.Thread

    def submit(self, job: str, *args) -> None:
        self.jobs.put((job, args))

    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        c = self.client_factory()
        t0 = time.monotonic()
        while not self._halt.is_set():
            try:
                ver = c.version()
                c.set_rtty()
                self.events.put(("connected", ver))
                break
            except Exception:                              # noqa: BLE001 – fldigi startet noch
                if time.monotonic() - t0 > self.connect_timeout:
                    self.events.put(("failed", ""))
                    return
                self._halt.wait(0.5)
        last_call, errors = None, 0
        while not self._halt.is_set():
            try:
                while True:
                    try:
                        job, args = self.jobs.get_nowait()
                    except queue.Empty:
                        break
                    if job == "counter":
                        c.proxy.log.set_contest_counter(str(args[0]))
                    elif job == "send":                # QTC-Zeile (WAE RTTY), dann Empfang
                        c.proxy.text.clear_tx()
                        c.proxy.text.add_tx("\n" + " ".join(str(args[0]).split()) + " ^r")
                        c.proxy.main.tx()
                    elif job == "abort":
                        c.proxy.main.abort()
                    elif job == "terminate":
                        c.terminate()
                        self.events.put(("terminated", ""))
                        return
                call = str(c.proxy.log.get_call() or "").strip().upper()
                if call != last_call:
                    last_call = call
                    self.events.put(("call", call))
                errors = 0
            except Exception:                              # noqa: BLE001
                errors += 1
                if errors >= 8:
                    self.events.put(("lost", ""))
                    return
            self._halt.wait(self.poll)


class Companions:
    """Startet und beendet die Zusatzprogramme für das Hauptfenster."""

    def __init__(self, mw, popen=subprocess.Popen):
        self.mw = mw
        self.popen = popen
        self.procs: dict[str, object] = {}          # von GoGoHam gestartet: Schlüssel -> Popen
        self.link: FldigiLink | None = None
        self.listener = None                         # UDP-Empfänger für fldigi
        self.mirrored = ""                           # zuletzt aus fldigi übernommenes Rufzeichen
        self.connected = False                       # fldigi antwortet über XML-RPC
        self.ask = lambda title, text: QMessageBox.question(
            mw, title, text) == QMessageBox.StandardButton.Yes          # Tests: Ersatz
        self.timer = QTimer()
        self.timer.timeout.connect(self._drain)

    # ---------------------------------------------------------------- Log gewechselt
    def log_opened(self) -> None:
        """Passendes Programm zum Contest starten; ein selbst gestartetes, das nicht mehr
        passt, beenden."""
        mw = self.mw
        if mw.practice is not None:
            return
        need = program_for(mw.contest)
        want = None
        if need == "fldigi":
            want = "fldigi" if extapps.find("fldigi") else None
        elif need == "ft8":
            want = ft8_choice(mw.cfg)
        for key in list(self.procs):
            if key != want or key == "fldigi":       # fldigi: neu starten (neue Makros)
                self.stop(key)
        if need and not want:
            mw.sb.showMessage(
                tr("Für diesen Contest braucht es fldigi – Einstellungen → Zusatzprogramme → "
                   "„Installieren“") if need == "fldigi" else
                tr("Für diesen Contest braucht es ein FT8-Programm (WS) – "
                   "Einstellungen → Zusatzprogramme"), 15000, "warn")
            return
        if want and want not in self.procs:
            self.start(want)

    # ---------------------------------------------------------------- starten
    def start(self, key: str) -> bool:
        mw = self.mw
        app = extapps.BY_KEY[key]
        path = extapps.find(key)
        if not path:
            mw.sb.showMessage(tr("{name} ist nicht installiert – Einstellungen → "
                                 "Zusatzprogramme", name=app.name), 10000, "warn")
            return False
        prof = rigprofiles.active(mw.cfg) if mw.cfg.get("rig_enabled") else None
        if key == "fldigi":
            return self._start_fldigi(path, prof)
        return self._start_ft8(key, path, prof)

    def _start_fldigi(self, path: str, prof: dict | None) -> bool:
        mw = self.mw
        if self.link is not None:
            return True
        if not fldigi.running():
            if prof is None:
                mw.sb.showMessage(tr("fldigi braucht ein eingerichtetes Funkgerät (Einstellungen → "
                                     "Funkgerät)"), 10000, "warn")
                return False
            meta = mw.meta or {}
            st, _origin = extapps.station_settings(mw.cfg, meta, prof)
            want = fldigi.wanted(prof.get("host", "127.0.0.1") or "127.0.0.1", int(prof["port"]),
                                 st["mycall"], st["grid"],
                                 mw.cfg.get("rtty_tx", "afsk"), mw.cfg.get("rtty_fsk_port", ""),
                                 mw.cfg.get("rtty_fsk_line", "DTR"), mw.cfg.get("fldigi_txatten"))
            want.update(fldigi.logging_settings(FLDIGI_UDP_PORT))
            try:
                fldigi.apply(fldigi.def_path(), want)
                # Makros immer: Contest-Makros (ohne Log: ohne Austausch) + Pegel-Makros
                exch = serial_template(mw.contest, meta.get("mycall", "")) \
                    if mw.contest is not None and mw.db is not None else "<CNTR>"
                fldigi.write_macros(fldigi.macros_path(), exch)
                env = fldigi.environment(st["sound_out"])
                self.procs["fldigi"] = self.popen(
                    extapps.launch_cmd(path, env), env=env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError as e:
                mw.sb.showMessage(tr("fldigi ließ sich nicht starten: {e}", e=e), 12000, "warn")
                return False
            mw.sb.showMessage(tr("fldigi wird gestartet – fertig eingerichtet für diesen Contest"),
                              10000)
        else:
            mw.sb.showMessage(tr("fldigi lief schon – GoGoHam übernimmt die geloggten QSOs, die "
                                 "Einstellungen von fldigi bleiben, wie sie sind"), 12000, "warn")
        self._start_listener()
        self.link = FldigiLink()
        self.link.start()
        self.timer.start(150)
        if mw.cabrillo_mode_now() != "RY":
            mw.cb_mode.setCurrentText("RTTY")          # Funkgerät auf RTTY bzw. LSB-Daten
        return True

    def _start_listener(self) -> None:
        from ..wsjtx import WsjtxListener
        if self.listener is None:
            self.listener = WsjtxListener(FLDIGI_UDP_PORT, "127.0.0.1", program="fldigi")
            self.listener.start()

    def _start_ft8(self, key: str, path: str, prof: dict | None) -> bool:
        mw = self.mw
        app = extapps.BY_KEY[key]
        if extapps.running(key):
            mw.sb.showMessage(tr("{name} läuft schon", name=app.name), 6000)
            return True
        if prof is not None:
            ini = extapps.ini_path(key, binary=path)
            st, origin = extapps.station_settings(mw.cfg, mw.meta if mw.db else None, prof,
                                                  key=key)
            args = (prof.get("host", "127.0.0.1") or "127.0.0.1", int(prof["port"]),
                    mw.cfg.get("wsjtx_address", "127.0.0.1") or "127.0.0.1",
                    int(mw.cfg.get("wsjtx_port", 2237)), st)
            if not origin:
                mw.sb.showMessage(no_sound_text(app.name, prof), 15000, "warn")
            diff = extapps.changes(ini, *args)
            if diff:
                ok = True
                if ini.is_file():
                    rows = "\n".join("• " + label + (tr(" (bisher: {old})", old=old) if old else "")
                                     for label, old in diff)
                    ok = self.ask(tr("{name}: Einstellungen übertragen", name=app.name),
                                  tr("GoGoHam würde in {name} nur Folgendes ändern:",
                                     name=app.name) + "\n\n" + rows + "\n\n" +
                                  tr("Alles andere bleibt, wie es ist. Vorher wird eine "
                                     "Sicherungskopie angelegt. Ändern?"))
                if ok:
                    try:
                        extapps.apply(ini, *args)
                    except OSError as e:
                        mw.sb.showMessage(tr("Ließ sich nicht eintragen: {e}", e=e), 10000, "warn")
        if not mw.cfg.get("wsjtx_enabled"):
            mw.cfg["wsjtx_enabled"] = True             # QSOs annehmen
            from .. import config as cfgmod
            cfgmod.save(mw.cfg)
            mw.start_wsjtx()
        try:
            self.procs[key] = self.popen(extapps.launch_cmd(path), stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as e:
            mw.sb.showMessage(tr("{name} ließ sich nicht starten: {e}", name=app.name, e=e),
                              12000, "warn")
            return False
        mw.sb.showMessage(tr("{name} wird gestartet", name=app.name), 8000)
        return True

    # ---------------------------------------------------------------- beenden
    def stop(self, key: str) -> None:
        """Ein von GoGoHam gestartetes Programm sauber beenden."""
        proc = self.procs.pop(key, None)
        if key == "fldigi":
            self.connected = False
            link, self.link = self.link, None
            if link is not None:
                if proc is not None:
                    link.submit("terminate")
                    link.join(3)
                link.stop()
            if self.listener is not None:
                self._drain_listener()
                self.listener.stop()
                self.listener = None
            if not self.procs:
                self.timer.stop()
        elif proc is not None:
            w = getattr(self.mw, "wsjtx", None)
            if w is not None and hasattr(w, "close_clients"):
                w.close_clients()                      # WS: „Close“ per UDP
        if proc is None:
            return
        try:
            proc.wait(5)
        except Exception:                              # noqa: BLE001 – hängt: dann hart
            try:
                proc.terminate()
                proc.wait(3)
            except Exception:                          # noqa: BLE001
                pass

    def send_text(self, text: str) -> None:
        """Text über fldigi senden (QTCs geben in RTTY) – nur auf Tastendruck des Nutzers."""
        if self.link is None:
            self.mw.sb.showMessage(tr("RTTY senden: fldigi läuft nicht (Station → "
                                      "Digitalprogramm starten → fldigi)"), 8000, "warn")
            return
        self.link.submit("send", text)

    def abort(self) -> None:
        if self.link is not None:
            self.link.submit("abort")

    def shutdown(self) -> None:
        for key in list(self.procs):
            self.stop(key)
        if self.link is not None or self.listener is not None:
            self.stop("fldigi")

    # ---------------------------------------------------------------- Ereignisse
    def _drain_listener(self) -> None:
        lst = self.listener
        while lst is not None and not lst.records.empty():
            rec = lst.records.get_nowait()
            self.mw._wsjtx_qso(rec, program="fldigi")
            if self.mw.ed_call.text().strip().upper() == (rec.get("CALL") or "").upper():
                self.mw.clear_entry()              # geloggt: Eingabe für das nächste QSO frei
            self._sync_counter()

    def _sync_counter(self) -> None:
        if self.link is not None and self.mw.contest is not None:
            self.link.submit("counter", self.mw._serial())

    def _drain(self) -> None:
        self._drain_listener()
        link = self.link
        while link is not None:
            try:
                kind, val = link.events.get_nowait()
            except queue.Empty:
                break
            if kind == "connected":
                self.connected = True
                self._sync_counter()
            elif kind == "call":
                self.mw.companion_call(val, self.mirrored)
                self.mirrored = val
            elif kind in ("failed", "lost"):
                self.mw.sb.showMessage(tr("fldigi antwortet nicht") if kind == "failed"
                                       else tr("fldigi wurde beendet"), 8000, "warn")
                proc = self.procs.pop("fldigi", None)
                if proc is not None:
                    proc.poll()                        # beendeten Prozess aufräumen
                self.stop("fldigi")
                return
