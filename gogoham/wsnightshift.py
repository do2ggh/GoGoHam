"""WS im Nightshift-Design (0.10.44, Bereich „Entwicklung“).

WS (WSJT-X Improved) ist ein Qt-Programm und nimmt beim Start ein fremdes Aussehen an:
„ws -style Fusion -stylesheet <Datei>“. Eingerichtet werden
  1. das Aussehen ~/.config/ws-nightshift.qss (Farben wie Nightshift dunkel in theme.py),
  2. der normale Starter „WS“ startet WS so (0.10.47.2, vorher eigener Starter „WS Nightshift“):
     im Startmenü ein gleichnamiger Eintrag in ~/.local/share/applications (verdeckt den des
     Pakets), auf dem Schreibtisch wird ein vorhandenes WS-Symbol umgestellt (Sicherung bzw.
     Verweis in ~/.local/share/gogoham/ws-nightshift/). Kein neues Symbol.
  3. in WS.ini schwarze Schrift für die farbig hinterlegten Dekodierzeilen (sonst nimmt WS die
     helle Schrift des Aussehens – unlesbar auf Hellgrün/Gelb). Mit Sicherungskopie, WS muss zu
     sein. Im normalen WS ändert sich dadurch nichts Sichtbares.
Fest im Programm sind die hellgraue Bandwechsel-Zeile und der Wasserfall – die bleiben.
"""

from __future__ import annotations

import base64
import os
import re
import shlex
import shutil
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import extapps
from .i18n import tr

KEY = "wsjtx_improved"
QSS_NAME = "ws-nightshift.qss"
STARTER_NAME = "ws-nightshift.desktop"     # alter eigener Starter (bis 0.10.47.1) – wird entfernt
MARK = "X-GoGoHam-Nightshift=true"         # kennzeichnet von GoGoHam umgestellte Starter
INI_KEY = "DecodeHighlighting_v2"

# Qt-Datenstrom (QDataStream) eines Pinsels: Stil (1 Byte), Farbe (11), Transformation (72)
_BRUSH = 1 + 11 + 72
_BLACK = bytes([1, 1]) + b"\xff\xff" + bytes(8)      # voller Pinsel, RGB, deckend, 0/0/0

