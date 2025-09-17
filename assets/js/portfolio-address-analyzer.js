(function(){
  const FN_BASE = 'https://rent-analyzer-fn-eheqhra2d6bwd6fm.canadacentral-01.azurewebsites.net';

  const form       = document.getElementById('portfolio-form');
  const err        = document.getElementById('err');
  const submitBtn  = document.getElementById('submitBtn');
  const addrSearch = document.getElementById('addrSearch');
  const addrResults= document.getElementById('addrResults');
  const addrRent   = document.getElementById('addrRent');
  const clearBtn   = document.getElementById('clearSearch');
  const pickedList = document.getElementById('pickedList');
  const pickedTpl  = document.getElementById('pickedTpl');
  const pickedCount= document.getElementById('pickedCount');
  const portRes    = document.getElementById('portfolioResult');
  const portNote   = document.getElementById('portfolioNote');
  const portTbl    = document.querySelector('#portfolioTable tbody');

  const dollars=(n)=>Number(n||0).toLocaleString(undefined,{style:'currency',currency:'USD'});
  const num=(v)=>{const x=Number(v);return Number.isFinite(x)?x:0;};
  function showErr(m){ err.textContent=m; err.style.display='block'; }
  function hideErr(){ err.style.display='none'; }

  // Google Places
  let placesService, sessionToken, autocompleteService;
  function initPlaces(){
    if (!('google' in window) || !google.maps || !google.maps.places) return;
    placesService = new google.maps.places.PlacesService(document.createElement('div'));
    autocompleteService = new google.maps.places.AutocompleteService();
    newSessionToken();
  }
  function newSessionToken(){ sessionToken = new google.maps.places.AutocompleteSessionToken(); }
  function renderSuggestions(preds){
    addrResults.innerHTML=''; if(!preds?.length){ addrResults.style.display='none'; return; }
    preds.forEach(pred=>{
      const li=document.createElement('li'); li.role='option'; li.tabIndex=0; li.style.cursor='pointer'; li.style.padding='8px';
      li.textContent=pred.description;
      li.addEventListener('click',()=>selectPrediction(pred));
      li.addEventListener('keydown',(e)=>{ if(e.key==='Enter') selectPrediction(pred); });
      addrResults.appendChild(li);
    });
    addrResults.style.display='block';
  }
  function selectPrediction(pred){
    placesService.getDetails({ placeId: pred.place_id, sessionToken,
      fields:['formatted_address','address_components','geometry','name'] },
      (place, status)=>{
        if(status!==google.maps.places.PlacesServiceStatus.OK || !place){ showErr('Could not validate the address.'); return; }
        const comp=(t)=> (place.address_components||[]).find(c=>c.types.includes(t));
        const street= [comp('street_number')?.long_name||'', comp('route')?.long_name||''].filter(Boolean).join(' ').trim() || place.name || '';
        const city  = comp('locality')?.long_name || comp('sublocality_level_1')?.long_name || '';
        const state = comp('administrative_area_level_1')?.short_name || '';
        const zip   = comp('postal_code')?.long_name || '';
        addPicked({
          label: place.formatted_address || [street, city, state, zip].filter(Boolean).join(', '),
          address: street, city, state, zip
        }, num(addrRent.value));
        addrSearch.value=''; addrRent.value=''; addrResults.innerHTML=''; addrResults.style.display='none'; newSessionToken();
      });
  }
  addrSearch.addEventListener('input', ()=>{
    hideErr();
    const q = (addrSearch.value||'').trim();
    if(!q){ addrResults.style.display='none'; return; }
    if(!autocompleteService || !sessionToken) return;
    autocompleteService.getPlacePredictions({ input:q, sessionToken, types:['address'], componentRestrictions:{country:['us']} },
      (preds, status)=>{ if(status!==google.maps.places.PlacesServiceStatus.OK){ addrResults.style.display='none'; return; } renderSuggestions(preds); });
  });
  clearBtn.addEventListener('click', ()=>{
    addrSearch.value=''; addrRent.value=''; addrResults.innerHTML=''; addrResults.style.display='none';
  });

  function pickedItems(){
    return Array.from(pickedList.querySelectorAll('[data-item]')).map(el=>({
      label: el.querySelector('[data-label]')?.textContent || '',
      address: el.dataset.address, city: el.dataset.city, state: el.dataset.state, zip: el.dataset.zip,
      rent: Number(el.querySelector('[data-rent]')?.value || 0)
    }));
  }
  function addPicked(addr, rent){
    const count = pickedList.querySelectorAll('[data-item]').length;
    if(count>=10){ showErr('You can add up to 10 properties.'); return; }
    const node = pickedTpl.content.firstElementChild.cloneNode(true);
    node.querySelector('[data-label]').textContent = addr.label;
    node.querySelector('[data-meta]').textContent  = [addr.city, addr.state, addr.zip].filter(Boolean).join(', ');
    node.querySelector('[data-rent]').value = rent || 0;
    node.dataset.address=addr.address||''; node.dataset.city=addr.city||''; node.dataset.state=addr.state||''; node.dataset.zip=addr.zip||'';
    node.querySelector('[data-remove]').addEventListener('click', ()=>{ node.remove(); updatePickedCount(); });
    pickedList.appendChild(node); updatePickedCount();
  }
  function updatePickedCount(){
    const c = pickedList.querySelectorAll('[data-item]').length;
    pickedCount.textContent = `${c} of 10 selected`;
  }

  async function postJSON(url, body){
    const res = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
    if (!res.ok){ const t = await res.text().catch(()=> ''); throw new Error(t || `Request failed: ${res.status}`); }
    return res.json();
  }

  async function analyzeOne(shared, picked){
    const price = Number(prompt(`Enter Purchase Price for:\n${picked.label}`, '0') || '0');
    if (!price) throw new Error('Purchase Price required.');

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
        <td>${addr}</td>
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

  form.addEventListener('submit', async (e)=>{
    e.preventDefault(); hideErr(); portRes.style.display='none'; portTbl.innerHTML='';

    try{
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
      if (!items.length) throw new Error('Please add at least one validated address.');
      if (items.length > 10) throw new Error('Up to 10 properties supported.');

      submitBtn.disabled = true; submitBtn.textContent = 'Analyzing…';

      const results = [];
      for (const p of items){
        const out = await analyzeOne(shared, p);
        results.push(out);
      }

      // Rank (server: { items, aiMode })
      let rankResp;
      try{
        rankResp = await postJSON(`${FN_BASE}/api/portfolio-rank`, { items: results, aiMode: 'auto' });
        const order = Array.isArray(rankResp.order) ? rankResp.order : null;
        renderTable(results, order, { ok: !!rankResp.ok, summary: rankResp.summary });
      } catch {
        // client fallback
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

      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event:'portfolio_analyzer_submit', count: items.length });

    } catch (ex){
      showErr(ex.message || 'Something went wrong.');
    } finally {
      submitBtn.disabled = false; submitBtn.textContent = 'Analyze & Rank';
    }
  });

  window.addEventListener('load', ()=> initPlaces());
})();