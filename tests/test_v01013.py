"""0.10.13: Original-WSJT-X raus, WS direkt von DG2YCB (neueste Version, Prüfsumme)."""
import hashlib
import io

import pytest

from gogoham import extapps, wsdl

FEED = """<rss><channel>
<item><link>https://sourceforge.net/projects/wsjt-x-improved/files/WS_v3.2.1/Linux/ws_3.2.1_AL_261010_boost1.74_amd64.deb/download</link>
<media:content><media:hash algo="md5">f5aeeb83485751f75a1d334c2764c22c</media:hash></media:content></item>
<item><link>https://sourceforge.net/projects/wsjt-x-improved/files/WS_v3.2.1/Linux/ws-3.2.1_261010.x86_64.rpm/download</link>
<media:content><media:hash algo="md5">ca2da264094ebfb1b3a83add4530f430</media:hash></media:content></item>
<item><link>https://sourceforge.net/projects/wsjt-x-improved/files/WS_v3.2.1/Linux/ws_3.2.1_widescreen_261010_amd64.deb/download</link>
<media:content><media:hash algo="md5">56b243786f59c3b424c9aab677747121</media:hash></media:content></item>
<item><link>https://sourceforge.net/projects/wsjt-x-improved/files/WS_v3.2.1/Linux/ws_3.2.1_261010_amd64.deb/download</link>
<media:content><media:hash algo="md5">46df358773759e32834f0bfd0054f394</media:hash></media:content></item>
<item><link>https://sourceforge.net/projects/wsjt-x-improved/files/WS_v3.2.0/Linux/ws_3.2.0_260924_amd64.deb/download</link>
<media:content><media:hash algo="md5">959ecd243ff91b13a617b6ed3af046a7</media:hash></media:content></item>
<item><link>https://sourceforge.net/projects/wsjt-x-improved/files/WSJT-X_v3.2.0/Linux/wsjtx_3.2.0_improved_PLUS_260908_amd64.deb/download</link>
<media:content><media:hash algo="md5">f97fd077af8db995f62ce9321ed45128</media:hash></media:content></item>
</channel></rss>"""


def test_parse_feed_newest_plain_package():
    best = wsdl.parse_feed(FEED)
    assert best["deb"].version == "3.2.1" and best["deb"].build == "261010"
    assert best["deb"].url.endswith("/ws_3.2.1_261010_amd64.deb/download")   # nicht AL/widescreen
    assert best["deb"].md5 == "46df358773759e32834f0bfd0054f394"
    assert best["deb"].filename == "ws_3.2.1_261010_amd64.deb"
    assert best["rpm"].filename == "ws-3.2.1_261010.x86_64.rpm"
    assert wsdl.parse_feed("<rss></rss>") == {}
    assert wsdl.latest("deb", fetch=lambda: FEED).version == "3.2.1"
    assert wsdl.latest("deb", fetch=lambda: (_ for _ in ()).throw(OSError("offline"))) is None


class _Resp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_checks_md5(tmp_path):
    data = b"x" * 600000
    good = wsdl.Package("3.2.1", "261010", "https://example/x", hashlib.md5(data).hexdigest(),
                        "deb")
    seen = []
    p = wsdl.download(good, tmp_path, lambda d, t: seen.append((d, t)),
                      opener=lambda req, timeout: _Resp(data))
    assert p.read_bytes() == data and seen[-1] == (600000, 600000)
    bad = wsdl.Package("3.2.1", "261011", "https://example/x", "0" * 32, "deb")
    with pytest.raises(ValueError):
        wsdl.download(bad, tmp_path, opener=lambda req, timeout: _Resp(data))
    assert not list(tmp_path.glob("*261011*"))                     # nichts Halbes liegen lassen


