/* ===== karaoke-player.js =====
   Song picker + playback + load lyrics.
*/
(function (w) {
  const K = w.KARAOKE || {};
  w.KARAOKE_MODE = 'player';

  // ---------- Elements ----------
  const LIST_META   = document.querySelector('meta[name="karaoke-list"]');
  const LIST_URL    = LIST_META?.content || '';

  const pick        = K.$?.('songPick')        || document.getElementById('songPick');
  const useBtn      = K.$?.('useSelection')    || document.getElementById('useSelection');
  const refreshBtn  = K.$?.('refreshList')     || document.getElementById('refreshList');
  const listStatus  = K.$?.('listStatus')      || document.getElementById('listStatus');
  const jobIdView   = K.$?.('jobIdView')       || document.getElementById('jobIdView');

  // Output routing elems
  const vocalsOut   = K.$?.('vocalsOut')       || document.getElementById('vocalsOut');
  const bandOut     = K.$?.('bandOut')         || document.getElementById('bandOut');
  const initBtn     = K.$?.('initAudio')       || document.getElementById('initAudio');
  const deviceMsgEl = K.$?.('deviceMsg')       || document.getElementById('deviceMsg');

  // Lyrics
  const lyricsBtn   = K.$?.('loadLyrics')      || document.getElementById('loadLyrics');
  const lyricsBoxId = 'lyricsBox';
  const lyricsMsgId = 'lyricsMsg';

  function setListStatus(t){ if (listStatus) listStatus.textContent = t || ''; }
  function setDeviceMsg(t){ if (deviceMsgEl) deviceMsgEl.textContent = t || ''; }

  // ---------- Playback from common ----------
  const PB = (K.initPlaybackControls && K.initPlaybackControls({})) || {
    setSources(){}, showTitle(){}, getDurations(){ return {}; }
  };

  // ---------- Helpers ----------
  function extractJobIdFromUrl(u){
    try{
      const p = new URL(u).pathname.split('/').filter(Boolean);
      const i = p.findIndex(seg => seg === 'vocals.wav' || seg === 'no_vocals.wav');
      if (i > 0) return p[i-1] || null;
    }catch{}
    return null;
  }

  function getCurrentJobIdFallback() {
    // Prefer K.currentJobId if present
    if (K.currentJobId) return K.currentJobId;
    // Try selected option data
    const opt = pick?.selectedOptions?.[0];
    if (opt?.dataset?.jobId) return opt.dataset.jobId;
    // Try from current URLs if PB stored them on hidden inputs
    const v = document.getElementById('vocalsUrl')?.value || '';
    const b = document.getElementById('bandUrl')?.value   || '';
    return extractJobIdFromUrl(v) || extractJobIdFromUrl(b) || null;
  }

  // ---------- Load list ----------
  async function loadList(){
    try{
      if (!LIST_URL) throw new Error('Missing karaoke-list URL meta.');
      setListStatus('Loading songs…');

      const res = await fetch(LIST_URL, { mode:'cors' });
      if (!res.ok) throw new Error(`List failed (${res.status})`);
      const data  = await res.json();
      const items = (data && data.items) || [];

      if (pick) pick.innerHTML = '';
      if (!items.length) {
        if (pick) pick.innerHTML = '<option value="">No completed songs yet</option>';
        setListStatus('');
        return;
      }

      items.sort((a,b) => (b.updated||'').localeCompare(a.updated||''));

      for (const it of items) {
        const opt = document.createElement('option');
        const derivedId = extractJobIdFromUrl(it.vocals_url || it.band_url || '');
        const jobId = it.job_id || derivedId || '';
        opt.value = JSON.stringify({
          job_id: jobId,
          vocals: it.vocals_url,
          band:   it.band_url,
          title:  it.title || jobId || '(unknown)'
        });
        opt.dataset.jobId = jobId;
        opt.textContent   = it.title || jobId || '(unknown)';
        pick.appendChild(opt);
      }
      setListStatus(`Loaded ${items.length} song(s).`);
    } catch (e) {
      console.warn(e);
      setListStatus('Could not load list. ' + (e.message || e));
    }
  }

  // ---------- Use selection ----------
  useBtn?.addEventListener('click', () => {
    const val = pick?.value;
    if (!val) return;
    try{
      const sel   = JSON.parse(val);
      const jobId = pick?.selectedOptions?.[0]?.dataset?.jobId || sel.job_id || null;

      PB.setSources(sel.vocals || '', sel.band || '');
      PB.showTitle(sel.title || 'Unknown Track');

      // Remember job id for lyrics
      if (typeof K.setJobId === 'function') K.setJobId(jobId);
      K.currentJobId = jobId;
      if (jobIdView) jobIdView.textContent = jobId || '—';

      // Reset lyrics preview/message if present
      const box = document.getElementById(lyricsBoxId); if (box) box.textContent = '—';
      const msg = document.getElementById(lyricsMsgId); if (msg) msg.textContent = '';
    }catch(e){ console.warn('Invalid selection', e); }
  });

  // ---------- Device list (Enable device list) ----------
  const supportSink = typeof HTMLMediaElement.prototype.setSinkId === 'function';

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
    if (outs.length) {
      fillSelect(vocalsOut, outs);
      fillSelect(bandOut, outs);
      setDeviceMsg(`Found ${outs.length} output device(s).`);
    } else {
      addDefaultFallback(vocalsOut);
      addDefaultFallback(bandOut);
      setDeviceMsg('No discrete outputs reported. Using system default.');
    }
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

  // ---------- Beep tests ----------
  function playBeep(which, sinkId, freq=880, ms=600) {
    if (!supportSink) { alert('Output selection not supported in this browser.'); return; }

    const outEl = new Audio();
    outEl.setAttribute('playsinline','');
    outEl.style.display = 'none';

    const AC   = (window.AudioContext || window.webkitAudioContext);
    const ac   = new AC();
    const osc  = ac.createOscillator();
    const gain = ac.createGain();

    gain.gain.setValueAtTime(0.0001, ac.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.3, ac.currentTime + 0.02);

    osc.frequency.value = freq;
    osc.type = 'sine';

    const dest = ac.createMediaStreamDestination();
    osc.connect(gain);
    gain.connect(dest);

    outEl.srcObject = dest.stream;

    (async () => {
      try { await outEl.setSinkId(sinkId || 'default'); } catch {}
      try {
        osc.start();
        await outEl.play();
        const endT = ac.currentTime + ms/1000;
        gain.gain.exponentialRampToValueAtTime(0.0001, endT-0.05);
        osc.stop(endT);
      } finally {
        setTimeout(() => {
          outEl.pause();
          outEl.srcObject = null;
          ac.close().catch(()=>{});
        }, ms+120);
      }
    })();
  }

  document.getElementById('testVocals')?.addEventListener('click', () =>
    playBeep('vocals', vocalsOut?.value, 880, 500)
  );
  document.getElementById('testBand')?.addEventListener('click', () =>
    playBeep('band', bandOut?.value, 660, 500)
  );

  // ---------- Load lyrics (by job id) ----------
  lyricsBtn?.addEventListener('click', async () => {
    const jobId = (typeof K.getJobId === 'function' && K.getJobId()) || getCurrentJobIdFallback();
    if (!jobId) {
      const msg = document.getElementById(lyricsMsgId);
      if (msg) msg.textContent = 'No job id. Pick a song first.';
      return;
    }

    const title = (document.getElementById('trackTitle')?.textContent || '').trim();
    const durs  = PB.getDurations?.() || {};
    await K.loadLyrics({
      jobId,
      title: title && title !== '—' ? title : '',
      artist: (document.getElementById('lyrArtist')?.value || '').trim(),
      duration: Math.round(durs.band || durs.vocals || 0),
      lyricsBoxId,
      msgId: lyricsMsgId
    });
  });

  // ---------- Init ----------
  refreshBtn?.addEventListener('click', loadList);
  loadList();

})(window);