/* ===== karaoke-azure.js =====
   Wires KARAOKE HTTP endpoints (submit/status/lyrics/list). Default base is the hosted Function App.
   Override window.KARAOKE_API_BASE before this script for any compatible API (e.g. karaoke/local_folder_queue.py).
   Requires karaoke-core.js first.
*/
(function (w) {
  const K = w.KARAOKE;
  if (!K || typeof K.initPlaybackControls !== 'function') {
    console.error('karaoke-azure.js: load karaoke-core.js before this file.');
    return;
  }

  /* e.g. http://127.0.0.1:8787 for local_folder_queue.py — not the Azure Functions host. */
  const API_BASE = (typeof w.KARAOKE_API_BASE === 'string' && w.KARAOKE_API_BASE.trim())
    ? w.KARAOKE_API_BASE.trim().replace(/\/$/, '')
    : 'https://karaoke-func-f34hnamn2t2os.azurewebsites.net';
  const FUNCTION_CODE = '';
  const withCode = (u) => (FUNCTION_CODE ? `${u}?code=${FUNCTION_CODE}` : u);

  K.endpoints = {
    submitUrl : withCode(`${API_BASE}/api/submit`),
    statusUrl : (jobId) => withCode(`${API_BASE}/api/status/${encodeURIComponent(jobId)}`),
    lyricsUrl : withCode(`${API_BASE}/api/lyrics`),
    listUrl   : withCode(`${API_BASE}/api/list`),
  };

  K.loadLyrics = async function loadLyrics(opts) {
    const jobId = opts.jobId;
    const title = opts.title;
    const artist = opts.artist;
    const duration = opts.duration;
    const lyricsBoxId = opts.lyricsBoxId != null ? opts.lyricsBoxId : 'lyricsBox';
    const textId = opts.textId;
    const msgId = opts.msgId;
    const box = lyricsBoxId ? K.$(lyricsBoxId) : null;
    const textEl = textId ? K.$(textId) : null;
    const msg = msgId ? K.$(msgId) : null;
    try {
      const url = new URL(K.endpoints.lyricsUrl);
      if (jobId) url.searchParams.set('job_id', jobId);
      if (title) url.searchParams.set('title', title);
      if (artist) url.searchParams.set('artist', artist);
      if (duration) url.searchParams.set('duration', String(duration));
      if (msg) msg.textContent = 'Fetching lyrics…';
      const r = await fetch(url.toString(), { mode: 'cors' });
      const data = await r.json();
      if (!data || data.found === false) {
        if (box) box.textContent = 'No lyrics found.';
        if (textEl) textEl.value = '';
        if (msg) msg.textContent = '';
        return;
      }
      if (data.synced && data.lrc) {
        if (textEl) textEl.value = data.lrc;
        if (box) box.textContent = 'Synced lyrics loaded.';
      } else {
        const plain = data.text || '';
        if (textEl) textEl.value = plain;
        if (box) box.textContent = plain ? 'Lyrics loaded.' : 'No lyrics text available.';
      }
      if (msg) msg.textContent = 'Loaded.';
    } catch (e) {
      console.warn(e);
      if (msg) msg.textContent = 'Failed to fetch lyrics.';
    }
  };

  K.saveLyrics = async function saveLyrics(opts) {
    const jobId = (opts.job_id || opts.jobId || '').trim();
    const msgId = opts.msgId;
    const msg = msgId ? K.$(msgId) : null;
    if (!jobId) {
      if (msg) msg.textContent = 'Job ID required.';
      return;
    }
    let text = (opts.text ?? '').toString();
    let lrc = (opts.lrc ?? '').toString();
    let synced = opts.synced;
    if (synced === undefined) {
      const t = text.trim();
      synced = /^\[\d{1,2}:\d{2}/m.test(t);
      if (synced) {
        lrc = t;
        text = '';
      }
    }
    try {
      if (msg) msg.textContent = 'Saving…';
      const body = {
        job_id: jobId,
        text: text.trim(),
        lrc: lrc.trim(),
        synced: !!synced,
        title: (opts.title || '').trim(),
        artist: (opts.artist || '').trim(),
      };
      const r = await fetch(K.endpoints.lyricsUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
        body: JSON.stringify(body),
        mode: 'cors',
      });
      let data = null;
      try {
        data = await r.json();
      } catch (_) {}
      if (!r.ok) {
        const err = (data && (data.error || data.message)) || r.statusText;
        throw new Error(err || 'Save failed (' + r.status + ')');
      }
      if (msg) msg.textContent = 'Saved.';
    } catch (e) {
      console.warn(e);
      if (msg) msg.textContent = 'Failed to save lyrics.';
    }
  };

})(window);
