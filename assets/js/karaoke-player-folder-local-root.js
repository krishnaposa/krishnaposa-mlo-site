/* ===== karaoke-player-folder-local-root.js =====
   Lists completed jobs from local_folder_queue.py (KARAOKE_LOCAL_ROOT tree via GET /api/list),
   loads stems and lyrics over HTTP — no directory picker.
*/
(function (w) {
  const K = w.KARAOKE;
  if (!K || typeof K.initPlaybackControls !== 'function') {
    console.error('karaoke-player-folder-local-root.js: load karaoke-core.js first.');
    return;
  }
  w.KARAOKE_MODE = 'player-folder-local-root';

  const folderScanSummary = K.$('folderScanSummary');
  const folderLoadStatus = K.$('folderLoadStatus');
  const songPick = K.$('folderSongPick');
  const songPickWrap = K.$('songPickWrap');
  const refreshBtn = K.$('refreshList');
  const searchModeQuick = K.$('searchModeQuick');
  const searchModeAdvanced = K.$('searchModeAdvanced');
  const advancedFiltersWrap = K.$('advancedFilters');
  const searchQ = K.$('searchQ');
  const filterTitle = K.$('filterTitle');
  const filterLanguage = K.$('filterLanguage');
  const filterCategory = K.$('filterCategory');
  const filterTags = K.$('filterTags');
  const filterSinger = K.$('filterSinger');
  const filterActor = K.$('filterActor');
  const filterText = K.$('filterText');
  const applyFiltersBtn = K.$('applyFilters');
  const clearFiltersBtn = K.$('clearFilters');

  /** @type {{ job_id: string, title?: string, vocals_url?: string, band_url?: string }[]} */
  let listItems = [];

  function apiOrigin() {
    try {
      return new URL(K.endpoints.listUrl).origin;
    } catch {
      return '';
    }
  }

  /** Use the same host as <code>?api=</code> so stems work over HTTPS/ngrok even when /api/list returns http://127.0.0.1/… links. */
  function resolveStemUrl(u) {
    if (!u || typeof u !== 'string') return u;
    const origin = apiOrigin();
    if (!origin) return u;
    try {
      const p = new URL(u, origin);
      return origin + p.pathname + p.search + p.hash;
    } catch {
      return u;
    }
  }

  /** ngrok free tier often needs this header on non-browser GETs; safe to send whenever host looks like ngrok. */
  function apiFetch(input, init) {
    const next = init ? { ...init } : {};
    next.headers = next.headers ? { ...next.headers } : {};
    let host = '';
    try {
      host = new URL(typeof input === 'string' ? input : String(input)).hostname;
    } catch {
      /* ignore */
    }
    if (/ngrok/i.test(host) && next.headers['ngrok-skip-browser-warning'] == null) {
      next.headers['ngrok-skip-browser-warning'] = '69420';
    }
    return fetch(input, next);
  }

  function explainListError(e) {
    const msg = e && e.message ? e.message : String(e);
    const isHttps = typeof location !== 'undefined' && location.protocol === 'https:';
    let api = '';
    try {
      api = new URL(K.endpoints.listUrl).protocol;
    } catch {
      /* ignore */
    }
    if (
      isHttps &&
      api === 'http:' &&
      (msg.includes('Failed to fetch') || msg.includes('NetworkError') || msg.includes('Load failed'))
    ) {
      return (
        msg +
        ' — Browsers block http:// API calls from an https:// page. Add a tunnel to port 8787 and open this page with ' +
        '?api=https://YOUR-TUNNEL (see the yellow note above).'
      );
    }
    return msg;
  }

  const PB = K.initPlaybackControls();
  K.syncNow = PB.hardResync;

  let lrcCleanup = null;
  function stopLrcSync() {
    if (typeof lrcCleanup === 'function') {
      try {
        lrcCleanup();
      } catch (_) {}
    }
    lrcCleanup = null;
  }

  function renderLrcLines(container, lines) {
    container.innerHTML = '';
    lines.forEach((line, i) => {
      const div = document.createElement('div');
      div.className = 'lyrics-line';
      div.dataset.idx = String(i);
      div.textContent = line.text || ' ';
      container.appendChild(div);
    });
  }

  function startLrcSync(lines) {
    stopLrcSync();
    const vocalsEl = K.$('vocalsEl');
    const box = K.$('lyricsSynced');
    if (!vocalsEl || !box || !lines.length) return;

    const lineEls = () => [...box.querySelectorAll('.lyrics-line')];
    let lastIdx = -1;

    function tick() {
      const t = vocalsEl.currentTime;
      let idx = 0;
      for (let i = 0; i < lines.length; i++) {
        if (lines[i].t <= t) idx = i;
        else break;
      }
      if (idx === lastIdx) return;
      lastIdx = idx;
      lineEls().forEach((el, i) => {
        el.classList.toggle('active', i === idx);
      });
      const active = lineEls()[idx];
      if (active && typeof active.scrollIntoView === 'function') {
        active.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }

    vocalsEl.addEventListener('timeupdate', tick);
    vocalsEl.addEventListener('seeked', tick);
    lrcCleanup = () => {
      vocalsEl.removeEventListener('timeupdate', tick);
      vocalsEl.removeEventListener('seeked', tick);
    };
    tick();
  }

  function normalizeLyricsBody(s) {
    if (typeof s !== 'string') return '';
    return s.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  }

  function applyLyricsPayload(data) {
    const lyricsPlain = K.$('lyricsBox');
    const lyricsSync = K.$('lyricsSynced');
    if (!lyricsPlain || !lyricsSync) return;

    if (!data || data.found === false) {
      lyricsPlain.hidden = false;
      lyricsSync.hidden = true;
      lyricsPlain.textContent = '—';
      stopLrcSync();
      return;
    }

    if (data.synced && data.lrc && String(data.lrc).trim()) {
      const parsed = K.parseLRC(data.lrc);
      if (parsed.length) {
        lyricsPlain.hidden = true;
        lyricsSync.hidden = false;
        renderLrcLines(lyricsSync, parsed);
        startLrcSync(parsed);
        return;
      }
    }

    const plain = normalizeLyricsBody(data.text || '');
    lyricsPlain.hidden = false;
    lyricsSync.hidden = true;
    lyricsPlain.textContent = plain.trim() ? plain : '—';
    stopLrcSync();
  }

  async function fetchLyricsForJob(jobId) {
    const url = new URL(K.endpoints.lyricsUrl);
    url.searchParams.set('job_id', jobId);
    const r = await apiFetch(url.toString(), { mode: 'cors' });
    return r.json();
  }

  function setFolderSummary(t) {
    if (folderScanSummary) folderScanSummary.textContent = t || '';
  }
  function setLoadStatus(t) {
    if (folderLoadStatus) folderLoadStatus.textContent = t || '';
  }

  function normalizeHumanTitle(raw) {
    let s = String(raw || '').trim();
    if (!s) return '';
    // Drop common download/bitrate tails from filenames.
    s = s.replace(/[_\s-]*(?:64|96|128|160|192|256|320)\s*kbps[_\s-]*/gi, ' ');
    s = s.replace(/\.(mp3|wav|m4a|flac|aac|ogg)$/i, '');
    s = s.replace(/[_]+/g, ' ');
    s = s.replace(/\s{2,}/g, ' ').trim();
    return s;
  }

  function buildSongDisplayLabel(item) {
    const title = normalizeHumanTitle((item && item.title) || '');
    const artist = (item && item.artist && String(item.artist).trim()) || '';
    const movie = (item && item.movie && String(item.movie).trim()) || '';
    const language = (item && item.language && String(item.language).trim()) || '';
    const category = (item && item.category && String(item.category).trim()) || '';
    const tags = Array.isArray(item && item.tags) ? item.tags.slice(0, 2).map((x) => String(x || '').trim()).filter(Boolean) : [];
    const primary = title || item.job_id;
    const meta = [];
    if (artist) meta.push(artist);
    if (movie) meta.push(movie);
    if (language) meta.push(language);
    if (category) meta.push(category);
    if (tags.length) meta.push(tags.join(', '));
    return meta.length ? primary + ' — ' + meta.join(' | ') : primary;
  }

  function resetSongUi() {
    PB.showTitle('—');
    setLoadStatus('Select a song from the list.');
    const lyricsPlain = K.$('lyricsBox');
    const lyricsSync = K.$('lyricsSynced');
    if (lyricsPlain) {
      lyricsPlain.hidden = false;
      lyricsPlain.textContent = '—';
    }
    if (lyricsSync) lyricsSync.hidden = true;
    stopLrcSync();
    K.setJobId(null);
  }

  function isAdvancedMode() {
    return !!(searchModeAdvanced && searchModeAdvanced.checked);
  }

  function updateSearchModeUi() {
    if (!advancedFiltersWrap) return;
    advancedFiltersWrap.hidden = !isAdvancedMode();
  }

  function buildListUrlWithFilters() {
    const url = new URL(K.endpoints.listUrl);
    const setIf = (k, v) => {
      const s = String(v || '').trim();
      if (s) url.searchParams.set(k, s);
      else url.searchParams.delete(k);
    };
    if (isAdvancedMode()) {
      setIf('title', filterTitle && filterTitle.value);
      setIf('language', filterLanguage && filterLanguage.value);
      setIf('category', filterCategory && filterCategory.value);
      setIf('tags', filterTags && filterTags.value);
      setIf('singer', filterSinger && filterSinger.value);
      setIf('actor', filterActor && filterActor.value);
      setIf('text', filterText && filterText.value);
      url.searchParams.delete('q');
    } else {
      setIf('q', searchQ && searchQ.value);
      ['title', 'language', 'category', 'tags', 'singer', 'actor', 'text'].forEach((k) => url.searchParams.delete(k));
    }
    return url.toString();
  }

  async function refreshList() {
    setFolderSummary('');
    setLoadStatus('Loading list…');
    listItems = [];
    if (songPick) songPick.innerHTML = '';
    if (songPickWrap) songPickWrap.hidden = true;
    try {
      const listUrl = buildListUrlWithFilters();
      const r = await apiFetch(listUrl, { mode: 'cors' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const j = await r.json();
      listItems = Array.isArray(j.items) ? j.items : [];
    } catch (e) {
      setLoadStatus('Could not load list — is local_folder_queue.py running? ' + explainListError(e));
      return;
    }

    if (!listItems.length) {
      setFolderSummary('API returned 0 completed jobs.');
      setLoadStatus(
        'No songs in the list. The queue only shows folders under output/ with a 16-hex job id and ' +
          'vocals.wav plus no_vocals.wav (or accompaniment.wav). ' +
          'Confirm KARAOKE_LOCAL_ROOT on the machine running local_folder_queue.py (see server log after GET /api/list). ' +
          'Upload and wait for a finished split via karaoke/index-local.html on this same host.'
      );
      resetSongUi();
      return;
    }

    setFolderSummary(listItems.length + ' song(s) on server.');
    if (!songPick || !songPickWrap) return;

    songPickWrap.hidden = false;
    const opt0 = document.createElement('option');
    opt0.value = '';
    opt0.textContent = '— Select a song —';
    songPick.appendChild(opt0);

    listItems.forEach((it) => {
      const opt = document.createElement('option');
      opt.value = it.job_id;
      const labelBase = buildSongDisplayLabel(it);
      const dup = listItems.filter(
        (x) => buildSongDisplayLabel(x) === labelBase
      ).length;
      opt.textContent = dup > 1 ? labelBase + ' [' + it.job_id + ']' : labelBase;
      songPick.appendChild(opt);
    });

    setLoadStatus('Pick a song, then route outputs and Play.');
    if (listItems.length === 1) {
      songPick.value = listItems[0].job_id;
      await selectJob(listItems[0].job_id);
    } else {
      resetSongUi();
    }
  }

  async function selectJob(jobId) {
    const item = listItems.find((x) => x.job_id === jobId);
    if (!item || !item.vocals_url || !item.band_url) {
      setLoadStatus('Missing stem URLs for this job.');
      return;
    }
    PB.setSources(resolveStemUrl(item.vocals_url), resolveStemUrl(item.band_url));
    K.setJobId(jobId);
    const title = (item.title && String(item.title).trim()) || jobId;
    PB.showTitle(title);
    setLoadStatus('Loaded “' + title + '”. Route outputs, then Play.');
    try {
      const data = await fetchLyricsForJob(jobId);
      applyLyricsPayload(data);
    } catch (e) {
      const msg = e && e.message ? e.message : String(e);
      applyLyricsPayload({ found: false });
      setLoadStatus('Lyrics fetch failed: ' + msg);
    }
  }

  K.$('syncNow')?.addEventListener('click', () => K.syncNow?.());

  refreshBtn?.addEventListener('click', () => {
    refreshList().catch((e) => setLoadStatus(String(e && e.message ? e.message : e)));
  });

  searchModeQuick?.addEventListener('change', updateSearchModeUi);
  searchModeAdvanced?.addEventListener('change', updateSearchModeUi);

  applyFiltersBtn?.addEventListener('click', () => {
    refreshList().catch((e) => setLoadStatus(String(e && e.message ? e.message : e)));
  });

  clearFiltersBtn?.addEventListener('click', () => {
    if (searchQ) searchQ.value = '';
    if (filterTitle) filterTitle.value = '';
    if (filterLanguage) filterLanguage.value = '';
    if (filterCategory) filterCategory.value = '';
    if (filterTags) filterTags.value = '';
    if (filterSinger) filterSinger.value = '';
    if (filterActor) filterActor.value = '';
    if (filterText) filterText.value = '';
    if (searchModeQuick) searchModeQuick.checked = true;
    if (searchModeAdvanced) searchModeAdvanced.checked = false;
    updateSearchModeUi();
    refreshList().catch((e) => setLoadStatus(String(e && e.message ? e.message : e)));
  });

  searchQ?.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !isAdvancedMode()) {
      ev.preventDefault();
      refreshList().catch((e) => setLoadStatus(String(e && e.message ? e.message : e)));
    }
  });

  songPick?.addEventListener('change', () => {
    const v = songPick.value;
    if (!v) {
      PB.setSources('', '');
      resetSongUi();
      return;
    }
    selectJob(v).catch((e) => setLoadStatus(String(e && e.message ? e.message : e)));
  });

  updateSearchModeUi();
  refreshList().catch((e) => setLoadStatus(String(e && e.message ? e.message : e)));
})(window);
