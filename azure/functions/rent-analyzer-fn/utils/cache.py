# utils/cache.py
import os
import json
import hashlib
import datetime
import logging
from typing import Any, Dict, Optional

# --- Settings ---
CACHE_CONTAINER = os.getenv("APP_CACHE_CONTAINER", "cache")  # override if you like
DEFAULT_TTL_SEC = int(os.getenv("APP_CACHE_TTL_SEC", str(6 * 60 * 60)))  # 6h

# --- Optional Blob backend (preferred) ---
_BLOB_SVC = None
_USE_BLOB = False
_CONTAINER_READY = False

try:
    conn = os.getenv("AzureWebJobsStorage")
    if conn:  # avoid .rstrip() on None inside the SDK
        from azure.storage.blob import BlobServiceClient, ContentSettings  # type: ignore

        _BLOB_SVC = BlobServiceClient.from_connection_string(conn)
        _USE_BLOB = True
    else:
        logging.warning("[cache] AzureWebJobsStorage is not set; using in-memory cache.")
except Exception as e:
    logging.warning("[cache] Blob client init failed; falling back to memory. %s", e)
    _BLOB_SVC = None
    _USE_BLOB = False

# --- In-memory fallback (per-process; fine for local/dev) ---
_MEMORY_CACHE: Dict[str, Dict[str, Any]] = {}


def _ensure_container_once() -> Optional["BlobServiceClient"]:
    """
    Ensure the container exists only once per process.
    Returns a container client or None if blob backend disabled.
    """
    global _CONTAINER_READY
    if not _USE_BLOB or _BLOB_SVC is None:
        return None

    cont = _BLOB_SVC.get_container_client(CACHE_CONTAINER)
    if _CONTAINER_READY:
        return cont

    try:
        # Avoid 409 noise: check existence first
        if not cont.exists():
            cont.create_container()
        _CONTAINER_READY = True
    except Exception as e:
        # Swallow 'ContainerAlreadyExists' and only warn on unexpected errors
        msg = str(e)
        if "ContainerAlreadyExists" in msg or "Conflict" in msg:
            _CONTAINER_READY = True
            logging.debug("[cache] Container '%s' already exists.", CACHE_CONTAINER)
        else:
            logging.warning("[cache] Could not ensure container '%s': %s", CACHE_CONTAINER, e)
            return None
    return cont


def make_cache_key(obj: Any, version: str = "v1") -> str:
    """
    Stable key from any JSON-serializable payload.
    Use 'version' to bust cache when you change logic.
    """
    try:
        data = json.dumps(
            obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
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
    # Memory fallback
    if not _USE_BLOB or _BLOB_SVC is None:
        entry = _MEMORY_CACHE.get(f"{group}/{key}")
        if not entry:
            return None
        try:
            created = datetime.datetime.fromisoformat(entry["created_utc"].replace("Z", ""))
            age = (datetime.datetime.utcnow() - created).total_seconds()
            if age > max_age_sec:
                return None
        except Exception:
            # If timestamp parse fails, treat as miss
            return None
        return entry.get("value")

    # Blob path
    cont = _ensure_container_once()
    if cont is None:
        return None
    blob_path = f"{group}/{key}.json"
    try:
        bc = cont.get_blob_client(blob_path)
        props = bc.get_blob_properties()
        last_mod = props.last_modified  # datetime with tzinfo
        age = (datetime.datetime.utcnow().replace(tzinfo=None) - last_mod.replace(tzinfo=None)).total_seconds()
        if age > max_age_sec:
            return None
        raw = bc.download_blob().readall()
        wrapper = json.loads(raw)
        return wrapper.get("value")
    except Exception as e:
        # Expected when not found / cold cache
        logging.debug("[cache miss] %s: %s", blob_path, e)
        return None


def blob_cache_put(group: str, key: str, value: Dict[str, Any]) -> None:
    """
    Store JSON under group/key. Wrap with a small envelope for future extensibility.
    """
    payload = {
        "created_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "value": value,
        "group": group,
        "key": key,
    }

    # Memory fallback
    if not _USE_BLOB or _BLOB_SVC is None:
        _MEMORY_CACHE[f"{group}/{key}"] = payload
        return

    cont = _ensure_container_once()
    if cont is None:
        # If container can't be ensured, keep at least in memory
        _MEMORY_CACHE[f"{group}/{key}"] = payload
        return

    blob_path = f"{group}/{key}.json"
    try:
        cont.upload_blob(
            blob_path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )
    except Exception as e:
        logging.warning("[cache put] blob failed for %s: %s; writing to memory fallback", blob_path, e)
        _MEMORY_CACHE[f"{group}/{key}"] = payload


def cache_headers(hit: bool) -> Dict[str, str]:
    return {"X-Cache": "HIT" if hit else "MISS"}