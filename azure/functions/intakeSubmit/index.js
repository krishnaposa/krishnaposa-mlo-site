// intakeSubmit / index.js
const { TableClient, TableServiceClient } = require("@azure/data-tables");
const { EmailClient } = require("@azure/communication-email");
const { randomUUID } = require("crypto");

const STORAGE  = process.env.AZURE_STORAGE_CONNECTION_STRING || process.env.AzureWebJobsStorage;
const ACS      = process.env.ACS_CONNECTION_STRING;
const MAIL_FROM = process.env.MAIL_FROM;
const NOTIFY_TO = process.env.NOTIFY_TO || "";
const ALLOW_ORIGIN = process.env.ALLOW_ORIGIN || "https://www.krishposa.com";
const TABLE_NAME = process.env.TABLE_NAME || "intakeResponses";

module.exports = async function (context, req) {
  // CORS preflight
  if (req.method === "OPTIONS") {
    context.res = {
      status: 204,
      headers: {
        "Access-Control-Allow-Origin": ALLOW_ORIGIN,
        "Access-Control-Allow-Methods": "POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,Authorization"
      }
    };
    return;
  }

  try {
    if (!STORAGE)  throw new Error("Missing AZURE_STORAGE_CONNECTION_STRING/AzureWebJobsStorage");
    if (!ACS)      throw new Error("Missing ACS_CONNECTION_STRING");
    if (!MAIL_FROM || !NOTIFY_TO) throw new Error("Missing MAIL_FROM/NOTIFY_TO");

    const b = (req.body && typeof req.body === "object") ? req.body : {};
    const data = {
      fullName:   (b.fullName || "").trim(),
      email:      (b.email || "").trim(),
      phone:      (b.phone || "").trim(),
      timeline:   (b.timeline || "").trim(),
      occupancy:  (b.occupancy || "").trim(),
      source:     (b.source || "").trim(),
      estPrice:   (b.estPrice || "").trim(),
      estDown:    (b.estDown || "").trim(),
      employment: (b.employment || "").trim(),
      coBorrower: (b.coBorrower || "").trim(),
      notes:      (b.notes || "").trim()
    };

    // Table create (idempotent) + insert
    const svc = TableServiceClient.fromConnectionString(STORAGE);
    try { await svc.createTable(TABLE_NAME); } catch {}
    const table = TableClient.fromConnectionString(STORAGE, TABLE_NAME);
    const entity = { partitionKey: "web", rowKey: randomUUID(), ts: new Date().toISOString(), ...data };
    await table.upsertEntity(entity, "Merge");

    // Email via ACS
    const emailClient = new EmailClient(ACS);
    const rows = Object.entries(data)
      .map(([k,v]) => `<tr><td style="padding:2px 8px"><b>${k}</b></td><td style="padding:2px 8px">${String(v||"")}</td></tr>`).join("");
    const toList = NOTIFY_TO.split(",").map(s => s.trim()).filter(Boolean).map(a => ({ address: a }));

    await emailClient.beginSend({
      senderAddress: MAIL_FROM,
      recipients: { to: toList },
      content: {
        subject: `New Intake: ${data.fullName || "Lead"}`,
        plainText: `New intake from ${data.fullName}\nEmail: ${data.email}\nPhone: ${data.phone}\nTimeline: ${data.timeline}`,
        html: `<h3>New Pre-Approval Intake</h3><table>${rows}</table>`
      }
    });

    context.res = {
      status: 200,
      headers: { "Access-Control-Allow-Origin": ALLOW_ORIGIN, "Content-Type": "application/json" },
      body: { ok: true, id: entity.rowKey }
    };
  } catch (err) {
    context.log.error(err);
    context.res = {
      status: 500,
      headers: { "Access-Control-Allow-Origin": ALLOW_ORIGIN, "Content-Type": "application/json" },
      body: { ok: false, error: String(err.message || err) }
    };
  }
};