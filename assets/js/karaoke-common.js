/* ===== karaoke-common.js =====
   Shared helpers used by index & player pages:
   - Endpoint config
   - DOM helpers
   - Playback wiring
   - Lyrics load/save (robust error surfacing + editor fill)
*/
(function (w) {
  const API_BASE = 'https://karaoke-func-bthmcvafagcncmck.canadacentral-01.azurewebsites.net';
  const FUNCTION_CODE = ''; // e.g. '?code=...' if not anonymous

  const endpoints = {
    submitUrl: `${API_BASE}/api/submit${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`,
    statusUrl: (jobId) => `${API_BASE}/api/status/${encodeURIComponent(jobId)}${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`,
    lyricsUrl: `${API_BASE}/api/lyrics${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`,
    listUrlFromMeta: () => (document.querySelector('meta[name="karaoke-list"]')?.content || '')
  };

  // ---- Tiny DOM helpers ----
  const $ = (id) => document.getElementById(id);
  const setTxt = (idOrEl, t) => {
    const el = typeof idOrEl === 'string' ? $(idOrEl) : idOrEl;
    if (el) el.textContent = t ?? '';
  };
  const setVal = (idOrEl, v) => {
    const el = typeof idOrEl === 'string' ? $(idOrEl) : idOrEl;
    if (el) el.value = v ?? '';
  };

  // Public state: current job id (set by index/player)
  let currentJobId = null;
  function setJobId(j) { currentJobId = (j || '').trim() || null; }

  // Build direct or SAS URL into clickable
  function asUrl(valueOrKey) {
    if (/^https?:\/\//i.test(valueOrKey)) return valueOrKey;
    return '#';
  }

  // ---- Playback controls wrapper ----
  function initPlaybackControls() {
    const vocalsEl = $('vocalsEl');
    const bandEl   = $('bandEl');
    const titleEl  = $('trackTitle');

    function showTitle(t){ if (titleEl) titleEl.textContent = t || '—'; }

    function setSources(vocals, band) {
      if (vocalsEl) vocalsEl.src = vocals || '';
      if (bandEl)   bandEl.src   = band   || '';
      // force reload so durations are fresh
      try { vocalsEl?.load(); bandEl?.load(); } catch {}
    }

    function getDurations(){
      return {
        vocals: (vocalsEl && isFinite(vocalsEl.duration)) ? vocalsEl.duration : 0,
        band:   (bandEl   && isFinite(bandEl.duration))   ? bandEl.duration   : 0
      };
    }

    return { setSources, showTitle, getDurations };
  }

  // ---- LRC parsing (for preview scrolling) ----
  function parseLRC(lrcText){
    const lines=[], re=/\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\](.*)/g; let m;
    while((m=re.exec(lrcText))!==null){
      const min=+m[1], sec=+m[2], ms=m[3]?+m[3].padEnd(3,'0'):0;
      const t=min*60+sec+ms/1000;
      lines.push({t, text:(m[4]||'').trim()});
    }
    lines.sort((a,b)=>a.t-b.t);
    return lines;
  }

  // ---- Lyrics: LOAD ----
  /**
   * opts: {
   *   jobId?: string, title?: string, artist?: string, duration?: number,
   *   lyricsBoxId?: string, textId?: string, msgId?: string
   * }
   */
  async function loadLyrics(opts = {}){
    const jobId   = (opts.jobId || currentJobId || '').trim();
    const title   = (opts.title || '').trim();
    const artist  = (opts.artist || '').trim();
    const dur     = opts.duration ? Math.round(opts.duration) : 0;

    const msgEl   = opts.msgId ? $(opts.msgId) : null;
    const boxEl   = opts.lyricsBoxId ? $(opts.lyricsBoxId) : null;
    const editEl  = opts.textId ? $(opts.textId) : null;

    if (msgEl)   msgEl.textContent = 'Fetching lyrics…';
    if (boxEl)   boxEl.textContent = '…';

    try{
      const url = new URL(endpoints.lyricsUrl);
      if (jobId)  url.searchParams.set('job_id', jobId);
      if (title)  url.searchParams.set('title', title);
      if (artist) url.searchParams.set('artist', artist);
      if (dur)    url.searchParams.set('duration', String(dur));

      // DEBUG: show exactly what we’re calling
      console.debug('[lyrics] GET', url.toString());

      const r = await fetch(url.toString(), { mode:'cors' });
      const isJson = (r.headers.get('content-type')||'').includes('application/json');
      if (!r.ok) {
        const bodyText = isJson ? JSON.stringify(await r.json()).slice(0,300) : (await r.text()).slice(0,300);
        throw new Error(`HTTP ${r.status} ${r.statusText} – ${bodyText}`);
      }
      const data = isJson ? await r.json() : {};
      console.debug('[lyrics] response', data);

      if (!data || data.found === false) {
        if (boxEl) boxEl.textContent = 'No lyrics found.';
        if (editEl) editEl.value = '';
        if (msgEl) msgEl.textContent = '';
        return;
      }

      // Prefer synced LRC
      if (data.synced && data.lrc) {
        if (boxEl) boxEl.textContent = 'Synced lyrics loaded.';
        if (editEl) editEl.value = data.lrc;
      } else {
        const text = data.text || '';
        if (boxEl) boxEl.textContent = text || 'No lyrics text available.';
        if (editEl) editEl.value = text;
      }
      if (msgEl) msgEl.textContent = 'Loaded.';
    } catch (e){
      console.warn('[lyrics] load failed', e);
      if (boxEl) boxEl.textContent = 'Failed to fetch lyrics.';
      if (msgEl) msgEl.textContent = e.message || 'Failed to fetch lyrics.';
    }
  }

  // ---- Lyrics: SAVE (upsert) ----
  /**
   * opts: { jobId: string, text: string, msgId?: string }
   * Saves as plain text (backend will store under by-job/{jobId}.json).
   */
  async function saveLyrics(opts = {}){
    const jobId = (opts.jobId || currentJobId || '').trim();
    const text  = (opts.text || '').trim();
    const msgEl = opts.msgId ? $(opts.msgId) : null;

    if (!jobId){ if (msgEl) msgEl.textContent = 'Please enter a Job ID first.'; return; }
    if (!text){  if (msgEl) msgEl.textContent = 'Paste lyrics before saving.';   return; }

    if (msgEl) msgEl.textContent = 'Saving…';

    try{
      console.debug('[lyrics] POST', endpoints.lyricsUrl, {job_id: jobId, text: text.slice(0,60)+'…'});
      const r = await fetch(endpoints.lyricsUrl, {
        method:'POST',
        mode:'cors',
        headers:{ 'Content-Type':'application/json; charset=utf-8' },
        body: JSON.stringify({ job_id: jobId, text })
      });
      const isJson = (r.headers.get('content-type')||'').includes('application/json');
      const resp = isJson ? await r.json() : {};
      if (!r.ok || resp.error) throw new Error(resp.error || `HTTP ${r.status}`);
      if (msgEl) msgEl.textContent = 'Saved.';
    } catch (e){
      console.warn('[lyrics] save failed', e);
      if (msgEl) msgEl.textContent = e.message || 'Save failed.';
    }
  }

  // Expose
  w.KARAOKE = Object.assign(w.KARAOKE || {}, {
    endpoints, $, setTxt, setVal, asUrl,
    currentJobId, setJobId,
    initPlaybackControls,
    parseLRC,
    loadLyrics,
    saveLyrics
  });
})(window);