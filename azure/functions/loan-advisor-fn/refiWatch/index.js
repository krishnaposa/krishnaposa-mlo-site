const { evaluateRefi } = require('../shared/refi-eval');
const { upsertWatch } = require('../shared/refi-watch-store');
const { handleOptions, sendJson, parseBody } = require('../shared/http');

module.exports = async function (context, req) {
  if (req.method === 'OPTIONS') return handleOptions(context);
  if (req.method !== 'POST') return sendJson(context, 405, { error: 'Method not allowed' });

  try {
    const data = parseBody(req);
    const email = String(data.email || '').trim().toLowerCase();
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      return sendJson(context, 400, { error: 'Valid email required for rate alerts' });
    }

    const profile = { ...data };
    delete profile.email;

    const result = evaluateRefi(profile);
    if (!result.ok) return sendJson(context, 400, { error: result.errors.join('; ') });

    await upsertWatch({
      email,
      profile,
      lastVerdict: result.verdict,
      createdAt: data.createdAt || new Date().toISOString()
    });

    return sendJson(context, 200, {
      ok: true,
      message: 'You are subscribed to refinance rate checks. We will email you when it looks worth exploring.',
      currentVerdict: result.verdict,
      verdictLabel: result.verdictLabel
    });
  } catch (err) {
    context.log.error(err);
    const msg = String(err.message || err);
    if (msg.includes('Missing AzureWebJobsStorage')) {
      return sendJson(context, 503, { error: 'Rate watch storage is not configured on the server yet.' });
    }
    return sendJson(context, 500, { error: msg });
  }
};
