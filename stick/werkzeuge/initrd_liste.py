"""Inhalt des Startsystems (initrd) im Stick-Abbild auflisten – ohne Bau, ohne root.
Aufruf: python3 stick/werkzeuge/initrd_liste.py [ausgabe/gogoham-live-X.iso] [Filter …]
Debian-initrds bestehen aus mehreren aneinandergehängten cpio-Archiven (Mikrocode vorn,
dann ein komprimiertes); hier werden alle durchgegangen."""
import subprocess, sys
from pathlib import Path

HIER = Path(__file__).resolve().parent.parent
iso = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].endswith(".iso") else \
    max((HIER / "ausgabe").glob("gogoham-live-*[0-9].iso"), key=lambda p: p.stat().st_mtime)
filt = [a for a in sys.argv[1:] if not a.endswith(".iso")]
names = subprocess.run(["bsdtar", "-tf", str(iso)], capture_output=True, text=True).stdout.split()
ird = next(n for n in names if n.startswith("live/initrd.img"))
data = subprocess.run(["bsdtar", "-xOf", str(iso), ird], capture_output=True).stdout

def newc(buf, pos):
    """Einträge eines unkomprimierten cpio (newc) ab pos – liefert (Name, Modus, Größe, Ziel), Ende."""
    out = []
    while buf[pos:pos + 6] in (b"070701", b"070702"):
        h = buf[pos:pos + 110]
        f = [int(h[6 + 8 * i:14 + 8 * i], 16) for i in range(13)]
        mode, size, nlen = f[1], f[6], f[11]
        name = buf[pos + 110:pos + 110 + nlen - 1].decode(errors="replace")
        p = (pos + 110 + nlen + 3) & ~3
        body = buf[p:p + size]
        pos = (p + size + 3) & ~3
        if name == "TRAILER!!!":
            break
        out.append((name, mode, size, body.decode(errors="replace") if mode & 0o170000 == 0o120000 else ""))
    while pos < len(buf) and buf[pos] == 0:
        pos += 1
    return out, pos

entries, pos = [], 0
while pos < len(data):
    if data[pos:pos + 6] in (b"070701", b"070702"):
        e, pos = newc(data, pos); entries += e
        continue
    # Rest komprimiert (zstd / gzip / xz)
    rest = data[pos:]
    for prog in (["zstd", "-dc"], ["gzip", "-dc"], ["xz", "-dc"]):
        r = subprocess.run(prog, input=rest, capture_output=True)
        if r.returncode == 0 and r.stdout[:6] in (b"070701", b"070702"):
            p2 = 0
            while p2 < len(r.stdout) and r.stdout[p2:p2 + 6] in (b"070701", b"070702"):
                e, p2 = newc(r.stdout, p2); entries += e
            break
    break

for name, mode, size, target in entries:
    if filt and not any(f in name for f in filt):
        continue
    kind = "l" if mode & 0o170000 == 0o120000 else ("d" if mode & 0o170000 == 0o040000 else "-")
    print(f"{kind} {size:>9} {name}" + (f" -> {target}" if target else ""))
