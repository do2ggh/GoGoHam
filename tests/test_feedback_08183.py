"""0.8.18.3: Kontakt-Knopf, Fehlerbericht, Protokolldatei, Uhrzeit-Prüfung."""

import struct
import time

from gogoham import CONTACT_EMAIL, applog, bugreport, clockcheck as ck, is_prerelease


def test_prerelease_only_before_1_0():
    assert is_prerelease("0.8.18.3") and is_prerelease("0.9")
    assert not is_prerelease("1.0") and not is_prerelease("1.2.3")


def test_mailto_and_subject():
    url = bugreport.mailto(bugreport.subject("Fehlerbericht", "DO2GGH"), "Zeile 1\nZeile 2")
    assert url.startswith(f"mailto:{CONTACT_EMAIL}?subject=GoGoHam%20")
    assert "DO2GGH" in url and "&body=Zeile%201%0AZeile%202" in url
    assert bugreport.subject("", "").startswith("GoGoHam ")


def test_report_hides_secrets_and_qsos(tmp_path):
    cfg = {"qrz_password": "geheim1", "hamqth_password": "geheim2", "livescore_password": "geheim3",
           "rig_model": 3073, "cluster_call": "DO2GGH",
           "rig_profiles": [{"name": "IC-7300", "model": 3073, "password": "geheim4",
                             "nested": {"api_key": "geheim5"}}],
           "last_log": str(tmp_path / "mein.log")}
    r = bugreport.build(cfg, log_lines=["2026-11-06 INFO CAT: verbunden"], ports=[])
    assert "geheim" not in r and "rig_model = 3073" in r and "IC-7300" in r
    assert "mein.log" not in r                                   # kein Logbuch-Pfad
    assert "CAT: verbunden" in r and CONTACT_EMAIL in r
    assert bugreport.clean({"password": ""}) == {"password": ""}  # leer bleibt leer


def test_os_name(tmp_path):
    f = tmp_path / "os-release"
    f.write_text('NAME="Fedora Linux"\nPRETTY_NAME="Fedora Linux 43 (Workstation Edition)"\n')
    assert bugreport.os_name(str(f)) == "Fedora Linux 43 (Workstation Edition)"


def test_log_file_messages_and_crash(tmp_path, monkeypatch):
    import sys
    import threading
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)       # wird nach dem Test zurückgesetzt
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(applog, "_last", "")
    path = tmp_path / "state" / "gogoham.log"
    assert applog.setup(path) == path
    applog.message("Funkgerät getrennt", "warn")
    applog.message("Funkgerät getrennt", "warn")                   # gleiche Meldung nur einmal
    applog.message("")
    try:
        raise ValueError("Testabsturz")
    except ValueError:
        info = sys.exc_info()
    import io
    monkeypatch.setattr(sys, "stderr", io.StringIO())             # Standard-Ausgabe des Absturzes
    sys.excepthook(*info)
    for h in applog.LOG.handlers:
        h.flush()
    lines = applog.tail(50, path)
    assert sum("Funkgerät getrennt" in ln for ln in lines) == 1
    assert any("WARNING" in ln for ln in lines) and any("Testabsturz" in ln for ln in lines)
    for h in list(applog.LOG.handlers):
        applog.LOG.removeHandler(h)
        h.close()


def test_tail_reads_older_file_first(tmp_path):
    p = tmp_path / "g.log"
    (tmp_path / "g.log.1").write_text("alt1\nalt2\n")
    p.write_text("neu1\n")
    assert applog.tail(2, p) == ["alt2", "neu1"]
    assert applog.tail(5, p) == ["alt1", "alt2", "neu1"]


class FakeSock:
    """Zeitserver, dessen Uhr `skew` Sekunden vor der PC-Uhr liegt."""

    def __init__(self, skew, stratum=2):
        self.skew, self.stratum = skew, stratum

    def settimeout(self, t):
        pass

    def sendto(self, data, addr):
        assert addr[1] == 123 and len(data) == 48 and data[0] == 0x23

    def recvfrom(self, n):
        t = time.time() + self.skew + ck._NTP_EPOCH
        ts = struct.pack("!II", int(t), int((t % 1) * 2 ** 32))
        return bytes([0x24, self.stratum]) + bytes(30) + ts + ts, ("x", 123)

    def close(self):
        pass


def test_offset_sign_and_threshold():
    off = ck.offset(sock_factory=lambda: FakeSock(30))
    assert abs(off - 30) < 0.5 and ck.is_wrong(off)               # Server 30 s weiter = PC geht nach
    assert "nach" in ck.describe(off)
    off = ck.offset(sock_factory=lambda: FakeSock(-0.5))
    assert not ck.is_wrong(off)
    assert "vor" in ck.describe(-300) and "Minuten" in ck.describe(-300)
    assert ck.offset(sock_factory=lambda: FakeSock(5, stratum=0)) is None
    assert not ck.is_wrong(None)


def test_offset_without_network():
    class Dead(FakeSock):
        def sendto(self, data, addr):
            raise OSError("Netz ist nicht erreichbar")
    assert ck.offset(sock_factory=lambda: Dead(0)) is None


def test_sync_commands_per_system():
    def which_for(*have):
        return lambda name: f"/usr/bin/{name}" if name in have else None
    # Fedora: chrony
    cmd = ck.sync_command(which_for("timedatectl", "chronyc", "pkexec"))
    assert cmd[:3] == ["pkexec", "/bin/sh", "-c"]
    assert "timedatectl set-ntp true" in cmd[3] and "chronyc -a makestep" in cmd[3]
    # Arch/Debian/Ubuntu: systemd-timesyncd
    cmd = ck.sync_command(which_for("timedatectl", "pkexec"))
    assert cmd[3] == "timedatectl set-ntp true; systemctl restart systemd-timesyncd"
    # ohne pkexec: nur Befehl zum Kopieren
    assert ck.sync_command(which_for("timedatectl")) is None
    assert ck.manual_commands(which_for("timedatectl")).startswith("sudo sh -c 'timedatectl")
    # gar kein Zeitdienst
    assert ck.sync_command(which_for("pkexec")) is None and ck.manual_commands(which_for()) == ""
