(function () {
  const form = document.getElementById('loan-form');
  const submitBtn = document.getElementById('submitBtn');
  const err = document.getElementById('err');
  const result = document.getElementById('result');

  function dollars(n) {
    return Number(n).toLocaleString(undefined, { style: 'currency', currency: 'USD' });
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderReasoning(text) {
    const parts = String(text || '').split(/\n\s*\n/).filter(Boolean);
    if (!parts.length) return '<p>—</p>';
    return parts.map((p) => `<p>${escapeHtml(p.trim())}</p>`).join('');
  }

  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    err.style.display = 'none';
    result.style.display = 'none';

    const data = Object.fromEntries(new FormData(form).entries());
    const hv = Number(data.homeValue);
    const la = Number(data.loanAmount);

    if (!document.getElementById('consent').checked) {
      err.textContent = 'Please accept the educational-only consent to proceed.';
      err.style.display = 'block';
      return;
    }
    if (!hv || !la || la <= 0 || hv <= 0 || la > hv * 1.1) {
      err.textContent = 'Please confirm home value and loan amount. Loan should not exceed about 110% of value.';
      err.style.display = 'block';
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Working…';

    try {
      const base = (window.LoanApi && window.LoanApi.base) || '/api';
      const API_URL = base.endsWith('/loanAdvisor') ? base : base.replace(/\/$/, '') + '/loanAdvisor';
      const res = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });

      const out = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(out.error || `Could not get a recommendation (HTTP ${res.status}).`);
      }

      const rec = out.recommendation || {};

      document.getElementById('summary').innerHTML =
        `<p><strong>Scenario</strong>: ${escapeHtml(data.purpose)} · ${escapeHtml(data.propertyType)} · ${escapeHtml(data.occupancy)} in ${escapeHtml(data.state)}</p>
         <p><strong>Value</strong>: ${dollars(hv)} · <strong>Loan</strong>: ${dollars(la)} · <strong>LTV</strong>: ${out.metrics.ltv}% · <strong>FICO</strong>: ${escapeHtml(data.fico)} · <strong>DTI</strong>: ${escapeHtml(data.dti)}%</p>`;

      const aiNote = rec.aiSource === 'fallback'
        ? '<p class="tiny muted">Note: AI explanation unavailable — showing rule-based summary. Book a call for personalized guidance.</p>'
        : '';

      document.getElementById('aiRec').innerHTML =
        `<p><strong>Recommended Product</strong>: ${escapeHtml(rec.product)}${rec.term ? ` · <strong>Term</strong>: ${escapeHtml(rec.term)}` : ''}</p>
         ${rec.note ? `<p class="small">${escapeHtml(rec.note)}</p>` : ''}
         ${renderReasoning(rec.reasoning)}
         ${aiNote}`;

      document.getElementById('rates').innerHTML =
        `<p><strong>Estimated Rate Range</strong>: ${out.rates.base.toFixed(3)}% to ${out.rates.high.toFixed(3)}% (rate). APR may be higher.</p>
         ${out.rates.asOf ? `<p class="tiny muted">${escapeHtml(out.rates.asOf)}</p>` : ''}`;

      document.getElementById('nextSteps').innerHTML =
        `<p><strong>Next Steps</strong>: ${escapeHtml(out.nextSteps || '')}</p>`;

      result.style.display = 'block';
      result.scrollIntoView({ behavior: 'smooth', block: 'start' });

      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({
        event: 'loan_advisor_submit',
        purpose: data.purpose,
        occupancy: data.occupancy,
        propertyType: data.propertyType,
        term: rec.term || data.term,
        product: rec.product,
        ltv: out.metrics.ltv,
        ficoBand: data.fico,
        aiSource: rec.aiSource
      });
    } catch (ex) {
      err.textContent = ex.message || 'Something went wrong. Please try again or call 678-481-8252.';
      err.style.display = 'block';
      err.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Get Recommendation';
    }
  });
})();
