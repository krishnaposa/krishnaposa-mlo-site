(function(){
  const form      = document.getElementById('rental-form');
  const submitBtn = document.getElementById('submitBtn');
  const err       = document.getElementById('err');
  const result    = document.getElementById('result');

  // IMPORTANT: set your deployed Azure Functions base
  const API_BASE = 'https://<YOUR-FUNCTION-APP>.azurewebsites.net/api';

  // helpers
  const dollars = (n)=> Number(n||0).toLocaleString(undefined,{style:'currency',currency:'USD'});
  const pct     = (n, d=2)=> `${Number(n||0).toFixed(d)}%`;
  const num     = (v)=> { const x = Number(v); return Number.isFinite(x) ? x : 0; };
  const text    = (v)=> (v ?? '').toString().trim();

  function getInputs() {
    const fd = new FormData(form);
    return {
      address: text(fd.get('address')),
      city: text(fd.get('city')),
      state: text(fd.get('state')),
      zip: text(fd.get('zip')),
      propertyType: text(fd.get('propertyType')),
      units: num(fd.get('units') || 1),

      purchasePrice: num(fd.get('purchasePrice')),
      downPct: num(fd.get('downPct')),
      rate: num(fd.get('rate')),
      termYears: num(fd.get('termYears')),
      closingCosts: num(fd.get('closingCosts')),
      pointsPct: num(fd.get('pointsPct')),

      rent: num(fd.get('rent')),
      otherIncome: num(fd.get('otherIncome')),
      vacancyPct: num(fd.get('vacancyPct') || 5),

      taxAnnual: num(fd.get('taxAnnual')),
      insAnnual: num(fd.get('insAnnual')),
      hoaMonthly: num(fd.get('hoaMonthly')),
      pmPct: num(fd.get('pmPct')),
      maintPct: num(fd.get('maintPct')),
      utilitiesMonthly: num(fd.get('utilitiesMonthly')),

      hoaName: text(fd.get('hoaName')),
      rentalRules: text(fd.get('rentalRules'))
    };
  }

  function buildSummary(inputs, out, pre) {
    const addr = [inputs.address, inputs.city, inputs.state, inputs.zip].filter(Boolean).join(', ');
    const ltv = (out.metrics.loanAmount / Math.max(out.metrics.price,1)) * 100;
    const rentSrc = out.rentSource ? out.rentSource.replace('_',' ') : (out.prefetchUsed ? 'ai estimate' : 'user input');

    return `
      <p><strong>Property</strong>: ${addr || '—'} · <strong>Type</strong>: ${inputs.propertyType || '—'} · <strong>Units</strong>: ${inputs.units||1}</p>
      <p><strong>Price</strong>: ${dollars(out.metrics.price)} · <strong>Loan</strong>: ${dollars(out.metrics.loanAmount)} · <strong>LTV</strong>: ${ltv.toFixed(1)}% · <strong>Rate</strong>: ${inputs.rate || '—'}% / ${inputs.termYears||'—'}y</p>
      <p class="muted">Taxes source: ${(pre?.taxes?.source || 'prefetch')} · Rent source: ${rentSrc}</p>
    `;
  }

  function fillTables(out){
    // mini metrics
    document.getElementById('mm_cashflow').textContent = dollars(out.metrics.cashFlowMonthly);
    document.getElementById('mm_caprate').textContent  = pct(out.metrics.capRate, 2);
    document.getElementById('mm_coc').textContent      = pct(out.metrics.cashOnCash, 1);
    document.getElementById('mm_dscr').textContent     = (out.metrics.dscr || 0).toFixed(2);

    // monthly breakdown
    const mt = document.querySelector('#monthlyTable tbody');
    mt.innerHTML = '';
    const m = out.metrics;
    const exp = m.monthlyExpenses || {};
    [
      ['Effective Income', m.monthlyIncome],
      ['Vacancy', exp.vacancy],
      ['Taxes', exp.taxes],
      ['Insurance', exp.insurance],
      ['HOA', exp.hoa],
      ['Mgmt (PM)', exp.management],
      ['Maintenance/CapEx', exp.maintenance],
      ['Utilities', exp.utilities],
      ['P&I (Mortgage)', exp.pi],
      ['NOI', m.noiMonthly],
      ['Cash Flow', m.cashFlowMonthly]
    ].forEach(([k,v])=>{
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${k}</td><td>${dollars(v)}</td>`;
      mt.appendChild(tr);
    });

    // annual summary
    const at = document.querySelector('#annualTable tbody');
    at.innerHTML = '';
    [
      ['NOI (Annual)', m.noiAnnual],
      ['Debt Service (Annual)', m.debtServiceAnnual || (m.monthlyExpenses?.pi*12)],
      ['Cash Flow (Annual)', m.cashFlowAnnual],
      ['Cap Rate', pct(m.capRate, 2)],
      ['Cash-on-Cash', pct(m.cashOnCash, 2)],
    ].forEach(([k,v])=>{
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${k}</td><td>${typeof v === 'string' && v.endsWith('%') ? v : (k.includes('Rate') || k.includes('Cash-on-Cash') ? v : dollars(v))}</td>`;
      at.appendChild(tr);
    });

    // sensitivity
    const st = document.querySelector('#sensitivityTable tbody');
    st.innerHTML = '';
    (out.sensitivity || []).forEach(row=>{
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${dollars(row.rent)}</td><td>${dollars(row.cashFlowMonthly)}</td><td>${(row.dscr||0).toFixed(2)}</td>`;
      st.appendChild(tr);
    });
  }

  function validate(inputs){
    if (!document.getElementById('consent').checked) {
      throw new Error('Please accept the educational-only consent to proceed.');
    }
    if (!inputs.purchasePrice || !inputs.rate || !inputs.termYears) {
      throw new Error('Please provide Purchase Price, Interest Rate, and Term.');
    }
  }

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

  form?.addEventListener('submit', async (e)=>{
    e.preventDefault();
    err.style.display = 'none';
    result.style.display = 'none';

    try {
      const inputs = getInputs();
      validate(inputs);

      submitBtn.disabled = true;
      submitBtn.textContent = 'Analyzing…';

      // 1) Server-side PREFETCH (does all-expense AI + rent context + county/fallback merge)
      const prefetch = await callJSON(`${API_BASE}/rent-prefetch`, { inputs: {
        address: inputs.address,
        city: inputs.city,
        state: inputs.state,
        zip: inputs.zip,
        county: undefined,
        propertyType: inputs.propertyType,
        units: inputs.units,
        purchasePrice: inputs.purchasePrice,
        yearBuilt: undefined,
        sqft: undefined,
        ownerOccupied: false
      }});

      // 2) ANALYZE — user inputs (override) + the entire prefetch object
      const out = await callJSON(`${API_BASE}/rent-analyze`, {
        inputs,
        prefetch
      });

      // Render
      document.getElementById('summary').innerHTML = buildSummary(inputs, out, prefetch);
      fillTables(out);
      result.style.display = 'block';

      // GTM/analytics
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({
        event: 'rental_analyzer_submit',
        state: inputs.state,
        city: inputs.city,
        propertyType: inputs.propertyType || 'unknown',
        units: inputs.units || 1,
        price: inputs.purchasePrice,
        downPct: inputs.downPct,
        rate: inputs.rate,
        termYears: inputs.termYears,
        usedPrefetch: !!out.prefetchUsed
      });

    } catch (ex) {
      err.textContent = ex.message || 'Something went wrong.';
      err.style.display = 'block';
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Analyze Deal';
    }
  });
})();