// FO76 Viewmodel Editor - Electron main process.
// Owns: the Python backend (backend/server.py), Fallout76Custom.ini edits, app state, and installing the archive.
const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawn, execFileSync } = require('child_process');
const readline = require('readline');
const { iniGet, iniSet } = require('./ini');
const game = require('./game');

const APP = __dirname;
const PACKAGED = app.isPackaged;
// The packaged app (Nexus download) keeps its settings, cache and backups in %APPDATA%\FO76 Viewmodel Editor and finds
// the game itself; the dev tree lives in <game>\Mods\_viewmodel_editor and keeps them next to it.
const USER = PACKAGED ? app.getPath('userData') : APP;
const STATE_FILE = path.join(USER, 'state.json');
// not "cache": in %APPDATA% that is Chromium's own Cache folder (case-insensitive)
const CACHE = path.join(USER, PACKAGED ? 'Game data cache' : 'cache');
// the Nexus file's name first, then the name of my original install
const ARCHIVES = ['WeaponReposition76.ba2', 'WeaponReposition - GunMover All Guns.ba2'];

let GAME = null, DATA = null, BACKUPS = null, HUD_PROFILES = null, INI = game.iniNames(null);
function setGame(dir) {
  GAME = dir;
  INI = game.iniNames(dir);             // Game Pass uses Project76Custom.ini / Project76Prefs.ini
  DATA = path.join(dir, 'Data');
  BACKUPS = PACKAGED ? path.join(USER, 'backups') : path.join(GAME, 'Mods', '_ba2_backups');
  HUD_PROFILES = path.join(GAME, 'Mods', '_hud_profiles');
}

let win = null;

// ---------------------------------------------------------------- finding the game (game.js)
async function askGameDir() {
  for (;;) {
    const r = await dialog.showOpenDialog({ title: 'Where is Fallout 76 installed? (the folder with Fallout76.exe or Project76_GamePass.exe)', properties: ['openDirectory'] });
    if (r.canceled || !r.filePaths.length) return null;
    const dir = game.resolvePicked(r.filePaths[0]);
    if (dir) return dir;
    await dialog.showMessageBox({ type: 'warning', message: 'That folder has no Fallout 76 exe and Data folder. Pick the Fallout 76 install folder.' });
  }
}
// ---------------------------------------------------------------- Python backend
function findPython() {
  if (PACKAGED) return path.join(process.resourcesPath, 'python', 'python.exe');     // bundled runtime
  const cands = [
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python313', 'python.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python312', 'python.exe'),
  ];
  for (const c of cands) if (fs.existsSync(c)) return c;
  return 'python';
}

class Backend {
  constructor() {
    this.next = 1;
    this.pending = new Map();
    const script = path.join(PACKAGED ? process.resourcesPath : APP, 'backend', 'server.py');
    this.proc = spawn(findPython(), ['-I', script], {
      cwd: path.dirname(script), windowsHide: true, env: { ...process.env, VM_GAME: GAME, VM_CACHE: CACHE },
    });
    this.ready = new Promise((resolve) => { this._ready = resolve; });
    readline.createInterface({ input: this.proc.stdout }).on('line', (line) => this.onLine(line));
    let err = '';
    this.proc.stderr.on('data', (d) => { err += d.toString(); if (err.length > 20000) err = err.slice(-10000); });
    this.proc.on('exit', (code) => {
      for (const p of this.pending.values()) p.reject(new Error('Python backend exited (' + code + '): ' + err.slice(-1500)));
      this.pending.clear();
      // closing the app kills the backend after the window is gone; only report a crash while it is still open
      if (!this.stopping && win && !win.isDestroyed()) win.webContents.send('backend-died', err.slice(-3000));
    });
  }
  onLine(line) {
    let msg;
    try { msg = JSON.parse(line); } catch { return; }
    if (msg.ready) return this._ready();
    const p = this.pending.get(msg.id);
    if (!p) return;
    if (msg.progress) { if (p.onProgress) p.onProgress(msg.progress); return; }
    this.pending.delete(msg.id);
    if (msg.ok) p.resolve(msg.result);
    else p.reject(new Error(msg.error + (msg.trace ? '\n' + msg.trace : '')));
  }
  async call(cmd, args, onProgress) {
    await this.ready;
    const id = this.next++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject, onProgress });
      this.proc.stdin.write(JSON.stringify({ id, cmd, args }) + '\n');
    });
  }
}
let backend = null;

