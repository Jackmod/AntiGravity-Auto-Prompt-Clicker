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
 * Find every word matching a keyword list (exact token match, so "yes"
 * matches but "yesterday" does not), above the confidence threshold.
 */
function findKeywordWords(words, keywords, minConfidence) {
  const wanted = keywords.map(normalize);
  return words.filter((w) => {
    if (w.confidence < minConfidence) return false;
    const norm = normalize(w.text);
    return norm && wanted.includes(norm);
  });
}

function wordHeight(w) { return Math.max(8, w.bbox.y1 - w.bbox.y0); }

/** Are two words on the same text line? */
function sameRow(a, b) {
  return Math.abs(a.cy - b.cy) <= wordHeight(a) * 0.9;
}

/** Horizontal whitespace gap between two same-row words (negative if overlapping). */
function horizontalGap(a, b) {
  return a.cx < b.cx ? b.bbox.x0 - a.bbox.x1 : a.bbox.x0 - b.bbox.x1;
}

/** Is there any other word sitting between a and b on their row? ("yes or no") */
function wordBetween(a, b, words) {
  const lo = Math.min(a.cx, b.cx);
  const hi = Math.max(a.cx, b.cx);
  return words.some((w) => w !== a && w !== b && sameRow(a, w) && w.cx > lo + 2 && w.cx < hi - 2);
}

/** List markers like "1", "2.", "›", "-" are part of a button label, not prose. */
function isMarker(w) {
  const t = normalize(w.text);
  return t.length <= 1 || /^[0-9]+$/.test(t);
}

/**
 * A real button has padding/whitespace around it. A word embedded in a
 * sentence has neighbours hugging it (a normal space away). This is the key
 * test that stops us clicking the word "yes" inside ordinary text. List
 * markers ("1 Yes", "2 No") are ignored so numbered options still count.
 */
function isIsolated(w, words) {
  const pad = wordHeight(w) * 0.7; // a normal prose space is well under this
  for (const o of words) {
    if (o === w || !sameRow(w, o) || isMarker(o)) continue;
    const g = horizontalGap(w, o);
    if (g >= 0 && g < pad) return false; // a real word is hugging it -> prose
  }
  return true;
}

/** Group OCR words into text lines (sorted left-to-right within each line). */
function groupLines(words) {
  const ws = words.slice().sort((a, b) => a.cy - b.cy || a.cx - b.cx);
  const lines = [];
  let cur = [];
  for (const w of ws) {
    if (!cur.length) { cur = [w]; continue; }
    const prev = cur[cur.length - 1];
    if (Math.abs(w.cy - prev.cy) <= wordHeight(prev) * 0.7) cur.push(w);
    else { lines.push(cur); cur = [w]; }
  }
  if (cur.length) lines.push(cur);
  for (const l of lines) l.sort((a, b) => a.cx - b.cx);
  return lines;
}

/**
 * Find where actual prompt phrases ("allow this", "do you want", "run command")
 * appear as consecutive words. These are strong anchors — far more reliable
 * than matching a single common word like "this", which appears everywhere.
 * Returns the centre point of each phrase occurrence.
 */
function findPhraseAnchors(words, phrases) {
  const phr = phrases
    .map((p) => normalize(p).split(' ').filter(Boolean))
    .filter((toks) => toks.length >= 2);
  const anchors = [];
  for (const line of groupLines(words)) {
    const toks = line.map((w) => normalize(w.text));
    for (const p of phr) {
      for (let i = 0; i + p.length <= toks.length; i++) {
        let ok = true;
        for (let j = 0; j < p.length; j++) { if (toks[i + j] !== p[j]) { ok = false; break; } }
        if (ok) {
          const span = line.slice(i, i + p.length);
          anchors.push({
            cx: span.reduce((s, w) => s + w.cx, 0) / span.length,
            cy: span.reduce((s, w) => s + w.cy, 0) / span.length,
          });
        }
      }
    }
  }
  return anchors;
}

/** Is the accept button near (just below/around) a real prompt phrase? */
function nearAnchor(accept, anchors) {
  return anchors.some((a) => Math.abs(accept.cy - a.cy) <= 320 && Math.abs(accept.cx - a.cx) <= 850);
}

/**
 * Is `reject` positioned like the partner button of `accept`? Approval dialogs
 * place Yes/No (or Accept/Reject) buttons side by side, or occasionally
 * stacked, with nothing wedged between them. Prose like "yes or no" fails this
 * because "or" sits between the two words.
 */
