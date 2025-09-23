/* assets/js/karaoke.js
   Upload + poll (submit page) and "player mode" listing (private storage via SAS).
   Output device routing, beep tests, correct Play/Pause/Restart behavior,
   and lyrics (load + save). Save writes meta.json next to outputs using /api/lyrics (POST).
*/

// =================== CONFIG ===================
const API_BASE = 'https://karaoke-func-bthmcvafagcncmck.canadacentral-01.azurewebsites.net'; // your Function App
const FUNCTION_CODE = ''; // optional: '...'; leave '' if authLevel="anonymous"
const OUTPUT_BASE = '';   // leave '' for private SAS links

const submitUrl   = `${API_BASE}/api/submit${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`;
const statusUrl   = (jobId) => `${API_BASE}/api/status/${encodeURIComponent(jobId)}${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`;
const lyricsApiUrl= `${API_BASE}/api/lyrics${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`;

// =================== ELEMENTS (upload page) ===================
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
};

let vocalsUrl = '';
let bandUrl   = '';
let pollTimer = null;
let currentJobId = null;   // <— used for Save Lyrics

// =================== HELPERS ===================
function setStatus(t) { if (els.status) els.status.textContent = t || ''; }
function showError(msg) { if (els.alert) { els.alert.textContent = msg; els.alert.classList.remove('hide'); } }
function hideError() { if (els.alert) { els.alert.classList.add('hide'); els.alert.textContent = ''; } }
function resetUI() {
  setStatus(''); hideError();
  els.done?.classList.add('hide');
  if (els.links) els.links.innerHTML = '';
  if (els.prog) els.prog.hidden = true;
  if (els.bar) els.bar.style.width = '0%';
  els.playerCard?.classList.add('hide');
  vocalsUrl = bandUrl = '';
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  // lyrics area
  const lyricsBox = document.getElementById('lyricsBox');
  const lyrText   = document.getElementById('lyrText');
  const lyricsMsg = document.getElementById('lyricsMsg');
  if (lyricsBox) lyricsBox.textContent = '';
  if (lyrText)   lyrText.value = '';
  if (lyricsMsg) lyricsMsg.textContent = '';
}

