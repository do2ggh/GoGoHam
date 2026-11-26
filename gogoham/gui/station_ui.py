"""Stationslog mit mehreren Plätzen (ab 0.10) – Anbindung an das Hauptfenster.

`StationController` hält Hauptplatz bzw. Platz am Laufen, fragt nach, wenn im Netzwerk ein
Stationslog auftaucht („Mitmachen?“), zeigt den Stand unten in der Statuszeile und gibt
eigene Änderungen weiter. Alles Netzwerk steckt in ``gogoham/station.py``.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QDialog, QFormLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton,
                               QVBoxLayout)

from .. import __version__
from .. import config as cfgmod
from .. import station as st
from ..db import LogDB
from ..i18n import tr

GREEN, RED, GREY = "#1b8a3a", "#c62828", "#777777"


def band_label(band: str) -> str:
    """„20“ -> „20 m“; „70cm“, „23cm“ und GHz-Bänder bleiben, wie sie sind."""
    b = band or ""
    return f"{b} m" if b.replace(".", "").isdigit() else b


class ClickLabel(QLabel):
    """Anzeige unten rechts – ein Klick öffnet das Fenster „Station“ (0.10.3)."""
    on_click = None

    def mousePressEvent(self, ev):  # noqa: N802
        if self.on_click:
            self.on_click()
        super().mousePressEvent(ev)


def default_place_name() -> str:
    try:
        name = socket.gethostname().split(".")[0]
    except OSError:
        name = ""
    return name or tr("Platz")


class StationController:
    def __init__(self, mw):
        self.mw = mw
        self.cfg = mw.cfg
        self.server: st.HostServer | None = None
        self.host: st.HostSync | None = None
        self.client: st.PlaceClient | None = None
        self.place: st.PlaceSync | None = None
        self.log_id = ""
        self.known: tuple[str, int] | None = None   # zuletzt bekannte Adresse des Hauptplatzes
        self.discovery: st.Discovery | None = None
        self._asking = False
        self._asked: set[str] = set()
        self._last_status = 0.0
        self._sent_sig = None
        self._last_state = None
        self._seen: dict[str, dict] = {}         # Fenster „Station“: wer war schon da (0.10.3)
        self._busy_key = None
        self._last_view = 0.0
        self.view = None                          # StationView, setzt das Hauptfenster
        self.view_visible = lambda: False
        self.label = ClickLabel("")
        self.label.setToolTip(tr("Klicken öffnet das Fenster „Station“ (Plätze und "
                                 "Nachrichten)"))
        self.label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.label.setVisible(False)
        self.timer = QTimer(mw)
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)
        # Unsichtbar (Tests, QT_QPA_PLATFORM=offscreen): nicht im Netz suchen – eine Frage
        # „Mitmachen?“ könnte dort niemand beantworten. GOGOHAM_DISCOVERY=1 erzwingt es.
        hidden = os.environ.get("QT_QPA_PLATFORM") == "offscreen" \
            and not os.environ.get("GOGOHAM_DISCOVERY")
        if self.cfg.get("station_discovery", True) and not hidden \
                and not os.environ.get("GOGOHAM_NO_DISCOVERY"):
            self.discovery = st.Discovery()
            self.discovery.start()

    # ------------------------------------------------------------ Angaben
    @property
    def active(self) -> bool:
        return self.host is not None or self.place is not None

    @property
    def role(self) -> str:
        return "host" if self.host else "place" if self.place else ""

    @property
    def place_name(self) -> str:
        return self.cfg.get("station_place_name") or default_place_name()

    @property
    def operator(self) -> str:
        return (self.cfg.get("station_operator") or "").upper()

    @property
    def tx(self) -> str:
        """Sendernummer dieses Platzes (Multi-OP): eingestellt, sonst Hauptplatz 0, Platz 1."""
        from .. import multiop
        mw = self.mw
        cat = multiop.category(mw.meta)
        own = (mw.meta.get("station_tx") or "") if mw.db else ""
        roles = [v for v, _t in multiop.tx_roles(mw.contest, cat)] if mw.contest else ["0"]
        if own in roles:
            return own
        if self.place and len(roles) > 1:
            return roles[1]
        return roles[0] if roles else "0"

    def set_tx(self, tx: str) -> None:
        if self.mw.db:
            self.mw.db.set_meta({"station_tx": tx})
            self.mw.meta["station_tx"] = tx
            self._send_status()
            self._update_label(force=True)

    def _own_status(self) -> dict:
        mw = self.mw
        return {"op": self.operator, "band": mw.current_band(), "freq": mw.current_freq() or 0,
                "mode": mw.current_mode(), "tx": self.tx}

    def _send_status(self) -> None:
        own = self._own_status()
        self._sent_sig = (own["op"], own["band"], own["mode"], own["tx"])
        self._last_status = time.monotonic()
        if self.place:
            self.place.status(**own)
        elif self.host:
            self.host.set_own(**own)
            self.host.broadcast_places()

    def _status_due(self) -> bool:
        """Band, Betriebsart, Operator oder Sender gewechselt = sofort melden, sonst alle 5 s
        (dann ist auch die Frequenz frisch)."""
        own = self._own_status()
        sig = (own["op"], own["band"], own["mode"], own["tx"])
        return sig != self._sent_sig or time.monotonic() - self._last_status > 5

    def _keys(self) -> dict:
        return dict(self.cfg.get("station_keys") or {})

    def _save_key(self, log_id: str, key: bytes) -> None:
        keys = self._keys()
        keys[log_id] = key.hex()
        self.cfg["station_keys"] = keys
        cfgmod.save(self.cfg)

    def connected(self) -> bool:
        return bool(self.host) or bool(self.place and self.place.connected)

    # ------------------------------------------------------------ Starten / Beenden
    def log_opened(self) -> None:
        """Nach dem Öffnen eines Logs: Stationslog? Dann Hauptplatz bzw. Platz starten."""
        self.stop()
        mw = self.mw
        if mw.db is None or mw.practice is not None:
            return
        meta = mw.meta
        role, log_id = meta.get("station_role", ""), meta.get("station_log_id", "")
        if role not in ("host", "place") or not log_id:
            return
        key_hex = self._keys().get(log_id)
        if not key_hex:
            pw = self._ask_password(meta.get("mycall", ""))
            if pw is None:
                return
            key = st.password_key(pw, log_id)
            self._save_key(log_id, key)
        else:
            key = bytes.fromhex(key_hex)
        self.log_id = log_id
        mw.db.chat_fail_pending()        # vom letzten Mal noch unterwegs = nicht angekommen
        if not self.operator:
            self.ask_operator()
        if role == "host":
            self._start_host(key)
        else:
            try:
                self.known = (meta.get("station_host_addr", ""),
                              int(meta.get("station_host_port", st.TCP_PORT)))
            except ValueError:
                self.known = None
            self.client = st.PlaceClient(key, self._where, self._hello)
            self.place = st.PlaceSync(mw.db, self.client)
            self.client.start()
        self._started = time.monotonic()
        self._update_label(force=True)
        QTimer.singleShot(1500, self._offer_cable_prepare)

    # ------------------------------------------------------------ Kabel ohne Router
    def cable_prepared(self, refresh: bool = False):
        if refresh or not hasattr(self, "_cable_prepared"):
            self._cable_prepared = st.cable_prepared()
        return self._cable_prepared

    def prepare_cable(self, device: str | None = None, parent=None) -> bool:
        ok = st.prepare_cable(device)
        self._cable_prepared = st.cable_prepared()
        w = parent or self.mw
        if ok:
            QMessageBox.information(w, tr("Netzwerk"), tr(
                "Erledigt: Der Kabelanschluss geht jetzt auch ohne Router (Switch oder Kabel direkt). "
                "Mit Router ändert sich nichts."))
        else:
            QMessageBox.warning(w, tr("Netzwerk"), tr(
                "Das Vorbereiten hat nicht geklappt (abgebrochen oder keine Berechtigung)."))
        return ok

    def _offer_cable_prepare(self) -> None:
        """Einmal fragen, sobald ein Stationslog läuft: Kabel auch ohne Router vorbereiten?"""
        asked = self.cfg.get("station_cable_asked")
        asked = 1 if asked is True else int(asked or 0)
        if not self.active or asked >= st.CABLE_PREPARE_VERSION \
                or QApplication.activeModalWidget() is not None:
            return
        if self.cable_prepared(refresh=True) is not False:
            return
        self.cfg["station_cable_asked"] = st.CABLE_PREPARE_VERSION
        cfgmod.save(self.cfg)
        r = QMessageBox.question(self.mw, tr("Stationslog"), tr(
            "Soll dieser Rechner im Stationslog auch ohne Router funktionieren – an einem Switch "
            "oder mit einem Kabel direkt zu einem anderen Rechner (z. B. am Fieldday)?\n\n"
            "Mit Router ändert sich nichts. Einmal „Ja“ genügt."))
        if r == QMessageBox.StandardButton.Yes:
            self.prepare_cable()

    def _check_cable(self) -> None:
        """Alle 10 s: hängt der Rechner am Kabel, hat dort aber keine Adresse (kein Router)?
        Dann von selbst den Knopf anbieten – nicht erst im Fenster suchen lassen."""
        now = time.monotonic()
        if now - getattr(self, "_cable_checked", 0) < 10:
            return
        self._cable_checked = now
        _lines, broken = st.network_summary(st.network_state())
        if broken is None or self._asking or QApplication.activeModalWidget() is not None:
            return
        if now - getattr(self, "_cable_offered", -1e9) < 300:
            return
        self._cable_offered = now
        self._asking = True
        try:
            r = QMessageBox.question(self.mw, tr("Netzwerk"), tr(
                "Am Kabel ({name}) ist kein Router, der Rechner hat dort keine Adresse – die "
                "anderen Plätze können ihn so nicht erreichen.\n\nJetzt für Betrieb ohne Router "
                "einrichten?", name=broken["name"]))
            if r == QMessageBox.StandardButton.Yes:
                self.prepare_cable(broken["name"])
        finally:
            self._asking = False

    def _start_host(self, key: bytes) -> None:
        mw = self.mw
        c = mw.contest
        info = {"log_id": self.log_id, "station": mw.meta.get("mycall", ""),
                "contest": mw.meta.get("contest", ""),
                "contest_name": c.name if c else "", "host_place": self.place_name}
        try:
            self.server = st.HostServer(info, key)
        except OSError:
            mw.statusBar().showMessage(tr("Stationslog: kein freier Netzwerk-Anschluss – andere "
                                          "Plätze können nicht mitmachen"), 15000, level="error")
            return
        self.host = st.HostSync(mw.db, self.server, self.place_name, self.operator,
                                serial_per_band=getattr(c, "serial_per_band", False) is True)
        fw = st.firewall()
        if fw:
            mw.statusBar().showMessage(tr(
                "Stationslog: Auf diesem Rechner läuft eine Firewall – falls andere Plätze "
                "dich nicht finden: Station → Stationslog … → „Firewall freigeben“"), 20000,
                level="warn")

    def stop(self) -> None:
        if self.server:
            self.server.stop()
        if self.client:
            self.client.stop()
        self.server = self.host = self.client = self.place = None
        self.log_id = ""
        self._seen.clear()
        self._busy_key = self._sent_sig = None
        self._update_label(force=True)
        self.refresh_view()

    def shutdown(self) -> None:
        self.stop()
        if self.discovery:
            self.discovery.stop()
        self.timer.stop()

    def _where(self):
        """(Netz-Thread) Wohin verbinden? Alle Wege, auf denen der Hauptplatz gerade ruft
        (IPv4 zuerst, dann IPv6-Link-Local), sonst die zuletzt bekannte Adresse."""
        f = self.discovery.found().get(self.log_id) if self.discovery else None
        targets = list(f.get("addrs") or []) if f else []
        if targets:
            self.known = targets[0]
        elif self.known and self.known[0]:
            targets = [self.known]
        return targets

    def _hello(self) -> dict:
        return {"t": "join", "place": self.place_name, "op": self.operator,
                "last_seq": self.place.last_seq() if self.place else 0, "app": __version__}

    # ------------------------------------------------------------ Änderungen weitergeben
    def stamp(self, q) -> None:
        """Vor dem Speichern eines eigenen QSOs: Platz und Operator eintragen."""
        if self.active:
            q.place = q.place or self.place_name
            q.operator = q.operator or self.operator
        from .. import multiop
        if multiop.category(self.mw.meta):
            q.tx = q.tx or (self.tx if self.active else "0")

    def _sync(self):
        return self.host or self.place

    def qso_added(self, q) -> None:
        s = self._sync()
        if s and q.uid:
            s.put("qso", self.mw.db.record("qso", q.uid))
            if self.place:
                self.place.ask_serial(self._band_key())

    qso_changed = qso_added

    def qso_deleted(self, uid: str) -> None:
        s = self._sync()
        if s and uid:
            s.delete("qso", uid)

    def qtcs_changed(self, qtcs) -> None:
        s = self._sync()
        if s:
            for t in qtcs:
                if t.uid:
                    s.put("qtc", self.mw.db.record("qtc", t.uid))

    def qtc_deleted(self, uid: str) -> None:
        s = self._sync()
        if s and uid:
            s.delete("qtc", uid)

    def meta_changed(self, meta: dict) -> None:
        s = self._sync()
        if s:
            s.meta_changed(meta)

    # ------------------------------------------------------------ Laufende Nummer
    def _per_band(self) -> bool:
        from .. import multiop
        c = self.mw.contest
        return getattr(c, "serial_per_band", False) is True or (
            c is not None and multiop.serial_mode(c, multiop.category(self.mw.meta)) == "band")

    def _band_key(self) -> str:
        return self.mw.current_band() if self._per_band() else ""

    def serial(self, fallback: int) -> int:
        """Nummer für das nächste QSO dieses Platzes. Ohne Verbindung: die eigene Schätzung."""
        if self.host:
            return self.host.serial(self._band_key())
        if self.place and self.place.connected:
            n = self.place.serial_cache.get(self._band_key())
            if n:
                return n
            self.place.ask_serial(self._band_key())
        return fallback

    # ------------------------------------------------------------ Takt
    def tick(self) -> None:
        mw = self.mw
        res = None
        if self.host:
            self.host.serial_per_band = self._per_band()
            res = self.host.process()
            for addr in res["denied"]:
                mw.statusBar().showMessage(tr("Stationslog: {addr} wollte mitmachen – "
                                              "Kennwort falsch", addr=addr), 10000, level="warn")
        elif self.place:
            res = self.place.process()
            if res["denied"]:
                self._denied()
            if res["connected"] is True:
                self._remember_host()
                self.place.ask_serial(self._band_key())
            if res["serial"] is not None and not mw.ed_call.text().strip():
                mw._update_sent()
            self._check_clock()
            if self.place.connected and self._status_due():
                self._send_status()
            if res["connected"] is False and mw.db:
                mw.db.chat_fail_pending()             # ohne Verbindung kommt nichts mehr an
            for mid, ok in res["chat_states"]:
                self._chat_state(mid, ok)
        if self.host and self._status_due():
            self._send_status()
        if res:
            for m in res.get("chats") or []:
                self._chat_in(m)
            if res["meta"] is not None:
                mw.meta = mw.db.get_meta()
                mw._setup_contest()
                mw.reload(keep_entry=True)
            elif res["changed"]:
                self._apply(res.get("recs") or [])
        self._update_label()
        self._maybe_offer()
        if self.active:
            self._check_cable()
        if time.monotonic() - self._last_view > 1.0:
            self._last_view = time.monotonic()
            rows = self.rows() if self.active else []
            self._check_band(rows)
            if self.view_visible():
                self.refresh_view(rows)

    # ------------------------------------------------------------ Fenster „Station“ (0.10.3)
    def _tx_text(self, tx: str) -> str:
        from .. import multiop
        mw = self.mw
        cat = multiop.category(mw.meta) if mw.db else None
        if not cat or not mw.contest:
            return ""
        return dict(multiop.tx_roles(mw.contest, cat)).get(str(tx or "0"), str(tx or ""))

    def rows(self) -> list[dict]:
        """Zeilen fürs Fenster: alle Plätze, auch getrennte und solche, die nur im Log stehen."""
        mw = self.mw
        own_name = self.place_name
        if self.host:
            live = self.host.place_list()
        elif self.place and self.place.connected:
            live = list(self.place.places)
        else:
            live = []
        stats = st.place_stats(mw.qsos if mw.db else [])
        rows, names = [], set()
        own_done = False
        for p in live:
            r = dict(p)
            name = r.get("place", "?")
            if name == own_name and not own_done:
                r.update(self._own_status(), own=True)
                own_done = True
            rows.append(r)
            names.add(name)
        if not own_done and self.active:
            rows.insert(0, dict(self._own_status(), place=own_name, own=True,
                                host=bool(self.host)))
            names.add(own_name)
        for r in rows:
            self._seen[r["place"]] = dict(r, gone=None)
        for name, old in self._seen.items():
            if name in names:
                continue
            if old.get("gone") is None:
                old["gone"] = time.strftime("%H:%M", time.gmtime())
            rows.append(dict(old, band="", freq=0, gone_text=tr(
                "getrennt seit {t} UTC", t=old["gone"])))
            names.add(name)
        for name in sorted(n for n in stats if n and n not in names):
            rows.append({"place": name, "gone_text": tr("nicht verbunden")})
        for r in rows:
            d = stats.get(r.get("place", ""), {})
            r.update(qsos=d.get("qsos", 0), r10=d.get("r10", 0), r60=d.get("r60", 0),
                     tx_text=self._tx_text(r.get("tx", "")) if r.get("op") or r.get("own")
                     else "")
        return rows

    def _check_band(self, rows: list[dict]) -> None:
        """Warnen, wenn ein anderer Platz auf dem eigenen Band ist – einmal je Lage."""
        if not self.active or (self.place and not self.place.connected):
            self._busy_key = None
            return
        band = self.mw.current_band()
        busy = st.band_conflicts(rows).get(band, set())
        others = sorted(busy - {self.place_name})
        key = (band, tuple(others))
        if key == self._busy_key:
            return
        self._busy_key = key
        if not others:
            return
        names = ", ".join(f"„{n}“" for n in others)
        if len(others) == 1:
            txt = tr("Achtung: Platz {places} ist auch auf {band}", places=names,
                     band=band_label(band))
        else:
            txt = tr("Achtung: Plätze {places} sind auch auf {band}", places=names,
                     band=band_label(band))
        self.mw.statusBar().showMessage(txt, 15000, level="warn", speak=False)
        self.mw.announcer.band_busy(band)

    def refresh_view(self, rows: list[dict] | None = None) -> None:
        v = self.view
        if v is None:
            return
        mw = self.mw
        if not self.active:
            v.set_active(False, tr("Kein Stationslog offen. Mehrere Plätze in einem Netzwerk "
                                   "richtest du unter Station → Stationslog … ein."))
            v.set_rows([], {})
            v.set_targets([])
        else:
            rows = self.rows() if rows is None else rows
            if self.place and not self.place.connected:
                v.set_active(True, tr("Keine Verbindung zum Hauptplatz – Nachrichten kommen "
                                      "erst wieder an, wenn die Verbindung steht."))
            else:
                v.set_active(True, "")
            v.set_rows(rows, st.band_conflicts(rows))
            v.set_targets(sorted({r["place"] for r in rows
                                  if not r.get("own") and not r.get("gone_text")}))
        v.set_chats(mw.db.chats() if mw.db and self.active else [])

    def send_chat(self, to: str, text: str) -> None:
        mw = self.mw
        if not self.active or not mw.db or not text.strip():
            return
        if self.host:
            m, ok = self.host.send_chat(to, text)
            state = "ok" if ok else "fail"
        else:
            m, ok = self.place.send_chat(self.place_name, to, text)
            state = "out" if ok is None else "fail"
        mw.db.chat_add(m, state)
        if state == "fail":
            self._chat_failed(to)
        self.refresh_view()

    def _chat_failed(self, to: str) -> None:
        if to:
            txt = tr("Nachricht an {place} nicht zugestellt – der Platz ist gerade nicht "
                     "verbunden", place=f"„{to}“")
        else:
            txt = tr("Nachricht nicht zugestellt – gerade ist kein anderer Platz verbunden")
        self.mw.statusBar().showMessage(txt, 10000, level="warn")

    def _chat_state(self, mid: str, ok: bool) -> None:
        db = self.mw.db
        if not db or not mid:
            return
        db.chat_state(mid, "ok" if ok else "fail")
        if not ok:
            m = next((c for c in db.chats() if c["mid"] == mid), None)
            self._chat_failed(m["to"] if m else "")
        self.refresh_view()

    def _chat_in(self, m: dict) -> None:
        mw = self.mw
        if not mw.db or not m.get("text"):
            return
        mw.db.chat_add(m, "in")
        mw.statusBar().showMessage(tr("Nachricht von {place}: {msg}", place=m.get("from", "?"),
                                      msg=m["text"]), 30000, speak=False)
        mw.announcer.chat(m.get("from", "?"), m["text"])
        self.refresh_view()

    CLOCK_LIMIT = 2.0

    def clock_offset(self) -> float | None:
        """Wie viele Sekunden die eigene Uhr hinter dem Hauptplatz liegt (+) bzw. vorgeht (−)."""
        if self.place and self.client and self.client.connected:
            return self.client.clock_offset
        return None

    def _check_clock(self) -> None:
        off = self.clock_offset()
        if off is None or abs(off) <= self.CLOCK_LIMIT:
            return
        now = time.monotonic()
        if now - getattr(self, "_clock_warned", -1e9) < 600:
            return
        self._clock_warned = now
        self.mw.statusBar().showMessage(clock_text(off) + " " + tr(
            "Station → Stationslog … → „Uhr nach dem Hauptplatz stellen“"), 30000, level="warn")

    def _apply(self, recs) -> None:
        """Änderungen anderer Plätze übernehmen. Nur neue QSOs (am Ende des Logs): anhängen
        und einzeln bewerten – schnell auch bei großen Logs (0.10.2). Sonst alles neu laden."""
        mw = self.mw
        have = {q.uid for q in mw.qsos}
        last = mw.qsos[-1].time if mw.qsos else ""
        new = []
        for kind, uid, deleted in recs:
            if kind != "qso" or deleted or uid in have:
                mw.reload(keep_entry=True)
                return
            new.append(uid)
        if len(new) > 200:                  # große Nachlieferung: einmal alles neu ist schneller
            mw.reload(keep_entry=True)
            return
        rows = [mw.db.record("qso", u) for u in dict.fromkeys(new)]
        qsos = []
        for d in rows:
            if d is None:
                continue
            r = mw.db.conn.execute("SELECT id FROM qso WHERE uid=?", (d["uid"],)).fetchone()
            from ..contests import Qso
            qsos.append(Qso(id=r[0], **d))
        qsos.sort(key=lambda q: q.time)
        # leicht verschobene Uhren (wenige Minuten) sind kein Grund, alles neu zu rechnen
        if qsos and last and qsos[0].time < _minus_minutes(last, 5):
            mw.reload(keep_entry=True)
            return
        for q in qsos:
            mw.add_remote_qso(q)
        mw.refresh_score()
        if mw.ed_call.text().strip():
            mw.update_check()
        else:
            mw._update_sent()

    def _remember_host(self) -> None:
        if self.known and self.mw.db:
            self.mw.db.set_meta({"station_host_addr": self.known[0],
                                 "station_host_port": str(self.known[1])})

    def _denied(self) -> None:
        """Kennwort passt nicht (mehr) – neu fragen."""
        log_id = self.log_id
        pw = self._ask_password(self.mw.meta.get("mycall", ""), wrong=True)
        if pw is None:
            self.stop()
            return
        self._save_key(log_id, st.password_key(pw, log_id))
        self.log_opened()

    def state_text(self) -> tuple[str, str]:
        if self.host:
            n = len(self.host.places) + 1
            return tr("Stationslog: Hauptplatz · {n} Plätze · OP {op}", n=n,
                      op=self.operator or "?"), GREEN
        if self.place:
            if self.place.connected:
                n = max(len(self.place.places), 1)
                return tr("Stationslog: verbunden · {n} Plätze · OP {op}", n=n,
                          op=self.operator or "?"), GREEN
            wait = len(self.mw.db.outbox()) if self.mw.db else 0
            txt = tr("Stationslog: keine Verbindung zum Hauptplatz")
            if wait:
                txt += " " + tr("({n} QSOs warten)", n=wait)
            return txt, RED
        return "", ""

    def _update_label(self, force: bool = False) -> None:
        state = self.state_text()
        if not force and state == self._last_state:
            return
        self._last_state = state
        txt, color = state
        self.label.setText(txt)
        self.label.setStyleSheet(f"color:{color}; font-weight:bold;" if color else "")
        self.label.setVisible(bool(txt))

    # ------------------------------------------------------------ Mitmachen
    def found(self) -> list[dict]:
        if not self.discovery:
            return []
        return [f for lid, f in self.discovery.found().items() if lid != self.log_id]

    def _maybe_offer(self) -> None:
        """Taucht im Netzwerk ein Stationslog auf, das wir noch nicht kennen: nachfragen."""
        mw = self.mw
        # Nicht stören, wer gerade mitfunkt (Hauptplatz oder verbundener Platz). Ein Platz OHNE
        # Verbindung – z. B. ein altes Stationslog, dessen Hauptplatz nicht mehr läuft – soll
        # ein neues Stationslog im Netz aber angeboten bekommen (Nutzer 2026-11-08).
        busy = self.host is not None or (self.place is not None and self.place.connected)
        if self.place is not None and not self.place.connected and \
                time.monotonic() - getattr(self, "_started", 0) < 15:
            busy = True                        # erst kurz warten: vielleicht verbindet er gleich
        if getattr(mw, "_startup_question", False):
            return                             # erst die Frage beim Start („Weitermachen?“)
        if self._asking or busy or mw.practice is not None or not mw.isVisible() \
                or QApplication.activeModalWidget() is not None:
            return
        keys = self._keys()
        declined = set(self.cfg.get("station_declined") or [])
        for f in self.found():
            lid = f["log_id"]
            if lid in keys or lid in declined or lid in self._asked:
                continue
            self._asked.add(lid)
            self._asking = True
            try:
                r = QMessageBox.question(mw, tr("Stationslog im Netzwerk"), tr(
                    "Im Netzwerk läuft das Stationslog {station} – {contest} "
                    "(Hauptplatz: {place}).\n\nMitmachen?", station=f.get("station", "?"),
                    contest=f.get("contest_name") or f.get("contest", ""),
                    place=f.get("host_place", "?")))
                if r == QMessageBox.StandardButton.Yes:
                    self.join(f)
                else:
                    self.cfg["station_declined"] = sorted(declined | {lid})
                    cfgmod.save(self.cfg)
            finally:
                self._asking = False
            return

    def _ask_password(self, station: str, wrong: bool = False) -> str | None:
        text = (tr("Das Kennwort stimmt nicht. Bitte noch einmal eingeben:") if wrong else
                tr("Kennwort des Stationslogs {station}:", station=station))
        pw, ok = QInputDialog.getText(self.mw, tr("Stationskennwort"), text,
                                      QLineEdit.EchoMode.Password)
        return pw if ok and pw else None

    def known_operators(self) -> list[str]:
        """Operatoren dieses Stationslogs: aus den QSOs, den Log-Angaben und dem eigenen."""
        mw = self.mw
        out: list[str] = []
        for o in [q.operator for q in mw.qsos] + \
                str(mw.meta.get("operators", "")).replace(",", " ").split() + [self.operator]:
            o = (o or "").strip().upper()
            if o and o not in out:
                out.append(o)
        return out

    def ask_operator(self) -> None:
        mw = self.mw
        cur = self.operator or (self.cfg.get("station_defaults") or {}).get("mycall", "") \
            or mw.meta.get("operators", "").split(",")[0].split(" ")[0]
        known = self.known_operators()
        items = known if cur in known or not cur else [cur] + known
        if items:
            call, ok = QInputDialog.getItem(mw, tr("Operator"), tr(
                "Wer funkt an diesem Platz? Rufzeichen des Operators (auswählen oder neu "
                "eintippen):"), items, items.index(cur) if cur in items else 0, True)
        else:
            call, ok = QInputDialog.getText(mw, tr("Operator"), tr(
                "Wer funkt an diesem Platz? Rufzeichen des Operators:"),
                QLineEdit.EchoMode.Normal, cur)
        call = (call or "").strip().upper()
        if ok and call and known and call not in known:
            r = QMessageBox.question(mw, tr("Operator"), tr(
                "{call} ist neu in diesem Stationslog. Stimmt das Rufzeichen (kein Tippfehler)?",
                call=call))
            if r != QMessageBox.StandardButton.Yes:
                return
        if ok and call:
            self.cfg["station_operator"] = call
            cfgmod.save(self.cfg)
            self._send_status()
            self._update_label(force=True)

    def join(self, f: dict) -> bool:
        """Einem gefundenen Stationslog beitreten: Kennwort, prüfen, eigene Log-Datei anlegen
        und öffnen."""
        mw = self.mw
        lid = f["log_id"]
        port = int(f.get("port", st.TCP_PORT))
        targets = list(f.get("addrs") or [(f["addr"], port)])
        addr = targets[0][0]
        wrong = False
        while True:
            pw = self._ask_password(f.get("station", "?"), wrong)
            if pw is None:
                return False
            key = st.password_key(pw, lid)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                meta, (addr, port) = self._probe_any(targets, key)
            except st.AuthError:
                wrong = True
                continue
            except (OSError, ValueError, ConnectionError):
                QMessageBox.warning(mw, tr("Stationslog"), tr(
                    "Der Hauptplatz ist gerade nicht erreichbar. Bitte später noch einmal "
                    "versuchen (Station → Stationslog …)."))
                return False
            finally:
                QApplication.restoreOverrideCursor()
            break
        self._save_key(lid, key)
        year = time.gmtime().tm_year
        name = f"station-{meta.get('contest', 'log')}-{year}-" \
               f"{meta.get('mycall', 'call').replace('/', '-')}"
        path = Path(mw._logs_dir()) / f"{name}.ggh"
        n = 2
        while path.exists():
            path = Path(mw._logs_dir()) / f"{name}-{n}.ggh"
            n += 1
        db = LogDB(path)
        db.set_meta(dict(st.shared_meta(meta), station_role="place", station_log_id=lid,
                         station_host_addr=addr, station_host_port=str(port)))
        db.close()
        mw.open_log(str(path))
        mw.statusBar().showMessage(tr("Stationslog {station}: du bist dabei – das Log wird "
                                      "abgeglichen", station=meta.get("mycall", "")), 10000)
        return True

    def _probe_any(self, targets, key):
        hello = {"t": "join", "place": self.place_name, "op": self.operator, "last_seq": 0,
                 "probe": True}
        last = None
        for a, p in targets:
            try:
                return st.probe(a, int(p), key, hello), (a, int(p))
            except st.AuthError:
                raise
            except (OSError, ValueError, ConnectionError) as e:
                last = e
        raise last or OSError("unreachable")

    def join_address(self) -> None:
        """Notweg: Adresse des Hauptplatzes von Hand eingeben."""
        mw = self.mw
        addr, ok = QInputDialog.getText(mw, tr("Stationslog"), tr(
            "Adresse des Hauptplatzes (wird dort im Fenster Station → Stationslog … angezeigt):"))
        addr = (addr or "").strip()
        if not ok or not addr:
            return
        host, _, port = addr.partition(":")
        info = st.ask_info(host, int(port) if port.isdigit() else st.TCP_PORT)
        if not info:
            QMessageBox.warning(mw, tr("Stationslog"), tr(
                "Unter {addr} antwortet kein Hauptplatz. Stimmt die Adresse? Läuft dort "
                "GoGoHam mit dem Stationslog? Vielleicht blockiert eine Firewall.", addr=addr))
            return
        self.join(info)

    def new_host_meta(self, meta: dict, password: str) -> dict:
        """Neues Stationslog anlegen (Fenster „Neues Contest-Log“)."""
        lid = uuid.uuid4().hex
        self._save_key(lid, st.password_key(password, lid))
        return dict(meta, station_role="host", station_log_id=lid)


def _minus_minutes(t: str, m: int) -> str:
    from datetime import datetime, timedelta
    try:
        x = datetime.strptime(t[:19], "%Y-%m-%d %H:%M:%S") - timedelta(minutes=m)
    except ValueError:
        return t
    return x.strftime("%Y-%m-%d %H:%M:%S")


def clock_text(off: float) -> str:
    from ..i18n import num
    sec = num(abs(off), 1)
    if off > 0:
        return tr("Deine Uhr geht {s} s nach (gegenüber dem Hauptplatz).", s=sec)
    return tr("Deine Uhr geht {s} s vor (gegenüber dem Hauptplatz).", s=sec)


def own_addresses() -> list[str]:
    """IPv4-Adressen dieses Rechners im Netzwerk (für die Anzeige beim Hauptplatz)."""
    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))          # es wird nichts gesendet – nur Weg ermitteln
        out.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return [a for a in out if not a.startswith("127.")]


class StationDialog(QDialog):
    """Station → Stationslog …: Stand, Plätze, Mitmachen, Firewall."""

    def __init__(self, ctl: StationController, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.setWindowTitle(tr("Stationslog"))
        lay = QVBoxLayout(self)
        self.lbl_state = QLabel("")
        self.lbl_state.setWordWrap(True)
        lay.addWidget(self.lbl_state)
        form = QFormLayout()
        self.ed_place = QLineEdit(ctl.place_name)
        self.ed_op = QLineEdit(ctl.operator)
        form.addRow(tr("Name dieses Platzes:"), self.ed_place)
        form.addRow(tr("Operator:"), self.ed_op)
        from .. import multiop
        from PySide6.QtWidgets import QComboBox
        self.cb_tx = QComboBox()
        cat = multiop.category(ctl.mw.meta)
        for val, txt in multiop.tx_roles(ctl.mw.contest, cat) if ctl.mw.contest else []:
            self.cb_tx.addItem(txt, val)
        self.cb_tx.setCurrentIndex(max(0, self.cb_tx.findData(ctl.tx)))
        if cat and self.cb_tx.count() > 1:
            form.addRow(tr("Sender:"), self.cb_tx)
        lay.addLayout(form)
        lay.addWidget(QLabel(tr("Plätze:")))
        self.lst_places = QListWidget()
        self.lst_places.setMaximumHeight(110)
        lay.addWidget(self.lst_places)
        lay.addWidget(QLabel(tr("Stationslogs im Netzwerk:")))
        self.lst_found = QListWidget()
        self.lst_found.setMaximumHeight(90)
        self.lst_found.itemDoubleClicked.connect(lambda _i: self._join())
        lay.addWidget(self.lst_found)
        row = QHBoxLayout()
        self.btn_join = QPushButton(tr("Mitmachen"))
        self.btn_join.clicked.connect(self._join)
        btn_addr = QPushButton(tr("Mit Adresse verbinden …"))
        btn_addr.clicked.connect(lambda: (self.accept(), ctl.join_address()))
        row.addWidget(self.btn_join)
        row.addWidget(btn_addr)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(QLabel(tr("Netzwerk:")))
        self.lbl_net = QLabel("")
        self.lbl_net.setWordWrap(True)
        lay.addWidget(self.lbl_net)
        self.btn_direct = QPushButton(tr("Kabelverbindung ohne Router einschalten"))
        self.btn_direct.setToolTip(tr("Für Switch oder Kabel direkt von Rechner zu Rechner: "
                                      "die Netzwerkverwaltung soll nicht auf einen Router warten"))
        self.btn_direct.clicked.connect(self._direct)
        self.btn_direct.setVisible(False)
        lay.addWidget(self.btn_direct)
        self.lbl_clock = QLabel("")
        self.lbl_clock.setWordWrap(True)
        lay.addWidget(self.lbl_clock)
        self.btn_clock = QPushButton(tr("Uhr nach dem Hauptplatz stellen"))
        self.btn_clock.clicked.connect(self._set_clock)
        self.btn_clock.setVisible(False)
        lay.addWidget(self.btn_clock)
        self.fw = st.firewall()
        self.lbl_fw = QLabel("")
        self.lbl_fw.setWordWrap(True)
        lay.addWidget(self.lbl_fw)
        self.btn_fw = QPushButton(tr("Firewall freigeben"))
        self.btn_fw.clicked.connect(self._firewall)
        self.btn_fw.setVisible(bool(self.fw))
        lay.addWidget(self.btn_fw)
        bl = QHBoxLayout()
        btn_help = QPushButton("?")
        btn_help.clicked.connect(self._help)
        bl.addWidget(btn_help)
        bl.addStretch(1)
        ok = QPushButton(tr("OK"))
        ok.clicked.connect(self.accept)
        bl.addWidget(ok)
        lay.addLayout(bl)
        self.resize(520, 520)
        self._found: list[dict] = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def _help(self) -> None:
        from .dialogs import show_help
        show_help(self, "station")

    def refresh(self) -> None:
        ctl = self.ctl
        txt, color = ctl.state_text()
        if not txt:
            txt = tr("Dieses Log ist kein Stationslog. Ein Stationslog legst du über Log & Contest → "
                     "Neues Contest-Log an (Häkchen „Stationslog für mehrere Plätze“).")
        if ctl.host:
            addrs = ", ".join(own_addresses()) or "?"
            txt += "\n" + tr("Adresse für den Notfall: {addr}", addr=addrs)
        self.lbl_state.setText(txt)
        self.lbl_state.setStyleSheet(f"color:{color}; font-weight:bold;" if color else "")
        places = (ctl.host.place_list() if ctl.host else ctl.place.places if ctl.place else [])
        self.lst_places.clear()
        for p in places:
            extra = " · ".join(x for x in (p.get("op", ""), p.get("band", "") and
                                           f"{p['band']} m", p.get("mode", ""),
                                           p.get("tx", "") and tr("Sender {tx}", tx=p["tx"]))
                               if x)
            mark = tr(" (Hauptplatz)") if p.get("host") else ""
            self.lst_places.addItem(f"{p.get('place', '?')}{mark}" + (f" – {extra}" if extra
                                                                       else ""))
        self._found = ctl.found()
        cur = self.lst_found.currentRow()
        self.lst_found.clear()
        for f in self._found:
            self.lst_found.addItem(tr("{station} – {contest} (Hauptplatz: {place})",
                                      station=f.get("station", "?"),
                                      contest=f.get("contest_name") or f.get("contest", ""),
                                      place=f.get("host_place", "?")))
        if self._found:
            self.lst_found.setCurrentRow(max(0, min(cur, len(self._found) - 1)))
        self.btn_join.setEnabled(bool(self._found))
        lines, self._broken = st.network_summary(st.network_state())
        if ctl.place and ctl.client and ctl.client.connected and ctl.client.via:
            lines.append(tr("✔ Verbunden mit dem Hauptplatz über {addr}",
                            addr=st.plain_addr(ctl.client.via)))
        self.lbl_net.setText("\n".join(lines))
        prepared = self.ctl.cable_prepared(refresh=True)
        if prepared is True:
            lines.append(tr("✔ Kabelanschluss ist auch für Betrieb ohne Router vorbereitet."))
        elif prepared is False:
            lines.append(tr("⚠ Kabelanschluss ist noch nicht für Betrieb ohne Router vorbereitet "
                            "(Switch oder Kabel direkt)."))
        self.lbl_net.setText("\n".join(lines))
        self.btn_direct.setText(tr("Kabel ohne Router vorbereiten") if prepared is False else
                                tr("Kabelverbindung ohne Router einschalten"))
        self.btn_direct.setVisible(self._broken is not None or prepared is False)
        off = ctl.clock_offset()
        if off is None:
            self.lbl_clock.setText("")
            self.btn_clock.setVisible(False)
        elif abs(off) <= ctl.CLOCK_LIMIT:
            self.lbl_clock.setText(tr("✔ Uhr stimmt mit dem Hauptplatz überein."))
            self.lbl_clock.setStyleSheet("")
            self.btn_clock.setVisible(False)
        else:
            self.lbl_clock.setText("⚠ " + clock_text(off))
            self.lbl_clock.setStyleSheet(f"color:{RED}; font-weight:bold;")
            self.btn_clock.setVisible(True)
        if self.fw:
            self.lbl_fw.setText(tr("Auf diesem Rechner läuft eine Firewall ({name}). Wenn sich "
                                   "die Plätze nicht finden, gib das Stationslog frei – du wirst "
                                   "nach dem Systempasswort gefragt.", name=self.fw))
        elif ctl.discovery is not None and not ctl.discovery.ok:
            self.lbl_fw.setText(tr("Hinweis: Das Suchen im Netzwerk ist auf diesem Rechner "
                                   "gerade nicht möglich (Anschluss belegt)."))

    def _direct(self) -> None:
        dev = self._broken["name"] if self._broken else None
        self.ctl.prepare_cable(dev, parent=self)
        self.refresh()

    def _set_clock(self) -> None:
        off = self.ctl.clock_offset()
        if off is None:
            return
        try:
            r = subprocess.run(st.clock_command(off), timeout=120)
            ok = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        if ok:
            self.ctl.client.clock_offset = None          # neu messen
            QMessageBox.information(self, tr("Uhr"), tr("Die Uhr ist nach dem Hauptplatz "
                                                        "gestellt."))
        else:
            QMessageBox.warning(self, tr("Uhr"), tr("Das Stellen der Uhr hat nicht geklappt "
                                                    "(abgebrochen oder falsches Passwort)."))
        self.refresh()

    def _join(self) -> None:
        i = self.lst_found.currentRow()
        if 0 <= i < len(self._found):
            f = self._found[i]
            self.accept()
            self.ctl.join(f)

    def _firewall(self) -> None:
        cmd = st.firewall_command(self.fw or "")
        if not cmd:
            return
        try:
            r = subprocess.run(cmd, timeout=120)
        except (OSError, subprocess.SubprocessError):
            r = None
        if r is not None and r.returncode == 0:
            QMessageBox.information(self, tr("Firewall"), tr("Das Stationslog ist in der "
                                                             "Firewall freigegeben."))
        else:
            QMessageBox.warning(self, tr("Firewall"), tr(
                "Das Freigeben hat nicht geklappt. Von Hand im Terminal:\n{cmd}",
                cmd=" ".join(cmd[3:]) if cmd else ""))

    def accept(self) -> None:
        ctl = self.ctl
        place = self.ed_place.text().strip()
        op = self.ed_op.text().strip().upper()
        changed = False
        if place and place != ctl.place_name:
            ctl.cfg["station_place_name"] = place
            changed = True
        if op and op != ctl.operator:
            ctl.cfg["station_operator"] = op
            changed = True
        tx = self.cb_tx.currentData()
        if tx is not None and tx != ctl.tx:
            ctl.set_tx(tx)
        if changed:
            cfgmod.save(ctl.cfg)
            if ctl.active:
                ctl.log_opened()                 # neu anmelden mit neuem Namen/Operator
        super().accept()
