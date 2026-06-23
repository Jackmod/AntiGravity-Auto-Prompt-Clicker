'use strict';

const Store = require('electron-store');

/**
 * Central settings definition. Every value here is a real, wired-up control
 * surfaced in the Settings panel — changing it changes engine behaviour live.
 */
const DEFAULTS = {
  general: {
    autoStartWatching: false,   // begin watching as soon as the app opens
    launchMinimized: false,     // start hidden in the tray/dock
    theme: 'midnight',          // 'midnight' | 'dark' | 'light'
    accent: '#7c5cff',          // UI accent colour
    showLivePreview: true,      // stream a small screenshot thumbnail to the UI
  },
  detection: {
    scanIntervalMs: 800,        // time between screen scans (higher = lighter CPU)
    minConfidence: 60,          // minimum OCR confidence (0-100) to trust a word
    requireActiveWindow: true,  // ONLY act while Antigravity is the focused window
    activeWindowKeywords: ['antigravity'], // title must contain one of these
    acceptKeywords: ['yes', 'accept', 'allow', 'approve', 'confirm'],
    rejectKeywords: ['no', 'reject', 'deny', 'cancel', 'decline'],
    strictMatch: true,          // only click a Yes that's paired with a No/Cancel
                                // or inside a known prompt (avoids clicking prose)
    requireTriggerPhrase: false, // extra safety: also require a prompt phrase to click
    triggerPhrases: [
      'allow this', 'do you want', 'run command', 'apply changes',
      'accept edits', 'proceed', 'would you like', 'permission',
    ],
    pauseOnUnknown: true,       // pause when a prompt appears but no Yes is found
    region: { mode: 'full', x: 0, y: 0, width: 0, height: 0 }, // 'full' | 'custom'
  },
  automation: {
    autoClick: true,            // master switch for actually clicking
    dryRun: false,              // detect + log but never move the mouse
    clickDelayMs: 220,          // wait after detection before clicking
    confirmDoubleScan: true,    // require two consecutive matches before clicking
    cooldownMs: 1500,           // minimum gap between two auto-clicks
    moveDurationMs: 0,          // mouse travel time (0 = instant)
    restoreCursor: true,        // return cursor to its previous spot after click
  },
  safety: {
    failSafe: true,             // slam mouse into a screen corner to abort nut-js
    maxClicksPerMinute: 20,     // hard ceiling; engine pauses if exceeded
    pauseHotkey: 'CommandOrControl+Shift+P', // global toggle hotkey
  },
};

const store = new Store({ name: 'auto-picker-settings', defaults: DEFAULTS });

/** Deep-merge a partial patch into the stored settings. */
function deepMerge(target, patch) {
  for (const key of Object.keys(patch)) {
    const val = patch[key];
    if (val && typeof val === 'object' && !Array.isArray(val)) {
      target[key] = deepMerge(target[key] ? { ...target[key] } : {}, val);
    } else {
      target[key] = val;
    }
  }
  return target;
}

module.exports = {
  DEFAULTS,
  get all() {
    // Merge over defaults so newly-added keys are always present.
    return deepMerge(JSON.parse(JSON.stringify(DEFAULTS)), store.store || {});
  },
  get(path) { return store.get(path); },
  /** Apply a partial settings object and return the merged result. */
  update(patch) {
    const merged = deepMerge(this.all, patch || {});
    store.store = merged;
    return merged;
  },
  reset() {
    store.clear();
    store.store = JSON.parse(JSON.stringify(DEFAULTS));
    return this.all;
  },
};
