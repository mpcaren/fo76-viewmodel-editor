"""Port Gun Mover's FO4 Plasma Gun offsets to FO76 plasmapistol / plasmarifle 1st-person clips (incl. Power Armor).
Writes out_plasma/ (vanilla-based) and out_plasma_lowered/ (Lowered Weapons 76's plasma idles as the base)."""
import sys, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from offset import apply
from lossless import Anim, Skeleton, model_pose
from spline import Spline
from tag0 import Tag

S = os.path.dirname(os.path.abspath(__file__))
V, LOW = os.path.join(S, 'vanilla'), os.path.join(S, 'lowered')
OFFSETS = {  # Gun Mover / First Person FOV Overhaul, Fallout4.esm Plasma Gun 0x100AE9
    'plasmapistol': (8.0, 10.0, -8.0),   # dn_HasGrip_Pistol 0x25018
    'plasmarifle': (8.0, 3.0, -8.0),     # dn_HasGrip_Rifle  0x25019
}
SKIP = ('sighted', 'add.hkx')            # ADS stays aligned; additive layers are deltas
SKEL = {'character': os.path.join(V, 'meshes/actors/character/_1stperson/characterassets/skeleton.hkx'),
        'powerarmor': os.path.join(V, 'meshes/actors/powerarmor/_1stperson/characterassets/skeleton.hkx')}


def verify(skel, a_path, b_path, delta):
    sk = Skeleton(skel)
    com = sk.bones.index('COM')
    try:
        A0, A1 = Anim(a_path), Anim(b_path)
    except ValueError:
        A0 = None
    if A0:
        err = other = 0.0
        for f in range(A0.F):
            for tr in range(A0.nT):
                t0, t1 = A0.trans(tr, f), A1.trans(tr, f)
                r0, r1 = A0.rot(tr, f), A1.rot(tr, f)
                bi = A0.t2b[tr] if A0.t2b else tr
                if bi == com:
                    err = max(err, max(abs(t1[k] - t0[k] - delta[k]) for k in range(3)))
                else:
                    other = max(other, max(abs(t1[k] - t0[k]) for k in range(3)))
                other = max(other, max(abs(r1[k] - r0[k]) for k in range(4)))
        return max(err, other)
    from lossless import arr
    S0, S1 = Spline(a_path), Spline(b_path)
    tr = S0.t2b.index(com)
    err = 0.0
    fbo1 = arr(S1.tg, S1.a['floatBlockOffsets'])
    for bi in range(S0.nB):
        p0, p1 = S0.pos_cp0(bi, tr), S1.pos_cp0(bi, tr)
        err = max(err, max(abs(p1[k] - p0[k] - delta[k]) for k in range(3)))
        b1 = S1.blocks[bi]
        if S1.nB == 1 and b1['tracks_end'] - S1.d0 != fbo1[0]:
            return 99.0   # walk must land exactly on the float block
        for t in range(S0.nT):
            m0, m1 = S0.blocks[bi]['tracks'][t]['mask'], b1['tracks'][t]['mask']
            if t != tr and m0 != m1:
                return 98.0
            if t != tr:
                q0, q1 = S0.pos_cp0(bi, t), S1.pos_cp0(bi, t)
                err = max(err, max(abs(q1[k] - q0[k]) for k in range(3)))
    return err


def build(out_root, use_lowered):
    rows = []
    for actor in ('character', 'powerarmor'):
        for folder, delta in OFFSETS.items():
            base = os.path.join(V, 'meshes/actors', actor, '_1stperson/animations', folder)
            for src in sorted(glob.glob(os.path.join(base, '*.hkx'))):
                name = os.path.basename(src).lower()
                if any(k in name for k in SKIP):
                    continue
                rel = os.path.relpath(src, V).replace('\\', '/')
                low = os.path.join(LOW, rel)
                tag = 'vanilla'
                if use_lowered and os.path.exists(low):
                    src, tag = low, 'lowered'
                dst = os.path.join(out_root, rel)
                try:
                    kind, n = apply(SKEL[actor], src, dst, list(delta))
                except Exception as e:
                    rows.append(('FAIL', rel, tag, repr(e), 0, 0))
                    continue
                Tag(dst)  # must re-parse cleanly
                err = verify(SKEL[actor], src, dst, delta)
                rows.append(('OK' if err < 1e-3 else 'BAD', rel, tag, kind, n, err))
    return rows


if __name__ == '__main__':
    for out, low in (('out_plasma', False), ('out_plasma_lowered', True)):
        rows = build(os.path.join(S, out), low)
        print('=====', out)
        for st, rel, tag, kind, n, err in rows:
            print('%-4s %-70s %-8s %-48s floats=%-4s err=%s' % (st, rel.split('animations/')[0].split('/')[2] + ':' + rel.split('animations/')[1], tag, kind, n, '%.5f' % err if isinstance(err, float) else err))
        print('files', len(rows), 'not OK', sum(r[0] != 'OK' for r in rows))
