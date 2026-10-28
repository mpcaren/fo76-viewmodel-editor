// FO76 Viewmodel Editor - renderer: weapon list, 3D preview (world + viewmodel passes), offset + ini editors.
import * as THREE from '../node_modules/three/build/three.module.js';

THREE.Object3D.DEFAULT_UP.set(0, 0, 1);          // game space: X right, Y forward, Z up
const $ = (s) => document.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null) e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
};
const fmt = (v) => (Math.round(v * 100) / 100).toString();
const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) < 1e-6);
const isZero = (a) => !a || a.every((v) => Math.abs(v) < 1e-9);

// ------------------------------------------------------------------ ini settings (what Quick Configuration exposes)
// FOV ranges are the game's own: the in-game FOV slider runs 70-120 (Quick Configuration's sliders use the same range).
// There is no Pip-Boy FOV: Fallout76.exe has no fPipboy1stFOV setting (checked 2026-10-27); the Pip-Boy uses the viewmodel FOV.
const SETTINGS = [
  { title: 'Field of view', items: [
    { section: 'Display', key: 'fDefault1stPersonFOV', label: 'Viewmodel FOV', def: 80, min: 70, max: 120, step: 1, role: 'viewmodel',
      help: 'Your hands, gun and Pip-Boy (use the Pip-Boy view above to see it). Also changes how far aiming down sights zooms. Game default 80.' },
    { section: 'Display', key: 'fDefaultWorldFOV', label: 'World FOV', def: 80, min: 70, max: 120, step: 1, role: 'world',
      help: 'The in-game FOV slider value. Quick Configuration writes it to Prefs.ini; this app writes Custom.ini because the game rewrites Prefs.ini from its menu on every exit.' },
    { section: 'Camera', key: 'fFPWorldFOV', label: '1st-person world FOV [Camera]', def: null, min: 70, max: 120, step: 1, removeOnReset: true,
      help: 'Newer camera key the game also reads. Keep it equal to World FOV. Reset removes the line (game default).' },
    { section: 'Camera', key: 'fTPWorldFOV', label: '3rd-person world FOV [Camera]', def: null, min: 70, max: 120, step: 1, removeOnReset: true,
      help: 'Third-person camera FOV. Reset removes the line (game default).' },
    { section: 'Camera', key: 'f3rdPersonAimFOV', label: '3rd-person aim FOV', def: 50, min: 20, max: 120, step: 1, removeOnReset: true,
      help: 'FOV when aiming in third person. Default 50. Reset removes the line.' },
  ] },
  { title: '3rd-person camera position (experimental)', items: [
    ['fOverShoulderPosX', 'Over shoulder X (left/right)'], ['fOverShoulderPosZ', 'Over shoulder Z (up/down)'],
    ['fOverShoulderCombatPosX', 'Combat X'], ['fOverShoulderCombatPosZ', 'Combat Z'], ['fOverShoulderCombatAddY', 'Combat Y (distance)'],
    ['fOverShoulderMeleeCombatPosX', 'Melee combat X'], ['fOverShoulderMeleeCombatPosZ', 'Melee combat Z'],
    ['fOverShoulderMeleeCombatAddY', 'Melee combat Y (distance)'],
  ].map(([key, label]) => ({ section: 'Camera', key, label, def: null, min: -100, max: 100, step: 1, removeOnReset: true,
    help: 'Same tweak as Quick Configuration\'s camera position page. Reset removes the line (game default).' })) },
  { title: 'Camera behaviour', items: [
    { section: 'Camera', key: 'bApplyCameraNodeAnimations', label: 'Shoulder camera node', type: 'bool', def: true, removeOnReset: true,
      help: 'Off puts the 3rd-person camera inside the head (zoom out to use it). Quick Configuration marks it "might cause issues if disabled".' },
  ] },
];
const ALL_SETTINGS = SETTINGS.flatMap((g) => g.items);
const sid = (s) => s.section + '/' + s.key;

// ------------------------------------------------------------------ state
let groups = [];
let state = {};
let ini = { values: {}, pending: {} };
let current = null;          // scene of the selected group
let pose = 'ready';
const sceneCache = new Map();

const byId = (id) => groups.find((g) => g.id === id);
const offsetOf = (g) => state.offsets[g.desc] || [0, 0, 0];
const shortName = (d) => d.replace(/\s*\((shared clips|.*borrows.*)\)\s*$/i, '');

let saveTimer = null;
let testMode = false;
function saveSoon() {
  clearTimeout(saveTimer);
  if (testMode) return;
  saveTimer = setTimeout(() => window.vm.saveState(state), 300);
}

// ------------------------------------------------------------------ three.js
const canvas = $('#canvas');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.autoClear = false;
renderer.setClearColor(0x1a1c1f, 1);
renderer.setPixelRatio(window.devicePixelRatio);
renderer.outputColorSpace = THREE.SRGBColorSpace;

