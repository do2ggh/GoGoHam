"""0.10.47: install.sh-Installation per Knopf aktualisieren (selfupdate)."""
import io
import json
import os
import shutil
import tarfile
from pathlib import Path

import pytest

from gogoham import selfupdate, versioncheck
from gogoham.gui import self_update

ROOT = Path(__file__).resolve().parents[1]


def make_tarball(tmp: Path, version="9.9.9", inner_version=None, evil=False) -> bytes:
    """Archiv wie von GitHub: oberster Ordner GoGoHam-<v>/ mit gogoham/, data/, uninstall.sh."""
    src = tmp / f"GoGoHam-{version}"
    shutil.copytree(ROOT / "gogoham", src / "gogoham",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    init = src / "gogoham" / "__init__.py"
    text = init.read_text(encoding="utf-8")
    import re
    init.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{inner_version or version}"',
                           text), encoding="utf-8")
    shutil.copytree(ROOT / "data", src / "data")
    shutil.copy(ROOT / "uninstall.sh", src / "uninstall.sh")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        t.add(src, arcname=src.name)
        if evil:
            info = tarfile.TarInfo("../../boese.txt")
            data = b"x"
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    shutil.rmtree(src)
    return buf.getvalue()


class _Resp(io.BytesIO):
    def __init__(self, data, url="https://codeload.github.com/do2ggh/GoGoHam/tar.gz/refs/tags/v9.9.9"):
        super().__init__(data)
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def opener_for(data, **kw):
    seen = []

    def op(req):
        seen.append(req.full_url)
        return _Resp(data, **kw)
    op.seen = seen
    return op


@pytest.fixture(scope="module")
def tarball(tmp_path_factory):
    return make_tarball(tmp_path_factory.mktemp("tb"))


def test_prepare_downloads_checks_and_probes(tmp_path, tarball):
    op = opener_for(tarball)
    steps = []
    res = selfupdate.prepare("9.9.9", opener=op, root=tmp_path / "up", progress=steps.append)
    assert res.ok, res.message
    assert op.seen == ["https://github.com/do2ggh/GoGoHam/archive/refs/tags/v9.9.9.tar.gz"]
    job = selfupdate.pending(tmp_path / "up")
    assert job["action"] == "install" and job["version"] == "9.9.9"
    assert (Path(job["src"]) / "gogoham" / "__init__.py").is_file()
    assert not list((tmp_path / "up").glob("*.tar.gz"))          # Archiv wieder weg
    assert any("Prüfe" in s for s in steps)


def test_probe_failure_keeps_everything(tmp_path, tarball):
    class R:
        returncode, stdout, stderr = 1, "", "Traceback …\nModuleNotFoundError: No module named 'neu'"
    res = selfupdate.prepare("9.9.9", opener=opener_for(tarball), root=tmp_path / "up",
                             run=lambda *a, **k: R())
    assert not res.ok and "No module named 'neu'" in res.message
    assert selfupdate.pending(tmp_path / "up") is None and not (tmp_path / "up").exists()


def test_wrong_version_inside_is_refused(tmp_path):
    data = make_tarball(tmp_path, "9.9.9", inner_version="0.0.1")
    res = selfupdate.prepare("9.9.9", opener=opener_for(data), root=tmp_path / "up")
    assert not res.ok and "0.0.1" in res.message and selfupdate.pending(tmp_path / "up") is None


def test_redirect_elsewhere_and_size_limit(tmp_path, tarball, monkeypatch):
    res = selfupdate.prepare("9.9.9", opener=opener_for(tarball, url="https://boese.example/x"),
                             root=tmp_path / "up")
    assert not res.ok and "boese.example" in res.message
    monkeypatch.setattr(selfupdate, "MAX_BYTES", 1000)
    res = selfupdate.prepare("9.9.9", opener=opener_for(tarball), root=tmp_path / "up")
    assert not res.ok and selfupdate.pending(tmp_path / "up") is None


def test_path_traversal_is_refused(tmp_path):
    data = make_tarball(tmp_path, evil=True)
    res = selfupdate.prepare("9.9.9", opener=opener_for(data), root=tmp_path / "w" / "up")
    assert not res.ok
    assert not (tmp_path / "boese.txt").exists() and not (tmp_path / "w" / "boese.txt").exists()


def _old_app(tmp_path) -> Path:
    app = tmp_path / "home" / ".local" / "share" / "gogoham" / "app"
    (app / "gogoham").mkdir(parents=True)
    (app / "gogoham" / "__init__.py").write_text('__version__ = "0.1"\n', encoding="utf-8")
    return app