QSS = """/* Nightshift dunkel für WS (WSJT-X Improved) – Farben aus GoGoHam (gogoham/gui/theme.py).
   Bernstein nur im Rahmen (Menü, Köpfe, Reiter, Hauptknopf), Türkis für Auswahl.
   Die Farben der Dekodierzeilen (CQ, eigenes Rufzeichen …) stellt WS selbst ein – sie bleiben. */

/* Grundfarbe nur für Schrift – der Hintergrund bleibt durchsichtig, damit der Verlauf des
   Fensters (Bernstein-Schimmer oben links, Blau unten rechts) überall durchscheint. */
QWidget { color:#E9EEF8; selection-background-color:#0E2F38; selection-color:#E9EEF8; }
QFrame, QStackedWidget, QScrollArea, QSplitter, QTabWidget > QWidget, QDockWidget > QWidget {
    background:transparent; }
QMenu, QToolTip, QComboBox QAbstractItemView, QMessageBox { background-color:#111A2D; }
QWidget:disabled { color:#5A6884; }
QMainWindow, QDialog { background:qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2A2218,
    stop:0.28 #0C1322, stop:0.72 #0C1322, stop:1 #0E2238); }
QLabel, QCheckBox, QRadioButton { background:transparent; }

/* Eingabe- und Listenfelder */
QLineEdit, QTextEdit, QPlainTextEdit, QTextBrowser, QListView, QTreeView, QTableView,
QSpinBox, QDoubleSpinBox, QDateTimeEdit, QTimeEdit {
    background-color:#111A2D; color:#E9EEF8; border:1px solid #4A6694; border-radius:4px;
    alternate-background-color:#18233A; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus { border:1px solid #2A9DF4; }
QComboBox { background-color:#18233A; color:#E9EEF8; border:1px solid #4A6694;
    border-radius:4px; padding:1px 6px; }
QComboBox:hover { border-color:#2A9DF4; }
QComboBox QAbstractItemView { background-color:#111A2D; color:#E9EEF8;
    selection-background-color:#0E2F38; border:1px solid #4A6694; }

/* Rahmen */
QMenuBar { background:qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #18233A, stop:1 #060A13);
    color:#E9EEF8; border-bottom:2px solid #FFB547; }
QMenuBar::item { background:transparent; color:#E9EEF8; padding:4px 10px; border-radius:4px; }
QMenuBar::item:selected, QMenuBar::item:pressed { background:qlineargradient(x1:0, y1:0, x2:0,
    y2:1, stop:0 #FFB547, stop:1 #FF8A3D); color:#1E1200; }
QMenu { background-color:#111A2D; color:#E9EEF8; border:1px solid #4A6694; }
QMenu::item:selected { background:qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FFB547,
    stop:1 #FF8A3D); color:#1E1200; }
QMenu::separator { height:1px; background:#26344F; margin:3px 6px; }
QHeaderView::section { background:qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFB547,
    stop:1 #FF8A3D); color:#1E1200; border:none; border-right:1px solid #FF8A3D;
    padding:3px 6px; font-weight:bold; }
QTableCornerButton::section { background:#FFB547; border:none; }
QTabWidget::pane { border:1px solid #4A6694; }
QTabBar::tab { background:#111A2D; color:#8C9AB5; border:1px solid #4A6694; border-bottom:none;
    border-top-left-radius:6px; border-top-right-radius:6px; padding:4px 12px; margin-right:2px; }
QTabBar::tab:hover { color:#E9EEF8; }
QTabBar::tab:selected { background:qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFB547,
    stop:1 #FF8A3D); color:#1E1200; font-weight:bold; }

/* Knöpfe – nur der Grundzustand; die farbigen Zustände von WS (Senden rot, Monitor grün,
   Auto-Seq …) setzt WS selbst und bleiben erkennbar. */
QPushButton { background:qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1E2A44, stop:1 #111A2D);
    color:#E9EEF8; border:1px solid #4A6694; border-radius:6px; padding:3px 10px; }
QPushButton:hover { background:qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #26365A,
    stop:1 #18233A); border-color:#2A9DF4; }
QPushButton:pressed { background:#18233A; }
QPushButton:checked { border:2px solid #2A9DF4; }
QPushButton:disabled { color:#8C9AB5; }
QPushButton:default { background:qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFB547,
    stop:1 #FF8A3D); color:#1E1200; border:1px solid #FF8A3D; font-weight:bold; }
QToolButton { background:#18233A; color:#E9EEF8; border:1px solid #4A6694; border-radius:4px; }
QToolButton:hover { border-color:#2A9DF4; }

/* Knöpfe, denen WS selbst einen hellen Grund gibt (Band- und Mode-Knöpfe hellgrau,
   DX-Rufzeichen hellblau, Warnungen orange): dort dunkle Schrift, sonst ist sie unlesbar.
   Erkannt wird das an WS' eigener Farbangabe im Knopf. */
QPushButton[styleSheet~="#e1e1e1;"], QToolButton[styleSheet~="#e1e1e1;"],
QPushButton[styleSheet~="#9fafd5;"], QPushButton[styleSheet~="#ff7a05;"],
QPushButton[styleSheet~="orange;}"] { color:#1A2233; }
/* dasselbe für Knöpfe, deren Farbangabe über mehrere Zeilen geht */
QPushButton[styleSheet*="#9fafd5"] { color:#1A2233; }
QPushButton[styleSheet~="#e1e1e1;"]:disabled, QToolButton[styleSheet~="#e1e1e1;"]:disabled {
    color:#6B7385; }

QGroupBox { background:qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(24,35,58,0.85),
    stop:1 rgba(12,19,34,0.35)); border:1px solid #4A6694; border-radius:8px;
    margin-top:1.2em; padding-top:6px; }
QGroupBox::title { subcontrol-origin:margin; subcontrol-position:top left; left:10px;
    padding:0 4px; color:#E9EEF8; font-weight:bold; }
QStatusBar { background:#060A13; border-top:1px solid #4A6694; }
QStatusBar QLabel { background:transparent; }
QProgressBar { background:#111A2D; border:1px solid #4A6694; border-radius:5px;
    text-align:center; }
QProgressBar::chunk { background:qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3FE0D0,
    stop:1 #2A9DF4); border-radius:4px; }
QSlider::groove:horizontal { height:4px; background:#26344F; border-radius:2px; }
QSlider::groove:vertical { width:4px; background:#26344F; border-radius:2px; }
QSlider::handle { background:#3FE0D0; border-radius:6px; width:12px; height:12px; margin:-5px; }
QScrollBar:vertical { background:transparent; width:12px; margin:0; }
QScrollBar::handle:vertical { background:qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3FE0D0,
    stop:1 #2A9DF4); border-radius:5px; min-height:24px; margin:2px; }
QScrollBar:horizontal { background:transparent; height:12px; margin:0; }
QScrollBar::handle:horizontal { background:qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 #3FE0D0, stop:1 #2A9DF4); border-radius:5px; min-width:24px; margin:2px; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:none; }
QToolTip { background-color:#18233A; color:#E9EEF8; border:1px solid #FF8A3D; }

/* Senkrechte Reiter (die kleinen Reiter 1, 2, 3 neben den Sendetexten): WS macht sie sehr
   klein. Darum flache Kästchen ohne Rahmen und Rundung – mit Rahmen werden sie zu Schleifen
   verzerrt. Gewählter Reiter Bernstein, die anderen Nachtblau mit heller Ziffer.
   Seit 0.10.47.3 größer (Nutzer: „sehr klein“): etwa 30 × 45 statt 21 × 12 Pixel. */
QTabBar::tab:left, QTabBar::tab:right { background:#18233A; color:#C9D3E6; border:none;
    border-radius:0; padding:6px 4px; margin:0 0 3px 0; min-width:22px; min-height:30px;
    font-size:11pt; }
QTabBar::tab:left:hover, QTabBar::tab:right:hover { background:#26365A; color:#E9EEF8; }
QTabBar::tab:left:selected, QTabBar::tab:right:selected { background:#FFB547; color:#1E1200;
    font-weight:bold; }

/* Rahmen der Dekodierfenster (Bandaktivität, Rx-Frequenz) und Listen deutlicher absetzen */
QTextEdit, QPlainTextEdit, QTextBrowser, QListView, QTreeView, QTableView {
    border:1px solid #4A6694; }
QTextEdit:focus, QPlainTextEdit:focus, QTextBrowser:focus { border:1px solid #2A9DF4; }

/* WS gibt den Reitern 1, 2, 3 eine dreieckige Form – die zeichnet Qt an dieser Größe als
   Schleifen. Hier auf schlichte Kästchenform umgestellt (gleiche Seite, gleiche Funktion).
   Qt 5 erkennt die Form nur an der Nummer (4–7 = dreieckig oben/unten/links/rechts). */
QTabBar[shape="6"] { qproperty-shape: RoundedWest; }
QTabBar[shape="7"] { qproperty-shape: RoundedEast; }
QTabBar[shape="4"] { qproperty-shape: RoundedNorth; }
QTabBar[shape="5"] { qproperty-shape: RoundedSouth; }

/* Umrandete Flächen und Gruppen (z. B. um die Sendetexte) wie die Dekodierfenster absetzen */
QFrame[frameShape="Box"], QFrame[frameShape="Panel"], QFrame[frameShape="StyledPanel"] {
    border:1px solid #4A6694; }
"""


