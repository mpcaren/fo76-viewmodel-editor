"""offset.py <skeleton.hkx> <in.hkx> <out.hkx> dx dy dz [bone]
Shift a bone's translation (default COM) by (dx,dy,dz) in its parent space, in place (same file size).
Works on hkaLosslessCompressedAnimation and hkaSplineCompressedAnimation. Fails if a component is 'zero'."""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tag0 import Tag
from lossless import Anim, Skeleton, find
from spline import Spline


def patch_offsets(path, bone_index):
    """List of (abs_offset, component) floats that must all get +delta[component]."""
    tg = Tag(path)
    if find(tg, 'hkaLosslessCompressedAnimation') is not None:
        an = Anim(path)
        tr = an.bone_track(bone_index)
        a = an.a
        dT_off = tg.data0 + tg.items[a['dynamicTranslations'][1]][2] if a['dynamicTranslations'][1] else None
        sT_off = tg.data0 + tg.items[a['staticTranslations'][1]][2] if a['staticTranslations'][1] else None
        out = []
        for c in range(3):
            ty, off = an.slot(tr, c)
            if ty == 0:
                raise ValueError('%s: component %d is zero (needs restructuring)' % (path, c))
            if ty == 1:
                out.append((sT_off + 4 * off, c))
            else:
                out += [(dT_off + 4 * (f * an.ndT + off), c) for f in range(an.F)]
        return 'lossless', out
    s = Spline(path)
    tr = s.t2b.index(bone_index) if s.t2b else bone_index
    out = []
    for bi, blk in enumerate(s.blocks):
        for c, e in enumerate(blk['tracks'][tr]['pos']['comp']):
            if e[0] == 'zero':
                raise ValueError('%s block %d: component %d is zero (needs restructuring)' % (path, bi, c))
            if e[0] == 'static':
                out.append((e[1], c))
            else:
                out += [(e[1], c), (e[2], c)]  # min, max
    return 'spline', out


