(function(){
  const FN_BASE = 'https://rent-analyzer-fn-eheqhra2d6bwd6fm.canadacentral-01.azurewebsites.net';

  // ----- DOM -----
  const form        = document.getElementById('portfolio-form');
  const err         = document.getElementById('err');
  const submitBtn   = document.getElementById('submitBtn');

  const addrSearch  = document.getElementById('addrSearch');
  const addrResults = document.getElementById('addrResults');
  const addrRent    = document.getElementById('addrRent');
  const addBtn      = document.getElementById('addAddressBtn');
  const clearBtn    = document.getElementById('clearSearch');
  const pickedCount = document.getElementById('pickedCount');

  const pickedTableBody = document.querySelector('#pickedTable tbody');
  const pickedRowTpl    = document.getElementById('pickedRowTpl');

  const portRes   = document.getElementById('portfolioResult');
  const portNote  = document.getElementById('portfolioNote');
  const portTbl   = document.querySelector('#portfolioTable tbody');

  // Sort UI
  const tableHead = document.querySelector('#portfolioTable thead');

  // ----- Utils -----
  const dollars = (n)=> Number(n||0).toLocaleString(undefined,{style:'currency',currency:'USD'});
  const num     = (v)=> { const x = Number(v); return Number.isFinite(x) ? x : 0; };
  function showErr(m){ err.textContent = m; err.style.display = 'block'; }
  function hideErr(){ err.style.display = 'none'; }

  // Keep last results in memory for sorting without re-calling the API
  const state = {
    results: [],
    order: null,
    aiMeta: null,
    sort: { key: 'rank', dir: 'asc' } // default shows AI order (we transform to rank=1..N)
  };

  // ---------- Google Places (new-first, fallback-old) ----------
  let sessionToken, AutocompleteSuggestion = null, oldAutocompleteService = null, oldPlacesService = null;

  function initPlaces(){
    if (!('google' in window) || !google.maps || !google.maps.places) return;
    AutocompleteSuggestion   = google.maps.places.AutocompleteSuggestion || null;
    oldAutocompleteService   = new google.maps.places.AutocompleteService();
    oldPlacesService         = new google.maps.places.PlacesService(document.createElement('div'));
    newSessionToken();
  }
  function newSessionToken(){ sessionToken = new google.maps.places.AutocompleteSessionToken(); }

  function renderSuggestions(items){
    addrResults.innerHTML='';
    if(!items || !items.length){ addrResults.style.display='none'; addrSearch.setAttribute('aria-expanded','false'); return; }
    items.forEach(pred=>{
      const li=document.createElement('li');
      li.role='option'; li.tabIndex=0; li.style.cursor='pointer'; li.style.padding='8px';
      li.textContent = pred.formattedSuggestion || pred.description || pred.text || '';
      li.addEventListener('click',()=> selectPrediction(pred));
      li.addEventListener('keydown',(e)=>{ if(e.key==='Enter') selectPrediction(pred); });
      addrResults.appendChild(li);
    });
    addrResults.style.display='block';
    addrSearch.setAttribute('aria-expanded','true');
  }

  async function selectPrediction(pred){
    try {
      // NEW API path
      if (pred && typeof pred.fetchFields === 'function') {
        const { placePrediction } = await pred.fetchFields({
          fields: ['formatted_address','address_components','geometry','name']
        });
        return addPlaceFromNew(placePrediction);
      }
      // OLD API
      oldPlacesService.getDetails({
        placeId: pred.place_id,
        sessionToken,
        fields: ['formatted_address','address_components','geometry','name']
      }, (place, status)=>{
        if (status !== google.maps.places.PlacesServiceStatus.OK || !place) {
          showErr('Could not validate the address.'); return;
        }
        addPlaceFromOld(place);
      });
    } catch (e) {
      console.error(e);
      showErr('Error fetching place details.');
    }
  }

  function extractComponents(components){
    const get=(t)=> (components||[]).find(c=>c.types.includes(t));
    const street=[get('street_number')?.long_name||'', get('route')?.long_name||''].filter(Boolean).join(' ').trim();
    const city  = get('locality')?.long_name || get('sublocality_level_1')?.long_name || '';
    const state = get('administrative_area_level_1')?.short_name || '';
    const zip   = get('postal_code')?.long_name || '';
    return { street, city, state, zip };
  }
  function addPlaceFromNew(place){
    if (!place){ showErr('Could not validate the address.'); return; }
    const { street, city, state, zip } = extractComponents(place.address_components);
    addPicked({
      label: place.formatted_address || [street || place.name || '', city, state, zip].filter(Boolean).join(', '),
      address: street || place.name || '', city, state, zip
    }, num(addrRent.value));
    afterPickReset();
  }
  function addPlaceFromOld(place){
    const { street, city, state, zip } = extractComponents(place.address_components);
    addPicked({
      label: place.formatted_address || [street || place.name || '', city, state, zip].filter(Boolean).join(', '),
      address: street || place.name || '', city, state, zip
    }, num(addrRent.value));
    afterPickReset();
  }
  function afterPickReset(){
    addrSearch.value=''; addrRent.value='';
    addrResults.innerHTML=''; addrResults.style.display='none';
    addrSearch.setAttribute('aria-expanded','false');
    newSessionToken();
  }

  // Manual entry if autocomplete not used
  addrSearch.addEventListener('keydown', (e)=>{
    if (e.key === 'Enter') {
      e.preventDefault();
      addManualCurrent();
    }
  });
  addBtn.addEventListener('click', addManualCurrent);

  function addManualCurrent(){
    const label = (addrSearch.value||'').trim();
    if (!label){ showErr('Enter an address to add.'); return; }
    // Light parse for state / zip (best-effort)
    const parts = label.split(/[\s,]+/);
    const zip   = parts.find(p=>/^\d{5}$/.test(p)) || '';
    const state = parts.find(p=>/^[A-Z]{2}$/i.test(p)) || '';
    addPicked({ label, address: label, city: '', state, zip }, num(addrRent.value));
    afterPickReset();
  }

  clearBtn.addEventListener('click', ()=>{
    addrSearch.value=''; addrRent.value='';
    addrResults.innerHTML=''; addrResults.style.display='none';
    addrSearch.setAttribute('aria-expanded','false');
  });

  // ---------- Picked list (table) ----------
  function pickedItems(){
    return Array.from(pickedTableBody.querySelectorAll('tr[data-item]')).map((row)=>({
      label: row.querySelector('[data-label]')?.textContent || '',
      address: row.dataset.address || '',
      city: row.dataset.city || '',
      state: row.dataset.state || '',
      zip: row.dataset.zip || '',
      rent: Number(row.dataset.rent || 0),
      price: Number(row.querySelector('[data-price-input]')?.value || 0)
    }));
  }

  function addPicked(addr, rent){
    const count = pickedTableBody.querySelectorAll('tr[data-item]').length;
    if (count >= 10){ showErr('You can add up to 10 properties.'); return; }

    const node = pickedRowTpl.content.firstElementChild.cloneNode(true);
    node.querySelector('[data-label]').textContent = addr.label;
    // Remove city/state/zip meta per your request (leave empty)
    node.querySelector('[data-meta]').textContent  = '';

    node.querySelector('[data-rent-readonly]').textContent = dollars(rent || 0);

    node.dataset.address = addr.address || '';
    node.dataset.city    = addr.city    || '';
    node.dataset.state   = addr.state   || '';
    node.dataset.zip     = addr.zip     || '';
    node.dataset.rent    = String(rent || 0);

    node.querySelector('[data-remove]').addEventListener('click', ()=>{
      node.remove(); updatePickedCountAndIndex();
    });

    pickedTableBody.appendChild(node);
    updatePickedCountAndIndex();
  }

  function updatePickedCountAndIndex(){
    const rows = Array.from(pickedTableBody.querySelectorAll('tr[data-item]'));
    rows.forEach((row, idx)=> {
      const idxCell = row.querySelector('[data-idx]');
      if (idxCell) idxCell.textContent = String(idx+1);
    });
    pickedCount.textContent = `${rows.length} of 10 selected`;
  }

  // ---------- Server calls ----------
  async function postJSON(url, body){
    const res = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
    if (!res.ok){ const t = await res.text().catch(()=> ''); throw new Error(t || `Request failed: ${res.status}`); }
    return res.json();
  }

  async function analyzeOne(shared, picked){
    const price = Number(picked.price || 0);
    if (!price) throw new Error(`Purchase Price required for:\n${picked.label}`);

    const prefetch = await postJSON(`${FN_BASE}/api/rent-prefetch`, {
      inputs: {
        address: picked.address, city: picked.city, state: picked.state, zip: picked.zip,
        propertyType: '', units: 1, purchasePrice: price, ownerOccupied: false
      }
    });

    const inputs = {
      address: picked.address, city: picked.city, state: picked.state, zip: picked.zip,
      propertyType: '', units: 1, purchasePrice: price,
      downPct: shared.downPct, rate: shared.rate, termYears: shared.termYears,
      closingCosts: shared.closingCosts, pointsPct: shared.pointsPct,
      rent: Number(picked.rent || prefetch?.ai?.rent?.est || 0),
      otherIncome: 0, vacancyPct: shared.vacancyPct
    };
    const analyzed = await postJSON(`${FN_BASE}/api/rent-analyzer`, { inputs, prefetch });
    analyzed.prefetch = prefetch;
    return analyzed;
  }

  // ---------- Rendering & sorting ----------
  function valueForKey(result, key, rankIdx){
    switch (key) {
      case 'rank':             return rankIdx + 1; // 1-based rank display
      case 'address':          return (result.address || [result.inputs?.address, result.inputs?.city, result.inputs?.state, result.inputs?.zip].filter(Boolean).join(', ')) || '';
      case 'price':            return Number(result.metrics?.price || result.inputs?.purchasePrice || 0);
      case 'rent':             return Number(result.inputs?.rent || result.prefetch?.ai?.rent?.est || 0);
      case 'cash_flow_monthly':return Number(result.metrics?.cashFlowMonthly || 0);
      case 'cap_rate':         return Number(result.metrics?.capRate || 0);
      case 'cash_on_cash':     return Number(result.metrics?.cashOnCash || 0);
      case 'dscr':             return Number(result.metrics?.dscr || 0);
      default: return '';
    }
  }

  function renderTable(results, order, aiMeta){
    portTbl.innerHTML = '';
    const list = order ? order.map(i=> results[i]) : results;

    list.forEach((r, i)=>{
      const addr = valueForKey(r, 'address', i);
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${i+1}</td>
        <td style="max-width:520px; white-space:normal">${addr}</td>
        <td>${dollars(valueForKey(r,'price',i))}</td>
        <td>${dollars(valueForKey(r,'rent',i))}</td>
        <td>${dollars(valueForKey(r,'cash_flow_monthly',i))}</td>
        <td>${Number(valueForKey(r,'cap_rate',i)).toFixed(2)}%</td>
        <td>${Number(valueForKey(r,'cash_on_cash',i)).toFixed(1)}%</td>
        <td>${Number(valueForKey(r,'dscr',i)).toFixed(2)}</td>`;
      portTbl.appendChild(tr);
    });

    if (aiMeta?.ok) {
      portNote.textContent = aiMeta.summary ? `Ranked by AI · ${aiMeta.summary}` : 'Ranked by AI (investment attractiveness).';
    } else {
      portNote.textContent = 'AI ranking unavailable — sorted by Cash-on-Cash then Monthly Cash Flow.';
    }
    portRes.style.display = 'block';
  }

  function setSortIndicator(th, dir){
    // Clear others
    tableHead.querySelectorAll('th[data-sort]').forEach(h=>{
      h.dataset.sorted = '';
      const arrow = h.querySelector('.sort-arrow');
      if (arrow) arrow.textContent = '';
    });
    // Set this one
    th.dataset.sorted = dir;
    const arrow = th.querySelector('.sort-arrow');
    if (arrow) arrow.textContent = dir === 'asc' ? '▲' : '▼';
  }

  function sortAndRender(){
    const { results, order, sort } = state;

    // Build working array with rank index resolved from either AI order or fallback
    const working = (order && order.length === results.length) ? order.map((idx, rank)=>({ idx, rank }))
                                                              : results.map((_, i)=>({ idx: i, rank: i }));
    // Sort
    const key = sort.key;
    const dir = sort.dir === 'desc' ? -1 : 1;

    working.sort((a, b)=>{
      const A = results[a.idx], B = results[b.idx];
      const va = (key==='rank') ? (a.rank+1) : valueForKey(A, key, a.rank);
      const vb = (key==='rank') ? (b.rank+1) : valueForKey(B, key, b.rank);

      if (typeof va === 'number' && typeof vb === 'number') {
        if (va === vb) return 0;
        return (va < vb ? -1 : 1) * dir;
      }
      // string compare (address)
      return String(va).localeCompare(String(vb)) * dir;
    });

    // New display order
    const orderedIdx = working.map(w => w.idx);
    renderTable(results, orderedIdx, state.aiMeta);
  }

  function attachSortHandlers(){
    if (!tableHead) return;
    tableHead.querySelectorAll('th[data-sort]').forEach((th)=>{
      th.style.cursor = 'pointer';
      th.addEventListener('click', ()=>{
        const key = th.dataset.sort;
        // Toggle direction if clicking same key; otherwise default asc (numbers feel natural asc for rank/address; for returns you might prefer desc—but toggling is simple)
        if (state.sort.key === key) {
          state.sort.dir = (state.sort.dir === 'asc') ? 'desc' : 'asc';
        } else {
          state.sort.key = key;
          state.sort.dir = 'asc';
        }
        setSortIndicator(th, state.sort.dir);
        sortAndRender();
      });
    });
  }

  // ---------- Submit ----------
  form.addEventListener('submit', async (e)=>{
    e.preventDefault(); hideErr(); portRes.style.display='none'; portTbl.innerHTML='';

    try{
      if (!document.getElementById('consent').checked) throw new Error('Please accept the educational-only consent.');
      const shared = {
        downPct: num(document.getElementById('downPct').value),
        rate: num(document.getElementById('rate').value),
        termYears: num(document.getElementById('termYears').value),
        closingCosts: num(document.getElementById('closingCosts').value),
        pointsPct: num(document.getElementById('pointsPct').value),
        vacancyPct: num(document.getElementById('vacancyPct').value || 5)
      };
      if (!shared.downPct || !shared.rate || !shared.termYears) throw new Error('Down %, Rate, and Term are required.');

      const items = pickedItems();
      if (!items.length) throw new Error('Please add at least one address.');
      if (items.length > 10) throw new Error('Up to 10 properties supported.');

      // Validate each has a price
      for (const it of items) {
        if (!num(it.price)) throw new Error(`Enter a Purchase Price for: ${it.label}`);
      }

      submitBtn.disabled = true; submitBtn.textContent = 'Analyzing…';

      const results = [];
      for (const p of items){
        const out = await analyzeOne(shared, p);
        results.push(out);
      }

      // Rank with appreciation by default
      let rankResp;
      try{
        rankResp = await postJSON(`${FN_BASE}/api/portfolio-rank`, { items: results, aiMode: 'aoai_appreciation' });
        state.results = results;
        state.order   = Array.isArray(rankResp.order) ? rankResp.order : null;
        state.aiMeta  = { ok: !!rankResp.ok, summary: rankResp.summary || '' };

        // default display is AI order -> sort key "rank"
        state.sort = { key: 'rank', dir: 'asc' };
        // set indicator on Rank header if present
        const rankTh = tableHead?.querySelector('th[data-sort="rank"]');
        if (rankTh) setSortIndicator(rankTh, 'asc');
        sortAndRender();
      } catch {
        // client fallback sort by cash_on_cash DESC, then cash_flow_monthly DESC
        const idx = results.map((_, i)=> i).sort((a,b)=>{
          const A=results[a].metrics||{}, B=results[b].metrics||{};
          const byCoC = (Number(B.cashOnCash||0) - Number(A.cashOnCash||0));
          if (byCoC !== 0) return byCoC;
          return Number(B.cashFlowMonthly||0) - Number(A.cashFlowMonthly||0);
        });
        state.results = results;
        state.order   = idx;
        state.aiMeta  = { ok:false, summary:'' };

        // default to CoC sort view
        state.sort = { key: 'cash_on_cash', dir: 'desc' };
        const cocTh = tableHead?.querySelector('th[data-sort="cash_on_cash"]');
        if (cocTh) setSortIndicator(cocTh, 'desc');
        sortAndRender();
      }

      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event:'portfolio_analyzer_submit', count: items.length });

    } catch (ex){
      showErr(ex.message || 'Something went wrong.');
    } finally {
      submitBtn.disabled = false; submitBtn.textContent = 'Analyze & Rank';
    }
  });

  // Expose Places init for Google callback & set up sorting
  window.initPortfolioPlaces = function(){
    initPlaces();
    attachSortHandlers();
  };

  // If Places fails to load, still attach sort handlers
  if (document.readyState !== 'loading') attachSortHandlers();
  else window.addEventListener('DOMContentLoaded', attachSortHandlers);
})();