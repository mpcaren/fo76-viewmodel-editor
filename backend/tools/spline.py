"""Walk hkaSplineCompressedAnimation blocks; locate per-track position floats (absolute file offsets)."""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tag0 import Tag
from lossless import find, arr

ROT_SIZE = {0: 4, 1: 5, 2: 6, 3: 3, 4: 2, 5: 16}
ROT_ALIGN = {0: 4, 1: 1, 2: 2, 3: 1, 4: 2, 5: 4}


def pad(p, base, a):
    r = (p - base) % a
    return p if r == 0 else p + (a - r)


class Spline:
    def __init__(self, path):
        self.path = path
        self.tg = tg = Tag(path)
        k = find(tg, 'hkaSplineCompressedAnimation')
        if k is None:
            raise ValueError('not spline')
        a = self.a = tg.item_values(k)[0]
        b = tg.item_values(find(tg, 'hkaAnimationBinding'))[0]
        self.blendHint = b['blendHint']
        self.t2b = arr(tg, b['transformTrackToBoneIndices'])
        self.nT = a['numberOfTransformTracks']; self.nF = a['numberOfFloatTracks']
        self.F = a['numFrames']; self.nB = a['numBlocks']; self.fpb = a['maxFramesPerBlock']
        self.blockOffsets = arr(tg, a['blockOffsets'])
        di = a['data'][1]
        ti, fl, off, cnt = tg.items[di]
        self.d0 = tg.data0 + off  # absolute offset of the data byte array
        self.dlen = cnt
        self.blocks = [self.parse_block(bi) for bi in range(self.nB)]

    def parse_block(self, bi):
        b = self.tg.b
        base = self.d0 + self.blockOffsets[bi]
        end = self.d0 + (self.blockOffsets[bi + 1] if bi + 1 < self.nB else self.dlen)
        p = base
        masks = []
        for t in range(self.nT):
            masks.append(tuple(b[p:p + 4])); p += 4
        p = pad(p, base, 4)
        tracks = []
        for t in range(self.nT):
            q, pt, rt, st = masks[t]
            info = {'mask': masks[t]}
            # --- position
            info['pos'], p = self.vec(b, p, base, pt, q & 3)
            p = pad(p, base, 4)
            # --- rotation
            rq = (q >> 2) & 0xF
            if rt & 0xF0:
                n = struct.unpack('<H', b[p:p + 2])[0]; deg = b[p + 2]; p += 3 + n + deg + 2
                p = pad(p, base, ROT_ALIGN[rq]); p += (n + 1) * ROT_SIZE[rq]
                info['rot'] = ('spline', n, deg)
            elif rt & 0x0F:
                p = pad(p, base, ROT_ALIGN[rq]); p += ROT_SIZE[rq]
                info['rot'] = ('static',)
            else:
                info['rot'] = ('identity',)
            p = pad(p, base, 4)
            # --- scale
            info['scale'], p = self.vec(b, p, base, st, (q >> 6) & 3)
            p = pad(p, base, 4)
            tracks.append(info)
        return {'base': base, 'end': end, 'tracks_end': p, 'tracks': tracks}

    def vec(self, b, p, base, types, quant):
        """Returns (info, newp). info['comp'][c] = ('spline', min_off, max_off) | ('static', off) | ('zero',)."""
        comp = []
        if types & 0x70:
            n = struct.unpack('<H', b[p:p + 2])[0]; deg = b[p + 2]; p += 3
            knots = list(b[p:p + n + deg + 2]); p += n + deg + 2
            p = pad(p, base, 4)
            nsp = 0
            for c in range(3):
                if types & (0x10 << c):
                    comp.append(('spline', p, p + 4)); p += 8; nsp += 1
                elif types & (1 << c):
                    comp.append(('static', p)); p += 4
                else:
                    comp.append(('zero',))
            qs = 1 if quant == 0 else 2
            cps_off = p
            p += (n + 1) * nsp * qs
            return {'comp': comp, 'n': n, 'deg': deg, 'knots': knots, 'quant': qs, 'cps': cps_off, 'nsp': nsp}, p
        for c in range(3):
            if types & (1 << c):
                comp.append(('static', p)); p += 4
            else:
                comp.append(('zero',))
        return {'comp': comp}, p

    def f32(self, off):
        return struct.unpack('<f', self.tg.b[off:off + 4])[0]

    def pos_cp0(self, bi, tr):
        """Position at the first frame of block bi (= first control point for clamped splines)."""
        v = self.blocks[bi]['tracks'][tr]['pos']
        out = []
        k = 0
        for c, e in enumerate(v['comp']):
            if e[0] == 'zero':
                out.append(0.0)
            elif e[0] == 'static':
                out.append(self.f32(e[1]))
            else:
                lo, hi = self.f32(e[1]), self.f32(e[2])
                qs = v['quant']
                o = v['cps'] + k * qs
                raw = self.tg.b[o] if qs == 1 else struct.unpack('<H', self.tg.b[o:o + 2])[0]
                mx = 255 if qs == 1 else 65535
                out.append(lo + (hi - lo) * raw / mx)
                k += 1
        return out


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from lossless import Skeleton
    sk = Skeleton(sys.argv[1])
    COM = sk.bones.index('COM')
    for p in sys.argv[2:]:
        s = Spline(p)
        tr = s.t2b.index(COM) if s.t2b else COM
        print('== %s frames=%d blocks=%d fpb=%d' % (os.path.basename(p), s.F, s.nB, s.fpb))
        for bi, blk in enumerate(s.blocks):
            slack = blk['end'] - blk['tracks_end']
            v = blk['tracks'][tr]['pos']
            print('  block %d  parsed-to-end slack=%d  COM pos comps=%s  cp0=(%s)' % (
                bi, slack, [e[0] for e in v['comp']], ' '.join('%.3f' % x for x in s.pos_cp0(bi, tr))))
