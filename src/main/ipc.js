'use strict';

const { ipcMain } = require('electron');
const settings = require('./settings-store');
const engine = require('./engine');
const logger = require('./util/logger');

/**
 * Wires the renderer <-> main process channels and forwards engine + logger
 * events to the active window. Kept separate from main.js so window/lifecycle
 * code and message routing stay readable.
 */
function registerIpc(getWindow) {
  const send = (channel, payload) => {
    const win = getWindow();
    if (win && !win.isDestroyed()) win.webContents.send(channel, payload);
  };

  // --- Renderer -> Main (request/response) ---
  ipcMain.handle('settings:get', () => settings.all);
  ipcMain.handle('settings:update', (_e, patch) => {
    const merged = settings.update(patch);
    engine.emit('settings-changed', merged);
    return merged;
  });
  ipcMain.handle('settings:reset', () => settings.reset());

  ipcMain.handle('engine:start', () => { engine.start(); return engine.state; });
  ipcMain.handle('engine:stop', () => { engine.stop(); return engine.state; });
  ipcMain.handle('engine:pause', () => { engine.pause('paused by user'); return engine.state; });
  ipcMain.handle('engine:resume', () => { engine.resume(); return engine.state; });
  ipcMain.handle('engine:toggle', () => { engine.toggle(); return engine.state; });
  ipcMain.handle('engine:status', () => ({ state: engine.state, stats: engine.stats }));
  ipcMain.handle('log:recent', () => logger.recent());

  // Window controls
  ipcMain.handle('window:minimize', () => { const w = getWindow(); if (w) w.minimize(); });
  ipcMain.handle('window:maximize', () => {
    const w = getWindow();
    if (!w) return;
    if (w.isMaximized()) w.unmaximize(); else w.maximize();
  });
  ipcMain.handle('window:close', () => { const w = getWindow(); if (w) w.close(); });

  // --- Main -> Renderer (push) ---
  engine.on('state', (p) => send('engine:state', p));
  engine.on('stats', (p) => send('engine:stats', p));
  engine.on('frame', (p) => send('engine:frame', p));
  engine.on('detection', (p) => send('engine:detection', p));
  logger.subscribe((entry) => send('log:entry', entry));
}

module.exports = { registerIpc };
