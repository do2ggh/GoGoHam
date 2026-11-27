"""Programmstart."""

from __future__ import annotations

from ..i18n import tr

import sys


def app_icon():
    """Programmsymbol: aus dem System (von install.sh installiert), sonst aus assets/."""
    from pathlib import Path
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon
    icon = QIcon.fromTheme("gogoham")
    if not icon.isNull():
        return icon
    assets = Path(__file__).resolve().parent.parent / "assets"
    icon = QIcon()
    for name, size in (("gogoham-klein.svg", 32), ("gogoham-mittel.svg", 64),
                       ("gogoham.svg", 256)):
        if (assets / name).exists():
            icon.addFile(str(assets / name), QSize(size, size))
    return icon


def main() -> None:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(tr("PySide6 fehlt. Unter Garuda/Arch installieren mit:\n"
              "  sudo pacman -S pyside6\n"), file=sys.stderr)
        sys.exit(1)
    from .. import APP_NAME, __version__
    from .. import config as cfgmod
    from .. import applog
    import os
    import platform
    if applog.setup():                    # Protokoll für den Fehlerbericht (ab 0.8.18.3)
        applog.LOG.info("Start %s %s%s · Python %s", APP_NAME, __version__,
                        " (AppImage)" if os.environ.get("APPIMAGE") else "",
                        platform.python_version())

    app = QApplication(sys.argv)
    _qt_tr = install_qt_translation(app)  # noqa: F841 – lebt so lange wie app
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setDesktopFileName("gogoham")      # Taskleiste ordnet das Fenster dem Startmenü-Eintrag zu
    app.setWindowIcon(app_icon())
    from .fitscreen import install as _fit_install   # 0.10.12: Fenster passen auf den Bildschirm
    _fit = _fit_install(app)  # noqa: F841 – lebt so lange wie app
    # Nur ein GoGoHam gleichzeitig: läuft schon eins, kommt dessen Fenster nach vorne – und zwar
    # bevor hier ein Ladebildschirm erscheint (ab 0.8.7)
    from .single import POWEROFF, RAISE, SingleInstance
    single = SingleInstance()
    # „gogoham --herunterfahren“ (Schreibtisch-Symbol auf dem Stick, ab 0.10.48): läuft GoGoHam,
    # fährt es selbst sauber herunter (Rückfrage, Log schließen); sonst nur Rückfrage + Ausschalten
    power_off = POWEROFF_ARG in sys.argv[1:]
    if not single.lock(POWEROFF if power_off else RAISE):
        sys.exit(0)
    if power_off:
        single.release()
        sys.exit(_power_off_only())
    # Startbildschirm mit Morse-Ladebalken „GGH“ (ab 0.8.5.1). Der Mithörton kommt nur aus
    # den Lautsprechern des PCs – mit dem Funkgerät hat er nichts zu tun.
    from .splash import MorseSplash
    splash = MorseSplash(ton=bool(cfgmod.load().get("splash_ton", False)),
                         version=tr("Version {v}", v=__version__))
    splash.show()
    splash.set_status(tr("Lade Contest-Regeln …"))
    from .main_window import MainWindow          # lädt dabei die Regel-Dateien
    win = MainWindow(progress=splash.set_status)
    splash.finish(win)                            # zeigt das Hauptfenster nach dem Durchlauf
    single.listen(win)
    single.on_poweroff = win.stick_poweroff       # Schreibtisch-Symbol „Herunterfahren“ (0.10.48)
    code = app.exec()
    single.release()
    if getattr(win, "restart_requested", False):
        # Neustart, z. B. nach dem Umstellen der Sprache
        import os
        from .. import stickupdate
        stickupdate.clean_env()                  # Stick: danach wieder die neueste Fassung wählen
        os.execv(sys.executable, [sys.executable, "-m", "gogoham", *sys.argv[1:]])
    sys.exit(code)


if __name__ == "__main__":
    main()


POWEROFF_ARG = "--herunterfahren"


def _power_off_only() -> int:
    """GoGoHam läuft nicht: nur fragen und den Rechner ausschalten (0.10.48)."""
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QMessageBox
    from .. import livestick
    cmd = livestick.poweroff_command()
    title = tr("Rechner herunterfahren")
    if not cmd:
        QMessageBox.warning(None, title, tr("Herunterfahren geht hier nicht."))
        return 1
    if QMessageBox.question(None, title, tr(
            "Den Rechner jetzt herunterfahren?\n\nDen Stick erst abziehen, wenn der Rechner "
            "aus ist.")) != QMessageBox.StandardButton.Yes:
        return 0
    return 0 if QProcess.startDetached(cmd[0], cmd[1:]) else 1


def install_qt_translation(app, lang: str | None = None):
    """Qts eigene Texte (OK/Abbrechen/Ja/Nein in Standard-Dialogen, Kontextmenüs) in der
    eingestellten Sprache (ab 0.10.27 – vorher immer Englisch, auch auf Deutsch). Fehlt die
    Qt-Übersetzung auf dem System, bleibt es eben Englisch."""
    from PySide6.QtCore import QLibraryInfo, QTranslator
    from ..i18n import language
    lang = lang or language()
    if lang == "en":
        return None
    tr_ = QTranslator(app)
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    for name in (f"qtbase_{lang}", "qtbase_pt_BR" if lang == "pt" else "",
                 "qtbase_no" if lang == "nb" else ""):
        if name and tr_.load(name, folder):
            app.installTranslator(tr_)
            return tr_
    return None
