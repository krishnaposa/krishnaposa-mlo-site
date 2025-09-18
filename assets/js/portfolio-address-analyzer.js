(function () {
  const FN_BASE = 'https://rent-analyzer-fn-eheqhra2d6bwd6fm.canadacentral-01.azurewebsites.net';

  // ------- DOM -------
  const form        = document.getElementById('portfolio-form');
  const err         = document.getElementById('err');
  const submitBtn   = document.getElementById('submitBtn');
  const addrSearch  = document.getElementById('addrSearch');
  const addrResults = document.getElementById('addrResults');
  const addrRent    = document.getElementById('addrRent');
  const clearBtn    = document.getElementById('clearSearch');
  const pickedList  = document.getElementById('pickedList');
  const pickedTpl   = document.getElementById('pickedTpl');
  const pickedCount = document.getElementById('pickedCount');
  const portRes     = document.getElementById('portfolioResult');
  const portNote    = document.getElementById('portfolioNote');
  const portTbl     = document.querySelector('#portfolioTable tbody');

  // ------- utils -------
  const dollars = (n) => Number(n || 0).toLocaleString(undefined, { style: 'currency', currency: 'USD' });
  const num     = (v) => { const x = Number(v); return Number.isFinite(x) ? x : 0; };
  const text    = (v) => (v ?? '').toString().trim();
  function showErr(m) { err.textContent = m; err.style.display = 'block'; }
  function hideErr()  { err.style.display = 'none'; }

  // =========================================================
  // Google Places (new API first; gracefully falls back to old)
  // AND: Freeform entry path if Places isn’t available
  // =========================================================
  let sessionToken,
      AutocompleteSuggestion = null,        // NEW API class (where available)
      oldAutocompleteService = null,        // Legacy AutocompleteService
      oldPlacesService       = null;        // Legacy PlacesService

  function initPlaces () {
    if (!('google' in window) || !google.maps || !google.maps.places) {
      // Google script missing or blocked — still allow freeform adding
      console.warn('[Places] not available — freeform entry enabled');
      enableFreeformEnter();
      return;
    }

    // Try new API first
    AutocompleteSuggestion = google.maps.places.AutocompleteSuggestion || null;

    // Fallback to classic
    if (!AutocompleteSuggestion) {
      oldAutocompleteService = new google.maps.places.AutocompleteService();
      oldPlacesService = new google.maps.places.PlacesService(document.createElement('div'));
    }

    newSessionToken();
    enableFreeformEnter(); // even with Places, allow Enter to add typed address
  }

  // Optional fallback poll if callback never fires (ad blockers / race)
  function startPlacesFallbackPoll () {
    let tries = 0, max = 40;
    const t = setInterval(() => {
      tries++;
      if (window.google?.maps?.places) {
        clearInterval(t);
        try { initPlaces(); } catch (e) { console.error('[Places] init failed', e); }
      } else if (tries >= max) {
        clearInterval(t);
        console.warn('[Places] not available after polling — freeform only');
        enableFreeformEnter();
      }
    }, 100);
  }

  function newSessionToken () {
    if (window.google?.maps?.places?.AutocompleteSessionToken) {
      sessionToken = new google.maps.places.AutocompleteSessionToken();
    } else {
      sessionToken = undefined;
    }
  }

  function renderSuggestions (items) {
    addrResults.innerHTML = '';
    if (!items || !items.length) {
      addrResults.style.display = 'none';
      return;
    }
    items.forEach((pred) => {
      const li = document.createElement('li');
      li.role = 'option';
      li.tabIndex = 0;
      li.style.cursor = 'pointer';
      li.style.padding = '8px';
      li.textContent = pred.formattedSuggestion || pred.description || pred.text || '';
      li.addEventListener('click', () => selectPrediction(pred));
      li.addEventListener('keydown', (e) => { if (e.key === 'Enter') selectPrediction(pred); });
      addrResults.appendChild(li);
    });
    addrResults.style.display = 'block';
  }

  async function selectPrediction (pred) {
    try {
      // New API: prediction has fetchFields()
      if (pred && typeof pred.fetchFields === 'function') {
        const { placePrediction } = await pred.fetchFields({
          fields: ['formatted_address', 'address_components', 'geometry', 'name']
        });
        return addPlaceFromNew(placePrediction);
      }
      // Old API path
      if (oldPlacesService) {
        oldPlacesService.getDetails({
          placeId: pred.place_id,
          sessionToken,
          fields: ['formatted_address', 'address_components', 'geometry', 'name']
        }, (place, status) => {
          if (status !== google.maps.places.PlacesServiceStatus.OK || !place) {
            showErr('Could not validate the address.'); return;
          }
          addPlaceFromOld(place);
        });
      }
    } catch (e) {
      console.error(e);
      showErr('Error fetching place details.');
    }
  }

  function extractComponents (components) {
    const get = (t) => (components || []).find((c) => c.types.includes(t));
    const street = [get('street_number')?.long_name || '', get('route')?.long_name || ''].filter(Boolean).join(' ').trim();
    const city   = get('locality')?.long_name || get('sublocality_level_1')?.long_name || '';
    const state  = get('administrative_area_level_1')?.short_name || '';
    const zip    = get('postal_code')?.long_name || '';
    return { street, city, state, zip };
  }

  function addPlaceFromNew (place) {
    if (!place) { showErr('Could not validate the address.'); return; }
    const { street, city, state, zip } = extractComponents(place.address_components);
    addPicked({
      label: place.formatted_address || [street || place.name || '', city, state, zip].filter(Boolean).join(', '),
      address: street || place.name || '', city, state, zip
    }, num(addrRent.value));
    afterPickReset();
  }

  function addPlaceFromOld (place) {
    const { street, city, state, zip } = extractComponents(place.address_components);
    addPicked({
      label: place.formatted_address || [street || place.name || '', city, state, zip].filter(Boolean).join(', '),
      address: street || place.name || '', city, state, zip
    }, num(addrRent.value));
    afterPickReset();
  }

  function afterPickReset () {
    addrSearch.value = '';
    addrRent.value = '';
    addrResults.innerHTML = '';
    addrResults.style.display = 'none';
    newSessionToken();
  }

  // ---------- Autocomplete typing ----------
  addrSearch.addEventListener('input', async () => {
    hideErr();
    const q = text(addrSearch.value);
    if (!q) { addrResults.style.display = 'none'; return; }

    try {
      // New API first
      if (AutocompleteSuggestion) {
        const sugg = new AutocompleteSuggestion({ sessionToken });
        const method = typeof sugg.getSuggestions === 'function' ? 'getSuggestions'
                     : typeof sugg.fetchSuggestions === 'function' ? 'fetchSuggestions'
                     : null;
        if (method) {
          const { suggestions } = await sugg[method]({
            input: q,
            sessionToken,
            types: ['address'],
            componentRestrictions: { country: ['us'] }
          });
          return renderSuggestions(suggestions);
        }
      }
      // Old API fallback
      if (oldAutocompleteService) {
        oldAutocompleteService.getPlacePredictions({
          input: q,
          sessionToken,
          types: ['address'],
          componentRestrictions: { country: ['us'] }
        }, (preds, status) => {
          if (status !== google.maps.places.PlacesServiceStatus.OK) {
            addrResults.style.display = 'none'; return;
          }
          renderSuggestions(preds);
        });
      }
    } catch (e) {
      console.error(e);
      addrResults.style.display = 'none';
    }
  });

  clearBtn.addEventListener('click', () => {
    addrSearch.value = '';
    addrRent.value = '';
    addrResults.innerHTML = '';
    addrResults.style.display = 'none';
  });

  // ---------- Freeform entry support ----------
  // Press Enter in the address box to add the typed text even if Places is down.
  function enableFreeformEnter () {
    addrSearch.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const raw = text(addrSearch.value);
      if (!raw) return;

      // If a suggestions list is open, prefer clicking the first suggestion
      const first = addrResults.querySelector('li');
      if (first) { first.click(); return; }

      // Otherwise, parse freeform "Addr, City, ST 12345"
      const parsed = parseFreeformAddress(raw);
      addPicked({
        label: raw,
        address: parsed.address,
        city: parsed.city,
        state: parsed.state,
        zip: parsed.zip
      }, num(addrRent.value));
      afterPickReset();
    }, { once: false });
  }

  function parseFreeformAddress (raw) {
    // Very light parser: "2450 Clairview St, Alpharetta, GA 30009"
    const out = { address: raw, city: '', state: '', zip: '' };
    try {
      const parts = raw.split(',').map(s => s.trim());
      if (parts.length >= 1) out.address = parts[0];
      if (parts.length >= 2) out.city    = parts[1];
      if (parts.length >= 3) {
        // Last part might be "GA 30009" or just "GA"
        const m = parts[2].match(/([A-Za-z]{2})\s+(\d{5})(?:-\d{4})?/) || parts[2].match(/([A-Za-z]{2})/);
        if (m) {
          out.state = (m[1] || '').toUpperCase();
          if (m[2]) out.zip = m[2];
        }
      }
    } catch {}
    return out;
  }

  // ---------- Picked list ----------
  function pickedItems () {
    return Array.from(pickedList.querySelectorAll('[data-item]')).map(el => ({
      label: el.querySelector('[data-label]')?.textContent || '',
      address: el.dataset.address,
      city: el.dataset.city,
      state: el.dataset.state,
      zip: el.dataset.zip,
      rent: Number(el.querySelector('[data-rent]')?.value || 0)
    }));
  }

  function addPicked (addr, rent) {
    const count = pickedList.querySelectorAll('[data-item]').length;
    if (count >= 10) { showErr('You can add up to 10 properties.'); return; }

    const node = pickedTpl.content.firstElementChild.cloneNode(true);
    node.querySelector('[data-label]').textContent = addr.label || [addr.address, addr.city, addr.state, addr.zip].filter(Boolean).join(', ');
    node.querySelector('[data-meta]').textContent  = [addr.city, addr.state, addr.zip].filter(Boolean).join(', ');
    node.querySelector('[data-rent]').value = rent || 0;

    node.dataset.address = addr.address || '';
    node.dataset.city    = addr.city || '';
    node.dataset.state   = addr.state || '';
    node.dataset.zip     = addr.zip || '';

    node.querySelector('[data-remove]').addEventListener('click', () => { node.remove(); updatePickedCount(); });

    pickedList.appendChild(node);
    updatePickedCount();
  }

  function updatePickedCount () {
    const c = pickedList.querySelectorAll('[data-item]').length;
    pickedCount.textContent = `${c} of 10 selected`;
  }

  // ---------- Server calls ----------
  async function postJSON (url, body) {
    const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) { const t = await res.text().catch(() => ''); throw new Error(t || `Request failed: ${res.status}`); }
    return res.json();
  }

  async function analyzeOne (shared, picked) {
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

  // ---------- Render ----------
  function renderTable (results, order, aiMeta) {
    portTbl.innerHTML = '';
    const list = order ? order.map(i => results[i]) : results;

    list.forEach((r, i) => {
      const addr = r.address || [r.inputs?.address, r.inputs?.city, r.inputs?.state, r.inputs?.zip].filter(Boolean).join(', ');
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${i + 1}</td>
        <td>${addr}</td>
        <td>${dollars(r.metrics?.price)}</td>
        <td>${dollars(r.inputs?.rent || r.prefetch?.ai?.rent?.est || 0)}</td>
        <td>${dollars(r.metrics?.cashFlowMonthly)}</td>
        <td>${Number(r.metrics?.capRate || 0).toFixed(2)}%</td>
        <td>${Number(r.metrics?.cashOnCash || 0).toFixed(1)}%</td>
        <td>${Number(r.metrics?.dscr || 0).toFixed(2)}</td>`;
      portTbl.appendChild(tr);
    });

    portNote.textContent = aiMeta?.ok
      ? (aiMeta.summary ? `Ranked by AI · ${aiMeta.summary}` : 'Ranked by AI (investment attractiveness).')
      : 'AI ranking unavailable — sorted by Cash-on-Cash then Monthly Cash Flow.';

    portRes.style.display = 'block';
  }

  // ---------- Form submit ----------
  form.addEventListener('submit', async (e) => {
    e.preventDefault(); hideErr(); portRes.style.display = 'none'; portTbl.innerHTML = '';

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
      if (!items.length) throw new Error('Please add at least one address.');
      if (items.length > 10) throw new Error('Up to 10 properties supported.');

      submitBtn.disabled = true; submitBtn.textContent = 'Analyzing…';

      const results = [];
      for (const p of items) {
        const out = await analyzeOne(shared, p);
        results.push(out);
      }

      // Rank on server
      let rankResp;
      try {
        rankResp = await postJSON(`${FN_BASE}/api/portfolio-rank`, { items: results, aiMode: 'auto' });
        const order = Array.isArray(rankResp.order) ? rankResp.order : null;
        renderTable(results, order, { ok: !!rankResp.ok, summary: rankResp.summary });
      } catch {
        // Client fallback sort
        const idx = results.map((_, i) => i);
        idx.sort((i, j) => {
          const a = results[i].metrics || {}, b = results[j].metrics || {};
          const c1 = Number(a.cashOnCash || 0), c2 = Number(b.cashOnCash || 0);
          if (c2 !== c1) return c2 - c1;
          const f1 = Number(a.cashFlowMonthly || 0), f2 = Number(b.cashFlowMonthly || 0);
          return f2 - f1;
        });
        renderTable(results, idx, { ok: false, summary: '' });
      }

      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event: 'portfolio_analyzer_submit', count: items.length });

    } catch (ex) {
      showErr(ex.message || 'Something went wrong.');
    } finally {
      submitBtn.disabled = false; submitBtn.textContent = 'Analyze & Rank';
    }
  });

  // Expose init for Google callback AND start a fallback poll
  window.initPortfolioPlaces = initPlaces;
  startPlacesFallbackPoll();
})();