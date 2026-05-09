// index.js
// Azure Function: POST /api/realtorSubmit
// Stores JSON realtor partner info in Cosmos DB + sends ACS email notifications.

const { CosmosClient } = require("@azure/cosmos");
const { EmailClient } = require("@azure/communication-email");
const crypto = require("crypto");

// ---- env/config ----
const COSMOS_ENDPOINT   = process.env.COSMOS_ENDPOINT;
const COSMOS_KEY        = process.env.COSMOS_KEY;
const COSMOS_DB         = process.env.COSMOS_DB || "krishposa";
const COSMOS_CONTAINER  = process.env.COSMOS_CONTAINER || "realtors";
const COSMOS_PARTITION  = process.env.COSMOS_PARTITION || "/firmLower"; // must match container

const ACS_CONN     = process.env.ACS_CONNECTION_STRING;
const MAIL_FROM    = process.env.MAIL_FROM;
const NOTIFY_TO    = process.env.NOTIFY_TO;
const ALLOW_ORIGIN = process.env.ALLOW_ORIGIN || "https://www.krishposa.com";

// singletons
let cosmosClient, container;
const emailClient = ACS_CONN ? new EmailClient(ACS_CONN) : null;

async function ensureCosmos() {
  if (!cosmosClient) {
    if (!COSMOS_ENDPOINT || !COSMOS_KEY) {
      throw new Error("Cosmos DB credentials missing (COSMOS_ENDPOINT/COSMOS_KEY).");
    }
    cosmosClient = new CosmosClient({ endpoint: COSMOS_ENDPOINT, key: COSMOS_KEY });

    // Create DB and container if not exist (idempotent)
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

    if (req.method !== "POST") {
      return send(context, 405, { ok: false, error: "Method Not Allowed" });
    }

    // --- Parse body ---
    const b = (req.body || {});
    const nowISO = new Date().toISOString();

    const firmIn  = (b.firm || b.brokerage || "").toString().trim();
    const nameIn  = (b.name || b.fullName || "").toString().trim();
    const emailIn = (b.email || "").toString().trim();

    // Basic validation
    if (!firmIn)  return send(context, 400, { ok: false, error: "Missing company name" });
    if (!nameIn)  return send(context, 400, { ok: false, error: "Missing contact name" });
    if (!emailIn) return send(context, 400, { ok: false, error: "Missing email" });

    const payload = {
      id: crypto.randomUUID(),

      // company / branding
      firm: firmIn,
      firmLower: firmIn.toLowerCase(),
      caption: (b.caption || "").toString().trim(),

      // primary contact
      name: nameIn,
      email: emailIn,
      phone: (b.phone || "").toString().trim(),

      // org details
      address: (b.address || "").toString().trim(),
      whatsapp: (b.whatsapp || "").toString().trim(),
      facebook: (b.facebook || "").toString().trim(),     // handle or full URL
      instagram: (b.instagram || "").toString().trim(),   // handle or full URL
      logo: (b.logo || b.logoUrl || "").toString().trim(),
      ownerPic: (b.ownerPic || b.ownerPicUrl || "").toString().trim(),

      // misc/meta
      notes: (b.notes || "").toString().trim(),
      sourceIp: req.headers["x-forwarded-for"] || req.headers["client-ip"] || "",
      userAgent: req.headers["user-agent"] || "",
      referer: req.headers["referer"] || req.headers["referrer"] || "",
      createdAt: nowISO,
      _v: 2
    };

    // --- Save to Cosmos as JSON ---
    const c = await ensureCosmos();
    await c.items.create(payload);

    // --- Email notifications (optional) ---
    if (emailClient && MAIL_FROM && NOTIFY_TO) {
      const subject = `New Realtor Partner: ${payload.firm} (${payload.name})`;
      const html = `
<h3>New Realtor Partner Submission</h3>
<p><b>Company:</b> ${esc(payload.firm)}</p>
<p><b>Caption:</b> ${esc(payload.caption)}</p>
<p><b>Contact:</b> ${esc(payload.name)} — ${esc(payload.email)} — ${esc(payload.phone)}</p>
<p><b>Address:</b> ${esc(payload.address)}</p>
<p><b>WhatsApp:</b> ${esc(payload.whatsapp)}</p>
<p><b>Facebook:</b> ${esc(payload.facebook)}</p>
<p><b>Instagram:</b> ${esc(payload.instagram)}</p>
<p><b>Logo URL:</b> ${esc(payload.logo)}</p>
<p><b>Owner Pic URL:</b> ${esc(payload.ownerPic)}</p>
<p><b>Notes:</b> ${esc(payload.notes)}</p>
<p style="color:#666;font-size:12px;margin-top:8px;">
  IP: ${esc(payload.sourceIp)}<br>
  UA: ${esc(payload.userAgent)}<br>
  Referrer: ${esc(payload.referer)}<br>
  Submitted: ${esc(payload.createdAt)}
</p>`;

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