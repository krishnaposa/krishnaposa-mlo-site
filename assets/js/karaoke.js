/* assets/js/karaoke.js
   Upload + poll (submit page) and "player mode" listing (private storage via SAS).
   Output device routing, beep tests, play/pause/restart.
   Lyrics: simplified — Load/Save with job_id, no preview box.
*/

// =================== CONFIG ===================
const API_BASE = 'https://karaoke-func-bthmcvafagcncmck.canadacentral-01.azurewebsites.net';
const FUNCTION_CODE = '';
const OUTPUT_BASE = '';

const submitUrl    = `${API_BASE}/api/submit${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`;
const statusUrl    = (jobId) => `${API_BASE}/api/status/${encodeURIComponent(jobId)}${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`;
const lyricsApiUrl = `${API_BASE}/api/lyrics${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`;

// =================== ELEMENTS ===================
const els = {
  file: document.getElementById('file'),
  go: document.getElementById('go'),
  clear: document.getElementById('clear'),
  status: document.getElementById('status'),
  alert: document.getElementById('alert'),
  done: document.getElementById('done'),
  links: document.getElementById('links'),
  prog: document.getElementById('prog'),
  bar: document.getElementById('bar'),
  playerCard: document.getElementById('playerCard'),
  lyrJobId: document.getElementById('lyrJobId'),
  lyrText: document.getElementById('lyrText'),
  loadLyrics: document.getElementById('loadLyrics'),
  saveLyrics: document.getElementById('saveLyrics'),
  lyricsMsg: document.getElementById('lyricsMsg'),
};

let vocalsUrl = '';
let bandUrl   = '';
let pollTimer = null;
let currentJobId = null;

// =================== HELPERS ===================
function setStatus(t) { els.status && (els.status.textContent = t || ''); }
function showError(msg) { if (els.alert) { els.alert.textContent = msg; els.alert.classList.remove('hide'); } }
function hideError() { if (els.alert) { els.alert.classList.add('hide'); els.alert.textContent = ''; } }
function resetUI() {
  setStatus(''); hideError();
  els.done?.classList.add('hide');
  els.links && (els.links.innerHTML = '');
  els.prog && (els.prog.hidden = true);
  els.bar && (els.bar.style.width = '0%');
  els.playerCard?.classList.add('hide');
  vocalsUrl = bandUrl = '';
  currentJobId = null;
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  // lyrics editor
  els.lyrJobId && (els.lyrJobId.value = '');
  els.lyrText && (els.lyrText.value = '');
  els.lyricsMsg && (els.lyricsMsg.textContent = '');
}

