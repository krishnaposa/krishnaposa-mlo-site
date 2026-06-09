const { TableClient, TableServiceClient } = require('@azure/data-tables');
const { randomUUID } = require('crypto');

const STORAGE = process.env.AZURE_STORAGE_CONNECTION_STRING || process.env.AzureWebJobsStorage;
const TABLE_NAME = process.env.LE_REVIEW_TABLE || 'leReviews';
const PARTITION = 'leReview';

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

async function saveLeReview(payload) {
  const table = await getTable();
  const id = randomUUID();
  const entity = {
    partitionKey: PARTITION,
    rowKey: id,
    id,
    status: 'pending',
    createdAt: new Date().toISOString(),
    source: String(payload.source || 'le-upload').slice(0, 64),
    fileName: String(payload.fileName || '').slice(0, 256),
    lenderName: String(payload.lenderName || '').slice(0, 128),
    contactName: String(payload.contact?.name || '').slice(0, 128),
    contactEmail: String(payload.contact?.email || '').trim().toLowerCase().slice(0, 128),
    contactPhone: String(payload.contact?.phone || '').slice(0, 32),
    notes: String(payload.notes || '').slice(0, 2000),
    fieldsJson: JSON.stringify(payload.fields || {}).slice(0, 30000)
  };
  await table.upsertEntity(entity, 'Merge');
  return entity;
}

module.exports = { saveLeReview, PARTITION, TABLE_NAME };
