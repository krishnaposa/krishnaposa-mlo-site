/* assets/js/karaoke.js
   Upload + poll; optional lyrics upload (same Submit).
   Robust output device listing, beep tests, and Play/Pause/Restart behavior.
   Lyrics POST goes to /api/lyrics; GET is supported (guarded) if you add a viewer later.
*/

// =================== CONFIG ===================
const API_BASE = 'https://karaoke-func-bthmcvafagcncmck.canadacentral-01.azurewebsites.net'; // your Function App
const FUNCTION_CODE = ''; // optional: '...'; leave '' if authLevel="anonymous"
const OUTPUT_BASE = '';   // if your output container is public, set the CDN/base here

// Endpoints
const submitUrl   = `${API_BASE}/api/submit${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`;
const statusUrl   = (jobId) => `${API_BASE}/api/status/${encodeURIComponent(jobId)}${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`;
const lyricsApiUrl= `${API_BASE}/api/lyrics${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`;

// =================== ELEMENTS ===================
const els = {
  // upload
  file:       document.getElementById('file'),
  go:         document.getElementById('go'),
  clear:      document.getElementById('clear'),
  status:     document.getElementById('status'),
  alert:      document.getElementById('alert'),
  done:       document.getElementById('done'),
  links:      document.getElementById('links'),
  prog:       document.getElementById('prog'),
  bar:        document.getElementById('bar'),
  playerCard: document.getElementById('playerCard'),

  // optional lyrics upload (same Submit)
  lyrTitle:   document.getElementById('lyrTitle'),
  lyrArtist:  document.getElementById('lyrArtist'),
  lyrText:    document.getElementById('lyrText'),
};

let vocalsUrl = '';
let bandUrl   = '';
let pollTimer = null;

// =================== HELPERS ===================
function setStatus(t){ if (els.status) els.status.textContent = t || ''; }
function showError(msg){ if (els.alert){ els.alert.textContent = msg; els.alert.classList.remove('hide'); } }
function hideError(){ if (els.alert){ els.alert.classList.add('hide'); els.alert.textContent = ''; } }
function resetUI(){
  setStatus(''); hideError();
  els.done?.classList.add('hide');
  if (els.links) els.links.innerHTML = '';
  els.prog && (els.prog.hidden = true);
  els.bar  && (els.bar.style.width = '0%');
  els.playerCard?.classList.add('hide');
  vocalsUrl = bandUrl = '';
  if (pollTimer){ clearInterval(pollTimer); pollTimer = null; }
}
function asUrl(valueOrKey){
  if (/^https?:\/\//i.test(valueOrKey)) return valueOrKey; // SAS or absolute
  return OUTPUT_BASE ? `${OUTPUT_BASE.replace(/\/$/,'')}/${valueOrKey.replace(/^\/+/,'')}` : '#';
}
function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }

// =================== CLEAR ===================
els.clear?.addEventListener('click', () => {
  if (els.file) els.file.value = '';
  if (els.lyrTitle)  els.lyrTitle.value  = '';
  if (els.lyrArtist) els.lyrArtist.value = '';
  if (els.lyrText)   els.lyrText.value   = '';
  resetUI();
});

// =================== POLLING (upload page) ===================
async function doPoll(jobId){
  try{
    const r = await fetch(statusUrl(jobId), { mode: 'cors' });
    if (r.status === 404) return; // not ready yet
    const s = await r.json();

    if (s.state === 'queued'){
      setStatus('Queued…'); els.prog && (els.prog.hidden = false);
      if (els.bar && !els.bar.style.width) els.bar.style.width = '10%';
      return;
    }

    if (s.state === 'running'){
      const p = Math.max(10, Math.min(95, s.progress ?? 50));
      els.prog && (els.prog.hidden = false);
      els.bar  && (els.bar.style.width = p + '%');
      setStatus(`Processing… (${p}%)`);
      return;
    }

    if (s.state === 'failed'){
      setStatus('Error.');
      const retryTxt = s.retrying ? ` Retrying (attempt ${s.attempt}) in ${s.next_retry_in_seconds}s.` : '';
      showError((s.error || 'Job failed.') + retryTxt);
      if (!s.retrying && pollTimer){ clearInterval(pollTimer); pollTimer = null; }
      els.prog && (els.prog.hidden = true); els.bar && (els.bar.style.width = '0%');
      return;
    }

    if (s.state === 'done'){
      if (pollTimer){ clearInterval(pollTimer); pollTimer = null; }
      els.bar && (els.bar.style.width = '100%');
      setTimeout(()=>{ els.prog && (els.prog.hidden = true); els.bar && (els.bar.style.width = '0%'); }, 800);
      setStatus('Done!');

      els.done?.classList.remove('hide');
      if (els.links) els.links.innerHTML = '';
      for (const [name, val] of Object.entries(s.outputs || {})){
        const href = asUrl(val);
        if (els.links){
          const li = document.createElement('li');
          const a  = document.createElement('a');
          a.textContent = name;
          if (href !== '#'){ a.href = href; a.target = '_blank'; a.rel = 'noopener'; a.download = name; }
          li.appendChild(a); els.links.appendChild(li);
        }
      }

      vocalsUrl = asUrl((s.outputs || {})['vocals.wav']     || '');
      bandUrl   = asUrl((s.outputs || {})['no_vocals.wav']  || '');
      if (els.playerCard && vocalsUrl && bandUrl && vocalsUrl !== '#' && bandUrl !== '#'){
        els.playerCard.classList.remove('hide');
        const base  = (s.original_name || '').split('/').pop() || '';
        const title = base.replace(/\.(wav|mp3|m4a|flac|aac)$/i,'');
        const tEl = document.getElementById('trackTitle');
        if (tEl) tEl.textContent = title || '—';
      }
      return;
    }

    setStatus(s.state || '…');
  }catch(err){
    console.warn('poll error', err);
  }
}
function startPolling(jobId){
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(()=>doPoll(jobId), 1500);
}

