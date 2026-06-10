// intakeSubmit / index.js
const { TableClient, TableServiceClient } = require("@azure/data-tables");
const { EmailClient } = require("@azure/communication-email");
const { randomUUID } = require("crypto");

const STORAGE = process.env.AZURE_STORAGE_CONNECTION_STRING || process.env.AzureWebJobsStorage;
const ACS = process.env.ACS_CONNECTION_STRING;
const MAIL_FROM = process.env.MAIL_FROM;
const NOTIFY_TO = process.env.NOTIFY_TO || "";
const ALLOW_ORIGIN = process.env.ALLOW_ORIGIN || "https://www.krishposa.com";
const TABLE_NAME = process.env.TABLE_NAME || "intakeResponses";

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmtMoney(n) {
  const x = Number(n);
  return isFinite(x)
    ? x.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 })
    : "";
}

function normalizeEstimate(raw) {
  if (!raw || typeof raw !== "object") return null;
  const e = {
    zip: String(raw.zip || "").trim(),
    price: raw.price != null ? String(raw.price) : "",
    down: raw.down != null ? String(raw.down) : "",
    rate: raw.rate != null ? String(raw.rate) : "",
    fico: String(raw.fico || "").trim(),
    program: String(raw.program || "").trim(),
    income: raw.income != null ? String(raw.income) : "",
    debts: raw.debts != null ? String(raw.debts) : "",
    monthlyPayment: raw.monthlyPayment != null ? String(raw.monthlyPayment) : "",
    pAndI: raw.pAndI != null ? String(raw.pAndI) : "",
    taxesInsMi: raw.taxesInsMi != null ? String(raw.taxesInsMi) : "",
    dti: raw.dti != null ? String(raw.dti) : "",
    calculatedAt: String(raw.calculatedAt || "").trim()
  };
  const hasData = e.price || e.income || e.monthlyPayment || e.dti;
  return hasData ? e : null;
}

function estimatePlainText(e) {
  if (!e) return "";
  return [
    "",
    "--- Quick Qualify estimate ---",
    e.zip ? `ZIP: ${e.zip}` : "",
    e.price ? `Home price: ${e.price}` : "",
    e.down ? `Down payment: ${e.down}` : "",
    e.rate ? `Rate: ${e.rate}%` : "",
    e.fico ? `Credit: ${e.fico}` : "",
    e.program ? `Program: ${e.program}` : "",
    e.income ? `Gross income/mo: ${e.income}` : "",
    e.debts ? `Debts/mo: ${e.debts}` : "",
    e.pAndI ? `P+I: ${e.pAndI}` : "",
    e.taxesInsMi ? `Taxes+Ins+MI: ${e.taxesInsMi}` : "",
    e.monthlyPayment ? `Total monthly: ${e.monthlyPayment}` : "",
    e.dti ? `DTI: ${e.dti}%` : "",
    e.calculatedAt ? `Calculated: ${e.calculatedAt}` : ""
  ].filter(Boolean).join("\n");
}

function estimateHtmlRows(e) {
  if (!e) return "";
  const rows = [
    ["ZIP", e.zip],
    ["Home price", e.price ? fmtMoney(e.price) : ""],
    ["Down payment", e.down ? fmtMoney(e.down) : ""],
    ["Rate", e.rate ? `${e.rate}%` : ""],
    ["Credit", e.fico],
    ["Program", e.program],
    ["Gross income/mo", e.income ? fmtMoney(e.income) : ""],
    ["Debts/mo", e.debts ? fmtMoney(e.debts) : ""],
    ["P+I", e.pAndI ? fmtMoney(e.pAndI) : ""],
    ["Taxes+Ins+MI", e.taxesInsMi ? fmtMoney(e.taxesInsMi) : ""],
    ["Total monthly", e.monthlyPayment ? fmtMoney(e.monthlyPayment) : ""],
    ["DTI", e.dti ? `${e.dti}%` : ""]
  ].filter(([, v]) => v);
  return rows
    .map(([k, v]) => `<tr><td style="padding:2px 8px"><b>${esc(k)}</b></td><td style="padding:2px 8px">${esc(v)}</td></tr>`)
    .join("");
}

async function sendEmail(emailClient, { to, subject, plainText, html }) {
  const recipients = (Array.isArray(to) ? to : [to])
    .map((a) => String(a || "").trim())
    .filter(Boolean)
    .map((address) => ({ address }));
  if (!recipients.length) return;
  await emailClient.beginSend({
    senderAddress: MAIL_FROM,
    recipients: { to: recipients },
    content: { subject, plainText, html }
  });
}

