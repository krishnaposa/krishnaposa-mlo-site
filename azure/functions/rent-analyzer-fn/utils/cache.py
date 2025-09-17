# utils/cache.py
import os, json, hashlib, datetime, logging
from typing import Any, Dict, Optional
from azure.storage.blob import BlobServiceClient, ContentSettings

# Reuse the same storage account as Functions
_BLOB_SVC = BlobServiceClient.from_connection_string(os.getenv("AzureWebJobsStorage"))

CACHE_CONTAINER = os.getenv("APP_CACHE_CONTAINER", "cache")  # you can override
DEFAULT_TTL_SEC = 6 * 60 * 60  # 6h default

def _container():
    cont = _BLOB_SVC.get_container_client(CACHE_CONTAINER)
    try:
        cont.create_container()
    except Exception:
        pass
    return cont

def make_cache_key(obj: Any, version: str = "v1") -> str:
    """
    Stable key from any JSON-serializable payload.
    Use 'version' to bust cache when you change logic.
    """
    try:
        data = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except Exception:
        # As a last resort, use str()
        data = str(obj).encode("utf-8")
    h = hashlib.sha256()
    h.update(version.encode("utf-8"))
    h.update(b"::")
    h.update(data)
    return h.hexdigest()

def blob_cache_get(group: str, key: str, max_age_sec: int = DEFAULT_TTL_SEC) -> Optional[Dict[str, Any]]:
    """
    Read a cached JSON blob if it's fresher than max_age_sec.
    Returns the stored 'value' field on hit (your original payload).
    """
    cont = _container()
    blob_path = f"{group}/{key}.json"
    try:
        bc = cont.get_blob_client(blob_path)
        props = bc.get_blob_properties()
        # age check
        last_mod = props.last_modified  # datetime with tzinfo
        age = (datetime.datetime.utcnow().replace(tzinfo=None) - last_mod.replace(tzinfo=None)).total_seconds()
        if age > max_age_sec:
            return None
        raw = bc.download_blob().readall()
        wrapper = json.loads(raw)
        return wrapper.get("value")
    except Exception as e:
        # Expected when not found / cold cache
        logging.debug(f"[cache miss] {group}/{key}: {e}")
        return None

def blob_cache_put(group: str, key: str, value: Dict[str, Any]) -> None:
    """
    Store JSON under group/key. Wrap with a small envelope for future extensibility.
    """
    cont = _container()
    blob_path = f"{group}/{key}.json"
    payload = {
        "created_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "value": value,
        "group": group,
        "key": key
    }
    cont.upload_blob(
        blob_path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json")
    )

def cache_headers(hit: bool) -> Dict[str, str]:
    return {"X-Cache": "HIT" if hit else "MISS"}