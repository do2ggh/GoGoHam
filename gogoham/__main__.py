"""Start: „python3 -m gogoham“ oder der Befehl „gogoham“ (aus dem Python-Paket, ab 0.9.2)."""


def main() -> None:
    # install.sh-Installation: liegt ein per Knopf vorbereitetes Update bereit, wird es jetzt
    # eingespielt – vor allen anderen Programmteilen (ab 0.10.47)
    try:
        from gogoham import selfupdate as _self
        _self.start_hook()
    except Exception:  # noqa: BLE001 – im Zweifel die vorhandene Fassung starten
        pass
    # Live-Stick: liegt im Datenteil eine neuere GoGoHam-Fassung (Aktualisieren per Knopf),
    # startet diese statt der aus dem Stick-Abbild (ab 0.10.24)
    try:
        from gogoham import stickupdate as _su
        _su.switch_if_newer()
    except Exception:  # noqa: BLE001 – im Zweifel die Fassung aus dem Abbild starten
        pass
    # Sprache zuerst setzen – erst danach werden die Programmteile mit ihren Texten geladen
    from gogoham import config as _config
    from gogoham import i18n as _i18n
    _i18n.set_language(_config.load().get("language", "auto"))
    from gogoham.gui.app import main as app_main
    app_main()


if __name__ == "__main__":
    main()
