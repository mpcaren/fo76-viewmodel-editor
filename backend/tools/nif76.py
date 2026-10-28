"""Minimal FO76 NIF reader (20.2.0.7, bsver 155): header, NiNode tree, BSTriShape geometry, BSSkin."""
import struct, sys


class B:
    def __init__(self, b, p=0):
        self.b, self.p = b, p

    def u8(self): v = self.b[self.p]; self.p += 1; return v
    def u16(self): v = struct.unpack_from('<H', self.b, self.p)[0]; self.p += 2; return v
    def u32(self): v = struct.unpack_from('<I', self.b, self.p)[0]; self.p += 4; return v
    def i32(self): v = struct.unpack_from('<i', self.b, self.p)[0]; self.p += 4; return v
    def u64(self): v = struct.unpack_from('<Q', self.b, self.p)[0]; self.p += 8; return v
    def f32(self): v = struct.unpack_from('<f', self.b, self.p)[0]; self.p += 4; return v
    def fs(self, n): v = struct.unpack_from('<%df' % n, self.b, self.p); self.p += 4 * n; return list(v)
    def h16(self): v = struct.unpack_from('<e', self.b, self.p)[0]; self.p += 2; return v
    def raw(self, n): v = self.b[self.p:self.p + n]; self.p += n; return v
    def sstr(self): n = self.u8(); return self.raw(n).rstrip(b'\0').decode('latin1')
    def lstr(self): n = self.u32(); return self.raw(n).decode('latin1')


