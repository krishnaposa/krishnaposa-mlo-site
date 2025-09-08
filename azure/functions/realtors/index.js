// index.js
// Azure Function: POST /api/realtorSubmit
// Stores JSON in Cosmos DB (one doc per submission) + optional ACS email notifications.

const { CosmosClient } = require("@azure/cosmos");
const { EmailClient } = require("@azure/communication-email");
const crypto = require("crypto");

// ---- env/config ----
const COSMOS_ENDPOINT = process.env.COSMOS_ENDPOINT;
const COSMOS_KEY = process.env.COSMOS_KEY;
const COSMOS_DB = process.env.COSMOS_DB || "krishposa";
const COSMOS_CONTAINER = process.env.COSMOS_CONTAINER || "realtors";
const COSMOS_PARTITION = process.env.COSMOS_PARTITION || "/firmLower"; // keep as string path

const ACS_CONN = process.env.ACS_CONNECTION_STRING;
const MAIL_FROM = process.env.MAIL_FROM;
const NOTIFY_TO = process.env.NOTIFY_TO;
const ALLOW_ORIGIN = process.env.ALLOW_ORIGIN || "https://www.krishposa.com";

// singletons
let cosmosClient, container;
const emailClient = ACS_CONN ? new EmailClient(ACS_CONN) : null;

async function ensureCosmos() {
  if (!cosmosClient) {
    cosmosClient = new CosmosClient({ endpoint: COSMOS_ENDPOINT, key: COSMOS_KEY });
    // Create DB/container if they don't exist (safe to call repeatedly)
    const { database } = await cosmosClient.databases.createIfNotExists({ id: COSMOS_DB });
    const { container: c } = await database.containers.createIfNotExists({
      id: COSMOS_CONTAINER,
      partitionKey: { paths: [COSMOS_PARTITION] }
    });
    container = c;
  }
  return container;
}

module.exports = async function (context, req) {
  try {
    // CORS preflight
    if (req.method === "OPTIONS") {
      return cors(context, 204);
    }

    // --- Parse body (handles JSON or x-www-form-urlencoded already parsed by Functions) ---
    const b = (req.body || {});
    const payload = {
      id: crypto.randomUUID(),
      name: (b.name || b.fullName || "").trim(),
      email: (b.email || "").trim(),
      phone: (b.phone || "").trim(),
      firm: (b.firm || b.brokerage || "").trim(),
      logo: (b.logo || b.logoUrl || "").trim(),
      notes: (b.notes || "").trim(),
      // computed
      firmLower: (b.firm || b.brokerage || "unknown").toString().trim().toLowerCase(),
      sourceIp: req.headers["x-forwarded-for"] || req.headers["client-ip"] || "",
      userAgent: req.headers["user-agent"] || "",
      createdAt: new Date().toISOString(),
      // keep raw for future-proofing if needed
      _v: 1
    };

    if (!payload.name) return send(context, 400, { ok: false, error: "Missing name" });

    // --- Save to Cosmos as JSON ---
    const c = await ensureCosmos();
    await c.items.create(payload);

    // --- Email notifications (optional) ---
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
<p class="small"><i>${payload.createdAt}</i></p>`;

      await safeSendEmail(() => emailClient.beginSend({
        senderAddress: MAIL_FROM,
        recipients: { to: [{ address: NOTIFY_TO }] },
        content: { subject, html }
      }), context);

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

    return send(context, 200, { ok: true, id: payload.id });
  } catch (err) {
    context.log("Function error:", err);
    return send(context, 500, { ok: false, error: "Server error" });
  }
};

// ---- helpers ----
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