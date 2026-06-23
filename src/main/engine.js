'use strict';

const { EventEmitter } = require('events');
const settings = require('./settings-store');
const capture = require('./detector/screen-capture');
const ocr = require('./detector/ocr');
const analyzer = require('./detector/analyzer');
const activeWindow = require('./detector/active-window');
const clicker = require('./automation/clicker');
const logger = require('./util/logger');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * The watch engine. A small state machine driven by a self-scheduling loop.
 *
 *   idle    -> not scanning
 *   watching-> scanning each scanIntervalMs, may click
 *   paused  -> scanning is halted because something needs a human
 *
 * Emits:
 *   'state'      ({ state })                  whenever the state changes
 *   'stats'      ({ scans, clicks, lastMs })  per-scan timing/counters
 *   'frame'      ({ thumbnail })              live preview (if enabled)
 *   'detection'  ({ action, reason, ... })    result of each analysis
 */
class Engine extends EventEmitter {
  constructor() {
    super();
    this.state = 'idle';
    this._timer = null;
    this._busy = false;
    this._lastClickAt = 0;
    this._clickTimestamps = [];   // for rate limiting
    this._pendingPoints = [];     // targets seen last scan (double-scan confirmation)
    this._recentClicks = [];      // {x,y,time} to avoid re-clicking the same button
    this._lastFocusOk = null;     // last known Antigravity-present state (for logging)
    this.stats = { scans: 0, clicks: 0, lastMs: 0 };
  }

  _setState(next, reason) {
    if (this.state === next) return;
    this.state = next;
    logger.info(`State -> ${next}${reason ? ` (${reason})` : ''}`);
    this.emit('state', { state: next, reason: reason || null });
  }

  start() {
    if (this.state === 'watching') return;
    clicker.configure(settings.all.safety, settings.all.automation);
    this._setState('watching');
    this._scheduleNext(0);
  }

  pause(reason) {
    this._setState('paused', reason);
    this._clearTimer();
  }

  resume() {
    this._pendingPoints = [];
    this._recentClicks = [];
    this.start();
  }

  stop() {
    this._clearTimer();
    this._pendingPoints = [];
    this._recentClicks = [];
    this._setState('idle');
  }

  toggle() {
    if (this.state === 'watching') this.pause('toggled off');
    else this.resume();
  }

  _clearTimer() {
    if (this._timer) { clearTimeout(this._timer); this._timer = null; }
  }

  _scheduleNext(delayOverride) {
    this._clearTimer();
    if (this.state !== 'watching') return;
    const delay = delayOverride != null
      ? delayOverride
      : settings.all.detection.scanIntervalMs;
    this._timer = setTimeout(() => this._tick(), Math.max(50, delay));
  }

  _withinRateLimit() {
    const now = Date.now();
    const max = settings.all.safety.maxClicksPerMinute;
    this._clickTimestamps = this._clickTimestamps.filter((t) => now - t < 60000);
    return this._clickTimestamps.length < max;
  }

