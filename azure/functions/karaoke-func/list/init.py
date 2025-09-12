import os, json, datetime, logging
import azure.functions as func
from azure.storage.blob import (
    BlobServiceClient, generate_blob_sas, BlobSasPermissions
)

STOR   = os.environ["STORAGE_CONN"]
OUTPUT = os.environ.get("OUTPUT_CONTAINER", "karaoke-output")
INPUT  = os.environ.get("INPUT_CONTAINER",  "karaoke-input")

BLOB = BlobServiceClient.from_connection_string(STOR)

def _cors():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization"
    }

def _sas_url(container: str, blob: str, minutes: int = 120) -> str:
    account_url = BLOB.url.rstrip("/")
    acc_name = account_url.split("//",1)[1].split(".")[0]  # <account>
    key_cred = BLOB.credential  # uses key from connection string

    expiry = datetime.datetime.utcnow() + datetime.timedelta(minutes=minutes)
    token = generate_blob_sas(
        account_name=acc_name,
        container_name=container,
        blob_name=blob,
        account_key=key_cred.account_key,  # available when using conn string
        permission=BlobSasPermissions(read=True),
        expiry=expiry,
    )
    return f"{account_url}/{container}/{blob}?{token}"

def main(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors())

    try:
        out_cc = BLOB.get_container_client(OUTPUT)
        in_cc  = BLOB.get_container_client(INPUT)

        # Group by job_id (first path segment)
        groups = {}  # job_id -> {"vocals": str, "band": str, "updated": dt}
        for b in out_cc.list_blobs():
            # expect "<job_id>/vocals.wav" or "<job_id>/no_vocals.wav"
            if "/" not in b.name: 
                continue
            job_id, name = b.name.split("/", 1)
            g = groups.setdefault(job_id, {"vocals": None, "band": None, "updated": None})
            if name == "vocals.wav":    g["vocals"] = b.name
            if name == "no_vocals.wav": g["band"]   = b.name
            # keep the most recent modified
            if not g["updated"] or b.last_modified > g["updated"]:
                g["updated"] = b.last_modified

        items = []
        for job_id, g in groups.items():
            if not (g["vocals"] and g["band"]):
                continue  # only completed jobs
            # Try to find original filename from input container
            display = job_id
            try:
                blob_list = list(in_cc.list_blobs(name_starts_with=f"{job_id}/"))
                if blob_list:
                    # use the first file's basename (without extension)
                    raw = blob_list[0].name.split("/",1)[1]
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

        return func.HttpResponse(json.dumps({"items": items}), mimetype="application/json", headers=_cors())

    except Exception as e:
        logging.exception("list failed")
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, mimetype="application/json", headers=_cors())