function asUrl(valueOrKey) {
  if (/^https?:\/\//i.test(valueOrKey)) return valueOrKey;
  return OUTPUT_BASE ? `${OUTPUT_BASE.replace(/\/$/,'')}/${valueOrKey.replace(/^\/+/,'')}` : '#';
}

// =================== CLEAR ===================
els.clear?.addEventListener('click', () => {
  if (els.file) els.file.value = '';
  resetUI();
});

// =================== POLLING ===================
async function doPoll(jobId) {
  try {
    const r = await fetch(statusUrl(jobId), { mode: 'cors' });
    if (r.status === 404) return;
    const s = await r.json();

    if (s.state === 'queued') {
      setStatus('Queued…');
      els.prog && (els.prog.hidden = false);
      if (els.bar && !els.bar.style.width) els.bar.style.width = '10%';
      return;
    }
    if (s.state === 'running') {
      const p = Math.max(10, Math.min(95, s.progress ?? 50));
      els.prog && (els.prog.hidden = false);
      els.bar && (els.bar.style.width = p + '%');
      setStatus(`Processing… (${p}%)`);
      return;
    }
    if (s.state === 'failed') {
      setStatus('Error.');
      const retryTxt = s.retrying ? ` Retrying (attempt ${s.attempt}) in ${s.next_retry_in_seconds}s.` : '';
      showError((s.error || 'Job failed.') + retryTxt);
      if (!s.retrying && pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      els.prog && (els.prog.hidden = true);
      els.bar && (els.bar.style.width = '0%');
      return;
    }
    if (s.state === 'done') {
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      els.bar && (els.bar.style.width = '100%');
      setTimeout(() => { els.prog && (els.prog.hidden = true); els.bar && (els.bar.style.width = '0%'); }, 800);
      setStatus('Done!');

      currentJobId = jobId;
      if (els.lyrJobId) els.lyrJobId.value = jobId; // expose to user

      els.done?.classList.remove('hide');
      els.links && (els.links.innerHTML = '');
      for (const [name, val] of Object.entries(s.outputs || {})) {
        const href = asUrl(val);
        if (els.links) {
          const li = document.createElement('li');
          const a = document.createElement('a');
          a.textContent = name;
          if (href !== '#') { a.href = href; a.target = '_blank'; a.rel = 'noopener'; a.download = name; }
          li.appendChild(a); els.links.appendChild(li);
        }
      }

      vocalsUrl = asUrl((s.outputs || {})['vocals.wav'] || '');
      bandUrl   = asUrl((s.outputs || {})['no_vocals.wav'] || '');
      if (els.playerCard && vocalsUrl && bandUrl && vocalsUrl !== '#' && bandUrl !== '#') {
        els.playerCard.classList.remove('hide');
        const base = (s.original_name || '').split('/').pop() || '—';
        const title = base.replace(/\.(wav|mp3|m4a|flac|aac)$/i,'');
        const tEl = document.getElementById('trackTitle');
        if (tEl) tEl.textContent = title || '—';
      }
      return;
    }
    setStatus(s.state || '…');
  } catch (err) {
    console.warn('poll error', err);
  }
}

function startPolling(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => doPoll(jobId), 1500);
}

// =================== SUBMIT ===================
els.go?.addEventListener('click', async () => {
  try {
    hideError(); els.done?.classList.add('hide'); els.links && (els.links.innerHTML = '');
    setStatus('Submitting…'); els.prog && (els.prog.hidden = false); els.bar && (els.bar.style.width = '10%');

    const fd = new FormData();
    if (els.file?.files[0]) fd.append('file', els.file.files[0]);
    if (!fd.has('file')) throw new Error('Please choose a file to upload.');

    const res = await fetch(submitUrl, { method: 'POST', body: fd, mode: 'cors' });
    let data = null; try { data = await res.json(); } catch {}
    if (!res.ok) {
      const msg = (data && (data.error || data.message)) || (await res.text());
      throw new Error(msg || `Submit failed (${res.status})`);
    }
    const jobId = data && data.job_id;
    if (!jobId) throw new Error('No job id returned.');
    currentJobId = jobId;
    if (els.lyrJobId) els.lyrJobId.value = jobId;

    (window.dataLayer = window.dataLayer || []).push({ event: 'karaoke_submit' });
    setStatus('Queued. Processing…');
    startPolling(jobId);
  } catch (e) {
    showError(e.message || String(e));
    setStatus(''); els.prog && (els.prog.hidden = true); els.bar && (els.bar.style.width = '0%');
  }
});

// =================== AUDIO ROUTING ===================
const vocalsEl  = document.getElementById('vocalsEl');
const bandEl    = document.getElementById('bandEl');
const vocalsOut = document.getElementById('vocalsOut');
const bandOut   = document.getElementById('bandOut');
const initBtn   = document.getElementById('initAudio');
const playBtn   = document.getElementById('play');
const pauseBtn  = document.getElementById('pause');
const restartBtn= document.getElementById('restart');
const offsetIn  = document.getElementById('offset');
const trackTitle= document.getElementById('trackTitle');

function showTrackTitle(t){ trackTitle && (trackTitle.textContent = t || ''); }

const deviceMsg = document.getElementById('deviceMsg');
function setDeviceMsg(t){ deviceMsg && (deviceMsg.textContent = t || ''); }

const supportSink = typeof HTMLMediaElement.prototype.setSinkId === 'function';
let isLoaded  = false;
let isPlaying = false;

async function ensurePermission() {
  try { await navigator.mediaDevices.getUserMedia({ audio: true }); return true; }
  catch { setDeviceMsg('Please allow microphone access to list audio outputs.'); return false; }
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
  const devices = await navigator.mediaDevices.enumerateDevices();
  const outs = devices.filter(d => d.kind === 'audiooutput');
  if (outs.length) { fillSelect(vocalsOut, outs); fillSelect(bandOut, outs); setDeviceMsg(`Found ${outs.length} output device(s).`); }
  else { addDefaultFallback(vocalsOut); addDefaultFallback(bandOut); setDeviceMsg('No discrete outputs reported. Using system default.'); }
  return outs.length;
}

initBtn?.addEventListener('click', async () => {
  setDeviceMsg('');
  if (!supportSink) { setDeviceMsg('Output selection not supported here. Use Chrome/Edge desktop.'); return; }
  if (!await ensurePermission()) return;
  const count = await listOutputs();
  initBtn.textContent = count ? 'Device list ready' : 'Device list (default only)';
  try { navigator.mediaDevices.addEventListener('devicechange', listOutputs); } catch {}
});

async function applySinks() {
  if (!supportSink) return;
  try { await vocalsEl?.setSinkId(vocalsOut?.value || 'default'); } catch(e){}
  try { await bandEl?.setSinkId(bandOut?.value   || 'default'); } catch(e){}
}

function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }
function clearSyncTimer(){ if (window._syncTimer){ clearInterval(window._syncTimer); window._syncTimer=null; } }
function pauseAll(){ clearSyncTimer(); try{vocalsEl?.pause()}catch{}; try{bandEl?.pause()}catch{}; if(vocalsEl) vocalsEl.playbackRate=1; if(bandEl) bandEl.playbackRate=1; isPlaying=false; }

