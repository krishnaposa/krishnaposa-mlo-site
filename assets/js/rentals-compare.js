(function(){
  const FN_BASE = 'https://rent-analyzer-fn-eheqhra2d6bwd6fm.canadacentral-01.azurewebsites.net';

  // DOM
  const form        = document.getElementById('portfolio-form');
  const err         = document.getElementById('err');
  const submitBtn   = document.getElementById('submitBtn');

  const addrSearch  = document.getElementById('addrSearch');
  const addrResults = document.getElementById('addrResults');
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

  // ---------------- Google Places (fallback-friendly) ----------------
  let sessionToken, oldAutocompleteService = null, oldPlacesService = null;
  function initPlaces(){
    if (!('google' in window) || !google.maps || !google.maps.places) return;
    oldAutocompleteService = new google.maps.places.AutocompleteService();
    oldPlacesService       = new google.maps.places.PlacesService(document.createElement('div'));
    newSessionToken();
  }
  function newSessionToken(){ sessionToken = new google.maps.places.AutocompleteSessionToken(); }

  function renderSuggestions(items){
    addrResults.innerHTML='';
    if(!items || !items.length){ addrResults.style.display='none'; addrSearch.setAttribute('aria-expanded','false'); return; }
    items.forEach(pred=>{
      const li=document.createElement('li');
      li.role='option'; li.tabIndex=0; li.style.cursor='pointer'; li.style.padding='8px';
      li.textContent = pred.description || '';
      li.addEventListener('click',()=> selectPrediction(pred));
      li.addEventListener('keydown',(e)=>{ if(e.key==='Enter') selectPrediction(pred); });
      addrResults.appendChild(li);
    });
    addrResults.style.display='block';
    addrSearch.setAttribute('aria-expanded','true');
  }

  function selectPrediction(pred){
    oldPlacesService.getDetails({
      placeId: pred.place_id,
      sessionToken,
      fields: ['formatted_address','address_components','geometry','name']
    }, (place, status)=>{
      if (status !== google.maps.places.PlacesServiceStatus.OK || !place) {
        showErr('Could not validate the address.'); return;
      }
      const { street, city, state, zip } = extractComponents(place.address_components);
      addPicked({
        label: place.formatted_address || [street || place.name || '', city, state, zip].filter(Boolean).join(', '),
        address: street || place.name || '', city, state, zip
      }, num(addrRent.value), num(addrPrice.value));
      afterPickReset();
    });
  }

  function extractComponents(components){
    const get=(t)=> (components||[]).find(c=>c.types.includes(t));
    const street=[get('street_number')?.long_name||'', get('route')?.long_name||''].filter(Boolean).join(' ').trim();
    const city  = get('locality')?.long_name || get('sublocality_level_1')?.long_name || '';
    const state = get('administrative_area_level_1')?.short_name || '';
    const zip   = get('postal_code')?.long_name || '';
    return { street, city, state, zip };
  }

  // Typeahead
  addrSearch.addEventListener('input', ()=>{
    hideErr();
    const q=(addrSearch.value||'').trim();
    if(!q || !oldAutocompleteService){ addrResults.style.display='none'; addrSearch.setAttribute('aria-expanded','false'); return; }
    oldAutocompleteService.getPlacePredictions({
      input:q, sessionToken, types:['address'], componentRestrictions:{ country:['us'] }
    }, (preds, status)=>{
      if (status !== google.maps.places.PlacesServiceStatus.OK) {
        addrResults.style.display='none'; addrSearch.setAttribute('aria-expanded','false'); return;
      }
      renderSuggestions(preds);
    });
  });

  // Manual add if autocomplete unused
  addrSearch.addEventListener('keydown', (e)=>{
    if (e.key === 'Enter') { e.preventDefault(); addManualCurrent(); }
  });
  addBtn.addEventListener('click', addManualCurrent);

  function addManualCurrent(){
    const label = (addrSearch.value||'').trim();
    const price = num(addrPrice.value);
    const rent  = num(addrRent.value);
    if (!label){ showErr('Enter an address to add.'); return; }
    if (!price){ showErr('Enter a purchase price for this address.'); return; }

    // quick parse for city/state/zip (best-effort only)
    const parts = label.split(/[\s,]+/);
    const zip   = parts.find(p=>/^\d{5}$/.test(p)) || '';
    const state = parts.find(p=>/^[A-Z]{2}$/i.test(p)) || '';
    const city  = ''; // optional — you asked to hide city/state/zip in table

    addPicked({ label, address: label, city, state, zip }, rent, price);
    afterPickReset();
  }

  function afterPickReset(){
    addrSearch.value=''; addrRent.value=''; addrPrice.value='';
    addrResults.innerHTML=''; addrResults.style.display='none';
    addrSearch.setAttribute('aria-expanded','false');
    newSessionToken();
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

    // optional prefetch (adds taxes/expenses/appreciation when possible)
    const prefetch = await maybePrefetch(picked, price);

    const inputs = {
      address: picked.address, city: picked.city, state: picked.state, zip: picked.zip,
      propertyType: '', units: 1, purchasePrice: price,
      downPct: shared.downPct, rate: shared.rate, termYears: shared.termYears,
      closingCosts: shared.closingCosts, pointsPct: shared.pointsPct,
      rent: Number(picked.rent || (prefetch?.ai?.rent?.est || 0)),
      otherIncome: 0, vacancyPct: shared.vacancyPct
    };

    // NOTE: Correct endpoint name per your note
    const analyzed = await postJSON(`${FN_BASE}/api/rent-analyzer`, { inputs, prefetch });
    analyzed.prefetch = prefetch || null;
    return analyzed;
  }

  // ---------------- Render ranked table + sorting ----------------
  let lastResults = [];  // keep the full results for client-side resort
  let lastOrder   = null;

  function derive5yTotalReturn(item){
    // Primary: model metric if present
    const direct = Number(item.metrics?.totalReturnPctProjected ?? NaN);
    if (!Number.isNaN(direct)) return direct;

    // Fallbacks from prefetch appreciation (shape may vary)
    const appr = item.prefetch?.ai?.appreciation || null;
    if (appr) {
      // common shapes seen in earlier code: { horizon_years:[1,3,5], pct:[...]} or keyed
      if (Array.isArray(appr.horizon_years) && Array.isArray(appr.pct)) {
        const idx = appr.horizon_years.findIndex((y)=> Number(y) === 5);
        if (idx >= 0 && Number.isFinite(Number(appr.pct[idx]))) return Number(appr.pct[idx]) * 100;
      }
      if (Array.isArray(appr.pct_5y) && appr.pct_5y.length) {
        return Number(appr.pct_5y[0]) * 100;
      }
      if (typeof appr.pct_5y === 'number') {
        return Number(appr.pct_5y) * 100;
      }
      if (typeof appr.total_return_5y === 'number') {
        return Number(appr.total_return_5y) * 100;
      }
    }
    // If nothing, show 0 (still sortable)
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
  let sortState = { key: 'rank', dir: 'asc' }; // dir: 'asc' | 'desc'

  function applySort(key){
    if (!lastResults.length) return;

    // Build array of {idx, item} to preserve link to original order for rank display
    const arr = (lastOrder ? lastOrder : lastResults.map((_,i)=> i)).map(idx => ({ idx, item: lastResults[idx] }));

    const getField = (obj) => {
      switch (key) {
        case 'rank': return arr.indexOf(obj); // initial row order
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

    // Render in sorted order
    const newOrder = arr.map(x => x.idx);
    renderTable(lastResults, newOrder, { ok: !!lastOrder }); // preserve note behavior
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
        // Simple visual arrow cue
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

      // Rank on server; fall back client-side
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

  // Expose for Google callback
  window.initPortfolioPlaces = initPlaces;
})();