'use strict';

const { contextBridge, ipcRenderer } = require('electron');

/**
 * Secure bridge between the sandboxed renderer and the main process.
 * The renderer never touches Node or Electron internals directly — it only
 * sees the small, explicit `window.autoPicker` API defined here.
 */
const api = {
  // Settings
  getSettings: () => ipcRenderer.invoke('settings:get'),
  updateSettings: (patch) => ipcRenderer.invoke('settings:update', patch),
  resetSettings: () => ipcRenderer.invoke('settings:reset'),

  // Window controls (custom frameless titlebar)
  windowMinimize: () => ipcRenderer.invoke('window:minimize'),
  windowMaximize: () => ipcRenderer.invoke('window:maximize'),
  windowClose: () => ipcRenderer.invoke('window:close'),
  platform: process.platform,

  // Engine control
  start: () => ipcRenderer.invoke('engine:start'),
  stop: () => ipcRenderer.invoke('engine:stop'),
  pause: () => ipcRenderer.invoke('engine:pause'),
  resume: () => ipcRenderer.invoke('engine:resume'),
  toggle: () => ipcRenderer.invoke('engine:toggle'),
  getStatus: () => ipcRenderer.invoke('engine:status'),
  getRecentLogs: () => ipcRenderer.invoke('log:recent'),

  // Push events (main -> renderer). Returns an unsubscribe fn.
  on: (channel, callback) => {
    const allowed = [
      'engine:state', 'engine:stats', 'engine:frame',
      'engine:detection', 'log:entry',
    ];
    if (!allowed.includes(channel)) return () => {};
    const listener = (_e, payload) => callback(payload);
    ipcRenderer.on(channel, listener);
    return () => ipcRenderer.removeListener(channel, listener);
  },
};

contextBridge.exposeInMainWorld('autoPicker', api);