def test_install_routes():
    assert "apt-get install -y '/tmp/a b.deb'" in wsdl.install_shell(wsdl.Path("/tmp/a b.deb"),
                                                                      "apt-get")
    assert wsdl.install_shell(wsdl.Path("/x.rpm"), "dnf") == "dnf install -y '/x.rpm'"
    assert "--allow-unsigned-rpm" in wsdl.install_shell(wsdl.Path("/x.rpm"), "zypper")
    assert wsdl.install_shell(wsdl.Path("/x"), "pacman") is None
    pkg = lambda k: wsdl.Package("3.2.1", "1", "u", "m", k)       # noqa: E731
    assert extapps.available_package("wsjtx_improved", "apt-get",
                                     latest=pkg) == extapps.WS_DEB
    assert extapps.available_package("wsjtx_improved", "dnf", latest=pkg) == extapps.WS_RPM
    assert extapps.available_package("wsjtx_improved", "apt-get", latest=lambda k: None) == ""
    which = {"paru": "/usr/bin/paru"}.get
    assert extapps.available_package("wsjtx_improved", "pacman", which=which) == "aur:paru"
    assert extapps.available_package("wsjtx_improved", "pacman", which=lambda n: None) == ""
    t = wsdl.terminal_command(["sh", "-c", "x"], {"konsole": "/usr/bin/konsole"}.get)
    assert t[:3] == ["konsole", "--nofork", "-e"]
    assert wsdl.terminal_command(["x"], lambda n: None) is None


def test_original_wsjtx_gone():
    keys = [a.key for a in extapps.APPS]
    assert keys == ["wsjtx_improved", "fldigi"]                 # 0.10.17: JTDX raus
    assert extapps.BY_KEY["wsjtx_improved"].name == "WS (DG2YCB)"
    from gogoham.gui.companions import ft8_choice
    # früher gewähltes Original-WSJT-X → jetzt das erste installierte FT8-Programm
    assert ft8_choice({"ft8_program": "wsjtx"}, find=lambda k: k == "wsjtx_improved") \
        == "wsjtx_improved"


# ---------------------------------------------------------------- 0.10.14: Flathub + Versionen
def test_flatpak_find_launch_and_install(tmp_path):
    from gogoham import fldigi
    which = {"fldigi": "/usr/bin/fldigi"}.get
    assert extapps.find("fldigi", which, flatpak=lambda i: True) == "flatpak:com.w1hkj.fldigi"
    assert extapps.find("fldigi", which, flatpak=lambda i: False) == "/usr/bin/fldigi"
    env = {"PULSE_SINK": "alsa_output.x", "PULSE_SOURCE": "alsa_input.x", "LC_NUMERIC": "C"}
    assert extapps.launch_cmd("flatpak:com.w1hkj.fldigi", env) == [
        "flatpak", "run", "--env=PULSE_SINK=alsa_output.x", "--env=PULSE_SOURCE=alsa_input.x",
        "--env=LC_NUMERIC=C", "com.w1hkj.fldigi"]
    assert extapps.launch_cmd("/usr/bin/ws") == ["/usr/bin/ws"]
    w = {"pkexec": "/x", "apt-get": "/x"}.get
    cmd = extapps.install_command("flathub:com.w1hkj.fldigi", which=w)[-1]
    assert cmd.startswith("apt-get update") and " flatpak && flatpak remote-add" in cmd
    assert cmd.endswith("flatpak install --or-update -y --noninteractive flathub com.w1hkj.fldigi")
    w2 = {"pkexec": "/x", "apt-get": "/x", "flatpak": "/x"}.get
    assert extapps.install_command("flathub:com.w1hkj.fldigi", which=w2)[-1].startswith(
        "flatpak remote-add --if-not-exists flathub")
    # Einstellungsordner des Flatpaks
    assert fldigi.config_dir(str(tmp_path), flatpak=True) == \
        tmp_path / ".var/app/com.w1hkj.fldigi/.fldigi"
    assert fldigi.config_dir(str(tmp_path)) == tmp_path / ".fldigi"


