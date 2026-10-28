const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('vm', {
  backend: (cmd, args) => ipcRenderer.invoke('backend', cmd, args),
  iniRead: (keys) => ipcRenderer.invoke('ini:read', keys),
  iniWrite: (changes) => ipcRenderer.invoke('ini:write', changes),
  loadState: () => ipcRenderer.invoke('state:load'),
  saveState: (s) => ipcRenderer.invoke('state:save', s),
  install: (offsets, archive) => ipcRenderer.invoke('install', offsets, archive),
  info: () => ipcRenderer.invoke('info'),
  reveal: (p) => ipcRenderer.invoke('reveal', p),
  onBuildProgress: (fn) => ipcRenderer.on('build-progress', (e, p) => fn(p)),
  onBackendDied: (fn) => ipcRenderer.on('backend-died', (e, t) => fn(t)),
});
