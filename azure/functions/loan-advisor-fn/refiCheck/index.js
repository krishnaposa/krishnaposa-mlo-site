const { BASE_BY_TERM } = require('../shared/rate-pricing');
const { evaluateRefi, buildAiPrompt } = require('../shared/refi-eval');
const { handleOptions, sendJson, parseBody } = require('../shared/http');
const { callAi } = require('../shared/ai');

module.exports = async function (context, req) {
  if (req.method === 'OPTIONS') return handleOptions(context);
  if (req.method !== 'POST') return sendJson(context, 405, { error: 'Method not allowed' });

  try {
    const data = parseBody(req);
    const result = evaluateRefi(data);
    if (!result.ok) return sendJson(context, 400, { error: result.errors.join('; ') });

    const ai = await callAi(buildAiPrompt(result, data), result.summary);
    const explanation = ai.text;

    return sendJson(context, 200, {
      ...result,
      explanation,
      aiSource: ai.source,
      checkedAt: new Date().toISOString(),
      baselineRates: BASE_BY_TERM
    });
  } catch (err) {
    context.log.error(err);
    return sendJson(context, 500, { error: String(err.message || err) });
  }
};
