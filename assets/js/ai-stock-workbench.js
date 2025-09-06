// === Endpoints (Anonymous auth) ===
const API_BASE     = "https://stocks-func-app.azurewebsites.net";
const UNIVERSE_URL = `${API_BASE}/api/universe`;
const RANK_URL     = `${API_BASE}/api/rank`;
const REFRESH_URL  = `${API_BASE}/api/refresh`;

// === Refresh key (for /api/refresh) ===
// If you rotate the key in App Settings (REFRESH_SHARED_KEY), update it here:
const REFRESH_KEY  = "Xc9v#4pLm2!b7QzR1t8w";

// ---- Elements ----
const els = {
  btnUniverse:    document.getElementById('btnUniverse'),
  statusUniverse: document.getElementById('statusUniverse'),
  tickers:        document.getElementById('tickers'),
  strategy:       document.getElementById('strategy'),
  horizonText:    document.getElementById('horizonText'),
  btnRank:        document.getElementById('btnRank'),
  statusRank:     document.getElementById('statusRank'),
  resultsTable:   document.getElementById('resultsTable'),
  resultsBody:    document.getElementById('resultsBody'),
  emptyMsg:       document.getElementById('emptyMsg'),
  // refresh UI (optional, safe if not present)
  btnRefresh:     document.getElementById('btnRefresh'),
  statusRefresh:  document.getElementById('statusRefresh'),
};

// ---- Helpers ----
function parseTickers(text){
  const raw = (text || "").toUpperCase();
  const parts = raw.split(/[\s,]+/)
                   .map(s => s.replace(/[^A-Z0-9.\-]/g,'').trim())
                   .filter(Boolean);
  return [...new Set(parts)];
}

// Horizon is OPTIONAL; normalize common shorthands
function normalizeHorizon(h){
  if(!h || !h.trim()) return "";
  let s = h.trim().toLowerCase();

  s = s
    .replace(/\byrs?\b/g, "years")
    .replace(/\by\b/g, "years")
    .replace(/\byears?\b/g, "years")
    .replace(/\bmos?\b/g, "months")
    .replace(/\bmon(?:ths?)?\b/g, "months")
    .replace(/\bm\b/g, "months")
    .replace(/\bd(?:ays?)?\b/g, "days")
    .replace(/\bday\b/g, "days");

  s = s.replace(/\s{2,}/g, " ").trim();

  const m2 = s.match(/^(\d+(?:\.\d+)?)(years|months|days)$/);
  if(m2) return `${m2[1]} ${m2[2]}`;

  const m = s.match(/^(\d+(?:\.\d+)?)\s*(years|months|days)$/);
  if(m) return `${m[1]} ${m[2]}`;

  if(/^\d+(?:\.\d+)?$/.test(s)) return `${s} years`;

  return s;
}

function renderRank(result){
  const data = result && result.ranked ? result.ranked : [];
  if(!data.length){
    els.resultsTable.style.display = 'none';
    els.emptyMsg.textContent = 'No results returned.';
    els.emptyMsg.style.display = 'block';
    return;
  }
  els.resultsBody.innerHTML = '';
  data.forEach((row, i) => {
    const tr = document.createElement('tr');
    const td = (t)=>{ const x=document.createElement('td'); x.textContent=(t ?? ''); return x; };
    tr.appendChild(td(i+1));
    tr.appendChild(td(row.ticker));
    tr.appendChild(td(typeof row.score === 'number' ? row.score.toFixed(2) : row.score));
    tr.appendChild(td(row.thesis));
    tr.appendChild(td(row.risks));
    tr.appendChild(td(row.suggested_action));
    els.resultsBody.appendChild(tr);
  });
  els.emptyMsg.style.display = 'none';
  els.resultsTable.style.display = 'table';
}

// ---- Actions ----
async function runUniverse(){
  if(els.statusUniverse) els.statusUniverse.textContent = 'Fetching universe…';
  if(els.btnUniverse) els.btnUniverse.disabled = true;
  try{
    const res = await fetch(UNIVERSE_URL, { method: 'GET' });
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const list = data.tickers || [];
    if(els.tickers) els.tickers.value = list.join(', ');
    if(els.statusUniverse) els.statusUniverse.textContent = `Loaded ${list.length} tickers. You can edit below.`;
  }catch(err){
    console.error(err);
    if(els.statusUniverse) els.statusUniverse.textContent = `Error: ${err.message}`;
  }finally{
    if(els.btnUniverse) els.btnUniverse.disabled = false;
  }
}

async function runRank(){
  const tickers = parseTickers(els.tickers?.value || "");
  if(!tickers.length){ alert('Please provide at least one ticker.'); return; }

  const strategy = els.strategy?.value || 'long_term';
  const horizonInput = normalizeHorizon(els.horizonText?.value || ""); // OPTIONAL

  // Build payload; include horizon ONLY if provided
  const body = { strategy, tickers };
  if(horizonInput) body.horizon = horizonInput;

  if(els.statusRank) els.statusRank.textContent = 'Ranking with AI…';
  if(els.btnRank) els.btnRank.disabled = true;
  try{
    const res = await fetch(RANK_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const payload = data.result || data;
    if(!(payload && (payload.ranked || (data.ok && data.result)))){
      throw new Error(data.error || 'Unexpected response format');
    }
    renderRank(payload);

    const strat = payload.strategy || strategy;
    const hz = payload.horizon || horizonInput || '';
    if(els.statusRank) els.statusRank.textContent = `Ranked by ${strat}${hz ? ` (horizon: ${hz})` : ''}.`;
  }catch(err){
    console.error(err);
    if(els.statusRank) els.statusRank.textContent = `Error: ${err.message}`;
  }finally{
    if(els.btnRank) els.btnRank.disabled = false;
  }
}

async function runRefresh(){
  if(!els.btnRefresh) return; // button not present on page
  if(els.statusRefresh) els.statusRefresh.textContent = 'Refreshing…';
  els.btnRefresh.disabled = true;
  try{
    const res = await fetch(REFRESH_URL, {
      method: 'POST',
      headers: { 'x-refresh-key': REFRESH_KEY }
    });
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json().catch(()=>({ ok:true }));
    if(els.statusRefresh) els.statusRefresh.textContent = data.ok ? 'Refresh complete.' : (data.message || 'Refreshed.');
    // Auto-fetch the new universe after a successful refresh:
    await runUniverse();
  }catch(err){
    console.error(err);
    if(els.statusRefresh) els.statusRefresh.textContent = `Error: ${err.message}`;
  }finally{
    els.btnRefresh.disabled = false;
  }
}

// ---- Wire buttons ----
els.btnUniverse?.addEventListener('click', runUniverse);
els.btnRank?.addEventListener('click', runRank);
els.btnRefresh?.addEventListener('click', runRefresh);