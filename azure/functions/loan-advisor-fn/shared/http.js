const ALLOW_ORIGIN = process.env.ALLOW_ORIGIN || 'https://www.krishposa.com';

function corsHeaders(extra = {}) {
  return {
    'Access-Control-Allow-Origin': ALLOW_ORIGIN,
    'Access-Control-Allow-Methods': 'POST,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Content-Type': 'application/json',
    ...extra
  };
}

function handleOptions(context) {
  context.res = { status: 204, headers: corsHeaders() };
}

function sendJson(context, status, body) {
  context.res = { status, headers: corsHeaders(), body };
}

function parseBody(req) {
  const b = req.body;
  return b && typeof b === 'object' ? b : {};
}

module.exports = { ALLOW_ORIGIN, corsHeaders, handleOptions, sendJson, parseBody };
