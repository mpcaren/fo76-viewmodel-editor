"""Viewmodel editor core: preview scenes (posed 1st-person hands + assembled weapon) and the Weapon Reposition
archive build (per-group COM offsets baked into vanilla clips with _weapon_reposition/tools/offset.py)."""
import sys, os, json, re, math, shutil, time, posixpath

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
# the packaged app passes the game folder and a writable cache folder; in the dev tree both are relative to it
GAME = os.environ.get('VM_GAME') or os.path.abspath(os.path.join(APP, '..', '..'))
DATA = os.path.join(GAME, 'Data')
TOOLS = os.path.join(HERE, 'tools') if os.path.isdir(os.path.join(HERE, 'tools')) \
    else os.path.join(GAME, 'Mods', '_weapon_reposition', 'tools')
CACHE = os.environ.get('VM_CACHE') or os.path.join(APP, 'cache')
EXTRACT = os.path.join(CACHE, 'extract')
os.makedirs(CACHE, exist_ok=True)
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)

from ba2 import Index                                   # noqa: E402
from nif76 import Nif                                   # noqa: E402
from lossless import Anim, Skeleton                     # noqa: E402
from tag0 import Tag                                    # noqa: E402
from offset import apply as apply_offset                # noqa: E402
from run_plasma import verify                           # noqa: E402
from gunmap import FO4, GROUPS, folder_path             # noqa: E402
from weapons import WEAPONS, SKIP_SLOTS, AVOID, PREFER  # noqa: E402
import ba2write                                         # noqa: E402

SKIP_CLIPS = ('sighted', 'add.hkx')     # ADS stays aligned; additive layers are deltas (same rule as run_all.py)
READY_CLIPS = ('wpnidleready.hkx', 'wpnidlereadya.hkx', 'wpnidlereadyb.hkx', 'wpnidlereadyc.hkx', 'wpnidlereadyd.hkx')
SIGHTED_CLIPS = ('wpnidlesighted.hkx',)


# ---------- 4x4 matrices (row-major lists, column vectors) ----------
def mat(R, t, s=1.0):
    return [[R[0][0] * s, R[0][1] * s, R[0][2] * s, t[0]],
            [R[1][0] * s, R[1][1] * s, R[1][2] * s, t[1]],
            [R[2][0] * s, R[2][1] * s, R[2][2] * s, t[2]], [0, 0, 0, 1]]


