# universe_utils.py
import os, json, logging
from azure.storage.blob import BlobServiceClient

_BLOB_SVC: BlobServiceClient | None = None

UNIVERSE_CONTAINER = os.getenv("UNIVERSE_CONTAINER", "cache")
UNIVERSE_BLOB_NAME = os.getenv("UNIVERSE_BLOB_NAME", "universe.json")

def _blob_service() -> BlobServiceClient:
    global _BLOB_SVC
    if _BLOB_SVC is None:
        conn = os.getenv("MONITOR_STORAGE")
        if not conn:
            raise RuntimeError("MONITOR_STORAGE is not set")
        _BLOB_SVC = BlobServiceClient.from_connection_string(conn, logging_enable=False)
    return _BLOB_SVC

def _blob_container():
    cont = _blob_service().get_container_client(UNIVERSE_CONTAINER)
    try:
        cont.create_container(logging_enable=False)
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