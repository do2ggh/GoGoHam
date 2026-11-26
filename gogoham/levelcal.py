"""Sendepegel für fldigi einmessen (ab 0.10.7).

fldigi sendet einen Dauerton (Tune), GoGoHam erhöht den Pegel in 3-dB-Schritten von leise nach
laut und liest dabei die ALC-Anzeige des Funkgeräts über rigctld. Genommen wird der lauteste
Schritt, bei dem die ALC noch (fast) nicht ausschlägt – so bleibt das RTTY-Signal sauber.

Den Pegel stellt fldigi nur über ein Makro-Kommando um (<TXATTEN:…>); dafür legt GoGoHam in
fldigi unsichtbare Makros ab Nummer LEVEL_MACRO_BASE an (siehe fldigi.write_macros).

Gesendet wird nur, wenn der Nutzer im Fenster ausdrücklich zustimmt; Abbrechen, Fehler und das
Ende schalten sofort auf Empfang.
"""

from __future__ import annotations

import subprocess
import threading
import time

STEPS = tuple(range(-30, 1, 3))         # -30, -27 … -3, 0 dB
LEVEL_MACRO_BASE = 36                   # fldigi-Makros 36 … 46 (4. Reihe, sonst ungenutzt)
ALC_LIMIT = 0.1                          # darüber schlägt die ALC sichtbar aus
SETTLE = 0.8                             # Sekunden je Schritt, bis Gerät und Anzeige stehen


def level_macros() -> list[tuple[int, str, str]]:
    """(Makro-Nummer, Beschriftung, Text) für jede Pegelstufe."""
    return [(LEVEL_MACRO_BASE + i, f"TX {db} dB", f"<TXATTEN:{db:.1f}>")
            for i, db in enumerate(STEPS)]


def macro_for(db: float) -> int:
    """Makro-Nummer der Stufe, die ``db`` am nächsten liegt."""
    i = min(range(len(STEPS)), key=lambda k: abs(STEPS[k] - db))
    return LEVEL_MACRO_BASE + i


def read_meter(host: str, port: int, level: str = "ALC", run=subprocess.run) -> float | None:
    """Messwert des Funkgeräts über rigctld (None = kann das Gerät/Hamlib nicht)."""
    try:
        r = run(["rigctl", "-m", "2", "-r", f"{host}:{port}", "l", level],
                capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        return float(r.stdout.split()[0].replace(",", "."))
    except (IndexError, ValueError):
        return None


def choose(results: list[tuple[int, float]], limit: float = ALC_LIMIT) -> tuple[int, str]:
    """Aus (dB, ALC)-Messungen die Stufe wählen. Rückgabe (dB, Befund):
    "ok" – lauteste Stufe ohne ALC; "too_loud" – schon die leiseste Stufe treibt die ALC
    (am Gerät den USB-Pegel senken); "no_alc" – auch voll keine ALC (Pegel 0 dB)."""
    if not results:
        return STEPS[0], "none"
    quiet = [db for db, alc in results if alc <= limit]
    if not quiet:
        return results[0][0], "too_loud"
    best = max(quiet)
    if best == results[-1][0] and best == STEPS[-1]:
        return best, "no_alc"
    return best, "ok"


class Calibration(threading.Thread):
    """Läuft im Hintergrund: Tune an, Stufen durchgehen, ALC lesen, Tune aus.
    ``progress(text)`` wird aus dem Thread gerufen; das Ergebnis steht danach in
    ``result`` = (dB, Befund, Messungen) oder ``error``."""

    def __init__(self, client, host: str, port: int, read=read_meter, settle: float = SETTLE,
                 steps=STEPS, progress=None):
        super().__init__(daemon=True, name="pegel")
        self.client, self.host, self.port = client, host, port
        self.read, self.settle, self.steps = read, settle, steps
        self.progress = progress or (lambda _t: None)
        self.cancel = threading.Event()
        self.result: tuple[int, str, list] | None = None
        self.error = ""

    def run(self) -> None:
        x = self.client.proxy
        measured: list[tuple[int, float]] = []
        try:
            if self.read(self.host, self.port) is None:
                self.error = "no_meter"
                return
            x.main.run_macro(macro_for(self.steps[0]))
            x.main.tune()
            for db in self.steps:
                if self.cancel.is_set():
                    self.error = "cancelled"
                    return
                x.main.run_macro(macro_for(db))
                time.sleep(self.settle)
                vals = [v for v in (self.read(self.host, self.port) for _ in range(2))
                        if v is not None]
                alc = max(vals) if vals else 0.0
                measured.append((db, alc))
                self.progress(f"{db:+d} dB · ALC {alc:.2f}")
                if alc > ALC_LIMIT * 3:
                    break                       # deutlich zu laut – nicht weiter hochdrehen
        except Exception as e:                  # noqa: BLE001 – fldigi weg o. Ä.
            self.error = str(e) or "error"
        finally:
            for f in (lambda: x.main.abort(), lambda: x.main.rx()):
                try:
                    f()                         # sofort zurück auf Empfang
                except Exception:               # noqa: BLE001
                    pass
        if not self.error:
            db, verdict = choose(measured)
            try:
                x.main.run_macro(macro_for(db))
            except Exception:                   # noqa: BLE001
                pass
            self.result = (db, verdict, measured)
