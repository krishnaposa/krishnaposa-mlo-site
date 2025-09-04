const { ensureTable } = require("../shared/table");
const { sanitizeStr } = require("../shared/utils");

module.exports = async function (context, req) {
    const allowedOrigin = process.env.ALLOWED_ORIGIN || "*";
    const headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": allowedOrigin,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, x-functions-key"
    };
    if (req.method === "OPTIONS") { context.res = { status: 204, headers }; return; }

    try {
        const { path, id, action } = req.body || {};
        if (!path || !id || !action) {
            context.res = { status: 400, headers, body: { error: "path, id, action are required" } };
            return;
        }

        const table = await ensureTable();
        const pk = encodeURIComponent(sanitizeStr(path));
        const rk = sanitizeStr(id);

        if (action === "approve") {
            const ent = await table.getEntity(pk, rk);
            ent.status = "approved";
            await table.updateEntity(ent, "Replace");
            context.res = { status: 200, headers, body: { ok: true, action: "approved" } };
            return;
        }

        if (action === "delete") {
            await table.deleteEntity(pk, rk);
            context.res = { status: 200, headers, body: { ok: true, action: "deleted" } };
            return;
        }

        context.res = { status: 400, headers, body: { error: "Invalid action" } };
    } catch (e) {
        context.log.error(e);
        context.res = { status: 404, body: { error: "Comment not found" } };
    }
};
