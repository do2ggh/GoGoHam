"""Hilfe-Fenster: Handbuch mit Inhaltsverzeichnis und Suche."""

from __future__ import annotations

from ..i18n import language, tr

import re
from pathlib import Path

from dataclasses import dataclass

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QSplitter, QTextBrowser,
                               QVBoxLayout, QWidget)

HELP_DIR = Path(__file__).resolve().parent.parent / "help"
HANDBOOK = HELP_DIR / "handbuch.html"          # Deutsch (Original)


def handbook_path(lang: str | None = None) -> Path:
    """Handbuch in der eingestellten Sprache (help/handbook.<lang>.html). Das Handbuch gibt es
    nur auf Deutsch und Englisch (Nutzer 2026-11-14) – alle anderen Sprachen bekommen das
    englische (ab 0.10.27; vorher das deutsche)."""
    lang = lang or language()
    if lang != "de":
        for code in (lang, "en"):
            p = HELP_DIR / f"handbook.{code}.html"
            if p.is_file():
                return p
    return HANDBOOK


def chapters(html: str) -> list[tuple[str, str]]:
    """[(Anker, Überschrift), …] aus den <h2 id="…">-Überschriften."""
    out = []
    for m in re.finditer(r'<h2 id="([^"]+)">(.*?)</h2>', html, re.S):
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        out.append((m.group(1), title))
    return out


# ------------------------------------------------------------ Suche (0.10.19)
# Nutzer: „Auto-CQ“ gesucht – zuerst kam alles andere. Jetzt eine Trefferliste: passende
# Überschriften zuerst, Bindestrich/Leerzeichen und Groß/klein egal („autocq“ = „Auto-CQ“).
MAX_HITS = 300
_GAP = r"[\s\-\x{2010}\x{2011}\x{2013}/._]?"


def search_pattern(text: str) -> str:
    """Regulärer Ausdruck zur Eingabe: zwischen Buchstaben darf ein Trenner stehen oder nicht."""
    chars = [c for c in text.strip() if not c.isspace() and c not in "-‐‑–/._"]
    return _GAP.join(re.escape(c) for c in chars)


@dataclass
class Hit:
    pos: int                 # Anfang im Dokument
    end: int
    chapter: str             # Kapitelüberschrift
    snippet: str             # Textausschnitt um den Treffer
    level: int = 0           # Überschrift-Ebene (2 = Kapitel, 3 = Abschnitt, 0 = Text)

    @property
    def heading(self) -> bool:
        return self.level in (2, 3)


def find_hits(doc, text: str, limit: int = MAX_HITS) -> list[Hit]:
    """Alle Fundstellen – Überschriften zuerst (h2 vor h3), danach in Reihenfolge des Textes."""
    from PySide6.QtCore import QRegularExpression
    from PySide6.QtGui import QTextCursor
    pat = search_pattern(text)
    if not pat:
        return []
    rx = QRegularExpression(pat, QRegularExpression.PatternOption.CaseInsensitiveOption)
    hits: list[Hit] = []
    cur = QTextCursor(doc)
    chapter = ""
    while len(hits) < limit:
        cur = doc.find(rx, cur)
        if cur.isNull():
            break
        hits.append(Hit(cur.selectionStart(), cur.selectionEnd(), "", "",
                        cur.block().blockFormat().headingLevel()))
    # Kapitel zuordnen: Überschriften der Ebene 2 in Dokumentreihenfolge
    heads = []
    b = doc.begin()
    while b.isValid():
        if b.blockFormat().headingLevel() == 2:
            heads.append((b.position(), b.text().strip()))
        b = b.next()
    hi = 0
    for h in hits:
        while hi < len(heads) and heads[hi][0] <= h.pos:
            chapter = heads[hi][1]
            hi += 1
        block = doc.findBlock(h.pos)
        t, off = block.text(), h.pos - block.position()
        a, e = max(0, off - 40), min(len(t), off + (h.end - h.pos) + 60)
        if a:                                    # an Wortgrenzen schneiden
            sp = t.find(" ", a, off)
            a = sp + 1 if sp != -1 else a
        if e < len(t):
            sp = t.rfind(" ", h.pos - block.position() + (h.end - h.pos), e)
            e = sp if sp != -1 else e
        h.chapter = chapter
        h.snippet = ("…" if a else "") + t[a:e].replace("\u2028", " ").strip() + \
            ("…" if e < len(t) else "")
    order = {2: 0, 3: 1}
    return sorted(hits, key=lambda h: (order.get(h.level, 2), h.pos))


