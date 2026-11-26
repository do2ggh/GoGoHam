"""0.10.41: Wohin mit dem Log? – Block „submit“ in den Regel-Dateien."""

import json
from datetime import datetime
from pathlib import Path

from gogoham import rulefiles
from gogoham import submit as sm

RULES = Path(__file__).parent.parent / "gogoham" / "rules"


def test_validate_good_and_bad():
    assert sm.validate({"email": "log@example.org", "subject": "{call}",
                        "deadline": {"days": 5}, "checked": "2026-11"}) == []
    assert sm.validate({"upload_url": "https://x.org/up", "deadline": {"day_of_month": 15}}) == []
    assert sm.validate({"email": {"CW": "cw@x.org", "PH": "ph@x.org"}}) == []
    assert sm.validate({"note": {"de": "per Post", "en": "by mail"}}) == []
    assert sm.validate({"email": "kein-mail"})
    assert sm.validate({"email": {"XX": "a@b.org"}})
    assert sm.validate({"upload_url": "ftp://x"})
    assert sm.validate({"subject": "{rufzeichen}", "email": "a@b.org"})
    assert sm.validate({"deadline": {"days": 0}, "email": "a@b.org"})
    assert sm.validate({"deadline": {"weeks": 1}, "email": "a@b.org"})
    assert sm.validate({"checked": "2026-11"})                 # weder Mail noch Upload
    assert sm.validate({"email": "a@b.org", "foo": 1})
    assert sm.validate("x")


def test_deadline():
    end = datetime(2026, 11, 29, 12, 0)
    assert sm.deadline({"deadline": {"days": 5}}, end) == datetime(2026, 12, 4, 12, 0)
    assert sm.deadline({"deadline": {"hours": 72}}, end) == datetime(2026, 12, 2, 12, 0)
    assert sm.deadline({"deadline": {"day_of_month": 15}}, end) == datetime(2026, 12, 15, 23, 59, 59)
    assert sm.deadline({"deadline": {"day_of_month": 31, "months": 3}}, end) == \
        datetime(2027, 2, 28, 23, 59, 59)
    assert sm.deadline({"deadline": {"month": 5, "day": 13}}, datetime(2027, 2, 27)) == \
        datetime(2027, 5, 13, 23, 59, 59)
    assert sm.deadline({"deadline": {"month": 1, "day": 10}}, end) == datetime(2027, 1, 10, 23, 59, 59)
    assert sm.validate({"deadline": {"month": 2, "day": 30}, "email": "a@b.org"})
    lz_end = datetime(2026, 11, 22, 12, 0)                        # LZ DX: 15 Tage, 00:00 UTC
    assert sm.deadline({"deadline": {"days": 15, "time": "00:00"}}, lz_end) == datetime(2026, 12, 7, 0, 0)
    assert sm.validate({"deadline": {"days": 5, "time": "24:00"}, "email": "a@b.org"})
    assert sm.deadline({"deadline": {"day_of_month": 31, "months": 0}}, datetime(2026, 2, 21)) == \
        datetime(2026, 2, 28, 23, 59, 59)
    assert sm.deadline({"deadline": {"month": 1, "day": 14, "time": "23:00"}}, datetime(2026, 1, 1, 12)) == \
        datetime(2026, 1, 14, 23, 0)
    assert sm.deadline({}, end) is None and sm.deadline({"deadline": {"days": 1}}, None) is None


def test_emails_subject_mailto():
    sub = {"email": {"CW": "cw@x.org", "PH": "ph@x.org"}, "subject": "{call} {contest}"}
    assert sm.emails(sub, {"CW"}) == ["cw@x.org"]
    assert sm.emails(sub, {"CW", "PH"}) == ["cw@x.org", "ph@x.org"]
    assert sm.emails(sub, {"DG"}) == ["cw@x.org", "ph@x.org"]     # keine passende: alle zeigen
    assert sm.subject(sub, "DO2GGH", "LZ DX") == "DO2GGH LZ DX"
    assert sm.subject({}, "DO2GGH", "LZ DX") == "LZ DX – DO2GGH"
    assert sm.mailto(["a@b.org"], "DO2GGH LZ") == "mailto:a@b.org?subject=DO2GGH%20LZ"
    assert sm.mailto(["a@b.org"], "X", "c@d.org") == "mailto:a@b.org?subject=X&cc=c@d.org"
    assert sm.validate({"email": "a@b.org", "cc": "nix"})


def test_show_in_folder_command(tmp_path):
    f = tmp_path / "log.cbr"
    f.write_text("x")
    seen = []

    class R:
        returncode = 0

    ok = sm.show_in_folder([str(f)], run=lambda cmd, **kw: seen.append(cmd) or R(),
                           which=lambda n: "/usr/bin/" + n if n == "gdbus" else None)
    assert ok and "org.freedesktop.FileManager1.ShowItems" in seen[0]
    assert f"['{f.as_uri()}']" in seen[0]
    assert not sm.show_in_folder([str(f)], which=lambda n: None)


