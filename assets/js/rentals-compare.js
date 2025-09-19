(function(){
  const FN_BASE = 'https://rent-analyzer-fn-eheqhra2d6bwd6fm.canadacentral-01.azurewebsites.net';

  // DOM
  const form        = document.getElementById('portfolio-form');
  const err         = document.getElementById('err');
  const submitBtn   = document.getElementById('submitBtn');

  const addrSearch  = document.getElementById('addrSearch');
  const addrResults = document.getElementById('addrResults'); // no-op in manual mode
  const addrRent    = document.getElementById('addrRent');
  const addrPrice   = document.getElementById('addrPrice');
  const addBtn      = document.getElementById('addAddressBtn');
  const clearBtn    = document.getElementById('clearSearch');

  const pickedCount = document.getElementById('pickedCount');
  const pickedTableBody = document.querySelector('#pickedTable tbody');
  const pickedRowTpl    = document.getElementById('pickedRowTpl');

  const portRes   = document.getElementById('portfolioResult');
  const portNote  = document.getElementById('portfolioNote');
  const portTbl   = document.querySelector('#portfolioTable tbody');
  const portHead  = document.querySelector('#portfolioTable thead');

  // helpers
  const dollars = (n)=> Number(n||0).toLocaleString(undefined,{style:'currency',currency:'USD'});
  const pct     = (n, d=2)=> `${Number(n||0).toFixed(d)}%`;
  const num     = (v)=> { const x = Number(v); return Number.isFinite(x) ? x : 0; };
  function showErr(m){ err.textContent = m; err.style.display = 'block'; }
  function hideErr(){ err.style.display = 'none'; }

  // ---------------- Places (NEW only, optional) / Manual mode by default ----------------
  // We do NOT touch legacy classes, so there are no console warnings.
  let NewAutocompleteSuggestion = null;
  let sessionToken = null;

  function initPlaces(){
    try {
      NewAutocompleteSuggestion = window.google?.maps?.places?.AutocompleteSuggestion || null;
      if (NewAutocompleteSuggestion && window.google?.maps?.places?.AutocompleteSessionToken) {
        sessionToken = new google.maps.places.AutocompleteSessionToken();
      }
    } catch { /* stay in manual mode */ }
  }
  window.initPortfolioPlaces = initPlaces; // safe even if script tag calls it

  // If you later want to wire suggestions with the NEW API, you can;
  // for now we keep manual mode to stay 100% warning-free.
  addrSearch.addEventListener('input', ()=>{
    // hide dropdown in manual mode
    addrResults.style.display='none';
    addrSearch.setAttribute('aria-expanded','false');
  });

  // Manual add (Enter or Add button)
  addrSearch.addEventListener('keydown', (e)=>{
    if (e.key === 'Enter') { e.preventDefault(); addManualCurrent(); }
  });
  addBtn.addEventListener('click', addManualCurrent);

  function parseCityStateZip(label){
    // Try to find ZIP (last 5 digits) and STATE (2 letters just before ZIP or anywhere in tail)
    const zipMatch = label.match(/(\d{5})(?:-\d{4})?\s*$/);
    const zip = zipMatch ? zipMatch[1] : '';

    // Look for a 2-letter token before ZIP or near the end
    let state = '';
    if (zipMatch) {
      const head = label.slice(0, zipMatch.index).trim();
      const tailTokens = head.split(/[\s,]+/);
      for (let i = tailTokens.length - 1; i >= 0; i--) {
        if (/^[A-Za-z]{2}$/.test(tailTokens[i])) { state = tailTokens[i].toUpperCase(); break; }
      }
    } else {
      const tokens = label.split(/[\s,]+/);
      for (let i = tokens.length - 1; i >= 0; i--) {
        if (/^[A-Za-z]{2}$/.test(tokens[i])) { state = tokens[i].toUpperCase(); break; }
      }
    }

    // City is optional for the API, but try to infer a best-effort city
    let city = '';
    if (state) {
      // Grab token sequence right before state, up to a comma
      const parts = label.split(',');
      // use the part that contains the state to find the previous comma chunk as city
      const stateIdx = parts.findIndex(p => new RegExp(`\\b${state}\\b`, 'i').test(p));
      if (stateIdx > 0) city = parts[stateIdx - 1].trim();
    }
    return { city, state, zip };
  }

  function addManualCurrent(){
    const label = (addrSearch.value||'').trim();
    const price = num(addrPrice.value);
    const rent  = num(addrRent.value);
    if (!label){ showErr('Enter an address to add.'); return; }
    if (!price){ showErr('Enter a purchase price for this address.'); return; }

    const { city, state, zip } = parseCityStateZip(label);
    addPicked({ label, address: label, city, state, zip }, rent, price);
    afterPickReset();
  }

  function afterPickReset(){
    addrSearch.value=''; addrRent.value=''; addrPrice.value='';
    addrResults.innerHTML=''; addrResults.style.display='none';
    addrSearch.setAttribute('aria-expanded','false');
  }
  clearBtn.addEventListener('click', afterPickReset);

  // ---------------- Picked list table ----------------
  function pickedItems(){
    return Array.from(pickedTableBody.querySelectorAll('tr[data-item]')).map((row)=>({
      label: row.querySelector('[data-label]')?.textContent || '',
      address: row.dataset.address || '',
      city: row.dataset.city || '',
      state: row.dataset.state || '',
      zip: row.dataset.zip || '',
      rent: Number(row.dataset.rent || 0),
      price: Number(row.dataset.price || 0)
    }));
  }

  function addPicked(addr, rent, price){
    const count = pickedTableBody.querySelectorAll('tr[data-item]').length;
    if (count >= 10){ showErr('You can add up to 10 properties.'); return; }

    const node = pickedRowTpl.content.firstElementChild.cloneNode(true);
    node.querySelector('[data-label]').textContent = addr.label;
    node.querySelector('[data-rent-readonly]').textContent  = dollars(rent || 0);
    node.querySelector('[data-price-readonly]').textContent = dollars(price || 0);

    node.dataset.address = addr.address || '';
    node.dataset.city    = addr.city    || '';
    node.dataset.state   = addr.state   || '';
    node.dataset.zip     = addr.zip     || '';
    node.dataset.rent    = String(rent || 0);
    node.dataset.price   = String(price || 0);

    node.querySelector('[data-remove]').addEventListener('click', ()=>{
      node.remove(); updatePickedCountAndIndex();
    });

    pickedTableBody.appendChild(node);
    updatePickedCountAndIndex();
  }

  function updatePickedCountAndIndex(){
    const rows = Array.from(pickedTableBody.querySelectorAll('tr[data-item]'));
    rows.forEach((row, idx)=> { const idxCell = row.querySelector('[data-idx]'); if (idxCell) idxCell.textContent = String(idx+1); });
    pickedCount.textContent = `${rows.length} of 10 selected`;
  }

  // ---------------- Server calls ----------------
  async function postJSON(url, body){
    const res = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
    if (!res.ok){ const t = await res.text().catch(()=> ''); throw new Error(t || `Request failed: ${res.status}`); }
    return res.json();
  }

  async function maybePrefetch(picked, price){
    // rent-prefetch requires at least state or zip — call only if we have one
    const hasLocation = !!(picked.state || picked.zip);
    if (!hasLocation) return null;
    try{
      return await postJSON(`${FN_BASE}/api/rent-prefetch`, {
        inputs: {
          address: picked.address, city: picked.city, state: picked.state, zip: picked.zip,
          propertyType: '', units: 1, purchasePrice: price, ownerOccupied: false
        }
      });
    } catch {
      return null;
    }
  }

  async function analyzeOne(shared, picked){
    const price = Number(picked.price || 0);
    if (!price) throw new Error(`Missing price for: ${picked.label}`);

    const prefetch = await maybePrefetch(picked, price);

    const inputs = {
      address: picked.address, city: picked.city, state: picked.state, zip: picked.zip,
      propertyType: '', units: 1, purchasePrice: price,
      downPct: shared.downPct, rate: shared.rate, termYears: shared.termYears,
      closingCosts: shared.closingCosts, pointsPct: shared.pointsPct,
      rent: Number(picked.rent || (prefetch?.ai?.rent?.est || 0)),
      otherIncome: 0, vacancyPct: shared.vacancyPct
    };

    const analyzed = await postJSON(`${FN_BASE}/api/rent-analyzer`, { inputs, prefetch });
    analyzed.prefetch = prefetch || null;
    return analyzed;
  }

  // ---------------- Render ranked table + sorting ----------------
  let lastResults = [];
  let lastOrder   = null;

  function derive5yTotalReturn(item){
    const direct = Number(item.metrics?.totalReturnPctProjected ?? NaN);
    if (!Number.isNaN(direct)) return direct;

    const appr = item.prefetch?.ai?.appreciation || null;
    if (appr) {
      if (Array.isArray(appr.horizon_years) && Array.isArray(appr.pct)) {
        const idx = appr.horizon_years.findIndex((y)=> Number(y) === 5);
        if (idx >= 0 && Number.isFinite(Number(appr.pct[idx]))) return Number(appr.pct[idx]) * 100;
      }
      if (Array.isArray(appr.pct_5y) && appr.pct_5y.length) return Number(appr.pct_5y[0]) * 100;
      if (typeof appr.pct_5y === 'number')  return Number(appr.pct_5y) * 100;
      if (typeof appr.total_return_5y === 'number') return Number(appr.total_return_5y) * 100;
    }
    return 0;
  }

  function renderTable(results, order, aiMeta){
    lastResults = results.slice();
    lastOrder   = Array.isArray(order) ? order.slice() : null;

    portTbl.innerHTML = '';
    const list = lastOrder ? lastOrder.map(i=> lastResults[i]) : lastResults;

    list.forEach((r, i)=>{
      const addr = r.address || [r.inputs?.address, r.inputs?.city, r.inputs?.state, r.inputs?.zip].filter(Boolean).join(', ');
      const tr = document.createElement('tr');

      const fiveY = derive5yTotalReturn(r); // %
      tr.innerHTML = `
        <td>${i+1}</td>
        <td style="max-width:520px; white-space:normal">${addr}</td>
        <td>${dollars(r.metrics?.price)}</td>
        <td>${dollars(r.inputs?.rent || r.prefetch?.ai?.rent?.est || 0)}</td>
        <td>${dollars(r.metrics?.cashFlowMonthly)}</td>
        <td>${Number(r.metrics?.capRate||0).toFixed(2)}%</td>
        <td>${Number(r.metrics?.cashOnCash||0).toFixed(1)}%</td>
        <td>${Number(r.metrics?.dscr||0).toFixed(2)}</td>
        <td>${Number(fiveY||0).toFixed(1)}%</td>`;
      portTbl.appendChild(tr);
    });

    portNote.textContent = aiMeta?.ok
      ? (aiMeta.summary ? `Ranked by AI · ${aiMeta.summary}` : 'Ranked by AI (investment attractiveness).')
      : 'AI ranking unavailable — sorted by Cash-on-Cash then Monthly Cash Flow.';
    portRes.style.display = 'block';
  }

  // Sorting
  let sortState = { key: 'rank', dir: 'asc' };

  function applySort(key){
    if (!lastResults.length) return;
    const arr = (lastOrder ? lastOrder : lastResults.map((_,i)=> i)).map(idx => ({ idx, item: lastResults[idx] }));

    const getField = (obj) => {
      switch (key) {
        case 'rank': return arr.indexOf(obj);
        case 'address':
          return (obj.item.address || [obj.item.inputs?.address, obj.item.inputs?.city, obj.item.inputs?.state, obj.item.inputs?.zip].filter(Boolean).join(', ')).toLowerCase();
        case 'price': return Number(obj.item.metrics?.price || 0);
        case 'rent': return Number(obj.item.inputs?.rent || obj.item.prefetch?.ai?.rent?.est || 0);
        case 'cash_flow_monthly': return Number(obj.item.metrics?.cashFlowMonthly || 0);
        case 'cap_rate': return Number(obj.item.metrics?.capRate || 0);
        case 'cash_on_cash': return Number(obj.item.metrics?.cashOnCash || 0);
        case 'dscr': return Number(obj.item.metrics?.dscr || 0);
        case 'total_return_5y': return Number(derive5yTotalReturn(obj.item) || 0);
        default: return 0;
      }
    };

    arr.sort((a,b)=>{
      const va = getField(a), vb = getField(b);
      if (typeof va === 'string' || typeof vb === 'string') {
        return sortState.dir === 'asc' ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
      }
      return sortState.dir === 'asc' ? (va - vb) : (vb - va);
    });

    const newOrder = arr.map(x => x.idx);
    renderTable(lastResults, newOrder, { ok: !!lastOrder });
  }

  function attachSortHandlers(){
    if (!portHead) return;
    portHead.querySelectorAll('th[data-sort]').forEach(th=>{
      th.style.cursor = 'pointer';
      th.addEventListener('click', ()=>{
        const key = th.getAttribute('data-sort');
        if (sortState.key === key) {
          sortState.dir = (sortState.dir === 'asc' ? 'desc' : 'asc');
        } else {
          sortState.key = key;
          sortState.dir = 'asc';
        }
        applySort(sortState.key);
        portHead.querySelectorAll('.sort-arrow').forEach(el=> el.textContent = '');
        th.querySelector('.sort-arrow').textContent = sortState.dir === 'asc' ? '▲' : '▼';
      });
    });
  }
  attachSortHandlers();

  // ---------------- Submit ----------------
  form.addEventListener('submit', async (e)=>{
    e.preventDefault(); hideErr(); portRes.style.display='none'; portTbl.innerHTML='';

    try{
      if (!document.getElementById('consent').checked) throw new Error('Please accept the educational-only consent.');
      const shared = {
        downPct:num(document.getElementById('downPct').value),
        rate:num(document.getElementById('rate').value),
        termYears:num(document.getElementById('termYears').value),
        closingCosts:num(document.getElementById('closingCosts').value),
        pointsPct:num(document.getElementById('pointsPct').value),
        vacancyPct:num(document.getElementById('vacancyPct').value || 5)
      };
      if (!shared.downPct || !shared.rate || !shared.termYears) throw new Error('Down %, Rate, and Term are required.');

      const items = pickedItems();
      if (!items.length) throw new Error('Please add at least one address.');
      if (items.length > 10) throw new Error('Up to 10 properties supported.');
      if (items.some(x => !x.price)) throw new Error('Each address needs a purchase price.');

      submitBtn.disabled = true; submitBtn.textContent = 'Analyzing…';

      const results = [];
      for (const p of items){
        results.push(await analyzeOne(shared, p));
      }

      try{
        const rankResp = await postJSON(`${FN_BASE}/api/portfolio-rank`, { items: results, aiMode: 'auto' });
        const order = Array.isArray(rankResp.order) ? rankResp.order : null;
        renderTable(results, order, { ok: !!rankResp.ok, summary: rankResp.summary });
      } catch {
        const idx = results.map((_, i)=> i);
        idx.sort((i, j)=>{
          const a = results[i].metrics||{}, b = results[j].metrics||{};
          const c1 = Number(a.cashOnCash||0), c2 = Number(b.cashOnCash||0);
          if (c2 !== c1) return c2 - c1;
          const f1 = Number(a.cashFlowMonthly||0), f2 = Number(b.cashFlowMonthly||0);
          return f2 - f1;
        });
        renderTable(results, idx, { ok:false, summary:'' });
      }

      // default sort indicator to AI rank (#)
      const thRank = portHead.querySelector('th[data-sort="rank"] .sort-arrow');
      if (thRank) thRank.textContent = '▲';
      sortState = { key: 'rank', dir: 'asc' };

      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event:'portfolio_analyzer_submit', count: items.length });

    } catch (ex){
      showErr(ex.message || 'Something went wrong.');
    } finally {
      submitBtn.disabled = false; submitBtn.textContent = 'Analyze & Rank';
    }
  });
})();