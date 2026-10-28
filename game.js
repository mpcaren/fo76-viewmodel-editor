// Finding the Fallout 76 install (Steam, Microsoft Store / Game Pass, old Bethesda.net launcher) and the ini names
// that go with it. No Electron here so it can be tested with plain node.
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

// Steam build: Fallout76.exe + Fallout76Custom.ini; Game Pass build: Project76_GamePass.exe + Project76Custom.ini
// (both inis in Documents\My Games\Fallout 76)
const EXES = ['Fallout76.exe', 'Project76_GamePass.exe'];

function gameExe(dir) {
  if (!dir || !fs.existsSync(path.join(dir, 'Data'))) return null;
  return EXES.find((e) => fs.existsSync(path.join(dir, e))) || null;
}
const isGameDir = (dir) => !!gameExe(dir);

function iniNames(dir) {
  const gp = gameExe(dir) === 'Project76_GamePass.exe';
  return { custom: gp ? 'Project76Custom.ini' : 'Fallout76Custom.ini', prefs: gp ? 'Project76Prefs.ini' : 'Fallout76Prefs.ini' };
}

function steamLibraries() {
  const roots = [];
  try {
    const out = execFileSync('reg', ['query', 'HKCU\\Software\\Valve\\Steam', '/v', 'SteamPath'], { encoding: 'utf8', windowsHide: true });
    const m = out.match(/SteamPath\s+REG_SZ\s+(.+)/);
    if (m) roots.push(m[1].trim());
  } catch { /* no Steam */ }
  roots.push('C:\\Program Files (x86)\\Steam');
  const libs = new Set();
  for (const r of roots) {
    libs.add(path.normalize(r));
    try {
      const vdf = fs.readFileSync(path.join(r, 'steamapps', 'libraryfolders.vdf'), 'utf8');
      for (const m of vdf.matchAll(/"path"\s+"([^"]+)"/g)) libs.add(path.normalize(m[1].replace(/\\\\/g, '\\')));
    } catch { /* no library list */ }
  }
  return [...libs];
}

// where to look, most likely first
function candidates({ saved, devGame, execPath, drives = 'CDEFGHIJ' } = {}) {
  const c = [];
  if (saved) c.push(saved);
  if (devGame) c.push(devGame);
  if (execPath) {                                     // the app unpacked somewhere inside the game folder
    let d = path.dirname(execPath);
    for (let i = 0; i < 6; i++) { c.push(d); d = path.dirname(d); }
  }
  for (const lib of steamLibraries()) c.push(path.join(lib, 'steamapps', 'common', 'Fallout76'));
  for (const dr of drives) {
    c.push(dr + ':\\XboxGames\\Fallout 76\\Content', dr + ':\\XboxGames\\Fallout76\\Content',     // Xbox app
      dr + ':\\Program Files\\ModifiableWindowsApps\\Fallout76',                                 // older Store installs
      dr + ':\\Program Files (x86)\\Bethesda.net Launcher\\games\\Fallout76');                   // retired launcher
  }
  return c;
}

function findGame(opts) {
  return candidates(opts).find(isGameDir) || null;
}

// a folder picked by hand: accept the install folder itself or the Xbox app folder above its Content folder
function resolvePicked(dir) {
  for (const d of [dir, path.join(dir, 'Content')]) if (isGameDir(d)) return d;
  return null;
}

module.exports = { EXES, gameExe, isGameDir, iniNames, steamLibraries, candidates, findGame, resolvePicked };
