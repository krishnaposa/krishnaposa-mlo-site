const { TableClient } = require("@azure/data-tables");

function getTableClient() {
    const conn = process.env.COMMENTS_TABLE_CONN;
    const tableName = "Comments";
    return TableClient.fromConnectionString(conn, tableName);
}

async function ensureTable() {
    const client = getTableClient();
    try { await client.createTable(); } catch (_) { }
    return client;
}

module.exports = { getTableClient, ensureTable };