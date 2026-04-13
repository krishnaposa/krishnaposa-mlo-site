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

  K.loadLyrics = async function loadLyrics({ jobId, title, artist, duration, lyricsBoxId='lyricsBox', msgId }){
    const box = K.$(lyricsBoxId);
    const msg = msgId ? K.$(msgId) : null;
    try{
      const url = new URL(K.endpoints.lyricsUrl);
      if (jobId) url.searchParams.set('job_id', jobId);
      if (title) url.searchParams.set('title', title);
      if (artist) url.searchParams.set('artist', artist);
      if (duration) url.searchParams.set('duration', String(duration));
      if (msg) msg.textContent = 'Fetching lyrics…';
      const r = await fetch(url.toString(), { mode:'cors' });
      const data = await r.json();
      if (!data || data.found === false) {
        if (box) box.textContent = 'No lyrics found.';
        if (msg) msg.textContent = '';
        return;
      }
      if (data.synced && data.lrc) {
        if (box) box.textContent = 'Synced lyrics loaded.';
      } else {
        if (box) box.textContent = data.text || 'No lyrics text available.';
      }
      if (msg) msg.textContent = 'Loaded.';
    }catch(e){
      console.warn(e);
      if (msg) msg.textContent = 'Failed to fetch lyrics.';
    }
  };

})(window);