def test_versions():
    assert extapps.vtuple("3.2.1.261010-1") == (3, 2, 1, 261010)
    assert extapps.update_available("4.2.06-1+deb13u1", "4.2.13")
    assert not extapps.update_available("3.2.1", "3.2.1")
    assert not extapps.update_available("3.2.1.261010-1", "3.2.1.261010-1")
    assert extapps.update_available("3.2.1.261010-1", "3.2.2.261201-1")
    assert not extapps.update_available("", "3.2.1")
    run = lambda a, t=0: (0, "  ID: com.w1hkj.fldigi\n Version: 4.2.13\n")     # noqa: E731
    assert extapps.installed_version("fldigi", "flatpak:com.w1hkj.fldigi", run=run) == "4.2.13"
    assert extapps.newest_version("fldigi", "/usr/bin/fldigi", flathub=lambda i: "4.2.13") \
        == "4.2.13"
    assert extapps.newest_version("wsjtx_improved", "/usr/bin/ws", "pacman",
                                  aur=lambda n: "3.2.1.261010-1") == "3.2.1.261010-1"
    assert extapps.newest_version("wsjtx_improved", "/usr/bin/ws", "apt-get",
                                  latest=lambda k: wsdl.Package("3.2.2", "1", "u", "m", k)) \
        == "3.2.2"
    assert extapps.newest_version("fldigi", None, flathub=lambda i: 1 / 0) == ""   # offline


# ---------------------------------------------------------------- 0.10.15: QR-Code fürs Handy
def test_qr_event_and_alarm():
    from datetime import datetime
    from gogoham import contestcal as cc
    x = cc.Entry("cqww-cw", "CQ WW DX CW", datetime(2026, 11, 28), datetime(2026, 11, 30),
                 frozenset({"CW"}), "https://cqww.com/rules.htm")
    t = cc.qr_event(x)
    assert t.startswith("BEGIN:VEVENT") and t.endswith("END:VEVENT")
    assert "DTSTART:20261128T000000Z" in t and "TRIGGER:-PT60M" in t       # Voreinstellung 1 h
    assert "VALARM" not in cc.qr_event(x, 0)
    ics = cc.to_ics([x], datetime(2026, 11, 13), alarm=1440)
    assert "TRIGGER:-PT1440M" in ics and ics.count("BEGIN:VALARM") == 1
    assert "VALARM" not in cc.to_ics([x], datetime(2026, 11, 13))
    # mitgelieferte Bibliothek: Muster entsteht, Lizenz liegt bei
    from gogoham.gui.qr_dialog import qr_matrix
    m = qr_matrix(t)
    assert len(m) == len(m[0]) and len(m) >= 21
    from pathlib import Path
    import gogoham
    assert (Path(gogoham.__file__).parent / "_vendor/segno/LICENSE").is_file()


# ---------------------------------------------------------------- 0.10.16: ältere Debians
def test_old_debian():
    pkg = lambda k: wsdl.Package("3.2.1", "261010", "u", "m", k)              # noqa: E731
    apt = lambda a, t=0: (0, "Package: x\n") if a[-1] == "libboost-log1.83.0" \
        else (1, "")                                                          # noqa: E731
    # WS auf älterem Debian/Ubuntu (Boost 1.74): Variante „boost1.74“
    old = lambda a, t=0: (0, "Package: x\n") if a[-1] == "libboost-log1.74.0" \
        else (1, "")                                                          # noqa: E731
    assert wsdl.old_debian(old) and not wsdl.old_debian(apt)
    assert extapps.available_package("wsjtx_improved", "apt-get", old,
                                     latest=pkg) == "sf:deb-old"
    assert extapps.available_package("wsjtx_improved", "apt-get", apt, latest=pkg) == "sf:deb"
    ws = wsdl.parse_feed(FEED)
    assert ws["deb-old"].filename == "ws_3.2.1_AL_261010_boost1.74_amd64.deb"
    assert wsdl.install_shell(wsdl.Path("/x.deb"), "apt-get").endswith("'/x.deb'")
