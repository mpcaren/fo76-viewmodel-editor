"""Minimal Havok 2015 tagfile (TAG0) reader: sections, types, items."""
import struct, sys


class R:
    def __init__(self, b, p=0):
        self.b, self.p = b, p

    def u8(self):
        v = self.b[self.p]; self.p += 1; return v

    def packed(self):
        b = self.u8()
        if b < 0x80:
            return b
        h = b >> 3
        if 0x10 <= h <= 0x17:
            return ((b << 8) | self.u8()) & 0x3FFF
        if 0x18 <= h <= 0x1B:
            v = b
            for _ in range(2): v = (v << 8) | self.u8()
            return v & 0x1FFFFF
        if h == 0x1C:
            v = b
            for _ in range(3): v = (v << 8) | self.u8()
            return v & 0x7FFFFFF
        if h == 0x1D:
            v = b
            for _ in range(4): v = (v << 8) | self.u8()
            return v & 0x7FFFFFFFF
        if h == 0x1E:
            v = b
            for _ in range(7): v = (v << 8) | self.u8()
            return v & 0x7FFFFFFFFFFFFFF
        raise ValueError('bad packed 0x%x at %d' % (b, self.p - 1))


def sections(b, start, end, depth=0, out=None):
    out = [] if out is None else out
    p = start
    while p < end:
        hdr = struct.unpack('>I', b[p:p + 4])[0]
        flag, size = hdr >> 30, hdr & 0x3FFFFFFF
        tag = b[p + 4:p + 8].decode('ascii')
        out.append((depth, tag, p + 8, p + size, flag))
        if flag == 0:  # container
            sections(b, p + 8, p + size, depth + 1, out)
        p += size
    return out


def strings(blob):
    return blob.split(b'\0')[:-1]


class Type:
    def __init__(self, i):
        self.i = i; self.name = None; self.tmpl = []; self.parent = 0
        self.flags = 0; self.sub = 0; self.ptr = 0; self.ver = 0
        self.size = 0; self.align = 0; self.abstract = 0
        self.fields = []; self.ifaces = []; self.attr = 0

    def __repr__(self):
        return '<T%d %s>' % (self.i, self.full())

    def full(self):
        if not self.tmpl:
            return self.name
        return '%s<%s>' % (self.name, ','.join(
            (types_ref[v].full() if k.startswith('t') and v else str(v)) for k, v in self.tmpl))


types_ref = {}


