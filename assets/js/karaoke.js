/* assets/js/karaoke.js
   Upload + poll (submit page) and "player mode" listing (private storage via SAS).
   Robust against network hiccups; handles blob keys OR absolute URLs.
*/

// =================== CONFIG ===================
const API_BASE = 'https://karaoke-func-bthmcvafagcncmck.canadacentral-01.azurewebsites.net'; // your Function App
const FUNCTION_CODE = ''; // optional: '...'; leave '' if authLevel="anonymous"
const OUTPUT_BASE = ''; 
// ^ For private containers, leave ''. We'll use SAS URLs from /api/list or /status.
//   If you make the container public, set to: 'https://<account>.blob.core.windows.net/karaoke-output'

// Build endpoints
const submitUrl = `${API_BASE}/api/submit${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`;
const statusUrl = (jobId) =>
  `${API_BASE}/api/status/${encodeURIComponent(jobId)}${FUNCTION_CODE ? `?code=${FUNCTION_CODE}` : ''}`;

// =================== ELEMENTS (upload page) ===================
const els = {
  file: document.getElementById('file'),
  yt: document.getElementById('yt'),
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
let bandUrl = '';
let pollTimer = null;

// =================== HELPERS ===================
function setStatus(t) { if (els.status) els.status.textContent = t || ''; }
function showError(msg) { if (els.alert) { els.alert.textContent = msg; els.alert.classList.remove('hide'); } }
function hideError() { if (els.alert) { els.alert.classList.add('hide'); els.alert.textContent = ''; } }
function resetUI() {
  setStatus(''); hideError();
  if (els.done) els.done.classList.add('hide');
  if (els.links) els.links.innerHTML = '';
  if (els.prog) { els.prog.hidden = true; }
  if (els.bar) els.bar.style.width = '0%';
  if (els.playerCard) els.playerCard.classList.add('hide');
  vocalsUrl = bandUrl = '';
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function asUrl(valueOrKey) {
  // If backend returned a full URL (SAS), use as-is
  if (/^https?:\/\//i.test(valueOrKey)) return valueOrKey;
  // Otherwise treat it as a blob KEY and build from OUTPUT_BASE (requires public container)
  return OUTPUT_BASE ? `${OUTPUT_BASE.replace(/\/$/,'')}/${valueOrKey.replace(/^\/+/,'')}` : '#';
}

// =================== CLEAR ===================
if (els.clear) {
  els.clear.addEventListener('click', () => {
    if (els.file) els.file.value = '';
    if (els.yt) els.yt.value = '';
    resetUI();
  });
}

// =================== POLLING (upload page) ===================
async function doPoll(jobId) {
  try {
    const r = await fetch(statusUrl(jobId), { mode: 'cors' });
    if (r.status === 404) return; // status blob not ready yet
    const s = await r.json();

    if (s.state === 'queued') {
      setStatus('Queued…');
      if (els.prog) els.prog.hidden = false;
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

      if (els.done) els.done.classList.remove('hide');
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
      }
      return;
    }

    setStatus(s.state || '…');

  } catch (err) {
    console.warn('poll error', err); // transient; keep polling
  }
}

function startPolling(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => doPoll(jobId), 1500);
}

// =================== SUBMIT (upload page) ===================
if (els.go) {
  els.go.addEventListener('click', async () => {
    try {
      hideError(); if (els.done) els.done.classList.add('hide'); if (els.links) els.links.innerHTML = '';
      setStatus('Submitting…'); if (els.prog) els.prog.hidden = false; if (els.bar) els.bar.style.width = '10%';

      const fd = new FormData();
      if (els.file?.files[0]) fd.append('file', els.file.files[0]);           // MUST be 'file'
      if (els.yt?.value)      fd.append('youtube_url', els.yt.value.trim()); // MUST be 'youtube_url'
      if (!fd.has('file') && !fd.has('youtube_url')) throw new Error('Select a file or paste a YouTube link.');

      const res = await fetch(submitUrl, { method: 'POST', body: fd, mode: 'cors' });
      let data = null;
      try { data = await res.json(); } catch {}
      if (!res.ok) {
        const msg = (data && (data.error || data.message)) || (await res.text());
        throw new Error(msg || `Submit failed (${res.status})`);
      }
      const jobId = data && data.job_id;
      if (!jobId) throw new Error('No job id returned.');

      (window.dataLayer = window.dataLayer || []).push({ event: 'karaoke_submit' });
      setStatus('Queued. Processing…');
      startPolling(jobId);

    } catch (e) {
      showError(e.message || String(e));
      setStatus(''); if (els.prog) els.prog.hidden = true; if (els.bar) els.bar.style.width = '0%';
    }
  });
}

// =================== DUAL-OUTPUT ROUTING (both pages) ===================
const vocalsEl = document.getElementById('vocalsEl');
const bandEl   = document.getElementById('bandEl');
const vocalsOut= document.getElementById('vocalsOut');
const bandOut  = document.getElementById('bandOut');
const initBtn  = document.getElementById('initAudio');
const playBtn  = document.getElementById('play');
const pauseBtn = document.getElementById('pause');
const offsetIn = document.getElementById('offset');

async function ensurePermission() { try { await navigator.mediaDevices.getUserMedia({ audio: true }); } catch(e){} }
async function listOutputs() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const outs = devices.filter(d => d.kind === 'audiooutput');
  function fill(select) {
    if (!select) return;
    select.innerHTML = '';
    outs.forEach(d => {
      const opt = document.createElement('option');
      opt.value = d.deviceId; opt.textContent = d.label || `Output ${d.deviceId}`;
      select.appendChild(opt);
    });
    const def = outs.find(d => d.deviceId === 'default');
    if (def) select.value = def.deviceId;
  }
  fill(vocalsOut); fill(bandOut);
}
initBtn?.addEventListener('click', async () => {
  if (!('setSinkId' in HTMLMediaElement.prototype)) { alert('Your browser does not support selecting outputs (try Chrome/Edge desktop).'); return; }
  await ensurePermission(); await listOutputs();
  initBtn.textContent = 'Device list ready';
});
async function applySinks() {
  if (!('setSinkId' in HTMLMediaElement.prototype)) return;
  try { await vocalsEl?.setSinkId(vocalsOut?.value || ''); } catch(e){}
  try { await bandEl?.setSinkId(bandOut?.value || ''); } catch(e){}
}
function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }
async function playSynced(offsetMs=0) {
  if (!vocalsUrl || !bandUrl || vocalsUrl === '#' || bandUrl === '#') { alert('No tracks loaded yet.'); return; }
  if (!vocalsEl || !bandEl) return;
  vocalsEl.src = vocalsUrl; bandEl.src = bandUrl;
  await applySinks();

  await Promise.all([vocalsEl.play().catch(()=>{}), bandEl.play().catch(()=>{})]);
  vocalsEl.pause(); bandEl.pause();

  await Promise.all([
    new Promise(r => vocalsEl.addEventListener('canplay', r, {once:true})),
    new Promise(r => bandEl.addEventListener('canplay', r, {once:true})),
  ]);

  vocalsEl.currentTime = 0; bandEl.currentTime = 0;
  if (offsetMs >= 0) { await bandEl.play(); await sleep(offsetMs); await vocalsEl.play(); }
  else { await vocalsEl.play(); await sleep(-offsetMs); await bandEl.play(); }

  clearInterval(window._syncTimer);
  window._syncTimer = setInterval(() => {
    const driftMs = (vocalsEl.currentTime - bandEl.currentTime) * 1000 - offsetMs;
    if (Math.abs(driftMs) > 60) {
      if (driftMs > 0) { const r=vocalsEl.playbackRate; vocalsEl.playbackRate=Math.max(0.9,r-0.05); setTimeout(()=>vocalsEl.playbackRate=r,300);}
      else { const r=bandEl.playbackRate; bandEl.playbackRate=Math.max(0.9,r-0.05); setTimeout(()=>bandEl.playbackRate=r,300);}
    }
  }, 2000);
}
playBtn?.addEventListener('click',()=>playSynced(parseInt(offsetIn?.value||'0',10)));
pauseBtn?.addEventListener('click',()=>{clearInterval(window._syncTimer);vocalsEl?.pause();bandEl?.pause();});

// =================== PLAYER MODE: list & load via SAS ===================
if (window.KARAOKE_MODE === 'player') {
  (function(){
    const LIST_URL = document.querySelector('meta[name="karaoke-list"]')?.content || '';

    const pick = document.getElementById('songPick');
    const useBtn = document.getElementById('useSelection');
    const refreshBtn = document.getElementById('refreshList');
    const status = document.getElementById('listStatus');

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

        // newest first if timestamps present
        items.sort((a,b) => (b.updated||'').localeCompare(a.updated||''));

        for (const it of items) {
          // Store SAS links as JSON in option value
          const opt = document.createElement('option');
          opt.value = JSON.stringify({
            vocals: it.vocals_url, 
            band: it.band_url
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
        vocalsUrl = sel.vocals || '';
        bandUrl   = sel.band   || '';

        if (vocalsUrlIn) vocalsUrlIn.value = vocalsUrl;
        if (bandUrlIn)   bandUrlIn.value   = bandUrl;
        loadBtn?.click(); // your existing player loader will pick these up
        if (loadStatus) loadStatus.textContent = 'Tracks loaded.';
      } catch (e) {
        console.warn('Invalid selection', e);
      }
    });

    refreshBtn?.addEventListener('click', loadList);
    loadList();
  })();
}