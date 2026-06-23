'use strict';

const path = require('path');
const {
  app, BrowserWindow, globalShortcut, nativeTheme, Menu,
} = require('electron');
const settings = require('./settings-store');
const engine = require('./engine');
const logger = require('./util/logger');
const { registerIpc } = require('./ipc');

const isDev = process.argv.includes('--dev');
let mainWindow = null;

// --- Memory trimming ---------------------------------------------------------
// Cap the V8 heap and disable some Chromium subsystems we don't use. The watch
// loop runs in the main process, so throttling the (mostly idle) renderer is
// free and keeps background memory/CPU low.
app.commandLine.appendSwitch('js-flags', '--max-old-space-size=256');
app.commandLine.appendSwitch('disable-features', 'CalculateNativeWinOcclusion');

function createWindow() {
  const cfg = settings.all;
  nativeTheme.themeSource = cfg.general.theme === 'light' ? 'light' : 'dark';

  mainWindow = new BrowserWindow({
    width: 1040,
    height: 720,
    minWidth: 880,
    minHeight: 600,
    show: false,
    backgroundColor: '#0b0b14',
    icon: path.join(__dirname, '..', '..', 'build', 'icon.png'),
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    frame: process.platform === 'darwin',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, '..', 'preload', 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  Menu.setApplicationMenu(null);
  mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));

  mainWindow.once('ready-to-show', () => {
    if (!cfg.general.launchMinimized) mainWindow.show();
    if (isDev) mainWindow.webContents.openDevTools({ mode: 'detach' });
    if (cfg.general.autoStartWatching) engine.start();
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

function registerHotkey() {
  globalShortcut.unregisterAll();
  const hotkey = settings.all.safety.pauseHotkey;
  if (!hotkey) return;
  const ok = globalShortcut.register(hotkey, () => engine.toggle());
  if (ok) logger.info(`Global toggle hotkey: ${hotkey}`);
  else logger.warn(`Could not register hotkey: ${hotkey}`);
}

// Re-apply hotkey + theme whenever settings change.
engine.on('settings-changed', (cfg) => {
  nativeTheme.themeSource = cfg.general.theme === 'light' ? 'light' : 'dark';
  registerHotkey();
});

// Single-instance lock so we never run two watchers at once.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) { mainWindow.show(); mainWindow.focus(); }
  });

  app.whenReady().then(() => {
    registerIpc(() => mainWindow);
    createWindow();
    registerHotkey();

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });
}

app.on('will-quit', () => globalShortcut.unregisterAll());
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