const worldScene = new THREE.Scene();
worldScene.background = new THREE.Color(0x9fb2c2);
worldScene.fog = new THREE.Fog(0x9fb2c2, 3000, 22000);
worldScene.add(new THREE.HemisphereLight(0xe6eef5, 0x4a4535, 1.6));
const sun = new THREE.DirectionalLight(0xfff2dd, 1.4);
sun.position.set(-2000, 1500, 4000);
worldScene.add(sun);
{
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(60000, 60000), new THREE.MeshLambertMaterial({ color: 0x6d6c56 }));
  worldScene.add(ground);
  const grid = new THREE.GridHelper(20000, 100, 0x4d4c3c, 0x5c5b48);
  grid.rotation.x = Math.PI / 2;
  grid.position.z = 0.5;
  worldScene.add(grid);
  const mat = new THREE.MeshLambertMaterial({ color: 0x8b7f6a });
  const dark = new THREE.MeshLambertMaterial({ color: 0x5a5a5e });
  const box = (x, y, w, d, h, m = mat) => {
    const b = new THREE.Mesh(new THREE.BoxGeometry(w, d, h), m);
    b.position.set(x, y, h / 2);
    worldScene.add(b);
  };
  // a target straight ahead and some buildings/posts to judge the world FOV by
  box(0, 1500, 120, 10, 180, dark);
  const tgt = new THREE.Mesh(new THREE.CircleGeometry(40, 32), new THREE.MeshBasicMaterial({ color: 0xd04a3a }));
  tgt.rotation.x = Math.PI / 2;
  tgt.position.set(0, 1494, 120);
  worldScene.add(tgt);
  for (let i = -6; i <= 6; i++) if (i) box(i * 260, 900, 20, 20, 260, dark);
  [[-2600, 4200, 900, 700, 800], [2300, 3900, 1100, 800, 1100], [-900, 7000, 1400, 900, 1500], [4200, 6500, 800, 800, 600],
   [-5200, 2500, 900, 1200, 700], [5400, 2200, 700, 900, 900]].forEach(([x, y, w, d, h]) => box(x, y, w, d, h));
}

const vmScene = new THREE.Scene();
vmScene.add(new THREE.HemisphereLight(0xe8eef4, 0x3b342a, 1.5));
const key = new THREE.DirectionalLight(0xffffff, 1.6);
key.position.set(-40, -30, 160);
vmScene.add(key);
const rim = new THREE.DirectionalLight(0xbcd2ff, 0.6);
rim.position.set(60, 80, 120);
vmScene.add(rim);

const vmRoot = new THREE.Group();          // moved by the offset (COM shift moves arms + gun together)
const ghostRoot = new THREE.Group();       // vanilla position
const pipRoot = new THREE.Group();         // Pip-Boy view (its clips aren't moved by weapon offsets)
pipRoot.visible = false;
vmScene.add(vmRoot, ghostRoot, pipRoot);

const MAT = {
  skin: new THREE.MeshStandardMaterial({ color: 0xb98c6e, roughness: 0.75, metalness: 0, side: THREE.DoubleSide }),
  metal: new THREE.MeshStandardMaterial({ color: 0x45484d, roughness: 0.45, metalness: 0.55, side: THREE.DoubleSide }),
  part: new THREE.MeshStandardMaterial({ color: 0x55585e, roughness: 0.5, metalness: 0.45, side: THREE.DoubleSide }),
  wood: new THREE.MeshStandardMaterial({ color: 0x6b4a30, roughness: 0.7, metalness: 0.05, side: THREE.DoubleSide }),
  ghost: new THREE.MeshBasicMaterial({ color: 0x9fd0ff, transparent: true, opacity: 0.025, depthWrite: false, side: THREE.DoubleSide }),
  ghostEdge: new THREE.LineBasicMaterial({ color: 0xa8d8ff, transparent: true, opacity: 0.11, depthWrite: false }),
  pipboy: new THREE.MeshStandardMaterial({ color: 0x55553f, roughness: 0.6, metalness: 0.3, side: THREE.DoubleSide }),
  // the screen sits just behind the case's glass, so it is drawn over it
  screen: new THREE.MeshBasicMaterial({ color: 0x1f9e55, side: THREE.DoubleSide, depthTest: false }),
};

const worldCam = new THREE.PerspectiveCamera(60, 16 / 9, 5, 60000);
const vmCam = new THREE.PerspectiveCamera(60, 16 / 9, 0.5, 2000);
const inspectCam = new THREE.PerspectiveCamera(40, 16 / 9, 0.5, 5000);
let inspect = null;          // {yaw, pitch, dist, target} when the user drags the view

function hFovToVertical(h, aspect) {
  // The ini FOV is the horizontal FOV of a 16:9 screen (matched against 16:9 game screenshots at viewmodel FOV 120,
  // 2026-10-26: a 4:3 base was clearly off). Other aspect ratios are assumed to keep the vertical FOV (Hor+).
  const mode = state.fovMode || 'hor169';
  const base = mode === 'hor43' ? 4 / 3 : mode === 'horizontal' ? aspect : 16 / 9;
  return THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(h) / 2) / base));
}

function fovValue(role) {
  const s = ALL_SETTINGS.find((x) => x.role === role);
  const v = effective(s);
  return Number.isFinite(v) ? v : s.def;
}

function geometry(pos, idx) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx.length > 65535 * 3 ? new THREE.Uint32BufferAttribute(idx, 1) : new THREE.Uint32BufferAttribute(idx, 1));
  g.computeVertexNormals();
  g.computeBoundingSphere();
  return g;
}

function rowMajor(m) {
  const M = new THREE.Matrix4();
  M.set(m[0][0], m[0][1], m[0][2], m[0][3], m[1][0], m[1][1], m[1][2], m[1][3],
    m[2][0], m[2][1], m[2][2], m[2][3], m[3][0], m[3][1], m[3][2], m[3][3]);
  return M;
}