// =================== LYRICS: POST (optional) ===================
async function postLyricsIfProvided(){
  const title  = (els.lyrTitle?.value || '').trim();
  const artist = (els.lyrArtist?.value || '').trim();
  const text   = (els.lyrText?.value || '').trim();

  // Nothing to upload? No-op.
  if (!title && !text) return;

  if (!title || !text){
    // Be forgiving: only warn in UI, don't block audio processing
    console.warn('Lyrics upload skipped: need both title and text if you want to upload lyrics.');
    return;
  }

  try{
    const res = await fetch(lyricsApiUrl, {
      method: 'POST',
      mode: 'cors',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, artist, text })
    });
    const data = await res.json().catch(()=> ({}));
    if (!res.ok){
      console.warn('Lyrics upload failed:', data?.error || res.statusText);
      return;
    }
    console.log('Lyrics uploaded:', data);
  }catch(e){
    console.warn('Lyrics upload error:', e);
  }
}

// =================== SUBMIT (upload page) ===================
els.go?.addEventListener('click', async () => {
  try{
    hideError(); els.done?.classList.add('hide'); if (els.links) els.links.innerHTML = '';
    setStatus('Submitting…'); els.prog && (els.prog.hidden = false); els.bar && (els.bar.style.width = '10%');

    const fd = new FormData();
    if (els.file?.files[0]) fd.append('file', els.file.files[0]);
    if (!fd.has('file')) throw new Error('Please choose a file to upload.');

    // Kick off audio job
    const res = await fetch(submitUrl, { method: 'POST', body: fd, mode: 'cors' });
    let data = null;
    try{ data = await res.json(); }catch{}
    if (!res.ok){
      const msg = (data && (data.error || data.message)) || (await res.text());
      throw new Error(msg || `Submit failed (${res.status})`);
    }
    const jobId = data && data.job_id;
    if (!jobId) throw new Error('No job id returned.');

    // Fire-and-forget lyrics upload (optional); don't block polling
    postLyricsIfProvided();

    (window.dataLayer = window.dataLayer || []).push({ event: 'karaoke_submit' });
    setStatus('Queued. Processing…');
    startPolling(jobId);

  }catch(e){
    showError(e.message || String(e));
    setStatus(''); els.prog && (els.prog.hidden = true); els.bar && (els.bar.style.width = '0%');
  }
});

// =================== DUAL-OUTPUT ROUTING + CONTROLS ===================
const vocalsEl   = document.getElementById('vocalsEl');
const bandEl     = document.getElementById('bandEl');
const vocalsOut  = document.getElementById('vocalsOut');
const bandOut    = document.getElementById('bandOut');
const initBtn    = document.getElementById('initAudio');
const playBtn    = document.getElementById('play');
const pauseBtn   = document.getElementById('pause');
const restartBtn = document.getElementById('restart'); // optional
const offsetIn   = document.getElementById('offset');
const trackTitle = document.getElementById('trackTitle');

const deviceMsg  = document.getElementById('deviceMsg');
function setDeviceMsg(t){ if (deviceMsg) deviceMsg.textContent = t || ''; }

const supportSink = typeof HTMLMediaElement.prototype.setSinkId === 'function';
let isLoaded  = false;
let isPlaying = false;