def _alive(w) -> bool:
    """Gibt es das Qt-Fenster noch (nicht schon von Qt gelöscht)?"""
    try:
        import shiboken6
        return shiboken6.isValid(w)
    except ImportError:
        return True


class HelpDialog(QDialog):
    _instance = None

    @classmethod
    def open_at(cls, parent=None, anchor: str = "") -> "HelpDialog":
        # Aus einem blockierenden Fenster heraus (z. B. Einstellungen, „?“-Knopf): eigenes
        # Handbuch-Fenster obenauf. Ein normales Fenster daneben würde mit blockiert und
        # ließe sich nicht schließen (gemeldet in 0.8.2).
        modal = QApplication.activeModalWidget()
        if modal is not None:
            dlg = cls(modal)
            if anchor:
                QTimer.singleShot(0, lambda: dlg.go(anchor))
            dlg.exec()
            return dlg
        if cls._instance is None or not _alive(cls._instance):
            cls._instance = cls(parent.window() if parent is not None else None)
        dlg = cls._instance
        if anchor:
            dlg.go(anchor)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("GoGoHam – Handbuch"))
        self.resize(1000, 720)
        book = handbook_path()
        html = book.read_text(encoding="utf-8") if book.is_file() else \
            tr("<p>Handbuch nicht gefunden.</p>")
        self.toc = QListWidget()
        for anchor, title in chapters(html):
            it = QListWidgetItem(title)
            it.setData(256, anchor)            # Qt.UserRole
            self.toc.addItem(it)
        self.toc.itemClicked.connect(lambda it: self.go(it.data(256)))
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setSearchPaths([str(HELP_DIR)])
        self.view.setHtml(html)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Suchen … (Enter = weiter)"))
        self.search.returnPressed.connect(self.find_next)
        btn = QPushButton(tr("Weiter suchen"))
        btn.clicked.connect(self.find_next)
        self.hits = QLabel("")
        self.results = QListWidget()
        self.results.setMaximumHeight(200)
        self.results.itemClicked.connect(lambda it: self._show_hit(self.results.row(it)))
        self.results.itemActivated.connect(lambda it: self._show_hit(self.results.row(it)))
        self.results.hide()
        self._hits: list[Hit] = []
        self._hit_i = -1
        self._typing = QTimer(self)
        self._typing.setSingleShot(True)
        self._typing.setInterval(300)
        self._typing.timeout.connect(self.update_hits)
        self.search.textChanged.connect(lambda _t: self._typing.start())
        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(btn)
        top.addWidget(self.hits)
        split = QSplitter()
        split.addWidget(self.toc)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addLayout(top)
        rl.addWidget(self.results)
        rl.addWidget(self.view)
        split.addWidget(right)
        split.setStretchFactor(1, 3)
        lay = QVBoxLayout(self)
        lay.addWidget(split)
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(close)
        lay.addLayout(bottom)

    def go(self, anchor: str) -> None:
        self.view.scrollToAnchor(anchor)

    def update_hits(self) -> None:
        """Trefferliste zur Eingabe neu aufbauen."""
        self._typing.stop()
        text = self.search.text().strip()
        self._hits = find_hits(self.view.document(), text) if len(text) >= 2 else []
        self._hit_i = -1
        self._query = text
        self.results.clear()
        for h in self._hits:
            mark = "§ " if h.heading else ""
            it = QListWidgetItem(f"{mark}{h.chapter}  –  {h.snippet}" if h.chapter
                                 else f"{mark}{h.snippet}")
            self.results.addItem(it)
        self.results.setVisible(bool(self._hits))
        if not text or len(text) < 2:
            self.hits.setText("")
        elif not self._hits:
            self.hits.setText(tr("nicht gefunden"))
        else:
            n = len(self._hits)
            self.hits.setText(tr("{n} Treffer", n=n) if n < MAX_HITS
                              else tr("über {n} Treffer", n=MAX_HITS))

    def _show_hit(self, i: int) -> None:
        if not 0 <= i < len(self._hits):
            return
        self._hit_i = i
        from PySide6.QtGui import QTextCursor
        h = self._hits[i]
        cur = QTextCursor(self.view.document())
        cur.setPosition(h.pos)
        cur.setPosition(h.end, QTextCursor.MoveMode.KeepAnchor)
        self.view.setTextCursor(cur)
        self.view.ensureCursorVisible()
        self.results.setCurrentRow(i)

    def find_next(self) -> None:
        """Enter / „Weiter suchen“: zum nächsten Treffer der Liste (beste zuerst)."""
        if self._typing.isActive() or self.search.text().strip() != getattr(self, "_query", None):
            self.update_hits()
        if not self._hits:
            return
        self._show_hit((self._hit_i + 1) % len(self._hits))