function partMaterial(name, mesh = '') {
  if (/pipboy2000\.nif\/screen/i.test(mesh)) return MAT.screen;
  if (/pipboy/i.test(name)) return MAT.pipboy;
  if (/stock|grip|wood/i.test(name)) return MAT.wood;
  return MAT.metal;
}

function clearGroup(g) {
  for (const c of [...g.children]) {
    g.remove(c);
    c.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
  }
}

function buildMeshes(sc, liveRoot = vmRoot, ghostTo = ghostRoot) {
  clearGroup(liveRoot);
  if (ghostTo) clearGroup(ghostTo);
  sc._hands = {};
  for (const p of Object.keys(sc.pose)) {
    sc._hands[p] = sc.hands.map((h) => geometry(h.pos[p], h.idx));
  }
  sc._weaponGeo = sc.weapon.map((w) => geometry(w.pos, w.idx));
  const make = (root, ghost) => {
    const hands = new THREE.Group();
    Object.values(sc._hands)[0].forEach((g) => hands.add(new THREE.Mesh(g, ghost ? MAT.ghost : MAT.skin)));
    const weapon = new THREE.Group();
    weapon.matrixAutoUpdate = false;
    sc._weaponGeo.forEach((g, i) => {
      const m = new THREE.Mesh(g, ghost ? MAT.ghost : partMaterial(sc.weapon[i].part, sc.weapon[i].name));
      weapon.add(m);
      if (ghost) weapon.add(new THREE.LineSegments(new THREE.EdgesGeometry(g, 60), MAT.ghostEdge));
    });
    root.add(hands, weapon);
    return { hands, weapon };
  };
  sc._live = make(liveRoot, false);
  sc._ghost = ghostTo ? make(ghostTo, true) : null;
}

let pip = null;              // Pip-Boy scene, loaded the first time the Pip-Boy view is picked
async function setPose(p) {
  const changed = pose !== p;
  pose = p;
  document.querySelectorAll('#pose-seg button').forEach((x) => x.classList.toggle('on', x.dataset.pose === p));
  syncIndicator($('#pose-seg'), '.seg-ind');
  if (p === 'pipboy' && !pip) {
    $('#loading').classList.remove('hidden');
    try {
      pip = await window.vm.backend('scene', { id: 'pipboy' });
      buildMeshes(pip, pipRoot, null);
    } catch (e) {
      showModal('Could not load the Pip-Boy', String(e.message || e), [['OK', hideModal]]);
    } finally {
      $('#loading').classList.add('hidden');
    }
  }
  inspect = null;
  applyPose();
  if (changed) pulseView();
}

function placeCameras(camera, target) {
  const cam = [...camera];
  if (window.__camOffset) window.__camOffset.forEach((v, i) => { cam[i] += v; });
  for (const c of [worldCam, vmCam]) {
    c.position.set(cam[0], cam[1], cam[2]);
    c.up.set(0, 0, 1);
    if (target) c.lookAt(target);
    else c.lookAt(cam[0], cam[1] + 100, cam[2]);
  }
}

// The open Pip-Boy is drawn centred and much closer than the Camera bone of the idle clip: Quick Configuration's
// in-game shots (viewmodel FOV 70-120) show it centred at every FOV and ~3x larger than from the Camera bone.
// So the camera looks straight at the screen (the Pip-Boy's -Z axis faces out of it), PIP_DIST units away
// (fitted to those shots).
let PIP_DIST = 16.5;
let PIP_SIGN = -1;
function pipCamera() {
  pip._live.weapon.updateMatrixWorld(true);
  const target = new THREE.Box3().setFromObject(pip._live.weapon).getCenter(new THREE.Vector3());
  const out = new THREE.Vector3().setFromMatrixColumn(pip._live.weapon.matrixWorld, 2).normalize().multiplyScalar(PIP_SIGN);
  return { pos: target.clone().addScaledVector(out, PIP_DIST).toArray(), target };
}

function applyPose() {
  const pipView = pose === 'pipboy' && !!pip;
  pipRoot.visible = pipView;
  vmRoot.visible = !pipView;
  $('.crosshair').classList.toggle('hidden', pipView);
  if (pipView) {
    ghostRoot.visible = false;
    pip._live.weapon.matrix.copy(rowMajor(pip.pose.pipboy.weapon));
    pip._live.weapon.matrixWorldNeedsUpdate = true;
    const pc = pipCamera();
    placeCameras(pc.pos, pc.target);
    renderHud();
    draw();
    return;
  }
  if (!current || !current._live) return;
  const p = current.pose[pose] ? pose : 'ready';
  for (const view of [current._live, current._ghost]) {
    view.hands.children.forEach((m, i) => { m.geometry = current._hands[p][i]; });
    view.weapon.matrix.copy(rowMajor(current.pose[p].weapon));
    view.weapon.matrixWorldNeedsUpdate = true;
  }
  const g = byId(current.id);
  const off = offsetOf(g);
  // sighted clips are never modified, so ADS shows the vanilla aim
  vmRoot.position.set(...(p === 'ready' ? off : [0, 0, 0]));
  ghostRoot.visible = $('#ghost').checked && p === 'ready' && !isZero(off);
  placeCameras(current.pose[p].camera);
  renderHud();
  draw();
}

function resize() {
  const stage = $('#stage');
  const aspect = parseFloat($('#aspect').value);
  const W = stage.clientWidth - 28, H = stage.clientHeight - 28;
  let w = W, h = W / aspect;
  if (h > H) { h = H; w = H * aspect; }
  const vp = $('#viewport');
  vp.style.width = Math.floor(w) + 'px';
  vp.style.height = Math.floor(h) + 'px';
  renderer.setSize(Math.floor(w), Math.floor(h), false);
  for (const c of [worldCam, vmCam, inspectCam]) { c.aspect = aspect; c.updateProjectionMatrix(); }
  draw();
}