async function preloadIfNeeded() {
  if (isLoaded) return;
  if (!vocalsUrl || !bandUrl || vocalsUrl === '#' || bandUrl === '#') throw new Error('No tracks loaded yet.');
  vocalsEl.src = vocalsUrl; bandEl.src = bandUrl;
  await applySinks(); vocalsEl.load(); bandEl.load();
  await Promise.all([
    new Promise(r => vocalsEl.addEventListener('canplay', r, {once:true})),
    new Promise(r => bandEl.addEventListener('canplay', r, {once:true})),
  ]);
  isLoaded = true;
}

async function resumePlay(){ await Promise.all([vocalsEl.play().catch(()=>{}), bandEl.play().catch(()=>{})]); isPlaying=true; }
async function startFromZeroWithOffset(offsetMs){
  vocalsEl.currentTime=0; bandEl.currentTime=0;
  if (offsetMs >= 0){ await bandEl.play(); await sleep(offsetMs); await vocalsEl.play(); }
  else { await vocalsEl.play(); await sleep(-offsetMs); await bandEl.play(); }
  isPlaying=true;
}
function currentOffsetMs(){ return parseInt(offsetIn?.value || '0', 10) || 0; }

playBtn?.addEventListener('click', async () => {
  try {
    if (!vocalsEl || !bandEl) return;
    if (isPlaying) return;
    await preloadIfNeeded();
    if (vocalsEl.paused && bandEl.paused && (vocalsEl.currentTime>0 || bandEl.currentTime>0)) await resumePlay();
    else await startFromZeroWithOffset(currentOffsetMs());
  } catch (e) { console.warn('play failed', e); alert(e.message || 'Could not start playback.'); }
});
pauseBtn?.addEventListener('click', pauseAll);
restartBtn?.addEventListener('click', async () => { try { await preloadIfNeeded(); pauseAll(); await startFromZeroWithOffset(currentOffsetMs()); } catch (e) { console.warn('restart failed', e); alert(e.message || 'Could not restart playback.'); } });

