(function(){
  const FN_BASE = 'https://rent-analyzer-fn-eheqhra2d6bwd6fm.canadacentral-01.azurewebsites.net';

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

  const dollars = (n)=> Number(n||0).toLocaleString(undefined,{style:'currency',currency:'USD'});
  const num     = (v)=> { const x = Number(v); return Number.isFinite(x) ? x : 0; };
  function showErr(m){ err.textContent = m; err.style.display = 'block'; }
  function hideErr(){ err.style.display = 'none'; }

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
      if (pred && typeof pred.fetchFields === 'function') {
        const { placePrediction } = await pred.fetchFields({
          fields: ['formatted_address','address_components','geometry','name']
        });
        return addPlaceFromNew(placePrediction);
      }
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
    // Basic parse for state/zip
    const parts = label.split(/[\s,]+/);
    const zip   = parts.find(p=>/^\d{5}$/.test(p)) || '';
    const state = parts.find(p=>/^[A-Z]{2}$/i.test(p)) || '';
    const city  = parts.length>2 ? parts[parts.length-3] : '';
    addPicked({ label, address: label, city, state, zip }, num(addrRent.value));
    afterPickReset();
  }

  clearBtn.addEventListener('click', ()=>{
    addrSearch.value=''; addrRent.value='';
    addrResults.innerHTML=''; addrResults.style.display='none';
    addrSearch.setAttribute('aria-expanded','false');
  });

  // Picked list handling
  function pickedItems(){
    return Array.from(pickedTableBody.querySelectorAll('tr[data-item]')).map((row)=>({
      label: row.querySelector('[data-label]')?.textContent || '',
      address: row.dataset.address || '',
      city: row.dataset.city || '',
      state: row.dataset.state || '',
      zip: row.dataset.zip || '',
      rent: Number(row.dataset.rent || 0)
    }));
  }

  function addPicked(addr, rent){
    const count = pickedTableBody.querySelectorAll('tr[data-item]').length;
    if (count >= 10){ showErr('You can add up to 10 properties.'); return; }
    const node = pickedRowTpl.content.firstElementChild.cloneNode(true);
    node.querySelector('[data-label]').textContent = addr.label;
    node.querySelector('[data-meta]').textContent  = [addr.city, addr.state, addr.zip].filter(Boolean).join(', ');
    node.querySelector('[data-rent-readonly]').textContent = dollars(rent || 0);
    node.dataset.address = addr.address || '';
    node.dataset.city    = addr.city    || '';
    node.dataset.state   = addr.state   || '';
    node.dataset.zip     = addr.zip     || '';
    node.dataset.rent    = String(rent || 0);
    node.querySelector('[data-remove]').addEventListener('click', ()=>{ node.remove(); updatePickedCountAndIndex(); });
    pickedTableBody.appendChild(node);
    updatePickedCountAndIndex();
  }

  function updatePickedCountAndIndex(){
    const rows = Array.from(pickedTableBody.querySelectorAll('tr[data-item]'));
    rows.forEach((row, idx)=> { const idxCell = row.querySelector('[data-idx]'); if (idxCell) idxCell.textContent = String(idx+1); });
    pickedCount.textContent = `${rows.length} of 10 selected`;
  }

  // Fetch helpers
  async function postJSON(url, body){
    const res = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
    if (!res.ok){ const t = await res.text().catch(()=> ''); throw new Error(t || `Request failed: ${res.status}`); }
    return res.json();
  }

  async function analyzeOne(shared, picked){
    const price = Number(prompt(`Enter Purchase Price for:\n${picked.label}`, '0') || '0');
    if (!price) throw new Error('Purchase Price required.');
    const prefetch = await postJSON(`${FN_BASE}/api/rent-prefetch`, {
      inputs: { ...picked, propertyType:'', units:1, purchasePrice:price, ownerOccupied:false }
    });
    const inputs = {
      ...picked,
      propertyType:'', units:1, purchasePrice:price,
      downPct:shared.downPct, rate:shared.rate, termYears:shared.termYears,
      closingCosts:shared.closingCosts, pointsPct:shared.pointsPct,
      rent: Number(picked.rent || prefetch?.ai?.rent?.est || 0),
      otherIncome:0, vacancyPct:shared.vacancyPct
    };
    const analyzed = await postJSON(`${FN_BASE}/api/rent-analyze`, { inputs, prefetch });
    analyzed.prefetch = prefetch;
    return analyzed;
  }

  function renderTable(results, order, aiMeta){
    portTbl.innerHTML = '';
    const list = order ? order.map(i=> results[i]) : results;
    list.forEach((r, i)=>{
      const addr = r.address || [r.inputs?.address, r.inputs?.city, r.inputs?.state, r.inputs?.zip].filter(Boolean).join(', ');
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${i+1}</td>
        <td style="max-width:520px; white-space:normal">${addr}</td>
        <td>${dollars(r.metrics?.price)}</td>
        <td>${dollars(r.inputs?.rent || r.prefetch?.ai?.rent?.est || 0)}</td>
        <td>${dollars(r.metrics?.cashFlowMonthly)}</td>
        <td>${Number(r.metrics?.capRate||0).toFixed(2)}%</td>
        <td>${Number(r.metrics?.cashOnCash||0).toFixed(1)}%</td>
        <td>${Number(r.metrics?.dscr||0).toFixed(2)}</td>`;
      portTbl.appendChild(tr);
    });
    portNote.textContent = aiMeta?.ok
      ? (aiMeta.summary ? `Ranked by AI · ${aiMeta.summary}` : 'Ranked by AI (investment attractiveness).')
      : 'AI ranking unavailable — sorted by Cash-on-Cash then Monthly Cash Flow.';
    portRes.style.display = 'block';
  }

  // Submit handler
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
      submitBtn.disabled = true; submitBtn.textContent = 'Analyzing…';
      const results = [];
      for (const p of items){ results.push(await analyzeOne(shared, p)); }
      let rankResp;
      try{
        rankResp = await postJSON(`${FN_BASE}/api/portfolio-rank`, { items: results, aiMode: 'auto' });
        renderTable(results, rankResp.order, { ok:!!rankResp.ok, summary:rankResp.summary });
      } catch {
        const idx = results.map((_,i)=>i).sort((a,b)=>{
          const A=results[a].metrics||{}, B=results[b].metrics||{};
          return (B.cashOnCash||0)-(A.cashOnCash||0) || (B.cashFlowMonthly||0)-(A.cashFlowMonthly||0);
        });
        renderTable(results, idx, { ok:false });
      }
      window.dataLayer=window.dataLayer||[]; window.dataLayer.push({ event:'portfolio_analyzer_submit', count:items.length });
    } catch(ex){ showErr(ex.message||'Something went wrong.'); }
    finally{ submitBtn.disabled=false; submitBtn.textContent='Analyze & Rank'; }
  });

  window.initPortfolioPlaces = initPlaces;
})();