@dataclass
class Result:
    ok: bool
    lines: list[str] = field(default_factory=list)    # was getan wurde (für die Meldung)
    backup: Path | None = None


def _home(home: str | None) -> Path:
    return Path(home or os.path.expanduser("~"))


def qss_path(home: str | None = None) -> Path:
    return _home(home) / ".config" / QSS_NAME


def desktop_dir(home: str | None = None) -> Path:
    """Schreibtisch-Ordner laut ~/.config/user-dirs.dirs (z. B. „Schreibtisch“), sonst Desktop."""
    h = _home(home)
    try:
        text = (h / ".config" / "user-dirs.dirs").read_text(encoding="utf-8")
        m = re.search(r'^XDG_DESKTOP_DIR="([^"]+)"', text, re.M)
        if m:
            return Path(m.group(1).replace("$HOME", str(h)))
    except OSError:
        pass
    for name in ("Schreibtisch", "Desktop"):
        if (h / name).is_dir():
            return h / name
    return h / "Desktop"


def _apps_dir(home: str | None) -> Path:
    return _home(home) / ".local" / "share" / "applications"


def backup_dir(home: str | None = None) -> Path:
    return _home(home) / ".local" / "share" / "gogoham" / "ws-nightshift"


def starter_paths(home: str | None = None) -> list[Path]:
    """Alter eigener Starter „WS Nightshift“ (Startmenü, Schreibtisch) – nur noch zum Aufräumen."""
    return [_apps_dir(home) / STARTER_NAME, desktop_dir(home) / STARTER_NAME]


