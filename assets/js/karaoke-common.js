/* ===== karaoke-common.js =====
   Shared helpers + robust playback controller.
*/
(function (w) {
  const K = w.KARAOKE = w.KARAOKE || {};

  // ---------- Endpoints (override here if needed) ----------
  const API_BASE = 'https://karaoke-func-bthmcvafagcncmck.canadacentral-01.azurewebsites.net';
  const FUNCTION_CODE = '';
  K.endpoints = {
    submitUrl  : `${API_BASE}/api/submit${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`,
    statusUrl  : (jobId) => `${API_BASE}/api/status/${encodeURIComponent(jobId)}${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`,
    lyricsUrl  : `${API_BASE}/api/lyrics${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`,
    listUrl    : (document.querySelector('meta[name="karaoke-list"]')?.content || '')
  };

  // ---------- Tiny DOM helpers ----------
  K.$ = (id) => document.getElementById(id);
  K.asUrl = (s) => s; // SAS is already absolute in player; index shows '#' for private unless SAS is used.
  K.currentJobId = null;
  K.setJobId = (id) => (K.currentJobId = id);
  K.getJobId = () => K.currentJobId;

  // ---------- Playback ----------
  K.initPlaybackControls = function initPlaybackControls() {
    const vEl   = K.$('vocalsEl');
    const bEl   = K.$('bandEl');
    const playB = K.$('play');
    const pauseB= K.$('pause');
    const restartB = K.$('restart');
    const offsetIn = K.$('offset');
    const msgEl = K.$('msg');   // optional <div id="msg" class="error">

    const supportSink = typeof HTMLMediaElement.prototype.setSinkId === 'function';
    let urls = { v:'', b:'' };
    let isLoaded = false;
    let isPlaying = false;
    let syncTimer = null;

    function showMsg(t){
      if (!msgEl) return;
      msgEl.textContent = t || '';
      if (t) msgEl.classList.remove('hide'); else msgEl.classList.add('hide');
    }

    function showTitle(t){
      const el = K.$('trackTitle');
      if (el) el.textContent = t || '—';
    }

    function getOffsetMs(){
      const n = parseInt(offsetIn?.value || '0', 10);
      return Number.isFinite(n) ? n : 0;
    }

    function clearSync(){
      if (syncTimer){ clearInterval(syncTimer); syncTimer = null; }
    }

    function stopAll(){
      clearSync();
      try{ vEl.pause(); }catch{}
      try{ bEl.pause(); }catch{}
      vEl.playbackRate = 1;
      bEl.playbackRate = 1;
      isPlaying = false;
    }

    function waitCanPlay(audio, label, timeoutMs=12000){
      return new Promise((resolve, reject) => {
        let done = false;
        const to = setTimeout(() => {
          if (!done) { done = true; reject(new Error(`${label} not ready (timeout)`)); }
        }, timeoutMs);
        const ok = () => {
          if (!done) { done = true; clearTimeout(to); resolve(); }
        };
        if (audio.readyState >= 3) ok();
        else {
          audio.addEventListener('canplay', ok, { once:true });
          audio.addEventListener('loadeddata', ok, { once:true });
          audio.addEventListener('error', () => {
            if (!done) { done = true; clearTimeout(to); reject(new Error(`${label} error`)); }
          }, { once:true });
        }
      });
    }

    async function applySinksIfAny(){
      if (!supportSink) return;
      const vSel = K.$('vocalsOut');
      const bSel = K.$('bandOut');
      try { if (vSel && vSel.value) await vEl.setSinkId(vSel.value); } catch{}
      try { if (bSel && bSel.value) await bEl.setSinkId(bSel.value); } catch{}
    }

    async function preload(){
      if (!urls.v || !urls.b || urls.v === '#' || urls.b === '#') {
        throw new Error('Tracks not loaded. Pick a song (or wait until processing finishes).');
      }
      // set sources (ensure HTTPS to avoid mixed-content)
      vEl.src = urls.v; bEl.src = urls.b;
      vEl.crossOrigin = 'anonymous';
      bEl.crossOrigin = 'anonymous';
      vEl.load(); bEl.load();

      // wait readiness
      await Promise.all([
        waitCanPlay(vEl, 'Vocals'),
        waitCanPlay(bEl, 'Band')
      ]);

      isLoaded = true;
    }

    function driftCorrect(biasMs){
  clearSync();

  const FAST_WINDOW_MS = 20000;  // tighten checks early
  const START = performance.now();
  const SOFT_THRESH = 90;        // ms: apply gentle rate nudge
  const HARD_THRESH = 180;       // ms: immediate re-seek
  const NUDGE = 0.02;            // 2% speed nudge

  function loop(){
    if (!isPlaying) return;

    const now = performance.now();
    const period = (now - START) < FAST_WINDOW_MS ? 500 : 1500;

    const driftMs = (vEl.currentTime - bEl.currentTime) * 1000 - biasMs;

    if (Math.abs(driftMs) >= HARD_THRESH) {
      // Hard re-sync: align band to vocals, preserving bias
      try {
        bEl.currentTime = Math.max(0, vEl.currentTime - biasMs / 1000);
      } catch {}
      // reset rates
      vEl.playbackRate = 1;
      bEl.playbackRate = 1;
    } else if (Math.abs(driftMs) >= SOFT_THRESH) {
      // Gentle nudge for 250ms
      if (driftMs > 0) { // vocals ahead
        vEl.playbackRate = 1 - NUDGE;
        setTimeout(() => { vEl.playbackRate = 1; }, 250);
      } else {            // band ahead
        bEl.playbackRate = 1 - NUDGE;
        setTimeout(() => { bEl.playbackRate = 1; }, 250);
      }
    }

    syncTimer = setTimeout(loop, period);
  }

  loop();
}

async function startFromZeroWithOffset(offsetMs){
  await applySinksIfAny();     // set sinks right before play
  vEl.currentTime = 0;
  bEl.currentTime = 0;

  // Staggered start for initial BT latency
  if (offsetMs >= 0){
    await bEl.play().catch(()=>{});
    await new Promise(r => setTimeout(r, offsetMs));
    await vEl.play();
  } else {
    await vEl.play().catch(()=>{});
    await new Promise(r => setTimeout(r, -offsetMs));
    await bEl.play();
  }

  isPlaying = true;

  // One-time settle re-sync after Bluetooth buffers fill
  setTimeout(() => {
    if (!isPlaying) return;
    try { bEl.currentTime = Math.max(0, vEl.currentTime - offsetMs / 1000); } catch {}
  }, 1000);

  driftCorrect(offsetMs);
}
    async function resumePlay(){
      await applySinksIfAny();
      await Promise.all([
        vEl.play().catch(()=>{}),
        bEl.play().catch(()=>{})
      ]);
      isPlaying = true;
      driftCorrect(getOffsetMs());
    }

    async function onPlay(){
      try{
        showMsg('');
        if (!isLoaded) await preload();
        if (vEl.paused && bEl.paused && (vEl.currentTime>0 || bEl.currentTime>0)) {
          await resumePlay();
        } else {
          await startFromZeroWithOffset(getOffsetMs());
        }
      } catch (e) {
        // Bubble the real reason into UI so we can see it.
        showMsg(e.message || 'Could not start playback.');
        console.warn('play error', e);
      }
    }

    async function onRestart(){
      try{
        showMsg('');
        if (!isLoaded) await preload();
        stopAll();
        await startFromZeroWithOffset(getOffsetMs());
      } catch (e) {
        showMsg(e.message || 'Could not restart playback.');
        console.warn('restart error', e);
      }
    }

    playB?.addEventListener('click', onPlay);
    pauseB?.addEventListener('click', () => { stopAll(); });
    restartB?.addEventListener('click', onRestart);

    return {
      setSources(vocalsUrl, bandUrl){
        urls = { v: vocalsUrl, b: bandUrl };
        isLoaded = false;
        stopAll();
      },
      showTitle,
      getDurations(){
        return { vocals: vEl?.duration || 0, band: bEl?.duration || 0 };
      }
    };
  };

  // ---------- Lyrics helpers ----------
  K.loadLyrics = async function loadLyrics({ jobId, title, artist, duration, lyricsBoxId, msgId }) {
    const box = K.$(lyricsBoxId);
    const msg = K.$(msgId);
    if (msg) msg.textContent = 'Fetching lyrics…';

    try{
      const url = new URL(K.endpoints.lyricsUrl);
      if (jobId)   url.searchParams.set('job_id', jobId);
      if (title)   url.searchParams.set('title', title);
      if (artist)  url.searchParams.set('artist', artist);
      if (duration)url.searchParams.set('duration', String(duration));

      const r = await fetch(url.toString(), { mode:'cors' });
      const data = await r.json();

      if (!data || data.found === false) {
        if (box) box.textContent = 'No lyrics found.';
        if (msg) msg.textContent = '';
        return;
      }
      if (data.synced && data.lrc) {
        if (box) box.textContent = data.lrc;
      } else {
        if (box) box.textContent = data.text || 'No lyrics text available.';
      }
      if (msg) msg.textContent = 'Loaded.';
    } catch (e) {
      console.warn(e);
      if (msg) msg.textContent = 'Failed to fetch lyrics.';
    }
  };

  K.saveLyrics = async function saveLyrics({ jobId, text, msgId }) {
    const msg = K.$(msgId);
    if (!jobId){ if (msg) msg.textContent = 'No job id. Upload or pick a song first.'; return; }
    const body = JSON.stringify({ job_id: jobId, text: (text||'').trim() });
    if (!JSON.parse(body).text){ if (msg) msg.textContent = 'Paste lyrics before saving.'; return; }

    try{
      if (msg) msg.textContent = 'Saving…';
      const r = await fetch(K.endpoints.lyricsUrl, {
        method:'POST', mode:'cors',
        headers:{ 'Content-Type':'application/json; charset=utf-8' },
        body
      });
      const resp = await r.json().catch(()=>({}));
      if (!r.ok || resp.error) throw new Error(resp.error || `Save failed (${r.status})`);
      if (msg) msg.textContent = 'Saved.';
    } catch (e) {
      console.warn(e);
      if (msg) msg.textContent = e.message || 'Save failed.';
    }
  };
})(window);