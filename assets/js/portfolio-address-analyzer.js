(function(){
  // --- Config ---
  const API_BASE = 'https://<YOUR-FUNCTION-APP>.azurewebsites.net/api'; // set your Azure Functions base

  // --- DOM ---
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

  // --- Helpers ---
  const dollars = (n)=> Number(n||0).toLocaleString(undefined,{style:'currency',currency:'USD'});
  const pct     = (n, d=2)=> `${Number(n||0).toFixed(d)}%`;
  const num     = (v)=> { const x = Number(v); return Number.isFinite(x) ? x : 0; };
  const text    = (v)=> (v ?? '').toString().trim();

  function showErr(msg){
    err.textContent = msg;
    err.style.display = 'block';
  }
  function hideErr(){ err.style.display = 'none'; }

  // --- Google Places Autocomplete (free-form, validated on pick) ---
  let placesService, sessionToken, autocompleteService;

  function initPlaces() {
    if (!('google' in window) || !google.maps || !google.maps.places) {
      console.warn('Google Places not loaded.');
      return;
    }
    placesService = new google.maps.places.PlacesService(document.createElement('div'));
    autocompleteService = new google.maps.places.AutocompleteService();
    newSessionToken();
  }
  function newSessionToken(){
    sessionToken = new google.maps.places.AutocompleteSessionToken();
  }

  function renderSuggestions(predictions){
    addrResults.innerHTML = '';
    if (!predictions || predictions.length === 0) {
      addrResults.style.display = 'none';
      addrSearch.setAttribute('aria-expanded','false');
      return;
    }
    predictions.forEach(pred => {
      const li = document.createElement('li');
      li.role = 'option';
      li.tabIndex = 0;
      li.style.cursor = 'pointer';
      li.style.padding = '8px';
      li.textContent = pred.description;
      li.addEventListener('click', ()=> selectPrediction(pred));
      li.addEventListener('keydown', (e)=>{ if (e.key === 'Enter') selectPrediction(pred); });
      addrResults.appendChild(li);
    });
    addrResults.style.display = 'block';
    addrSearch.setAttribute('aria-expanded','true');
  }

  function selectPrediction(pred){
    // Get place details to normalize components (addr, city, state, zip, country)
    placesService.getDetails({
      placeId: pred.place_id,
      sessionToken,
      fields: ['formatted_address','address_components','geometry','name']
    }, (place, status)=>{
      if (status !== google.maps.places.PlacesServiceStatus.OK || !place) {
        showErr('Could not validate the address. Please try another.');
        return;
      }
      const addr = normalizePlace(place);
      addPicked(addr, num(addrRent.value));
      // reset search box/session
      addrSearch.value = '';
      addrRent.value = '';
      addrResults.innerHTML = '';
      addrResults.style.display = 'none';
      addrSearch.setAttribute('aria-expanded','false');
      newSessionToken();
    });
  }

  function normalizePlace(place){
    const comp = (type) => (place.address_components || []).find(c => c.types.includes(type));
    const streetNum = comp('street_number')?.long_name || '';
    const route     = comp('route')?.long_name || '';
    const locality  = comp('locality')?.long_name || comp('sublocality_level_1')?.long_name || '';
    const admin1    = comp('administrative_area_level_1')?.short_name || '';
    const postal    = comp('postal_code')?.long_name || '';
    const country   = comp('country')?.short_name || '';
    const address1  = [streetNum, route].filter(Boolean).join(' ').trim() || place.name || place.formatted_address;
    return {
      label: place.formatted_address || [address1, locality, admin1, postal].filter(Boolean).join(', '),
      address: address1,
      city: locality,
      state: admin1,
      zip: postal,
      country,
      lat: place.geometry?.location?.lat?.() || null,
      lng: place.geometry?.location?.lng?.() || null
    };
  }

  addrSearch.addEventListener('input', () => {
    hideErr();
    const q = text(addrSearch.value);
    if (!q) { addrResults.style.display='none'; addrSearch.setAttribute('aria-expanded','false'); return; }
    if (!autocompleteService || !sessionToken) return;
    autocompleteService.getPlacePredictions({
      input: q,
      sessionToken,
      types: ['address'], // address-only
      componentRestrictions: { country: ['us'] } // adjust as needed
    }, (predictions, status)=>{
      if (status !== google.maps.places.PlacesServiceStatus.OK) {
        addrResults.style.display = 'none';
        addrSearch.setAttribute('aria-expanded','false');
        return;
      }
      renderSuggestions(predictions);
    });
  });

  clearBtn.addEventListener('click', ()=>{
    addrSearch.value = '';
    addrRent.value = '';
    addrResults.innerHTML = '';
    addrResults.style.display = 'none';
    addrSearch.setAttribute('aria-expanded','false');
  });

  // --- Picked list (up to 10) ---
  function pickedItems(){
    return Array.from(pickedList.querySelectorAll('[data-item]')).map(el => ({
      address: el.dataset.address,
      city: el.dataset.city,
      state: el.dataset.state,
      zip: el.dataset.zip,
      purchasePrice: Number(el.dataset.price || 0), // price not known here; user will add later via prompt
      rent: Number(el.querySelector('[data-rent]')?.value || 0),
      label: el.querySelector('[data-label]')?.textContent || ''
    }));
  }

  function addPicked(addrObj, rent){
    const current = pickedItems();
    if (current.length >= 10) { showErr('You can add up to 10 properties.'); return; }

    // render chip/card
    const node = pickedTpl.content.firstElementChild.cloneNode(true);
    node.querySelector('[data-label]').textContent = addrObj.label;
    node.querySelector('[data-meta]').textContent = [addrObj.city, addrObj.state, addrObj.zip].filter(Boolean).join(', ');
    node.querySelector('[data-rent]').value = rent || 0;

    // stash normalized data on element
    node.dataset.address = addrObj.address || '';
    node.dataset.city    = addrObj.city || '';
    node.dataset.state   = addrObj.state || '';
    node.dataset.zip     = addrObj.zip || '';
    node.dataset.label   = addrObj.label || '';

    node.querySelector('[data-remove]').addEventListener('click', ()=> {
      node.remove();
      updatePickedCount();
    });

    pickedList.appendChild(node);
    updatePickedCount();
  }

  function updatePickedCount(){
    const count = pickedList.querySelectorAll('[data-item]').length;
    pickedCount.textContent = `${count} of 10 selected`;
  }

  // --- Networking ---
  async function callJSON(url, payload){
    const res = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const t = await res.text().catch(()=> '');
      throw new Error(t || ('Request failed: ' + res.status));
    }
    return res.json();
  }

  // --- Analyze each property with shared financing ---
  async function analyzeOne(shared, picked){
    // You’ll probably prompt for price per property; for now we’ll ask the user after pick if price is missing.
    // Minimal prompt flow for price:
    let price = picked.purchasePrice;
    if (!price) {
      price = Number(prompt(`Enter Purchase Price for:\n${picked.label}`, '0') || '0');
      if (!Number.isFinite(price) || price <= 0) throw new Error('Purchase Price required.');
    }

    const rent = Number(picked.rent || 0);

    // 1) Prefetch (server orchestrates all-expense + rent + appreciation)
    const prefetch = await callJSON(`${API_BASE}/rent-prefetch`, { inputs: {
      address: picked.address,
      city: picked.city,
      state: picked.state,
      zip: picked.zip,
      propertyType: '',   // optional
      units: 1,
      purchasePrice: price,
      ownerOccupied: false
    }});

    // 2) Analyze (shared financing + per-property)
    const inputs = {
      address: picked.address, city: picked.city, state: picked.state, zip: picked.zip,
      propertyType: '', units: 1,
      purchasePrice: price,
      downPct: shared.downPct,
      rate: shared.rate,
      termYears: shared.termYears,
      closingCosts: shared.closingCosts,
      pointsPct: shared.pointsPct,
      rent,
      otherIncome: 0,
      vacancyPct: shared.vacancyPct
      // user expense overrides omitted → analyzer will use prefetch.ai.expenses
    };

    const out = await callJSON(`${API_BASE}/rent-analyze`, { inputs, prefetch });
    return out;
  }

  function sortResults(results){
    // Default: sort by Cash-on-Cash (desc), then Cash Flow Monthly (desc)
    return results.sort((a,b)=>{
      const c1 = Number(a.metrics?.cashOnCash || 0);
      const c2 = Number(b.metrics?.cashOnCash || 0);
      if (c2 !== c1) return c2 - c1;
      const f1 = Number(a.metrics?.cashFlowMonthly || 0);
      const f2 = Number(b.metrics?.cashFlowMonthly || 0);
      return f2 - f1;
    });
  }

  function renderTable(results){
    portTbl.innerHTML = '';
    results.forEach((r, i)=>{
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
  }

  // --- Form submit ---
  form.addEventListener('submit', async (e)=>{
    e.preventDefault();
    hideErr();
    portRes.style.display = 'none';
    portTbl.innerHTML = '';

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

      submitBtn.disabled = true;
      submitBtn.textContent = 'Analyzing…';

      // Analyze sequentially to keep it simple (can parallelize with Promise.all if desired)
      const results = [];
      for (const p of items) {
        const out = await analyzeOne(shared, p);
        results.push(out);
      }

      // Rank & render
      const ranked = sortResults(results);
      renderTable(ranked);
      portNote.textContent = 'Sorted by Cash-on-Cash (desc), then by Monthly Cash Flow (desc).';
      portRes.style.display = 'block';

      // Analytics
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({
        event: 'portfolio_analyzer_submit',
        count: items.length
      });

    } catch (ex) {
      showErr(ex.message || 'Something went wrong.');
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Analyze & Rank';
    }
  });

  // Init
  window.addEventListener('load', initPlaces);
})();