function draw() {
  const aspect = parseFloat($('#aspect').value);
  renderer.clear();
  if (inspect) {
    const t = inspect.target;
    const cp = Math.cos(inspect.pitch);
    inspectCam.position.set(t.x + inspect.dist * cp * Math.sin(inspect.yaw), t.y - inspect.dist * cp * Math.cos(inspect.yaw),
      t.z + inspect.dist * Math.sin(inspect.pitch));
    inspectCam.up.set(0, 0, 1);
    inspectCam.lookAt(t);
    renderer.render(vmScene, inspectCam);
    return;
  }
  if ($('#world').checked) {
    worldCam.fov = hFovToVertical(fovValue('world'), aspect);
    worldCam.updateProjectionMatrix();
    renderer.render(worldScene, worldCam);
    renderer.clearDepth();
  }
  vmCam.fov = hFovToVertical(fovValue('viewmodel'), aspect);
  vmCam.updateProjectionMatrix();
  renderer.render(vmScene, vmCam);
}

function renderHud() {
  if (!current) return;
  const off = offsetOf(byId(current.id));
  const bits = [
    'Viewmodel FOV ' + fmt(fovValue('viewmodel')),
    'World FOV ' + fmt(fovValue('world')),
    pose === 'pipboy' ? 'Pip-Boy (drawn with the viewmodel FOV)' : pose === 'ready' ? 'Offset ' + off.map(fmt).join(', ') : 'ADS (not changed by offsets)',
  ];
  if (inspect) bits.push('Free view: double-click for the game view');
  $('#hud').textContent = bits.join('   ·   ');
}

// mouse: drag = orbit around the gun, wheel = zoom, double-click = back to the game camera
{
  let drag = null;
  canvas.addEventListener('pointerdown', (e) => { drag = { x: e.clientX, y: e.clientY }; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener('pointerup', () => { drag = null; });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag || !current) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag = { x: e.clientX, y: e.clientY };
    if (!inspect) {
      const box = new THREE.Box3().setFromObject(pipRoot.visible ? pipRoot : vmRoot);
      const target = box.getCenter(new THREE.Vector3());
      const cam = vmCam.position;
      const v = cam.clone().sub(target);
      inspect = { target, dist: Math.max(v.length() * 1.6, 60), yaw: Math.atan2(v.x, -v.y), pitch: Math.asin(v.z / v.length()) };
    }
    inspect.yaw -= dx * 0.008;
    inspect.pitch = Math.max(-1.45, Math.min(1.45, inspect.pitch + dy * 0.008));
    renderHud();
    draw();
  });
  canvas.addEventListener('wheel', (e) => {
    if (!inspect) return;
    inspect.dist = Math.max(15, Math.min(600, inspect.dist * (e.deltaY > 0 ? 1.1 : 0.9)));
    draw();
    e.preventDefault();
  }, { passive: false });
  canvas.addEventListener('dblclick', () => { inspect = null; renderHud(); draw(); });
}

// ------------------------------------------------------------------ weapon list + offsets
// Weapon groups with no Fallout 76 weapon: not listed, but still built with their offset so the archive stays the same
const HIDDEN = new Set(['deliverer']);

// rebuilt (with a staggered fade-in) only when the filter changes; refreshList() updates the rows in place
function renderList() {
  const q = $('#search').value.trim().toLowerCase();
  const ul = $('#weapons');
  ul.textContent = '';
  let n = 0;
  for (const g of groups) {
    if (HIDDEN.has(g.id) || (q && !g.desc.toLowerCase().includes(q))) continue;
    ul.append(el('li', { 'data-id': g.id, style: '--i:' + Math.min(n++, 30), onclick: () => select(g.id) },
      el('div', { class: 'nm', title: g.desc }, shortName(g.desc)), el('div', { class: 'off' })));
  }
  if (!n) ul.append(el('li', { class: 'empty' }, 'No weapon matches “' + $('#search').value.trim() + '”'));
  $('#w-count').textContent = n;
  replay(ul, 'stagger');
  refreshList();
}

function refreshList() {
  for (const li of document.querySelectorAll('#weapons li[data-id]')) {
    const g = byId(li.dataset.id);
    const off = offsetOf(g);
    const changed = !same(off, state.installed[g.desc] || [0, 0, 0]);
    li.classList.toggle('on', !!current && current.id === g.id);
    li.querySelector('.off').textContent = isZero(off) ? 'vanilla' : off.map(fmt).join(',  ');
    const want = changed ? 'changed' : (!g.mesh ? 'hands only' : '');
    let tag = li.querySelector('.tag');
    if (!want) { if (tag) tag.remove(); continue; }
    if (!tag) { tag = el('div', { class: 'tag' }); li.insertBefore(tag, li.querySelector('.off')); }
    tag.textContent = want;
    tag.classList.toggle('dim', !changed);
  }
}