async function ensurePermission(){
  try{
    await navigator.mediaDevices.getUserMedia({ audio: true });
    return true;
  }catch{
    setDeviceMsg('Please allow microphone access to list audio outputs.');
    return false;
  }
}
function fillSelect(sel, outs){
  if (!sel) return;
  sel.innerHTML = '';
  outs.forEach(d=>{
    const opt = document.createElement('option');
    opt.value = d.deviceId;
    opt.textContent = d.label || `Output ${d.deviceId}`;
    sel.appendChild(opt);
  });
  const def = outs.find(d=>d.deviceId==='default');
  sel.value = def ? def.deviceId : (outs[0]?.deviceId || 'default');
}
function addDefaultFallback(sel){
  if (!sel) return;
  sel.innerHTML = '';
  const opt = document.createElement('option');
  opt.value='default'; opt.textContent='System default';
  sel.appendChild(opt); sel.value='default';
}
async function listOutputs(){
  const devices = await navigator.mediaDevices.enumerateDevices();
  const outs = devices.filter(d=>d.kind==='audiooutput');
  if (outs.length){ fillSelect(vocalsOut, outs); fillSelect(bandOut, outs); setDeviceMsg(`Found ${outs.length} output device(s).`); }
  else { addDefaultFallback(vocalsOut); addDefaultFallback(bandOut); setDeviceMsg('No discrete outputs reported. Using system default.'); }
  return outs.length;
}
initBtn?.addEventListener('click', async ()=>{
  setDeviceMsg('');
  if (!supportSink){ setDeviceMsg('Output selection not supported here. Use Chrome/Edge desktop.'); return; }
  if (!await ensurePermission()) return;
  const count = await listOutputs();
  initBtn.textContent = count ? 'Device list ready' : 'Device list (default only)';
  try{ navigator.mediaDevices.addEventListener('devicechange', listOutputs); }catch{}
});
async function applySinks(){
  if (!supportSink) return;
  try{ await vocalsEl?.setSinkId(vocalsOut?.value || 'default'); }catch{}
  try{ await bandEl?.setSinkId(bandOut?.value   || 'default'); }catch{}
}

function clearSyncTimer(){ if (window._syncTimer){ clearInterval(window._syncTimer); window._syncTimer=null; } }
function pauseAll(){
  clearSyncTimer();
  try{ vocalsEl?.pause(); }catch{}
  try{ bandEl?.pause(); }catch{}
  if (vocalsEl) vocalsEl.playbackRate = 1;
  if (bandEl)   bandEl.playbackRate   = 1;
  isPlaying = false;
}
async function preloadIfNeeded(){
  if (isLoaded) return;
  if (!vocalsUrl || !bandUrl || vocalsUrl === '#' || bandUrl === '#') throw new Error('No tracks loaded yet.');
  vocalsEl.src = vocalsUrl; bandEl.src = bandUrl;
  await applySinks();
  vocalsEl.load(); bandEl.load();
  await Promise.all([
    new Promise(r=>vocalsEl.addEventListener('canplay', r, { once:true })),
    new Promise(r=>bandEl.addEventListener('canplay',   r, { once:true })),
  ]);
  isLoaded = true;
}
function currentOffsetMs(){ return parseInt(offsetIn?.value || '0', 10) || 0; }
function startDriftCorrection(offsetMs){
  clearSyncTimer();
  window._syncTimer = setInterval(()=>{
    if (!isPlaying) return;
    const driftMs = (vocalsEl.currentTime - bandEl.currentTime) * 1000 - offsetMs;
    if (Math.abs(driftMs) > 60){
      if (driftMs > 0){
        const r=vocalsEl.playbackRate; vocalsEl.playbackRate=Math.max(0.9, r-0.05);
        setTimeout(()=>{ vocalsEl.playbackRate=r; }, 300);
      }else{
        const r=bandEl.playbackRate; bandEl.playbackRate=Math.max(0.9, r-0.05);
        setTimeout(()=>{ bandEl.playbackRate=r; }, 300);
      }
    }
  }, 2000);
}
async function resumePlay(){
  await Promise.all([ vocalsEl.play().catch(()=>{}), bandEl.play().catch(()=>{}) ]);
  isPlaying = true; startDriftCorrection(currentOffsetMs());
}
async function startFromZeroWithOffset(offsetMs){
  vocalsEl.currentTime = 0; bandEl.currentTime = 0;
  if (offsetMs >= 0){ await bandEl.play(); await sleep(offsetMs); await vocalsEl.play(); }
  else { await vocalsEl.play(); await sleep(-offsetMs); await bandEl.play(); }
  isPlaying = true; startDriftCorrection(offsetMs);
}

