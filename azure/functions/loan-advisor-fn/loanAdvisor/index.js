const { estimateRate, ltvPercent } = require('../shared/rate-pricing');
const { handleOptions, sendJson, parseBody } = require('../shared/http');
const { callAi } = require('../shared/ai');

module.exports = async function (context, req) {
  if (req.method === 'OPTIONS') return handleOptions(context);
  if (req.method !== 'POST') return sendJson(context, 405, { error: 'Method not allowed' });

  try {
    const data = parseBody(req);
    const {
      state, occupancy, purpose, propertyType, homeValue, loanAmount,
      fico, dti, term, veteran, goals
    } = data;

    const hv = Number(homeValue);
    const la = Number(loanAmount);
    if (!hv || !la || la <= 0 || hv <= 0) {
      return sendJson(context, 400, { error: 'Invalid value or loan amount' });
    }

    const ltv = ltvPercent(hv, la);
    const rates = estimateRate({ term, fico, ltv, occupancy, propertyType, dti, purpose, veteran });

    const vaEligible = veteran === 'Yes'
      && occupancy === 'Primary Residence'
      && (purpose === 'Purchase' || String(purpose).includes('Refinance'));

    const product = vaEligible ? 'VA Fixed' :
      (goals === 'Pay Off Faster' ? '15 Year Fixed' :
        (goals === 'Lowest Monthly Payment' && /ARM/.test(term || '')) ? term : term);

    let reasoning = 'Based on your credit tier, LTV, occupancy, and goal, this product balances eligibility and cost while aligning with your payment objective.';

    const prompt = `User profile: ${JSON.stringify({
      state, occupancy, purpose, propertyType, ltv, fico, dti, term, veteran, goals
    })}.
Recommend the best loan type and explain why in 2 short paragraphs, plain English, no jargon.
End with one cautionary note about risks (like rate changes, PMI, or costs).`;

    reasoning = await callAi(prompt, reasoning);

    return sendJson(context, 200, {
      metrics: { ltv },
      recommendation: { product, reasoning },
      rates: { base: rates.base, high: rates.high },
      nextSteps: 'If this looks good, start a full application to lock a rate. We will verify income, assets, credit, and property details.'
    });
  } catch (err) {
    context.log.error(err);
    return sendJson(context, 500, { error: String(err.message || err) });
  }
};
