/* ===== karaoke-player-folder.js =====
   Folder pick → list songs (stem pairs) → pick one → stems + per-song status/lyrics.
*/
(function (w) {
  const K = w.KARAOKE;
  w.KARAOKE_MODE = 'player-folder';

  const projectFolderInput = K.$('projectFolder');
  const pickProjectBtn = K.$('pickProjectFolder');
  const folderScanSummary = K.$('folderScanSummary');
  const folderLoadStatus = K.$('folderLoadStatus');
  const songPick = K.$('folderSongPick');
  const songPickWrap = K.$('songPickWrap');

  const VOC_LEAF = /^vocals\.(wav|mp3|flac|m4a|aac)$/i;
  const BAND_LEAF = /^(no_vocals|accompaniment)\.(wav|mp3|flac|m4a|aac)$/i;

  /** @type {File[]|null} */
  let folderFiles = null;
  /** @type {{ dir: string, vocals: File, band: File }[]} */
  let folderPairs = [];

  function parentDirKey(f){
    const rel = (f.webkitRelativePath || f.name || '').replace(/\\/g, '/');
    const parts = rel.split('/').filter(Boolean);
    if (parts.length < 2) return '';
    return parts.slice(0, -1).join('/');
  }

  function demucsDirRank(dir){
    const d = (dir || '').toLowerCase();
    if (d.includes('htdemucs')) return 0;
    if (d.includes('mdx_extra') || d.includes('mdx') || d.includes('demucs')) return 1;
    if (d.includes('spleeter')) return 2;
    return 3;
  }

  function outputFolderBias(dir){
    const d = (dir || '').toLowerCase().replace(/\\/g, '/');
    if (d.includes('/output/') || d.endsWith('/output')) return 0;
    if (d.includes('/stems/') || d.endsWith('/stems')) return 1;
    return 2;
  }

  function normPath(f){
    return (f.webkitRelativePath || f.name || '').replace(/\\/g, '/');
  }

  function titleFromLocalFile(f){
    if (!f) return 'Local';
    const rel = normPath(f);
    const parts = rel.split('/').filter(Boolean);
    if (parts.length >= 2) return parts[parts.length - 2];
    const leaf = parts[0] || 'Local';
    return leaf.replace(/\.[^.]+$/i, '') || 'Local';
  }

  /** Human-readable song name from the stem directory path. */
  function titleFromPair(pair){
    const { dir, vocals } = pair;
    if (dir) {
      const parts = String(dir).split('/').filter(Boolean);
      const last = parts[parts.length - 1] || '';
      if (last && !/^(output|stems|htdemucs|vocals|no_vocals)$/i.test(last)) return last;
      if (parts.length >= 2) return parts[parts.length - 2];
      return last || dir;
    }
    return titleFromLocalFile(vocals);
  }

  /**
   * Collect every directory that has both vocals + band stems.
   */
  function collectAllStemPairs(files){
    const arr = [...files];
    const byDir = new Map();
    for (const f of arr) {
      const leaf = (f.name || '').trim();
      if (!VOC_LEAF.test(leaf) && !BAND_LEAF.test(leaf)) continue;
      const dKey = parentDirKey(f);
      if (!byDir.has(dKey)) byDir.set(dKey, { vocals: null, band: null });
      const slot = byDir.get(dKey);
      if (VOC_LEAF.test(leaf) && !slot.vocals) slot.vocals = f;
      if (BAND_LEAF.test(leaf) && !slot.band) slot.band = f;
    }

    const pairs = [];
    for (const [dir, o] of byDir) {
      if (o.vocals && o.band) pairs.push({ dir, vocals: o.vocals, band: o.band });
    }
    if (pairs.length) {
      pairs.sort((a, b) => {
        const ra = demucsDirRank(a.dir);
        const rb = demucsDirRank(b.dir);
        if (ra !== rb) return ra - rb;
        const oa = outputFolderBias(a.dir);
        const ob = outputFolderBias(b.dir);
        if (oa !== ob) return oa - ob;
        return titleFromPair(a).localeCompare(titleFromPair(b), undefined, { sensitivity: 'base' });
      });
      return { pairs, mismatchedDirs: false };
    }

    let vocals = null;
    let band = null;
    for (const f of arr) {
      const leaf = (f.name || '').trim();
      if (VOC_LEAF.test(leaf) && !vocals) vocals = f;
      if (BAND_LEAF.test(leaf) && !band) band = f;
    }
    if (vocals && band) {
      const dv = parentDirKey(vocals);
      const db = parentDirKey(band);
      if (dv !== db) {
        return { pairs: [], mismatchedDirs: true };
      }
      return { pairs: [{ dir: dv || '', vocals, band }], mismatchedDirs: false };
    }
    return { pairs: [], mismatchedDirs: false };
  }

  function findStatusFile(files, stemDir){
    const rows = [...files].map(f => ({ f, leaf: (f.name || '').trim(), rel: normPath(f) }));
    const sd = (stemDir || '').replace(/\\/g, '/');
    function inScope(rel){
      if (!sd) return true;
      let cur = sd;
      while (cur) {
        if (rel === cur || rel.startsWith(cur + '/')) return true;
        if (!cur.includes('/')) break;
        cur = cur.slice(0, cur.lastIndexOf('/'));
      }
      return false;
    }
    const order = [
      (leaf) => leaf === 'status.json',
      (leaf) => leaf === 'job.json',
      (leaf) => leaf === 'state.json',
      (leaf) => leaf === 'status.txt',
      (leaf) => /\.json$/i.test(leaf) && /status|job|state/i.test(leaf),
    ];
    for (const pred of order) {
      const hit = rows.filter(r => pred(r.leaf) && inScope(r.rel));
      if (!hit.length) continue;
      hit.sort((a, b) => a.rel.split('/').length - b.rel.split('/').length);
      return hit[0].f;
    }
    if (sd) return findStatusFile(files, null);
    return null;
  }

  function findLyricsFile(files, stemDir){
    const rows = [...files].map(f => ({
      f,
      leaf: (f.name || '').toLowerCase(),
      rel: normPath(f),
    }));
    const sd = (stemDir || '').replace(/\\/g, '/');
    function inStemTree(rel){
      if (!sd) return true;
      return rel === sd || rel.startsWith(sd + '/');
    }
    function score(r){
      if (!inStemTree(r.rel)) return -1;
      let s = 0;
      if (r.leaf === 'lyrics.lrc') s = 100;
      else if (r.leaf === 'lyrics.txt') s = 90;
      else if (r.leaf.endsWith('.lrc')) s = 50;
      else if (r.leaf.endsWith('.txt') && /lyric/.test(r.leaf)) s = 40;
      else return -1;
      const depth = r.rel.split('/').length;
      return s * 1000 - depth;
    }
    const ranked = rows.map(r => ({ ...r, sc: score(r) })).filter(x => x.sc >= 0);
    ranked.sort((a, b) => b.sc - a.sc);
    if (ranked.length) return ranked[0].f;

    if (sd) return null;

    const fallback = rows.filter(r =>
      r.leaf === 'lyrics.lrc' || r.leaf === 'lyrics.txt' || r.leaf.endsWith('.lrc')
    );
    fallback.sort((a, b) => a.rel.split('/').length - b.rel.split('/').length);
    return fallback[0]?.f || null;
  }

  const PB = K.initPlaybackControls();
  K.syncNow = PB.hardResync;

  let lrcCleanup = null;
  function stopLrcSync(){
    if (typeof lrcCleanup === 'function') {
      try { lrcCleanup(); } catch (_) {}
    }
    lrcCleanup = null;
  }

  function renderLrcLines(container, lines){
    container.innerHTML = '';
    lines.forEach((line, i) => {
      const div = document.createElement('div');
      div.className = 'lyrics-line';
      div.dataset.idx = String(i);
      div.textContent = line.text || ' ';
      container.appendChild(div);
    });
  }

  function startLrcSync(lines){
    stopLrcSync();
    const vocalsEl = K.$('vocalsEl');
    const box = K.$('lyricsSynced');
    if (!vocalsEl || !box || !lines.length) return;

    const lineEls = () => [...box.querySelectorAll('.lyrics-line')];
    let lastIdx = -1;

    function tick(){
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

  async function applySidecars(files, stemDir){
    const statusEl = K.$('folderStatusText');
    const lyricsPlain = K.$('lyricsBox');
    const lyricsSync = K.$('lyricsSynced');

    const statusFile = findStatusFile(files, stemDir);
    if (statusEl) {
      if (statusFile) {
        try {
          const raw = await statusFile.text();
          try {
            statusEl.textContent = JSON.stringify(JSON.parse(raw), null, 2);
          } catch (_) {
            statusEl.textContent = raw;
          }
        } catch (e) {
          statusEl.textContent = 'Could not read status file: ' + (e && e.message ? e.message : e);
        }
      } else {
        statusEl.textContent = '— (no status file next to this song)';
      }
    }

    const lyricsFile = findLyricsFile(files, stemDir);
    if (!lyricsPlain || !lyricsSync) return;

    if (!lyricsFile) {
      lyricsPlain.hidden = false;
      lyricsSync.hidden = true;
      lyricsPlain.textContent = '—';
      stopLrcSync();
      return;
    }

    try {
      const txt = await lyricsFile.text();
      const looksLrc = /\.lrc$/i.test(lyricsFile.name) || /\[\d{1,2}:\d{2}/.test(txt);
      const parsed = looksLrc ? K.parseLRC(txt) : [];
      if (looksLrc && parsed.length) {
        lyricsPlain.hidden = true;
        lyricsSync.hidden = false;
        renderLrcLines(lyricsSync, parsed);
        startLrcSync(parsed);
      } else {
        lyricsPlain.hidden = false;
        lyricsSync.hidden = true;
        lyricsPlain.textContent = txt;
        stopLrcSync();
      }
    } catch (e) {
      lyricsPlain.hidden = false;
      lyricsSync.hidden = true;
      lyricsPlain.textContent = 'Could not read lyrics: ' + (e && e.message ? e.message : e);
      stopLrcSync();
    }
  }

  function setFolderSummary(t){ if (folderScanSummary) folderScanSummary.textContent = t || ''; }
  function setLoadStatus(t){ if (folderLoadStatus) folderLoadStatus.textContent = t || ''; }

  function applyStems(vocalsFile, bandFile, pairedDir, allFiles){
    if (!vocalsFile || !bandFile) return;
    if (vocalsFile === bandFile) {
      setLoadStatus('Vocals and band must be two different files.');
      return;
    }
    const vUrl = URL.createObjectURL(vocalsFile);
    const bUrl = URL.createObjectURL(bandFile);
    PB.setSources(vUrl, bUrl);
    K.setJobId(null);

    const title = titleFromPair({ dir: pairedDir || '', vocals: vocalsFile, band: bandFile });
    PB.showTitle(title);
    setLoadStatus(`Loaded “${title}”. Route outputs, then Play.`);

    if (allFiles && allFiles.length) {
      applySidecars(allFiles, pairedDir || null);
    }
  }

  function loadSongAtIndex(idx){
    if (!folderFiles || !folderPairs.length) return;
    const pair = folderPairs[idx];
    if (!pair) return;
    applyStems(pair.vocals, pair.band, pair.dir, folderFiles);
  }

  function populateSongList(pairs){
    folderPairs = pairs;
    if (!songPick || !songPickWrap) return;

    songPick.innerHTML = '';
    if (pairs.length === 0) {
      songPickWrap.hidden = true;
      return;
    }

    songPickWrap.hidden = false;

    if (pairs.length > 1) {
      const opt0 = document.createElement('option');
      opt0.value = '';
      opt0.textContent = '— Select a song —';
      songPick.appendChild(opt0);
    }

    pairs.forEach((p, i) => {
      const opt = document.createElement('option');
      opt.value = String(i);
      let label = titleFromPair(p);
      const dup = pairs.filter((q) => titleFromPair(q) === label).length;
      if (dup > 1) label = `${label} (${p.dir || 'root'})`;
      opt.textContent = label;
      songPick.appendChild(opt);
    });

    if (pairs.length === 1) {
      songPick.value = '0';
      loadSongAtIndex(0);
    } else {
      songPick.value = '';
      PB.showTitle('—');
      setLoadStatus('Select a song from the list.');
      const st = K.$('folderStatusText');
      if (st) st.textContent = '—';
      const lyricsPlain = K.$('lyricsBox');
      const lyricsSync = K.$('lyricsSynced');
      if (lyricsPlain) {
        lyricsPlain.hidden = false;
        lyricsPlain.textContent = '—';
      }
      if (lyricsSync) lyricsSync.hidden = true;
      stopLrcSync();
    }
  }

  K.$('syncNow')?.addEventListener('click', () => K.syncNow?.());

  pickProjectBtn?.addEventListener('click', () => {
    setFolderSummary('');
    setLoadStatus('');
    projectFolderInput?.click();
  });

  projectFolderInput?.addEventListener('change', () => {
    const files = projectFolderInput.files;
    if (!files || !files.length) return;

    folderFiles = [...files];
    setFolderSummary(`Scanned ${folderFiles.length} file(s).`);

    const { pairs, mismatchedDirs } = collectAllStemPairs(folderFiles);

    if (mismatchedDirs) {
      folderPairs = [];
      if (songPickWrap) songPickWrap.hidden = true;
      setLoadStatus('Vocals and band are in different folders — select a parent folder that contains each song’s stems together.');
      applySidecars(folderFiles, null);
    } else if (!pairs.length) {
      folderPairs = [];
      if (songPickWrap) songPickWrap.hidden = true;
      setLoadStatus('No songs found. Each song needs vocals.* and no_vocals.* or accompaniment.* in the same directory.');
      applySidecars(folderFiles, null);
    } else {
      setLoadStatus(`Found ${pairs.length} song(s).`);
      populateSongList(pairs);
    }

    projectFolderInput.value = '';
  });

  songPick?.addEventListener('change', () => {
    const v = songPick.value;
    if (v === '') {
      setLoadStatus('Select a song to load stems and lyrics.');
      PB.showTitle('—');
      const st = K.$('folderStatusText');
      if (st) st.textContent = '—';
      const lyricsPlain = K.$('lyricsBox');
      const lyricsSync = K.$('lyricsSynced');
      if (lyricsPlain) {
        lyricsPlain.hidden = false;
        lyricsPlain.textContent = '—';
      }
      if (lyricsSync) lyricsSync.hidden = true;
      stopLrcSync();
      return;
    }
    loadSongAtIndex(parseInt(v, 10));
  });
})(window);
