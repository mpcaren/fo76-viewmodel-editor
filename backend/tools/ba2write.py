"""ba2write.py <out.ba2> <rootdir> [--verify <existing.ba2>]
Writes a BTDX v1 GNRL archive (uncompressed) of every file under rootdir (paths relative to it)."""
import struct, sys, os, zlib


def bhash(s):
    # Bethesda BA2 hash = reflected CRC-32 (0xEDB88320), init 0, no final xor
    return (~zlib.crc32(s.encode('ascii'), 0xFFFFFFFF)) & 0xFFFFFFFF


def split(name):
    n = name.replace('/', '\\').lower()
    d, f = n.rsplit('\\', 1)
    stem, ext = f.rsplit('.', 1)
    return d, stem, ext


def read_records(path):
    with open(path, 'rb') as f:
        f.read(8); f.read(4)
        count, ntab = struct.unpack('<IQ', f.read(12))
        recs = [struct.unpack('<I4sIIQIII', f.read(36)) for _ in range(count)]
        f.seek(ntab)
        names = []
        for _ in range(count):
            n = struct.unpack('<H', f.read(2))[0]; names.append(f.read(n).decode())
    return list(zip(names, recs))


def write(out, root):
    files = []
    for dp, dn, fn in os.walk(root):
        for f in sorted(fn):
            full = os.path.join(dp, f)
            files.append((os.path.relpath(full, root).replace('\\', '/').lower(), full))
    files.sort()
    hdr = 24
    off = hdr + 36 * len(files)
    recs, blobs = [], []
    for name, full in files:
        data = open(full, 'rb').read()
        d, stem, ext = split(name)
        recs.append(struct.pack('<I4sIIQIII', bhash(stem), ext.encode().ljust(4, b'\0')[:4], bhash(d),
                                0x100100, off, 0, len(data), 0xBAADF00D))
        blobs.append(data); off += len(data)
    ntab = off
    with open(out, 'wb') as f:
        f.write(b'BTDX' + struct.pack('<I', 1) + b'GNRL' + struct.pack('<IQ', len(files), ntab))
        for r in recs: f.write(r)
        for b in blobs: f.write(b)
        for name, _ in files:
            e = name.encode(); f.write(struct.pack('<H', len(e)) + e)
    return [n for n, _ in files]


if __name__ == '__main__':
    if '--verify' in sys.argv:
        ref = sys.argv[sys.argv.index('--verify') + 1]
        ok = bad = 0
        for name, (h, ext, dh, fl, o, p, sz, al) in read_records(ref):
            d, stem, e = split(name)
            if (bhash(stem), bhash(d), e.encode().ljust(4, b'\0')[:4]) == (h, dh, ext):
                ok += 1
            else:
                bad += 1
        print('hash check vs %s: ok=%d bad=%d  (flags=%#x align=%#x on last)' % (os.path.basename(ref), ok, bad, fl, al))
    else:
        names = write(sys.argv[1], sys.argv[2])
        print('wrote', sys.argv[1], len(names), 'files')
