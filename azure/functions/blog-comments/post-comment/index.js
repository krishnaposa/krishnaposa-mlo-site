const { ensureTable } = require("../shared/table");
const { sanitizeStr, validateInput, hashIP, uuid, getClientIP } = require("../shared/utils");

const RATE_LIMIT_SECONDS = 60;

module.exports = async function (context, req) {
    const allowedOrigin = process.env.ALLOWED_ORIGIN || "*";
    const headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": allowedOrigin,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization"
    };
    if (req.method === "OPTIONS") {
        context.res = { status: 204, headers }; return;
    }

    try {
        const body = req.body || {};
        const path = sanitizeStr(body.path);
        const name = sanitizeStr(body.name);
        const email = sanitizeStr(body.email);
        const message = sanitizeStr(body.message);
        if (!path) { context.res = { status: 400, headers, body: { error: "Missing path" } }; return; }

        const err = validateInput({ name, email, message });
        if (err) { context.res = { status: 400, headers, body: { error: err } }; return; }

        const table = await ensureTable();

        // Rate limiting by IP+path
        const ipHash = hashIP(getClientIP(req));
        const now = Date.now();
        const filter = `PartitionKey eq '${encodeURIComponent(path)}' and ipHash eq '${ipHash}'`;
        for await (const ent of table.listEntities({ queryOptions: { filter } })) {
            if ((now - new Date(ent.createdAt).getTime()) / 1000 < RATE_LIMIT_SECONDS) {
                context.res = { status: 429, headers, body: { error: "Please wait a minute before posting again." } };
                return;
            }
        }

        const entity = {
            partitionKey: encodeURIComponent(path),
            rowKey: uuid(),
            name, email, message,
            status: "pending",
            createdAt: new Date().toISOString(),
            ipHash,
            userAgent: req.headers["user-agent"] || ""
        };
        await table.createEntity(entity);

        context.res = { status: 200, headers, body: { ok: true, status: "pending" } };
    } catch (e) {
        context.log.error(e);
        context.res = { status: 500, body: { error: "Server error" } };
    }
};