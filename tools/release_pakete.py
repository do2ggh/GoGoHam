#!/usr/bin/env python3
"""Fertige Pakete einer Version vom openSUSE Build Service holen – für die GitHub-Release-Seite.

Aufruf:  python3 tools/release_pakete.py 0.10.47.5 ausgabe/ [--notes notes.md] [--warten 10800]

Wartet, bis alle Paketquellen die Version anbieten, holt jede Datei vom Ursprungsserver und
prüft die ganze Kette: Unterschrift der Paketliste (Schlüssel FINGERPRINT) -> Prüfsumme der
Datei in der Paketliste -> heruntergeladene Datei. Eine veraltete Datei (Spiegel/CDN) fällt so
auf; dann wird später neu versucht. Schreibt die Dateien mit eindeutigem Namen, SHA256SUMS und
auf Wunsch den Text der Release-Seite. Nur Standardbibliothek + gpg.

Ändern sich die Distributionen in OBS (z. B. Fedora 45), REPOS unten anpassen.
"""
import argparse
import gzip
import hashlib
import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ORIGIN = "https://downloadcontent.opensuse.org/repositories/home:/Franz"
FINGERPRINT = "D389DED10CE918036666175678AF9B87F520FFB8"
REPO_URL = "https://github.com/do2ggh/GoGoHam"
KEY = "https://download.opensuse.org/repositories/home:/Franz"

# (OBS-Repo, Art, Kennung im Dateinamen, Anzeige auf der Release-Seite, Installationsbefehl)
REPOS = [
    ("openSUSE_Tumbleweed", "rpm", "opensuse-tumbleweed", "openSUSE Tumbleweed", "sudo zypper install ./{f}"),
    ("16.0", "rpm", "opensuse-leap16", "openSUSE Leap 16", "sudo zypper install ./{f}"),
    ("Fedora_44", "rpm", "fedora44", "Fedora 44", "sudo dnf install ./{f}"),
    ("Fedora_43", "rpm", "fedora43", "Fedora 43", "sudo dnf install ./{f}"),
    ("Debian_13", "deb", "debian13", "Debian 13", "sudo apt install ./{f}"),
    ("xUbuntu_26.04", "deb", "ubuntu26.04", "Ubuntu 26.04", "sudo apt install ./{f}"),
    ("Arch", "arch", "arch", "Arch / Garuda / Manjaro", "sudo pacman -U {f}"),
]


class Pending(Exception):
    """Version (noch) nicht oder nicht stimmig da – später noch einmal versuchen."""


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gogoham-release"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class Gpg:
    def __init__(self):
        self.home = tempfile.mkdtemp(prefix="gogoham-gpg-")
        os.chmod(self.home, 0o700)

    def run(self, *args, data=None):
        return subprocess.run(["gpg", "--homedir", self.home, "--batch", "--status-fd", "1", *args],
                              input=data, capture_output=True)

    def import_key(self, key):
        self.run("--import", data=key)

    def verify(self, sig, data=None):
        """Wahr, wenn die Unterschrift gültig und vom GoGoHam-Schlüssel ist."""
        with tempfile.TemporaryDirectory() as d:
            s = Path(d, "sig")
            s.write_bytes(sig)
            args = ["--verify", str(s)]
            if data is not None:
                p = Path(d, "data")
                p.write_bytes(data)
                args.append(str(p))
            out = self.run(*args).stdout.decode(errors="replace")
        return any(line.startswith("[GNUPG:] VALIDSIG ") and FINGERPRINT in line.split()
                   for line in out.splitlines())


# ---- Paketlisten auswerten (ohne Netz, getestet in tests/test_release_pakete.py) ----

def parse_repomd(xml):
    ns = {"r": "http://linux.duke.edu/metadata/repo"}
    for d in ET.fromstring(xml).findall("r:data", ns):
        if d.get("type") == "primary":
            ck = d.find("r:checksum", ns)
            return d.find("r:location", ns).get("href"), ck.get("type", "sha256"), ck.text.strip()
    raise Pending("repomd ohne primary")


def find_rpm(primary_xml, version):
    ns = {"c": "http://linux.duke.edu/metadata/common"}
    for p in ET.fromstring(primary_xml).findall("c:package", ns):
        if p.findtext("c:name", namespaces=ns) == "gogoham" and \
                p.find("c:version", ns).get("ver") == version:
            ck = p.find("c:checksum", ns)
            return p.find("c:location", ns).get("href"), ck.get("type"), ck.text.strip()
    raise Pending("rpm " + version + " fehlt")