def _marked(p: Path) -> bool:
    try:
        return MARK in p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False


def _ours(home: str | None) -> list[Path]:
    """Alle von GoGoHam umgestellten Starter (Startmenü + Schreibtisch)."""
    out = []
    for d in (_apps_dir(home), desktop_dir(home)):
        if d.is_dir():
            out += [p for p in sorted(d.glob("*.desktop")) if not p.is_symlink() and _marked(p)]
    return out


def is_installed(home: str | None = None) -> bool:
    return qss_path(home).is_file() and (bool(_ours(home)) or starter_paths(home)[0].is_file())


def _quote(s: str) -> str:
    return f'"{s}"' if re.search(r"[\s\"\\]", s) else s


def starter_text(binary: str, qss: Path | None = None) -> str:
    """Ersatz, wenn das Paket keinen Starter mitbringt (mit qss: schon umgestellt)."""
    text = ("[Desktop Entry]\nVersion=1.0\nName=WS\n"
            "Comment=Amateur Radio Weak Signal Operating\n"
            f"Exec={_quote(binary)}\n"
            "Icon=ws_icon\nTerminal=false\nX-MultipleArgs=false\nType=Application\n"
            "Categories=AudioVideo;Audio;HamRadio;\nStartupNotify=true\n")
    return nightshift_text(text, qss) if qss else text


def _split_exec(value: str) -> tuple[str, str]:
    """Exec-Wert -> (Programm wie geschrieben, Rest mit führendem Leerzeichen)."""
    value = value.strip()
    if value.startswith('"'):
        i = value.find('"', 1)
        while i > 0 and value[i - 1] == "\\":
            i = value.find('"', i + 1)
        if i > 0:
            return value[:i + 1], value[i + 1:]
    head, _sep, rest = value.partition(" ")
    return head, (" " + rest) if rest else ""


def _main_exec(text: str) -> str | None:
    section = None
    for ln in text.splitlines():
        st = ln.strip()
        if st.startswith("["):
            section = st
        elif section == "[Desktop Entry]" and st.startswith("Exec="):
            return st[5:]
    return None


def _exec_name(text: str) -> str | None:
    value = _main_exec(text)
    if not value:
        return None
    prog = _split_exec(value)[0]
    try:
        prog = shlex.split(prog)[0]
    except (ValueError, IndexError):
        pass
    return Path(prog).name


def starts(text: str, binary: str) -> bool:
    """Startet dieser Starter das Programm binary (gleicher Programmname)?"""
    return _exec_name(text) == Path(binary).name


def nightshift_text(text: str, qss: Path) -> str:
    """Starter-Text umstellen: Aussehen nach dem Programm einfügen, Kennzeichen setzen.
    Alles andere (Name, Übersetzungen, Symbol, Aktionen) bleibt."""
    out, section, done = [], None, False
    for ln in text.splitlines():
        st = ln.strip()
        if st.startswith("["):
            section = st
            out.append(ln)
            if st == "[Desktop Entry]":
                out.append(MARK)
            continue
        if st == MARK:
            continue
        if section == "[Desktop Entry]" and st.startswith("Exec=") and not done:
            prog, rest = _split_exec(st[5:])
            ln = f"Exec={prog} -style Fusion -stylesheet {_quote(str(qss))}{rest}"
            done = True
        out.append(ln)
    return "\n".join(out) + "\n"


def plain_text(text: str) -> str:
    """Umgekehrt (falls die Sicherung fehlt): Kennzeichen und Aussehen wieder herausnehmen."""
    out = []
    for ln in text.splitlines():
        if ln.strip() == MARK:
            continue
        if ln.strip().startswith("Exec="):
            ln = re.sub(r" -style Fusion -stylesheet (\"[^\"]*\"|\S+)", "", ln, count=1)
        out.append(ln)
    return "\n".join(out) + "\n"


def _data_dirs() -> list[Path]:
    raw = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [Path(d) for d in raw.split(":") if d]


def system_entry(binary: str, data_dirs: list[Path] | None = None) -> Path | None:
    """Starter des installierten Pakets, der dieses Programm startet (z. B. /usr/share/
    applications/ws.desktop). Bevorzugt ws.desktop/wsjtx.desktop, sonst der erste passende."""
    found = []
    for d in (data_dirs if data_dirs is not None else _data_dirs()):
        apps = d / "applications"
        if not apps.is_dir():
            continue
        for p in sorted(apps.glob("*.desktop")):
            try:
                if starts(p.read_text(encoding="utf-8", errors="replace"), binary):
                    found.append(p)
            except OSError:
                continue
    for p in found:
        if p.stem == Path(binary).name:
            return p
    return found[0] if found else None