// =================== LYRICS (no preview) ===================
els.loadLyrics?.addEventListener('click', async () => {
  try{
    const jobId = (els.lyrJobId?.value || currentJobId || '').trim();
    if (!jobId){ els.lyricsMsg && (els.lyricsMsg.textContent='Enter a Job ID first.'); return; }

    const url=new URL(lyricsApiUrl);
    url.searchParams.set('job_id', jobId);

    els.lyricsMsg && (els.lyricsMsg.textContent='Fetching lyrics…');
    const r=await fetch(url.toString(), {mode:'cors'});
    const data=await r.json();

    if(!data || data.found===false){
      els.lyricsMsg && (els.lyricsMsg.textContent='No saved lyrics for this job.');
      els.lyrText && (els.lyrText.value = '');
      return;
    }
    els.lyrText && (els.lyrText.value = data.lrc || data.text || '');
    els.lyricsMsg && (els.lyricsMsg.textContent='Loaded.');
    currentJobId = jobId; // lock in for Save
  }catch(e){
    console.warn(e);
    els.lyricsMsg && (els.lyricsMsg.textContent='Failed to fetch lyrics.');
  }
});

els.saveLyrics?.addEventListener('click', async () => {
  try{
    const jobId = (els.lyrJobId?.value || currentJobId || '').trim();
    if (!jobId){ els.lyricsMsg && (els.lyricsMsg.textContent='Enter a Job ID first.'); return; }
    const text = (els.lyrText?.value || '').trim();
    if (!text){ els.lyricsMsg && (els.lyricsMsg.textContent='Paste lyrics before saving.'); return; }

    const payload = { job_id: jobId, text };
    els.lyricsMsg && (els.lyricsMsg.textContent='Saving…');
    const r = await fetch(lyricsApiUrl, {
      method:'POST',
      mode:'cors',
      headers:{'Content-Type':'application/json; charset=utf-8'},
      body: JSON.stringify(payload)
    });
    const resp = await r.json().catch(()=>({}));
    if (!r.ok || resp.error){
      throw new Error(resp.error || `Save failed (${r.status})`);
    }
    els.lyricsMsg && (els.lyricsMsg.textContent='Saved.');
    currentJobId = jobId;
  }catch(e){
    console.warn(e);
    els.lyricsMsg && (els.lyricsMsg.textContent = e.message || 'Save failed.');
  }
});

// =================== PLAYER MODE (list via SAS, unchanged) ===================
if (window.KARAOKE_MODE === 'player') {
  (function(){
    const LIST_META = document.querySelector('meta[name="karaoke-list"]');
    const LIST_URL  = LIST_META?.content || '';

    const pick        = document.getElementById('songPick');
    const useBtn      = document.getElementById('useSelection');
    const refreshBtn  = document.getElementById('refreshList');
    const status      = document.getElementById('listStatus');

    const vocalsUrlIn = document.getElementById('vocalsUrl');
    const bandUrlIn   = document.getElementById('bandUrl');
    const loadBtn     = document.getElementById('loadBtn');
    const loadStatus  = document.getElementById('loadStatus');

    function setListStatus(t){ status && (status.textContent = t || ''); }

    async function loadList(){
      try {
        if (!LIST_URL) throw new Error('Missing karaoke-list URL meta.');
        setListStatus('Loading songs…');
        const res = await fetch(LIST_URL, { mode: 'cors' });
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
          opt.value = JSON.stringify({
            job_id: it.job_id,
            vocals: it.vocals_url,
            band:   it.band_url,
            title:  it.title || it.job_id
          });
          opt.textContent = it.title || it.job_id;
          pick?.appendChild(opt);
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
      try {
        const sel = JSON.parse(val);
        vocalsUrl    = sel.vocals || '';
        bandUrl      = sel.band   || '';
        currentJobId = sel.job_id || null;
        showTrackTitle(sel.title || 'Unknown Track');

        isLoaded  = false; isPlaying = false; pauseAll();

        if (vocalsUrlIn) vocalsUrlIn.value = vocalsUrl;
        if (bandUrlIn)   bandUrlIn.value   = bandUrl;
        loadBtn?.click();
        if (loadStatus) loadStatus.textContent = 'Tracks loaded.';
        if (els.lyrJobId) els.lyrJobId.value = currentJobId || '';
      } catch (e) {
        console.warn('Invalid selection', e);
      }
    });

    refreshBtn?.addEventListener('click', loadList);
    loadList();
  })();
}