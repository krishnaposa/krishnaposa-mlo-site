(function () {
  const FN_BASE = 'https://rent-analyzer-fn-eheqhra2d6bwd6fm.canadacentral-01.azurewebsites.net';
  const form = document.getElementById('rental-form');
  const submitBtn = document.getElementById('submitBtn');
  const err = document.getElementById('err');
  const result = document.getElementById('result');

  const mmCash = document.getElementById('mm_cashflow');
  const mmCap  = document.getElementById('mm_caprate');
  const mmCoC  = document.getElementById('mm_coc');
  const mmDSCR = document.getElementById('mm_dscr');
  // New (optional) mini-metrics (render only if present in HTML)
  const mmTR  = document.getElementById('mm_totalreturn');
  const mmIRR = document.getElementById('mm_irr');
  const assumptionLine = document.getElementById('assumptionLine');

  const monthlyTbody = document.querySelector('#monthlyTable tbody');
  const annualTbody  = document.querySelector('#annualTable tbody');
  const sensTbody    = document.querySelector('#sensitivityTable tbody');
  const summary      = document.getElementById('summary');

  const dollars = (n)=> Number(n ?? 0).toLocaleString(undefined, { style:'currency', currency:'USD' });
  const pct     = (n,d=2)=> `${Number(n ?? 0).toFixed(d)}%`;
  const toNum   = (v)=> (v === '' || v == null ? 0 : Number(v));
  const clamp   = (x, lo, hi) => Math.max(lo, Math.min(hi, x));

  function pmt(ratePct, years, loanAmount){
    const r = ratePct/100/12, n = years*12;
    if (!r) return loanAmount/n;
    return (loanAmount*r)/(1-Math.pow(1+r,-n));
  }
  function clearTables(){ monthlyTbody.innerHTML=''; annualTbody.innerHTML=''; sensTbody.innerHTML=''; }

  function validateInputs(d){
    if (!document.getElementById('consent').checked) throw new Error('Please accept the educational-only consent to proceed.');
    if (!toNum(d.purchasePrice)) throw new Error('Enter a valid Purchase Price.');
    if (!toNum(d.rate))          throw new Error('Enter a valid Interest Rate (%).');
    if (!toNum(d.termYears))     throw new Error('Select a valid Term (years).');
    if (toNum(d.downPct) < 0 || toNum(d.downPct) > 100) throw new Error('Down Payment (%) must be between 0 and 100.');
  }

  // --- IRR via bisection (robust) ---
  function npv(rate, cashflows){
    let v = 0;
    for (let t = 0; t < cashflows.length; t++){
      v += cashflows[t] / Math.pow(1 + rate, t);
    }
    return v;
  }
  function irr(cashflows){
    // bracket IRR between -99% and 500%
    let lo = -0.99, hi = 5.0;
    let fLo = npv(lo, cashflows), fHi = npv(hi, cashflows);
    if (!isFinite(fLo) || !isFinite(fHi) || fLo * fHi > 0) return 0;
    for (let i=0;i<80;i++){
      const mid = (lo+hi)/2, fMid = npv(mid, cashflows);
      if (Math.abs(fMid) < 1e-7) return mid;
      if (fLo * fMid < 0){ hi = mid; fHi = fMid; } else { lo = mid; fLo = fMid; }
    }
    return (lo+hi)/2;
  }

  // Remaining balance after X months of amortization
  function remainingBalance(ratePct, years, principal, monthsPaid){
    const r = ratePct/100/12;
    const n = years*12;
    if (r === 0) return Math.max(0, principal * (1 - monthsPaid/n));
    const payment = (principal * r) / (1 - Math.pow(1 + r, -n));
    const bal = principal * Math.pow(1 + r, monthsPaid) - payment * ((Math.pow(1 + r, monthsPaid) - 1) / r);
    return Math.max(0, bal);
  }

  // Appreciation/selling defaults
  const DEFAULT_APPRECIATION_PCT = 3.0; // %/yr
  const DEFAULT_SELLING_COST_PCT = 6.0; // % of sale price

  // Allow injection of appreciation hints
  function localAnalyze(data, apprHints = {}){
    const price  = toNum(data.purchasePrice);
    const down   = price * (toNum(data.downPct)/100);
    const loan   = Math.max(0, price - down);
    const rate   = toNum(data.rate);
    const term   = toNum(data.termYears);
    const pi     = pmt(rate, term, loan);

    const rent        = toNum(data.rent);
    const other       = toNum(data.otherIncome);
    const vacPct      = toNum(data.vacancyPct);
    const taxAnnual   = toNum(data.taxAnnual);
    const insAnnual   = toNum(data.insAnnual);
    const hoaMonthly  = toNum(data.hoaMonthly);
    const pmPct       = toNum(data.pmPct);
    const maintPct    = toNum(data.maintPct);
    const utils       = toNum(data.utilitiesMonthly);
    const pointsCost  = loan * (toNum(data.pointsPct)/100);
    const closing     = toNum(data.closingCosts);

    const monthlyTaxes = taxAnnual/12, monthlyIns = insAnnual/12;
    const gross = rent + other;
    const vac   = gross * (vacPct/100);
    const mgmt  = rent * (pmPct/100);
    const maint = rent * (maintPct/100);

    const income = gross - vac;
    const fixed  = pi + monthlyTaxes + monthlyIns + hoaMonthly + utils;
    const variable = mgmt + maint;
    const totalExp = fixed + variable;

    const noiMonthly = income - (monthlyTaxes + monthlyIns + hoaMonthly + utils + mgmt + maint);
    const cashFlowMonthly = income - totalExp;

    const capRate = (noiMonthly*12*100) / (price || 1);
    const totalCashToClose = down + closing + pointsCost;
    const coc = totalCashToClose ? (cashFlowMonthly*12/totalCashToClose)*100 : 0;
    const dscr = pi ? (noiMonthly/pi) : 0;

    // ---- 5-year projections (with appreciation) ----
    // Appreciation hint can come as:
    //   apprHints.appreciationAnnualPct
    //   apprHints.appreciationPct
    //   apprHints.aoai_appreciation (number or string)
    const apprPct = clamp(
      toNum(
        apprHints.appreciationAnnualPct ??
        apprHints.appreciationPct ??
        apprHints.aoai_appreciation ??
        DEFAULT_APPRECIATION_PCT
      ), -20, 20
    );
    const sellingCostPct = clamp(toNum(apprHints.sellingCostPct ?? DEFAULT_SELLING_COST_PCT), 0, 12);

    const months5 = Math.min(60, term*12);
    const balAfter5 = remainingBalance(rate, term, loan, months5);
    const principalPaid5 = Math.max(0, loan - balAfter5);

    const valueAfter5 = price * Math.pow(1 + apprPct/100, 5);
    const sellingCosts = valueAfter5 * (sellingCostPct/100);
    const netSaleProceeds = Math.max(0, valueAfter5 - sellingCosts - balAfter5);

    const annualCF = cashFlowMonthly * 12;
    const cashFlow5y = annualCF * 5;
    const totalGain5y = cashFlow5y + (netSaleProceeds - totalCashToClose);
    const totalReturnPct5y = totalCashToClose > 0 ? (totalGain5y / totalCashToClose) * 100 : 0;

    const cfs = [-totalCashToClose, annualCF, annualCF, annualCF, annualCF, annualCF + netSaleProceeds];
    const irr5y = irr(cfs) * 100;

    const sensitivity = [-100,0,100].map(delta=>{
      const r2 = rent + delta;
      const g2 = r2 + other;
      const v2 = g2*(vacPct/100);
      const m2 = r2*(pmPct/100);
      const x2 = r2*(maintPct/100);
      const inc2 = g2 - v2;
      const noi2 = inc2 - (monthlyTaxes + monthlyIns + hoaMonthly + utils + m2 + x2);
      const cf2  = inc2 - (pi + monthlyTaxes + monthlyIns + hoaMonthly + utils + m2 + x2);
      return { rent:r2, cashFlowMonthly:cf2, dscr: (pi? noi2/pi : 0) };
    });

    return {
      address: [data.address, data.city, data.state, data.zip].filter(Boolean).join(', '),
      inputs: data,
      metrics: {
        price,
        downPayment: down,
        loanAmount: loan,
        pointsCost,
        closingCosts: closing,
        totalCashToClose: totalCashToClose,
        piMonthly: pi,
        monthlyIncome: income,
        monthlyExpenses: { vacancy: vac, taxes: monthlyTaxes, insurance: monthlyIns, hoa: hoaMonthly, management: mgmt, maintenance: maint, utilities: utils, pi },
        noiMonthly,
        noiAnnual: noiMonthly*12,
        capRate,
        cashFlowMonthly,
        cashFlowAnnual: cashFlowMonthly*12,
        cashOnCash: coc,
        dscr,

        // 5y projections
        appreciationAnnualPct: apprPct,
        sellingCostPct,
        valueAfter5,
        principalPaid5,
        cashFlow5y,
        netSaleProceeds,
        totalReturnPctProjected: totalReturnPct5y,
        irr5y
      },
      sensitivity,
      explanation: 'Calculated locally from your inputs.',
      rentalRestrictions: { hasHoa: hoaMonthly>0, notes: data.rentalRules || 'Unknown' }
    };
  }

  function render(out){
    const a = out.address || '';
    const i = out.inputs || {};
    summary.innerHTML =
      `<p><strong>Property</strong>: ${a || '—'}</p>
       <p><strong>Scenario</strong>: ${i.propertyType || 'Property'} · Price ${dollars(out.metrics.price)} · Down ${pct(i.downPct||0)} · Rate ${pct(i.rate||0)} · Term ${i.termYears||'—'} yrs</p>
       <p class="note">HOA/Rules: ${out.rentalRestrictions?.notes || 'Unknown'}</p>`;

    // Mini metrics (existing)
    mmCash && (mmCash.textContent = dollars(out.metrics.cashFlowMonthly));
    mmCap  && (mmCap.textContent  = pct(out.metrics.capRate));
    mmCoC  && (mmCoC.textContent  = pct(out.metrics.cashOnCash));
    mmDSCR && (mmDSCR.textContent = (out.metrics.dscr ?? 0).toFixed(2));

    // NEW optional mini metrics (render only if the elements exist)
    if (mmTR)  mmTR.textContent  = pct(out.metrics.totalReturnPctProjected ?? 0, 1);
    if (mmIRR) mmIRR.textContent = pct(out.metrics.irr5y ?? 0, 2);

    // Assumption line if present
    if (assumptionLine) {
      const ap = out.metrics.appreciationAnnualPct;
      const sc = out.metrics.sellingCostPct;
      assumptionLine.textContent = `Assumptions: Appreciation ${pct(ap ?? 3.0, 1)} per year, Selling costs ${pct(sc ?? 6.0, 1)} at sale in year 5.`;
    }

    clearTables();
    const m = out.metrics, me = m.monthlyExpenses || {};
    [
      ['Rent + Other (after vacancy)', dollars(m.monthlyIncome)],
      ['Principal & Interest', dollars(me.pi ?? m.piMonthly)],
      ['Taxes', dollars(me.taxes)], ['Insurance', dollars(me.insurance)], ['HOA', dollars(me.hoa)],
      ['Management', dollars(me.management)], ['Maintenance/CapEx', dollars(me.maintenance)],
      ['Utilities', dollars(me.utilities)], ['Vacancy (line item)', dollars(me.vacancy)],
      ['Total Expenses (mo)', dollars((me.pi ?? m.piMonthly)+me.taxes+me.insurance+me.hoa+me.management+me.maintenance+me.utilities)],
      ['Cash Flow (mo)', dollars(m.cashFlowMonthly)]
    ].forEach(([k,v])=>{
      const tr = document.createElement('tr'); tr.innerHTML = `<td>${k}</td><td>${v}</td>`; monthlyTbody.appendChild(tr);
    });

    // Annual table stays compatible with your current HTML,
    // but if you later add rows for 5y items, you can show them here as well.
    const annualRows = [
      ['NOI (annual)', dollars(m.noiAnnual)],
      ['Cap Rate', pct(m.capRate)],
      ['Cash Flow (annual)', dollars(m.cashFlowAnnual)],
      ['Cash-on-Cash', pct(m.cashOnCash)],
      ['Loan Amount', dollars(m.loanAmount)],
      ['Down Payment', dollars(m.downPayment)],
      ['Points Cost', dollars(m.pointsCost)],
      ['Closing Costs (est.)', dollars(m.closingCosts)],
      ['Total Cash to Close', dollars(m.totalCashToClose)]
    ];

    // If your HTML expects 5y metrics too, append them safely:
    if ('principalPaid5' in m || 'valueAfter5' in m || 'netSaleProceeds' in m || 'totalReturnPctProjected' in m || 'irr5y' in m) {
      annualRows.push(
        ['Principal Paid (5 yr)', dollars(m.principalPaid5 ?? 0)],
        ['Value After 5 yr', dollars(m.valueAfter5 ?? 0)],
        ['Net Sale Proceeds (yr 5)', dollars(m.netSaleProceeds ?? 0)],
        ['Cash Flow (5 yr total)', dollars(m.cashFlow5y ?? 0)],
        ['5-Yr Total Return', pct(m.totalReturnPctProjected ?? 0, 1)],
        ['IRR (5 yr)', pct(m.irr5y ?? 0, 2)]
      );
    }

    annualRows.forEach(([k,v])=>{
      const tr = document.createElement('tr'); tr.innerHTML = `<td>${k}</td><td>${v}</td>`; annualTbody.appendChild(tr);
    });

    (out.sensitivity||[]).forEach(row=>{
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${dollars(row.rent)}</td><td>${dollars(row.cashFlowMonthly)}</td><td>${(row.dscr ?? 0).toFixed(2)}</td>`;
      sensTbody.appendChild(tr);
    });

    result.style.display = 'block';
  }

  async function postJSON(url, body){
    const res = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(`Server error (${res.status})`);
    return res.json();
  }

  form?.addEventListener('submit', async (e)=>{
    e.preventDefault();
    err.style.display='none'; result.style.display='none'; clearTables();

    const data = Object.fromEntries(new FormData(form).entries());
    try {
      validateInputs(data);
      submitBtn.disabled = true; submitBtn.textContent = 'Analyzing…';

      // 1) Prefetch (AI taxes+expenses+rent+appreciation)
      const prefetch = await postJSON(`${FN_BASE}/api/rent-prefetch`, {
        inputs: {
          address: data.address, city: data.city, state: data.state, zip: data.zip,
          county: data.county || undefined,
          propertyType: data.propertyType || undefined,
          units: Number(data.units || 1),
          purchasePrice: Number(data.purchasePrice || 0),
          homeValue: Number(data.purchasePrice || 0),
          ownerOccupied: false
        }
      });

      // 2) Analyze (must send {inputs, prefetch})
      const inputs = {
        address: data.address, city: data.city, state: data.state, zip: data.zip,
        propertyType: data.propertyType || undefined, units: Number(data.units || 1),
        purchasePrice: Number(data.purchasePrice),
        downPct: Number(data.downPct), rate: Number(data.rate), termYears: Number(data.termYears),
        closingCosts: Number(data.closingCosts || 0), pointsPct: Number(data.pointsPct || 0),
        rent: Number(data.rent || (prefetch?.ai?.rent?.est ?? 0)),
        otherIncome: Number(data.otherIncome || 0), vacancyPct: Number(data.vacancyPct || 5),
        taxAnnual: Number(data.taxAnnual || prefetch?.ai?.expenses?.tax_current_year_est || 0),
        insAnnual: Number(data.insAnnual || prefetch?.ai?.expenses?.insurance_annual_est || 0),
        hoaMonthly: Number(data.hoaMonthly || prefetch?.ai?.expenses?.hoa_monthly_est || 0),
        pmPct: Number(data.pmPct || prefetch?.ai?.expenses?.pm_pct_est || 0),
        maintPct: Number(data.maintPct || prefetch?.ai?.expenses?.maint_pct_est || 0),
        utilitiesMonthly: Number(data.utilitiesMonthly || prefetch?.ai?.expenses?.utilities_monthly_est || 0),
        rentalRules: data.rentalRules || ''
      };

      // extract appreciation hints from prefetch (supports both shapes)
      const apprHints = {
        appreciationAnnualPct:
          prefetch?.ai?.appreciation?.annualPct ??
          prefetch?.ai?.appreciation?.pct ??
          undefined,
        aoai_appreciation: prefetch?.ai?.aoai_appreciation, // if your backend puts it here
        sellingCostPct: prefetch?.ai?.sellingCostPct
      };

      let analyzed;
      try {
        analyzed = await postJSON(`${FN_BASE}/api/rent-analyze`, { inputs, prefetch });
      } catch {
        analyzed = localAnalyze(inputs, apprHints); // fallback
      }

      // Make sure 5y metrics exist even if server doesn't return them
      if (!analyzed.metrics) analyzed.metrics = {};
      const local = localAnalyze(inputs, apprHints);
      const m = analyzed.metrics;
      const addIfMissing = (k, v) => { if (m[k] == null) m[k] = v; };
      addIfMissing('appreciationAnnualPct', local.metrics.appreciationAnnualPct);
      addIfMissing('sellingCostPct',        local.metrics.sellingCostPct);
      addIfMissing('valueAfter5',           local.metrics.valueAfter5);
      addIfMissing('principalPaid5',        local.metrics.principalPaid5);
      addIfMissing('cashFlow5y',            local.metrics.cashFlow5y);
      addIfMissing('netSaleProceeds',       local.metrics.netSaleProceeds);
      addIfMissing('totalReturnPctProjected', local.metrics.totalReturnPctProjected);
      addIfMissing('irr5y',                 local.metrics.irr5y);
      // also ensure base fields present
      [
        'price','downPayment','loanAmount','pointsCost','closingCosts','totalCashToClose',
        'piMonthly','monthlyIncome','noiMonthly','noiAnnual','capRate','cashFlowMonthly',
        'cashFlowAnnual','cashOnCash','dscr'
      ].forEach(k=> addIfMissing(k, local.metrics[k]));

      // suit the outer object (address, inputs, sensitivity)
      if (!analyzed.address) analyzed.address = local.address;
      if (!analyzed.inputs) analyzed.inputs = inputs;
      if (!analyzed.sensitivity) analyzed.sensitivity = local.sensitivity;
      if (!analyzed.rentalRestrictions) analyzed.rentalRestrictions = local.rentalRestrictions;

      render(analyzed);
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event:'rental_analyzer_submit', state: data.state || '', price: Number(data.purchasePrice||0) });
      result.scrollIntoView({ behavior:'smooth', block:'start' });

    } catch (ex) {
      err.textContent = ex.message || 'Something went wrong. Please review your inputs.';
      err.style.display = 'block';
    } finally {
      submitBtn.disabled = false; submitBtn.textContent = 'Analyze Deal';
    }
  });
})();