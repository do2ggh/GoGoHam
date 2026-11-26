"""Startmenü-Bild (GRUB) und Plymouth-Startbild für den GoGoHam-Live-Stick erzeugen.
Aufruf:  QT_QPA_PLATFORM=offscreen python3 werkzeuge/bilder.py"""
import sys
from pathlib import Path
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter
from PySide6.QtSvg import QSvgRenderer

HIER = Path(__file__).resolve().parent.parent
LOGO = HIER.parent / "gogoham/assets/gogoham.svg"       # stick/ liegt im GoGoHam-Projekt
OBEN, UNTEN = QColor("#0f1726"), QColor("#1d2b45")
UNTERZEILE = "Contest-Logger · by DO2GGH"
app = QGuiApplication(sys.argv)
svg = QSvgRenderer(str(LOGO))


def text(p, rect, s, size, color, bold=False):
    f = QFont("Noto Sans")
    f.setPixelSize(size)
    f.setBold(bold)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, s)


# 1) Startmenü (GRUB): 800x600, Menü beginnt bei 52 % → Logo und Name in der oberen Hälfte
img = QImage(800, 600, QImage.Format.Format_RGB32)
p = QPainter(img)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
g = QLinearGradient(0, 0, 0, 600)
g.setColorAt(0, OBEN)
g.setColorAt(1, UNTEN)
p.fillRect(img.rect(), g)
svg.render(p, QRectF(340, 30, 120, 120))
text(p, QRectF(0, 160, 800, 60), "GoGoHam Live", 44, "#ffffff", bold=True)
text(p, QRectF(0, 222, 800, 30), UNTERZEILE, 20, "#aebbd0")
p.setPen(QColor("#3a4c6e"))
p.drawLine(200, 285, 600, 285)
p.end()
out = HIER / "config/bootloaders/grub-pc/splash.png"
img.save(str(out))
print(out)

# 2) Plymouth: Logo + Name, durchsichtig; Ladeanzeige setzt Plymouth darunter
w, h = 520, 300
img = QImage(w, h, QImage.Format.Format_ARGB32)
img.fill(Qt.GlobalColor.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
svg.render(p, QRectF((w - 160) / 2, 0, 160, 160))
text(p, QRectF(0, 175, w, 70), "GoGoHam", 56, "#ffffff", bold=True)
text(p, QRectF(0, 250, w, 36), UNTERZEILE, 22, "#aebbd0")
p.end()
out = HIER / "config/includes.chroot/usr/share/plymouth/themes/gogoham/watermark.png"
img.save(str(out))
print(out)

# 3) Vorschau beider Bilder zum Ansehen
prev = QImage(1920, 1080, QImage.Format.Format_RGB32)
prev.fill(OBEN)
p = QPainter(prev)
p.drawImage((1920 - w) // 2, int(1080 * 0.45 - h / 2), img)
p.end()
prev.save(str(HIER / "vm/plymouth-vorschau.png"))

# 4) Desktop-Hintergrund (Plasma): 2560x1440, Logo + Name leicht über der Mitte – die Mitte bleibt
#    für die Fenster frei genug, unten Platz für die Leiste
W, H = 2560, 1440
bg = QImage(W, H, QImage.Format.Format_RGB32)
p = QPainter(bg)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
g = QLinearGradient(0, 0, 0, H)
g.setColorAt(0, OBEN)
g.setColorAt(1, UNTEN)
p.fillRect(bg.rect(), g)
p.setOpacity(0.9)
svg.render(p, QRectF((W - 360) / 2, H * 0.30, 360, 360))
p.setOpacity(1.0)
text(p, QRectF(0, H * 0.30 + 390, W, 130), "GoGoHam", 110, "#ffffff", bold=True)
text(p, QRectF(0, H * 0.30 + 530, W, 60), UNTERZEILE, 42, "#aebbd0")
p.end()
wp = HIER / "config/includes.chroot/usr/share/wallpapers/GoGoHam"
(wp / "contents/images").mkdir(parents=True, exist_ok=True)
out = wp / "contents/images/2560x1440.png"
bg.save(str(out))
bg.scaled(400, 225, Qt.AspectRatioMode.KeepAspectRatio,
          Qt.TransformationMode.SmoothTransformation).save(str(wp / "contents/screenshot.png"))
(wp / "metadata.json").write_text(
    '{\n  "KPlugin": {\n    "Id": "GoGoHam",\n    "Name": "GoGoHam",\n'
    '    "Authors": [{"Name": "DO2GGH"}],\n    "License": "GPL-3.0-only"\n  }\n}\n')
print(out)
