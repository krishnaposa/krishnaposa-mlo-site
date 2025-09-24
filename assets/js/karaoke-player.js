/* ===== karaoke-player.js =====
   Song picker + playback + load lyrics + enable device list.
*/
(function (w) {
  const K = w.KARAOKE;
  w.KARAOKE_MODE = 'player';

  // ----- Elements -----
  const LIST_META = document.querySelector('meta[name="karaoke-list"]');
  const LIST_URL  = LIST_META?.content || '';

  const pick        = K.$('songPick');
  const useBtn      = K.$('useSelection');
  const refreshBtn  = K.$('refreshList');
  const listStatus  = K.$('listStatus');
  const jobIdView   = K.$('jobIdView');         // optional helper in HTML
  const lyricsBtn   = K.$('loadLyrics');

  const initBtn     = K.$('initAudio');
  const vocalsOut   = K.$('vocalsOut');
  const bandOut     = K.$('bandOut');
  const deviceMsg   = K.$('deviceMsg');

  // Playback controller from common bundle
  const PB = K.initPlaybackControls({});

  function setListStatus(t){ if (listStatus) listStatus.textContent = t || ''; }
  function setDeviceMsg(t){ if (deviceMsg) deviceMsg.textContent = t || ''; }

  // ---------- Enable device list (self-contained) ----------
  const supportSink = typeof HTMLMediaElement.prototype.setSinkId === 'function';

  async function ensurePermission() {
    try {
      // Needed so browsers reveal device labels
      await navigator.mediaDevices.getUserMedia({ audio: true });
      return true;
    } catch (e) {
      setDeviceMsg('Please allow microphone access to list audio outputs.');
      return false;
    }
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
    try {
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
    } catch (e) {
      console.warn('enumerateDevices failed', e);
      setDeviceMsg('Could not list outputs.');
      addDefaultFallback(vocalsOut);
      addDefaultFallback(bandOut);
      return 0;
    }
  }

  initBtn?.addEventListener('click', async () => {
    if (!supportSink) {
      setDeviceMsg('Output selection not supported here. Use Chrome/Edge desktop.');
      return;
    }
    if (location.protocol !== 'https:') {
      setDeviceMsg('Needs HTTPS to access device list.');
      return;
    }
    setDeviceMsg('');
    if (!await ensurePermission()) return;
    const count = await listOutputs();
    initBtn.textContent = count ? 'Device list ready' : 'Device list (default only)';
    try { navigator.mediaDevices.addEventListener('devicechange', listOutputs); } catch {}
    // hand off selected sinks to playback engine
    PB.applySinks?.(vocalsOut?.value || 'default', bandOut?.value || 'default');
    vocalsOut?.addEventListener('change', () => PB.applySinks?.(vocalsOut.value, bandOut?.value || 'default'));
    bandOut  ?.addEventListener('change', () => PB.applySinks?.(vocalsOut?.value || 'default', bandOut.value));
  });

  // ---------- Song list ----------
  function extractJobIdFromUrl(u){
    try{
      const p = new URL(u).pathname.split('/');
      const i = p.findIndex(seg => seg === 'vocals.wav' || seg === 'no_vocals.wav');
      if (i > 0) return p[i-1] || null;
    }catch{}
    return null;
  }

  async function loadList(){
    try{
      if (!LIST_URL) throw new Error('Missing karaoke-list URL meta.');
      setListStatus('Loading songs…');

      const res = await fetch(LIST_URL, { mode:'cors' });
      if (!res.ok) throw new Error(`List failed (${res.status})`);
      const data = await res.json();
      const items = (data && data.items) || [];

      if (pick) pick.innerHTML = '';
      if (!items.length) {
        pick.innerHTML = '<option value="">No completed songs yet</option>';
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
        opt.textContent = it.title || jobId || '(unknown)';
        pick.appendChild(opt);
      }
      setListStatus(`Loaded ${items.length} song(s).`);
    } catch (e) {
      console.warn(e);
      setListStatus('Could not load list. ' + (e.message || e));
    }
  }

  useBtn?.addEventListener('click', () => {
    const val = pick?.value;
    if (!val) return;
    try{
      const sel = JSON.parse(val);
      const jobId = pick?.selectedOptions?.[0]?.dataset?.jobId || sel.job_id || null;

      PB.setSources(sel.vocals || '', sel.band || '');
      PB.showTitle(sel.title || 'Unknown Track');

      K.setJobId(jobId);
      if (jobIdView) jobIdView.textContent = jobId || '—';

      const lyricsBox = K.$('lyricsBox'); if (lyricsBox) lyricsBox.textContent = '—';
      const lyricsMsg = K.$('lyricsMsg'); if (lyricsMsg) lyricsMsg.textContent = '';
    }catch(e){ console.warn('Invalid selection', e); }
  });

  // ---------- Lyrics load ----------
  lyricsBtn?.addEventListener('click', async () => {
    const title = (K.$('trackTitle')?.textContent || '').trim();
    const durs  = PB.getDurations();
    await K.loadLyrics({
      jobId: K.currentJobId,                                   // <- comes from K.setJobId above
      title: title && title !== '—' ? title : '',
      artist: (K.$('lyrArtist')?.value || '').trim(),
      duration: Math.round(durs.band || durs.vocals || 0),
      lyricsBoxId: 'lyricsBox',
      msgId: 'lyricsMsg'
    });
  });

  refreshBtn?.addEventListener('click', loadList);
  loadList();
})(window);