def test_all_rule_files_valid():
    assert rulefiles.FORMAT_VERSION >= 25
    for p in sorted(RULES.glob("*.json")):
        d = json.loads(p.read_text())
        assert rulefiles.validate(d) == [], p.name
        if "submit" in d:
            assert d["submit"].get("checked"), p.name


def test_dialog_actions(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import fake_qt
    fake_qt.install()
    for m in [m for m in sys.modules if m.startswith("gogoham.gui")]:
        del sys.modules[m]
    from gogoham.contests import CONTESTS
    from gogoham.contests.base import Qso
    from gogoham.gui import submit_dialog as sd
    f = tmp_path / "lz.cbr"
    f.write_text("x")
    shown, opened = [], []
    monkeypatch.setattr(sd.sm, "show_in_folder", lambda paths: shown.append(paths) or True)
    qs = [Qso(time="2026-11-21 14:00:00", call="LZ1A", band="40", mode="CW")]
    d = sd.SubmitDialog(CONTESTS["lzdx"], [str(f)], "DO2GGH", qs, now=datetime(2026, 11, 23))
    d.open_url = lambda u: opened.append(u) or True
    d.send_mail = lambda u: opened.append(u) or True
    assert "07.12.2026 00:00" in d.text.text() and "lzdxc@bfra.bg" in d.text.text()
    d.open_mail()
    assert shown == [[str(f)]] and opened == ["mailto:lzdxc@bfra.bg?subject=LZ%20DX%20Contest%20%E2%80%93%20DO2GGH"]
    d.open_link("http://bfra.bg:8080/WebEditor/")             # Upload: Ordner + Seite
    assert len(shown) == 2 and opened[-1] == "http://bfra.bg:8080/WebEditor/"
    d.open_link("mailto:lzdxc@bfra.bg")                       # Klick auf die Adresse = Knopf
    assert len(shown) == 3 and opened[-1].startswith("mailto:")
    # Ohne gesicherten Weg: Hinweis auf die Ausschreibung, kein Mail-/Upload-Knopf
    r = sd.SubmitDialog(CONTESTS["volta-rtty"], [str(f)], "DO2GGH", [])
    assert r.btn_mail is None and r.btn_upload is None and "contestvolta.it" in r.text.text()
    # Ordner-Notweg: Dateimanager ohne Markier-Funktion -> Ordner öffnen
    monkeypatch.setattr(sd.sm, "show_in_folder", lambda paths: False)
    r.open_url = lambda u: opened.append(u) or True
    r.show_folder()
    assert opened[-1].endswith(str(tmp_path))


def test_old_log_gets_current_submit_route():
    """Ein Log von vor 0.10.41 hat Regeln ohne „submit“ – der Einsendeweg kommt trotzdem."""
    from gogoham.contests import CONTESTS
    from gogoham.contests.rulebased import make_contest_class
    old = dict(CONTESTS["lzdx"].rules)
    old.pop("submit")
    cls = make_contest_class(old)
    assert cls is not CONTESTS["lzdx"] and sm.block(cls)["email"] == "lzdxc@bfra.bg"


def test_mail_opens_via_xdg_open():
    """0.10.42.1: mailto unter Linux über xdg-open (KDE scheiterte mit Thunderbird aus Flatpak)."""
    from gogoham import mailopen
    seen, fb = [], []

    class P:
        def wait(self):
            return 0

    url = "mailto:lzdxc@bfra.bg?subject=LZ%20DX%20Contest%20%E2%80%93%20DO2GGH"
    ok = mailopen.open_mail(url, fallback=lambda u: fb.append(u) or True,
                            run=lambda cmd, **kw: seen.append((cmd, kw)) or P(),
                            which=lambda n: "/usr/bin/xdg-open", platform="linux")
    assert ok and seen[0][0] == ["/usr/bin/xdg-open", url] and seen[0][1]["start_new_session"]
    assert not fb
    # ohne xdg-open (oder nicht Linux): bisheriger Weg über Qt
    assert mailopen.open_mail(url, fallback=lambda u: fb.append(u) or True,
                              which=lambda n: None, platform="linux") and fb == [url]
    assert mailopen.open_mail(url, fallback=lambda u: fb.append(u) or True,
                              which=lambda n: "/x", platform="win32") and len(fb) == 2

    def boom(cmd, **kw):
        raise OSError("weg")
    assert mailopen.open_mail(url, fallback=lambda u: fb.append(u) or False, run=boom,
                              which=lambda n: "/usr/bin/xdg-open", platform="linux") is False
