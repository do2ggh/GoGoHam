"""Programm-Einstellungen (~/.config/gogoham/config.json)."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

DEFAULTS = {
    "last_log": "",
    "font_size": 15,
    "theme": "system",              # system / light / dark
    "language": "auto",             # auto (Sprache des Systems) / de / en …
    "splash_ton": False,            # Mithörton beim Startbildschirm (nur PC-Lautsprecher)
    # Auto-CQ (F1 wird wiederholt): Länge des Rufs + Hörpause
    # „Enter sendet“ (ESM, ab 0.8.9): Enter löst je nach Lage F1–F4 aus; Standard aus
    "esm_enabled": False,
    # Ansagen per Sprachausgabe (0.8.26): Standard aus
    "announce_enabled": False,
    "announce_backend": "auto",      # auto / speechd / espeak
    "announce_rate": "normal",       # slow / normal / fast / very_fast
    "announce_spelling": "letters",  # letters (D L 1 …) / phonetic (Delta Lima 1 …)
    "announce_events": {},           # je Ereignis an/aus (fehlt = an)
    "esm_mode": "run",              # run = du rufst CQ · sp = du rufst an (Search & Pounce)
    "autocq_msg_sec": 3,
    "autocq_listen_sec": 8,
    # Sicherung alle … Minuten (wenn sich etwas geändert hat)
    "backup_minutes": 10,
    "stick_backup": True,        # Live-Stick: Logs auch in den Austausch-Ordner (0.10.8)
    "stick_hint_done": False,    # Live-Stick: Hinweis „nicht abziehen“ gezeigt
    # Contest-Regeln von GitHub holen (beim Anlegen eines Logs)
    "rules_auto_update": True,
    # Tägliches Update beim Start (ab 0.8.10): Regeln, cty.dat, MASTER.SCP, DOKs, Flaggen
    "daily_update": True,
    "daily_update_last": "",        # Datum (JJJJ-MM-TT) der letzten erfolgreichen Nachfrage
    "flags_last_check": "",         # fehlende Flaggen höchstens einmal im Monat nachladen
    # Neue GoGoHam-Version (ab 0.9.4): einmal am Tag bei GitHub nachsehen, Hinweis je Version 1×
    "version_check": True,
    "version_check_last": "",
    "version_hint_shown": "",
    # CW-Tempo mit Bild auf/ab (ab 0.8.10): Schrittweite in WpM
    "cw_wpm_step": 2,
    # DX-Cluster (ab 0.8.12)
    # Zusatzfenster beim Programmstart öffnen (ab 0.8.14.1; offen = Funktion an, Standard: keins)
    "open_scp": False,
    "open_bandmap": False,          # Bandmap = DX-Cluster verbunden
    "open_beacons": False,          # Bakenanzeige über das RBN
    "open_map": False,              # Grayline-Karte (ab 0.8.15)
    # Grayline-Karte (ab 0.8.15): Kartenart und was gezeigt wird
    "map_kind": "rect",
    "map_background": "nasa",       # nasa / relief / simple (Kartenbilder ab 0.8.15)             # rect = Weltkarte, azimuthal = Kreiskarte um den Standort
    "map_daynight": True,
    "map_twilight": True,
    "map_path": True,
    "map_grid": True,               # Locator-Gitter beim Zoomen
    "map_rivers": True,
    "map_cities": True,
    "map_beacons": True,            # NCDXF-Baken auf der Karte (0.8.15.1)
    "map_spots": True,              # Cluster-Spots des aktiven Bandes auf der Karte (0.8.15.1)
    "map_beam": True,               # Rotor-Beam auf der Karte (0.8.23.1)
    "open_rotor": False,            # Rotor-Fenster beim Start öffnen (0.8.23.1)
    "open_propagation": False,      # Bandöffnungs-Vorschau beim Start öffnen (0.8.27)
    "prop_view": "now",             # now = Bänder × Kontinente, hours = nächste 12 Stunden
    "prop_cont": "NA",              # Kontinent der Stundenansicht
    "rotor": {},                    # Rotor (0.8.23), siehe rotor.profile()
    "gps": {},                      # GPS-Empfänger (0.10.25), siehe gps_settings()
    "serial_access_asked": False,   # USB-Freigabe beim Start schon angeboten (0.10.25)
    "rotor_auto": False,            # beim Tippen automatisch drehen (Standard aus)
    "calendar_remind": True,        # Contest-Kalender: beim Start erinnern (0.8.21)
    # Filter CW/SSB/DIGI/UKW (0.8.21.1: neuer Schlüssel – leer heißt jetzt „nichts“; der alte
    # „calendar_kinds“ meinte mit leer „alle“ und wird nicht mehr gelesen)
    "calendar_filter": ["CW", "SSB", "DIGI", "UKW"],
    "cluster_node": "db0sue.de:8000",
    "cluster_custom": "",
    "cluster_call": "",             # leer = Rufzeichen aus dem Log
    "cluster_max_age": 30,          # Minuten
    "cluster_contest_only": True,
    "cluster_spotter_cont": None,   # None = eigener Kontinent (aus dem Rufzeichen)
    "cluster_dx_cont": None,        # None = alle
    # Live-Score
    "livescore_enabled": False,
    "livescore_url": "https://contestonlinescore.com/post/",
    "livescore_user": "",
    "livescore_password": "",
    # Name/QTH beim ADIF-Export
    "callbook_enabled": True,
    "callbook_order": ["hamqth", "qrz"],
    "hamqth_user": "",
    "hamqth_password": "",
    "qrz_user": "",
    "qrz_password": "",
    # CAT über Hamlib rigctld
    "rig_enabled": True,
    "rig_host": "127.0.0.1",
    "rig_port": 4532,
    "rig_autostart": True,
    # Kein Gerät voreingestellt – jeder wählt sein Funkgerät selbst aus der Hamlib-Liste
    "rig_model": 0,
    "rig_device": "",
    "rig_baud": 0,
    "rig_extra": "",
    # Geräte-Profile (bis zu 3); das aktive wird in die rig_*-Felder oben übernommen.
    # GoGoHam startet immer mit Profil 1.
    "rig_profiles": [],
    "rig_profile": 0,
    # WSJT-X
    "wsjtx_enabled": True,
    "wsjtx_address": "224.0.0.1",   # 0.10.43: Gruppe – GoGoHam + GoGoHome bekommen beide alles
    "wsjtx_port": 2237,
    # Solange ein FT8-Programm aktiv ist: Funkgerät nur anzeigen, nicht steuern/senden
    "wsjtx_lock_rig": True,
    # Funktionstasten. SSB: Sprachspeicher des Funkgeräts (voice) oder – ab 0.8.11 – eigene
    # Aufnahmen in GoGoHam (text, siehe voice.py); CW: Text
    "macros_ssb": {
        "F1": {"label": "CQ", "voice": 1, "text": "[CQ] {MYCALL} {MYCALL}"},
        "F2": {"label": "Austausch", "voice": 2, "text": "{CALL} {RST} {EXCH}"},
        "F3": {"label": "TU", "voice": 3, "text": "[TU] {MYCALL}"},
        "F4": {"label": "Mein Call", "voice": 4, "text": "{MYCALL}"},
        "F5": {"label": "Speicher 5", "voice": 5, "text": "{CALL}"},
        "F6": {"label": "Speicher 6", "voice": 6, "text": "[AGN]"},
        "F7": {"label": "Speicher 7", "voice": 7, "text": "[CALLQ]"},
        "F8": {"label": "Speicher 8", "voice": 8, "text": "[NR]"},
    },
    # Sprachausgabe (ab 0.8.11): woher SSB-Ansagen kommen – "rig" = Sprachspeicher im
    # Funkgerät, "gogoham" = eigene Aufnahmen (Einstellungen → Ton & Ansagen → Sprachaufnahmen)
    "voice_source": "rig",
    "voice_mic": "",                # Kennung des Mikrofons (leer = Standard des Systems)
    "voice_monitor": "",            # Probehören (Kopfhörer/Lautsprecher, nie das Funkgerät)
    "voice_rig_out": "",            # Soundkarte des Funkgeräts (Senden)
    "voice_gain_db": 0,             # Verstärkung bei der Aufnahme (0 … 30 dB)
    "voice_send_level": 20,         # Sendepegel zum Funkgerät in %
    "voice_tone": {"preset": "normal", "bass": 0, "lowmid": 0, "mid": 0, "treble": 0,
                   "volume": 100},
    # Eigene Klang-Profile (ab 0.8.11.3): 2 Plätze, je {name, base, bass, lowmid, mid, treble,
    # volume} oder null
    "voice_profiles": [None, None],
    "macros_cw": {
        "F1": {"label": "CQ", "text": "CQ TEST {MYCALL} {MYCALL} TEST"},
        "F2": {"label": "Austausch", "text": "{CALL} 5NN {EXCH}"},
        "F3": {"label": "TU", "text": "TU {MYCALL}"},
        "F4": {"label": "Mein Call", "text": "{MYCALL}"},
        "F5": {"label": "Sein Call", "text": "{CALL}"},
        "F6": {"label": "Nochmal", "text": "AGN?"},
        "F7": {"label": "?", "text": "?"},
        "F8": {"label": "Nr?", "text": "NR?"},
    },
    # RTTY über fldigi (0.10.5/0.10.6)
    "rtty_tx": "afsk",               # "afsk" = Ton über die Soundkarte, "fsk" = Steuerleitung
    "rtty_fsk_port": "",             # Schnittstelle für FSK, z. B. /dev/ttyUSB1
    "rtty_fsk_line": "DTR",          # Leitung für FSK: "DTR" oder "RTS"
    "fldigi_txatten": None,          # eingemessener Sendepegel für fldigi in dB (0.10.7)
    "ft8_program": "",               # bevorzugtes FT8-Programm (extapps-Schlüssel), "" = erstes
}


def config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "gogoham" / "config.json"


def load() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    p = config_path()
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for k, v in data.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except (OSError, ValueError):
            pass
        else:
            migrate(cfg, data)
    return cfg


def migrate(cfg: dict, data: dict) -> None:
    """Einmalige Umstellungen beim Laden (werden beim nächsten Speichern festgeschrieben)."""
    # 0.10.43: WSJT-X & Co. an die Gruppe 224.0.0.1 statt nur an 127.0.0.1 – sonst bekommt bei
    # gleichzeitig laufendem GoGoHome nur eines der Programme die QSOs. Eigene Adressen bleiben.
    if not data.get("wsjtx_multicast_done"):
        if data.get("wsjtx_address", "127.0.0.1") in ("127.0.0.1", "localhost", ""):
            cfg["wsjtx_address"] = "224.0.0.1"
        cfg["wsjtx_multicast_done"] = True


def save(cfg: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)      # enthält Callbook-Passwörter – nur für dich lesbar
    except OSError:
        pass
