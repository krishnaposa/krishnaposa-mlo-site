# list/__init__.py
import os, json, datetime, logging
import azure.functions as func
from urllib.parse import quote
from azure.storage.blob import (
    BlobServiceClient, generate_blob_sas, BlobSasPermissions
)

STOR   = os.environ["STORAGE_CONN"]
OUTPUT = os.environ.get("OUTPUT_CONTAINER", "karaoke-output")
INPUT  = os.environ.get("INPUT_CONTAINER",  "karaoke-input")

BLOB = BlobServiceClient.from_connection_string(STOR)

def _cors():
    return {
        "Access-Control-Allow-Origin": "*",  # or lock to https://www.krishposa.com
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization"
    }

def _conn_info_from_connection_string(conn: str):
    """
    Parse AccountName and AccountKey from a classic Azure Storage connection string.
    Works regardless of SDK internals.
    """
    parts = dict(
        s.split("=", 1) for s in conn.split(";") if "=" in s
    )
    return parts.get("AccountName"), parts.get("AccountKey")

def _sas_url(container: str, blob: str, minutes: int = 120) -> str:
    """
    Build a read-only SAS URL for a single blob.
    """
    account_url = BLOB.url.rstrip("/")  # e.g., https://<account>.blob.core.windows.net
    acc_name, acc_key = _conn_info_from_connection_string(STOR)
    if not acc_name or not acc_key:
        raise RuntimeError("Could not extract AccountName/AccountKey from STORAGE_CONN")

    # give a tiny "start" skew so clients behind clock skew still pass
    start  = datetime.datetime.utcnow() - datetime.timedelta(minutes=2)
    expiry = datetime.datetime.utcnow() + datetime.timedelta(minutes=minutes)

    token = generate_blob_sas(
        account_name=acc_name,
        container_name=container,
        blob_name=blob,
        account_key=acc_key,
        permission=BlobSasPermissions(read=True),
        start=start,
        expiry=expiry,
    )
    # URL-encode the blob path part
    return f"{account_url}/{container}/{quote(blob)}?{token}"

def main(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors())

    try:
        out_cc = BLOB.get_container_client(OUTPUT)
        in_cc  = BLOB.get_container_client(INPUT)

        # Collect finished jobs (those that have both vocals + band)
        groups = {}  # job_id -> {"vocals": str, "band": str, "updated": dt}
        for b in out_cc.list_blobs():
            # Expect "<job_id>/vocals.wav" or "<job_id>/no_vocals.wav"
            # (If you also emit .mp3, you can extend this section accordingly.)
            name = b.name
            if "/" not in name:
                continue
            job_id, leaf = name.split("/", 1)
            g = groups.setdefault(job_id, {"vocals": None, "band": None, "updated": None})
            if leaf.lower() == "vocals.wav":
                g["vocals"] = name
            elif leaf.lower() in ("no_vocals.wav", "accompaniment.wav"):
                # support Spleeter naming too
                g["band"] = name

            if not g["updated"] or (b.last_modified and b.last_modified > g["updated"]):
                g["updated"] = b.last_modified

        items = []
        for job_id, g in groups.items():
            if not (g["vocals"] and g["band"]):
                # only show completed pairs
                continue

            # Try to display the original filename (basename without extension)
            display = job_id
            try:
                blob_list = list(in_cc.list_blobs(name_starts_with=f"{job_id}/"))
                if blob_list:
                    raw = blob_list[0].name.split("/", 1)[1]
                    display = os.path.splitext(os.path.basename(raw))[0]
            except Exception:
                pass

            items.append({
                "job_id": job_id,
                "title": display,
                "updated": g["updated"].isoformat() if g["updated"] else None,
                "vocals_url": _sas_url(OUTPUT, g["vocals"]),
                "band_url":   _sas_url(OUTPUT, g["band"]),
            })

        # newest first
        items.sort(key=lambda x: x.get("updated") or "", reverse=True)

        return func.HttpResponse(
            json.dumps({"items": items}),
            mimetype="application/json",
            headers=_cors()
        )

    except Exception as e:
        logging.exception("list failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
            headers=_cors()
        )