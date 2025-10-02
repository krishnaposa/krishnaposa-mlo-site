# universe_utils.py
import os, json, datetime, logging
from azure.storage.blob import BlobServiceClient, ContentSettings

# Blob client (uses AzureWebJobsStorage connection string)
_BLOB_SVC = BlobServiceClient.from_connection_string(
    os.getenv("AzureWebJobsStorage")
)

UNIVERSE_CONTAINER = os.getenv("UNIVERSE_CONTAINER", "cache")
UNIVERSE_BLOB_NAME = os.getenv("UNIVERSE_BLOB_NAME", "universe.json")

def _blob_container():
    cont = _BLOB_SVC.get_container_client(UNIVERSE_CONTAINER)
    try:
        cont.create_container()
    except Exception:
        pass
    return cont

def read_universe_blob() -> dict | None:
    cont = _blob_container()
    try:
        blob = cont.get_blob_client(UNIVERSE_BLOB_NAME)
        data = blob.download_blob().readall()
        return json.loads(data)
    except Exception as e:
        logging.warning(f"[universe_utils] failed to read blob: {e}")
        return None