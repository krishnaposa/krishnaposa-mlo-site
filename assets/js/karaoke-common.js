/* ===== karaoke-common.js =====
   Shared config, helpers, playback routing, and lyrics helpers.
*/
(function (w) {
  // ---------- CONFIG ----------
  const API_BASE = 'https://karaoke-func-bthmcvafagcncmck.canadacentral-01.azurewebsites.net';
  const FUNCTION_CODE = ''; // e.g. '&code=...' if not anonymous
  const OUTPUT_BASE = '';   // leave '' for private SAS links

  const endpoints = {
    submitUrl:  `${API_BASE}/api/submit${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`,
    statusUrl:  (jobId) => `${API_BASE}/api/status/${encodeURIComponent(jobId)}${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`,
    lyricsUrl:  `${API_BASE}/api/lyrics${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`,
  };

  // ---------- STATE ----------
  const K = (w.KARAOKE = w.KARAOKE || {});
  K.currentJobId = null;
  K.setJobId = (id) => { K.currentJobId = id || null; const v = document.getElementById('jobIdView'); if (v) v.textContent = K.currentJobId || '—'; };
  K.endpoints = endpoints;

  // ---------- HELPERS ----------
  function asUrl(valueOrKey) {
    if (/^https?:\/\//i.test(valueOrKey)) return valueOrKey;
    return OUTPUT_BASE ? `${OUTPUT_BASE.replace(/\/$/,'')}/${valueOrKey.replace(/^\/+/,'')}` : '#';
  }
  function $(id) { return document.getElementById(id); }
  function setText(id, t) { const el = $(id); if (el) el.textContent = t || ''; }

  // ---------- PLAYBACK (routing + controls) ----------
  function initPlaybackControls(cfg = {}) {
    const {
      vocalsElId='vocalsEl', bandElId='bandEl',
      vocalsOutId='vocalsOut', bandOutId='bandOut',
      initBtnId='initAudio', playBtnId='play', pauseBtnId='pause', restartBtnId='restart',
      offsetId='offset', trackTitleId='trackTitle', deviceMsgId='deviceMsg'
    } = cfg;

    const vocalsEl  = $(vocalsElId);
    const bandEl    = $(bandElId);
    const vocalsOut = $(vocalsOutId);
    const bandOut   = $(bandOutId);
    const initBtn   = $(initBtnId);
    const playBtn   = $(playBtnId);
    const pauseBtn  = $(pauseBtnId);
    const restartBtn= $(restartBtnId);
    const offsetIn  = $(offsetId);
    const titleEl   = $(trackTitleId);
    const devMsgEl  = $(deviceMsgId);

    let vocalsUrl = '';
    let bandUrl   = '';
    let isLoaded  = false;
    let isPlaying = false;

    const supportSink = typeof HTMLMediaElement.prototype.setSinkId === 'function';

    function showTitle(t){ if (titleEl) titleEl.textContent = t || '—'; }
    function setDeviceMsg(t){ if (devMsgEl) devMsgEl.textContent = t || ''; }
    function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }
    function clearSyncTimer(){ if (w._syncTimer){ clearInterval(w._syncTimer); w._syncTimer=null; } }
    function currentOffsetMs(){ return parseInt(offsetIn?.value || '0', 10) || 0; }

    async function ensurePermission() {
      try { await navigator.mediaDevices.getUserMedia({ audio: true }); return true; }
      catch { setDeviceMsg('Please allow microphone access to list audio outputs.'); return false; }
    }

    function fillSelect(sel, outs) {
      if (!sel) return;
      sel.innerHTML = '';
      outs.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.deviceId;
        opt.textContent = d.label || `Output ${d.deviceId}`;
        sel.appendChild(opt);
      });
      const def = outs.find(d => d.deviceId === 'default');
      sel.value = def ? def.deviceId : (outs[0]?.deviceId || 'default');
    }

    function addDefaultFallback(sel) {
      if (!sel) return;
      sel.innerHTML = '';
      const opt = document.createElement('option');
      opt.value = 'default';
      opt.textContent = 'System default';
      sel.appendChild(opt);
      sel.value = 'default';
    }

    async function listOutputs() {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const outs = devices.filter(d => d.kind === 'audiooutput');
      if (outs.length) { fillSelect(vocalsOut, outs); fillSelect(bandOut, outs); setDeviceMsg(`Found ${outs.length} output device(s).`); }
      else { addDefaultFallback(vocalsOut); addDefaultFallback(bandOut); setDeviceMsg('No discrete outputs reported. Using system default.'); }
      return outs.length;
    }

    async function applySinks() {
      if (!supportSink) return;
      try { await vocalsEl?.setSinkId(vocalsOut?.value || 'default'); } catch {}
      try { await bandEl?.setSinkId(bandOut?.value   || 'default'); } catch {}
    }

    function pauseAll(){
      clearSyncTimer();
      try{vocalsEl?.pause()}catch{}
      try{bandEl?.pause()}catch{}
      if(vocalsEl) vocalsEl.playbackRate=1;
      if(bandEl)   bandEl.playbackRate=1;
      isPlaying=false;
      // any lyrics sync stopper is page-specific
      w.dispatchEvent(new CustomEvent('karaoke:paused'));
    }

    async function preloadIfNeeded() {
      if (isLoaded) return;
      if (!vocalsUrl || !bandUrl || vocalsUrl === '#' || bandUrl === '#') throw new Error('No tracks loaded yet.');
      vocalsEl.src = vocalsUrl; bandEl.src = bandUrl;
      await applySinks(); vocalsEl.load(); bandEl.load();
      await Promise.all([
        new Promise(r => vocalsEl.addEventListener('canplay', r, {once:true})),
        new Promise(r => bandEl.addEventListener('canplay', r, {once:true})),
      ]);
      isLoaded = true;
    }

    function startDriftCorrection(offsetMs){
      clearSyncTimer();
      w._syncTimer = setInterval(() => {
        if (!isPlaying) return;
        const driftMs = (vocalsEl.currentTime - bandEl.currentTime) * 1000 - offsetMs;
        if (Math.abs(driftMs) > 60) {
          if (driftMs > 0) { const r=vocalsEl.playbackRate; vocalsEl.playbackRate=Math.max(0.9,r-0.05); setTimeout(()=>{vocalsEl.playbackRate=r},300); }
          else { const r=bandEl.playbackRate; bandEl.playbackRate=Math.max(0.9,r-0.05); setTimeout(()=>{bandEl.playbackRate=r},300); }
        }
      }, 2000);
    }

    async function resumePlay(){
      await Promise.all([vocalsEl.play().catch(()=>{}), bandEl.play().catch(()=>{})]);
      isPlaying=true;
      startDriftCorrection(currentOffsetMs());
      w.dispatchEvent(new CustomEvent('karaoke:playing'));
    }

    async function startFromZeroWithOffset(offsetMs){
      vocalsEl.currentTime=0; bandEl.currentTime=0;
      if (offsetMs >= 0){ await bandEl.play(); await sleep(offsetMs); await vocalsEl.play(); }
      else { await vocalsEl.play(); await sleep(-offsetMs); await bandEl.play(); }
      isPlaying=true;
      startDriftCorrection(offsetMs);
      w.dispatchEvent(new CustomEvent('karaoke:playing'));
    }

    // Wire UI
    initBtn?.addEventListener('click', async () => {
      setDeviceMsg('');
      if (!supportSink) { setDeviceMsg('Output selection not supported here. Use Chrome/Edge desktop.'); return; }
      if (!await ensurePermission()) return;
      const count = await listOutputs();
      initBtn.textContent = count ? 'Device list ready' : 'Device list (default only)';
      try { navigator.mediaDevices.addEventListener('devicechange', listOutputs); } catch {}
    });

    playBtn?.addEventListener('click', async () => {
      try{
        if (!vocalsEl || !bandEl) return;
        if (isPlaying) return;
        await preloadIfNeeded();
        if (vocalsEl.paused && bandEl.paused && (vocalsEl.currentTime>0 || bandEl.currentTime>0)) await resumePlay();
        else await startFromZeroWithOffset(currentOffsetMs());
      }catch(e){ alert(e.message || 'Could not start playback.'); }
    });

    pauseBtn?.addEventListener('click', pauseAll);
    restartBtn?.addEventListener('click', async () => {
      try { await preloadIfNeeded(); pauseAll(); await startFromZeroWithOffset(currentOffsetMs()); }
      catch(e){ alert(e.message || 'Could not restart playback.'); }
    });

    // Public API for page scripts
    return {
      setSources: (vocals, band) => { vocalsUrl = asUrl(vocals); bandUrl = asUrl(band); isLoaded=false; isPlaying=false; },
      showTitle,
      getDurations: () => ({ vocals: vocalsEl?.duration || 0, band: bandEl?.duration || 0 }),
      elements: { vocalsEl, bandEl }
    };
  }

  // ---------- LYRICS HELPERS ----------
  async function loadLyrics({ jobId, title, artist, duration, lyricsBoxId, msgId }) {
    const lyricsBox = $(lyricsBoxId);
    const msg = $(msgId);
    try{
      const url = new URL(K.endpoints.lyricsUrl);
      if (jobId) url.searchParams.set('job_id', jobId);
      if (!jobId && title)   url.searchParams.set('title', title);
      if (!jobId && artist)  url.searchParams.set('artist', artist);
      if (!jobId && duration)url.searchParams.set('duration', String(duration));

      if (msg) msg.textContent = jobId ? `Fetching lyrics for job ${jobId}…` : 'Fetching lyrics…';
      const r = await fetch(url.toString(), { mode:'cors' });
      const data = await r.json();

      if (!data || data.found === false) {
        if (lyricsBox) lyricsBox.textContent = 'No lyrics found.';
        if (msg) msg.textContent = '';
        return { found:false };
      }
      const text = (data.synced && data.lrc) ? data.lrc : (data.text || 'No lyrics text available.');
      if (lyricsBox) lyricsBox.textContent = text;
      if (msg) msg.textContent = 'Loaded.';
      return { found:true, text, synced:!!data.synced };
    } catch (e) {
      if (msg) msg.textContent = 'Failed to fetch lyrics.';
      return { found:false, error:String(e) };
    }
  }

  async function saveLyrics({ jobId, text, msgId }) {
    const msg = $(msgId);
    try{
      if (!jobId) throw new Error('No job id.');
      if (!text || !text.trim()) throw new Error('Paste lyrics before saving.');

      if (msg) msg.textContent = 'Saving…';
      const r = await fetch(K.endpoints.lyricsUrl, {
        method:'POST',
        mode:'cors',
        headers:{'Content-Type':'application/json; charset=utf-8'},
        body: JSON.stringify({ job_id: jobId, text })
      });
      const resp = await r.json().catch(()=>({}));
      if (!r.ok || resp.error) throw new Error(resp.error || `Save failed (${r.status})`);
      if (msg) msg.textContent = 'Saved.';
      return { ok:true };
    } catch (e) {
      if (msg) msg.textContent = e.message || 'Save failed.';
      return { ok:false, error:String(e) };
    }
  }

  // Expose shared API
  K.asUrl = asUrl;
  K.$ = $;
  K.setText = setText;
  K.initPlaybackControls = initPlaybackControls;
  K.loadLyrics = loadLyrics;
  K.saveLyrics = saveLyrics;

})(window);