// ------------------------------------------------------------------ small UI motion helpers
function replay(node, cls) {          // restart a CSS animation class
  node.classList.remove(cls);
  void node.offsetWidth;
  node.classList.add(cls);
}
function syncIndicator(container, indSel) {       // slide the pill/underline under the active button
  const on = container.querySelector('button.on');
  const ind = container.querySelector(indSel);
  if (!on || !ind) return;
  ind.style.width = on.offsetWidth + 'px';
  ind.style.transform = 'translateX(' + on.offsetLeft + 'px)';
}
function syncIndicators() {
  syncIndicator($('#pose-seg'), '.seg-ind');
  syncIndicator($('#tabs'), '.tab-ind');
}
function paintRange(r, zero) {        // fill from `zero` (or the minimum) to the value
  const min = parseFloat(r.min), max = parseFloat(r.max);
  const pct = (x) => Math.max(0, Math.min(100, ((x - min) / (max - min)) * 100));
  const a = pct(zero ?? min), b = pct(parseFloat(r.value));
  r.style.setProperty('--a', Math.min(a, b) + '%');
  r.style.setProperty('--b', Math.max(a, b) + '%');
}
function pulseView() { replay($('#viewport'), 'pulse'); }

const AX = [['X', 'right', 'var(--x)'], ['Y', 'forward', 'var(--y)'], ['Z', 'up', 'var(--z)']];
function renderAxes() {
  const g = current && byId(current.id);
  const box = $('#axes');
  box.textContent = '';
  if (!g) return;
  const off = offsetOf(g);
  AX.forEach(([n, word, col], i) => {
    const num = el('input', { type: 'number', step: '0.1', value: fmt(off[i]) });
    const rng = el('input', { type: 'range', min: '-40', max: '40', step: '0.1', value: off[i] });
    paintRange(rng, 0);
    const set = (v) => {
      v = Math.round(parseFloat(v) * 100) / 100;
      if (!Number.isFinite(v)) return;
      const o = [...offsetOf(g)];
      o[i] = v;
      setOffset(g, o, { keepInputs: true });
      num.value = fmt(v);
      rng.value = v;
      paintRange(rng, 0);
    };
    num.addEventListener('input', () => set(num.value));
    rng.addEventListener('input', () => set(rng.value));
    box.append(el('div', { class: 'axis', title: n + ' = ' + word, style: '--c:' + col },
      el('span', { class: 'lab' }, n), rng, num));
  });
  $('#btn-installed').disabled = same(off, state.installed[g.desc] || [0, 0, 0]);
}

function setOffset(g, o, opts = {}) {
  state.offsets[g.desc] = o.map((v) => Math.round(v * 100) / 100);
  saveSoon();
  applyPose();
  refreshList();
  if (!opts.keepInputs) renderAxes();
  else $('#btn-installed').disabled = same(state.offsets[g.desc], state.installed[g.desc] || [0, 0, 0]);
  updateStatus();
}

function renderParts() {
  const box = $('#parts');
  box.textContent = '';
  if (!current) return;
  if (!current.root) {
    box.append(el('p', { class: 'note' }, 'No model for this weapon was found in the game archives, so only the hands are shown. The offset still works in game.'));
    return;
  }
  box.append(el('div', { class: 'part' }, el('span', {}, 'Base'), el('div', { class: 'path', title: current.root }, current.root.split('/').slice(-2).join('/'))));
  for (const row of current.parts) {
    const sel = el('select', {},
      el('option', { value: '' }, '(none)'),
      row.options.map((o) => el('option', { value: o }, o.split('/').pop().replace(/\.nif$/, '') + (o === row.default ? '  (default)' : ''))));
    sel.value = row.part || '';
    sel.addEventListener('change', () => {
      const p = state.parts[current.id] || (state.parts[current.id] = {});
      p[row.slot] = sel.value || null;
      saveSoon();
      loadScene(current.id);
    });
    box.append(el('div', { class: 'part' }, el('span', {}, row.slot.replace(/^P-/, '')), sel));
  }
  if (state.parts[current.id] && Object.keys(state.parts[current.id]).length) {
    box.append(el('div', { class: 'row-btns' }, el('button', { onclick: () => { delete state.parts[current.id]; saveSoon(); loadScene(current.id); } }, 'Default parts')));
  }
}

async function loadScene(id) {
  const parts = state.parts[id] || {};
  const k = id + JSON.stringify(parts);
  $('#loading').classList.remove('hidden');
  try {
    let sc = sceneCache.get(k);
    if (!sc) {
      sc = await window.vm.backend('scene', { id, parts });
      sceneCache.set(k, sc);
    }
    if (state.selected !== id) return;          // another weapon was picked while this one loaded
    current = sc;
    buildMeshes(sc);
    inspect = null;
    applyPose();
    pulseView();
    renderParts();
  } catch (e) {
    showModal('Could not load the preview', String(e.message || e), [['OK', hideModal]]);
  } finally {
    $('#loading').classList.add('hidden');
  }
}

async function select(id) {
  state.selected = id;
  saveSoon();
  const g = byId(id);
  $('#w-title').textContent = shortName(g.desc);
  $('#w-sub').textContent = (g.desc !== shortName(g.desc) ? g.desc + '. ' : '') +
    'Default from First Person FOV Overhaul: ' + g.src + (g.closest ? ' (closest Fallout 4 gun)' : '') + ' = ' + g.default.map(fmt).join(', ') +
    '. ' + g.folders.length + ' animation folder' + (g.folders.length > 1 ? 's' : '') + '.';
  replay($('#w-head'), 'enter');
  current = { id, pose: {} };
  refreshList();
  renderAxes();
  await loadScene(id);
  renderAxes();
  if (pose === 'pipboy') await setPose('ready');     // picking a gun shows the gun
}

