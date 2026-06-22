'use strict';

/**
 * Tiny ring-buffer logger. Keeps the most recent entries in memory and
 * forwards them to any subscriber (the renderer activity feed). Avoids any
 * disk I/O on the hot path so the watch loop stays light.
 */
const MAX_ENTRIES = 300;

class Logger {
  constructor() {
    this._entries = [];
    this._subscribers = new Set();
  }

  /** @param {(entry: object) => void} fn */
  subscribe(fn) {
    this._subscribers.add(fn);
    return () => this._subscribers.delete(fn);
  }

  _push(level, message, meta) {
    const entry = {
      level,
      message,
      meta: meta || null,
      time: new Date().toISOString(),
    };
    this._entries.push(entry);
    if (this._entries.length > MAX_ENTRIES) this._entries.shift();
    for (const fn of this._subscribers) {
      try { fn(entry); } catch (_) { /* never let a listener break logging */ }
    }
    // Mirror to stdout for `--dev` debugging.
    const tag = `[${level.toUpperCase()}]`;
    if (level === 'error') console.error(tag, message, meta || '');
    else console.log(tag, message, meta || '');
    return entry;
  }

  info(message, meta) { return this._push('info', message, meta); }
  warn(message, meta) { return this._push('warn', message, meta); }
  error(message, meta) { return this._push('error', message, meta); }
  success(message, meta) { return this._push('success', message, meta); }
  action(message, meta) { return this._push('action', message, meta); }

  recent() { return this._entries.slice(); }
}

module.exports = new Logger();