def _write_starter(p: Path, text: str) -> None:
    if p.is_symlink():
        p.unlink()
    tmp = p.with_name("." + p.name + ".nightshift-tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o755)
    os.replace(tmp, p)


def _setup_starters(binary: str, qss: Path, home: str | None,
                    data_dirs: list[Path] | None) -> list[str]:
    lines = []
    bdir = backup_dir(home)
    bdir.mkdir(parents=True, exist_ok=True)
    # Startmenü: gleichnamiger eigener Eintrag verdeckt den des Pakets
    src = system_entry(binary, data_dirs)
    menu = _apps_dir(home) / (src.name if src else "ws.desktop")
    menu.parent.mkdir(parents=True, exist_ok=True)
    keep = bdir / ("menu-" + menu.name)
    if menu.is_file() and not menu.is_symlink() and not _marked(menu):
        if not keep.exists():                          # eigener Eintrag des Nutzers: sichern
            shutil.copy2(menu, keep)
        base = menu.read_text(encoding="utf-8", errors="replace")
    elif keep.is_file():
        base = keep.read_text(encoding="utf-8", errors="replace")
    elif src:
        base = src.read_text(encoding="utf-8", errors="replace")
    else:
        base = starter_text(binary)
    _write_starter(menu, nightshift_text(base, qss))
    lines.append(tr("Startmenü: „WS“ startet jetzt im Nightshift-Design"))
    # Schreibtisch: vorhandene WS-Symbole umstellen, keine neuen anlegen
    desk, n = desktop_dir(home), 0
    if desk.is_dir():
        for p in sorted(desk.glob("*.desktop")):
            if p.name == STARTER_NAME:
                continue
            link, copy = bdir / ("desk-" + p.name + ".link"), bdir / ("desk-" + p.name)
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _marked(p):
                if copy.is_file():
                    text = copy.read_text(encoding="utf-8", errors="replace")
                elif not link.is_file():
                    text = plain_text(text)
                else:
                    text = Path(link.read_text(encoding="utf-8").strip()).read_text(
                        encoding="utf-8", errors="replace")
            elif not starts(text, binary):
                continue
            elif p.is_symlink():
                link.write_text(os.readlink(p) + "\n", encoding="utf-8")
            else:
                shutil.copy2(p, copy)
            _write_starter(p, nightshift_text(text, qss))
            n += 1
    if n:
        lines.append(tr("Schreibtisch: {n} WS-Symbol(e) umgestellt", n=n))
    else:
        lines.append(tr("Schreibtisch: kein WS-Symbol vorhanden – dort wurde nichts angelegt"))
    # alter eigener Starter „WS Nightshift“ (bis 0.10.47.1)
    old = [p for p in starter_paths(home) if p.exists() or p.is_symlink()]
    for p in old:
        p.unlink()
    if old:
        lines.append(tr("Altes Extra-Symbol „WS Nightshift“ entfernt"))
    return lines


def _restore_starters(home: str | None) -> None:
    bdir = backup_dir(home)
    apps = _apps_dir(home)
    for p in _ours(home):
        prefix = "menu-" if p.parent == apps else "desk-"
        copy, link = bdir / (prefix + p.name), bdir / (prefix + p.name + ".link")
        if link.is_file():
            p.unlink()
            p.symlink_to(link.read_text(encoding="utf-8").strip())
            link.unlink()
        elif copy.is_file():
            os.replace(copy, p)
        elif prefix == "menu-":
            p.unlink()                                 # Paket-Eintrag gilt wieder
        else:
            _write_starter(p, plain_text(p.read_text(encoding="utf-8", errors="replace")))


def black_text(data: bytes) -> tuple[bytes, int]:
    """Farbeinstellung der Dekodierzeilen (Qt-Datenstrom): bei jeder Zeilenart mit Hintergrund,
    aber ohne eigene Schriftfarbe, die Schrift auf Schwarz setzen. -> (neue Daten, Anzahl).
    Unbekanntes Format -> ValueError (dann wird nichts geändert)."""
    if len(data) < 4:
        raise ValueError("zu kurz")
    out, pos, changed = bytearray(data[:4]), 4, 0
    for _ in range(struct.unpack(">I", data[:4])[0]):
        if pos + 4 > len(data):
            raise ValueError("abgeschnitten")
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        end = pos + 4 + n + 1 + 2 * _BRUSH                 # Name, an/aus, Schrift, Hintergrund
        if end > len(data):
            raise ValueError("abgeschnitten")
        head, fg, bg = data[pos:pos + 5 + n], data[pos + 5 + n:end - _BRUSH], data[end - _BRUSH:end]
        if fg[0] == 0 and bg[0] != 0:
            fg = _BLACK + fg[12:]
            changed += 1
        out += head + fg + bg
        pos = end
    if pos != len(data):
        raise ValueError("unerwartete Länge")
    return bytes(out), changed


def patch_ini(path: Path, now: float | None = None) -> tuple[int, Path | None]:
    """Schwarze Schrift in WS.ini eintragen -> (Anzahl Zeilenarten, Sicherungskopie oder None).
    Ohne Datei, ohne Eintrag oder schon erledigt: (0, None). Unbekanntes Format: ValueError."""
    if not path.is_file():
        return 0, None
    raw = path.read_bytes().decode("utf-8", "surrogateescape")
    m = re.search(rf'^{INI_KEY}="([^"]+)"\r?$', raw, re.M)
    if not m:
        return 0, None
    new, n = black_text(base64.b64decode(m.group(1)))
    if not n:
        return 0, None
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    backup = path.with_name(f"{path.name}.nightshift-{stamp}.bak")
    shutil.copy2(path, backup)
    text = raw[:m.start(1)] + base64.b64encode(new).decode() + raw[m.end(1):]
    tmp = path.with_name(path.name + ".nightshift-tmp")
    tmp.write_bytes(text.encode("utf-8", "surrogateescape"))
    os.replace(tmp, path)
    return n, backup


def install(home: str | None = None, find=extapps.find, running=extapps.running,
            now: float | None = None, data_dirs: list[Path] | None = None) -> Result:
    """Alles einrichten (beliebig oft aufrufbar)."""
    binary = find(KEY)
    if not binary:
        return Result(False, [tr("WS ist nicht installiert.")])
    if binary.startswith(extapps.FLATPAK):
        return Result(False, [tr("WS als Flatpak wird dafür nicht unterstützt.")])
    if running(KEY):
        return Result(False, [tr("WS läuft gerade – bitte WS zuerst schließen, sonst überschreibt "
                                 "es die Einstellungen beim Beenden wieder.")])
    res = Result(True)
    qss = qss_path(home)
    qss.parent.mkdir(parents=True, exist_ok=True)
    qss.write_text(QSS + "\n", encoding="utf-8")
    res.lines.append(tr("Aussehen angelegt: {p}", p=str(qss)))
    res.lines += _setup_starters(binary, qss, home, data_dirs)
    ini = extapps.ini_path(KEY, home, binary)
    try:
        n, res.backup = patch_ini(ini, now)
    except ValueError:
        res.lines.append(tr("Farben der Dekodierzeilen in {f} nicht erkannt – dort nichts "
                            "geändert.", f=ini.name))
        return res
    if n:
        res.lines.append(tr("{n} Arten von Dekodierzeilen bekommen schwarze Schrift (Sicherung: "
                            "{b})", n=n, b=res.backup.name))
    elif ini.is_file():
        res.lines.append(tr("Dekodierzeilen haben schon schwarze Schrift."))
    else:
        res.lines.append(tr("{f} gibt es noch nicht – WS einmal normal starten und beenden, dann "
                            "nochmal einrichten.", f=ini.name))
    return res


def remove(home: str | None = None) -> Result:
    """Nightshift-Design wieder ausschalten: Aussehen löschen, die WS-Starter in Startmenü und auf
    dem Schreibtisch zurückstellen (Schreibtisch-Verweis wie vorher), alten Extra-Starter löschen.
    Die schwarze Schrift in WS.ini bleibt (stört im normalen WS nicht); zurück geht es mit der
    Sicherungskopie."""
    _restore_starters(home)
    for p in [qss_path(home)] + starter_paths(home):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    return Result(True, [tr("Nightshift-Design entfernt: WS startet wieder ganz normal. Die "
                            "schwarze Schrift der Dekodierzeilen bleibt – sie stört im normalen "
                            "WS nicht.")])