class Nif:
    def __init__(self, path, data=None):
        self.path = path
        b = data if data is not None else open(path, 'rb').read()
        r = B(b)
        nl = b.index(b'\n')
        self.header = b[:nl].decode()
        r.p = nl + 1
        self.version = r.u32(); r.u8()
        self.user = r.u32(); nb = r.u32()
        self.bsver = r.u32()
        r.sstr()                       # author
        if self.bsver > 130:
            r.u32()                    # unknown int
        if self.bsver < 131:
            r.sstr()                   # process script
        r.sstr()                       # export script
        if self.bsver >= 103:
            r.sstr()                   # max filepath
        nt = r.u16()
        self.btypes = [r.lstr() for _ in range(nt)]
        tidx = [r.u16() for _ in range(nb)]
        sizes = [r.u32() for _ in range(nb)]
        ns = r.u32(); r.u32()
        self.strings = [r.lstr() for _ in range(ns)]
        ng = r.u32()
        for _ in range(ng): r.u32()
        self.blocks = []
        p = r.p
        for i in range(nb):
            t = self.btypes[tidx[i] & 0x7FFF]
            self.blocks.append({'i': i, 'type': t, 'off': p, 'size': sizes[i]})
            p += sizes[i]
        self.b = b
        for blk in self.blocks:
            self.parse(blk)

    def s(self, idx):
        return self.strings[idx] if 0 <= idx < len(self.strings) else None

    def avobject(self, r, d):
        d['name'] = self.s(r.i32())
        d['extra'] = [r.i32() for _ in range(r.u32())]
        d['controller'] = r.i32()
        d['flags'] = r.u32()
        d['t'] = r.fs(3)
        d['R'] = [r.fs(3) for _ in range(3)]   # row-major 3x3
        d['scale'] = r.f32()
        d['collision'] = r.i32()

    def parse(self, d):
        t = d['type']
        r = B(self.b, d['off'])
        try:
            if t in ('NiNode', 'BSFadeNode', 'BSLeafAnimNode', 'BSWeakReferenceNode', 'BSOrderedNode', 'BSValueNode'):
                self.avobject(r, d)
                d['children'] = [r.i32() for _ in range(r.u32())]
            elif t in ('BSTriShape', 'BSSubIndexTriShape', 'BSMeshLODTriShape', 'BSDynamicTriShape'):
                self.avobject(r, d)
                d['bsphere'] = r.fs(4)
                if self.bsver == 155:
                    d['bminmax'] = r.fs(6)
                d['skin'] = r.i32(); d['shader'] = r.i32(); d['alpha'] = r.i32()
                desc = r.u64()
                ntri = r.u32() if self.bsver >= 130 else r.u16()
                nv = r.u16(); dsize = r.u32()
                d['desc'] = desc; d['ntri'] = ntri; d['nv'] = nv; d['dsize'] = dsize
                if dsize:
                    self.vertices(r, d)
                    d['tris'] = [struct.unpack_from('<3H', self.b, r.p + 6 * k) for k in range(ntri)]
                    r.p += 6 * ntri
            elif t == 'BSSkin::Instance':
                d['root'] = r.i32(); d['bonedata'] = r.i32()
                d['bones'] = [r.i32() for _ in range(r.u32())]
            elif t == 'BSSkin::BoneData':
                n = r.u32(); bones = []
                for _ in range(n):
                    sph = r.fs(4); R = [r.fs(3) for _ in range(3)]; tt = r.fs(3); sc = r.f32()
                    bones.append({'R': R, 't': tt, 'scale': sc})
                d['bones'] = bones
            elif t == 'BSConnectPoint::Parents':
                d['name'] = self.s(r.i32())
                cps = []
                for _ in range(r.u32()):
                    parent = r.lstr(); name = r.lstr()
                    q = r.fs(4); tt = r.fs(3); sc = r.f32()
                    cps.append({'parent': parent, 'name': name, 'q': q, 't': tt, 'scale': sc})
                d['cps'] = cps
            elif t == 'BSConnectPoint::Children':
                d['name'] = self.s(r.i32())
                d['skinned'] = r.u8()
                d['targets'] = [r.lstr() for _ in range(r.u32())]
            elif t in ('NiStringExtraData',):
                d['name'] = self.s(r.i32()); d['value'] = self.s(r.i32())
            elif t in ('BSLightingShaderProperty', 'BSEffectShaderProperty'):
                d['name'] = self.s(r.i32())
        except Exception as e:  # keep going; report
            d['error'] = repr(e)

    def vertices(self, r, d):
        desc = d['desc']
        vsize = (desc & 0xF) * 4
        flags = desc >> 44
        off = lambda k: ((desc >> (4 * k)) & 0xF) * 4
        full = bool(flags & 0x400) or self.bsver == 100
        V, UV, W, J = [], [], [], []
        base = r.p
        for k in range(d['nv']):
            p = base + k * vsize
            if flags & 1:
                if full:
                    V.append(struct.unpack_from('<3f', self.b, p))
                else:
                    V.append(struct.unpack_from('<3e', self.b, p))
            if flags & 2:
                UV.append(struct.unpack_from('<2e', self.b, p + off(2)))
            if flags & 0x40:
                q = p + off(7)
                W.append(struct.unpack_from('<4e', self.b, q))
                J.append(struct.unpack_from('<4B', self.b, q + 8))
        r.p = base + vsize * d['nv']
        d['V'], d['UV'], d['W'], d['J'] = V, UV, W, J
        d['full'] = full

    def tree(self, i=0, depth=0, out=None):
        out = [] if out is None else out
        d = self.blocks[i]
        out.append((depth, d))
        for c in d.get('children', []):
            if c >= 0:
                self.tree(c, depth + 1, out)
        return out


if __name__ == '__main__':
    for p in sys.argv[1:]:
        n = Nif(p)
        print('==', p.split('/')[-1].split('\\')[-1], n.header, 'bsver', n.bsver, 'blocks', len(n.blocks))
        print('   types:', sorted(set(n.btypes)))
        for depth, d in n.tree():
            extra = ''
            if 'nv' in d:
                extra = ' nv=%d ntri=%d dsize=%d desc=%016x full=%s skin=%d' % (d['nv'], d['ntri'], d['dsize'], d['desc'], d.get('full'), d['skin'])
            print('   ' + '  ' * depth + '%s "%s" t=(%s)%s%s' % (d['type'], d.get('name'), ' '.join('%.2f' % x for x in d.get('t', [])), extra,
                                                           ' ERR ' + d['error'] if 'error' in d else ''))
        for d in n.blocks:
            if d['type'].startswith('BSConnectPoint'):
                print('  ', d['type'], d.get('cps') or d.get('targets'))
            if 'error' in d:
                print('   ERROR', d['type'], d['error'])
