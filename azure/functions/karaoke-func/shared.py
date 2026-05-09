import os, json, time, hashlib
from azure.storage.blob import BlobServiceClient
from azure.storage.queue import QueueClient
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient

STOR = os.environ["STORAGE_CONN"]
INPUT = os.environ.get("INPUT_CONTAINER","karaoke-input")
OUTPUT = os.environ.get("OUTPUT_CONTAINER","karaoke-output")
STATUS = os.environ.get("STATUS_CONTAINER","karaoke-status")
QUEUE  = os.environ.get("QUEUE_NAME","karaoke-jobs")

BLOB = BlobServiceClient.from_connection_string(STOR)
QCLIENT = QueueClient.from_connection_string(STOR, QUEUE)


def worker_vm_enabled() -> bool:
    """When false, skip Azure VM start/deallocate (e.g. worker is local_worker.py on a laptop)."""
    v = (os.environ.get("WORKER_VM_ENABLED") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _vm_ids():
    return (
        os.environ["SUBSCRIPTION_ID"],
        os.environ["RESOURCE_GROUP"],
        os.environ["VM_NAME"],
    )

def job_id_for(name: str) -> str:
    return hashlib.sha1(f"{name}-{time.time()}".encode()).hexdigest()[:16]

def put_status(job_id: str, payload: dict):
    data = json.dumps(payload).encode()
    BLOB.get_container_client(STATUS).upload_blob(f"{job_id}.json", data, overwrite=True)

def get_status(job_id: str):
    try:
        b = BLOB.get_container_client(STATUS).download_blob(f"{job_id}.json").readall()
        return json.loads(b)
    except Exception:
        return None

def enqueue_job(msg: dict):
    QCLIENT.send_message(json.dumps(msg))

# ---------- VM control ----------
def _compute():
    sub, _, _ = _vm_ids()
    cred = DefaultAzureCredential(exclude_interactive_browser_credential=False)
    return ComputeManagementClient(cred, sub)

def ensure_vm_running():
    if not worker_vm_enabled():
        return "disabled"
    _, rg, name = _vm_ids()
    cm = _compute()
    vm = cm.virtual_machines.get(rg, name, expand="instanceView")
    statuses = [s.code for s in vm.instance_view.statuses]
    if any("powerstate/running" in s for s in statuses):
        return "running"
    cm.virtual_machines.begin_start(rg, name).wait()
    return "started"

def deallocate_vm():
    if not worker_vm_enabled():
        return
    _, rg, name = _vm_ids()
    cm = _compute()
    cm.virtual_machines.begin_deallocate(rg, name).wait()

def queue_length() -> int:
    meta = QCLIENT.get_queue_properties()
    return meta.approximate_message_count or 0