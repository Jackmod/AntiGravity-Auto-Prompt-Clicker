'use strict';

/**
 * Decision engine.
 *
 * Given the OCR words for a frame plus the user's detection settings, decide
 * what to do:
 *   - 'click' : a recognized accept control is on screen (and, if required, a
 *               known prompt phrase confirms this is really a Claude/Antigravity
 *               approval). Returns the logical click point.
 *   - 'pause' : a prompt clearly needs a decision but we cannot safely pick
 *               "Yes" (ambiguous, only reject options, or unknown wording).
 *               This is the "anything different -> pause" safety behaviour.
 *   - 'none'  : nothing actionable on screen; keep watching.
 */

function normalize(s) {
  return (s || '').toLowerCase().replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
}

function anyKeywordInText(text, keywords) {
  const t = ` ${normalize(text)} `;
  return keywords.some((k) => t.includes(` ${normalize(k)} `));
}

/**
 * Find the best-matching word for a keyword list.
 * @returns {object|null} the OCR word, or null
 */
function findKeywordWord(words, keywords, minConfidence) {
  const wanted = keywords.map(normalize);
  let best = null;
  for (const w of words) {
    if (w.confidence < minConfidence) continue;
    const norm = normalize(w.text);
    if (!norm) continue;
    // Exact token match (so "yes" matches but "yesterday" does not).
    if (wanted.includes(norm)) {
      if (!best || w.confidence > best.confidence) best = w;
    }
  }
  return best;
}

/**
 * @param {{words: Array, fullText: string}} ocr
 * @param {object} detection  detection settings slice
 * @param {{scaleX:number, scaleY:number, region:{left:number,top:number}}} geom
 */
function analyze(ocr, detection, geom) {
  const { words, fullText } = ocr;
  const minConf = detection.minConfidence;

  const acceptWord = findKeywordWord(words, detection.acceptKeywords, minConf);
  const rejectWord = findKeywordWord(words, detection.rejectKeywords, minConf);

  const triggerPresent = !detection.requireTriggerPhrase
    || anyKeywordInText(fullText, detection.triggerPhrases)
    || words.some((w) => anyKeywordInText(w.text, detection.triggerPhrases));

  // A "prompt context" exists when either trigger phrasing or a clear
  // accept/reject pair is on screen.
  const promptContext = triggerPresent || (!!acceptWord && !!rejectWord);

  // Happy path: a clear accept control, in a recognized prompt context.
  if (acceptWord && triggerPresent) {
    const x = Math.round(geom.region.left + acceptWord.cx * geom.scaleX);
    const y = Math.round(geom.region.top + acceptWord.cy * geom.scaleY);
    return {
      action: 'click',
      point: { x, y },
      matched: acceptWord.text,
      confidence: Math.round(acceptWord.confidence),
      reason: `Found "${acceptWord.text}" in a recognized prompt`,
    };
  }

  // A prompt needs a decision but we can't confidently pick Yes -> pause.
  if (detection.pauseOnUnknown && promptContext) {
    let reason;
    if (rejectWord && !acceptWord) {
      reason = `Only a "${rejectWord.text}" option was found — paused for safety`;
    } else if (acceptWord && !triggerPresent) {
      reason = `Saw "${acceptWord.text}" but no trusted prompt phrase — paused`;
    } else {
      reason = 'A decision prompt appeared but no clear "Yes" — paused';
    }
    return { action: 'pause', reason };
  }

  return { action: 'none', reason: 'No actionable prompt on screen' };
}

module.exports = { analyze, normalize };