function asUrl(valueOrKey) {
  if (/^https?:\/\//i.test(valueOrKey)) return valueOrKey; // SAS or absolute
  return OUTPUT_BASE ? `${OUTPUT_BASE.replace(/\/$/,'')}/${valueOrKey.replace(/^\/+/,'')}` : '#';
}

// =================== CLEAR ===================
els.clear?.addEventListener('click', () => {
  if (els.file) els.file.value = '';
  resetUI();
});

// =================== POLLING (upload page) ===================
async function doPoll(jobId) {
  try {
    const r = await fetch(statusUrl(jobId), { mode: 'cors' });
    if (r.status === 404) return;
    const s = await r.json();

    if (s.state === 'queued') {
      setStatus('Queued…'); if (els.prog) els.prog.hidden = false;
      if (els.bar && !els.bar.style.width) els.bar.style.width = '10%';
      return;
    }

    if (s.state === 'running') {
      const p = Math.max(10, Math.min(95, s.progress ?? 50));
      if (els.prog) els.prog.hidden = false;
      if (els.bar) els.bar.style.width = p + '%';
      setStatus(`Processing… (${p}%)`);
      return;
    }

    if (s.state === 'failed') {
      setStatus('Error.');
      const retryTxt = s.retrying ? ` Retrying (attempt ${s.attempt}) in ${s.next_retry_in_seconds}s.` : '';
      showError((s.error || 'Job failed.') + retryTxt);
      if (!s.retrying && pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      if (els.prog) els.prog.hidden = true; if (els.bar) els.bar.style.width = '0%';
      return;
    }

    if (s.state === 'done') {
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      if (els.bar) els.bar.style.width = '100%';
      setTimeout(() => { if (els.prog) els.prog.hidden = true; if (els.bar) els.bar.style.width = '0%'; }, 800);
      setStatus('Done!');

      currentJobId = jobId; // <— tie saves to this processed song

      els.done?.classList.remove('hide');
      if (els.links) els.links.innerHTML = '';
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
        // Friendly title from original file name if available
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

// =================== SUBMIT (upload page) ===================
els.go?.addEventListener('click', async () => {
  try {
    hideError(); els.done?.classList.add('hide'); if (els.links) els.links.innerHTML = '';
    setStatus('Submitting…'); els.prog && (els.prog.hidden = false); els.bar && (els.bar.style.width = '10%');

    const fd = new FormData();
    if (els.file?.files[0]) fd.append('file', els.file.files[0]);
    if (!fd.has('file')) throw new Error('Please choose a file to upload.');

    const res = await fetch(submitUrl, { method: 'POST', body: fd, mode: 'cors' });
    let data = null;
    try { data = await res.json(); } catch {}
    if (!res.ok) {
      const msg = (data && (data.error || data.message)) || (await res.text());
      throw new Error(msg || `Submit failed (${res.status})`);
    }
    const jobId = data && data.job_id;
    if (!jobId) throw new Error('No job id returned.');

    currentJobId = jobId; // <— capture for lyrics save

    (window.dataLayer = window.dataLayer || []).push({ event: 'karaoke_submit' });
    setStatus('Queued. Processing…');
    startPolling(jobId);

  } catch (e) {
    showError(e.message || String(e));
    setStatus(''); if (els.prog) els.prog.hidden = true; if (els.bar) els.bar.style.width = '0%';
  }
});

// =================== DUAL-OUTPUT ROUTING + CONTROLS ===================
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

function showTrackTitle(t){ if (trackTitle) trackTitle.textContent = t || ''; }

const deviceMsg = document.getElementById('deviceMsg');
function setDeviceMsg(t){ if (deviceMsg) deviceMsg.textContent = t || ''; }

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
function pauseAll(){ clearSyncTimer(); try{vocalsEl?.pause()}catch{}; try{bandEl?.pause()}catch{}; if(vocalsEl) vocalsEl.playbackRate=1; if(bandEl) bandEl.playbackRate=1; isPlaying=false; onPlaybackPaused(); }

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

async function resumePlay(){ await Promise.all([vocalsEl.play().catch(()=>{}), bandEl.play().catch(()=>{})]); isPlaying=true; startDriftCorrection(currentOffsetMs()); onPlaybackStarted(); }

async function startFromZeroWithOffset(offsetMs){
  vocalsEl.currentTime=0; bandEl.currentTime=0;
  if (offsetMs >= 0){ await bandEl.play(); await sleep(offsetMs); await vocalsEl.play(); }
  else { await vocalsEl.play(); await sleep(-offsetMs); await bandEl.play(); }
  isPlaying=true; startDriftCorrection(offsetMs); onPlaybackStarted();
}

function currentOffsetMs(){ return parseInt(offsetIn?.value || '0', 10) || 0; }

function startDriftCorrection(offsetMs){
  clearSyncTimer();
  window._syncTimer = setInterval(() => {
    if (!isPlaying) return;
    const driftMs = (vocalsEl.currentTime - bandEl.currentTime) * 1000 - offsetMs;
    if (Math.abs(driftMs) > 60) {
      if (driftMs > 0) { const r=vocalsEl.playbackRate; vocalsEl.playbackRate=Math.max(0.9,r-0.05); setTimeout(()=>{vocalsEl.playbackRate=r},300); }
      else { const r=bandEl.playbackRate; bandEl.playbackRate=Math.max(0.9,r-0.05); setTimeout(()=>{bandEl.playbackRate=r},300); }
    }
  }, 2000);
}

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

// ======= Beep tests =======
const _beepElVocals = document.createElement('audio');
const _beepElBand   = document.createElement('audio');
_beepElVocals.setAttribute('playsinline',''); _beepElVocals.style.display='none';
_beepElBand.setAttribute('playsinline','');   _beepElBand.style.display='none';
document.body.appendChild(_beepElVocals); document.body.appendChild(_beepElBand);
async function playBeep(which, sinkId, freq=880, ms=600){
  const supportSink = typeof HTMLMediaElement.prototype.setSinkId === 'function';
  if (!supportSink){ alert('Output selection not supported in this browser.'); return; }
  const outEl = which==='band'?_beepElBand:_beepElVocals;
  const ac = new (window.AudioContext||window.webkitAudioContext)(); const osc=ac.createOscillator(); const gain=ac.createGain();
  gain.gain.setValueAtTime(0.0001, ac.currentTime); gain.gain.exponentialRampToValueAtTime(0.3, ac.currentTime+0.02);
  osc.frequency.value=freq; osc.type='sine'; const dest=ac.createMediaStreamDestination(); osc.connect(gain); gain.connect(dest);
  try{ await outEl.setSinkId(sinkId||'default'); }catch{}
  outEl.srcObject=dest.stream;
  try{ osc.start(); await outEl.play(); const endT=ac.currentTime+ms/1000; gain.gain.exponentialRampToValueAtTime(0.0001,endT-0.05); osc.stop(endT); setTimeout(()=>{outEl.pause(); outEl.srcObject=null; ac.close().catch(()=>{});}, ms+120); }catch{ ac.close().catch(()=>{}); }
}
document.getElementById('testVocals')?.addEventListener('click', ()=>playBeep('vocals', vocalsOut?.value, 880, 500));
document.getElementById('testBand')?.addEventListener('click',   ()=>playBeep('band',   bandOut?.value,   660, 500));

// =================== LYRICS (load + save) ===================
const lyricsBtn   = document.getElementById('loadLyrics');
const saveBtn     = document.getElementById('saveLyrics');
const lyricsBox   = document.getElementById('lyricsBox');
const lyrArtist   = document.getElementById('lyrArtist');
const lyrText     = document.getElementById('lyrText');
const lyricsMsg   = document.getElementById('lyricsMsg');

let _lrcLines = null, _lyricsTimer = null;

function parseLRC(lrcText){
  const lines=[]; const re=/\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\](.*)/g; let m;
  while((m=re.exec(lrcText))!==null){ const min=+m[1], sec=+m[2], ms=m[3]?+m[3].padEnd(3,'0'):0; const t=min*60+sec+ms/1000; lines.push({t, text:(m[4]||'').trim()}); }
  lines.sort((a,b)=>a.t-b.t); return lines;
}
function renderUnsynced(text){ if(lyricsBox) lyricsBox.textContent = text || 'No lyrics found.'; }
function stopLyricsSync(){ if(_lyricsTimer){ clearInterval(_lyricsTimer); _lyricsTimer=null; } }
function startLyricsSync(){
  if(!_lrcLines||!lyricsBox) return; stopLyricsSync();
  _lyricsTimer=setInterval(()=>{ const ct=bandEl?.currentTime||vocalsEl?.currentTime||0; let i=_lrcLines.findIndex(l=>l.t>ct); if(i===-1)i=_lrcLines.length; const idx=Math.max(0,i-1); const prev=Math.max(0,idx-3); const next=Math.min(_lrcLines.length, idx+4);
    const chunk=_lrcLines.slice(prev,next).map(l=>l===_lrcLines[idx]?`> ${l.text}`:`  ${l.text}`).join('\n'); lyricsBox.textContent=chunk||'—'; },250);
}
function onPlaybackStarted(){ startLyricsSync(); }
function onPlaybackPaused(){ stopLyricsSync(); }

// Load current lyrics (favor uploaded meta.json via your Function)
lyricsBtn?.addEventListener('click', async () => {
  try{
    const titleText=(trackTitle?.textContent||'').trim();
    let title=(titleText && titleText!=='—' && titleText!=='Unknown Track')?titleText:'';
    if(!title){ const guess=(vocalsUrl||bandUrl||'').split('?')[0].split('/').pop(); title=guess?guess.replace(/\.(wav|mp3|m4a|flac|aac)$/i,''):''; }
    const artist=lyrArtist?.value?.trim()||''; const duration=Math.round(bandEl?.duration||vocalsEl?.duration||0);

    const url=new URL(lyricsApiUrl);
    if (currentJobId) url.searchParams.set('job_id', currentJobId);
    if (title)        url.searchParams.set('title', title);
    if (artist)       url.searchParams.set('artist', artist);
    if (duration)     url.searchParams.set('duration', String(duration));

    lyricsMsg && (lyricsMsg.textContent='Fetching lyrics…');
    const r=await fetch(url.toString(), {mode:'cors'}); const data=await r.json();
    stopLyricsSync(); _lrcLines=null;

    if(!data || data.found===false){ renderUnsynced('No lyrics found.'); lyricsMsg && (lyricsMsg.textContent=''); return; }
    if(data.synced && data.lrc){
      _lrcLines=parseLRC(data.lrc);
      lyricsBox.textContent='Synced lyrics loaded.';
      lyrText && (lyrText.value = data.lrc); // fill editor with what we loaded
      if(isPlaying) startLyricsSync();
    } else {
      renderUnsynced(data.text || 'No lyrics text available.');
      lyrText && (lyrText.value = data.text || '');
    }
    lyricsMsg && (lyricsMsg.textContent='Loaded.');
  }catch(e){
    console.warn(e);
    lyricsMsg && (lyricsMsg.textContent='Failed to fetch lyrics.');
  }
});

// Save (upsert) lyrics for this song/job
saveBtn?.addEventListener('click', async () => {
  try{
    const text = (lyrText?.value || '').trim();
    if (!text){ lyricsMsg && (lyricsMsg.textContent='Paste lyrics before saving.'); return; }

    // detect LRC by presence of time tags
    const isLRC = /\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]/.test(text);

    const titleText=(trackTitle?.textContent||'').trim();
    let title=(titleText && titleText!=='—' && titleText!=='Unknown Track')?titleText:'';
    if(!title){ const guess=(vocalsUrl||bandUrl||'').split('?')[0].split('/').pop(); title=guess?guess.replace(/\.(wav|mp3|m4a|flac|aac)$/i,''):''; }
    const artist=lyrArtist?.value?.trim()||'';

    const payload = {
      synced: !!isLRC
    };
    if (currentJobId) payload.job_id = currentJobId;
    if (title)        payload.title  = title;
    if (artist)       payload.artist = artist;
    if (isLRC)        payload.lrc    = text;
    else              payload.text   = text;

    lyricsMsg && (lyricsMsg.textContent='Saving…');
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
    lyricsMsg && (lyricsMsg.textContent='Saved.');
    // Refresh preview to reflect final source of truth
    document.getElementById('loadLyrics')?.click();
  }catch(e){
    console.warn(e);
    lyricsMsg && (lyricsMsg.textContent = e.message || 'Save failed.');
  }
});

// =================== PLAYER MODE (uses /api/list with SAS) ===================
if (window.KARAOKE_MODE === 'player') {
  (function(){
    const LIST_META = document.querySelector('meta[name="karaoke-list"]');
    const LIST_URL  = LIST_META?.content || '';

    const pick        = document.getElementById('songPick');
    const useBtn      = document.getElementById('useSelection');
    const refreshBtn  = document.getElementById('refreshList');
    const status      = document.getElementById('listStatus');

    const vocalsUrlIn = document.getElementById('vocalsUrl'); // hidden
    const bandUrlIn   = document.getElementById('bandUrl');   // hidden
    const loadBtn     = document.getElementById('loadBtn');   // hidden
    const loadStatus  = document.getElementById('loadStatus');

    function setListStatus(t){ if (status) status.textContent = t || ''; }

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
          // include job_id so Save ties to the same job
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
        vocalsUrl   = sel.vocals || '';
        bandUrl     = sel.band   || '';
        currentJobId= sel.job_id || null;
        showTrackTitle(sel.title || 'Unknown Track');

        // Reset playback + lyrics because sources changed
        isLoaded  = false;
        isPlaying = false;
        pauseAll();
        stopLyricsSync();
        if (lyricsBox) lyricsBox.textContent = '—';
        if (lyrText)   lyrText.value = '';
        if (lyricsMsg) lyricsMsg.textContent = '';

        if (vocalsUrlIn) vocalsUrlIn.value = vocalsUrl;
        if (bandUrlIn)   bandUrlIn.value   = bandUrl;
        loadBtn?.click();
        if (loadStatus) loadStatus.textContent = 'Tracks loaded.';
      } catch (e) {
        console.warn('Invalid selection', e);
      }
    });

    refreshBtn?.addEventListener('click', loadList);
    loadList();
  })();
}