const { estimateRate, ltvPercent } = require('../shared/rate-pricing');
const { recommendProduct } = require('../shared/product-rules');
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
      return sendJson(context, 400, { error: 'Invalid home value or loan amount.' });
    }
    if (la > hv * 1.1) {
      return sendJson(context, 400, { error: 'Loan amount should not exceed about 110% of property value.' });
    }

    const ltv = ltvPercent(hv, la);
    const fit = recommendProduct({
      occupancy, purpose, loanAmount: la, ltv, fico, veteran, goals, term
    });

    const rates = estimateRate({
      term: fit.term,
      fico,
      ltv,
      occupancy,
      propertyType,
      dti,
      purpose,
      veteran
    });

    const fallback = [
      `For your scenario (${purpose}, ${occupancy}, ${ltv}% LTV), ${fit.product} on a ${fit.term} is a sensible starting point.`,
      fit.note,
      'This is educational guidance only — final eligibility, rate, and APR depend on full underwriting.'
    ].join(' ');

    const prompt = `Explain this mortgage recommendation in 2 short paragraphs, plain English, no jargon.
Recommended product: ${fit.product}
Suggested term: ${fit.term}
Why (underwriting note): ${fit.note}
User profile: state=${state}, occupancy=${occupancy}, purpose=${purpose}, property=${propertyType}, LTV=${ltv}%, FICO band=${fico}, DTI=${dti}%, goal=${goals}, VA eligible=${veteran}.
Do not change the recommended product. End with one caution about PMI, rate changes, or closing costs.`;

    const ai = await callAi(prompt, fallback);

    return sendJson(context, 200, {
      metrics: { ltv },
      recommendation: {
        product: fit.product,
        term: fit.term,
        note: fit.note,
        reasoning: ai.text,
        aiSource: ai.source
      },
      rates: {
        base: rates.base,
        high: rates.high,
        asOf: 'Educational baseline — not a live market feed'
      },
      nextSteps: 'Next: send your existing Loan Estimate — I\'ll compete, book a quick call, or start a full application to lock pricing after verification.'
    });
  } catch (err) {
    context.log.error(err);
    return sendJson(context, 500, { error: String(err.message || err) });
  }
};