// ------------------------------------------------------------------ ini settings tab
function parsedValue(s, raw) {
  if (raw === null || raw === undefined) return null;
  if (s.type === 'bool') return /^(1|true)$/i.test(raw.trim());
  const v = parseFloat(raw);
  return Number.isFinite(v) ? v : null;
}
function stored(s) {
  const v = ini.values[sid(s)] || {};
  return parsedValue(s, v.custom);
}
function effective(s) {
  if (!s) return null;
  if (sid(s) in ini.pending) {
    const p = ini.pending[sid(s)];
    if (p !== null) return p;
    const pv = ini.values[sid(s)] || {};
    return parsedValue(s, pv.prefs) ?? s.def;
  }
  const v = ini.values[sid(s)] || {};
  return parsedValue(s, v.custom) ?? parsedValue(s, v.prefs) ?? s.def;
}

function renderSettings() {
  const box = $('#settings');
  box.textContent = '';
  if (ini.hudScreenshots) {
    box.append(el('p', { class: 'note', style: 'color:var(--accent);margin:0 0 12px' },
      'The screenshot HUD is on, which holds the viewmodel FOV at 80. A new viewmodel FOV is saved for when you switch back to the normal HUD.'));
  }
  for (const grp of SETTINGS) {
    const gbox = el('div', { class: 'set-group' }, el('h3', {}, grp.title));
    for (const s of grp.items) {
      const v = ini.values[sid(s)] || {};
      const changed = sid(s) in ini.pending;
      const cur = effective(s);
      let where;
      if (v.custom !== null && v.custom !== undefined) where = 'Custom.ini: ' + v.custom;
      else if (v.prefs !== null && v.prefs !== undefined) where = 'Not in Custom.ini; Prefs.ini has ' + v.prefs;
      else where = 'Not set (game default' + (s.def !== null && s.def !== undefined ? ' ' + s.def : '') + ')';
      if (changed) where += ini.pending[sid(s)] === null ? '  →  line will be removed' : '  →  ' + ini.pending[sid(s)];
      const reset = el('button', { title: s.removeOnReset ? 'Remove the line (game default)' : 'Game default ' + s.def,
        onclick: () => { setPending(s, s.removeOnReset ? null : s.def); } }, '↺');
      let ctl;
      if (s.type === 'bool') {
        const cb = el('input', { type: 'checkbox' });
        cb.checked = cur === null ? !!s.def : !!cur;
        cb.addEventListener('change', () => setPending(s, cb.checked ? 1 : 0));
        ctl = el('div', { class: 'bool' }, el('label', { class: 'chk' }, cb, cb.checked ? 'On' : 'Off'), reset);
      } else {
        const val = cur ?? s.min;
        const rng = el('input', { type: 'range', min: s.min, max: s.max, step: s.step, value: val });
        const num = el('input', { type: 'number', min: s.min, max: s.max, step: s.step, value: cur === null ? '' : fmt(cur) });
        const zero = s.min < 0 ? 0 : undefined;          // the camera offsets fill from 0
        paintRange(rng, zero);
        rng.addEventListener('input', () => { num.value = rng.value; paintRange(rng, zero); setPending(s, parseFloat(rng.value), true); });
        num.addEventListener('change', () => {
          const x = parseFloat(num.value);
          if (!Number.isFinite(x)) return;
          const c = Math.min(s.max, Math.max(s.min, x));
          num.value = fmt(c);
          setPending(s, c);
        });
        ctl = el('div', { class: 'ctl' }, rng, num, reset);
      }
      gbox.append(el('div', { class: 'set' + (changed ? ' changed' : '') },
        el('div', { class: 'top' }, el('span', { class: 'name' }, s.label), el('span', { class: 'key' }, '[' + s.section + '] ' + s.key)),
        ctl, el('div', { class: 'meta where' }, where), el('div', { class: 'meta' }, s.help)));
    }
    box.append(gbox);
  }
  const n = Object.keys(ini.pending).length;
  const bar = $('#save-bar');
  if (!!n !== bar.classList.contains('dirty')) bar.classList.toggle('dirty', !!n);
  $('#ini-state').textContent = n ? n + ' unsaved change' + (n > 1 ? 's' : '') : 'All changes saved';
  $('#btn-ini-save').disabled = !n;
  $('#btn-ini-revert').disabled = !n;
}

let settingsTimer = null;
function setPending(s, value, live) {
  const st = stored(s);
  const v = ini.values[sid(s)] || {};
  const unchanged = value === null ? (v.custom === null || v.custom === undefined) : (st !== null && Math.abs(st - value) < 1e-9);
  if (unchanged) delete ini.pending[sid(s)];
  else ini.pending[sid(s)] = value;
  renderHud();
  draw();
  if (live) {     // don't rebuild the list while a slider is being dragged
    clearTimeout(settingsTimer);
    settingsTimer = setTimeout(renderSettings, 400);
  } else renderSettings();
}

async function loadIni() {
  const r = await window.vm.iniRead(ALL_SETTINGS.map((s) => ({ section: s.section, key: s.key })));
  ini.values = r.values;
  ini.file = r.file;
  ini.hudScreenshots = r.hudScreenshots;
  ini.pending = {};
  renderSettings();
  renderHud();
  draw();
}

