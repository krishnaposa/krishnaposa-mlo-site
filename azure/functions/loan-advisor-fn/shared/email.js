const { EmailClient } = require('@azure/communication-email');

const ACS = process.env.ACS_CONNECTION_STRING;
const MAIL_FROM = process.env.MAIL_FROM;
const NOTIFY_TO = process.env.NOTIFY_TO || '';

async function sendPlainEmail({ to, subject, text, html }) {
  if (!ACS || !MAIL_FROM) {
    console.log('[email-skip]', to, subject);
    return false;
  }

  const client = new EmailClient(ACS);
  const recipients = [{ address: to }];
  const notifyList = NOTIFY_TO.split(',').map(s => s.trim()).filter(Boolean);
  for (const addr of notifyList) {
    if (addr && addr.toLowerCase() !== String(to).toLowerCase()) {
      recipients.push({ address: addr });
    }
  }

  try {
    const poller = await client.beginSend({
      senderAddress: MAIL_FROM,
      recipients: { to: recipients },
      content: {
        subject,
        plainText: text,
        html: html || `<pre style="font-family:sans-serif;white-space:pre-wrap">${escapeHtml(text)}</pre>`
      }
    });
    await poller.pollUntilDone();
    return true;
  } catch (err) {
    console.error('ACS email error', err?.message || err);
    return false;
  }
}

function escapeHtml(s = '') {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

module.exports = { sendPlainEmail };