module.exports = async function (context, req) {
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
    if (!STORAGE) throw new Error("Missing AZURE_STORAGE_CONNECTION_STRING/AzureWebJobsStorage");
    if (!ACS) throw new Error("Missing ACS_CONNECTION_STRING");
    if (!MAIL_FROM || !NOTIFY_TO) throw new Error("Missing MAIL_FROM/NOTIFY_TO");

    const b = (req.body && typeof req.body === "object") ? req.body : {};
    const estimate = normalizeEstimate(b.estimate);

    const data = {
      fullName: (b.fullName || "").trim(),
      email: (b.email || "").trim().toLowerCase(),
      phone: (b.phone || "").trim(),
      timeline: (b.timeline || "").trim(),
      occupancy: (b.occupancy || "").trim(),
      source: (b.source || "").trim(),
      estPrice: (b.estPrice || "").trim(),
      estDown: (b.estDown || "").trim(),
      employment: (b.employment || "").trim(),
      coBorrower: (b.coBorrower || "").trim(),
      notes: (b.notes || "").trim()
    };

    if (!data.fullName) throw new Error("Name required");
    if (!data.email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email)) {
      throw new Error("Valid email required");
    }

    const svc = TableServiceClient.fromConnectionString(STORAGE);
    try { await svc.createTable(TABLE_NAME); } catch {}
    const table = TableClient.fromConnectionString(STORAGE, TABLE_NAME);

    const entity = {
      partitionKey: "web",
      rowKey: randomUUID(),
      ts: new Date().toISOString(),
      ...data,
      estimateJson: estimate ? JSON.stringify(estimate) : ""
    };
    if (estimate) {
      entity.qualZip = estimate.zip;
      entity.qualPrice = estimate.price;
      entity.qualDown = estimate.down;
      entity.qualRate = estimate.rate;
      entity.qualFico = estimate.fico;
      entity.qualProgram = estimate.program;
      entity.qualIncome = estimate.income;
      entity.qualDebts = estimate.debts;
      entity.qualMonthly = estimate.monthlyPayment;
      entity.qualDti = estimate.dti;
    }

    await table.upsertEntity(entity, "Merge");

    const emailClient = new EmailClient(ACS);
    const intakeRows = Object.entries(data)
      .map(([k, v]) => `<tr><td style="padding:2px 8px"><b>${esc(k)}</b></td><td style="padding:2px 8px">${esc(v)}</td></tr>`)
      .join("");
    const estimateRows = estimateHtmlRows(estimate);
    const notifyPlain = [
      `New intake from ${data.fullName}`,
      `Email: ${data.email}`,
      `Phone: ${data.phone}`,
      `Timeline: ${data.timeline}`,
      estimatePlainText(estimate)
    ].filter(Boolean).join("\n");

    await sendEmail(emailClient, {
      to: NOTIFY_TO.split(",").map((s) => s.trim()).filter(Boolean),
      subject: `New Pre-Approval Intake: ${data.fullName}`,
      plainText: notifyPlain,
      html: [
        "<h3>New Pre-Approval Intake</h3>",
        "<table>", intakeRows, "</table>",
        estimate ? "<h4>Quick Qualify estimate</h4><table>" + estimateRows + "</table>" : ""
      ].join("")
    });

    const firstName = data.fullName.split(/\s+/)[0] || data.fullName;
    const estimateSummary = estimate && estimate.monthlyPayment
      ? `Your Quick Qualify estimate showed about ${fmtMoney(estimate.monthlyPayment)}/mo total payment${estimate.dti ? ` (DTI ~${estimate.dti}%)` : ""}. `
      : "";

    await sendEmail(emailClient, {
      to: data.email,
      subject: "Pre-approval request received — Krish Posa",
      plainText: [
        `Hi ${firstName},`,
        "",
        "Thanks for submitting your pre-approval intake. I saved your information and will follow up with next steps and a document checklist.",
        "",
        estimateSummary + "These are estimates only — not a loan offer.",
        "",
        "Typical documents:",
        "• Last two pay stubs and W-2s (or 1099/tax returns if self-employed)",
        "• Two months bank statements",
        "• Photo ID",
        "",
        "Questions? Call or text 678-481-8252.",
        "",
        "— Krish Posa · Innovative Mortgage Services · NMLS #2533287"
      ].filter(Boolean).join("\n"),
      html: [
        `<p>Hi ${esc(firstName)},</p>`,
        "<p>Thanks for submitting your pre-approval intake. I saved your information and will follow up with next steps and a document checklist.</p>",
        estimate && estimate.monthlyPayment
          ? `<p><strong>Your Quick Qualify estimate:</strong> about ${esc(fmtMoney(estimate.monthlyPayment))}/mo total${estimate.dti ? ` (DTI ~${esc(estimate.dti)}%)` : ""}. Estimates only — not a loan offer.</p>`
          : "",
        "<p><strong>Typical documents:</strong></p>",
        "<ul>",
        "<li>Last two pay stubs and W-2s (or 1099/tax returns if self-employed)</li>",
        "<li>Two months bank statements</li>",
        "<li>Photo ID</li>",
        "</ul>",
        "<p>Questions? Call or text <a href=\"tel:+16784818252\">678-481-8252</a>.</p>",
        "<p>— Krish Posa · Innovative Mortgage Services · NMLS #2533287</p>"
      ].join("")
    });

    context.res = {
      status: 200,
      headers: { "Access-Control-Allow-Origin": ALLOW_ORIGIN, "Content-Type": "application/json" },
      body: {
        ok: true,
        id: entity.rowKey,
        message: "Thanks! Check your email for confirmation — Krish will follow up shortly."
      }
    };
  } catch (err) {
    context.log.error(err);
    context.res = {
      status: /required|valid email/i.test(String(err.message)) ? 400 : 500,
      headers: { "Access-Control-Allow-Origin": ALLOW_ORIGIN, "Content-Type": "application/json" },
      body: { ok: false, error: String(err.message || err) }
    };
  }
};
