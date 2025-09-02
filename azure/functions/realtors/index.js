const { TableClient } = require("@azure/data-tables");
const { EmailClient } = require("@azure/communication-email");
const crypto = require("crypto");

// --- env/config ---
const TABLE_NAME = "realtors";
const STORAGE_CONN = process.env.AZURE_STORAGE_CONNECTION_STRING;
const ACS_CONN = process.env.ACS_CONNECTION_STRING;
const MAIL_FROM = process.env.MAIL_FROM;
const NOTIFY_TO = process.env.NOTIFY_TO;
const ALLOW_ORIGIN = process.env.ALLOW_ORIGIN || "https://www.krishposa.com";

const emailClient = ACS_CONN ? new EmailClient(ACS_CONN) : null;

module.exports = async function (context, req) {
    try {
        // CORS preflight
        if (req.method === "OPTIONS") {
            return cors(context, 204);
        }

        // Parse body (JSON or form)
        const b = (req.body || {});
        const payload = {
            name: (b.name || b.fullName || "").trim(),
            email: (b.email || "").trim(),
            phone: (b.phone || "").trim(),
            firm: (b.firm || b.brokerage || "").trim(),
            logo: (b.logo || b.logoUrl || "").trim(),
            notes: (b.notes || "").trim(),
            createdAt: new Date().toISOString()
        };

        if (!payload.name) return send(context, 400, { ok: false, error: "Missing name" });

        // Table save (auto-create table if needed)
        const table = TableClient.fromConnectionString(STORAGE_CONN, TABLE_NAME);
        await table.createTable({ onResponse: () => { } }).catch(() => { });
        const entity = {
            partitionKey: (payload.firm || "unknown").toLowerCase(),
            rowKey: crypto.randomUUID(),
            ...payload
        };
        await table.createEntity(entity);

        // Email: notify you
        if (emailClient && MAIL_FROM && NOTIFY_TO) {
            const subject = `New Realtor saved: ${payload.name}`;
            const html = `
<h3>New realtor</h3>
<p><b>Name:</b> ${esc(payload.name)}</p>
<p><b>Email:</b> ${esc(payload.email)}</p>
<p><b>Phone:</b> ${esc(payload.phone)}</p>
<p><b>Firm:</b> ${esc(payload.firm)}</p>
<p><b>Logo:</b> ${esc(payload.logo)}</p>
<p><b>Notes:</b> ${esc(payload.notes)}</p>
<p><i>${payload.createdAt}</i></p>`;

            await safeSendEmail(() => emailClient.beginSend({
                senderAddress: MAIL_FROM,
                recipients: { to: [{ address: NOTIFY_TO }] },
                content: { subject, html }
            }), context);

            // Optional thank-you
            if (payload.email) {
                await safeSendEmail(() => emailClient.beginSend({
                    senderAddress: MAIL_FROM,
                    recipients: { to: [{ address: payload.email }] },
                    content: {
                        subject: "Thanks — got your info",
                        html: `<p>Hi ${esc(payload.name)},</p>
<p>Thanks for sharing your info. I’ll reach out shortly.</p>
<p>— Krish</p>`
                    }
                }), context);
            }
        }

        return send(context, 200, { ok: true });
    } catch (err) {
        context.log("Function error:", err);
        return send(context, 500, { ok: false, error: "Server error" });
    }
};

// --- helpers ---
function cors(context, status) {
    context.res = {
        status,
        headers: {
            "Access-Control-Allow-Origin": ALLOW_ORIGIN,
            "Access-Control-Allow-Methods": "POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type"
        }
    };
}

function send(context, status, body) {
    cors(context, status);
    context.res = {
        ...context.res,
        headers: { ...context.res.headers, "Content-Type": "application/json" },
        body
    };
}

function esc(s = "") {
    return s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function safeSendEmail(fn, context) {
    try {
        const poller = await fn();
        await poller.pollUntilDone();
    } catch (e) {
        context.log("ACS email error:", e?.message || e);
    }
}