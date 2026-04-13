/* ===== karaoke-player-local.js =====
   Local stems only: folder scan or two file picks → blob URLs → karaoke-core.js playback (no Azure).
*/
(function (w) {
  const K = w.KARAOKE;
  w.KARAOKE_MODE = 'player-local';

  const localFolderInput = K.$('localSplitFolder');
  const pickLocalFolderBtn = K.$('pickLocalFolder');
  const localVocInput = K.$('localVocalsFile');
  const localBandInput = K.$('localBandFile');
  const loadLocalPairBtn = K.$('loadLocalPair');
  const localFilesStatus = K.$('localFilesStatus');

  function setLocalFilesStatus(t){ if (localFilesStatus) localFilesStatus.textContent = t || ''; }

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
    if (!f) return 'Local files';
    const rel = (f.webkitRelativePath || f.name || '').replace(/\\/g, '/');
    const parts = rel.split('/').filter(Boolean);
    if (parts.length >= 2) return parts[parts.length - 2];
    const leaf = parts[0] || 'Local';
    return leaf.replace(/\.[^.]+$/i, '') || 'Local files';
  }

  const PB = K.initPlaybackControls();
  K.syncNow = PB.hardResync;

  function applyLocalFiles(vocalsFile, bandFile, meta){
    if (!vocalsFile || !bandFile) return;
    if (vocalsFile === bandFile) {
      setLocalFilesStatus('Vocals and band must be two different files.');
      return;
    }
    const vUrl = URL.createObjectURL(vocalsFile);
    const bUrl = URL.createObjectURL(bandFile);
    PB.setSources(vUrl, bUrl);
    PB.showTitle(titleFromLocalFile(vocalsFile));
    K.setJobId(null);

    let msg = 'Loaded. ';
    if (meta && meta.pairedDir) msg += `Folder: “${meta.pairedDir}”. `;
    msg += 'Route vocals vs band to different devices—both on “System default” sounds like one mixed track. Then Play.';
    if (meta && meta.pairCount > 1) {
      msg += ` (${meta.pairCount} stem pairs found; using best match—pick a tighter folder if wrong.)`;
    }
    setLocalFilesStatus(msg);
  }

  K.$('syncNow')?.addEventListener('click', () => K.syncNow?.());

  pickLocalFolderBtn?.addEventListener('click', () => {
    setLocalFilesStatus('');
    localFolderInput?.click();
  });

  localFolderInput?.addEventListener('change', () => {
    const files = localFolderInput.files;
    if (!files || !files.length) return;
    const found = findStemsInFileList(files);
    const { vocals, band, pairedDir, pairCount, mismatchedDirs } = found;
    if (mismatchedDirs) {
      setLocalFilesStatus(
        'Vocals and band are in different folders—open the folder that contains both (e.g. …/htdemucs/YourSong/), or use two file picks.'
      );
    } else if (!vocals || !band) {
      setLocalFilesStatus(
        'No pair found. Need vocals.wav (or .mp3…) and no_vocals.wav or accompaniment.wav in the same directory under your selection.'
      );
    } else {
      applyLocalFiles(vocals, band, { pairedDir, pairCount: pairCount || 1 });
    }
    localFolderInput.value = '';
  });

  loadLocalPairBtn?.addEventListener('click', () => {
    setLocalFilesStatus('');
    const vf = localVocInput?.files?.[0];
    const bf = localBandInput?.files?.[0];
    if (!vf || !bf) {
      setLocalFilesStatus('Choose both files, then click “Load chosen files”.');
      return;
    }
    applyLocalFiles(vf, bf, { pairedDir: null, pairCount: 1 });
  });
})(window);