// ---------------------------------------------------------------- ini files
function iniDir() {
  const cands = [
    path.join(process.env.OneDrive || '', 'Documents', 'My Games', 'Fallout 76'),
    path.join(os.homedir(), 'OneDrive', 'Documents', 'My Games', 'Fallout 76'),
    path.join(os.homedir(), 'Documents', 'My Games', 'Fallout 76'),
  ];
  for (const c of cands) if (fs.existsSync(path.join(c, INI.custom))) return c;
  for (const c of cands) if (fs.existsSync(c)) return c;
  return cands[cands.length - 1];
}
const customIni = () => path.join(iniDir(), INI.custom);
const prefsIni = () => path.join(iniDir(), INI.prefs);

function readText(p) {
  if (!fs.existsSync(p)) return '';
  let t = fs.readFileSync(p, 'utf8');
  if (t.charCodeAt(0) === 0xfeff) t = t.slice(1);
  return t;
}

function backupOnce(file, tag) {
  const bak = file + '.' + tag + '.bak';
  if (fs.existsSync(file) && !fs.existsSync(bak)) fs.copyFileSync(file, bak);
  return bak;
}

// ---------------------------------------------------------------- state
function loadState() {
  try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); } catch { return {}; }
}
function saveState(s) {
  fs.mkdirSync(USER, { recursive: true });
  const tmp = STATE_FILE + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(s, null, 2));
  fs.renameSync(tmp, STATE_FILE);
}

function gameRunning() {
  try {
    const out = execFileSync('tasklist', ['/NH', '/FO', 'CSV'], { encoding: 'utf8', windowsHide: true }).toLowerCase();
    return game.EXES.some((e) => out.includes('"' + e.toLowerCase() + '"'));
  } catch { return false; }
}

function hudScreenshotMode() {
  try { return fs.readFileSync(path.join(HUD_PROFILES, 'active.txt'), 'utf8').trim() === 'screenshots'; } catch { return false; }
}

// ---------------------------------------------------------------- IPC
ipcMain.handle('backend', async (ev, cmd, args) => {
  if (cmd === 'scene') {
    const r = await backend.call('scene', args);
    const sc = JSON.parse(fs.readFileSync(r.file, 'utf8'));
    fs.rmSync(r.file, { force: true });
    return sc;
  }
  return backend.call(cmd, args);
});

ipcMain.handle('ini:read', (ev, keys) => {
  const c = readText(customIni()), p = readText(prefsIni());
  const out = {};
  for (const k of keys) {
    out[k.section + '/' + k.key] = { custom: iniGet(c, k.section, k.key), prefs: iniGet(p, k.section, k.key) };
  }
  return { values: out, file: customIni(), exists: fs.existsSync(customIni()), hudScreenshots: hudScreenshotMode() };
});

ipcMain.handle('ini:write', (ev, changes) => {
  // changes: [{section, key, value|null}] -> Fallout76Custom.ini (UTF-8, no BOM, line endings kept)
  const file = customIni();
  let text = readText(file);
  const before = text;
  const notes = [];
  const shot = hudScreenshotMode();
  for (const ch of changes) {
    if (shot && ch.section.toLowerCase() === 'display' && ch.key.toLowerCase() === 'fdefault1stpersonfov' && ch.value !== null) {
      // the screenshot HUD holds the viewmodel FOV at 80 and restores viewmodel_fov.txt when switched back
      fs.writeFileSync(path.join(HUD_PROFILES, 'viewmodel_fov.txt'), String(ch.value) + '\r\n', 'ascii');
      notes.push('Screenshot HUD is on: viewmodel FOV ' + ch.value + ' saved for when you switch back to the normal HUD.');
      continue;
    }
    text = iniSet(text, ch.section, ch.key, ch.value);
  }
  if (text === before) return { file, changed: false, notes };
  const bak = backupOnce(file, 'pre-vmeditor');
  const tmp = file + '.vmeditor.tmp';
  fs.writeFileSync(tmp, text, { encoding: 'utf8' });
  fs.renameSync(tmp, file);
  return { file, changed: true, backup: bak, notes };
});

ipcMain.handle('state:load', () => loadState());
ipcMain.handle('state:save', (ev, s) => { saveState(s); return true; });

