/* ===== karaoke-player-folder.js =====
   Folder pick → list songs (stem pairs) → pick one → stems + lyrics (original_name labels).
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

  const VOC_LEAF = /^vocals\.(wav|mp3|flac|m4a|aac|ogg)$/i;
  const BAND_LEAF = /^(no_vocals|accompaniment|instrumental)\.(wav|mp3|flac|m4a|aac|ogg)$/i;

  /** @type {File[]|null} */
  let folderFiles = null;
  /** @type {{ dir: string, vocals: File, band: File, originalName?: string }[]} */
  let folderPairs = [];

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
    return String(f.webkitRelativePath || f.name || '')
      .replace(/\\/g, '/')
      .replace(/\/+/g, '/');
  }

  /** Leaf name from relative path (more reliable than `File.name` alone). */
  function stemLeafFromFile(f){
    const rel = normPath(f);
    const parts = rel.split('/').filter(Boolean);
    if (parts.length >= 2) return parts[parts.length - 1];
    return (f.name || '').trim();
  }

  function stemDirFromFile(f){
    const rel = normPath(f);
    const parts = rel.split('/').filter(Boolean);
    if (parts.length < 2) return '';
    return parts.slice(0, -1).join('/');
  }

  /** Last path segment of stem folder (e.g. Demucs job id). */
  function jobIdFromStemDir(stemDir){
    if (!stemDir) return '';
    const parts = String(stemDir).split('/').filter(Boolean);
    return parts.length ? parts[parts.length - 1] : '';
  }

  /**
   * Job id may match the stem folder name, a parent segment, or a field inside JSON.
   * Try several path segments (e.g. skip generic folder names like htdemucs).
   */
  function jobIdCandidatesFromStemDir(stemDir){
    const parts = String(stemDir || '').split('/').filter(Boolean);
    const skipSeg = (leaf) =>
      /^(htdemucs|mdx|mdx_extra|spleeter|vocals|output|stems|no_vocals)$/i.test(leaf);
    const out = [];
    if (parts.length) {
      const last = parts[parts.length - 1];
      if (!skipSeg(last)) out.push(last);
    }
    if (parts.length >= 2) {
      const prev = parts[parts.length - 2];
      if (!skipSeg(prev)) out.push(prev);
    }
    if (parts.length >= 3) {
      const p2 = parts[parts.length - 3];
      if (!skipSeg(p2)) out.push(p2);
    }
    const uniq = [...new Set(out.filter(Boolean))];
    if (uniq.length) return uniq;
    return parts.length ? [parts[parts.length - 1]] : [];
  }

  function isVocalStemLeaf(leaf){
    const s = (leaf || '').trim();
    return VOC_LEAF.test(s);
  }

  function isBandStemLeaf(leaf){
    const s = (leaf || '').trim();
    return BAND_LEAF.test(s);
  }

  function titleFromLocalFile(f){
    if (!f) return 'Local';
    const rel = normPath(f);
    const parts = rel.split('/').filter(Boolean);
    if (parts.length >= 2) return parts[parts.length - 2];
    const leaf = parts[0] || 'Local';
    return leaf.replace(/\.[^.]+$/i, '') || 'Local';
  }

  /** Human-readable song name from the stem directory path (fallback if no original_name). */
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

  function displayLabel(pair){
    const on = pair.originalName && String(pair.originalName).trim();
    return on || titleFromPair(pair);
  }

  function isJsonInLyricsOrStatusFolder(rel){
    const parts = String(rel).replace(/\\/g, '/').split('/').filter(Boolean);
    if (
      parts.some((p) => {
        const pl = p.toLowerCase();
        return pl === 'lyrics' || pl === 'lyric' || pl === 'status';
      })
    ) {
      return true;
    }
    // Some browsers only expose the file name (no parent folders) for directory picks.
    if (parts.length === 1 && /\.json$/i.test(parts[0])) return true;
    return false;
  }

  /** JSON sidecars we may read for titles: lyrics/status/metadata/input, or basename-only. */
  function isJsonMetadataCandidate(rel){
    const n = String(rel).replace(/\\/g, '/');
    if (/(^|\/)(lyrics|lyric|status|state|metadata|meta|input|config)(\/|$)/i.test(n)) return true;
    const parts = n.split('/').filter(Boolean);
    if (parts.length === 1 && /\.json$/i.test(parts[0])) return true;
    return false;
  }

  function isStatusJsonPath(rel){
    const n = String(rel).replace(/\\/g, '/');
    return /(^|\/)(status|state)(\/|$)/i.test(n);
  }

  /** Prefer original_name (status/*.json uses this for dropdown titles). */
  function extractDisplayNameForIndex(data, statusFile){
    if (!data || typeof data !== 'object') return '';
    if (statusFile) {
      if (typeof data.original_name === 'string' && data.original_name.trim()) return data.original_name.trim();
      if (typeof data.originalName === 'string' && data.originalName.trim()) return data.originalName.trim();
      const nested = extractOriginalNameDeep(data, 0);
      if (nested) return nested;
      return '';
    }
    return extractOriginalNameFromJson(data, 0) || extractOriginalNameDeep(data, 0);
  }

  /** Deep search: prefer nested original_* before shallow title. */
  function extractOriginalNameDeep(obj, depth){
    const d = depth == null ? 0 : depth;
    if (d > 14 || obj == null) return '';
    if (typeof obj === 'string') return '';
    if (typeof obj !== 'object') return '';
    if (Array.isArray(obj)) {
      for (const el of obj) {
        const s = extractOriginalNameDeep(el, d + 1);
        if (s) return s;
      }
      return '';
    }
    for (const key of Object.keys(obj)) {
      const kl = key.toLowerCase();
      if (
        kl === 'original_name' ||
        kl === 'originalname' ||
        kl === 'original_title' ||
        kl === 'originaltitle'
      ) {
        const v = obj[key];
        if (typeof v === 'string' && v.trim()) return v.trim();
      }
    }
    for (const key of Object.keys(obj)) {
      const v = obj[key];
      if (typeof v === 'object' && v) {
        const s = extractOriginalNameDeep(v, d + 1);
        if (s) return s;
      }
    }
    for (const key of Object.keys(obj)) {
      const kl = key.toLowerCase();
      if (
        kl === 'title' ||
        kl === 'song_title' ||
        kl === 'songtitle' ||
        kl === 'track_title' ||
        kl === 'tracktitle' ||
        kl === 'name'
      ) {
        const v = obj[key];
        if (typeof v === 'string' && v.trim()) return v.trim();
      }
    }
    return '';
  }

  function extractOriginalNameFromJson(data, depth){
    const d = depth == null ? 0 : depth;
    if (d > 10 || data == null) return '';
    if (typeof data === 'string') return '';
    if (typeof data !== 'object') return '';
    const keys = [
      'original_name', 'originalName', 'original_title', 'originalTitle',
      'title', 'song_title', 'songTitle', 'track_title', 'trackTitle', 'name',
    ];
    for (const k of keys) {
      const v = data[k];
      if (typeof v === 'string' && v.trim()) return v.trim();
    }
    if (data.song && typeof data.song === 'object') {
      const s = extractOriginalNameFromJson(data.song, d + 1);
      if (s) return s;
    }
    if (data.metadata && typeof data.metadata === 'object') {
      const s = extractOriginalNameFromJson(data.metadata, d + 1);
      if (s) return s;
    }
    if (data.track && typeof data.track === 'object') {
      const s = extractOriginalNameFromJson(data.track, d + 1);
      if (s) return s;
    }
    return '';
  }

  const ID_KEYS = new Set([
    'job_id', 'jobid', 'id', 'hash', 'job_hash', 'jobhash', 'execution_id', 'executionid',
    'batch_id', 'batchid', 'track_id', 'trackid', 'song_id', 'songid', 'request_id', 'requestid',
    'split_id', 'splitid', 'demucs_id', 'uuid', 'basename', 'folder', 'run_id', 'runid',
  ]);

  function collectIdsFromJsonForIndex(obj, depth){
    const ids = [];
    if (depth > 12 || obj == null || typeof obj !== 'object') return ids;
    if (Array.isArray(obj)) {
      obj.forEach((e) => ids.push(...collectIdsFromJsonForIndex(e, depth + 1)));
      return ids;
    }
    for (const [k, v] of Object.entries(obj)) {
      const kl = k.toLowerCase().replace(/-/g, '_');
      if (ID_KEYS.has(kl)) {
        if (typeof v === 'string' && v.trim()) ids.push(v.trim());
        else if (typeof v === 'number' && Number.isFinite(v)) ids.push(String(v));
      } else if (
        typeof v === 'string' &&
        v.trim().length >= 6 &&
        /(^|_)(id|hash)$/i.test(k)
      ) {
        ids.push(v.trim());
      }
    }
    for (const k of Object.keys(obj)) {
      const v = obj[k];
      if (typeof v === 'object' && v) ids.push(...collectIdsFromJsonForIndex(v, depth + 1));
    }
    return ids;
  }

  /**
   * status/*.json (and state/) first — they carry authoritative original_name for the dropdown.
   * Other JSON (lyrics, etc.) fills ids only when that key is still missing.
   */
  async function buildOriginalNameIndex(files){
    const byId = new Map();

    async function ingestFile(f, opts){
      const onlyIfMissing = opts && opts.onlyIfMissing;
      const statusFile = opts && opts.statusFile;
      const rel = normPath(f);
      const leaf = (f.name || '').trim();
      if (!/\.json$/i.test(leaf)) return;
      if (!isJsonMetadataCandidate(rel)) return;
      let data;
      try {
        const raw = (await f.text()).replace(/^\uFEFF/, '');
        data = JSON.parse(raw);
      } catch {
        return;
      }
      const name = extractDisplayNameForIndex(data, statusFile);
      if (!name) return;

      function setKey(k){
        if (!k) return;
        const kk = String(k).toLowerCase();
        if (onlyIfMissing && byId.has(kk)) return;
        byId.set(kk, name);
      }

      const base = leaf.replace(/\.json$/i, '').toLowerCase();
      setKey(base);
      for (const rawId of collectIdsFromJsonForIndex(data, 0)) {
        setKey(rawId);
      }
    }

    for (const f of files) {
      const rel = normPath(f);
      if (!/\.json$/i.test(f.name)) continue;
      if (!isJsonMetadataCandidate(rel)) continue;
      if (!isStatusJsonPath(rel)) continue;
      await ingestFile(f, { statusFile: true, onlyIfMissing: false });
    }

    for (const f of files) {
      const rel = normPath(f);
      if (!/\.json$/i.test(f.name)) continue;
      if (!isJsonMetadataCandidate(rel)) continue;
      if (isStatusJsonPath(rel)) continue;
      await ingestFile(f, { statusFile: false, onlyIfMissing: true });
    }

    return byId;
  }

  /**
   * Collect every directory that has both vocals + band stems.
   * Uses the path’s final segment for matching (not only `File.name`), which fixes
   * some browsers / layouts where names alone don’t pair correctly.
   */
  function collectAllStemPairs(files){
    const arr = [...files];
    const byDir = new Map();
    for (const f of arr) {
      const leaf = stemLeafFromFile(f);
      if (!isVocalStemLeaf(leaf) && !isBandStemLeaf(leaf)) continue;
      const dKey = stemDirFromFile(f);
      if (!byDir.has(dKey)) byDir.set(dKey, { vocals: null, band: null });
      const slot = byDir.get(dKey);
      if (isVocalStemLeaf(leaf) && !slot.vocals) slot.vocals = f;
      if (isBandStemLeaf(leaf) && !slot.band) slot.band = f;
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
      const leaf = stemLeafFromFile(f);
      if (isVocalStemLeaf(leaf) && !vocals) vocals = f;
      if (isBandStemLeaf(leaf) && !band) band = f;
    }
    if (vocals && band) {
      const dv = stemDirFromFile(vocals);
      const db = stemDirFromFile(band);
      if (dv !== db) {
        return { pairs: [], mismatchedDirs: true };
      }
      return { pairs: [{ dir: dv || '', vocals, band }], mismatchedDirs: false };
    }
    return { pairs: [], mismatchedDirs: false };
  }

  function findLyricsFile(files, stemDir){
    const rows = [...files].map(f => ({
      f,
      leaf: (f.name || '').toLowerCase(),
      rel: normPath(f),
    }));
    const sd = (stemDir || '').replace(/\\/g, '/');
    const jid = jobIdFromStemDir(sd);
    if (jid) {
      const jn = jid.toLowerCase();
      const byJob = rows.find((r) => {
        const n = r.rel.replace(/\\/g, '/');
        const leaf = (r.f.name || '').trim();
        const base = leaf.replace(/\.(json|lrc|txt)$/i, '');
        const nameOk =
          base.toLowerCase() === jn &&
          (leaf.toLowerCase().endsWith('.json') ||
            leaf.toLowerCase().endsWith('.lrc') ||
            leaf.toLowerCase().endsWith('.txt'));
        const pathOk =
          /(^|\/)lyrics\//i.test(n) || /^lyrics\//i.test(n) || n.split('/').filter(Boolean).length === 1;
        return nameOk && pathOk;
      });
      if (byJob) return byJob.f;
    }
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

  async function enrichPairsWithLyricsMeta(files, pairs){
    const index = await buildOriginalNameIndex(files);
    const out = pairs.map((p) => {
      let originalName = '';
      const jids = jobIdCandidatesFromStemDir(p.dir);
      for (const jid of jids) {
        const k = String(jid).toLowerCase();
        if (k && index.has(k)) {
          originalName = index.get(k);
          break;
        }
      }
      return { ...p, originalName };
    });
    out.sort((a, b) =>
      displayLabel(a).localeCompare(displayLabel(b), undefined, { sensitivity: 'base' })
    );
    return out;
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

  function normalizeLyricsBody(s){
    if (typeof s !== 'string') return '';
    return s.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  }

  /** Prefer top-level `text` for display; timed `lines` / `lrc` only when needed for sync. */
  function tryParseLyricsJson(raw){
    let data;
    try { data = JSON.parse(raw); } catch { return null; }
    if (data == null) return null;
    if (typeof data === 'string') return { plain: normalizeLyricsBody(data) };
    if (typeof data.text === 'string') {
      const t = normalizeLyricsBody(data.text);
      if (t.trim()) return { plain: t };
    }
    if (typeof data.lrc === 'string' && data.lrc.trim()) return { lrc: data.lrc };
    if (typeof data.lyrics === 'string' && data.lyrics.trim()) return { plain: normalizeLyricsBody(data.lyrics) };
    if (typeof data.content === 'string' && data.content.trim()) return { plain: normalizeLyricsBody(data.content) };
    if (Array.isArray(data.lines)) {
      const lines = data.lines.map((l) => {
        if (typeof l === 'string') return { t: 0, text: l };
        const t = Number(l.time != null ? l.time : l.t != null ? l.t : l.start != null ? l.start : 0);
        const text = String(l.text != null ? l.text : l.line != null ? l.line : '');
        return { t: Number.isFinite(t) ? t : 0, text };
      }).filter((x) => x.text);
      if (lines.length) return { parsed: lines };
    }
    return null;
  }

  async function applyLyricsOnly(files, stemDir){
    const lyricsPlain = K.$('lyricsBox');
    const lyricsSync = K.$('lyricsSynced');

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
      const isJson = /\.json$/i.test(lyricsFile.name);

      if (isJson) {
        const jsonLyrics = tryParseLyricsJson(txt);
        if (jsonLyrics && jsonLyrics.parsed && jsonLyrics.parsed.length) {
          lyricsPlain.hidden = true;
          lyricsSync.hidden = false;
          renderLrcLines(lyricsSync, jsonLyrics.parsed);
          startLrcSync(jsonLyrics.parsed);
          return;
        }
        if (jsonLyrics && jsonLyrics.lrc) {
          const parsed = K.parseLRC(jsonLyrics.lrc);
          if (parsed.length) {
            lyricsPlain.hidden = true;
            lyricsSync.hidden = false;
            renderLrcLines(lyricsSync, parsed);
            startLrcSync(parsed);
            return;
          }
        }
        if (jsonLyrics && typeof jsonLyrics.plain === 'string') {
          lyricsPlain.hidden = false;
          lyricsSync.hidden = true;
          lyricsPlain.textContent = jsonLyrics.plain.trim() ? jsonLyrics.plain : '—';
          stopLrcSync();
          return;
        }
        lyricsPlain.hidden = false;
        lyricsSync.hidden = true;
        lyricsPlain.textContent = '—';
        stopLrcSync();
        return;
      }

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
        lyricsPlain.textContent = normalizeLyricsBody(txt);
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

  function applyStems(vocalsFile, bandFile, pairedDir, allFiles, displayTitle){
    if (!vocalsFile || !bandFile) return;
    if (vocalsFile === bandFile) {
      setLoadStatus('Vocals and band must be two different files.');
      return;
    }
    const vUrl = URL.createObjectURL(vocalsFile);
    const bUrl = URL.createObjectURL(bandFile);
    PB.setSources(vUrl, bUrl);
    K.setJobId(null);

    const title =
      (displayTitle && String(displayTitle).trim()) ||
      titleFromPair({ dir: pairedDir || '', vocals: vocalsFile, band: bandFile });
    PB.showTitle(title);
    setLoadStatus(`Loaded “${title}”. Route outputs, then Play.`);

    if (allFiles && allFiles.length) {
      applyLyricsOnly(allFiles, pairedDir || null);
    }
  }

  function loadSongAtIndex(idx){
    if (!folderFiles || !folderPairs.length) return;
    const pair = folderPairs[idx];
    if (!pair) return;
    const displayTitle = pair.originalName && pair.originalName.trim()
      ? pair.originalName.trim()
      : null;
    applyStems(pair.vocals, pair.band, pair.dir, folderFiles, displayTitle);
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
      let label = displayLabel(p);
      const dup = pairs.filter((q) => displayLabel(q) === label).length;
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

  projectFolderInput?.addEventListener('change', async () => {
    const files = projectFolderInput.files;
    if (!files || !files.length) return;

    folderFiles = [...files];
    setFolderSummary(`Scanned ${folderFiles.length} file(s).`);

    const { pairs, mismatchedDirs } = collectAllStemPairs(folderFiles);

    if (mismatchedDirs) {
      folderPairs = [];
      if (songPickWrap) songPickWrap.hidden = true;
      setLoadStatus('Vocals and band are in different folders — select a parent folder that contains each song’s stems together.');
      applyLyricsOnly(folderFiles, null);
    } else if (!pairs.length) {
      folderPairs = [];
      if (songPickWrap) songPickWrap.hidden = true;
      let nWav = 0;
      let nVoc = 0;
      let nBand = 0;
      for (const f of folderFiles) {
        const leaf = stemLeafFromFile(f);
        if (/\.wav$/i.test(leaf)) nWav++;
        if (isVocalStemLeaf(leaf)) nVoc++;
        if (isBandStemLeaf(leaf)) nBand++;
      }
      setLoadStatus(
        `No songs found. Expected vocals.* and no_vocals.* (or accompaniment.*) in the same folder. ` +
        `Scan: ${nVoc} vocal stem file(s), ${nBand} band stem file(s), ${nWav} .wav file(s). ` +
        `Pick the parent folder that includes output/… and lyrics/.`
      );
      applyLyricsOnly(folderFiles, null);
    } else {
      setLoadStatus(`Loading song names…`);
      const enriched = await enrichPairsWithLyricsMeta(folderFiles, pairs);
      setLoadStatus(`Found ${enriched.length} song(s).`);
      populateSongList(enriched);
    }

    projectFolderInput.value = '';
  });

  songPick?.addEventListener('change', () => {
    const v = songPick.value;
    if (v === '') {
      setLoadStatus('Select a song to load stems and lyrics.');
      PB.showTitle('—');
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
