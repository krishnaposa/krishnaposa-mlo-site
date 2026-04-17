/* ===== karaoke-player-folder.js =====
   One folder pick: stems + status (json/txt) + lyrics (txt/lrc), playback via karaoke-core.js.
*/
(function (w) {
  const K = w.KARAOKE;
  w.KARAOKE_MODE = 'player-folder';

  const projectFolderInput = K.$('projectFolder');
  const pickProjectBtn = K.$('pickProjectFolder');
  const folderScanSummary = K.$('folderScanSummary');
  const folderLoadStatus = K.$('folderLoadStatus');
  const vocOverride = K.$('folderVocalsFile');
  const bandOverride = K.$('folderBandFile');
  const loadPairBtn = K.$('folderLoadPair');

  const VOC_LEAF = /^vocals\.(wav|mp3|flac|m4a|aac)$/i;
  const BAND_LEAF = /^(no_vocals|accompaniment)\.(wav|mp3|flac|m4a|aac)$/i;

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

  function findStemsInFileList(fileList){
    const files = [...fileList];
    const byDir = new Map();
    for (const f of files) {
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
        const da = a.dir.split('/').length;
        const db = b.dir.split('/').length;
        if (da !== db) return db - da;
        return a.dir.localeCompare(b.dir);
      });
      return {
        vocals: pairs[0].vocals,
        band: pairs[0].band,
        pairedDir: pairs[0].dir,
        pairCount: pairs.length,
        mismatchedDirs: false,
      };
    }

    let vocals = null;
    let band = null;
    for (const f of files) {
      const leaf = (f.name || '').trim();
      if (VOC_LEAF.test(leaf) && !vocals) vocals = f;
      if (BAND_LEAF.test(leaf) && !band) band = f;
    }
    if (vocals && band) {
      const dv = parentDirKey(vocals);
      const db = parentDirKey(band);
      if (dv !== db) {
        return {
          vocals: null,
          band: null,
          pairedDir: null,
          pairCount: 0,
          mismatchedDirs: true,
        };
      }
      return {
        vocals,
        band,
        pairedDir: dv || null,
        pairCount: 1,
        mismatchedDirs: false,
      };
    }
    return { vocals: null, band: null, pairedDir: null, pairCount: 0, mismatchedDirs: false };
  }

  function normPath(f){
    return (f.webkitRelativePath || f.name || '').replace(/\\/g, '/');
  }

  function findStatusFile(files){
    const rows = [...files].map(f => ({ f, leaf: (f.name || '').trim(), rel: normPath(f) }));
    const order = [
      (leaf) => leaf === 'status.json',
      (leaf) => leaf === 'job.json',
      (leaf) => leaf === 'state.json',
      (leaf) => leaf === 'status.txt',
      (leaf) => /\.json$/i.test(leaf) && /status|job|state/i.test(leaf),
    ];
    for (const pred of order) {
      const hit = rows.filter(r => pred(r.leaf));
      if (!hit.length) continue;
      hit.sort((a, b) => a.rel.split('/').length - b.rel.split('/').length);
      return hit[0].f;
    }
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

    const fallback = rows.filter(r =>
      r.leaf === 'lyrics.lrc' || r.leaf === 'lyrics.txt' || r.leaf.endsWith('.lrc')
    );
    fallback.sort((a, b) => a.rel.split('/').length - b.rel.split('/').length);
    return fallback[0]?.f || null;
  }

  function titleFromLocalFile(f){
    if (!f) return 'Local';
    const rel = normPath(f);
    const parts = rel.split('/').filter(Boolean);
    if (parts.length >= 2) return parts[parts.length - 2];
    const leaf = parts[0] || 'Local';
    return leaf.replace(/\.[^.]+$/i, '') || 'Local';
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

    const statusFile = findStatusFile(files);
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
        statusEl.textContent = '— (no status.json, job.json, state.json, or status.txt found)';
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

  function applyStems(vocalsFile, bandFile, meta, allFiles){
    if (!vocalsFile || !bandFile) return;
    if (vocalsFile === bandFile) {
      setLoadStatus('Vocals and band must be two different files.');
      return;
    }
    const vUrl = URL.createObjectURL(vocalsFile);
    const bUrl = URL.createObjectURL(bandFile);
    PB.setSources(vUrl, bUrl);
    PB.showTitle(titleFromLocalFile(vocalsFile));
    K.setJobId(null);

    let msg = 'Stems loaded. ';
    if (meta && meta.pairedDir) msg += `Directory: “${meta.pairedDir}”. `;
    msg += 'Route outputs, then Play.';
    if (meta && meta.pairCount > 1) {
      msg += ` (${meta.pairCount} stem pairs found; using best match.)`;
    }
    setLoadStatus(msg);

    if (allFiles && allFiles.length) {
      applySidecars(allFiles, meta && meta.pairedDir ? meta.pairedDir : null);
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
    setFolderSummary(`Scanned ${files.length} file(s).`);

    const found = findStemsInFileList(files);
    const { vocals, band, pairedDir, pairCount, mismatchedDirs } = found;
    if (mismatchedDirs) {
      setLoadStatus('Vocals and band are in different folders — select the folder that contains both stems (e.g. …/output/).');
      applySidecars(files, null);
    } else if (!vocals || !band) {
      setLoadStatus('No stem pair found. Need vocals.* and no_vocals.* or accompaniment.* in the same directory.');
      applySidecars(files, null);
    } else {
      applyStems(vocals, band, { pairedDir, pairCount: pairCount || 1 }, files);
    }
    projectFolderInput.value = '';
  });

  loadPairBtn?.addEventListener('click', () => {
    setLoadStatus('');
    const vf = vocOverride?.files?.[0];
    const bf = bandOverride?.files?.[0];
    if (!vf || !bf) {
      setLoadStatus('Choose both vocal and band files, then click “Load chosen files instead”.');
      return;
    }
    applyStems(vf, bf, { pairedDir: null, pairCount: 1 }, null);
    const lyricsPlain = K.$('lyricsBox');
    const lyricsSync = K.$('lyricsSynced');
    if (lyricsPlain) {
      lyricsPlain.hidden = false;
      lyricsPlain.textContent = '— (load a project folder above to pull lyrics/status from disk.)';
    }
    if (lyricsSync) lyricsSync.hidden = true;
    stopLrcSync();
    const st = K.$('folderStatusText');
    if (st) st.textContent = '—';
  });
})(window);