ipcMain.handle('install', async (ev, offsets, archiveName) => {
  if (gameRunning()) return { ok: false, error: 'Fallout 76 is running. Close the game first; it keeps its archives open.' };
  const name = archiveName || currentArchive();
  const target = path.join(DATA, name);
  let backup = null;
  if (fs.existsSync(target)) {
    fs.mkdirSync(BACKUPS, { recursive: true });
    backup = path.join(BACKUPS, name + '.pre-vmeditor.bak');
    if (!fs.existsSync(backup)) fs.copyFileSync(target, backup);
  }
  const result = await backend.call('build', { offsets, out: target }, (p) => {
    if (win && !win.isDestroyed()) win.webContents.send('build-progress', p);
  });
  result.target = target;
  result.backup = backup;
  result.registered = archiveRegistered(name);
  if (result.ok && !result.empty && !result.registered) {
    registerArchive(name);
    result.registered = archiveRegistered(name);
    result.registeredNow = !!result.registered;
  }
  return result;
});

// the game only loads mod archives named in [Archive] sResourceArchive2List of Fallout76Custom.ini
function registerArchive(name) {
  const file = customIni();
  let text = readText(file);
  const cur = iniGet(text, 'Archive', 'sResourceArchive2List');
  const list = cur ? cur.split(',').map((s) => s.trim()).filter(Boolean) : [];
  list.push(name);
  backupOnce(file, 'pre-vmeditor');
  text = iniSet(text, 'Archive', 'sResourceArchive2List', list.join(', '));
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = file + '.vmeditor.tmp';
  fs.writeFileSync(tmp, text, { encoding: 'utf8' });
  fs.renameSync(tmp, file);
}

function currentArchive() {
  return ARCHIVES.find((n) => archiveRegistered(n)) || ARCHIVES.find((n) => fs.existsSync(path.join(DATA, n))) || ARCHIVES[0];
}

function archiveRegistered(name) {
  const c = readText(customIni());
  for (const key of ['sResourceIndexFileList', 'sResourceArchive2List']) {
    const v = iniGet(c, 'Archive', key);
    if (v && v.split(',').map((s) => s.trim().toLowerCase()).includes(name.toLowerCase())) return key;
  }
  return null;
}

ipcMain.handle('info', () => {
  const archive = currentArchive();
  return {
    game: GAME, data: DATA, ini: customIni(), archive,
    archiveExists: fs.existsSync(path.join(DATA, archive)),
    registered: archiveRegistered(archive), gameRunning: gameRunning(),
  };
});
ipcMain.handle('reveal', (ev, p) => shell.showItemInFolder(p));

// ---------------------------------------------------------------- window
function createWindow() {
  const size = (process.argv.find((a) => a.startsWith('--size=')) || '').slice(7).split('x').map(Number);
  win = new BrowserWindow({
    width: size[0] || 1500, height: size[1] || 920, minWidth: 1100, minHeight: 700,
    backgroundColor: '#0d0f12', title: 'FO76 Viewmodel Editor', autoHideMenuBar: true,
    // the app header is the title bar; Windows draws the min/max/close buttons over its right end
    titleBarStyle: 'hidden', titleBarOverlay: { color: '#14171b', symbolColor: '#a7aab0', height: 52 },
    webPreferences: { preload: path.join(APP, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  win.loadFile(path.join(APP, 'renderer', 'index.html'));
  if (process.argv.includes('--devtools')) win.webContents.openDevTools({ mode: 'detach' });
  // --shot=<png> [--shot-delay=ms] [--js=<code>]: screenshot the window once loaded, then quit (for testing)
  const shot = (process.argv.find((a) => a.startsWith('--shot=')) || '').slice(7);
  if (shot) {
    const delay = parseInt((process.argv.find((a) => a.startsWith('--shot-delay=')) || '=6000').split('=')[1], 10);
    const js = (process.argv.find((a) => a.startsWith('--js=')) || '').slice(5);
    win.webContents.on('console-message', (e, level, msg) => console.log('[renderer]', msg));
    win.webContents.once('did-finish-load', () => setTimeout(async () => {
      if (js) { try { console.log('[js]', JSON.stringify(await win.webContents.executeJavaScript(js))); } catch (e) { console.log('[js error]', e.message); } }
      setTimeout(async () => {
        const img = await win.webContents.capturePage();
        fs.writeFileSync(shot, img.toPNG());
        app.quit();
      }, 1500);
    }, delay));
  }
}

app.whenReady().then(async () => {
  const st = loadState();
  const dir = game.findGame({ saved: st.gameDir, devGame: PACKAGED ? null : path.resolve(APP, '..', '..'), execPath: process.execPath })
    || await askGameDir();
  if (!dir) { app.quit(); return; }
  if (dir !== st.gameDir) saveState({ ...st, gameDir: dir });
  setGame(dir);
  backend = new Backend();
  createWindow();
});
app.on('window-all-closed', () => {
  win = null;
  if (backend && backend.proc) { backend.stopping = true; backend.proc.kill(); }
  app.quit();
});
