import os, json, time
from azure.storage.blob import BlobClient
from shared import queue_length, deallocate_vm, BLOB

IDLE_MIN = int(os.environ.get("IDLE_MINUTES","5"))

def main(myTimer):
    # Use a tiny blob as heartbeat updated by the VM worker
    bc = BLOB.get_container_client("karaoke-status")
    last = 0
    try:
        last = int(bc.download_blob("_last_done_epoch.txt").content_as_text())
    except Exception:
        pass

    if queue_length() == 0 and last and (time.time() - last) > IDLE_MIN*60:
        deallocate_vm()