async function saveIni() {
  const changes = Object.entries(ini.pending).map(([k, value]) => {
    const s = ALL_SETTINGS.find((x) => sid(x) === k);
    const out = value === null ? null : s.type === 'bool' ? (value ? '1' : '0') : (Number.isInteger(value) ? value.toString() : fmt(value));
    return { section: s.section, key: s.key, value: out };
  });
  const r = await window.vm.iniWrite(changes);
  await loadIni();
  const msg = [];
  if (r.changed) msg.push('Saved to ' + r.file + '.' + (r.backup ? '\nThe file before this app first changed it is kept as ' + r.backup.split(/[\\/]/).pop() + '.' : ''));
  msg.push(...r.notes);
  msg.push('Restart the game for FOV changes to apply. Saving the F76Manager Tweaks page later can overwrite these values.');
  showModal('Settings saved', msg.join('\n\n'), [['OK', hideModal]]);
}

// ------------------------------------------------------------------ install
async function install() {
  const shown = groups.filter((g) => !HIDDEN.has(g.id));
  const changed = shown.filter((g) => !same(offsetOf(g), state.installed[g.desc] || [0, 0, 0]));
  const active = shown.filter((g) => !isZero(offsetOf(g)));
  const body = (changed.length ? changed.length + ' weapon' + (changed.length > 1 ? 's' : '') + ' changed since the last install.\n' : 'Nothing changed since the last install; this rebuilds the same archive.\n') +
    active.length + ' of ' + shown.length + ' weapons will be moved (vanilla ones are left out).\n\n' +
    'Writes Data\\' + info.archive + ' (about a minute). The game must be closed.';
  showModal('Install gun positions', body, [['Cancel', hideModal], ['Install', async () => {
    $('#m-btns').textContent = '';
    $('#m-progress').classList.remove('hidden');
    $('#m-bar').style.width = '0';
    $('#m-body').textContent = 'Baking offsets into the animations…';
    const offsets = {};
    for (const g of groups) offsets[g.desc] = offsetOf(g);
    try {
      const r = await window.vm.install(offsets, info.archive);
      $('#m-progress').classList.add('hidden');
      if (!r.ok) {
        const bad = (r.bad || []).map((b) => '  ' + b.clip.split('/animations/').pop() + ': ' + b.kind).join('\n');
        showModal('Install failed', (r.error || (r.nbad + ' clips failed verification; nothing was installed.')) + (bad ? '\n\n' + bad : ''), [['OK', hideModal]]);
        return;
      }
      state.installed = JSON.parse(JSON.stringify(offsets));
      saveSoon();
      refreshList();
      renderAxes();
      updateStatus();
      let text = r.empty ? 'Every weapon is vanilla, so the archive was not rebuilt. Remove it from your mod list to go fully vanilla.'
        : 'Installed ' + r.clips + ' clips for ' + r.groups + ' weapons in ' + r.seconds + ' s.\n' + r.target;
      if (r.backup) text += '\n\nThe archive from before this app first replaced it: ' + r.backup;
      if (r.registeredNow) text += '\n\nAdded it to sResourceArchive2List in Fallout76Custom.ini so the game loads it. If a mod manager manages that list, add it there as well or the manager may remove it.';
      else if (!r.registered) text += '\n\nThis archive is not in your Fallout76Custom.ini archive list. Add it in your mod manager (or the ini) or the game will not load it.';
      info = await window.vm.info();
      updateStatus();
      showModal('Gun positions installed', text, [['OK', hideModal]]);
    } catch (e) {
      $('#m-progress').classList.add('hidden');
      showModal('Install failed', String(e.message || e), [['OK', hideModal]]);
    }
  }]]);
}
window.vm.onBuildProgress((p) => {
  $('#m-bar').style.width = Math.round((100 * p.done) / p.total) + '%';
  $('#m-body').textContent = 'Baking offsets into the animations… ' + p.done + ' / ' + p.total + ' clips';
});
window.vm.onBackendDied((t) => showModal('Backend stopped', t || 'The Python backend exited.', [['OK', hideModal]]));

// ------------------------------------------------------------------ modal / status
function showModal(title, body, buttons) {
  $('#m-title').textContent = title;
  $('#m-body').textContent = body;
  const b = $('#m-btns');
  b.textContent = '';
  buttons.forEach(([label, fn], i) => b.append(el('button', { class: i === buttons.length - 1 ? 'primary' : '', onclick: fn }, label)));
  $('#modal').classList.remove('hidden');
}
function hideModal() { $('#modal').classList.add('hidden'); }

let info = {};
function updateStatus() {
  const changed = groups.filter((g) => !same(offsetOf(g), state.installed[g.desc] || [0, 0, 0])).length;
  const box = $('#status');
  box.textContent = '';
  box.append(el('span', { class: 'pill ' + (info.archiveExists ? (info.registered ? 'good' : 'warn') : 'bad') },
    info.archiveExists ? (info.registered ? 'Archive installed' : 'Archive not in the ini list') : 'Archive not installed'));
  if (changed) box.append(el('span', { class: 'pill warn' }, changed + ' not installed yet'));
  if (info.gameRunning) box.append(el('span', { class: 'pill bad' }, 'Game running'));
}

