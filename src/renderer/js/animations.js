'use strict';

/**
 * Lightweight motion helpers used by the UI. Everything here is throttled and
 * uses requestAnimationFrame so the interface stays fluid without burning CPU.
 */
window.AP_anim = (() => {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /** Animate a number from its current value to `to`, easing out. */
  function countTo(el, to, suffix = '') {
    const from = parseFloat(el.dataset.val || '0') || 0;
    el.dataset.val = String(to);
    if (reduced || from === to) { el.firstChild ? renderNum(el, to, suffix) : (el.textContent = to + suffix); return; }
    const dur = 420;
    const start = performance.now();
    function frame(now) {
      const t = Math.min(1, (now - start) / dur);
      const eased = 1 - Math.pow(1 - t, 3);
      const val = Math.round(from + (to - from) * eased);
      renderNum(el, val, suffix);
      if (t < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  function renderNum(el, val, suffix) {
    if (suffix === 'ms') el.innerHTML = `${val}<small>ms</small>`;
    else el.textContent = val + suffix;
  }

  /** A small ripple feedback on click. */
  function ripple(el) {
    if (reduced) return;
    el.animate(
      [{ transform: 'scale(1)' }, { transform: 'scale(0.96)' }, { transform: 'scale(1)' }],
      { duration: 220, easing: 'cubic-bezier(0.22,1,0.36,1)' },
    );
  }

  return { countTo, ripple, reduced };
})();
