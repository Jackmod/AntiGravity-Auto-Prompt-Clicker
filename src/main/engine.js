'use strict';

const { EventEmitter } = require('events');
const settings = require('./settings-store');
const capture = require('./detector/screen-capture');
const ocr = require('./detector/ocr');
const analyzer = require('./detector/analyzer');
const activeWindow = require('./detector/active-window');
const clicker = require('./automation/clicker');
const logger = require('./util/logger');

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
    this._pendingPoint = null;    // for double-scan confirmation (position-tolerant)
    this._lastFocusOk = null;     // last known Antigravity-focus state (for logging)
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
    this._pendingPoint = null;
    this.start();
  }

  stop() {
    this._clearTimer();
    this._pendingPoint = null;
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

      // --- Gate: only act while Antigravity is the focused window ---
      let captureDetection = cfg.detection;
      if (cfg.detection.requireActiveWindow) {
        const aw = await activeWindow.getActive();
        const focused = aw && activeWindow.titleMatches(aw.title, cfg.detection.activeWindowKeywords);
        if (focused !== this._lastFocusOk) {
          this._lastFocusOk = focused;
          logger.info(focused
            ? `Antigravity in focus — watching for prompts`
            : 'Waiting for Antigravity to be focused…');
        }
        if (!focused) {
          this._pendingPoint = null;
          this.emit('detection', { action: 'none', reason: 'Antigravity is not focused' });
          return; // finally{} schedules the next scan
        }
        // Look only inside the Antigravity window: faster, and clicks can only
        // ever land inside Antigravity.
        const r = aw.region;
        captureDetection = {
          ...cfg.detection,
          region: { mode: 'custom', x: r.left, y: r.top, width: r.width, height: r.height },
        };
      }

      const { jimp, region, scaleX, scaleY } = await capture.capture(captureDetection);

      if (cfg.general.showLivePreview) {
        capture.toThumbnail(jimp)
          .then((thumb) => this.emit('frame', { thumbnail: thumb }))
          .catch(() => {});
      }

      const png = await capture.toPngBuffer(jimp);
      const result = await ocr.recognizeWords(png);
      const decision = analyzer.analyze(result, cfg.detection, {
        scaleX, scaleY, region,
      });

      this.stats.scans += 1;
      await this._handleDecision(decision, cfg);
      this.emit('detection', decision);
    } catch (err) {
      logger.error(`Scan failed: ${err.message}`);
    } finally {
      this.stats.lastMs = Date.now() - started;
      this.emit('stats', { ...this.stats });
      this._busy = false;
      this._scheduleNext();
    }
  }

  async _handleDecision(decision, cfg) {
    if (decision.action === 'pause') {
      this._pendingPoint = null;
      logger.warn(decision.reason);
      this.pause(decision.reason);
      return;
    }

    if (decision.action !== 'click') {
      this._pendingPoint = null;
      return;
    }

    // From here: action === 'click'
    if (!cfg.automation.autoClick) {
      logger.info(`Detected "${decision.matched}" button — auto-click is off`);
      return;
    }

    // Double-scan confirmation: require the target two scans in a row, but
    // tolerate the small pixel jitter OCR produces between frames.
    if (cfg.automation.confirmDoubleScan) {
      const p = decision.point;
      const prev = this._pendingPoint;
      const TOL = 22;
      if (!prev || Math.abs(prev.x - p.x) > TOL || Math.abs(prev.y - p.y) > TOL) {
        this._pendingPoint = p;
        logger.info(`Saw "${decision.matched}" button — confirming on next scan…`);
        return;
      }
      this._pendingPoint = null;
    }

    // Cooldown between clicks.
    const now = Date.now();
    if (now - this._lastClickAt < cfg.automation.cooldownMs) return;

    // Rate limit.
    if (!this._withinRateLimit()) {
      this.pause(`Click rate limit (${cfg.safety.maxClicksPerMinute}/min) reached`);
      return;
    }

    if (cfg.automation.dryRun) {
      logger.action(`[DRY RUN] Would click "${decision.matched}" at (${decision.point.x}, ${decision.point.y})`);
      this._lastClickAt = now;
      return;
    }

    if (cfg.automation.clickDelayMs > 0) {
      await new Promise((r) => setTimeout(r, cfg.automation.clickDelayMs));
    }
    await clicker.clickAt(decision.point, cfg.automation);
    this._lastClickAt = Date.now();
    this._clickTimestamps.push(this._lastClickAt);
    this.stats.clicks += 1;
    logger.success(`Auto-confirmed "${decision.matched}"`);
  }
}

module.exports = new Engine();
