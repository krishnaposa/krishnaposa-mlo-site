/* ===== karaoke-common.js =====
   Shared helpers (state, endpoints, playback, lyrics).
*/
(function (w) {
  const API_BASE = 'https://karaoke-func-bthmcvafagcncmck.canadacentral-01.azurewebsites.net';
  const FUNCTION_CODE = ''; // if your function needs ?code=
  const withCode = (u) => FUNCTION_CODE ? `${u}?code=${FUNCTION_CODE}` : u;

  const K = w.KARAOKE || (w.KARAOKE = {});

  // --- Endpoints ---
  K.endpoints = {
    submitUrl : withCode(`${API_BASE}/api/submit`),
    statusUrl : (jobId) => withCode(`${API_BASE}/api/status/${encodeURIComponent(jobId)}`),
    lyricsUrl : withCode(`${API_BASE}/api/lyrics`),
  };

  // --- Utilities ---
  K.$ = (id) => document.getElementById(id);
  K.asUrl = (v) => /^https?:\/\//i.test(v) ? v : v; // expecting SAS/absolute

  // --- Job state ---
  K.currentJobId = null;
  K.setJobId = (id) => { K.currentJobId = id || null; };

  // --- Playback controls (dual audio elements + routing) ---
  K.initPlaybackControls = function initPlaybackControls () {
    const vEl = K.$('vocalsEl');
    const bEl = K.$('bandEl');
    const playBtn = K.$('play');
    const pauseBtn = K.$('pause');
    const restartBtn = K.$('restart');
    const offsetIn = K.$('offset');
    const initBtn = K.$('initAudio');
    const vOut = K.$('vocalsOut');
    const bOut = K.$('bandOut');
    const deviceMsg = K.$('deviceMsg');

    const supportSink = typeof HTMLMediaElement.prototype.setSinkId === 'function';
    let isLoaded = false, isPlaying = false, driftTimer = null;

    function setDeviceMsg(t){ if (deviceMsg) deviceMsg.textContent = t || ''; }
    async function ensurePermission(){
      try { await navigator.mediaDevices.getUserMedia({ audio:true }); return true; }
      catch { setDeviceMsg('Please allow microphone access to list audio outputs.'); return false; }
    }
    function fillSelect(sel, outs){
      sel.innerHTML = '';
      outs.forEach(d => {
        const o = document.createElement('option');
        o.value = d.deviceId; o.textContent = d.label || `Output ${d.deviceId}`;
        sel.appendChild(o);
      });
      const def = outs.find(d => d.deviceId === 'default');
      sel.value = def ? def.deviceId : (outs[0]?.deviceId || 'default');
    }
    function addDefault(sel){
      sel.innerHTML = '';
      const o = document.createElement('option');
      o.value = 'default'; o.textContent = 'System default';
      sel.appendChild(o); sel.value = 'default';
    }
    async function listOutputs(){
      const devs = await navigator.mediaDevices.enumerateDevices();
      const outs = devs.filter(d => d.kind === 'audiooutput');
      if (outs.length) { fillSelect(vOut, outs); fillSelect(bOut, outs); setDeviceMsg(`Found ${outs.length} output device(s).`); }
      else { addDefault(vOut); addDefault(bOut); setDeviceMsg('No discrete outputs reported. Using system default.'); }
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

    async function applySinks(){
      if (!supportSink) return;
      try { await vEl?.setSinkId(vOut?.value || 'default'); } catch {}
      try { await bEl?.setSinkId(bOut?.value || 'default'); } catch {}
    }

    function currentOffsetMs(){
      const v = parseInt((offsetIn?.value || '0'), 10);
      return Number.isFinite(v) ? v : 0;
    }

    function clearDriftTimer(){
      if (driftTimer) { clearInterval(driftTimer); driftTimer = null; }
    }

    function startDriftCorrection(offsetMs){
      clearDriftTimer();
      driftTimer = setInterval(() => {
        if (!isPlaying || !vEl || !bEl) return;
        const driftMs = (vEl.currentTime - bEl.currentTime) * 1000 - offsetMs;
        if (Math.abs(driftMs) > 60) {
          if (driftMs > 0) {
            const r = vEl.playbackRate; vEl.playbackRate = Math.max(0.9, r - 0.05);
            setTimeout(() => { vEl.playbackRate = r; }, 300);
          } else {
            const r = bEl.playbackRate; bEl.playbackRate = Math.max(0.9, r - 0.05);
            setTimeout(() => { bEl.playbackRate = r; }, 300);
          }
        }
      }, 2000);
    }

    function hardResync(){
      if (!vEl || !bEl) return;
      const off = currentOffsetMs(); // vocals leads by off ms
      try {
        // align band to vocals - off
        bEl.currentTime = Math.max(0, vEl.currentTime - off / 1000);
        vEl.playbackRate = 1;
        bEl.playbackRate = 1;
      } catch {}
    }

    async function preloadIfNeeded(){
      if (isLoaded) return;
      await applySinks();
      vEl.load(); bEl.load();
      await Promise.all([
        new Promise(r => vEl.addEventListener('canplay', r, {once:true})),
        new Promise(r => bEl.addEventListener('canplay', r, {once:true})),
      ]);
      isLoaded = true;
    }

    async function resumePlay(){
      await Promise.all([ vEl.play().catch(()=>{}), bEl.play().catch(()=>{}) ]);
      isPlaying = true;
      startDriftCorrection(currentOffsetMs());
    }

    async function startFromZeroWithOffset(offsetMs){
      vEl.currentTime = 0; bEl.currentTime = 0;
      if (offsetMs >= 0) {
        await bEl.play(); await new Promise(r=>setTimeout(r, offsetMs)); await vEl.play();
      } else {
        await vEl.play(); await new Promise(r=>setTimeout(r, -offsetMs)); await bEl.play();
      }
      isPlaying = true;
      startDriftCorrection(offsetMs);
    }

    function pauseAll(){
      clearDriftTimer();
      try { vEl.pause(); } catch {}
      try { bEl.pause(); } catch {}
      if (vEl) vEl.playbackRate = 1;
      if (bEl) bEl.playbackRate = 1;
      isPlaying = false;
      if (K._onPlaybackPaused) K._onPlaybackPaused();
    }

    playBtn?.addEventListener('click', async () => {
      try {
        if (!vEl || !bEl) return;
        await preloadIfNeeded();
        if (vEl.paused && bEl.paused && (vEl.currentTime > 0 || bEl.currentTime > 0)) await resumePlay();
        else await startFromZeroWithOffset(currentOffsetMs());
        if (K._onPlaybackStarted) K._onPlaybackStarted();
      } catch (e) {
        console.warn('play failed', e);
        alert(e?.message || 'Could not start playback.');
      }
    });
    pauseBtn?.addEventListener('click', pauseAll);
    restartBtn?.addEventListener('click', async () => {
      try {
        await preloadIfNeeded();
        pauseAll();
        await startFromZeroWithOffset(currentOffsetMs());
        if (K._onPlaybackStarted) K._onPlaybackStarted();
      } catch (e) {
        console.warn('restart failed', e);
        alert(e?.message || 'Could not restart playback.');
      }
    });

    // Beep tests
    const _beepVoc = document.createElement('audio');
    const _beepBand = document.createElement('audio');
    _beepVoc.setAttribute('playsinline',''); _beepVoc.style.display='none';
    _beepBand.setAttribute('playsinline',''); _beepBand.style.display='none';
    document.body.appendChild(_beepVoc); document.body.appendChild(_beepBand);
    async function playBeep(which, sinkId, freq=880, ms=600){
      if (!supportSink){ alert('Output selection not supported in this browser.'); return; }
      const outEl = which==='band'? _beepBand : _beepVoc;
      const ac = new (w.AudioContext||w.webkitAudioContext)();
      const osc=ac.createOscillator(); const gain=ac.createGain();
      gain.gain.setValueAtTime(0.0001, ac.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.3, ac.currentTime+0.02);
      osc.frequency.value=freq; osc.type='sine';
      const dest=ac.createMediaStreamDestination();
      osc.connect(gain); gain.connect(dest);
      try{ await outEl.setSinkId(sinkId||'default'); }catch{}
      outEl.srcObject = dest.stream;
      try{
        osc.start(); await outEl.play();
        const endT=ac.currentTime+ms/1000;
        gain.gain.exponentialRampToValueAtTime(0.0001, endT-0.05);
        osc.stop(endT);
        setTimeout(()=>{ outEl.pause(); outEl.srcObject=null; ac.close().catch(()=>{}); }, ms+120);
      }catch{
        ac.close().catch(()=>{});
      }
    }
    K.$('testVocals')?.addEventListener('click', ()=>playBeep('vocals', vOut?.value, 880, 500));
    K.$('testBand')?.addEventListener('click',   ()=>playBeep('band',   bOut?.value, 660, 500));

    // Public API from playback
    return {
      setSources(vocalsUrl, bandUrl){
        if (!vEl || !bEl) return;
        isLoaded = false; // force reload
        vEl.src = vocalsUrl;
        bEl.src = bandUrl;
      },
      showTitle(t){ const el = K.$('trackTitle'); if (el) el.textContent = t || '—'; },
      getDurations(){ return { vocals: vEl?.duration || 0, band: bEl?.duration || 0 }; },
      pause: pauseAll,
      hardResync,
    };
  };

  // Expose Sync-now so player can wire a button
  K.syncNow = () => {
    // Will be replaced by the instance returned from initPlaybackControls
    console.warn('syncNow called before playback init');
  };

  // Wire syncNow after initPlaybackControls returns the instance
  // (player code will set K.syncNow = PB.hardResync)

  // --- Lyrics helpers (read-only load here) ---
  K._onPlaybackStarted = null;
  K._onPlaybackPaused = null;

  // simple LRC parser + live preview support
  function parseLRC(lrc){
    const out=[], re=/\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\](.*)/g; let m;
    while((m=re.exec(lrc))!==null){
      const min=+m[1], sec=+m[2], ms=m[3]?+m[3].padEnd(3,'0'):0;
      out.push({ t: min*60 + sec + ms/1000, text:(m[4]||'').trim() });
    }
    return out.sort((a,b)=>a.t-b.t);
  }

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
        // optional: you can render a rolling preview if you want
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