class Tag:
    def __init__(self, path):
        self.b = b = open(path, 'rb').read()
        self.secs = sections(b, 0, len(b))
        S = {t: (s, e) for d, t, s, e, f in self.secs}
        for a, c in (('TST1', 'TSTR'), ('FST1', 'FSTR'), ('TNA1', 'TNAM'), ('TBDY', 'TBOD')):
            if a not in S and c in S:
                S[a] = S[c]
        self.S = S
        self.sdk = b[S['SDKV'][0]:S['SDKV'][1]].decode()
        self.data0, self.data1 = S['DATA']
        tst = strings(b[S['TST1'][0]:S['TST1'][1]])
        fst = strings(b[S['FST1'][0]:S['FST1'][1]])
        self.tst, self.fst = tst, fst
        # TNA1
        r = R(b, S['TNA1'][0])
        n = r.packed()
        T = {0: None}
        for i in range(1, n):
            t = Type(i); t.name = tst[r.packed()].decode()
            for _ in range(r.packed()):
                k = tst[r.packed()].decode(); v = r.packed()
                t.tmpl.append((k, v))
            T[i] = t
        types_ref.clear(); types_ref.update(T)
        # TBDY
        r = R(b, S['TBDY'][0]); end = S['TBDY'][1]
        while r.p < end:
            i = r.packed()
            if i == 0:
                continue
            t = T[i]
            t.parent = r.packed(); t.flags = f = r.packed()
            if f & 1: t.sub = r.packed()
            if f & 2: t.ptr = r.packed()
            if f & 4: t.ver = r.packed()
            if f & 8: t.size = r.packed(); t.align = r.packed()
            if f & 0x10: t.abstract = r.packed()
            if f & 0x20:
                cnt = r.packed() & 0xFFFF
                for _ in range(cnt):
                    nm = fst[r.packed()].decode(); ff = r.packed(); off = r.packed(); ty = r.packed()
                    t.fields.append((nm, ff, off, ty))
            if f & 0x40:
                for _ in range(r.packed()):
                    t.ifaces.append((r.packed(), r.packed()))
            if f & 0x80:
                t.attr = r.packed()
        self.T = T
        # ITEM
        s, e = S['ITEM']
        self.items = []
        for p in range(s, e, 12):
            fl, off, cnt = struct.unpack('<III', b[p:p + 12])
            self.items.append((fl & 0xFFFFFF, fl >> 24, off, cnt))

    # --- type helpers
    def resolve_sub(self, t):
        while t and not (t.flags & 1):
            t = self.T[t.parent]
        return t

    def tsize(self, t):
        while t and not (t.flags & 8):
            t = self.T[t.parent]
        return t.size if t else 0

    def allfields(self, t):
        chain = []
        while t:
            chain.append(t); t = self.T[t.parent]
        out = []
        for c in reversed(chain):
            out += c.fields
        return out

    def ptrtype(self, t):
        while t and not (t.flags & 2):
            t = self.T[t.parent]
        return self.T[t.ptr] if t else None

    # --- value reader
    def read(self, t, off, depth=0):
        b = self.b
        st = self.resolve_sub(t)
        sub = st.sub if st else 0
        kind = sub & 0x1F
        if kind == 0:
            return None
        if kind == 1:  # opaque
            return '<opaque %s>' % t.full()
        if kind == 2:
            return b[off] != 0
        if kind == 3:  # string -> item index
            idx = struct.unpack('<Q', b[off:off + 8])[0]
            return self.item_str(idx)
        if kind == 4:
            bits = {0x2000: 1, 0x4000: 2, 0x8000: 4, 0x10000: 8}
            sz = next((v for k, v in bits.items() if sub & k), self.tsize(t))
            signed = bool(sub & 0x200)
            return int.from_bytes(b[off:off + sz], 'little', signed=signed)
        if kind == 5:
            sz = self.tsize(t)
            if sz == 4:
                return struct.unpack('<f', b[off:off + 4])[0]
            if sz == 2:
                return struct.unpack('<e', b[off:off + 2])[0]
            return struct.unpack('<d', b[off:off + 8])[0]
        if kind == 6:  # pointer -> item index
            return ('ptr', struct.unpack('<Q', b[off:off + 8])[0])
        if kind == 7:  # record
            return {nm: self.read(self.T[ty], off + fo, depth + 1)
                    for nm, ff, fo, ty in self.allfields(t)}
        if kind == 8:  # array or tuple
            et = self.ptrtype(t)
            if sub & 0x20:  # tuple, count in high bits
                n = sub >> 8
                es = self.tsize(et)
                return [self.read(et, off + k * es, depth + 1) for k in range(n)]
            idx = struct.unpack('<Q', b[off:off + 8])[0]
            return ('arr', idx)
        return '<kind %d sub 0x%x>' % (kind, sub)

    def item_str(self, idx):
        if not idx:
            return None
        ti, fl, off, cnt = self.items[idx]
        s = self.data0 + off
        return self.b[s:s + cnt].split(b'\0')[0].decode('utf-8', 'replace')

    def item_values(self, idx, limit=None):
        ti, fl, off, cnt = self.items[idx]
        t = self.T[ti]; es = self.tsize(t)
        n = cnt if limit is None else min(cnt, limit)
        return [self.read(t, self.data0 + off + k * es) for k in range(n)]


if __name__ == '__main__':
    tg = Tag(sys.argv[1])
    print('SDK', tg.sdk)
    for d, t, s, e, f in tg.secs:
        print('  ' * d + t, e - s)
    for i, t in tg.T.items():
        if t is None: continue
        print('T%-3d %-50s parent=%-3s flags=%-3x sub=%-8x size=%-4s fields=%s' % (
            i, t.full(), t.parent, t.flags, t.sub, t.size, [(n, o, ty) for n, ff, o, ty in t.fields]))
    print('items:')
    for k, (ti, fl, off, cnt) in enumerate(tg.items):
        print('  #%-3d T%-3d %-40s flags=%02x off=%-6d cnt=%d' % (k, ti, tg.T[ti].full() if ti else '-', fl, off, cnt))