def signed_text(inrelease):
    """Nur den unterschriebenen Teil einer InRelease-Datei."""
    m = re.search(r"-----BEGIN PGP SIGNED MESSAGE-----\r?\n.*?\r?\n\r?\n(.*?)\r?\n-----BEGIN PGP SIGNATURE-----",
                  inrelease, re.S)
    if not m:
        raise Pending("InRelease nicht unterschrieben")
    return m.group(1)


def release_sha256(release_text, name):
    sect = False
    for line in release_text.splitlines():
        if not line.startswith(" "):
            sect = line.strip() == "SHA256:"
            continue
        parts = line.split()
        if sect and len(parts) == 3 and parts[2] == name:
            return parts[0]
    raise Pending(name + " nicht in InRelease")


def find_deb(packages, version):
    for stanza in packages.split("\n\n"):
        f = {}
        for line in stanza.splitlines():
            if ":" in line and not line.startswith(" "):
                k, v = line.split(":", 1)
                f[k] = v.strip()
        if f.get("Package") == "gogoham" and f.get("Version", "").split("-")[0] == version:
            return f["Filename"], f["SHA256"]
    raise Pending("deb " + version + " fehlt")


def find_arch(db_targz, version):
    with tarfile.open(fileobj=io.BytesIO(db_targz)) as t:
        for m in t.getmembers():
            if not m.name.endswith("/desc"):
                continue
            fields, key = {}, None
            for line in t.extractfile(m).read().decode().splitlines():
                if line.startswith("%") and line.endswith("%"):
                    key = line.strip("%")
                elif line and key and key not in fields:
                    fields[key] = line
            if fields.get("NAME") == "gogoham" and fields.get("VERSION", "").split("-")[0] == version:
                return fields["FILENAME"], fields["SHA256SUM"]
    raise Pending("arch " + version + " fehlt")


