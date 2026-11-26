"""Reiter „Ansagen“ in den Einstellungen (ab 0.8.26): Sprachausgabe für sehbehinderte
Funkamateure – automatisch bei Ereignissen und auf Tastendruck (Alt+1 … Alt+6)."""

from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout)

from .. import speech
from ..i18n import tr


def keys_text() -> str:
    return tr("Alt+1\tFrequenz und Betriebsart\n"
              "Alt+2\tRufzeichen im Eingabefeld (buchstabiert) mit Dupe/Multi/Punkten\n"
              "Alt+3\tletztes QSO\n"
              "Alt+4\tPunktestand und Anzahl QSOs\n"
              "Alt+5\tUhrzeit (UTC) und Contest-Zeit\n"
              "Alt+6\tletzte Ansage bzw. Meldung wiederholen\n"
              "Esc\tAnsage abbrechen (stoppt auch das Senden)")


def _piper_mb() -> int:
    from .. import piper
    return round(piper.total_size() / 1e6)


class AnnouncePage(QDialog):
    def __init__(self, cfg: dict, parent=None, have_speechd: bool | None = None,
                 have_espeak: bool | None = None, install=None, have_piper: bool | None = None,
                 piper_download=None):
        super().__init__(parent)
        self._install = install
        self._piper_download = piper_download
        self._pi = speech.piper_ok() if have_piper is None else have_piper
        self.cfg = cfg
        self._sd = speech.speechd_ok() if have_speechd is None else have_speechd
        self._es = bool(speech.espeak_exe()) if have_espeak is None else have_espeak
        self._probe: speech.Speaker | None = None
        lay = QVBoxLayout(self)
        intro = QLabel(tr("GoGoHam kann wichtige Dinge vorlesen – gedacht vor allem für "
                          "sehbehinderte Funkamateure. Die Ansagen laufen über die normale "
                          "Sprachausgabe des Systems (Lautsprecher/Kopfhörer), nie über das "
                          "Funkgerät."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.enabled = QCheckBox(tr("Ansagen einschalten"))
        self.enabled.setChecked(bool(cfg.get("announce_enabled", False)))
        lay.addWidget(self.enabled)

        form = QFormLayout()
        self.backend = QComboBox()
        for key, text in (("auto", tr("Automatisch")),
                          ("piper", tr("Piper (natürliche Stimme)")),
                          ("speechd", "speech-dispatcher"), ("espeak", "espeak-ng")):
            self.backend.addItem(text, key)
        self.backend.setCurrentIndex(max(self.backend.findData(cfg.get("announce_backend",
                                                                       "auto")), 0))
        test = QPushButton(tr("Probe"))
        test.setToolTip(tr("Einen Beispielsatz vorlesen"))
        test.clicked.connect(self._test)
        row = QHBoxLayout()
        row.addWidget(self.backend, 1)
        row.addWidget(test)
        form.addRow(tr("Sprachausgabe:"), row)
        self.found = QLabel()
        self.found.setWordWrap(True)
        form.addRow("", self.found)
        self.install_btn = QPushButton(tr("speech-dispatcher jetzt installieren"))
        self.install_btn.setToolTip(tr("Installiert speech-dispatcher und espeak-ng über die "
                                       "Paketverwaltung – Linux fragt nach dem Passwort."))
        self.install_btn.clicked.connect(self._do_install)
        self.install_btn.setVisible(not self._sd and install is not None)
        form.addRow("", self.install_btn)
        self.piper_btn = QPushButton(tr("Natürliche Stimme (Piper) herunterladen, ca. {mb} MB",
                                        mb=_piper_mb()))
        self.piper_btn.setToolTip(tr("Lädt Piper und je eine deutsche und englische Stimme – "
                                     "ohne Passwort, nur für GoGoHam."))
        self.piper_btn.clicked.connect(self._do_piper)
        self.piper_btn.setVisible(not self._pi and piper_download is not None)
        form.addRow("", self.piper_btn)
        self.rate = QComboBox()
        for key, text in (("slow", tr("langsam")), ("normal", tr("normal")),
                          ("fast", tr("schnell")), ("very_fast", tr("sehr schnell"))):
            self.rate.addItem(text, key)
        self.rate.setCurrentIndex(max(self.rate.findData(cfg.get("announce_rate", "normal")), 0))
        form.addRow(tr("Tempo:"), self.rate)
        self.spelling = QComboBox()
        self.spelling.addItem(tr("einzelne Buchstaben (D O 2 G G H)"), "letters")
        self.spelling.addItem(tr("Buchstabieralphabet (Delta Oscar 2 Golf Golf Hotel)"),
                              "phonetic")
        self.spelling.setCurrentIndex(max(self.spelling.findData(
            cfg.get("announce_spelling", "letters")), 0))
        form.addRow(tr("Rufzeichen vorlesen als:"), self.spelling)
        lay.addLayout(form)

        box = QGroupBox(tr("Von selbst ansagen"))
        bl = QVBoxLayout(box)
        ev = cfg.get("announce_events") or {}
        self.events: dict[str, QCheckBox] = {}
        for key, text in (("dupe", tr("Dupe (beim Tippen des Rufzeichens)")),
                          ("new_mult", tr("Neuer Multi (beim Tippen des Rufzeichens)")),
                          ("invalid", tr("QSO zählt nicht (beim Tippen des Rufzeichens)")),
                          ("band", tr("Bandwechsel")),
                          ("mode", tr("Wechsel der Betriebsart")),
                          ("logged", tr("QSO geloggt (mit Rufzeichen)")),
                          ("hints", tr("Warnungen und Fehler aus der Hinweiszeile")),
                          ("qtc", tr("QTC geben in SSB: die Zeile zum Vorlesen (WAE)")),
                          ("band_busy", tr("Stationslog: ein anderer Platz ist auf demselben "
                                           "Band")),
                          ("chat", tr("Stationslog: Nachrichten von anderen Plätzen "
                                      "vorlesen"))):
            cb = QCheckBox(text)
            cb.setChecked(bool(ev.get(key, key not in speech.Announcer.OFF_BY_DEFAULT)))
            bl.addWidget(cb)
            self.events[key] = cb
        lay.addWidget(box)
        keys = QGroupBox(tr("Auf Tastendruck"))
        kl = QVBoxLayout(keys)
        kt = QLabel(keys_text().replace("\t", " – "))
        kt.setWordWrap(True)
        kl.addWidget(kt)
        lay.addWidget(keys)
        lay.addStretch(1)
        self.backend.currentIndexChanged.connect(self._update_found)
        self._update_found()

    def _update_found(self) -> None:
        use = speech.choose(self.backend.currentData() or "auto", self._sd, self._es, self._pi)
        if use is None:
            self.found.setText(tr("Keine Sprachausgabe gefunden. Bitte speech-dispatcher oder "
                                  "espeak-ng installieren, z. B. „sudo pacman -S espeak-ng“ "
                                  "(Arch) bzw. „sudo apt install espeak-ng“ (Debian/Ubuntu)."))
        else:
            txt = tr("Benutzt wird: {name}", name=speech.backend_name(use))
            if not self._pi:
                txt += " · " + tr("Piper ist nicht geladen.")
            if not self._sd:
                txt += " · " + tr("speech-dispatcher ist nicht installiert.")
            if use == "piper":
                from .. import piper
                txt += " · " + tr("Stimmen: {voices}", voices=", ".join(
                    piper.VOICE_CREDITS.values()))
            self.found.setText(txt)

    def _do_install(self) -> None:
        self.install_btn.setEnabled(False)
        self.install_btn.setText(tr("Installiere … (Linux fragt nach dem Passwort)"))

        def done(ok: bool) -> None:
            try:
                self._sd = speech.speechd_ok()
                self.install_btn.setVisible(not self._sd)
                self.install_btn.setEnabled(True)
                self.install_btn.setText(tr("speech-dispatcher jetzt installieren"))
                self._update_found()
            except RuntimeError:                 # Fenster schon zu
                pass
        self._install(done)

    def _do_piper(self) -> None:
        self.piper_btn.setEnabled(False)
        self.piper_btn.setText(tr("Lade … (Fortschritt in der Hinweiszeile)"))

        def done(ok: bool) -> None:
            try:
                self._pi = speech.piper_ok()
                self.piper_btn.setVisible(not self._pi)
                self.piper_btn.setEnabled(True)
                self.piper_btn.setText(tr("Natürliche Stimme (Piper) herunterladen, ca. {mb} MB",
                                          mb=_piper_mb()))
                self._update_found()
            except RuntimeError:                 # Fenster schon zu
                pass
        self._piper_download(done)

    def _test(self) -> None:
        use = speech.choose(self.backend.currentData() or "auto", self._sd, self._es, self._pi)
        if self._probe:
            self._probe.close()
        self._probe = speech.Speaker(use, self.rate.currentData() or "normal")
        call = "DO2GGH"
        self._probe.say(tr("Das ist die Ansage von GoGoHam. {call}, Neuer Multi.",
                           call=speech.spell_call(call, self.spelling.currentData() == "phonetic")))

    def apply(self) -> bool:
        self.cfg["announce_enabled"] = self.enabled.isChecked()
        self.cfg["announce_backend"] = self.backend.currentData() or "auto"
        self.cfg["announce_rate"] = self.rate.currentData() or "normal"
        self.cfg["announce_spelling"] = self.spelling.currentData() or "letters"
        self.cfg["announce_events"] = {k: cb.isChecked() for k, cb in self.events.items()}
        return True

    def shutdown(self) -> None:
        if self._probe:
            self._probe.close()