playBtn?.addEventListener('click', async ()=>{
  try{
    if (!vocalsEl || !bandEl) return;
    if (isPlaying) return;
    await preloadIfNeeded();
    if (vocalsEl.paused && bandEl.paused && (vocalsEl.currentTime>0 || bandEl.currentTime>0)){
      await resumePlay();
    }else{
      await startFromZeroWithOffset(currentOffsetMs());
    }
  }catch(e){
    console.warn('play failed', e);
    alert(e.message || 'Could not start playback.');
  }
});
pauseBtn?.addEventListener('click', pauseAll);
restartBtn?.addEventListener('click', async ()=>{
  try{
    await preloadIfNeeded(); pauseAll(); await startFromZeroWithOffset(currentOffsetMs());
  }catch(e){
    console.warn('restart failed', e);
    alert(e.message || 'Could not restart playback.');
  }
});

// ======= Beep tests =======
const _beepElVocals = document.createElement('audio');
const _beepElBand   = document.createElement('audio');
_beepElVocals.setAttribute('playsinline',''); _beepElVocals.style.display='none';
_beepElBand.setAttribute('playsinline','');   _beepElBand.style.display='none';
document.body.appendChild(_beepElVocals); document.body.appendChild(_beepElBand);

async function playBeep(which, sinkId, freq=880, ms=600){
  const supportSink = typeof HTMLMediaElement.prototype.setSinkId === 'function';
  if (!supportSink){ alert('Output selection not supported in this browser.'); return; }
  const outEl = which === 'band' ? _beepElBand : _beepElVocals;

  const ac = new (window.AudioContext||window.webkitAudioContext)();
  const osc = ac.createOscillator();
  const gain = ac.createGain();
  gain.gain.setValueAtTime(0.0001, ac.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.3, ac.currentTime + 0.02);

  osc.frequency.value = freq; osc.type='sine';
  const dest = ac.createMediaStreamDestination();
  osc.connect(gain); gain.connect(dest);

  try{ await outEl.setSinkId(sinkId || 'default'); }catch{}
  outEl.srcObject = dest.stream;

  try{
    osc.start();
    await outEl.play();
    const endT = ac.currentTime + ms/1000;
    gain.gain.exponentialRampToValueAtTime(0.0001, endT - 0.05);
    osc.stop(endT);
    setTimeout(()=>{ outEl.pause(); outEl.srcObject=null; ac.close().catch(()=>{}); }, ms+120);
  }catch{
    ac.close().catch(()=>{});
  }
}
document.getElementById('testVocals')?.addEventListener('click', ()=>playBeep('vocals', vocalsOut?.value, 880, 500));
document.getElementById('testBand')  ?.addEventListener('click', ()=>playBeep('band',   bandOut?.value,   660, 500));

// =================== (Optional) Player-Mode list logic ===================
// If you add a player listing page with meta[name="karaoke-list"], this section
// will populate and load items. It’s safe to keep here; it no-ops otherwise.
if (window.KARAOKE_MODE === 'player'){
  (function(){
    const LIST_META = document.querySelector('meta[name="karaoke-list"]');
    const LIST_URL  = LIST_META?.content || '';
    if (!LIST_URL) return;

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
      try{
        setListStatus('Loading songs…');
        const res = await fetch(LIST_URL, { mode: 'cors' });
        if (!res.ok) throw new Error(`List failed (${res.status})`);
        const data = await res.json();

        const items = (data && data.items) || [];
        if (pick) pick.innerHTML = '';
        if (!items.length){
          if (pick) pick.innerHTML = '<option value="">No completed songs yet</option>';
          setListStatus('');
          return;
        }

        items.sort((a,b)=> (b.updated||'').localeCompare(a.updated||''));

        for (const it of items){
          const opt = document.createElement('option');
          opt.value = JSON.stringify({ vocals: it.vocals_url, band: it.band_url, title: it.title || it.job_id });
          opt.textContent = it.title || it.job_id;
          pick?.appendChild(opt);
        }
        setListStatus(`Loaded ${items.length} song(s).`);
      }catch(e){
        console.warn(e);
        setListStatus('Could not load list. ' + (e.message || e));
      }
    }

    useBtn?.addEventListener('click', ()=>{
      const val = pick?.value; if (!val) return;
      try{
        const sel = JSON.parse(val);
        vocalsUrl = sel.vocals || '';
        bandUrl   = sel.band   || '';
        const tt = document.getElementById('trackTitle'); if (tt) tt.textContent = sel.title || 'Unknown Track';

        // reset playback state
        isLoaded = false; isPlaying = false; pauseAll();

        if (vocalsUrlIn) vocalsUrlIn.value = vocalsUrl;
        if (bandUrlIn)   bandUrlIn.value   = bandUrl;
        loadBtn?.click();
        if (loadStatus) loadStatus.textContent = 'Tracks loaded.';
      }catch(e){ console.warn('Invalid selection', e); }
    });

    refreshBtn?.addEventListener('click', loadList);
    loadList();
  })();
}