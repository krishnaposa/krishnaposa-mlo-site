/* ===== karaoke-player-standalone.js =====
   Offline player: karaoke-core.js only. Folder layout: optional input/, stems in output/ or stems/ or Demucs tree.
*/
(function (w) {
  const K = w.KARAOKE;
  w.KARAOKE_MODE = 'standalone';

  const inputFolderInput = K.$('standaloneInputFolder');
  const pickInputBtn = K.$('pickStandaloneInput');
  const inputStatus = K.$('standaloneInputStatus');
  const stemsFolderInput = K.$('standaloneStemsFolder');
  const pickStemsBtn = K.$('pickStandaloneStems');
  const vocFile = K.$('standaloneVocals');
  const bandFile = K.$('standaloneBand');
  const loadPairBtn = K.$('standaloneLoadPair');
  const statusEl = K.$('standaloneStatus');

  function setStatus(t){ if (statusEl) statusEl.textContent = t || ''; }

  const VOC_LEAF = /^vocals\.(wav|mp3|flac|m4a|aac)$/i;
  const BAND_LEAF = /^(no_vocals|accompaniment)\.(wav|mp3|flac|m4a|aac)$/i;
  const INPUT_AUDIO = /\.(mp3|wav|m4a|flac|aac|ogg|opus)$/i;

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

  /** Prefer output/ or stems/ when multiple pairs exist (matches documented folder layout). */
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

  function titleFromLocalFile(f){
    if (!f) return 'Local';
    const rel = (f.webkitRelativePath || f.name || '').replace(/\\/g, '/');
    const parts = rel.split('/').filter(Boolean);
    if (parts.length >= 2) return parts[parts.length - 2];
    const leaf = parts[0] || 'Local';
    return leaf.replace(/\.[^.]+$/i, '') || 'Local';
  }

  const PB = K.initPlaybackControls();
  K.syncNow = PB.hardResync;

  function applyStems(vocalsFile, bandFile, meta){
    if (!vocalsFile || !bandFile) return;
    if (vocalsFile === bandFile) {
      setStatus('Vocals and band must be two different files.');
      return;
    }
    PB.setSources(URL.createObjectURL(vocalsFile), URL.createObjectURL(bandFile));
    PB.showTitle(titleFromLocalFile(vocalsFile));
    let msg = 'Loaded. ';
    if (meta && meta.pairedDir) msg += `Stems dir: “${meta.pairedDir}”. `;
    msg += 'Route outputs, then Play.';
    if (meta && meta.pairCount > 1) msg += ` (${meta.pairCount} pairs; using best match.)`;
    setStatus(msg);
  }

  K.$('syncNow')?.addEventListener('click', () => K.syncNow?.());

  pickInputBtn?.addEventListener('click', () => {
    if (inputStatus) inputStatus.textContent = '';
    inputFolderInput?.click();
  });

  inputFolderInput?.addEventListener('change', () => {
    const files = inputFolderInput.files;
    if (!files || !files.length) return;
    const names = [];
    for (const f of files) {
      if (INPUT_AUDIO.test(f.name)) names.push(f.webkitRelativePath || f.name);
    }
    if (inputStatus) {
      inputStatus.textContent = names.length
        ? `Input folder: ${names.length} audio-like file(s). E.g. ${names.slice(0, 3).join('; ')}${names.length > 3 ? '…' : ''}`
        : 'No obvious audio files in that folder (names checked by extension).';
    }
    inputFolderInput.value = '';
  });

  pickStemsBtn?.addEventListener('click', () => {
    setStatus('');
    stemsFolderInput?.click();
  });

  stemsFolderInput?.addEventListener('change', () => {
    const files = stemsFolderInput.files;
    if (!files || !files.length) return;
    const found = findStemsInFileList(files);
    const { vocals, band, pairedDir, pairCount, mismatchedDirs } = found;
    if (mismatchedDirs) {
      setStatus('Vocals and band are in different folders — select the folder that contains both stems together.');
    } else if (!vocals || !band) {
      setStatus('No stem pair found. Expected vocals.* + no_vocals.* or accompaniment.* in the same directory (see layout: output/ or stems/).');
    } else {
      applyStems(vocals, band, { pairedDir, pairCount: pairCount || 1 });
    }
    stemsFolderInput.value = '';
  });

  loadPairBtn?.addEventListener('click', () => {
    setStatus('');
    const vf = vocFile?.files?.[0];
    const bf = bandFile?.files?.[0];
    if (!vf || !bf) {
      setStatus('Choose both files, then click “Load chosen files”.');
      return;
    }
    applyStems(vf, bf, { pairedDir: null, pairCount: 1 });
  });
})(window);
