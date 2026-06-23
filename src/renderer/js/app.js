'use strict';

/* global AP_anim */
const AP = window.autoPicker;

/* ------------------------------------------------------------------
   Settings schema — drives the auto-generated Settings panel. Each
   field maps to a path in the settings store. Editing a control writes
   straight back through the bridge, so every option is genuinely live.
------------------------------------------------------------------- */
const SCHEMA = [
  {
    title: 'General', path: 'general', fields: [
      { key: 'autoStartWatching', type: 'toggle', name: 'Auto-start watching', desc: 'Begin watching the moment the app opens.' },
      { key: 'launchMinimized', type: 'toggle', name: 'Launch minimized', desc: 'Start hidden, controlled by the global hotkey.' },
      { key: 'showLivePreview', type: 'toggle', name: 'Live preview', desc: 'Stream a small screenshot to the Dashboard.' },
      { key: 'theme', type: 'select', name: 'Theme', desc: 'Overall look.', options: ['midnight', 'dark', 'light'] },
      { key: 'accent', type: 'color', name: 'Accent colour', desc: 'Primary highlight colour.' },
    ],
  },
  {
    title: 'Detection', path: 'detection', fields: [
      { key: 'requireActiveWindow', type: 'toggle', name: 'Only inside Antigravity', desc: 'Only watch & click inside windows whose title matches below.' },
      { key: 'onlyFocusedWindow', type: 'toggle', name: 'Focused window only', desc: 'Off = handle prompts in every Antigravity window (multiple bots). On = only the one in front.' },
      { key: 'activeWindowKeywords', type: 'list', name: 'Window title contains', desc: 'A window title must contain one of these to count.' },
      { key: 'scanIntervalMs', type: 'range', name: 'Scan interval', desc: 'Time between screen scans. Higher = lighter on the CPU.', min: 300, max: 3000, step: 100, unit: 'ms' },
      { key: 'minConfidence', type: 'range', name: 'OCR confidence', desc: 'Minimum confidence before a word is trusted.', min: 40, max: 95, step: 1, unit: '%' },
      { key: 'strictMatch', type: 'toggle', name: 'Strict button matching', desc: 'Only click a "Yes" that sits next to a No/Cancel or inside a prompt. Stops it clicking the word "yes" in text.' },
      { key: 'pauseOnUnknown', type: 'toggle', name: 'Pause on anything unknown', desc: 'Pause when a prompt appears but no clear "Yes" is found.' },
      { key: 'requireTriggerPhrase', type: 'toggle', name: 'Require prompt phrase', desc: 'Extra safety: also require a known prompt phrase before clicking.' },
      { key: 'acceptKeywords', type: 'list', name: 'Accept words', desc: 'Words that count as "Yes" (comma separated).' },
      { key: 'rejectKeywords', type: 'list', name: 'Reject words', desc: 'Words treated as "No" — never auto-clicked.' },
      { key: 'triggerPhrases', type: 'list', name: 'Prompt phrases', desc: 'Phrases that indicate a real approval prompt.' },
    ],
  },
  {
    title: 'Automation', path: 'automation', fields: [
      { key: 'autoClick', type: 'toggle', name: 'Auto-click', desc: 'Master switch — actually move the mouse and click.' },
      { key: 'dryRun', type: 'toggle', name: 'Dry run', desc: 'Detect and log, but never click. Great for testing.' },
      { key: 'multiClick', type: 'toggle', name: 'Click all at once', desc: 'When several prompts pop up together, click every Yes in one pass.' },
      { key: 'maxClicksPerScan', type: 'range', name: 'Max clicks per pass', desc: 'Safety cap on how many prompts are clicked in one scan.', min: 1, max: 20, step: 1, unit: '' },
      { key: 'interClickMs', type: 'range', name: 'Stagger between clicks', desc: 'Small gap between clicks in a burst so it stays smooth.', min: 0, max: 800, step: 10, unit: 'ms' },
      { key: 'confirmDoubleScan', type: 'toggle', name: 'Double-confirm', desc: 'Require two scans in a row before clicking (more stable).' },
      { key: 'clickDelayMs', type: 'range', name: 'Click delay', desc: 'Pause after detection before clicking.', min: 0, max: 1500, step: 20, unit: 'ms' },
      { key: 'cooldownMs', type: 'range', name: 'Click cooldown', desc: 'Minimum gap between two auto-clicks.', min: 200, max: 5000, step: 100, unit: 'ms' },
      { key: 'restoreCursor', type: 'toggle', name: 'Restore cursor', desc: 'Return the cursor to where it was after clicking.' },
    ],
  },
  {
    title: 'Safety', path: 'safety', fields: [
      { key: 'failSafe', type: 'toggle', name: 'Corner fail-safe', desc: 'Slam the cursor into a screen corner to abort instantly.' },
      { key: 'maxClicksPerMinute', type: 'range', name: 'Max clicks / min', desc: 'Hard ceiling — the watcher pauses if exceeded.', min: 1, max: 60, step: 1, unit: '' },
      { key: 'pauseHotkey', type: 'text', name: 'Toggle hotkey', desc: 'Global shortcut to start/pause (needs restart to re-bind).' },
    ],
  },
];

