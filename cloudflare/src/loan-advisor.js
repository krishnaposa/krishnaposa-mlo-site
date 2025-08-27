// src/loan-advisor.js
// Cloudflare Workers version of your loan advisor endpoint.
// Supports: POST /  •  CORS (preflight)  •  Same JSON shape as before.

function json(body, status = 200, origin = '*') {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      'access-control-allow-origin': origin,
      'access-control-allow-headers': 'content-type',
      'access-control-allow-methods': 'POST, OPTIONS',
      'access-control-max-age': '86400'
    }
  });
}

export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get('origin') || '*';
    const allowOrigin = origin && /krishposa\.com$/i.test(new URL(origin).hostname)
      ? origin
      : 'https://www.krishposa.com'; // tighten to your site

    if (request.method === 'OPTIONS') {
      // CORS preflight
      return new Response(null, {
        status: 204,
        headers: {
          'access-control-allow-origin': allowOrigin,
          'access-control-allow-headers': 'content-type',
          'access-control-allow-methods': 'POST, OPTIONS',
          'access-control-max-age': '86400'
        }
      });
    }

    if (request.method !== 'POST') {
      return json({ error: 'Method not allowed' }, 405, allowOrigin);
    }

    let data;
    try {
      data = await request.json();
    } catch {
      return json({ error: 'Invalid JSON body' }, 400, allowOrigin);
    }

    const {
      state, occupancy, purpose, propertyType, homeValue, loanAmount,
      fico, dti, term, veteran, goals
    } = data;

    const hv = Number(homeValue);
    const la = Number(loanAmount);
    if (!hv || !la || la <= 0 || hv <= 0) {
      return json({ error: 'Invalid value or loan amount' }, 400, allowOrigin);
    }
    const ltv = Math.round((la / hv) * 100);

    // Baseline rate by term (tune as you like)
    const baseByTerm = {
      '30 Year Fixed': 6.500,
      '20 Year Fixed': 6.300,
      '15 Year Fixed': 6.000,
      '10 Year ARM': 5.950,
      '7 Year ARM': 5.850,
      '5 Year ARM': 5.800
    };
    let rate = baseByTerm[term] || 6.600;

    // Adjustments
    const ficoAdjMap = {
      '780+': -0.10, '760-779': -0.05, '740-759': 0.00, '720-739': 0.05,
      '700-719': 0.10, '680-699': 0.20, '660-679': 0.35, '640-659': 0.60, '620-639': 0.80
    };
    const ficoAdj = ficoAdjMap[fico] ?? 0.20;

    const ltvAdj = ltv <= 60 ? -0.10 :
                   ltv <= 75 ? 0.00  :
                   ltv <= 80 ? 0.05  :
                   ltv <= 85 ? 0.15  :
                   ltv <= 90 ? 0.30  : 0.60;

    const occAdj  = occupancy === 'Investment' ? 0.75 : occupancy === 'Second Home' ? 0.20 : 0.00;
    const propAdj = propertyType === 'Condo' ? 0.15 : propertyType === 'Multi-Unit (2–4)' ? 0.35 : 0.00;
    const dtiAdj  = Number(dti) > 45 ? 0.20 : 0.00;
    const cashAdj = purpose === 'Cash-out Refinance' ? 0.35 : 0.00;

    // VA product handling
    const vaEligible = veteran === 'Yes'
      && occupancy === 'Primary Residence'
      && (purpose === 'Purchase' || purpose?.includes('Refinance'));

    const product = vaEligible ? 'VA Fixed' :
                    (goals === 'Pay Off Faster' ? '15 Year Fixed' :
                     (goals === 'Lowest Monthly Payment' && /ARM/.test(term)) ? term : term);

    if (vaEligible) rate = Math.min(rate, 6.000);

    const estRate = rate + (ficoAdj + ltvAdj + occAdj + propAdj + dtiAdj + cashAdj);

    // Optional: richer LLM explanation (env.AI_API_KEY secret). Omitted by default.
    let reasoning = 'Based on your credit tier, LTV, occupancy, and goal, this product balances eligibility and cost while aligning with your payment objective.';
    // if (env.AI_API_KEY) {
    //   const prompt = `User profile: ${JSON.stringify({state, occupancy, purpose, propertyType, ltv, fico, dti, term, veteran, goals})}.
    //     Recommend the best loan type and explain why in 2 short paragraphs, plain English, and include one cautionary note.`;
    //   // Example (pseudo): call your LLM provider here using fetch() with env.AI_API_KEY
    //   // reasoning = await callLLM(prompt, env.AI_API_KEY);
    // }

    const response = {
      metrics: { ltv },
      recommendation: { product, reasoning },
      rates: {
        base: Math.max(estRate - 0.125, 3.5),
        high: estRate + 0.125
      },
      nextSteps: 'If this looks good, start a full application to lock a rate. We will verify income, assets, credit, and property details.'
    };

    return json(response, 200, allowOrigin);
  }
};