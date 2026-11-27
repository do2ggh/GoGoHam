"""Live-Stick 0.10.47.6: nach einem neuen Abbild den Systemteil im Datenteil aufräumen
(stick/config/…/init-premount/gogoham-reset, Funktion „aufraeumen“)."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parent.parent / "stick/config/includes.chroot_before_packages"
          "/etc/initramfs-tools/scripts/init-premount/gogoham-reset")
pytestmark = pytest.mark.skipif(not SCRIPT.is_file() or not shutil.which("sh"),
                                reason="Stick-Ordner fehlt (Quelltext-Archiv)")


def put(p: Path, text: str = "x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def used_stick(d: Path) -> Path:
    rw = d / "rw"
    home = rw / "home/gogoham"
    put(home / "GoGoHam/cqww.ggh", "log")
    put(home / ".config/gogoham/config.json", "{}")
    put(home / "Desktop/gogoham.desktop", "[Desktop Entry]\nExec=gogoham\n")
    put(home / "Desktop/gogoham-wsjtx_improved.desktop", "[Desktop Entry]\nExec=wsjtx\n")
    put(home / "Desktop/gogoham-fldigi.desktop",
        "[Desktop Entry]\nName=fldigi\nExec=flatpak run com.w1hkj.fldigi\nIcon=x\n")
    put(rw / "etc/NetworkManager/system-connections/Heim.nmconnection", "wlan")
    put(rw / "etc/timezone", "Europe/Berlin\n")
    os.symlink("/usr/share/zoneinfo/Europe/Berlin", rw / "etc/localtime")
    put(rw / "etc/udev/rules.d/99-microham-dxp.rules")
    put(rw / "var/lib/bluetooth/AA/info")
    put(rw / "var/lib/flatpak/app/com.w1hkj.fldigi/current")
    put(rw / "var/lib/dpkg/status", "Package: wsjtx-improved\n")   # alte Paketliste
    put(rw / "etc/sddm.conf", "Session=plasma.desktop\n")
    put(rw / "usr/bin/wsjtx")
    put(rw / "etc/NetworkManager/NetworkManager.conf")             # nicht die Zugänge
    return rw


def run(d: Path):
    sh = os.environ.get("GOGOHAM_TEST_SH", "sh").split()     # z. B. „busybox sh“ wie im Startsystem
    subprocess.run([*sh, str(SCRIPT), "aufraeumen", str(d)], check=True)


def check_clean(rw: Path):
    home = rw / "home/gogoham"
    assert (home / "GoGoHam/cqww.ggh").read_text() == "log"
    assert (home / ".config/gogoham/config.json").is_file()
    assert (home / "Desktop/gogoham.desktop").is_file()
    assert (home / "Desktop/gogoham-fldigi.desktop").is_file()        # Flatpak bleibt
    assert not (home / "Desktop/gogoham-wsjtx_improved.desktop").exists()
    assert (rw / "etc/NetworkManager/system-connections/Heim.nmconnection").read_text() == "wlan"
    assert (rw / "etc/timezone").is_file() and (rw / "etc/localtime").is_symlink()
    assert (rw / "etc/udev/rules.d/99-microham-dxp.rules").is_file()
    assert (rw / "var/lib/bluetooth/AA/info").is_file()
    assert (rw / "var/lib/flatpak/app/com.w1hkj.fldigi/current").is_file()
    for gone in ("var/lib/dpkg", "etc/sddm.conf", "usr", "etc/NetworkManager/NetworkManager.conf"):
        assert not (rw / gone).exists(), gone
    assert not (rw.parent / "rw.neu").exists()


def test_aufraeumen(tmp_path):
    rw = used_stick(tmp_path)
    run(tmp_path)
    check_clean(rw)
    marker = rw / "home/gogoham/.config/gogoham/stick-aktualisiert"
    assert marker.read_text().split() == ["wsjtx_improved"]
    run(tmp_path)                                    # noch einmal: nichts geht verloren
    check_clean(rw)
    assert marker.read_text().split() == ["wsjtx_improved"]


def test_stromausfall_mittendrin(tmp_path):
    """Abbruch, nachdem der Benutzerordner schon umgezogen war: der nächste Start macht weiter."""
    rw = used_stick(tmp_path)
    neu = tmp_path / "rw.neu"
    neu.mkdir()
    shutil.move(str(rw / "home"), str(neu / "home"))
    run(tmp_path)
    check_clean(rw)
    # Abbruch nach dem Löschen von rw, vor dem Umbenennen
    shutil.move(str(rw), str(neu))
    run(tmp_path)
    check_clean(rw)


def test_frischer_stick(tmp_path):
    run(tmp_path)                                    # kein rw: nichts tun, kein Fehler
    assert list(tmp_path.iterdir()) == []
    (tmp_path / "rw").mkdir()                        # leer, ohne Benutzerordner: keine Marke
    run(tmp_path)
    assert list((tmp_path / "rw").iterdir()) == []
