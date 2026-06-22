'use strict';

const path = require('path');
const os = require('os');
const { createWorker } = require('tesseract.js');
const logger = require('../util/logger');

/**
 * Resolve a writable directory to cache the downloaded OCR language model.
 * Inside Electron this is the per-user app-data folder (the app bundle itself
 * is read-only once packaged); outside Electron we fall back to the temp dir.
 */
function resolveCachePath() {
  try {
    // Lazy require so this module still loads in a plain-Node test harness.
    const { app } = require('electron');
    if (app && app.getPath) return app.getPath('userData');
  } catch (_) { /* not running under Electron */ }
  return path.join(os.tmpdir(), 'auto-picker-ocr');
}

/**
 * OCR engine wrapper. A single Tesseract worker is created lazily and reused
 * for the lifetime of the app so we never pay worker startup on the hot path.
 * recognize() returns word-level boxes which the analyzer uses to locate the
 * exact button to click.
 */
let workerPromise = null;

async function getWorker() {
  if (!workerPromise) {
    logger.info('Initializing OCR engine (one-time)…');
    const cachePath = resolveCachePath();
    workerPromise = createWorker('eng', 1, {
      // Quiet by default; tesseract.js downloads the English model on first run
      // and caches it in a writable per-user directory.
      cachePath,
      logger: () => {},
    }).then(async (worker) => {
      // Treat the screenshot as a sparse block of text — good for scattered
      // dialog labels and buttons.
      await worker.setParameters({ tessedit_pageseg_mode: '11' });
      logger.success('OCR engine ready.');
      return worker;
    });
  }
  return workerPromise;
}

/**
 * Run OCR on a PNG buffer.
 * @returns {Promise<Array<{text:string, confidence:number, cx:number, cy:number, bbox:object}>>}
 */
async function recognizeWords(pngBuffer) {
  const worker = await getWorker();
  const { data } = await worker.recognize(pngBuffer);
  const words = (data.words || []).map((w) => {
    const b = w.bbox || { x0: 0, y0: 0, x1: 0, y1: 0 };
    return {
      text: (w.text || '').trim(),
      confidence: w.confidence || 0,
      cx: (b.x0 + b.x1) / 2,
      cy: (b.y0 + b.y1) / 2,
      bbox: b,
    };
  }).filter((w) => w.text.length > 0);
  return { words, fullText: data.text || '' };
}

async function terminate() {
  if (workerPromise) {
    try { (await workerPromise).terminate(); } catch (_) { /* ignore */ }
    workerPromise = null;
  }
}

module.exports = { recognizeWords, terminate, getWorker };
