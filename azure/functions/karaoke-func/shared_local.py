# shared.py  (no VM control)
import os, json, time, hashlib
from typing import Optional
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.storage.queue import QueueClient

# ---- Env ----
STOR   = os.environ["STORAGE_CONN"]
INPUT  = os.environ.get("INPUT_CONTAINER",  "karaoke-input")
OUTPUT = os.environ.get("OUTPUT_CONTAINER", "karaoke-output")
STATUS = os.environ.get("STATUS_CONTAINER", "karaoke-status")
QUEUE  = os.environ.get("QUEUE_NAME",       "karaoke-jobs")

# ---- Clients ----
BLOB    = BlobServiceClient.from_connection_string(STOR)
QCLIENT = QueueClient.from_connection_string(STOR, QUEUE)

def _ensure_containers() -> None:
    for name in {INPUT, OUTPUT, STATUS}:
        try:
            BLOB.create_container(name)
        except Exception:
            # already exists is fine
            pass
_ensure_containers()

# ---- Job id / status helpers ----
def job_id_for(name: str) -> str:
    return hashlib.sha1(f"{name}-{time.time()}".encode()).hexdigest()[:16]

def put_status(job_id: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    BLOB.get_container_client(STATUS).upload_blob(
        f"{job_id}.json", data, overwrite=True,
        content_settings=ContentSettings(content_type="application/json"),
    )

def get_status(job_id: str) -> Optional[dict]:
    try:
        raw = BLOB.get_container_client(STATUS).download_blob(f"{job_id}.json").readall()
        return json.loads(raw)
    except Exception:
        return None

def enqueue_job(msg: dict) -> None:
    QCLIENT.send_message(json.dumps(msg))

def queue_length() -> int:
    meta = QCLIENT.get_queue_properties()
    return meta.approximate_message_count or 0