import os, datetime as dt
from azure.cosmos import CosmosClient

_CONN = os.environ["COSMOS_CONN"]
_DB   = os.environ["COSMOS_DB"]
_CT   = os.environ["COSMOS_CONTAINER"]

_client = CosmosClient.from_connection_string(_CONN)
_container = _client.get_database_client(_DB).get_container_client(_CT)

def nowiso():
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def create_doc(doc: dict):
    doc["createdAt"] = doc.get("createdAt") or nowiso()
    doc["updatedAt"] = nowiso()
    _container.create_item(doc)
    return doc

def upsert_doc(doc: dict):
    doc["updatedAt"] = nowiso()
    _container.upsert_item(doc)
    return doc

def get_doc(doc_id: str):
    try:
        return _container.read_item(item=doc_id, partition_key=doc_id)
    except Exception:
        return None