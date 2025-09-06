// === Hard-wired endpoints (Anonymous auth, no key needed) ===
const API_BASE = "https://stocks-func-app.azurewebsites.net";
const UNIVERSE_URL = `${API_BASE}/api/universe`;
const RANK_URL     = `${API_BASE}/api/rank`;

// ---- Elements ----
const els = {
  btnUniverse:  document.getElementById('btnUniverse'),
  statusUniverse: document.getElementById('statusUniverse'),
  tickers:      document.getElementById('tickers'),
  strategy:     document.getElementById('strategy'),
  horizonText:  document.getElementById('horizonText'),
  btnRank:      document.getElementById('btnRank'),
  statusRank:   document.getElementById('statusRank'),
  resultsTable: document.getElementById('resultsTable'),
  resultsBody:  document.getElementById('resultsBody'),
  emptyMsg:     document.getElementById('emptyMsg'),
};

// ---- Helpers ----
function parseTickers(text){
  const raw = (text || "").toUpperCase();
  const parts = raw.split(/[\s,]+/).map(s => s.replace(/[^A-Z0-9.\-]/g,'').trim()).filter(Boolean);
  return [...new Set(parts)];
}

// Normalize common abbreviations into canonical strings
function normalizeHorizon(h){
  if(!h || !h.trim()) return ""; // OPTIONAL now
  let s = h.trim().toLowerCase();

  // Abbreviations -> canonical
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

  // "3years" -> "3 years"
  const m2 = s.match(/^(\d+(?:\.\d+)?)(years|months|days)$/);
  if(m2) return `${m2[1]} ${m2[2]}`;

  // "3 years" / "8 months" / "30 days"
  const m = s.match(/^(\d+(?:\.\d+)?)\s*(years|months|days)$/);
  if(m) return `${m[1]} ${m[2]}`;

  // Just a number? interpret as years
  if(/^\d+(?:\.\d+)?$/.test(s)) return `${s} years`;

  // Otherwise pass through
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
  els.statusUniverse.textContent = 'Fetching universe…';
  els.btnUniverse.disabled = true;
  try{
    const res = await fetch(UNIVERSE_URL, { method: 'GET' });
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const list = data.tickers || [];
    els.tickers.value = list.join(', ');
    els.statusUniverse.textContent = `Loaded ${list.length} tickers. You can edit below.`;
  }catch(err){
    console.error(err);
    els.statusUniverse.textContent = `Error: ${err.message}`;
  }finally{
    els.btnUniverse.disabled = false;
  }
}

async function runRank(){
  const tickers = parseTickers(els.tickers.value);
  if(!tickers.length){ alert('Please provide at least one ticker.'); return; }

  const strategy = els.strategy.value;
  const horizonInput = normalizeHorizon(els.horizonText.value || ""); // OPTIONAL

  // Build payload; include horizon ONLY if provided
  const body = { strategy, tickers };
  if(horizonInput) body.horizon = horizonInput;

  els.statusRank.textContent = 'Ranking with AI…';
  els.btnRank.disabled = true;
  try{
    const res = await fetch(RANK_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const payload = data.result || data; // support either shape
    if(!(payload && (payload.ranked || (data.ok && data.result)))){
      throw new Error(data.error || 'Unexpected response format');
    }
    renderRank(payload);

    const strat = payload.strategy || strategy;
    const hz = payload.horizon || horizonInput || '';
    els.statusRank.textContent = `Ranked by ${strat}${hz ? ` (horizon: ${hz})` : ''}.`;
  }catch(err){
    console.error(err);
    els.statusRank.textContent = `Error: ${err.message}`;
  }finally{
    els.btnRank.disabled = false;
  }
}

// ---- Wire buttons ----
document.getElementById('btnUniverse')?.addEventListener('click', runUniverse);
document.getElementById('btnRank')?.addEventListener('click', runRank);