  async _tick() {
    if (this._busy || this.state !== 'watching') return;
    this._busy = true;
    const started = Date.now();
    try {
      const cfg = settings.all;

      const det = cfg.detection;

      // --- Gate: only act inside Antigravity windows ---
      let matchWindows = null;
      if (det.requireActiveWindow) {
        if (det.onlyFocusedWindow) {
          const aw = await activeWindow.getActive();
          matchWindows = (aw && activeWindow.titleMatches(aw.title, det.activeWindowKeywords))
            ? [aw] : [];
        } else {
          matchWindows = await activeWindow.getMatchingWindows(det.activeWindowKeywords);
        }
        const present = matchWindows.length > 0;
        if (present !== this._lastFocusOk) {
          this._lastFocusOk = present;
          logger.info(present
            ? `Antigravity detected (${matchWindows.length} window${matchWindows.length > 1 ? 's' : ''}) — watching`
            : 'Waiting for an Antigravity window…');
        }
        if (!present) {
          this._pendingPoints = [];
          this.emit('detection', { action: 'none', reason: 'No Antigravity window' });
          return; // finally{} schedules the next scan
        }
      }

      // Capture the full screen so prompts in every window/pane are seen, then
      // OCR once. Clicks are filtered to Antigravity windows below.
      const { jimp, region, scaleX, scaleY } = await capture.capture({
        ...det, region: { mode: 'full' },
      });

      if (cfg.general.showLivePreview) {
        capture.toThumbnail(jimp)
          .then((thumb) => this.emit('frame', { thumbnail: thumb }))
          .catch(() => {});
      }

      const png = await capture.toPngBuffer(jimp);
      const result = await ocr.recognizeWords(png);
      const analysis = analyzer.analyze(result, det, { scaleX, scaleY, region });

      // Only act on prompts located inside an Antigravity window.
      if (matchWindows) {
        analysis.clicks = analysis.clicks
          .filter((c) => activeWindow.pointInWindows(c.point, matchWindows));
      }

      this.stats.scans += 1;
      await this._handleAnalysis(analysis, cfg);
      this.emit('detection', {
        action: analysis.pause ? 'pause' : (analysis.clicks.length ? 'click' : 'none'),
        reason: analysis.pause ? analysis.pause.reason : analysis.reason,
        count: analysis.clicks.length,
      });
    } catch (err) {
      logger.error(`Scan failed: ${err.message}`);
    } finally {
      this.stats.lastMs = Date.now() - started;
      this.emit('stats', { ...this.stats });
      this._busy = false;
      this._scheduleNext();
    }
  }

  async _handleAnalysis(analysis, cfg) {
    // A real prompt we can't safely resolve -> pause for the human.
    if (analysis.pause) {
      this._pendingPoints = [];
      logger.warn(analysis.pause.reason);
      this.pause(analysis.pause.reason);
      return;
    }

    const all = analysis.clicks || [];
    const auto = cfg.automation;
    const TOL = 28;
    const near = (a, b) => Math.abs(a.x - b.x) <= TOL && Math.abs(a.y - b.y) <= TOL;

    if (!all.length) { this._pendingPoints = []; return; }

    if (!auto.autoClick) {
      logger.info(`Detected ${all.length} Yes button${all.length > 1 ? 's' : ''} — auto-click is off`);
      this._pendingPoints = all.map((c) => c.point);
      return;
    }

    const now = Date.now();
    this._recentClicks = this._recentClicks.filter((r) => now - r.time < auto.cooldownMs);
    const prev = this._pendingPoints;

    // A target is ready if it isn't on per-button cooldown and (when enabled)
    // was already seen on the previous scan.
    const ready = all.filter((c) => {
      if (this._recentClicks.some((r) => near(r, c.point))) return false;
      if (auto.confirmDoubleScan && !prev.some((p) => near(p, c.point))) return false;
      return true;
    });
    this._pendingPoints = all.map((c) => c.point); // remember for next scan

    if (!ready.length) {
      if (auto.confirmDoubleScan) {
        logger.info(`Saw ${all.length} Yes button${all.length > 1 ? 's' : ''} — confirming on next scan…`);
      }
      return;
    }

    // Click all ready targets (a controlled burst), or just one if multiClick off.
    const burst = (auto.multiClick ? ready : ready.slice(0, 1)).slice(0, auto.maxClicksPerScan);
    if (auto.clickDelayMs > 0) await sleep(auto.clickDelayMs);

    let clicked = 0;
    for (const c of burst) {
      if (!this._withinRateLimit()) {
        this.pause(`Click rate limit (${cfg.safety.maxClicksPerMinute}/min) reached`);
        break;
      }
      if (auto.dryRun) {
        logger.action(`[DRY RUN] Would click "${c.matched}" at (${c.point.x}, ${c.point.y})`);
      } else {
        await clicker.clickAt(c.point, auto);
        logger.success(`Auto-confirmed "${c.matched}" at (${c.point.x}, ${c.point.y})`);
      }
      const t = Date.now();
      this._recentClicks.push({ x: c.point.x, y: c.point.y, time: t });
      this._lastClickAt = t;
      this._clickTimestamps.push(t);
      this.stats.clicks += 1;
      clicked += 1;
      if (clicked < burst.length && auto.interClickMs > 0) await sleep(auto.interClickMs);
    }
    if (clicked > 1) logger.info(`Handled ${clicked} prompts in one burst`);
  }
}

module.exports = new Engine();