def test_apply_and_rollback(tmp_path, tarball):
    root = tmp_path / "up"
    assert selfupdate.prepare("9.9.9", opener=opener_for(tarball), root=root).ok
    app, home, data = _old_app(tmp_path), tmp_path / "home", tmp_path / "xdg"
    assert selfupdate.apply_pending(app, root, data, home) == "installed:9.9.9"
    v = selfupdate._version_in
    assert v(app / "gogoham") == "9.9.9" and v(app / "gogoham.prev") == "0.1"
    assert not root.exists() and not (app / "gogoham.new").exists()
    desk = (data / "applications" / "gogoham.desktop").read_text(encoding="utf-8")
    assert f"Exec={home / '.local' / 'bin' / 'gogoham'}" in desk
    assert list((data / "icons" / "hicolor").glob("*/apps/gogoham.png"))
    assert (data / "metainfo" / "io.github.do2ggh.GoGoHam.metainfo.xml").is_file()
    assert os.access(home / ".local" / "share" / "gogoham" / "uninstall.sh", os.X_OK)
    assert selfupdate.has_previous(app)
    assert selfupdate.apply_pending(app, root, data, home) == ""            # nichts mehr offen
    selfupdate.request_rollback(root)
    assert selfupdate.apply_pending(app, root, data, home) == "rolled-back"
    assert v(app / "gogoham") == "0.1" and v(app / "gogoham.prev") == "9.9.9"


def test_apply_with_missing_source_does_nothing(tmp_path):
    root = tmp_path / "up"
    root.mkdir()
    (root / "pending.json").write_text(json.dumps({"action": "install", "version": "9.9.9",
                                                   "src": str(tmp_path / "weg")}))
    app = _old_app(tmp_path)
    assert selfupdate.apply_pending(app, root, tmp_path / "xdg", tmp_path / "home") == ""
    assert selfupdate._version_in(app / "gogoham") == "0.1" and not root.exists()


def test_start_hook_applies_then_restarts(tmp_path, tarball, monkeypatch):
    root = tmp_path / "up"
    assert selfupdate.prepare("9.9.9", opener=opener_for(tarball), root=root).ok
    app = _old_app(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(selfupdate, "running_from", lambda: True)
    monkeypatch.setattr(selfupdate, "update_root", lambda: root)
    monkeypatch.setattr(selfupdate, "app_dir", lambda: app)
    calls = []
    monkeypatch.setattr(os, "execv", lambda exe, args: calls.append(args))
    monkeypatch.setattr(os, "chdir", lambda d: calls.append(("cd", str(d))))
    selfupdate.start_hook(["--x"])
    assert ("cd", str(app)) in calls and calls[-1][-3:] == ["-m", "gogoham", "--x"]
    assert selfupdate._version_in(app / "gogoham") == "9.9.9"


def test_not_for_source_tree_or_packages():
    assert not selfupdate.running_from()              # Tests laufen aus dem Quelltext-Ordner
    assert versioncheck.install_kind(str(Path.home() / ".local/share/gogoham/app/gogoham/x.py")) \
        == "script"
    assert "ein Klick" in versioncheck.hint_text("9.9.9", kind="script")


def test_dialog_worker():
    res = self_update._check_and_prepare(latest=lambda: "0.0.1", prepare=None)
    assert res.ok and not res.version and "neueste" in res.message
    got = []
    res = self_update._check_and_prepare(
        latest=lambda: "99.0", prepare=lambda v, progress=None: got.append(v) or
        selfupdate.Result(True, v, "bereit"))
    assert got == ["99.0"] and res.version == "99.0"

    def boom():
        raise OSError("kein Netz")
    res = self_update._check_and_prepare(latest=boom)
    assert not res.ok and "kein Netz" in res.message


def test_appstream_and_desktop_entry_are_valid():
    """0.10.47.1: Software-Verwaltungen finden GoGoHam (AppStream + Startmenü-Eintrag)."""
    import shutil as sh
    import subprocess as sp
    meta = ROOT / "data" / "io.github.do2ggh.GoGoHam.metainfo.xml"
    desk = ROOT / "data" / "gogoham.desktop"
    text = meta.read_text(encoding="utf-8")
    assert "<launchable type=\"desktop-id\">gogoham.desktop</launchable>" in text
    assert "<category>HamRadio</category>" in text and "GPL-3.0-only" in text
    for img in ("gogoham-en.png", "gogoham-de.png"):
        assert f"docs/images/{img}" in text and (ROOT / "docs" / "images" / img).is_file()
    d = desk.read_text(encoding="utf-8")
    assert "HamRadio" in d and "Keywords[de]=" in d and "Amateurfunk" in d
    assert meta.name in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert meta.name in (ROOT / "install.sh").read_text(encoding="utf-8")
    assert meta.name in (ROOT / "packaging" / "obs" / "gogoham.spec").read_text(encoding="utf-8")
    if sh.which("appstreamcli"):
        r = sp.run(["appstreamcli", "validate", "--no-net", str(meta)], capture_output=True,
                   text=True)
        assert r.returncode == 0, r.stdout + r.stderr
    if sh.which("desktop-file-validate"):
        r = sp.run(["desktop-file-validate", str(desk)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
