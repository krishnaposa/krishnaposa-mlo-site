/* ===== karaoke-player.js =====
   List finished splits, route vocals vs band to different devices, lyrics (read-only).
*/
(function (w) {
  const K = w.KARAOKE;

  // Player mode
  w.KARAOKE_MODE = 'player';

  const LIST_META = document.querySelector('meta[name="karaoke-list"]');
  // Prefer API_BASE from karaoke-common.js; meta tag overrides if set (non-empty).
  const LIST_URL = (LIST_META?.content && LIST_META.content.trim())
    ? LIST_META.content.trim()
    : (K.endpoints && K.endpoints.listUrl) || '';

  const pick        = K.$('songPick');
  const useBtn      = K.$('useSelection');
  const refreshBtn  = K.$('refreshList');
  const listStatus  = K.$('listStatus');
  const lyricsBtn   = K.$('loadLyrics');

  function setListStatus(t){ if (listStatus) listStatus.textContent = t || ''; }

  // Playback from common
  const PB = K.initPlaybackControls();
  // expose syncNow to the button via common
  K.syncNow = PB.hardResync;

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
      if (!LIST_URL) throw new Error('Missing list URL: set meta name="karaoke-list" or API_BASE in karaoke-common.js.');
      setListStatus('Loading songs…');

      const res = await fetch(LIST_URL, { mode:'cors' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const err = (data && data.error) ? String(data.error) : res.statusText;
        throw new Error(`List failed (${res.status}): ${err}`);
      }
      if (data && data.error) {
        throw new Error(String(data.error));
      }
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

      // sources + title
      PB.setSources(sel.vocals || '', sel.band || '');
      PB.showTitle(sel.title || 'Unknown Track');

      // job id stored globally so lyrics load uses it
      K.setJobId(jobId);

      // reset lyrics area
      const lyricsBox = K.$('lyricsBox'); if (lyricsBox) lyricsBox.textContent = '—';
      const lyricsMsg = K.$('lyricsMsg'); if (lyricsMsg) lyricsMsg.textContent = '';
    }catch(e){ console.warn('Invalid selection', e); }
  });

  // Lyrics: load by job id (preferred)
  lyricsBtn?.addEventListener('click', async () => {
    const title = (K.$('trackTitle')?.textContent || '').trim();
    const durs  = PB.getDurations();
    await K.loadLyrics({
      jobId: K.currentJobId,                           // << uses selected job
      title: title && title !== '—' ? title : '',
      artist: (K.$('lyrArtist')?.value || '').trim(),
      duration: Math.round(durs.band || durs.vocals || 0),
      lyricsBoxId: 'lyricsBox',
      msgId: 'lyricsMsg'
    });
  });

  // Sync now button (hard, immediate alignment)
  K.$('syncNow')?.addEventListener('click', () => K.syncNow?.());

  refreshBtn?.addEventListener('click', loadList);
  loadList();
})(window);