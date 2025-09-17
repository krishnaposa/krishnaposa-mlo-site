// /assets/js/rent-analyzer.js
(function () {
  const form = document.getElementById('rental-form');
  const submitBtn = document.getElementById('submitBtn');
  const err = document.getElementById('err');
  const result = document.getElementById('result');

  // Mini-metric nodes
  const mmCash = document.getElementById('mm_cashflow');
  const mmCap = document.getElementById('mm_caprate');
  const mmCoC = document.getElementById('mm_coc');
  const mmDSCR = document.getElementById('mm_dscr');

  // Tables
  const monthlyTbody = document.querySelector('#monthlyTable tbody');
  const annualTbody = document.querySelector('#annualTable tbody');
  const sensTbody = document.querySelector('#sensitivityTable tbody');

  // Summary
  const summary = document.getElementById('summary');

  // ---------- Helpers ----------
  const dollars = (n) =>
    Number(n ?? 0).toLocaleString(undefined, { style: 'currency', currency: 'USD' });
  const pct = (n, digits = 2) => `${Number(n ?? 0).toFixed(digits)}%`;
  const toNum = (v) => (v === '' || v == null ? 0 : Number(v));

  // Amortized monthly payment (principal+interest only)
  function pmt(ratePct, nYears, loanAmount) {
    const r = ratePct / 100 / 12;
    const n = nYears * 12;
    if (r === 0) return loanAmount / n;
    return (loanAmount * r) / (1 - Math.pow(1 + r, -n));
  }

  function clearTables() {
    monthlyTbody.innerHTML = '';
    annualTbody.innerHTML = '';
    sensTbody.innerHTML = '';
  }

  function validateInputs(data) {
    const price = toNum(data.purchasePrice);
    const downPct = toNum(data.downPct);
    const rate = toNum(data.rate);
    const termYears = toNum(data.termYears);
    const rent = toNum(data.rent);

    if (!document.getElementById('consent').checked) {
      throw new Error('Please accept the educational-only consent to proceed.');
    }
    if (!price || price <= 0) throw new Error('Enter a valid Purchase Price.');
    if (downPct < 0 || downPct > 100) throw new Error('Down Payment (%) must be between 0 and 100.');
    if (!rate || rate <= 0) throw new Error('Enter a valid Interest Rate (%).');
    if (!termYears || termYears <= 0) throw new Error('Select a valid Term (years).');
    if (!rent || rent <= 0) throw new Error('Enter a valid target Monthly Rent.');
  }

  // Local calculator (used as fallback or to normalize AI output)
  function localAnalyze(data) {
    const price = toNum(data.purchasePrice);
    const downPct = toNum(data.downPct);
    const rate = toNum(data.rate);
    const years = toNum(data.termYears);

    const rent = toNum(data.rent);
    const otherIncome = toNum(data.otherIncome);
    const vacancyPct = toNum(data.vacancyPct);

    const taxAnnual = toNum(data.taxAnnual);
    const insAnnual = toNum(data.insAnnual);
    const hoaMonthly = toNum(data.hoaMonthly);
    const pmPct = toNum(data.pmPct);
    const maintPct = toNum(data.maintPct);
    const utilitiesMonthly = toNum(data.utilitiesMonthly);

    const pointsPct = toNum(data.pointsPct);
    const closingCosts = toNum(data.closingCosts);

    const downPayment = price * (downPct / 100);
    const loanAmount = Math.max(0, price - downPayment);
    const pointsCost = loanAmount * (pointsPct / 100);

    const pi = pmt(rate, years, loanAmount); // monthly P&I
    const monthlyTaxes = taxAnnual / 12;
    const monthlyInsurance = insAnnual / 12;

    const grossRent = rent + otherIncome;
    const vacancy = grossRent * (vacancyPct / 100);
    const management = rent * (pmPct / 100); // usually % of collected rent
    const maintenance = rent * (maintPct / 100);

    const totalMonthlyIncome = grossRent - vacancy;
    const fixedMonthly = pi + monthlyTaxes + monthlyInsurance + hoaMonthly + utilitiesMonthly;
    const variableMonthly = management + maintenance;
    const totalMonthlyExpenses = fixedMonthly + variableMonthly;

    const noiMonthly = totalMonthlyIncome - (monthlyTaxes + monthlyInsurance + hoaMonthly + utilitiesMonthly + management + maintenance);
    const cashFlowMonthly = totalMonthlyIncome - totalMonthlyExpenses;

    const priceForCap = price > 0 ? price : 1;
    const capRate = (noiMonthly * 12 * 100) / priceForCap;

    const totalCashToClose = downPayment + closingCosts + pointsCost;
    const annualCashFlow = cashFlowMonthly * 12;
    const cashOnCash = totalCashToClose > 0 ? (annualCashFlow / totalCashToClose) * 100 : 0;

    const dscr = pi > 0 ? noiMonthly / pi : 0; // monthly DSCR

    const sensitivity = [-100, 0, 100].map((delta) => {
      const newRent = rent + delta;
      const newGross = newRent + otherIncome;
      const newVac = newGross * (vacancyPct / 100);
      const newMgmt = newRent * (pmPct / 100);
      const newMaint = newRent * (maintPct / 100);
      const newIncome = newGross - newVac;
      const newNOIMonthly = newIncome - (monthlyTaxes + monthlyInsurance + hoaMonthly + utilitiesMonthly + newMgmt + newMaint);
      const newCash = newIncome - (pi + monthlyTaxes + monthlyInsurance + hoaMonthly + utilitiesMonthly + newMgmt + newMaint);
      const newDSCR = pi > 0 ? newNOIMonthly / pi : 0;
      return { rent: newRent, cashFlowMonthly: newCash, dscr: newDSCR };
    });

    return {
      address: [data.address, data.city, data.state, data.zip].filter(Boolean).join(', '),
      inputs: data,
      metrics: {
        price,
        downPayment,
        loanAmount,
        pointsCost,
        closingCosts,
        totalCashToClose,
        piMonthly: pi,
        monthlyIncome: totalMonthlyIncome,
        monthlyExpenses: {
          vacancy,
          taxes: monthlyTaxes,
          insurance: monthlyInsurance,
          hoa: hoaMonthly,
          management,
          maintenance,
          utilities: utilitiesMonthly,
          pi: pi
        },
        noiMonthly,
        noiAnnual: noiMonthly * 12,
        capRate,
        cashFlowMonthly,
        cashFlowAnnual: annualCashFlow,
        cashOnCash,
        dscr
      },
      sensitivity,
      explanation:
        'Calculated locally using your inputs. Results are estimates and for education only.',
      rentalRestrictions: {
        hasHoa: hoaMonthly > 0,
        notes: data.rentalRules || 'Unknown'
      }
    };
  }

  // Render output into the DOM
  function render(out) {
    // Summary
    const a = out.address || '';
    const i = out.inputs || {};
    summary.innerHTML =
      `<p><strong>Property</strong>: ${a || '—'}</p>
       <p><strong>Scenario</strong>: ${i.propertyType || 'Property'} · Price ${dollars(out.metrics.price)} · ` +
      `Down ${pct(i.downPct || 0)} · Rate ${pct(i.rate || 0)} · Term ${i.termYears || '—'} yrs</p>
       <p class="note">HOA/Rules: ${out.rentalRestrictions?.notes || 'Unknown'}</p>`;

    // Mini metrics
    mmCash.textContent = dollars(out.metrics.cashFlowMonthly);
    mmCap.textContent = pct(out.metrics.capRate);
    mmCoC.textContent = pct(out.metrics.cashOnCash);
    mmDSCR.textContent = (out.metrics.dscr ?? 0).toFixed(2);

    // Monthly table
    clearTables();
    const m = out.metrics;
    const me = m.monthlyExpenses || {};
    const monthlyRows = [
      ['Rent + Other (after vacancy)', dollars(m.monthlyIncome)],
      ['Principal & Interest', dollars(me.pi ?? m.piMonthly)],
      ['Taxes', dollars(me.taxes)],
      ['Insurance', dollars(me.insurance)],
      ['HOA', dollars(me.hoa)],
      ['Management', dollars(me.management)],
      ['Maintenance/CapEx', dollars(me.maintenance)],
      ['Utilities', dollars(me.utilities)],
      ['Vacancy (line item)', dollars(me.vacancy)],
      ['Total Expenses (mo)', dollars((me.pi ?? m.piMonthly) + me.taxes + me.insurance + me.hoa + me.management + me.maintenance + me.utilities)],
      ['Cash Flow (mo)', dollars(m.cashFlowMonthly)]
    ];
    monthlyRows.forEach(([k, v]) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${k}</td><td>${v}</td>`;
      monthlyTbody.appendChild(tr);
    });

    // Annual table
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
    annualRows.forEach(([k, v]) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${k}</td><td>${v}</td>`;
      annualTbody.appendChild(tr);
    });

    // Sensitivity
    (out.sensitivity || []).forEach((row) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${dollars(row.rent)}</td><td>${dollars(row.cashFlowMonthly)}</td><td>${(row.dscr ?? 0).toFixed(2)}</td>`;
      sensTbody.appendChild(tr);
    });

    result.style.display = 'block';
  }

  // ---------- Main submit ----------
  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    err.style.display = 'none';
    result.style.display = 'none';
    clearTables();

    // Collect inputs
    const data = Object.fromEntries(new FormData(form).entries());

    try {
      validateInputs(data);

      submitBtn.disabled = true;
      submitBtn.textContent = 'Analyzing…';

      // IMPORTANT: Replace with your deployed AI endpoint
      // Suggestion: Cloudflare Worker / Azure Function / Vercel Edge
      const API_URL = 'https://rental-analyzer.krishna-posa.workers.dev';

      // Shape we send to AI (add anything else your model needs)
      const payload = {
        type: 'rental_analysis',
        inputs: {
          address: data.address,
          city: data.city,
          state: data.state,
          zip: data.zip,
          propertyType: data.propertyType,
          units: Number(data.units || 1),

          purchasePrice: Number(data.purchasePrice),
          downPct: Number(data.downPct),
          rate: Number(data.rate),
          termYears: Number(data.termYears),
          closingCosts: Number(data.closingCosts || 0),
          pointsPct: Number(data.pointsPct || 0),

          rent: Number(data.rent),
          otherIncome: Number(data.otherIncome || 0),
          vacancyPct: Number(data.vacancyPct || 5),

          taxAnnual: Number(data.taxAnnual || 0),
          insAnnual: Number(data.insAnnual || 0),
          hoaMonthly: Number(data.hoaMonthly || 0),
          pmPct: Number(data.pmPct || 0),
          maintPct: Number(data.maintPct || 0),
          utilitiesMonthly: Number(data.utilitiesMonthly || 0),

          hoaName: data.hoaName || '',
          rentalRules: data.rentalRules || ''
        }
      };

      let out;

      try {
        const res = await fetch(API_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error(`Server error (${res.status})`);

        // Expected AI response shape (example):
        // {
        //   "address": "3739 Jamestown Ct, Atlanta, GA 30340",
        //   "metrics": { price, downPayment, loanAmount, piMonthly, monthlyIncome,
        //                monthlyExpenses:{pi,taxes,insurance,hoa,management,maintenance,utilities,vacancy},
        //                noiMonthly, noiAnnual, cashFlowMonthly, cashFlowAnnual, capRate, cashOnCash, dscr,
        //                pointsCost, closingCosts, totalCashToClose },
        //   "sensitivity":[{"rent":1984,"cashFlowMonthly":..,"dscr":..}, ...],
        //   "rentalRestrictions":{"hasHoa":false,"notes":"No HOA / No Restrictions"},
        //   "explanation":"…"
        // }
        const ai = await res.json();

        // If the AI sends partials, normalize with local calculator using its (possibly corrected) inputs.
        // Prefer AI metrics if present; otherwise backfill.
        const mergedInputs = { ...(payload.inputs || {}), ...((ai.inputs) || {}) };
        const fallback = localAnalyze(mergedInputs);

        out = {
          address: ai.address || fallback.address,
          inputs: mergedInputs,
          metrics: { ...fallback.metrics, ...(ai.metrics || {}) },
          sensitivity: ai.sensitivity || fallback.sensitivity,
          rentalRestrictions: ai.rentalRestrictions || fallback.rentalRestrictions,
          explanation: ai.explanation || fallback.explanation
        };
      } catch (networkOrAIError) {
        // If AI is down/unavailable, do local math so the tool still works.
        out = localAnalyze(payload.inputs);
      }

      render(out);

      // GTM event
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({
        event: 'rental_analyzer_submit',
        propertyType: data.propertyType || '',
        state: data.state || '',
        price: Number(data.purchasePrice || 0),
        downPct: Number(data.downPct || 0),
        rate: Number(data.rate || 0),
        termYears: Number(data.termYears || 0),
        rent: Number(data.rent || 0),
        hoaMonthly: Number(data.hoaMonthly || 0)
      });

      // Optional: scroll to results on mobile
      result.scrollIntoView({ behavior: 'smooth', block: 'start' });

    } catch (ex) {
      err.textContent = ex.message || 'Something went wrong. Please review your inputs.';
      err.style.display = 'block';
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Analyze Deal';
    }
  });
})();