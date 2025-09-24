/* ===== karaoke-player.js =====
   Song picker + playback + load lyrics (read-only by default).
   Ensures job_id is captured (from list or derived from SAS URLs) so /api/lyrics
   is always called with ?job_id=... in player mode.
*/
(function (w) {
  const K = w.KARAOKE;

  // Tell common code this is player mode (optional)
  w.KARAOKE_MODE = 'player';

  const LIST_META = document.querySelector('meta[name="karaoke-list"]');
  const LIST_URL  = LIST_META?.content || '';

  const pick        = K.$('songPick');
  const useBtn      = K.$('useSelection');
  const refreshBtn  = K.$('refreshList');
  const listStatus  = K.$('listStatus');
  const jobIdView   = K.$('jobIdView');   // optional helper span in HTML
  const lyricsBtn   = K.$('loadLyrics');

  function setListStatus(t){ if (listStatus) listStatus.textContent = t || ''; }

  // Playback from shared/common code
  const PB = K.initPlaybackControls({});

  // ---------- Helpers ----------
  function extractJobIdFromUrl(u){
    try{
      const p = new URL(u).pathname.split('/');
      // expect .../karaoke-output/<job_id>/vocals.wav
      const i = p.findIndex(seg => seg === 'vocals.wav' || seg === 'no_vocals.wav');
      if (i > 0) return p[i-1] || null;
    }catch{}
    return null;
  }

  function getActiveUrls(){
    // Prefer hidden inputs if your common code fills them
    const v = document.getElementById('vocalsUrl')?.value || '';
    const b = document.getElementById('bandUrl')?.value   || '';
    return { vocals: v, band: b };
  }

  function bestJobIdFallback(){
    // 1) from selected option
    const opt = pick?.selectedOptions?.[0];
    if (opt?.dataset?.jobId) return opt.dataset.jobId;

    // 2) from current URLs in the page
    const { vocals, band } = getActiveUrls();
    return extractJobIdFromUrl(vocals) || extractJobIdFromUrl(band) || null;
  }

  // ---------- List loading ----------
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

      // newest first if timestamps present
      items.sort((a,b) => (b.updated||'').localeCompare(a.updated||''));

      for (const it of items) {
        const derivedId = extractJobIdFromUrl(it.vocals_url || it.band_url || '');
        const jobId = it.job_id || derivedId || '';
        const opt = document.createElement('option');
        opt.value = JSON.stringify({
          job_id: jobId,
          vocals: it.vocals_url,
          band:   it.band_url,
          title:  it.title || jobId || '(unknown)'
        });
        opt.dataset.jobId = jobId;                // <-- store for easy retrieval
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

      // Set sources + title
      PB.setSources(sel.vocals || '', sel.band || '');
      PB.showTitle(sel.title || 'Unknown Track');

      // Persist job id for lyrics fetch/save
      K.setJobId(jobId || bestJobIdFallback());
      if (jobIdView) jobIdView.textContent = K.currentJobId || '—';
      console.log('[player] currentJobId =', K.currentJobId);

      // Reset any previous lyrics UI
      const lyricsBox = K.$('lyricsBox'); if (lyricsBox) lyricsBox.textContent = '—';
      const lyricsMsg = K.$('lyricsMsg'); if (lyricsMsg) lyricsMsg.textContent = '';
    }catch(e){ console.warn('Invalid selection', e); }
  });

  // ---------- Load lyrics button ----------
  lyricsBtn?.addEventListener('click', async () => {
    // If for some reason common state is missing the jobId, try to recover it now
    if (!K.currentJobId) {
      const recovered = bestJobIdFallback();
      if (recovered) {
        K.setJobId(recovered);
        if (jobIdView) jobIdView.textContent = recovered;
        console.log('[player] recovered jobId =', recovered);
      }
    }

    const title = (K.$('trackTitle')?.textContent || '').trim();
    const durs  = PB.getDurations?.() || {};
    await K.loadLyrics({
      jobId: K.currentJobId,                                 // <-- critical
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