let settings = null;

/* ---------------- bootstrap ---------------- */
async function init() {
  document.body.classList.toggle('is-mac', AP.platform === 'darwin');
  wireWindowControls();
  wireNav();
  settings = await AP.getSettings();
  applyAppearance();
  buildSettings();
  wireEngineEvents();
  hydrateLogs();
  refreshStatus();
  document.getElementById('hotkeyHint').textContent =
    `Global toggle: ${settings.safety.pauseHotkey}`;

  // Pause all animations while the window is hidden/minimized — zero background cost.
  document.addEventListener('visibilitychange', () => {
    document.body.classList.toggle('anim-paused', document.hidden);
  });
}

/* ---------------- window + nav ---------------- */
function wireWindowControls() {
  document.getElementById('winControls').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-win]');
    if (!btn) return;
    const a = btn.dataset.win;
    if (a === 'min') AP.windowMinimize();
    else if (a === 'max') AP.windowMaximize();
    else if (a === 'close') AP.windowClose();
  });
}

function wireNav() {
  document.querySelectorAll('.nav-item').forEach((item) => {
    item.addEventListener('click', () => {
      const view = item.dataset.view;
      document.querySelectorAll('.nav-item').forEach((n) => n.classList.toggle('active', n === item));
      document.querySelectorAll('.view').forEach((v) =>
        v.classList.toggle('active', v.dataset.view === view));
    });
  });
}

/* ---------------- appearance ---------------- */
function applyAppearance() {
  document.body.dataset.theme = settings.general.theme;
  document.documentElement.style.setProperty('--accent', settings.general.accent);
}

/* ---------------- settings panel ---------------- */
function buildSettings() {
  const root = document.getElementById('settingsRoot');
  root.innerHTML = '';
  for (const group of SCHEMA) {
    const g = document.createElement('div');
    g.className = 'set-group';
    g.innerHTML = `<h3>${group.title}</h3>`;
    for (const f of group.fields) {
      g.appendChild(buildRow(group.path, f));
    }
    root.appendChild(g);
  }
  document.getElementById('resetBtn').onclick = async () => {
    settings = await AP.resetSettings();
    applyAppearance();
    buildSettings();
    toast('Settings reset to defaults', 'success');
  };
}

function buildRow(path, f) {
  const row = document.createElement('div');
  row.className = 'set-row';
  const cur = settings[path][f.key];

  const info = document.createElement('div');
  info.className = 'set-info';
  info.innerHTML = `<div class="set-name">${f.name}</div><div class="set-desc">${f.desc}</div>`;
  row.appendChild(info);

  const control = document.createElement('div');
  control.className = 'set-control';
  control.appendChild(buildControl(path, f, cur));
  row.appendChild(control);
  return row;
}

function buildControl(path, f, cur) {
  const save = (val) => commit(path, f.key, val);

  if (f.type === 'toggle') {
    const label = document.createElement('label');
    label.className = 'switch';
    label.innerHTML = '<input type="checkbox"><span class="track"></span><span class="thumb"></span>';
    const input = label.querySelector('input');
    input.checked = !!cur;
    input.onchange = () => save(input.checked);
    return label;
  }

  if (f.type === 'range') {
    const wrap = document.createElement('div');
    wrap.className = 'range-wrap';
    const input = document.createElement('input');
    input.type = 'range'; input.min = f.min; input.max = f.max; input.step = f.step; input.value = cur;
    const val = document.createElement('span');
    val.className = 'range-val';
    val.textContent = `${cur}${f.unit}`;
    input.oninput = () => { val.textContent = `${input.value}${f.unit}`; };
    input.onchange = () => save(Number(input.value));
    wrap.append(input, val);
    return wrap;
  }

  if (f.type === 'select') {
    const sel = document.createElement('select');
    sel.className = 'select-input';
    for (const o of f.options) {
      const opt = document.createElement('option');
      opt.value = o; opt.textContent = o[0].toUpperCase() + o.slice(1);
      if (o === cur) opt.selected = true;
      sel.appendChild(opt);
    }
    sel.onchange = () => { save(sel.value); if (f.key === 'theme') applyAppearance(); };
    return sel;
  }

  if (f.type === 'color') {
    const input = document.createElement('input');
    input.type = 'color'; input.value = cur; input.className = 'num-input';
    input.style.width = '60px'; input.style.padding = '2px'; input.style.height = '36px';
    input.onchange = () => { save(input.value); applyAppearance(); };
    return input;
  }

  if (f.type === 'list') {
    const input = document.createElement('input');
    input.type = 'text'; input.className = 'text-input';
    input.value = Array.isArray(cur) ? cur.join(', ') : '';
    input.onchange = () => save(input.value.split(',').map((s) => s.trim()).filter(Boolean));
    return input;
  }

  // text
  const input = document.createElement('input');
  input.type = 'text'; input.className = 'text-input'; input.value = cur;
  input.onchange = () => save(input.value);
  return input;
}

