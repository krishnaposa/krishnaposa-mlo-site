(function () {
  const STORAGE_KEY = 'kp_refi_monitor_profile_v1';

  function apiUrl(route) {
    const base = (window.LoanApi && window.LoanApi.base) || '/api';
    const root = base.replace(/\/$/, '');
    return root + '/' + route;
  }

  const form = document.getElementById('refi-form');
  const checkBtn = document.getElementById('checkBtn');
  const watchBtn = document.getElementById('watchBtn');
  const saveBtn = document.getElementById('saveBtn');
  const err = document.getElementById('err');
  const preview = document.getElementById('preview');
  const result = document.getElementById('result');
  const watchMsg = document.getElementById('watchMsg');

  const { evaluateRefi, fmtMoney, fmtRate } = window.RefiEval;

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function scrollToResult() {
    result?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function dollars(n) {
    return Number(n).toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
  }

  function parseRate(v) {
    if (v == null || v === '') return NaN;
    const s = String(v).trim().replace('%', '');
    return parseFloat(s);
  }

  function readProfile() {
    const data = Object.fromEntries(new FormData(form).entries());
    return {
      state: data.state,
      occupancy: data.occupancy,
      propertyType: data.propertyType,
      purpose: data.purpose || 'Rate/Term Refinance',
      homeValue: Number(data.homeValue),
      loanBalance: Number(data.loanBalance),
      currentRate: parseRate(data.currentRate),
      yearsRemaining: Number(data.yearsRemaining),
      term: data.term,
      refiCosts: Number(data.refiCosts || 0),
      stayYears: Number(data.stayYears || 5),
      fico: data.fico,
      dti: Number(data.dti || 36),
      veteran: data.veteran || 'No',
      email: (data.email || '').trim()
    };
  }

  function validateProfile(p) {
    if (!document.getElementById('consent').checked) {
      return 'Please accept the educational-only consent to proceed.';
    }
    if (!p.homeValue || !p.loanBalance || p.loanBalance <= 0) {
      return 'Enter home value and current loan balance.';
    }
    if (p.loanBalance > p.homeValue * 1.1) {
      return 'Loan balance should not exceed about 110% of home value.';
    }
    if (!p.currentRate || p.currentRate <= 0) {
      return 'Enter your current interest rate.';
    }
    if (!p.yearsRemaining || p.yearsRemaining <= 0) {
      return 'Enter years remaining on your current loan.';
    }
    return null;
  }

  function saveLocal(p) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
    } catch (_) {}
  }

  function loadLocal() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const p = JSON.parse(raw);
      Object.entries(p).forEach(([k, v]) => {
        const el = form.elements.namedItem(k);
        if (el && v != null) el.value = v;
      });
    } catch (_) {}
  }

  function verdictClass(verdict) {
    return {
      GO: 'verdict-go',
      MAYBE: 'verdict-maybe',
      NOT_YET: 'verdict-hold',
      NO_BENEFIT: 'verdict-no'
    }[verdict] || 'verdict-hold';
  }

  function renderResult(out, fromApi) {
    const m = out.metrics;
    document.getElementById('verdictBadge').className = 'verdict-badge ' + verdictClass(out.verdict);
    document.getElementById('verdictBadge').textContent = out.verdictLabel;
    document.getElementById('resultSummary').textContent = out.summary;

    document.getElementById('metricGrid').innerHTML = `
      <div class="metric"><strong>Your rate</strong><span>${fmtRate(m.currentRate)}</span></div>
      <div class="metric"><strong>Est. market rate</strong><span>${fmtRate(m.marketRate)}</span></div>
      <div class="metric"><strong>Rate drop</strong><span>${m.rateDrop.toFixed(2)}%</span></div>
      <div class="metric"><strong>Monthly P&amp;I savings</strong><span>${fmtMoney(m.monthlySavings)}</span></div>
      <div class="metric"><strong>Break-even</strong><span>${m.breakEvenMonths != null ? m.breakEvenMonths + ' mo' : 'N/A'}</span></div>
      <div class="metric"><strong>LTV</strong><span>${m.ltv}%</span></div>
    `;

    document.getElementById('bulletList').innerHTML =
      out.bullets.map(b => `<li>${escapeHtml(b)}</li>`).join('');

    const expl = out.explanation || out.summary;
    const explParts = String(expl || '').split(/\n\s*\n/).filter(Boolean);
    document.getElementById('explanation').innerHTML = explParts.length
      ? explParts.map((p) => `<p>${escapeHtml(p.trim())}</p>`).join('')
      : `<p>${escapeHtml(expl || '')}</p>`;

    const aiNote = document.getElementById('aiSourceNote');
    if (aiNote) {
      if (fromApi && out.aiSource === 'fallback') {
        aiNote.textContent = 'Note: AI explanation unavailable — showing rule-based summary. Book a call for personalized guidance.';
        aiNote.hidden = false;
      } else if (fromApi && (out.aiSource === 'azure' || out.aiSource === 'openai')) {
        aiNote.textContent = 'AI-assisted explanation (educational only — not a loan offer).';
        aiNote.hidden = false;
      } else {
        aiNote.textContent = '';
        aiNote.hidden = true;
      }
    }

    document.getElementById('checkedAt').textContent = out.checkedAt
      ? 'Checked ' + new Date(out.checkedAt).toLocaleString()
      : (fromApi ? '' : 'Instant preview — click Check Now for server analysis with optional AI explanation.');

    result.style.display = 'block';
    preview.style.display = 'none';
  }

  function showPreview() {
    const p = readProfile();
    const msg = validateProfile(p);
    if (msg) {
      err.textContent = msg;
      err.style.display = 'block';
      return;
    }
    err.style.display = 'none';
    const out = evaluateRefi(p);
    if (!out.ok) {
      err.textContent = out.errors.join('; ');
      err.style.display = 'block';
      return;
    }
    renderResult(out, false);
    preview.textContent = 'Preview updated — click Check Now for server analysis with optional AI explanation.';
    preview.style.display = 'block';
  }

  async function checkNow() {
    const p = readProfile();
    const msg = validateProfile(p);
    if (msg) {
      err.textContent = msg;
      err.style.display = 'block';
      return;
    }
    err.style.display = 'none';
    watchMsg.style.display = 'none';
    saveLocal(p);

    checkBtn.disabled = true;
    checkBtn.textContent = 'Checking…';

    try {
      const res = await fetch(apiUrl('refiCheck'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(p)
      });
      const out = await res.json();
      if (!res.ok) throw new Error(out.error || 'Check failed. Try again.');

      renderResult(out, true);
      scrollToResult();

      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({
        event: 'refi_monitor_check',
        verdict: out.verdict,
        rate_drop: out.metrics?.rateDrop,
        monthly_savings: out.metrics?.monthlySavings,
        aiSource: out.aiSource
      });
    } catch (ex) {
      err.textContent = ex.message;
      err.style.display = 'block';
      err.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } finally {
      checkBtn.disabled = false;
      checkBtn.textContent = 'Check Now';
    }
  }

  async function subscribeWatch() {
    const p = readProfile();
    const msg = validateProfile(p);
    if (msg) {
      err.textContent = msg;
      err.style.display = 'block';
      return;
    }
    if (!p.email) {
      err.textContent = 'Enter your email to get alerts when refinancing looks worthwhile.';
      err.style.display = 'block';
      return;
    }
    err.style.display = 'none';
    saveLocal(p);

    watchBtn.disabled = true;
    watchBtn.textContent = 'Subscribing…';

    try {
      const res = await fetch(apiUrl('refiWatch'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...p, createdAt: new Date().toISOString() })
      });
      const out = await res.json();
      if (!res.ok) throw new Error(out.error || 'Could not subscribe.');

      watchMsg.textContent = out.message + ' Current status: ' + out.verdictLabel + '.';
      watchMsg.style.display = 'block';

      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event: 'refi_monitor_watch', verdict: out.currentVerdict });
    } catch (ex) {
      err.textContent = ex.message;
      err.style.display = 'block';
    } finally {
      watchBtn.disabled = false;
      watchBtn.textContent = 'Email Me When It Makes Sense';
    }
  }

  form.querySelectorAll('input, select').forEach(el => {
    el.addEventListener('change', () => {
      if (form.checkValidity()) showPreview();
    });
  });

  saveBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    const p = readProfile();
    saveLocal(p);
    preview.textContent = 'Profile saved on this device.';
    preview.style.display = 'block';
  });

  checkBtn.addEventListener('click', (e) => { e.preventDefault(); checkNow(); });
  watchBtn.addEventListener('click', (e) => { e.preventDefault(); subscribeWatch(); });

  loadLocal();
  if (form.checkValidity()) showPreview();
})();
