"""Read-only access to the game's GNRL .ba2 archives: build a name index, read files by name."""
import struct, os, zlib, json

# searched in this order; the first archive that has a name wins (update archives override the base ones)
ARCHIVES = ['SeventySix - 00UpdateMain.ba2', 'SeventySix - 00UpdateStream.ba2', 'SeventySix - Animations.ba2',
            'SeventySix - Meshes.ba2', 'SeventySix - MeshesExtra.ba2', 'SeventySix - Startup.ba2']


def read_table(path):
    """[(name, offset, packed, size)] of a GNRL archive."""
    with open(path, 'rb') as f:
        magic = f.read(4)
        ver = struct.unpack('<I', f.read(4))[0]
        typ = f.read(4)
        if magic != b'BTDX' or typ != b'GNRL':
            return []
        count, ntab = struct.unpack('<IQ', f.read(12))
        if ver in (2, 3):
            f.read(8 if ver == 2 else 12)
        recs = []
        raw = f.read(36 * count)
        for k in range(count):
            h, ext, dh, fl, off, packed, size, al = struct.unpack_from('<I4sIIQIII', raw, 36 * k)
            recs.append((off, packed, size))
        f.seek(ntab)
        tab = f.read()
    names, p = [], 0
    for _ in range(count):
        n = struct.unpack_from('<H', tab, p)[0]
        names.append(tab[p + 2:p + 2 + n].decode('utf-8', 'replace').replace('\\', '/').lower())
        p += 2 + n
    return [(nm,) + r for nm, r in zip(names, recs)]


class Index:
    """name -> (archive path, offset, packed, size); cached as JSON keyed by archive sizes/mtimes."""

    def __init__(self, data_dir, cache_file):
        self.data_dir = data_dir
        stamp = []
        for a in ARCHIVES:
            p = os.path.join(data_dir, a)
            if os.path.exists(p):
                st = os.stat(p)
                stamp.append([a, st.st_size, int(st.st_mtime)])
        self.map = None
        if os.path.exists(cache_file):
            try:
                c = json.load(open(cache_file))
                if c['stamp'] == stamp:
                    self.map = c['map']
            except Exception:
                pass
        if self.map is None:
            self.map = {}
            for a, _, _ in reversed(stamp):          # later loops overwrite -> first archive in ARCHIVES wins
                for nm, off, packed, size in read_table(os.path.join(data_dir, a)):
                    self.map[nm] = [a, off, packed, size]
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            json.dump({'stamp': stamp, 'map': self.map}, open(cache_file, 'w'))

    def has(self, name):
        return name.lower() in self.map

    def names(self, prefix):
        prefix = prefix.lower()
        return sorted(n for n in self.map if n.startswith(prefix))

    def read(self, name):
        a, off, packed, size = self.map[name.lower()]
        with open(os.path.join(self.data_dir, a), 'rb') as f:
            f.seek(off)
            data = f.read(packed or size)
        if packed:
            data = zlib.decompress(data)
        assert len(data) == size, name
        return data

    def extract(self, name, root):
        """Write name under root (keeps the archive path) unless it is already there; returns the path."""
        dst = os.path.join(root, name.lower())
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + '.part'
            open(tmp, 'wb').write(self.read(name))
            os.replace(tmp, dst)
        return dst
