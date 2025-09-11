// Set your Azure Function base URL
const API_BASE = 'https://<YOUR-FUNCTION-APP>.azurewebsites.net';

// Elements
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

let vocalsUrl = "";
let bandUrl   = "";

// Clear form
els.clear.addEventListener('click', () => {
  els.file.value = '';
  els.yt.value = '';
  els.status.textContent = '';
  els.alert.classList.add('hide');
  els.done.classList.add('hide');
  els.links.innerHTML = '';
  els.playerCard.classList.add('hide');
  vocalsUrl = bandUrl = "";
});

// Poll job status
async function pollStatus(jobId) {
  els.status.textContent = 'Processing… (1–3 minutes for long tracks)';
  els.prog.hidden = false; els.bar.style.width = '20%';
  while (true) {
    const r = await fetch(`${API_BASE}/api/status/${jobId}`);
    if (r.status === 404) { await new Promise(r => setTimeout(r, 1500)); continue; }
    const s = await r.json();
    if (s.state === 'done') {
      els.status.textContent = 'Done!';
      els.bar.style.width = '100%';
      setTimeout(()=>{ els.prog.hidden = true; els.bar.style.width='0%'; }, 1000);

      els.done.classList.remove('hide');
      els.links.innerHTML = '';
      for (const [name, url] of Object.entries(s.outputs || {})) {
        const li = document.createElement('li');
        const a = document.createElement('a'); a.href = url; a.textContent = name; a.download = name;
        li.appendChild(a); els.links.appendChild(li);
      }

      // Capture URLs for in-page playback
      vocalsUrl = (s.outputs || {})["vocals.wav"] || "";
      bandUrl   = (s.outputs || {})["no_vocals.wav"] || "";
      if (vocalsUrl && bandUrl) els.playerCard.classList.remove('hide');
      return;
    } else if (s.state === 'failed') {
      els.alert.textContent = s.error || 'Job failed';
      els.alert.classList.remove('hide');
      els.status.textContent = '';
      els.prog.hidden = true; els.bar.style.width = '0%';
      return;
    } else {
      els.bar.style.width = (Math.min(95, parseInt(els.bar.style.width||'20')+5)) + '%';
      await new Promise(r => setTimeout(r, 2000));
    }
  }
}

// Submit
els.go.addEventListener('click', async () => {
  try {
    els.alert.classList.add('hide');
    els.done.classList.add('hide');
    els.links.innerHTML = '';
    els.status.textContent = 'Submitting…';
    els.prog.hidden = false; els.bar.style.width = '10%';

    const fd = new FormData();
    if (els.file.files[0]) fd.append('file', els.file.files[0]);
    if (els.yt.value) fd.append('youtube_url', els.yt.value);
    if (!fd.has('file') && !fd.has('youtube_url')) throw new Error('Select a file or paste a YouTube link.');

    const res = await fetch(`${API_BASE}/api/submit`, { method:'POST', body:fd });
    if (!res.ok) throw new Error(await res.text());
    const { job_id } = await res.json();
    if (!job_id) throw new Error('No job id returned');

    (window.dataLayer = window.dataLayer || []).push({event:'karaoke_submit'});
    pollStatus(job_id);
  } catch (e) {
    els.alert.textContent = e.message || String(e);
    els.alert.classList.remove('hide');
    els.status.textContent = '';
    els.prog.hidden = true; els.bar.style.width = '0%';
  }
});

// ====== Dual-output routing ======
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
    select.innerHTML = "";
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
initBtn.addEventListener('click', async () => {
  if (!('setSinkId' in HTMLMediaElement.prototype)) { alert('Your browser does not support selecting outputs (try Chrome/Edge desktop).'); return; }
  await ensurePermission(); await listOutputs();
  initBtn.textContent = 'Device list ready';
});
async function applySinks() {
  if (!('setSinkId' in HTMLMediaElement.prototype)) return;
  try { await vocalsEl.setSinkId(vocalsOut.value); } catch(e){}
  try { await bandEl.setSinkId(bandOut.value); } catch(e){}
}
function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }
async function playSynced(offsetMs=0) {
  if (!vocalsUrl || !bandUrl) { alert('No tracks loaded yet.'); return; }
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
    const driftMs = (vocalsEl.currentTime - bandEl.currentTime)*1000 - offsetMs;
    if (Math.abs(driftMs) > 60) {
      if (driftMs > 0) { let r=vocalsEl.playbackRate; vocalsEl.playbackRate=Math.max(0.9,r-0.05); setTimeout(()=>vocalsEl.playbackRate=r,300);}
      else { let r=bandEl.playbackRate; bandEl.playbackRate=Math.max(0.9,r-0.05); setTimeout(()=>bandEl.playbackRate=r,300);}
    }
  },2000);
}
playBtn.addEventListener('click',()=>playSynced(parseInt(offsetIn.value||'0',10)));
pauseBtn.addEventListener('click',()=>{clearInterval(window._syncTimer);vocalsEl.pause();bandEl.pause();});