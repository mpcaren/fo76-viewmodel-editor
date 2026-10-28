"""Decode hkaLosslessCompressedAnimation (FO76) + forward kinematics."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tag0 import Tag


def find(tg, name):
    r = [k for k, (ti, fl, off, cnt) in enumerate(tg.items) if ti and tg.T[ti].name == name and fl == 0x10]
    return r[0] if r else None


def arr(tg, v):
    return tg.item_values(v[1]) if v[1] else []


class Skeleton:
    def __init__(self, path):
        sk = Tag(path)
        s = sk.item_values(find(sk, 'hkaSkeleton'))[0]
        self.bones = [b['name'] for b in arr(sk, s['bones'])]
        self.parents = arr(sk, s['parentIndices'])
        self.ref = [(r['translation'][:3], r['rotation']) for r in arr(sk, s['referencePose'])]


class Anim:
    def __init__(self, path):
        self.tg = an = Tag(path)
        k = find(an, 'hkaLosslessCompressedAnimation')
        if k is None:
            kinds = sorted({an.T[ti].name for ti, fl, o, c in an.items if ti and an.T[ti].name.startswith('hka') and fl == 0x10})
            raise ValueError('not lossless: %s' % kinds)
        self.item = k
        a = self.a = an.item_values(k)[0]
        b = an.item_values(find(an, 'hkaAnimationBinding'))[0]
        self.blendHint = b['blendHint']
        self.t2b = arr(an, b['transformTrackToBoneIndices'])
        self.F = a['numFrames']; self.duration = a['duration']
        self.dT = arr(an, a['dynamicTranslations']); self.sT = arr(an, a['staticTranslations'])
        self.dR = arr(an, a['dynamicRotations'])
        self.sR = arr(an, a['staticRotations'])
        self.tto = arr(an, a['translationTypeAndOffsets']); self.rto = arr(an, a['rotationTypeAndOffsets'])
        self.nT = a['numberOfTransformTracks']
        nd = sum(1 for v in self.tto for c in range(3) if ((v >> (16 * c)) & 3) == 2)
        self.ndT = nd  # dynamic translation components per frame
        self.ndR = sum(1 for v in self.rto if (v & 3) == 2)
        assert self.ndT * self.F == len(self.dT), (self.ndT, self.F, len(self.dT))
        assert self.ndR * self.F == len(self.dR), (self.ndR, self.F, len(self.dR))

    def slot(self, tr, c):
        s = (self.tto[tr] >> (16 * c)) & 0xFFFF
        return s & 3, s >> 2

    def trans(self, tr, f):
        out = []
        for c in range(3):
            ty, off = self.slot(tr, c)
            out.append(0.0 if ty == 0 else self.sT[off] if ty == 1 else self.dT[f * self.ndT + off])
        return out

    def rot(self, tr, f):
        s = self.rto[tr]; ty, off = s & 3, s >> 2
        if ty == 0:
            return [0.0, 0.0, 0.0, 1.0]
        return self.sR[off] if ty == 1 else self.dR[f * self.ndR + off]

    def bone_track(self, bone):
        return self.t2b.index(bone) if self.t2b else bone


def qmul(a, b):
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz]


def qrot(q, v):
    x, y, z, w = q
    qv = [x, y, z]
    t = [2 * (qv[1] * v[2] - qv[2] * v[1]), 2 * (qv[2] * v[0] - qv[0] * v[2]), 2 * (qv[0] * v[1] - qv[1] * v[0])]
    return [v[i] + w * t[i] + (qv[(i + 1) % 3] * t[(i + 2) % 3] - qv[(i + 2) % 3] * t[(i + 1) % 3]) for i in range(3)]


def model_pose(sk, an, f):
    """Root-space (position, rotation) of every bone at frame f."""
    n = len(sk.bones)
    local = [sk.ref[i] for i in range(n)]
    for tr in range(an.nT):
        bi = an.t2b[tr] if an.t2b else tr
        local[bi] = (an.trans(tr, f), an.rot(tr, f))
    world = [None] * n
    for i in range(n):
        t, r = local[i]
        p = sk.parents[i]
        if p < 0:
            world[i] = (t, r)
        else:
            pt, pr = world[p]
            wt = qrot(pr, t)
            world[i] = ([pt[k] + wt[k] for k in range(3)], qmul(pr, r))
    return world


if __name__ == '__main__':
    sk = Skeleton(sys.argv[1])
    for p in sys.argv[2:]:
        an = Anim(p)
        name = os.path.basename(p)
        print('== %s  frames=%d dur=%.2f blend=%s dynT=%d dynR=%d' % (name, an.F, an.duration, an.blendHint, an.ndT, an.ndR))
        moving = [sk.bones[an.t2b[tr] if an.t2b else tr] for tr in range(an.nT)
                  if any(an.slot(tr, c)[0] == 2 for c in range(3)) or (an.rto[tr] & 3) == 2]
        print('   animated bones:', moving)
        for f in (0, an.F // 2):
            w = model_pose(sk, an, f)
            for b in ('COM', 'Camera', 'Weapon', 'RArm_Hand', 'LArm_Hand'):
                i = sk.bones.index(b)
                print('   f%-3d %-10s pos=(%8.3f %8.3f %8.3f)' % (f, b, *w[i][0]))
