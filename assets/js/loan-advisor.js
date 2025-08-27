(function(){
  const form = document.getElementById('loan-form');
  const submitBtn = document.getElementById('submitBtn');
  const err = document.getElementById('err');
  const result = document.getElementById('result');

  function dollars(n){ return Number(n).toLocaleString(undefined, { style: 'currency', currency: 'USD' }); }

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
      err.textContent = 'Please confirm Home Value and Loan Amount. Loan should not exceed about 110% of value.';
      err.style.display = 'block';
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Working…';

    try {
      // IMPORTANT: replace with your deployed serverless endpoint
      const API_URL = 'https://loan-advisor.krishna-posa.workers.dev';
      const res = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      if (!res.ok) throw new Error('Server error. Please try again.');

      const out = await res.json();

      document.getElementById('summary').innerHTML =
        `<p><strong>Scenario</strong>: ${data.purpose} · ${data.propertyType} · ${data.occupancy} in ${data.state}</p>
         <p><strong>Value</strong>: ${dollars(hv)} · <strong>Loan</strong>: ${dollars(la)} · <strong>LTV</strong>: ${out.metrics.ltv}% · <strong>FICO</strong>: ${data.fico} · <strong>DTI</strong>: ${data.dti}%</p>`;

      document.getElementById('aiRec').innerHTML =
        `<p><strong>Recommended Product</strong>: ${out.recommendation.product}</p>
         <p>${out.recommendation.reasoning}</p>`;

      document.getElementById('rates').innerHTML =
        `<p><strong>Estimated Rate Range</strong>: ${out.rates.base.toFixed(3)}% to ${out.rates.high.toFixed(3)}% (rate). Est. APR may be higher.</p>`;

      document.getElementById('nextSteps').innerHTML =
        `<p><strong>Next Steps</strong>: ${out.nextSteps}</p>`;

      result.style.display = 'block';

      // GTM event for analytics
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({
        event: 'loan_advisor_submit',
        purpose: data.purpose,
        occupancy: data.occupancy,
        propertyType: data.propertyType,
        term: data.term,
        ltv: out.metrics.ltv,
        ficoBand: data.fico
      });

    } catch (ex) {
      err.textContent = ex.message;
      err.style.display = 'block';
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Get Recommendation';
    }
  });
})();