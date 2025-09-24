/* ===== karaoke-player.js =====
   Song picker + playback + load lyrics (read-only by default).
*/
(function (w) {
  const K = w.KARAOKE;
  w.KARAOKE_MODE = 'player';

  const LIST_URL = K.endpoints.listUrlFromMeta();

  const pick        = K.$('songPick');
  const useBtn      = K.$('useSelection');
  const refreshBtn  = K.$('refreshList');
  const listStatus  = K.$('listStatus');
  const jobIdView   = K.$('jobIdView'); // optional span to show job id
  const lyricsBtn   = K.$('loadLyrics');

  function setListStatus(t){ if (listStatus) listStatus.textContent = t || ''; }

  // Playback via common
  const PB = K.initPlaybackControls({});

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

      K.setJobId(jobId);       // writes to #lyrJobId if present
      if (jobIdView) jobIdView.textContent = jobId || '—';

      const lyricsBox = K.$('lyricsBox'); if (lyricsBox) lyricsBox.textContent = '—';
      const lyricsMsg = K.$('lyricsMsg'); if (lyricsMsg) lyricsMsg.textContent = '';
    }catch(e){ console.warn('Invalid selection', e); }
  });

  // Load lyrics: prefer job id (memory or typed)
  lyricsBtn?.addEventListener('click', async () => {
    const title = (K.$('trackTitle')?.textContent || '').trim();
    const durs  = PB.getDurations();
    await K.loadLyrics({
      jobId: K.getJobId(),
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