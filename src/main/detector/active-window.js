'use strict';

const { getActiveWindow, getWindows } = require('@nut-tree-fork/nut-js');

/**
 * Foreground-window detection. This is how Auto Picker knows you are *in
 * Antigravity* — it reads the title of the currently focused window and the
 * region it occupies. Far more reliable than guessing from on-screen text.
 */

/** @returns {Promise<{title:string, region:object}|null>} */
async function getActive() {
  try {
    const w = await getActiveWindow();
    const [title, region] = await Promise.all([w.getTitle(), w.getRegion()]);
    return { title: title || '', region };
  } catch (_) {
    return null; // window provider unavailable (rare) — caller decides what to do
  }
}

/** Case-insensitive: does the window title contain any of the keywords? */
function titleMatches(title, keywords) {
  if (!keywords || keywords.length === 0) return true;
  const t = (title || '').toLowerCase();
  return keywords.some((k) => t.includes(String(k).toLowerCase()));
}

/**
 * Every open window whose title matches the keywords. Used to support several
 * bots at once: prompts in any Antigravity window/pane can be handled, not just
 * the focused one.
 * @returns {Promise<Array<{title:string, region:object}>>}
 */
async function getMatchingWindows(keywords) {
  try {
    const wins = await getWindows();
    const out = [];
    for (const w of wins) {
      let title = '';
      try { title = await w.getTitle(); } catch (_) { /* skip */ }
      if (!titleMatches(title, keywords)) continue;
      let region = null;
      try { region = await w.getRegion(); } catch (_) { region = null; }
      if (region && region.width > 0 && region.height > 0) out.push({ title, region });
    }
    return out;
  } catch (_) {
    return [];
  }
}

/** Is a point inside any of the given window regions? */
function pointInWindows(point, windows) {
  return windows.some((w) => {
    const r = w.region;
    return point.x >= r.left && point.x <= r.left + r.width
      && point.y >= r.top && point.y <= r.top + r.height;
  });
}

module.exports = { getActive, getMatchingWindows, titleMatches, pointInWindows };
