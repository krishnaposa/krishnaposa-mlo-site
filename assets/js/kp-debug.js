/* kp-debug.js
 *
 * Drop this file on your site and load it BEFORE any other scripts.
 * Then, inside any script, do:
 *   const log = KP.debug.ns('Portfolio'); // or whatever namespace you want
 *   log.info('hello', { any: 'data' });
 *
 * Turn on debugging:
 *   - Add ?debug=1 to the page URL (persists in localStorage), or
 *   - localStorage.setItem('kp_debug', '1') in DevTools.
 * Turn off:
 *   - ?debug=0  (or localStorage.removeItem('kp_debug')).
 */

(function () {
  // ----------- state & enable/disable -----------
  const qs = new URLSearchParams(location.search);
  const urlDebug = qs.get('debug');

  if (urlDebug === '1') localStorage.setItem('kp_debug', '1');
  if (urlDebug === '0') localStorage.removeItem('kp_debug');

  const isEnabled = () => localStorage.getItem('kp_debug') === '1';
  const redactHeaders = ['authorization', 'x-api-key', 'proxy-authorization'];

  // ----------- core printer -----------
  function printer(ns) {
    const p = (level, ...args) => {
      // errors always print; others only if enabled
      if (level !== 'error' && !isEnabled()) return;
      const prefix = ns ? `[KP:${ns}]` : '[KP]';
      // eslint-disable-next-line no-console
      (console[level] || console.log).apply(console, [prefix, ...args]);
    };
    return {
      info: (...a) => p('log', ...a),
      warn: (...a) => p('warn', ...a),
      error: (...a) => p('error', ...a),
      table: (obj) => { if (isEnabled()) console.table(obj); },
      group(label, fn) {
        if (!isEnabled()) {
          try { fn && fn(); } catch (e) { console.error('[KP] group error:', e); }
          return;
        }
        console.groupCollapsed(ns ? `[KP:${ns}] ${label}` : `[KP] ${label}`);
        try { fn && fn(); } finally { console.groupEnd(); }
      },
      time: (label) => { if (isEnabled()) console.time(ns ? `[KP:${ns}] ${label}` : `[KP] ${label}`); },
      timeEnd: (label) => { if (isEnabled()) console.timeEnd(ns ? `[KP:${ns}] ${label}` : `[KP] ${label}`); },
    };
  }

  // ----------- fetch wrapper -----------
  function wrapFetch(fetchImpl) {
    const f = fetchImpl || window.fetch;
    if (!f) return null;
    return async function kpFetch(input, init = {}) {
      const id = Math.random().toString(36).slice(2, 7);
      const ns = 'fetch';
      const log = printer(ns);

      // clone log-friendly request info
      const method = (init.method || 'GET').toUpperCase();
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      const started = performance.now();

      // headers (redact secrets)
      const hdrs = {};
      const sourceHeaders = (init.headers || (input && input.headers)) || {};
      try {
        // Normalize various header types
        const h = sourceHeaders.forEach ? sourceHeaders : new Headers(sourceHeaders);
        h.forEach((v, k) => { hdrs[k] = redactHeaders.includes(k.toLowerCase()) ? '***redacted***' : v; });
      } catch {
        // best effort fallback
        Object.entries(sourceHeaders).forEach(([k, v]) => {
          hdrs[k] = redactHeaders.includes(String(k).toLowerCase()) ? '***redacted***' : v;
        });
      }

      if (isEnabled()) {
        log.group(`${id} → ${method} ${url}`, () => {
          log.info('options', { method, headers: hdrs });
          if (init.body) {
            try { log.info('body', JSON.parse(init.body)); }
            catch { log.info('body(raw)', init.body); }
          }
        });
      }

      try {
        const res = await f(input, init);
        const ms = Math.round(performance.now() - started);

        if (isEnabled()) {
          // clone response (do not consume if not JSON)
          const ct = res.headers.get('content-type') || '';
          let preview;
          if (ct.includes('application/json')) {
            try {
              const clone = res.clone();
              preview = await clone.json();
            } catch {
              preview = '[unreadable json body]';
            }
          } else {
            preview = `[${ct}]`;
          }

          log.group(`${id} ← ${res.status} ${res.statusText} (${ms}ms)`, () => {
            log.info('headers', Object.fromEntries(res.headers.entries()));
            log.info('preview', preview);
          });
        }

        return res;
      } catch (e) {
        const ms = Math.round(performance.now() - started);
        printer('fetch').error(`${id} ✖ ${method} ${url} failed after ${ms}ms`, e);
        throw e;
      }
    };
  }

  // ----------- global error hooks -----------
  function attachGlobalErrorHandlers() {
    window.addEventListener('error', (e) => {
      printer('error').error('Uncaught error:', e.message, e.error);
    });
    window.addEventListener('unhandledrejection', (e) => {
      printer('error').error('Unhandled promise rejection:', e.reason);
    });
  }

  // ----------- DOM helpers for quick inspection -----------
  function dumpDom(selector) {
    const nodes = Array.from(document.querySelectorAll(selector || 'body *')).slice(0, 200);
    const rows = nodes.map((el) => ({
      tag: el.tagName,
      id: el.id || '',
      cls: el.className || '',
      text: (el.textContent || '').trim().slice(0, 80),
    }));
    console.table(rows);
    return rows;
  }

  // ----------- public API -----------
  const api = {
    get enabled() { return isEnabled(); },
    set(val) { val ? localStorage.setItem('kp_debug', '1') : localStorage.removeItem('kp_debug'); },
    enable() { localStorage.setItem('kp_debug', '1'); },
    disable() { localStorage.removeItem('kp_debug'); },
    ns: (name) => printer(name),
    log: printer().info,
    warn: printer().warn,
    error: printer().error,
    table: printer().table,
    group: printer().group,
    time: printer().time,
    timeEnd: printer().timeEnd,
    wrapFetch,
    attachGlobalErrorHandlers,
    dumpDom,
  };

  // install on window
  window.KP = window.KP || {};
  window.KP.debug = api;

  // attach error hooks by default
  attachGlobalErrorHandlers();

  // optional: auto-wrap fetch
  if (window.fetch && !window.fetch.__kpWrapped) {
    const wrapped = wrapFetch(window.fetch);
    if (wrapped) {
      wrapped.__kpWrapped = true;
      window.fetch = wrapped;
    }
  }

  // console banner
  if (isEnabled()) {
    printer().info('KP Debug is ON. Use KP.debug.disable() to turn off.');
  } else {
    printer().info('KP Debug is OFF. Add ?debug=1 or run KP.debug.enable().');
  }
})();