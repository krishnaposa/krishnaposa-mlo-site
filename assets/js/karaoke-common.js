/* ===== karaoke-common.js =====
   Shared helpers:
   - API endpoints
   - $, asUrl
   - job id set/get (with input fallback)
   - playback controls initializer
   - loadLyrics() and saveLyrics()
*/
(function (w) {
  const API_BASE = 'https://karaoke-func-bthmcvafagcncmck.canadacentral-01.azurewebsites.net';
  const FUNCTION_CODE = ''; // if your function isn't anonymous, put code here
  const OUTPUT_BASE = '';   // leave '' for private (SAS)

  function buildUrl(path) {
    const q = FUNCTION_CODE ? `?code=${encodeURIComponent(FUNCTION_CODE)}` : '';
    return `${API_BASE}${path}${q}`;
  }

  const endpoints = {
    submitUrl: buildUrl('/api/submit'),
    statusUrl: (jobId) => buildUrl(`/api/status/${encodeURIComponent(jobId)}`),
    lyricsUrl: buildUrl('/api/lyrics'),
    listUrlFromMeta: () => {
      const m = document.querySelector('meta[name="karaoke-list"]');
      return m?.content || '';
    }
  };

  function $(id) { return document.getElementById(id); }
  function asUrl(valueOrKey) {
    if (/^https?:\/\//i.test(valueOrKey)) return valueOrKey;
    return OUTPUT_BASE ? `${OUTPUT_BASE.replace(/\/$/,'')}/${String(valueOrKey).replace(/^\/+/,'')}` : '#';
  }

  // -------- Job ID state (with input fallback) --------
  let _jobId = null;
  function setJobId(id) {
    _jobId = id || null;
    const box = $('lyrJobId');
    if (box && id) box.value = id;
  }
  function getJobId() {
    if (_jobId) return _jobId;
    const typed = ($('lyrJobId')?.value || '').trim();
    return typed || null;
  }

  // -------- Playback controls initializer --------
  function initPlaybackControls() {
    const vocalsEl  = $('vocalsEl');
    const bandEl    = $('bandEl');
    const vocalsOut = $('vocalsOut');
    const bandOut   = $('bandOut');
    const initBtn   = $('initAudio');
    const playBtn   = $('play');
    const pauseBtn  = $('pause');
    const restartBtn= $('restart');
    const offsetIn  = $('offset');
    const titleEl   = $('trackTitle');
    const deviceMsg = $('deviceMsg');

    const supportSink = typeof HTMLMediaElement?.prototype?.setSinkId === 'function';
    let isLoaded = false, isPlaying = false;
    let syncTimer = null;
    let sources = { vocals: '', band: '' };

    function showTitle(t){ if (titleEl) titleEl.textContent = t || '—'; }
    function setDeviceMsg(t){ if (deviceMsg) deviceMsg.textContent = t || ''; }
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
    initBtn?.addEventListener('click', async () => {
      setDeviceMsg('');
      if (!supportSink) { setDeviceMsg('Output selection not supported here. Use Chrome/Edge desktop.'); return; }
      if (!await ensurePermission()) return;
      const count = await listOutputs();
      initBtn.textContent = count ? 'Device list ready' : 'Device list (default only)';
      try { navigator.mediaDevices.addEventListener('devicechange', listOutputs); } catch {}
    });

    async function applySinks() {
      if (!supportSink) return;
      try { await vocalsEl?.setSinkId(vocalsOut?.value || 'default'); } catch{}
      try { await bandEl?.setSinkId(bandOut?.value   || 'default'); } catch{}
    }
    function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }
    function clearSyncTimer(){ if (syncTimer){ clearInterval(syncTimer); syncTimer=null; } }
    function onPlaybackPaused(){}
    function onPlaybackStarted(){}
    function pauseAll(){ clearSyncTimer(); try{vocalsEl?.pause()}catch{}; try{bandEl?.pause()}catch{}; if(vocalsEl) vocalsEl.playbackRate=1; if(bandEl) bandEl.playbackRate=1; isPlaying=false; onPlaybackPaused(); }
    function currentOffsetMs(){ return parseInt(offsetIn?.value || '0', 10) || 0; }
    function startDriftCorrection(offsetMs){
      clearSyncTimer();
      syncTimer = setInterval(() => {
        if (!isPlaying) return;
        const driftMs = (vocalsEl.currentTime - bandEl.currentTime) * 1000 - offsetMs;
        if (Math.abs(driftMs) > 60) {
          if (driftMs > 0) { const r=vocalsEl.playbackRate; vocalsEl.playbackRate=Math.max(0.9,r-0.05); setTimeout(()=>{vocalsEl.playbackRate=r},300); }
          else { const r=bandEl.playbackRate; bandEl.playbackRate=Math.max(0.9,r-0.05); setTimeout(()=>{bandEl.playbackRate=r},300); }
        }
      }, 2000);
    }
    async function preloadIfNeeded() {
      if (isLoaded) return;
      if (!sources.vocals || !sources.band || sources.vocals === '#' || sources.band === '#')
        throw new Error('No tracks loaded yet.');
      vocalsEl.src = sources.vocals;
      bandEl.src   = sources.band;
      await applySinks(); vocalsEl.load(); bandEl.load();
      await Promise.all([
        new Promise(r => vocalsEl.addEventListener('canplay', r, {once:true})),
        new Promise(r => bandEl.addEventListener('canplay', r, {once:true})),
      ]);
      isLoaded = true;
    }
    async function resumePlay(){
      await Promise.all([vocalsEl.play().catch(()=>{}), bandEl.play().catch(()=>{})]);
      isPlaying=true; startDriftCorrection(currentOffsetMs()); onPlaybackStarted();
    }
    async function startFromZeroWithOffset(offsetMs){
      vocalsEl.currentTime=0; bandEl.currentTime=0;
      if (offsetMs >= 0){ await bandEl.play(); await sleep(offsetMs); await vocalsEl.play(); }
      else { await vocalsEl.play(); await sleep(-offsetMs); await bandEl.play(); }
      isPlaying=true; startDriftCorrection(offsetMs); onPlaybackStarted();
    }

    playBtn?.addEventListener('click', async () => {
      try {
        if (!vocalsEl || !bandEl) return;
        if (isPlaying) return;
        await preloadIfNeeded();
        if (vocalsEl.paused && bandEl.paused && (vocalsEl.currentTime>0 || bandEl.currentTime>0)) await resumePlay();
        else await startFromZeroWithOffset(currentOffsetMs());
      } catch (e) { console.warn('play failed', e); alert(e.message || 'Could not start playback.'); }
    });
    pauseBtn?.addEventListener('click', pauseAll);
    restartBtn?.addEventListener('click', async () => {
      try { await preloadIfNeeded(); pauseAll(); await startFromZeroWithOffset(currentOffsetMs()); }
      catch (e) { console.warn('restart failed', e); alert(e.message || 'Could not restart playback.'); }
    });

    // expose a tiny API for pages
    return {
      setSources(vocals, band){
        sources.vocals = asUrl(vocals);
        sources.band   = asUrl(band);
        isLoaded = false; // force reload next play
      },
      showTitle: showTitle,
      getDurations(){
        return {
          vocals: parseFloat(vocalsEl?.duration || 0) || 0,
          band:   parseFloat(bandEl?.duration   || 0) || 0,
        };
      }
    };
  }

  // -------- Lyrics helpers --------
  function _setMsg(msgId, t){ const el=$(msgId); if (el) el.textContent = t || ''; }
  function _setBox(lyricsBoxId, text){ const el=$(lyricsBoxId); if (el) el.textContent = text ?? ''; }

  async function loadLyrics({ jobId, title, artist, duration, lyricsBoxId='lyricsBox', msgId='lyricsMsg' }) {
    const useJob = jobId || getJobId();
    try{
      const url = new URL(endpoints.lyricsUrl);
      if (useJob) {
        url.searchParams.set('job_id', useJob);
      } else {
        if (!title) { _setMsg(msgId, 'Provide a job id or a title.'); return; }
        url.searchParams.set('title', title);
        if (artist)   url.searchParams.set('artist', artist);
        if (duration) url.searchParams.set('duration', String(duration));
      }

      _setMsg(msgId, 'Fetching lyrics…');
      const r = await fetch(url.toString(), { mode:'cors' });
      const data = await r.json().catch(()=>null);
      if (!r.ok || !data) { _setMsg(msgId, 'Failed to fetch lyrics.'); return; }

      if (data.found === false) { _setBox(lyricsBoxId, '—'); _setMsg(msgId, ''); return; }

      const text = (data.synced && data.lrc) ? data.lrc : (data.text || '');
      _setBox(lyricsBoxId, text || '—');
      _setMsg(msgId, 'Loaded.');
    } catch (e) {
      console.warn(e);
      _setMsg(msgId, 'Failed to fetch lyrics.');
    }
  }

  async function saveLyrics({ jobId, text, msgId='lyricsMsg' }) {
    const useJob = jobId || getJobId();
    if (!useJob) { _setMsg(msgId, 'No job id. Paste it above.'); return; }
    const body = { job_id: useJob, text: (text || '').trim() };
    if (!body.text) { _setMsg(msgId, 'Paste lyrics before saving.'); return; }

    try{
      _setMsg(msgId, 'Saving…');
      const r = await fetch(endpoints.lyricsUrl, {
        method:'POST',
        mode:'cors',
        headers:{ 'Content-Type':'application/json; charset=utf-8' },
        body: JSON.stringify(body)
      });
      const data = await r.json().catch(()=>null);
      if (!r.ok || (data && data.error)) throw new Error(data?.error || `Save failed (${r.status})`);
      _setMsg(msgId, 'Saved.');
    } catch (e) {
      console.warn(e);
      _setMsg(msgId, e.message || 'Save failed.');
    }
  }

  // namespace
  w.KARAOKE = {
    endpoints, $, asUrl,
    setJobId, getJobId,
    initPlaybackControls,
    loadLyrics, saveLyrics,
    get currentJobId(){ return getJobId(); }
  };
})(window);