function isButtonPartner(accept, reject, words) {
  const ah = wordHeight(accept);
  const dx = Math.abs(accept.cx - reject.cx);
  const dy = Math.abs(accept.cy - reject.cy);
  if (dy <= ah * 1.2 && dx <= 560) {
    return !wordBetween(accept, reject, words); // side-by-side buttons
  }
  const stacked = dx <= Math.max(130, (accept.bbox.x1 - accept.bbox.x0) * 3)
    && dy > ah * 0.6 && dy <= 300;
  return stacked; // stacked buttons (e.g. a "1. Yes / 2. No" list)
}

/**
 * @param {{words: Array, fullText: string}} ocr
 * @param {object} detection  detection settings slice
 * @param {{scaleX:number, scaleY:number, region:{left:number,top:number}}} geom
 */
function analyze(ocr, detection, geom) {
  const { words, fullText } = ocr;
  const minConf = detection.minConfidence;
  const strict = detection.strictMatch !== false; // default on

  const acceptWords = findKeywordWords(words, detection.acceptKeywords, minConf);
  const rejectWords = findKeywordWords(words, detection.rejectKeywords, minConf);

  // Does the screen show a known prompt phrase (e.g. "do you want", "allow")?
  const promptPhrasePresent =
    anyKeywordInText(fullText, detection.triggerPhrases)
    || words.some((w) => anyKeywordInText(w.text, detection.triggerPhrases));

  // Find an accept word that forms a real button pair with a reject word
  // (both must be isolated, i.e. button-like, not words inside a sentence).
  let pairedAccept = null;
  for (const a of acceptWords) {
    if (!isIsolated(a, words)) continue;
    if (rejectWords.some((r) => isIsolated(r, words) && isButtonPartner(a, r, words))) {
      if (!pairedAccept || a.confidence > pairedAccept.confidence) pairedAccept = a;
    }
  }
  // Best isolated (button-like) accept word, for the phrase / non-strict paths.
  const isolatedAccepts = acceptWords.filter((a) => isIsolated(a, words));
  const bestAccept = isolatedAccepts.slice().sort((x, y) => y.confidence - x.confidence)[0] || null;

  // For a lone accept button, confirm a real prompt phrase sits next to it.
  const anchors = findPhraseAnchors(words, detection.triggerPhrases);
  const phraseAccept = isolatedAccepts
    .filter((a) => nearAnchor(a, anchors))
    .sort((x, y) => y.confidence - x.confidence)[0] || null;

  // Decide what we're allowed to click:
  //  - a genuine Yes/No button pair is the strongest signal, OR
  //  - an isolated accept button with a prompt phrase right beside it.
  // In non-strict mode, any confident isolated accept word is enough.
  let target = null;
  let why = '';
  if (pairedAccept) { target = pairedAccept; why = `"${pairedAccept.text}" button (paired with a No/Cancel)`; }
  else if (phraseAccept) { target = phraseAccept; why = `"${phraseAccept.text}" button in a recognized prompt`; }
  else if (!strict && bestAccept) { target = bestAccept; why = `"${bestAccept.text}" (strict matching off)`; }

  // Optional extra gate: require a prompt phrase before ever clicking.
  if (target && detection.requireTriggerPhrase && !promptPhrasePresent) {
    target = null;
    return { action: 'none', reason: 'Saw a Yes but no trusted prompt phrase' };
  }

  if (target) {
    const x = Math.round(geom.region.left + target.cx * geom.scaleX);
    const y = Math.round(geom.region.top + target.cy * geom.scaleY);
    return {
      action: 'click',
      point: { x, y },
      matched: target.text,
      confidence: Math.round(target.confidence),
      reason: `Found ${why}`,
    };
  }

  // A real decision prompt is on screen but we can't safely pick "Yes" ->
  // pause so the human takes over. ("anything different -> pause".)
  // We only treat it as a prompt when a prompt phrase or a reject button pair
  // is present — never on a stray word in prose.
  const rejectPairPresent = rejectWords.length > 0 && acceptWords.length > 0;
  if (detection.pauseOnUnknown && promptPhrasePresent && acceptWords.length === 0) {
    return {
      action: 'pause',
      reason: rejectWords.length
        ? `Prompt found with only a "${rejectWords[0].text}" option — paused for you`
        : 'A prompt appeared but no clear "Yes" — paused for you',
    };
  }

  if (rejectPairPresent && !target) {
    // accept + reject both present but not a confident pair/phrase — be safe.
    return { action: 'none', reason: 'Possible prompt — waiting for a clearer match' };
  }

  return { action: 'none', reason: 'No prompt on screen' };
}

module.exports = { analyze, normalize };
