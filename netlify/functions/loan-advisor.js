// netlify/functions/loan-advisor.js
exports.handler = async (event) => {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: 'Method not allowed' };
  }

  const data = JSON.parse(event.body || '{}');

  // Extract inputs
  const {
    state, occupancy, purpose, propertyType, homeValue, loanAmount,
    fico, dti, term, veteran, goals
  } = data;

  // Compute core metrics
  const hv = Number(homeValue);
  const la = Number(loanAmount);
  const ltv = Math.round((la / hv) * 100);

  // Simple base rate by term
  const baseByTerm = {
    '30 Year Fixed': 6.500,
    '20 Year Fixed': 6.300,
    '15 Year Fixed': 6.000,
    '10 Year ARM': 5.950,
    '7 Year ARM': 5.850,
    '5 Year ARM': 5.800
  };
  let rate = baseByTerm[term] || 6.600;

  // Addons by risk buckets
  const ficoAdj = (() => {
    const map = {
      '780+': -0.10, '760-779': -0.05, '740-759': 0.00, '720-739': 0.05,
      '700-719': 0.10, '680-699': 0.20, '660-679': 0.35, '640-659': 0.60, '620-639': 0.80
    };
    return map[fico] ?? 0.20;
  })();

  const ltvAdj = ltv <= 60 ? -0.10 :
                 ltv <= 75 ? 0.00  :
                 ltv <= 80 ? 0.05  :
                 ltv <= 85 ? 0.15  :
                 ltv <= 90 ? 0.30  : 0.60;

  const occAdj = occupancy === 'Investment' ? 0.75 : occupancy === 'Second Home' ? 0.20 : 0.00;
  const propAdj = propertyType === 'Condo' ? 0.15 : propertyType === 'Multi-Unit (2–4)' ? 0.35 : 0.00;
  const dtiAdj = Number(dti) > 45 ? 0.20 : 0.00;
  const cashoutAdj = purpose === 'Cash-out Refinance' ? 0.35 : 0.00;
  const stateAdj = 0.00; // Placeholder for state overlays if needed

  // VA pricing if eligible and purpose fits
  const vaEligible = veteran === 'Yes' && occupancy === 'Primary Residence' && (purpose === 'Purchase' || purpose.includes('Refinance'));
  const product = vaEligible ? 'VA Fixed' :
                  (goals === 'Pay Off Faster' ? '15 Year Fixed' :
                   goals === 'Lowest Monthly Payment' && term.includes('ARM') ? term :
                   term);

  if (vaEligible) {
    rate = Math.min(rate, 6.000); // Better baseline for VA
  }

  // Sum adjustments
  const totalAdj = ficoAdj + ltvAdj + occAdj + propAdj + dtiAdj + cashoutAdj + stateAdj;
  const estRate = rate + totalAdj;
  const response = {
    metrics: { ltv },
    recommendation: {
      product,
      reasoning: 'Based on your credit tier, LTV, occupancy, and goal, this product balances eligibility and cost while aligning with your payment objective.'
    },
    rates: {
      base: Math.max(estRate - 0.125, 3.5), // show a small range
      high: estRate + 0.125
    },
    nextSteps: 'If this looks good, start a full application to lock a rate. We will verify income, assets, credit, and property details.'
  };

  // Optional: call an LLM to generate a richer, user-friendly explanation
  try {
    if (process.env.AI_API_KEY) {
      // Example pseudocode. Replace with your preferred LLM SDK call.
      // const aiText = await callLLM({
      //   apiKey: process.env.AI_API_KEY,
      //   prompt: `User profile: ${JSON.stringify({state, occupancy, purpose, propertyType, ltv, fico, dti, term, veteran, goals})}.
      //            Recommend the best loan type and explain why in 2 short paragraphs, plain English, no jargon, and include one cautionary note.`
      // });
      // response.recommendation.reasoning = aiText;
    }
  } catch {
    // Fail gracefully
  }

  return {
    statusCode: 200,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
    body: JSON.stringify(response)
  };
};