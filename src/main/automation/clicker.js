'use strict';

const { mouse, Button, Point, straightTo } = require('@nut-tree-fork/nut-js');
const logger = require('../util/logger');

/**
 * Mouse automation wrapper around nut-js. All clicks flow through here so
 * safety options (fail-safe, dry-run, cursor restore, travel time) live in
 * one place.
 */

function configure(safety, automation) {
  // nut-js fail-safe: ramming the cursor into a screen corner aborts actions.
  mouse.config.autoDelayMs = 1;
  if (typeof safety.failSafe === 'boolean') {
    // Some nut-js builds expose this as a provider option; guard defensively.
    try { mouse.config.failSafe = safety.failSafe; } catch (_) { /* optional */ }
  }
  mouse.config.mouseSpeed = automation.moveDurationMs > 0
    ? Math.max(1, Math.round(2000 / Math.max(1, automation.moveDurationMs)))
    : 9999; // effectively instant
}

/**
 * Move to a point and left-click it.
 * @param {{x:number,y:number}} point  logical screen coordinates
 * @param {object} automation  automation settings slice
 */
async function clickAt(point, automation) {
  let previous = null;
  if (automation.restoreCursor) {
    try { previous = await mouse.getPosition(); } catch (_) { previous = null; }
  }

  if (automation.moveDurationMs > 0) {
    await mouse.move(straightTo(new Point(point.x, point.y)));
  } else {
    await mouse.setPosition(new Point(point.x, point.y));
  }
  await mouse.click(Button.LEFT);
  logger.action(`Clicked at (${point.x}, ${point.y})`);

  if (previous) {
    // Small settle delay so the target app registers the click before we leave.
    await new Promise((r) => setTimeout(r, 60));
    try { await mouse.setPosition(previous); } catch (_) { /* ignore */ }
  }
}

module.exports = { clickAt, configure };
