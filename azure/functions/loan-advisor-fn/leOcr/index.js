const { parseLoanEstimate } = require('../shared/le-parse');
const { handleOptions, sendJson, parseBody } = require('../shared/http');

module.exports = async function (context, req) {
  if (req.method === 'OPTIONS') return handleOptions(context);
  if (req.method !== 'POST') return sendJson(context, 405, { error: 'Method not allowed' });

  try {
    const data = parseBody(req);
    const { text, imageBase64, mimeType } = data;

    if (!text && !imageBase64) {
      return sendJson(context, 400, { error: 'Provide text and/or imageBase64' });
    }

    const allowed = ['image/jpeg', 'image/png', 'image/webp', 'image/gif', 'application/pdf'];
    if (imageBase64 && mimeType && !allowed.includes(mimeType)) {
      return sendJson(context, 400, { error: 'Unsupported file type' });
    }

    if (imageBase64 && imageBase64.length > 8_000_000) {
      return sendJson(context, 400, { error: 'Image too large (max ~6MB)' });
    }

    const fields = await parseLoanEstimate({ text, imageBase64, mimeType });
    return sendJson(context, 200, { fields, disclaimer: 'Educational OCR only. Verify all numbers against your Loan Estimate before deciding.' });
  } catch (err) {
    context.log.error(err);
    return sendJson(context, 500, { error: String(err.message || err) });
  }
};