def changelog_section(text, version):
    m = re.search(r"^## Neu in " + re.escape(version) + r"\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not m:
        raise SystemExit("CHANGELOG.md: kein Abschnitt „## Neu in " + version + "“")
    return m.group(1).strip()


# ---- Netz ----

def get_package(gpg, repo, kind, version):
    """Gibt [(Dateiname, Inhalt), …] zurück – geprüft – oder wirft Pending."""
    base = ORIGIN + "/" + repo + "/"
    try:
        if kind == "rpm":
            gpg.import_key(fetch(base + "repodata/repomd.xml.key"))
            repomd = fetch(base + "repodata/repomd.xml")
            if not gpg.verify(fetch(base + "repodata/repomd.xml.asc"), repomd):
                raise Pending("Unterschrift repomd.xml falsch")
            loc, algo, ck = parse_repomd(repomd)
            prim = fetch(base + loc)
            if algo not in ("sha256", "sha512") or hashlib.new(algo, prim).hexdigest() != ck:
                raise Pending("primary.xml veraltet")
            path, algo, ck = find_rpm(gzip.decompress(prim) if loc.endswith(".gz") else prim, version)
        elif kind == "deb":
            gpg.import_key(fetch(base + "Release.key"))
            inrel = fetch(base + "InRelease")
            if not gpg.verify(inrel):
                raise Pending("Unterschrift InRelease falsch")
            pk = fetch(base + "Packages")
            if sha256(pk) != release_sha256(signed_text(inrel.decode()), "Packages"):
                raise Pending("Packages veraltet")
            path, ck = find_deb(pk.decode(), version)
            algo = "sha256"
        else:
            base += "x86_64/"
            gpg.import_key(fetch(base + "home_Franz_Arch.key"))
            db = fetch(base + "home_Franz_Arch.db.tar.gz")
            if not gpg.verify(fetch(base + "home_Franz_Arch.db.tar.gz.sig"), db):
                raise Pending("Unterschrift Arch-Datenbank falsch")
            path, ck = find_arch(db, version)
            algo = "sha256"
        path = path.removeprefix("./")
        if algo not in ("sha256", "sha512"):
            raise Pending(path + ": unbekannte Prüfsumme " + str(algo))
        data = fetch(base + path)
        if hashlib.new(algo, data).hexdigest() != ck:
            raise Pending(path + ": Prüfsumme passt nicht (veraltete Datei?)")
        files = [(path, data)]
        if kind == "arch":
            sig = fetch(base + path + ".sig")
            if not gpg.verify(sig, data):
                raise Pending(path + ".sig passt nicht")
            files.append((path + ".sig", sig))
        return files
    except OSError as e:          # Netzfehler, 404 …
        raise Pending(str(e))


def out_name(kind, tag, version, orig):
    if kind == "rpm":
        return f"gogoham-{version}-{tag}.noarch.rpm"
    if kind == "deb":
        return f"gogoham_{version}_{tag}_all.deb"
    return f"gogoham-{version}-{tag}-any.pkg.tar.zst" + (".sig" if orig.endswith(".sig") else "")


def notes(version, rows):
    cl = changelog_section(Path(__file__).resolve().parent.parent.joinpath("CHANGELOG.md")
                           .read_text(encoding="utf-8"), version)
    table = "\n".join(f"| {disp} | `{name}` | `{cmd.format(f=name)}` |" for disp, cmd, name in rows)
    return f"""**GoGoHam {version}** – Contest-Logger für Linux

### Installieren
**Empfohlen:** GoGoHam über die Paketquelle installieren – dann kommt es mit dem normalen
Systemupdate automatisch mit. 👉 [Anleitung]({REPO_URL}#installation)

Die Dateien unten sind **zum Ausprobieren** ohne Paketquelle. ⚠ Damit gibt es **keine
automatischen Updates**. Alles, was GoGoHam braucht, holt der Befehl aus den normalen Quellen
deines Systems dazu.

**Einmalig vorher, nur openSUSE und Arch:** den GoGoHam-Schlüssel eintragen (sonst bricht die
Installation mit „Signature verification failed“ bzw. „invalid or corrupted package“ ab). Unter
Arch muss die Datei `….pkg.tar.zst.sig` im selben Ordner liegen.
```bash
# openSUSE
sudo rpm --import {KEY}/openSUSE_Tumbleweed/repodata/repomd.xml.key
# Arch / Garuda / Manjaro
curl -fsSL {KEY}/Arch/x86_64/home_Franz_Arch.key | sudo pacman-key --add -
sudo pacman-key --lsign-key {FINGERPRINT}
```

| System | Datei | Befehl im Ordner der Datei |
|---|---|---|
{table}

Die Dateien stammen aus der unterschriebenen Paketquelle (Schlüssel `{FINGERPRINT}`) und
wurden dagegen geprüft; Prüfsummen in `SHA256SUMS`.

### Neu in dieser Version
{cl}

---
**English:** Best installed from the package repository – updates then come with your normal
system update: [instructions]({REPO_URL}/blob/main/README.en.md#installation). The files above
are for trying GoGoHam out and do **not** receive updates. Changelog in German.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("version")
    ap.add_argument("outdir")
    ap.add_argument("--notes")
    ap.add_argument("--warten", type=int, default=0, help="Sekunden auf OBS warten (Standard 0)")
    a = ap.parse_args()
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    gpg = Gpg()
    done, deadline = {}, time.time() + a.warten
    while True:
        for repo, kind, tag, disp, cmd in REPOS:
            if repo in done:
                continue
            try:
                done[repo] = get_package(gpg, repo, kind, a.version)
                print("ok     ", repo, flush=True)
            except Pending as e:
                print("wartet ", repo, "–", e, flush=True)
        if len(done) == len(REPOS) or time.time() >= deadline:
            break
        time.sleep(120)
    missing = [r for r, *_ in REPOS if r not in done]
    if missing:
        sys.exit("Fehlt noch: " + ", ".join(missing))
    sums, rows = [], []
    for repo, kind, tag, disp, cmd in REPOS:
        for orig, data in done[repo]:
            name = out_name(kind, tag, a.version, orig)
            out.joinpath(name).write_bytes(data)
            sums.append(f"{sha256(data)}  {name}")
            if not name.endswith(".sig"):
                rows.append((disp, cmd, name))
    out.joinpath("SHA256SUMS").write_text("\n".join(sums) + "\n")
    if a.notes:
        Path(a.notes).write_text(notes(a.version, rows), encoding="utf-8")
    print("fertig:", len(sums), "Dateien in", out)


if __name__ == "__main__":
    main()
