// Azure Function: save realtor to Azure Table Storage (table: "realtors")

const { TableClient, odata } = require("@azure/data-tables");
const { randomUUID } = require("crypto");

// Table name (must exist; we can auto-create)
const TABLE_NAME = "realtors";

// CORS allowlist (adjust your domain)
const ALLOW_ORIGIN = "https://www.krishposa.com";

module.exports = async function (context, req) {
    // Handle preflight quickly
    if (req.method === "OPTIONS") {
        context.res = {
            status: 204,
            headers: corsHeaders()
        };
        return;
    }

    try {
        // Read body (expects JSON)
        const b = req.body || {};
        // Basic validation (tweak as you like)
        const name = (b.name || "").trim();
        const firm = (b.firm || "").trim();
        const email = (b.email || "").trim();
        let logo = (b.logo || "").trim();
        if (!name) throw new Error("Missing 'name'");
        // Fallback logo if client didn’t provide or it failed
        if (!logo) logo = "https://www.krishposa.com/assets/img/realtor.png";

        // Partition/Row keys (you can shard by first letter, date, etc.)
        const partitionKey = "default";               // or new Date().toISOString().slice(0,10)
        const rowKey = randomUUID();
        // Build entity (add any extra fields you want to keep)
        const entity = {
            partitionKey,
            rowKey,
            name,
            firm,
            email,
            logo,
            // Optional useful metadata from client:
            page: b.page || "",
            source: b.source || "buyer-funnel",
            ua: b.ua || "",
            site_ts: b.site_ts || new Date().toISOString(),
            addedAt: new Date().toISOString()
        };

        // Connect using AzureWebJobsStorage (already configured on your app)
        const connectionString = process.env.AzureWebJobsStorage;
        const client = TableClient.fromConnectionString(connectionString, TABLE_NAME);
        // Ensure table exists (no-op if it already does)
        await client.createTable({ onResponse: () => { } }).catch(() => { });
        // Insert (or upsert if you prefer)
        await client.createEntity(entity);
        context.res = {
            status: 200,
            headers: corsHeaders(),
            body: { ok: true, id: rowKey }
        };
    } catch (err) {
        context.log.error(err);
        context.res = {
            status: 400,
            headers: corsHeaders(),
            body: { ok: false, error: String(err.message || err) }
        };
    }
};

function corsHeaders() {
    return {
        "Access-Control-Allow-Origin": ALLOW_ORIGIN,
        "Access-Control-Allow-Methods": "POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "86400",
        "Content-Type": "application/json"
    };
}

