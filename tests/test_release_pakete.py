"""tools/release_pakete.py: Paketlisten auswerten und Text der Release-Seite (ohne Netz)."""
import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("release_pakete", ROOT / "tools" / "release_pakete.py")
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)

REPOMD = b"""<?xml version="1.0"?><repomd xmlns="http://linux.duke.edu/metadata/repo">
<data type="filelists"><checksum type="sha256">aa</checksum><location href="repodata/f.xml.gz"/></data>
<data type="primary"><checksum type="sha512">bb</checksum><location href="repodata/p.xml.gz"/></data>
</repomd>"""

PRIMARY = b"""<?xml version="1.0"?><metadata xmlns="http://linux.duke.edu/metadata/common" packages="2">
<package type="rpm"><name>gogoham</name><version epoch="0" ver="0.10.47.4" rel="3.1"/>
 <checksum type="sha512">alt</checksum><location href="noarch/gogoham-0.10.47.4-3.1.noarch.rpm"/></package>
<package type="rpm"><name>gogoham</name><version epoch="0" ver="0.10.47.5" rel="5.1"/>
 <checksum type="sha512">neu</checksum><location href="noarch/gogoham-0.10.47.5-5.1.noarch.rpm"/></package>
</metadata>"""

INRELEASE = """-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA256

Origin: obs://build.opensuse.org/home:Franz/Debian_13
SHA256:
 1111 10 Packages.gz
 2222 20 Packages
-----BEGIN PGP SIGNATURE-----

xyz
-----END PGP SIGNATURE-----
"""

PACKAGES = """Package: gogoham
Version: 0.10.47.5-0
Filename: ./all/gogoham_0.10.47.5-0_all.deb
SHA256: abc
Description: Contest-Logger
 mehrzeilig: mit Doppelpunkt

Package: anderes
Version: 0.10.47.5-0
Filename: ./all/anderes.deb
SHA256: falsch
"""


def arch_db(version):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        desc = (f"%FILENAME%\ngogoham-{version}-0-any.pkg.tar.zst\n\n%NAME%\ngogoham\n\n"
                f"%VERSION%\n{version}-0\n\n%SHA256SUM%\ndef\n").encode()
        info = tarfile.TarInfo(f"gogoham-{version}-0/desc")
        info.size = len(desc)
        t.addfile(info, io.BytesIO(desc))
    return buf.getvalue()


def test_rpm():
    assert rp.parse_repomd(REPOMD) == ("repodata/p.xml.gz", "sha512", "bb")
    assert rp.find_rpm(PRIMARY, "0.10.47.5") == ("noarch/gogoham-0.10.47.5-5.1.noarch.rpm", "sha512", "neu")
    with pytest.raises(rp.Pending):
        rp.find_rpm(PRIMARY, "0.10.48")


def test_deb():
    assert rp.release_sha256(rp.signed_text(INRELEASE), "Packages") == "2222"
    assert rp.find_deb(PACKAGES, "0.10.47.5") == ("./all/gogoham_0.10.47.5-0_all.deb", "abc")
    with pytest.raises(rp.Pending):
        rp.find_deb(PACKAGES, "0.10.47.4")
    with pytest.raises(rp.Pending):          # ohne Unterschrift kein Inhalt
        rp.signed_text("SHA256:\n 2222 20 Packages\n")


def test_arch():
    assert rp.find_arch(arch_db("0.10.47.5"), "0.10.47.5") == ("gogoham-0.10.47.5-0-any.pkg.tar.zst", "def")
    with pytest.raises(rp.Pending):
        rp.find_arch(arch_db("0.10.47.4"), "0.10.47.5")


def test_namen_eindeutig():
    names = {rp.out_name(kind, tag, "1.0", "x") for _, kind, tag, *_ in rp.REPOS}
    assert len(names) == len(rp.REPOS)
    assert rp.out_name("arch", "arch", "1.0", "a.sig").endswith(".pkg.tar.zst.sig")


def test_text_mit_changelog():
    import gogoham
    rows = [("Debian 13", "sudo apt install ./{f}", "gogoham_x_debian13_all.deb")]
    text = rp.notes(gogoham.__version__, rows)
    assert "keine\nautomatischen Updates" in text
    assert "`sudo apt install ./gogoham_x_debian13_all.deb`" in text
    assert rp.changelog_section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"),
                                gogoham.__version__) in text
    with pytest.raises(SystemExit):
        rp.changelog_section("## Neu in 1.0\n* x\n", "0.1")
