const { saveLeReview } = require('../shared/le-review-store');
const { sendPlainEmail } = require('../shared/email');
const { handleOptions, sendJson, parseBody } = require('../shared/http');

const FIELD_LABELS = {
  amount: 'Loan amount',
  rate: 'Rate (%)',
  term: 'Term (years)',
  points: 'Points (%)',
  lender_fees: 'Lender fees',
  credits: 'Lender credits',
  shop_total: 'Shoppable 3rd-party',
  other_3p: 'Other 3rd-party',
  prepaids: 'Prepaids + escrows',
  taxes_ins: 'Taxes + HOI / mo',
  pmi: 'PMI / mo',
  down: 'Down payment'
};

function formatFields(fields) {
  return Object.entries(FIELD_LABELS)
    .map(([k, label]) => `${label}: ${fields[k] ?? '—'}`)
    .join('\n');
}

module.exports = async function (context, req) {
  if (req.method === 'OPTIONS') return handleOptions(context);
  if (req.method !== 'POST') return sendJson(context, 405, { error: 'Method not allowed' });

  try {
    const data = parseBody(req);
    const email = String(data.contact?.email || '').trim().toLowerCase();
    const name = String(data.contact?.name || '').trim();

    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      return sendJson(context, 400, { error: 'Valid email required' });
    }
    if (!name) return sendJson(context, 400, { error: 'Name required' });

    const fields = data.fields && typeof data.fields === 'object' ? data.fields : {};
    if (!fields.amount && !fields.rate) {
      return sendJson(context, 400, { error: 'Upload and review your Loan Estimate fields first' });
    }

    const saved = await saveLeReview({
      source: data.source,
      fileName: data.fileName,
      lenderName: data.lenderName || fields.lender_name,
      contact: { name, email, phone: data.contact?.phone },
      notes: data.notes,
      fields
    });

    const summary = formatFields(fields);
    const text = [
      'New Loan Estimate review request',
      '',
      `ID: ${saved.id}`,
      `From: ${name} <${email}>`,
      data.contact?.phone ? `Phone: ${data.contact.phone}` : '',
      data.fileName ? `File: ${data.fileName}` : '',
      data.lenderName ? `Their lender: ${data.lenderName}` : '',
      data.notes ? `Borrower notes: ${data.notes}` : '',
      '',
      '--- Extracted LE fields ---',
      summary,
      '',
      'Status: pending — prepare competitive LE and follow up.'
    ].filter(Boolean).join('\n');

    await sendPlainEmail({
      to: email,
      subject: 'Loan Estimate received — Krish will follow up',
      text: [
        `Hi ${name},`,
        '',
        'Thanks for uploading your Loan Estimate. I saved the details and will review them to prepare a competitive quote.',
        '',
        'I typically follow up within one business day. If anything is urgent, call or text 678-481-8252.',
        '',
        '— Krish Posa · Innovative Mortgage Services'
      ].join('\n')
    });

    const notifyTo = process.env.NOTIFY_TO;
    if (notifyTo) {
      await sendPlainEmail({
        to: notifyTo.split(',')[0].trim(),
        subject: `LE review request: ${name}`,
        text
      });
    }

    return sendJson(context, 200, {
      ok: true,
      id: saved.id,
      message: 'Your Loan Estimate is saved. Krish will review it and follow up with a competitive quote.'
    });
  } catch (err) {
    context.log.error(err);
    const msg = String(err.message || err);
    if (msg.includes('Missing AzureWebJobsStorage')) {
      return sendJson(context, 503, { error: 'LE review storage is not configured on the server yet.' });
    }
    return sendJson(context, 500, { error: msg });
  }
};
