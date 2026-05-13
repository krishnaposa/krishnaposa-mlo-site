/* ===== karaoke-core.js =====
   Playback-only: dual-audio routing, LRC parse. No cloud code.
   Pages that upload/poll/list/load lyrics also load karaoke-azure.js (optional backend).
*/
(function (w) {
  const K = w.KARAOKE || (w.KARAOKE = {});

  K.endpoints = {};
  K.$ = (id) => document.getElementById(id);
  K.asUrl = (v) => /^https?:\/\//i.test(v) ? v : v;

  K.currentJobId = null;
  K.setJobId = (id) => { K.currentJobId = id || null; };

  K.initPlaybackControls = function initPlaybackControls (opts) {
    const o = opts && typeof opts === 'object' ? opts : {};
    const autoInitDevices = !!o.autoInitDevices;
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
    let _lastBlobV = '', _lastBlobB = '';
    let deviceChangeHooked = false;

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
    function hookDeviceChangeOnce(){
      if (deviceChangeHooked) return;
      deviceChangeHooked = true;
      try { navigator.mediaDevices.addEventListener('devicechange', listOutputs); } catch {}
    }
    async function initDeviceList(){
      setDeviceMsg('');
      if (!supportSink) { setDeviceMsg('Output selection not supported here. Use Chrome/Edge desktop.'); return; }
      if (!await ensurePermission()) return;
      let count = 0;
      try {
        count = await listOutputs();
      } catch (e) {
        setDeviceMsg('Could not list outputs: ' + (e && e.message ? e.message : String(e)));
        throw e;
      }
      if (initBtn) initBtn.textContent = count ? 'Device list ready' : 'Device list (default only)';
      hookDeviceChangeOnce();
    }
    initBtn?.addEventListener('click', () => {
      initDeviceList().catch((e) => { console.warn('initDeviceList', e); });
    });
    if (autoInitDevices) {
      void initDeviceList().catch(() => {
        if (deviceMsg && !String(deviceMsg.textContent || '').trim()) {
          setDeviceMsg('Use “Enable device list” if outputs did not load (some browsers need a tap first).');
        }
      });
    }

    vOut?.addEventListener('change', () => { applySinks().catch(() => {}); });
    bOut?.addEventListener('change', () => { applySinks().catch(() => {}); });

    async function applySinks(){
      if (!supportSink) return;
      const errs = [];
      try {
        await vEl?.setSinkId(vOut?.value || 'default');
      } catch (e) {
        errs.push('Vocals output: ' + (e && e.message ? e.message : e));
      }
      try {
        await bEl?.setSinkId(bOut?.value || 'default');
      } catch (e) {
        errs.push('Band output: ' + (e && e.message ? e.message : e));
      }
      if (errs.length) setDeviceMsg(errs.join(' · '));
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
      const off = currentOffsetMs();
      try {
        bEl.currentTime = Math.max(0, vEl.currentTime - off / 1000);
        vEl.playbackRate = 1;
        bEl.playbackRate = 1;
      } catch {}
    }

    function _mediaErrorDetail(el, label){
      const e = el?.error;
      if (!e) return `${label}: unknown media error`;
      const codes = { 1: 'ABORTED', 2: 'NETWORK', 3: 'DECODE', 4: 'SRC_NOT_SUPPORTED' };
      return `${label}: ${codes[e.code] || e.code} (${e.message || 'no message'})`;
    }

    async function preloadIfNeeded(){
      if (isLoaded) {
        await applySinks();
        return;
      }
      if (!vEl?.src || !bEl?.src) {
        throw new Error('No audio loaded yet — load stems first.');
      }
      vEl.load();
      bEl.load();
      const waitOne = (el, label) =>
        new Promise((resolve, reject) => {
          const to = setTimeout(() => {
            el.removeEventListener('canplay', onOk);
            el.removeEventListener('error', onErr);
            reject(new Error(`${label}: timed out waiting to load (network/CORS/blob URL).`));
          }, 45000);
          function onOk(){
            clearTimeout(to);
            el.removeEventListener('error', onErr);
            resolve();
          }
          function onErr(){
            clearTimeout(to);
            el.removeEventListener('canplay', onOk);
            reject(new Error(_mediaErrorDetail(el, label)));
          }
          el.addEventListener('canplay', onOk, { once: true });
          el.addEventListener('error', onErr, { once: true });
        });
      await Promise.all([waitOne(vEl, 'Vocals'), waitOne(bEl, 'Band')]);
      await applySinks();
      isLoaded = true;
    }

    async function resumePlay(){
      await applySinks();
      const [vr, br] = await Promise.allSettled([vEl.play(), bEl.play()]);
      const errs = [vr, br].filter((x) => x.status === 'rejected').map((x) => (x.reason && x.reason.message) || String(x.reason));
      if (errs.length) {
        throw new Error('Play blocked: ' + errs.join(' | ') + ' (try interacting with the page first, or check browser autoplay settings.)');
      }
      isPlaying = true;
      startDriftCorrection(currentOffsetMs());
    }

    async function startFromZeroWithOffset(offsetMs){
      vEl.currentTime = 0;
      bEl.currentTime = 0;
      const playOrThrow = (el, label) =>
        el.play().catch((err) => {
          throw new Error(`${label}: ${err?.message || err}`);
        });
      try {
        await applySinks();
        if (offsetMs >= 0) {
          await playOrThrow(bEl, 'Band');
          await new Promise((r) => setTimeout(r, offsetMs));
          await playOrThrow(vEl, 'Vocals');
        } else {
          await playOrThrow(vEl, 'Vocals');
          await new Promise((r) => setTimeout(r, -offsetMs));
          await playOrThrow(bEl, 'Band');
        }
      } catch (e) {
        pauseAll();
        throw e;
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

    return {
      setSources(vocalsUrl, bandUrl){
        if (!vEl || !bEl) return;
        const v = (vocalsUrl == null ? '' : String(vocalsUrl)).trim();
        const b = (bandUrl == null ? '' : String(bandUrl)).trim();
        if (_lastBlobV && _lastBlobV.startsWith('blob:')) {
          try { URL.revokeObjectURL(_lastBlobV); } catch {}
        }
        if (_lastBlobB && _lastBlobB.startsWith('blob:')) {
          try { URL.revokeObjectURL(_lastBlobB); } catch {}
        }
        _lastBlobV = v.startsWith('blob:') ? v : '';
        _lastBlobB = b.startsWith('blob:') ? b : '';
        isLoaded = false;
        vEl.src = v;
        bEl.src = b;
      },
      showTitle(t){ const el = K.$('trackTitle'); if (el) el.textContent = t || '—'; },
      getDurations(){ return { vocals: vEl?.duration || 0, band: bEl?.duration || 0 }; },
      pause: pauseAll,
      hardResync,
    };
  };

  K.syncNow = () => {
    console.warn('syncNow called before playback init');
  };

  K._onPlaybackStarted = null;
  K._onPlaybackPaused = null;

  K.parseLRC = function parseLRC(lrc){
    const out=[], re=/\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\](.*)/g; let m;
    while((m=re.exec(lrc))!==null){
      const min=+m[1], sec=+m[2], ms=m[3]?+m[3].padEnd(3,'0'):0;
      out.push({ t: min*60 + sec + ms/1000, text:(m[4]||'').trim() });
    }
    return out.sort((a,b)=>a.t-b.t);
  };

  K.loadLyrics = async function loadLyrics(){
    /* Overwritten when karaoke-azure.js is loaded. */
  };

})(window);
