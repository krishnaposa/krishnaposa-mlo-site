// /assets/js/portfolio-address-analyzer.js
(function(){
  const API_BASE = 'https://<YOUR-FUNCTION-APP>.azurewebsites.net/api'; // set your Functions base

  // DOM
  const form      = document.getElementById('portfolio-form');
  const err       = document.getElementById('err');
  const submitBtn = document.getElementById('submitBtn');
  const addrSearch = document.getElementById('addrSearch');
  const addrResults = document.getElementById('addrResults');
  const addrRent   = document.getElementById('addrRent');
  const clearBtn   = document.getElementById('clearSearch');
  const pickedList = document.getElementById('pickedList');
  const pickedTpl  = document.getElementById('pickedTpl');
  const pickedCount = document.getElementById('pickedCount');
  const portRes   = document.getElementById('portfolioResult');
  const portNote  = document.getElementById('portfolioNote');
  const portTbl   = document.querySelector('#portfolioTable tbody');

  // Helpers
  const dollars = (n)=> Number(n||0).toLocaleString(undefined,{style:'currency',currency:'USD'});
  const pct     = (n, d=2)=> `${Number(n||0).toFixed(d)}%`;
  const num     = (v)=> { const x = Number(v); return Number.isFinite(x) ? x : 0; };
  const text    = (v)=> (v ?? '').toString().trim();

  function showErr(msg){ err.textContent = msg; err.style.display = 'block'; }
  function hideErr(){ err.style.display = 'none'; }

  // Google Places
  let placesService, sessionToken, autocompleteService;
  function initPlaces() {
    if (!('google' in window) || !google.maps || !google.maps.places) return;
    placesService = new google.maps.places.PlacesService(document.createElement('div'));
    autocompleteService = new google.maps.places.AutocompleteService();
    newSessionToken();
  }
  function newSessionToken(){ sessionToken = new google.maps.places.AutocompleteSessionToken(); }

  function renderSuggestions(predictions){
    addrResults.innerHTML = '';
    if (!predictions || !predictions.length){
      addrResults.style.display='none';
      addrSearch.setAttribute('aria-expanded','false');
      return;
    }
    predictions.forEach(pred=>{
      const li = document.createElement('li');
      li.role = 'option'; li.tabIndex = 0;
      li.style.cursor = 'pointer'; li.style.padding = '8px';
      li.textContent = pred.description;
      li.addEventListener('click', ()=> selectPrediction(pred));
      li.addEventListener('keydown', (e)=>{ if (e.key==='Enter') selectPrediction(pred); });
      addrResults.appendChild(li);
    });
    addrResults.style.display='block';
    addrSearch.setAttribute('aria-expanded','true');
  }

  function selectPrediction(pred){
    placesService.getDetails({
      placeId: pred.place_id,
      sessionToken,
      fields: ['formatted_address','address_components','geometry','name']
    }, (place, status)=>{
      if (status !== google.maps.places.PlacesServiceStatus.OK || !place){
        showErr('Could not validate the address. Please try again.');
        return;
      }
      const addr = normalizePlace(place);
      addPicked(addr, num(addrRent.value));
      addrSearch.value = ''; addrRent.value = '';
      addrResults.innerHTML = ''; addrResults.style.display='none';
      addrSearch.setAttribute('aria-expanded','false');
      newSessionToken();
    });
  }

  function normalizePlace(place){
    const comp = (type)=> (place.address_components||[]).find(c=>c.types.includes(type));
    const streetNum = comp('street_number')?.long_name || '';
    const route     = comp('route')?.long_name || '';
    const locality  = comp('locality')?.long_name || comp('sublocality_level_1')?.long_name || '';
    const admin1    = comp('administrative_area_level_1')?.short_name || '';
    const postal    = comp('postal_code')?.long_name || '';
    const address1  = [streetNum, route].filter(Boolean).join(' ').trim() || place.name || place.formatted_address;
    return {
      label: place.formatted_address || [address1, locality, admin1, postal].filter(Boolean).join(', '),
      address: address1, city: locality, state: admin1, zip: postal,
      lat: place.geometry?.location?.lat?.() || null,
      lng: place.geometry?.location?.lng?.() || null
    };
  }

  addrSearch.addEventListener('input', ()=>{
    hideErr();
    const q = text(addrSearch.value);
    if (!q){ addrResults.style.display='none'; addrSearch.setAttribute('aria-expanded','false'); return; }
    if (!autocompleteService || !sessionToken) return;
    autocompleteService.getPlacePredictions({
      input: q, sessionToken, types: ['address'], componentRestrictions: { country: ['us'] }
    }, (predictions, status)=>{
      if (status !== google.maps.places.PlacesServiceStatus.OK){ addrResults.style.display='none'; addrSearch.setAttribute('aria-expanded','false'); return; }
      renderSuggestions(predictions);
    });
  });

  clearBtn.addEventListener('click', ()=>{
    addrSearch.value=''; addrRent.value='';
    addrResults.innerHTML=''; addrResults.style.display='none';
    addrSearch.setAttribute('aria-expanded','false');
  });

  function pickedItems(){
    return Array.from(pickedList.querySelectorAll('[data-item]')).map(el => ({
      label: el.querySelector('[data-label]')?.textContent || '',
      address: el.dataset.address, city: el.dataset.city, state: el.dataset.state, zip: el.dataset.zip,
      rent: Number(el.querySelector('[data-rent]')?.value || 0)
    }));
  }

  function addPicked(addrObj, rent){
    const count = pickedList.querySelectorAll('[data-item]').length;
    if (count >= 10){ showErr('You can add up to 10 properties.'); return; }

    const node = pickedTpl.content.firstElementChild.cloneNode(true);
    node.querySelector('[data-label]').textContent = addrObj.label;
    node.querySelector('[data-meta]').textContent = [addrObj.city, addrObj.state, addrObj.zip].filter(Boolean).join(', ');
    node.querySelector('[data-rent]').value = rent || 0;

    node.dataset.address = addrObj.address || '';
    node.dataset.city    = addrObj.city || '';
    node.dataset.state   = addrObj.state || '';
    node.dataset.zip     = addrObj.zip || '';

    node.querySelector('[data-remove]').addEventListener('click', ()=> { node.remove(); updatePickedCount(); });

    pickedList.appendChild(node);
    updatePickedCount();
  }
  function updatePickedCount(){
    const c = pickedList.querySelectorAll('[data-item]').length;
    pickedCount.textContent = `${c} of 10 selected`;
  }

  // Networking
  async function callJSON(url, payload){
    const res = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    if (!res.ok){ const t = await res.text().catch(()=> ''); throw new Error(t || ('Request failed: '+res.status)); }
    return res.json();
  }

  // Analyze a single property with shared financing
  async function analyzeOne(shared, picked){
    let price = Number(prompt(`Enter Purchase Price for:\n${picked.label}`, '0') || '0');
    if (!Number.isFinite(price) || price <= 0) throw new Error('Purchase Price required.');
    const rent = Number(picked.rent || 0);

    const prefetch = await callJSON(`${API_BASE}/rent-prefetch`, { inputs: {
      address: picked.address, city: picked.city, state: picked.state, zip: picked.zip,
      propertyType: '', units: 1, purchasePrice: price, ownerOccupied: false
    }});

    const inputs = {
      address: picked.address, city: picked.city, state: picked.state, zip: picked.zip,
      propertyType: '', units: 1, purchasePrice: price,
      downPct: shared.downPct, rate: shared.rate, termYears: shared.termYears,
      closingCosts: shared.closingCosts, pointsPct: shared.pointsPct,
      rent, otherIncome: 0, vacancyPct: shared.vacancyPct
    };
    const out = await callJSON(`${API_BASE}/rent-analyze`, { inputs, prefetch });
    return out;
  }

  function renderTable(results, order, aiMeta){
    portTbl.innerHTML = '';
    const list = order ? order.map(i => results[i]) : results;
    list.forEach((r, i)=>{
      const addr = r.address || [r.inputs?.address, r.inputs?.city, r.inputs?.state, r.inputs?.zip].filter(Boolean).join(', ');
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${i+1}</td>
        <td>${addr}</td>
        <td>${dollars(r.metrics?.price)}</td>
        <td>${dollars(r.inputs?.rent || r.prefetch?.ai?.rent?.est || 0)}</td>
        <td>${dollars(r.metrics?.cashFlowMonthly)}</td>
        <td>${Number(r.metrics?.capRate||0).toFixed(2)}%</td>
        <td>${Number(r.metrics?.cashOnCash||0).toFixed(1)}%</td>
        <td>${Number(r.metrics?.dscr||0).toFixed(2)}</td>
      `;
      portTbl.appendChild(tr);
    });
    if (aiMeta?.ok) {
      portNote.textContent = 'Ranked by AI (investment attractiveness).';
    } else {
      portNote.textContent = 'AI ranking unavailable — sorted by Cash-on-Cash (desc), then Monthly Cash Flow (desc).';
    }
    portRes.style.display = 'block';
  }

  // Submit
  form.addEventListener('submit', async (e)=>{
    e.preventDefault(); hideErr(); portRes.style.display='none'; portTbl.innerHTML='';

    try {
      if (!document.getElementById('consent').checked) throw new Error('Please accept the educational-only consent to proceed.');
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
      if (items.length === 0) throw new Error('Please add at least one validated address.');
      if (items.length > 10) throw new Error('Up to 10 properties supported.');

      submitBtn.disabled = true; submitBtn.textContent = 'Analyzing…';

      const results = [];
      // Simple sequential loop; you can switch to Promise.all for parallel if desired
      for (const p of items){
        const out = await analyzeOne(shared, p);
        results.push(out);
      }

      // Call AI ranker
      let rankResp = null;
      try {
        rankResp = await callJSON(`${API_BASE}/portfolio-rank`, { items: results });
        const order = Array.isArray(rankResp.order) ? rankResp.order : null;
        renderTable(results, order, rankResp);
      } catch (rankErr) {
        console.warn('AI ranker failed, falling back:', rankErr);
        // Fallback: sort by CoC desc, then CF desc
        const indices = results.map((_, i)=> i);
        indices.sort((i, j)=>{
          const a = results[i].metrics || {}, b = results[j].metrics || {};
          const c1 = Number(a.cashOnCash || 0), c2 = Number(b.cashOnCash || 0);
          if (c2 !== c1) return c2 - c1;
          const f1 = Number(a.cashFlowMonthly || 0), f2 = Number(b.cashFlowMonthly || 0);
          return f2 - f1;
        });
        renderTable(results, indices, { ok: false });
      }

      // Analytics
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event: 'portfolio_analyzer_submit', count: items.length });

    } catch (ex) {
      showErr(ex.message || 'Something went wrong.');
    } finally {
      submitBtn.disabled = false; submitBtn.textContent = 'Analyze & Rank';
    }
  });

  // Init
  window.addEventListener('load', ()=>{
    initPlaces();
  });
})();