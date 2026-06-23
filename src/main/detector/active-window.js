'use strict';

const { getActiveWindow } = require('@nut-tree-fork/nut-js');

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

module.exports = { getActive, titleMatches };
