'use strict';

const Store = require('electron-store');

// Bump when detection keyword/phrase logic changes so existing installs pick up
// the new safer lists instead of keeping stale persisted ones.
const SCHEMA_VERSION = 2;

/**
 * Central settings definition. Every value here is a real, wired-up control
 * surfaced in the Settings panel — changing it changes engine behaviour live.
 */
const DEFAULTS = {
  _schemaVersion: SCHEMA_VERSION,
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
    requireActiveWindow: true,  // ONLY act inside Antigravity windows
    onlyFocusedWindow: false,   // true = only the focused one; false = all Antigravity windows
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
    multiClick: true,           // click EVERY Yes found in one pass (multiple bots)
    maxClicksPerScan: 8,        // safety cap on clicks in a single scan
    interClickMs: 130,          // stagger between consecutive clicks in a burst
    clickDelayMs: 220,          // wait after detection before clicking
    confirmDoubleScan: true,    // require two consecutive matches before clicking
    cooldownMs: 1500,           // per-button: don't re-click the same spot within this
    moveDurationMs: 0,          // mouse travel time (0 = instant)
    restoreCursor: true,        // return cursor to its previous spot after click
  },
  safety: {
    failSafe: true,             // slam mouse into a screen corner to abort nut-js
    maxClicksPerMinute: 20,     // hard ceiling; engine pauses if exceeded
    pauseHotkey: 'CommandOrControl+Shift+P', // global toggle hotkey
  },
};

// NOTE: no `defaults` here on purpose — if defaults were applied at the store
// layer, store.store would always report the current _schemaVersion and the
// migration below could never detect an older install. Defaults are merged in
// the `all` getter instead.
const store = new Store({ name: 'auto-picker-settings' });

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
    const stored = store.store || {};
    // Merge over defaults so newly-added keys are always present.
    const merged = deepMerge(JSON.parse(JSON.stringify(DEFAULTS)), stored);
    // Migration: when detection logic changes, refresh the keyword/phrase lists
    // (arrays are replaced wholesale by the merge, so stale ones would persist).
    if ((stored._schemaVersion || 0) < SCHEMA_VERSION) {
      merged.detection.acceptKeywords = DEFAULTS.detection.acceptKeywords.slice();
      merged.detection.rejectKeywords = DEFAULTS.detection.rejectKeywords.slice();
      merged.detection.triggerPhrases = DEFAULTS.detection.triggerPhrases.slice();
      merged.detection.requireTriggerPhrase = DEFAULTS.detection.requireTriggerPhrase;
      merged._schemaVersion = SCHEMA_VERSION;
      store.store = merged; // persist the migration once
    }
    return merged;
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