// ------------------------------------------------------------------ wiring
document.querySelectorAll('#pose-seg button').forEach((b) => b.addEventListener('click', () => setPose(b.dataset.pose)));
document.querySelectorAll('.tabs button').forEach((b) => b.addEventListener('click', () => {
  const was = state.tab || 'position';
  document.querySelectorAll('.tabs button').forEach((x) => x.classList.toggle('on', x === b));
  $('#tab-position').classList.toggle('hidden', b.dataset.tab !== 'position');
  $('#tab-fov').classList.toggle('hidden', b.dataset.tab !== 'fov');
  if (was !== b.dataset.tab) replay($('#tab-' + b.dataset.tab), 'enter');
  syncIndicators();
  state.tab = b.dataset.tab;
  saveSoon();
}));
$('#ghost').addEventListener('change', () => { state.showGhost = $('#ghost').checked; saveSoon(); applyPose(); });
$('#world').addEventListener('change', () => { state.world = $('#world').checked; saveSoon(); draw(); });
$('#aspect').addEventListener('change', () => { state.aspect = $('#aspect').value; saveSoon(); resize(); });
$('#search').addEventListener('input', renderList);
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !$('#modal').classList.contains('hidden') && $('#m-progress').classList.contains('hidden')) hideModal();
});
$('#btn-default').addEventListener('click', () => { const g = byId(current.id); setOffset(g, [...g.default]); });
$('#btn-zero').addEventListener('click', () => setOffset(byId(current.id), [0, 0, 0]));
$('#btn-installed').addEventListener('click', () => { const g = byId(current.id); setOffset(g, [...(state.installed[g.desc] || [0, 0, 0])]); });
$('#btn-install').addEventListener('click', install);
$('#btn-ini-save').addEventListener('click', saveIni);
$('#btn-ini-revert').addEventListener('click', () => { ini.pending = {}; renderSettings(); renderHud(); draw(); });
window.addEventListener('resize', () => { resize(); syncIndicators(); });
document.fonts.ready.then(syncIndicators);
window.addEventListener('keydown', (e) => {
  if (!current || ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
  const step = e.shiftKey ? 1 : 0.1;
  const d = { ArrowLeft: [0, -step], ArrowRight: [0, step], ArrowUp: [2, step], ArrowDown: [2, -step], PageUp: [1, step], PageDown: [1, -step] }[e.key];
  if (!d) return;
  const g = byId(current.id);
  const o = [...offsetOf(g)];
  o[d[0]] = Math.round((o[d[0]] + d[1]) * 100) / 100;
  setOffset(g, o);
  e.preventDefault();
});
new ResizeObserver(resize).observe($('#stage'));

// test hook (used by main.js --js=...): preview-only changes, nothing is saved
window.__vmTest = async ({ id, offset, fovMode, pose: p, world, ghost, parts, ref, alpha, fov, camOffset, pipDist }) => {
  testMode = true;
  if (pipDist) PIP_DIST = pipDist;
  if (window.__pipSign) PIP_SIGN = window.__pipSign;
  if (fovMode) state.fovMode = fovMode;
  if (parts && id) state.parts[id] = parts;
  if (fov) ini.pending['Display/fDefault1stPersonFOV'] = fov;
  if (camOffset) window.__camOffset = camOffset;
  if (ref) {       // draw a game screenshot behind a see-through viewmodel to compare
    const tex = await new THREE.TextureLoader().loadAsync(ref);
    tex.colorSpace = THREE.SRGBColorSpace;
    worldScene.background = tex;
    worldScene.fog = null;
    worldScene.traverse((c) => { if (c !== worldScene && (c.isMesh || c.isLine || c.isLineSegments)) c.visible = false; });
    document.querySelector('main').style.gridTemplateColumns = '0 1fr 0';
    document.querySelector('header').style.display = 'none';
    document.querySelector('.toolbar').style.display = 'none';
    document.querySelector('.hint').style.display = 'none';
    document.querySelector('main').style.height = '100%';
    $('.crosshair').style.display = 'none';
    resize();
    for (const m of [MAT.skin, MAT.metal, MAT.part, MAT.wood, MAT.pipboy, MAT.screen]) { m.transparent = true; m.opacity = alpha || 0.55; }
  }
  if (world !== undefined) $('#world').checked = world;
  if (ghost !== undefined) $('#ghost').checked = ghost;
  if (id) await select(id);
  if (offset) state.offsets[byId(current.id).desc] = offset;
  await setPose(p || pose);
  return { id: current.id, fov: fovValue('viewmodel'), vfov: vmCam.fov, cam: current.pose.ready.camera };
};

// ------------------------------------------------------------------ start
(async function start() {
  $('#loading').classList.remove('hidden');
  try {
    info = await window.vm.info();
    state = await window.vm.loadState();
    const init = await window.vm.backend('init', {});
    groups = init.groups;
    if (!state.installed) {
      // the archive this app replaces was built from the default offsets (byte-identical rebuild, checked 2026-10-26)
      state.installed = {};
      for (const g of groups) state.installed[g.desc] = info.archiveExists ? [...g.default] : [0, 0, 0];
    }
    if (!state.offsets) state.offsets = JSON.parse(JSON.stringify(state.installed));
    state.parts = state.parts || {};
    if (state.aspect) $('#aspect').value = state.aspect;
    delete state.ghost;                 // older key; the vanilla outline now starts off unless turned on
    $('#ghost').checked = state.showGhost === true;
    if (state.world === false) $('#world').checked = false;
    if (state.tab === 'fov') document.querySelector('.tabs button[data-tab=fov]').click();
    saveSoon();
    updateStatus();
    renderList();
    syncIndicators();
    await loadIni();
    resize();
    const first = groups.find((g) => !HIDDEN.has(g.id));
    await select(state.selected && byId(state.selected) && !HIDDEN.has(state.selected) ? state.selected : first.id);
  } catch (e) {
    showModal('Startup failed', String(e.message || e), [['OK', hideModal]]);
  } finally {
    $('#loading').classList.add('hidden');
  }
})();
