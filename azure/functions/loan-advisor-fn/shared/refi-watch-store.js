const { TableClient, TableServiceClient } = require('@azure/data-tables');

const STORAGE = process.env.AZURE_STORAGE_CONNECTION_STRING || process.env.AzureWebJobsStorage;
const TABLE_NAME = process.env.REFI_WATCH_TABLE || 'refiWatches';
const PARTITION = 'refiWatch';

let tableClient;

async function getTable() {
  if (!STORAGE) throw new Error('Missing AzureWebJobsStorage / AZURE_STORAGE_CONNECTION_STRING');
  if (!tableClient) {
    const svc = TableServiceClient.fromConnectionString(STORAGE);
    try { await svc.createTable(TABLE_NAME); } catch (_) {}
    tableClient = TableClient.fromConnectionString(STORAGE, TABLE_NAME);
  }
  return tableClient;
}

function rowKeyForEmail(email) {
  return String(email).trim().toLowerCase().replace(/[^a-z0-9@._-]/g, '_');
}

async function upsertWatch({ email, profile, lastVerdict, createdAt }) {
  const table = await getTable();
  const entity = {
    partitionKey: PARTITION,
    rowKey: rowKeyForEmail(email),
    email: String(email).trim().toLowerCase(),
    profileJson: JSON.stringify(profile),
    lastVerdict: lastVerdict || 'NOT_YET',
    lastChecked: new Date().toISOString(),
    createdAt: createdAt || new Date().toISOString()
  };
  await table.upsertEntity(entity, 'Merge');
  return entity;
}

async function listWatches() {
  const table = await getTable();
  const out = [];
  const iter = table.listEntities({ queryOptions: { filter: `PartitionKey eq '${PARTITION}'` } });
  for await (const entity of iter) {
    let profile = {};
    try { profile = JSON.parse(entity.profileJson || '{}'); } catch (_) {}
    out.push({
      email: entity.email,
      profile,
      lastVerdict: entity.lastVerdict,
      lastChecked: entity.lastChecked,
      createdAt: entity.createdAt,
      rowKey: entity.rowKey
    });
  }
  return out;
}

async function updateWatchVerdict(rowKey, lastVerdict) {
  const table = await getTable();
  await table.updateEntity({
    partitionKey: PARTITION,
    rowKey,
    lastVerdict,
    lastChecked: new Date().toISOString()
  }, 'Merge');
}

module.exports = { upsertWatch, listWatches, updateWatchVerdict };