async function commit(path, key, value) {
  settings[path][key] = value;
  await AP.updateSettings({ [path]: { [key]: value } });
}

/* ---------------- engine control ---------------- */
const toggleBtn = document.getElementById('toggleBtn');
toggleBtn.addEventListener('click', async () => {
  AP_anim.ripple(toggleBtn);
  const status = await AP.getStatus();
  if (status.state === 'watching') await AP.pause();
  else await AP.resume();
});

async function refreshStatus() {
  const { state, stats } = await AP.getStatus();
  setState(state);
  if (stats) {
    AP_anim.countTo(document.getElementById('statScans'), stats.scans || 0);
    AP_anim.countTo(document.getElementById('statClicks'), stats.clicks || 0);
  }
}

function setState(state) {
  const orb = document.getElementById('orb');
  const pill = document.getElementById('statePill');
  orb.dataset.state = state;
  pill.dataset.state = state;
  const labels = { idle: 'Idle', watching: 'Watching', paused: 'Paused' };
  const subs = {
    idle: 'Press start to begin watching',
    watching: 'Scanning for approval prompts…',
    paused: 'Stopped — your attention may be needed',
  };
  document.getElementById('orbStatus').textContent = labels[state] || state;
  document.getElementById('orbSub').textContent = subs[state] || '';
  document.getElementById('statePillText').textContent = labels[state] || state;
  const active = state === 'watching';
  document.body.classList.toggle('is-watching', active);
  toggleBtn.classList.toggle('is-active', active);
  toggleBtn.querySelector('.btn-label').textContent = active ? 'Pause watching' : 'Start watching';
}

/* ---------------- live events ---------------- */
function wireEngineEvents() {
  AP.on('engine:state', ({ state, reason }) => {
    setState(state);
    if (state === 'paused' && reason) toast(reason, 'warn');
    if (state === 'watching') toast('Watching started', 'success');
  });

  let lastClicks = 0;
  AP.on('engine:stats', (stats) => {
    AP_anim.countTo(document.getElementById('statScans'), stats.scans || 0);
    const clicksEl = document.getElementById('statClicks');
    AP_anim.countTo(clicksEl, stats.clicks || 0);
    if ((stats.clicks || 0) > lastClicks) {
      lastClicks = stats.clicks;
      clicksEl.classList.remove('bump');
      void clicksEl.offsetWidth; // restart animation
      clicksEl.classList.add('bump');
    }
    AP_anim.countTo(document.getElementById('statMs'), stats.lastMs || 0, 'ms');
  });

  AP.on('engine:frame', ({ thumbnail }) => {
    const img = document.getElementById('previewImg');
    const empty = document.querySelector('.preview-empty');
    img.src = thumbnail; img.hidden = false;
    if (empty) empty.style.display = 'none';
  });

  AP.on('engine:detection', (d) => {
    const el = document.getElementById('detectLine');
    const tagClass = d.action === 'click' ? 'click' : d.action === 'pause' ? 'pause' : 'none';
    const label = { click: 'CLICK', pause: 'PAUSE', none: 'IDLE' }[d.action] || d.action;
    el.innerHTML = `<span class="tag ${tagClass}">${label}</span>${escapeHtml(d.reason || '')}`;
    if (d.action === 'click') {
      const orb = document.getElementById('orb');
      orb.classList.remove('pop');
      void orb.offsetWidth;
      orb.classList.add('pop');
    }
  });

  AP.on('log:entry', (entry) => appendLog(entry));
}

/* ---------------- activity log ---------------- */
async function hydrateLogs() {
  const recent = await AP.getRecentLogs();
  recent.slice(-60).forEach(appendLog);
}

function appendLog(entry) {
  const feed = document.getElementById('logFeed');
  const row = document.createElement('div');
  row.className = `log-entry ${entry.level}`;
  const time = new Date(entry.time).toLocaleTimeString();
  row.innerHTML = `<span class="ts">${time}</span><span class="lvl">${entry.level}</span><span class="msg">${escapeHtml(entry.message)}</span>`;
  feed.prepend(row);
  while (feed.children.length > 120) feed.removeChild(feed.lastChild);
}

/* ---------------- toast ---------------- */
let toastTimer = null;
function toast(message, kind = 'info') {
  const host = document.getElementById('toastHost');
  const t = document.createElement('div');
  t.className = `toast ${kind}`;
  t.textContent = message;
  host.appendChild(t);
  setTimeout(() => {
    t.classList.add('leaving');
    setTimeout(() => t.remove(), 320);
  }, 3600);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

window.addEventListener('DOMContentLoaded', init);