def mul(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def inv(M):  # rigid (+uniform scale) inverse
    R = [[M[j][i] for j in range(3)] for i in range(3)]
    s2 = sum(R[0][k] ** 2 for k in range(3))
    R = [[R[i][j] / s2 for j in range(3)] for i in range(3)]
    t = [-sum(R[i][k] * M[k][3] for k in range(3)) for i in range(3)]
    return mat(R, t)


def T(R):
    return [[R[j][i] for j in range(3)] for i in range(3)]


def quat_to_R(q):  # q = (x, y, z, w)
    x, y, z, w = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def xf(M, v):
    return [M[i][0] * v[0] + M[i][1] * v[1] + M[i][2] * v[2] + M[i][3] for i in range(3)]


def dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


IDENT = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


# ---------- shared state ----------
_ix = None


def index():
    global _ix
    if _ix is None:
        _ix = Index(DATA, os.path.join(CACHE, 'index.json'))
    return _ix


def read_nif(name):
    return Nif(name, index().read(name))


def group_id(desc):
    return re.sub(r'[^a-z0-9]+', '-', desc.lower()).strip('-')[:60]


def groups():
    out = []
    for folders, src, closest, desc in GROUPS:
        out.append({'id': group_id(desc), 'desc': desc, 'src': src, 'closest': closest, 'folders': folders,
                    'default': list(FO4[src]), 'mesh': WEAPONS.get(desc) is not None})
    return out


def group_by_id(gid):
    for folders, src, closest, desc in GROUPS:
        if group_id(desc) == gid:
            return folders, src, closest, desc
    raise KeyError(gid)


# ---------- weapon part catalog ----------
_catalog = None


def catalog():
    """nif name -> {'P': parent points, 'C': child targets, 'nv'}; every weapon nif, cached."""
    global _catalog
    if _catalog is not None:
        return _catalog
    path = os.path.join(CACHE, 'parts.json')
    ix = index()
    stamp = os.path.getmtime(os.path.join(CACHE, 'index.json'))
    if os.path.exists(path):
        c = json.load(open(path))
        if c.get('stamp') == stamp:
            _catalog = c['parts']
            return _catalog
    rx = re.compile(r'^meshes/(dlc0\d/)?weapons/.*\.nif$')
    parts = {}
    for n in ix.map:
        if not rx.match(n):
            continue
        try:
            nf = read_nif(n)
        except Exception:
            continue
        parts[n] = {'P': [c['name'] for b in nf.blocks if b['type'] == 'BSConnectPoint::Parents' for c in b['cps']],
                    'C': [t for b in nf.blocks if b['type'] == 'BSConnectPoint::Children' for t in b['targets']],
                    'nv': sum(b.get('nv', 0) for b in nf.blocks)}
    json.dump({'stamp': stamp, 'parts': parts}, open(path, 'w'))
    _catalog = parts
    return parts


def hires(name):
    """The _1 variant (more detailed) when the game has one."""
    alt = name[:-4] + '_1.nif'
    return alt if not name.endswith('_1.nif') and alt in catalog() else name


def family_dir(root):
    d = posixpath.dirname(root)
    if posixpath.basename(d) in ('recievers', 'receivers', 'lod'):
        d = posixpath.dirname(d)
    return d + '/'


def slot_candidates(root, slot):
    """Parts in the weapon's folder tree that attach to `slot` (P-X -> child target C-X), canonical (non-_1) names."""
    want = {'c-' + slot[2:].lower()}
    if slot.lower() == 'p-receiver':
        want.add('c-reciever')
    fam = family_dir(root)
    cat = catalog()
    out = []
    for n, v in cat.items():
        if not n.startswith(fam) or 'workshop' in n:
            continue
        if n.endswith('_1.nif') and n[:-6] + '.nif' in cat:
            continue
        if any(c.lower() in want for c in v['C']) and v['nv'] > 0:
            out.append(n)
    return sorted(out)


def default_part(root, slot, cands, prefer):
    want = prefer.get(slot)
    if want == 'zz-none':
        return None
    if want:
        hit = [c for c in cands if want in c]
        if hit:
            return min(hit, key=len)
    rdir = posixpath.dirname(root) + '/'

    def score(c):
        b = posixpath.basename(c)
        s = sum(5 for w in PREFER if w in b) - sum(10 for w in AVOID if w in b)
        s += 3 if posixpath.dirname(c) + '/' == rdir else 0
        return (s, -len(b))
    return max(cands, key=score) if cands else None


def slots_of(name):
    seen = []
    for p in catalog().get(hires(name), catalog().get(name, {'P': []}))['P']:
        if p not in SKIP_SLOTS and p not in seen and not re.search(r'move|pivot|ring|flap|chain|handle|nospin|tesla|mod\d|slide|rotor', p, re.I):
            seen.append(p)
    return seen


def resolve_parts(desc, chosen=None):
    """Walk the connect points from the root: [{'slot', 'options', 'part'}] in attach order, plus the root."""
    spec = WEAPONS.get(desc)
    if not spec:
        return None, []
    chosen = chosen or {}
    prefer = spec.get('prefer', {})
    root = spec['root']
    rows, queue, done = [], [root], set()
    while queue:
        n = queue.pop(0)
        for slot in slots_of(n):
            if slot in done:
                continue
            done.add(slot)
            cands = slot_candidates(root, slot)
            if not cands:
                continue
            part = chosen[slot] if slot in chosen else default_part(root, slot, cands, prefer)
            if part not in cands:
                part = None
            rows.append({'slot': slot, 'options': cands, 'part': part, 'default': default_part(root, slot, cands, prefer)})
            if part:
                queue.append(part)
    return root, rows


# ---------- rig: skeleton + skinned hands ----------
class Rig:
    def __init__(self, actor='character'):
        ix = index()
        base = 'meshes/actors/%s/' % actor
        self.skel_hkx = ix.extract(base + '_1stperson/characterassets/skeleton.hkx', EXTRACT)
        sk = self.sk = Skeleton(self.skel_hkx)
        self.hk_local = [mat(quat_to_R(r), t) for t, r in sk.ref]
        hk_world = []
        for i, p in enumerate(sk.parents):
            hk_world.append(self.hk_local[i] if p < 0 else mul(hk_world[p], self.hk_local[i]))
        skn = read_nif(base + '_1stperson/characterassets/skeleton.nif')
        best = None
        for tr in (False, True):          # pick the nif matrix convention that matches havok
            W = self._nif_worlds(skn, tr)
            common = [b for b in sk.bones if b in W]
            err = max(dist(xf(W[b], [10, 0, 0]), xf(hk_world[sk.bones.index(b)], [10, 0, 0])) for b in common)
            if best is None or err < best[0]:
                best = (err, tr, W)
        self.nif_t, nifW = best[1], best[2]
        parent_of = {}
        for d in skn.blocks:
            for c in d.get('children', []):
                if c >= 0:
                    parent_of[skn.blocks[c].get('name')] = d.get('name')
        self.extra = {}       # nif-only bone -> (parent, local)
        self.extra_order = []

        def ensure(name):
            if name in sk.bones or name in self.extra:
                return
            par = parent_of[name]
            ensure(par)
            self.extra[name] = (par, mul(inv(nifW[par]), nifW[name]))
            self.extra_order.append(name)

        hands_nif = base + ('characterassets/1stpersonmalehands.nif' if actor == 'character'
                            else 'characterassets/1stpersonpowerarmor.nif')
        hands = read_nif(hands_nif)
        self.meshes = []
        for d in hands.blocks:
            if d['type'] not in ('BSTriShape', 'BSSubIndexTriShape') or not d.get('V') or d.get('skin', -1) < 0:
                continue
            inst = hands.blocks[d['skin']]
            bd = hands.blocks[inst['bonedata']]['bones']
            names = [hands.blocks[b]['name'] for b in inst['bones']]
            for nm in names:
                ensure(nm)
            s2b = [mat(self.R(bd[k]['R']), bd[k]['t'], bd[k]['scale']) for k in range(len(names))]
            k0 = names.index('RArm_Hand') if 'RArm_Hand' in names else 0
            D = mul(nifW[names[k0]], s2b[k0])           # mesh space -> skeleton space
            bind = {nm: mul(D, inv(s2b[k])) for k, nm in enumerate(names)}
            self.meshes.append({'name': d['name'], 'V': [xf(D, v) for v in d['V']], 'tris': d['tris'],
                                'J': d['J'], 'W': d['W'], 'names': names, 'bind': bind})

    def R(self, R):
        return T(R) if self.nif_t else R

    @staticmethod
    def _nif_worlds(n, transpose):
        W = {}

        def walk(i, parent):
            d = n.blocks[i]
            R = T(d['R']) if transpose else d['R']
            M = mat(R, d['t'], d['scale'])
            Wm = M if parent is None else mul(parent, M)
            W[d['name']] = Wm
            for c in d.get('children', []):
                if c >= 0 and 'R' in n.blocks[c]:
                    walk(c, Wm)
        walk(0, None)
        return W

    def pose(self, clip_path, frame=0):
        """World matrix of every bone (havok + nif-only) at a clip frame."""
        sk = self.sk
        local = list(self.hk_local)
        an = Anim(clip_path)
        for tr in range(an.nT):
            bi = an.t2b[tr] if an.t2b else tr
            local[bi] = mat(quat_to_R(an.rot(tr, frame)), an.trans(tr, frame))
        W = {}
        for i, p in enumerate(sk.parents):
            W[sk.bones[i]] = local[i] if p < 0 else mul(W[sk.bones[p]], local[i])
        for n in self.extra_order:
            par, L = self.extra[n]
            W[n] = mul(W[par], L)
        return W

    def skinned(self, W):
        out = []
        for m in self.meshes:
            S = {nm: mul(W[nm], inv(B)) for nm, B in m['bind'].items()}
            Sl = [S[nm] for nm in m['names']]
            pos = []
            for v, J, Wt in zip(m['V'], m['J'], m['W']):
                acc = [0.0, 0.0, 0.0]
                tw = 0.0
                for j, w in zip(J, Wt):
                    if w <= 0:
                        continue
                    p = xf(Sl[j], v)
                    acc[0] += w * p[0]; acc[1] += w * p[1]; acc[2] += w * p[2]
                    tw += w
                if tw > 0:
                    acc = [a / tw for a in acc]
                pos += [round(acc[0], 3), round(acc[1], 3), round(acc[2], 3)]
            out.append(pos)
        return out


_rigs = {}


def rig(actor='character'):
    if actor not in _rigs:
        _rigs[actor] = Rig(actor)
    return _rigs[actor]


# ---------- weapon assembly ----------
def weapon_meshes(root, rows):
    """Meshes of the assembled weapon in Weapon-bone space: [{'name', 'pos', 'idx', 'part'}]."""
    chosen = {r['slot']: r['part'] for r in rows if r['part']}
    r = rig()
    cps = {}
    meshes = []

    def attach(name, base):
        nf = read_nif(hires(name))
        Wn = {}

        def walk(i, parent):
            d = nf.blocks[i]
            Wm = mul(parent, mat(r.R(d['R']), d['t'], d['scale']))
            Wn[i] = Wm
            for c in d.get('children', []):
                if c >= 0 and 'R' in nf.blocks[c]:
                    walk(c, Wm)
        walk(0, base)
        byname = {nf.blocks[i].get('name'): M for i, M in Wn.items()}
        mine = []
        for d in nf.blocks:
            if d['type'] == 'BSConnectPoint::Parents':
                for c in d['cps']:
                    pm = byname.get(c['parent'], base) if c['parent'] else base
                    q = c['q']                                    # stored w, x, y, z
                    M = mul(pm, mat(quat_to_R((q[1], q[2], q[3], q[0])), c['t'], c['scale']))
                    if c['name'] not in cps:
                        cps[c['name']] = M
                        mine.append(c['name'])
        for i, M in Wn.items():
            d = nf.blocks[i]
            if d['type'] in ('BSTriShape', 'BSSubIndexTriShape') and d.get('V'):
                pos = []
                for v in d['V']:
                    p = xf(M, v)
                    pos += [round(p[0], 3), round(p[1], 3), round(p[2], 3)]
                meshes.append({'name': '%s/%s' % (posixpath.basename(name), d['name']), 'part': name,
                               'pos': pos, 'idx': [k for t in d['tris'] for k in t]})
        for slot in mine:
            if slot in chosen:
                attach(chosen[slot], cps[slot])

    attach(root, IDENT)
    return meshes


# ---------- preview scene ----------
def find_clip(folders, names):
    ix = index()
    for f in folders:
        if f.startswith('powerarmor'):
            continue
        for c in names:
            n = folder_path(f) + '/' + c
            if ix.has(n):
                try:
                    p = ix.extract(n, EXTRACT)
                    Anim(p)
                    return p, n
                except ValueError:
                    continue
    return None, None


def scene(gid, chosen=None):
    folders, src, closest, desc = group_by_id(gid)
    r = rig()
    ready, ready_name = find_clip(folders, READY_CLIPS)
    if ready is None:
        raise RuntimeError('no readable idle clip for ' + desc)
    sighted, sighted_name = find_clip(folders, SIGHTED_CLIPS)
    poses = {'ready': r.pose(ready)}
    if sighted:
        poses['sighted'] = r.pose(sighted)
    root, rows = resolve_parts(desc, chosen)
    out = {'id': gid, 'desc': desc, 'clips': {'ready': ready_name, 'sighted': sighted_name},
           'hands': [], 'weapon': [], 'pose': {}, 'parts': rows, 'root': root}
    skinned = {k: r.skinned(W) for k, W in poses.items()}
    for i, m in enumerate(r.meshes):
        out['hands'].append({'name': m['name'], 'idx': [k for t in m['tris'] for k in t],
                             'pos': {k: skinned[k][i] for k in poses}})
    for k, W in poses.items():
        out['pose'][k] = {'weapon': W['Weapon'], 'camera': [W['Camera'][i][3] for i in range(3)],
                          'com': [W['COM'][i][3] for i in range(3)]}
    if root:
        out['weapon'] = weapon_meshes(root, rows)
    return out


PIPBOY_CLIP = 'meshes/actors/character/_1stperson/animations/pipboy2000/pipboyidle.hkx'
PIPBOY_NIF = 'meshes/pipboy2000/characterassets/pipboy2000.nif'   # static (unskinned) version, PipboyBone space
PIPBOY_SKIP = ('glow', 'stealthboy', 'vactubeglass')                # effect cards


def pipboy_scene():
    """Hands in the Pip-Boy idle pose + the Pip-Boy on PipboyBone, in the same shape as scene() (one pose, 'pipboy').
    The game draws it with the viewmodel FOV (fDefault1stPersonFOV); weapon offsets don't touch these clips."""
    r = rig()
    W = r.pose(index().extract(PIPBOY_CLIP, EXTRACT))
    sk = r.skinned(W)
    out = {'id': 'pipboy', 'desc': 'Pip-Boy', 'clips': {'pipboy': PIPBOY_CLIP}, 'hands': [], 'parts': [], 'root': PIPBOY_NIF,
           'pose': {'pipboy': {'weapon': W['PipboyBone'], 'camera': [W['Camera'][i][3] for i in range(3)],
                               'com': [W['COM'][i][3] for i in range(3)]}}}
    for i, m in enumerate(r.meshes):
        out['hands'].append({'name': m['name'], 'idx': [k for t in m['tris'] for k in t], 'pos': {'pipboy': sk[i]}})
    out['weapon'] = [m for m in weapon_meshes(PIPBOY_NIF, [])
                     if not any(s in m['name'].lower() for s in PIPBOY_SKIP)]
    return out


# ---------- archive build ----------
def clip_names(folder):
    """Modifiable clips directly in an animation folder (not its subfolders), as run_all.py picks them."""
    pre = folder_path(folder) + '/'
    out = []
    for n in index().names(pre):
        rest = n[len(pre):]
        if '/' in rest or not rest.endswith('.hkx'):
            continue
        if any(k in rest for k in SKIP_CLIPS):
            continue
        out.append(n)
    return out


def build(offsets, out_path, progress=None):
    """offsets: {group desc: [x, y, z]}; groups at 0,0,0 are left out (vanilla). Writes a v1 GNRL ba2 to out_path."""
    ix = index()
    vanilla = os.path.join(CACHE, 'vanilla')
    stage = os.path.join(CACHE, 'stage')
    if os.path.exists(stage):
        shutil.rmtree(stage)
    skel = {a: ix.extract('meshes/actors/%s/_1stperson/characterassets/skeleton.hkx' % a, EXTRACT)
            for a in ('character', 'powerarmor')}
    jobs = []
    for folders, src, closest, desc in GROUPS:
        d = offsets.get(desc)
        if not d or not any(abs(x) > 1e-9 for x in d):
            continue
        for f in folders:
            for n in clip_names(f):
                jobs.append((n, 'powerarmor' if f.startswith('powerarmor') else 'character', [float(x) for x in d], desc))
    rows = []
    t0 = time.time()
    for k, (n, actor, delta, desc) in enumerate(jobs):
        src = ix.extract(n, vanilla)
        dst = os.path.join(stage, n)
        try:
            kind, cnt = apply_offset(skel[actor], src, dst, delta)
            Tag(dst)
            err = verify(skel[actor], src, dst, delta)
            rows.append({'clip': n, 'ok': err < 1e-3, 'err': err, 'kind': kind, 'group': desc})
        except Exception as e:
            rows.append({'clip': n, 'ok': False, 'err': -1, 'kind': repr(e)[:200], 'group': desc})
        if progress and (k % 10 == 0 or k == len(jobs) - 1):
            progress({'done': k + 1, 'total': len(jobs), 'elapsed': round(time.time() - t0, 1)})
    bad = [r for r in rows if not r['ok']]
    if bad:
        return {'ok': False, 'clips': len(rows), 'bad': bad[:20], 'nbad': len(bad)}
    tmp = out_path + '.building'
    names = ba2write.write(tmp, stage) if rows else []
    if not rows:
        return {'ok': True, 'clips': 0, 'empty': True}
    os.replace(tmp, out_path)
    return {'ok': True, 'clips': len(names), 'groups': len({r['group'] for r in rows}),
            'inserted': sum(1 for r in rows if 'added static' in r['kind']), 'seconds': round(time.time() - t0, 1)}