def grow_item(path, k, extra):
    """Append `extra` bytes (zeros) to item k's data; returns new file bytes. Uses the item's padding when
    possible, otherwise inserts a 16-aligned gap and fixes ITEM/PTCH offsets and section sizes."""
    tg = Tag(path)
    b = bytearray(tg.b)
    ti, fl, off, cnt = tg.items[k]
    es = tg.tsize(tg.T[ti])
    assert extra % es == 0
    end = off + cnt * es
    nxt = min([o for (t2, f2, o, c2) in tg.items if t2 and o > off] + [tg.data1 - tg.data0])
    item_pos = tg.S['ITEM'][0] + 12 * k
    if nxt - end >= extra and not any(b[tg.data0 + end:tg.data0 + end + extra]):
        struct.pack_into('<I', b, item_pos + 8, cnt + extra // es)
        return bytes(b), 'padding'
    ins = (extra + 15) // 16 * 16
    pos = tg.data0 + end
    # section headers: TAG0 (outer) and DATA grow by ins
    def bump(sec_hdr_pos):
        h = struct.unpack_from('>I', b, sec_hdr_pos)[0]
        struct.pack_into('>I', b, sec_hdr_pos, (h & 0xC0000000) | ((h & 0x3FFFFFFF) + ins))
    bump(0)
    bump(tg.data0 - 8)
    for j, (t2, f2, o, c2) in enumerate(tg.items):
        p = tg.S['ITEM'][0] + 12 * j
        if j == k:
            struct.pack_into('<I', b, p + 8, cnt + extra // es)
        elif t2 and o >= end:
            struct.pack_into('<I', b, p + 4, o + ins)
    s, e = tg.S['PTCH']
    r = s
    while r < e:
        t, n = struct.unpack_from('<II', b, r); r += 8
        for q in range(n):
            o = struct.unpack_from('<I', b, r + 4 * q)[0]
            if o >= end:
                struct.pack_into('<I', b, r + 4 * q, o + ins)
        r += 4 * n
    b[pos:pos] = bytes(ins)
    return bytes(b), 'insert %d' % ins


def materialize_zero(path, bone_index, delta):
    """Lossless only: turn 'zero' translation components of the bone (with a non-zero delta) into static 0.0
    entries so they can be offset. Returns new bytes or None if nothing to do."""
    an = Anim(path)
    tr = an.bone_track(bone_index)
    zeros = [c for c in range(3) if an.slot(tr, c)[0] == 0 and delta[c] != 0]
    if not zeros:
        return None
    a = an.a
    k_sT = a['staticTranslations'][1]
    if not k_sT:
        raise ValueError('%s: no staticTranslations array to extend' % path)
    first = an.tg.items[k_sT][3]
    data, how = grow_item(path, k_sT, 4 * len(zeros))
    tmp = path + '.tmp'
    open(tmp, 'wb').write(data)
    tg = Tag(tmp)
    k_tto = a['translationTypeAndOffsets'][1]
    tto_abs = tg.data0 + tg.items[k_tto][2] + 8 * tr
    v = struct.unpack_from('<Q', data, tto_abs)[0]
    for n, c in enumerate(zeros):
        v |= (((first + n) << 2) | 1) << (16 * c)
    data = bytearray(data)
    struct.pack_into('<Q', data, tto_abs, v)
    os.remove(tmp)
    return bytes(data), how, zeros


def materialize_zero_spline(path, bone_index, delta):
    """Spline, single block: turn 'zero' position components of the bone into static 0.0 floats."""
    s = Spline(path)
    tr = s.t2b.index(bone_index) if s.t2b else bone_index
    if s.nB != 1:
        if any(e[0] == 'zero' for blk in s.blocks for c, e in enumerate(blk['tracks'][tr]['pos']['comp']) if delta[c]):
            raise ValueError('%s: zero component in a multi-block spline (unsupported)' % path)
        return None
    comps = s.blocks[0]['tracks'][tr]['pos']['comp']
    zeros = [c for c, e in enumerate(comps) if e[0] == 'zero' and delta[c] != 0]
    if not zeros:
        return None
    from lossless import arr
    fbo = arr(s.tg, s.a['floatBlockOffsets'])[0]
    dlen = s.dlen
    assert dlen == (fbo + 15) // 16 * 16, (fbo, dlen)
    add = 4 * len(zeros)
    new_fbo = fbo + add
    new_dlen = (new_fbo + 15) // 16 * 16
    k_data = s.a['data'][1]
    data = s.tg.b
    if new_dlen > dlen:
        data, _ = grow_item(path, k_data, new_dlen - dlen)
    tmp = path + '.tmp'
    open(tmp, 'wb').write(data)
    s2 = Spline(tmp)          # same layout, maybe moved/grown item
    base = s2.d0
    comps = s2.blocks[0]['tracks'][tr]['pos']['comp']
    # insertion point = first stored entry after the zero comps, else end of the per-component floats
    stored = [e for e in comps if e[0] != 'zero']
    v = s2.blocks[0]['tracks'][tr]['pos']
    if v.get('cps') is not None and 'n' in v:
        after = v['cps']
    else:
        last = stored[-1] if stored else None
        after = (last[2] + 4 if last and last[0] == 'spline' else last[1] + 4) if last else None
    b = bytearray(data)
    blob = bytearray(b[base:base + fbo])
    # every zero comp precedes some stored comp or is appended at the end, in x,y,z order
    ins_list = []
    for c in zeros:
        later = [e for cc, e in enumerate(comps) if cc > c and e[0] != 'zero']
        at = later[0][1] if later else after
        if at is None:
            raise ValueError('%s: COM has no position data at all' % path)
        ins_list.append(at - base)
    for n, at in enumerate(sorted(ins_list)):
        blob[at + 4 * n:at + 4 * n] = struct.pack('<f', 0.0)
    blob += bytes(new_dlen - len(blob))
    b[base:base + new_dlen] = blob
    # mask: positionTypes static bits
    mask_pos = base + 4 * tr + 1
    for c in zeros:
        b[mask_pos] |= (1 << c)
    # floatBlockOffsets[0]
    tg2 = s2.tg
    fbo_abs = tg2.data0 + tg2.items[s2.a['floatBlockOffsets'][1]][2]
    struct.pack_into('<I', b, fbo_abs, new_fbo)
    os.remove(tmp)
    return bytes(b), 'spline insert', zeros


def apply(skel, src, dst, delta, bone='COM'):
    sk = Skeleton(skel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    note = ''
    lossless = find(Tag(src), 'hkaLosslessCompressedAnimation') is not None
    m = (materialize_zero if lossless else materialize_zero_spline)(src, sk.bones.index(bone), delta)
    if True:
        if m:
            data, how, zeros = m
            open(dst, 'wb').write(data)
            src = dst
            note = ' (added static for comps %s via %s)' % (zeros, how)
    kind, offs = patch_offsets(src, sk.bones.index(bone))
    b = bytearray(open(src, 'rb').read())
    for o, c in offs:
        v = struct.unpack_from('<f', b, o)[0]
        struct.pack_into('<f', b, o, v + delta[c])
    open(dst, 'wb').write(b)
    return kind + note, len(offs)


if __name__ == '__main__':
    skel, src, dst = sys.argv[1:4]
    d = [float(x) for x in sys.argv[4:7]]
    bone = sys.argv[7] if len(sys.argv) > 7 else 'COM'
    print(apply(skel, src, dst, d, bone))
