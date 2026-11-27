"""0.10.47.6: Hinweis nach einem neuen Stick-Abbild (Datei vom Startsystem, siehe
tests/test_stick_aufraeumen.py)."""
from gogoham import extapps, livestick


def test_refreshed(tmp_path):
    f = tmp_path / "stick-aktualisiert"
    assert livestick.refreshed(f) is None                  # keine Datei: nichts anzeigen
    f.write_text("")
    assert livestick.refreshed(f) == []                    # aufgeräumt, keine Verknüpfungen
    f.write_text("wsjtx_improved\n\nfldigi\n")
    keys = livestick.refreshed(f)
    assert keys == ["wsjtx_improved", "fldigi"] and all(k in extapps.BY_KEY for k in keys)
    livestick.refreshed_done(f)
    assert not f.exists() and livestick.refreshed(f) is None
    livestick.refreshed_done(f)                            # schon weg: kein Fehler


def test_refreshed_file_im_benutzerordner():
    assert livestick.refreshed_file().parts[-3:] == (".config", "gogoham", "stick-aktualisiert")


def test_hinweis_fenster(tmp_path, monkeypatch):
    from gogoham.gui import main_window
    f = tmp_path / "stick-aktualisiert"
    f.write_text("wsjtx_improved\nunbekannt\n")
    monkeypatch.setattr(livestick, "refreshed_file", lambda: f)
    shown = []
    monkeypatch.setattr(main_window.QMessageBox, "information",
                        lambda parent, title, text: shown.append(text))
    main_window.MainWindow._stick_refreshed(None)
    assert len(shown) == 1 and "Logs, Einstellungen und WLAN-Zugänge sind erhalten" in shown[0]
    assert shown[0].endswith(extapps.BY_KEY["wsjtx_improved"].name)     # unbekannte Namen fehlen
    assert not f.exists()                                              # nur einmal
