const { ensureTable } = require("../shared/table");
const { sanitizeStr, escapeHtml } = require("../shared/utils");

module.exports = async function (context, req) {
    const allowedOrigin = process.env.ALLOWED_ORIGIN || "*";
    const headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": allowedOrigin,
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization"
    };
    if (req.method === "OPTIONS") { context.res = { status: 204, headers }; return; }

    const path = sanitizeStr(req.query.path);
    if (!path) { context.res = { status: 400, headers, body: { error: "Missing path" } }; return; }

    try {
        const table = await ensureTable();
        const comments = [];
        const filter = `PartitionKey eq '${encodeURIComponent(path)}' and status eq 'approved'`;
        for await (const ent of table.listEntities({ queryOptions: { filter } })) {
            comments.push({
                id: ent.rowKey,
                name: escapeHtml(ent.name || "Anonymous"),
                message: escapeHtml(ent.message || ""),
                createdAt: ent.createdAt
            });
        }
        comments.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));

        context.res = { status: 200, headers, body: { ok: true, comments } };
    } catch (e) {
        context.log.error(e);
        context.res = { status: 500, body: { error: "Server error" } };
    }
};