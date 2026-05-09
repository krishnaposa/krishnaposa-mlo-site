# submit/init.py
import json, logging, re
from azure.storage.blob import ContentSettings
import azure.functions as func
from shared import BLOB, INPUT, enqueue_job, job_id_for, put_status, ensure_vm_running

YTLINK_RE = re.compile(r'^https?://(www\.)?(youtube\.com|youtu\.be)/', re.I)

def _cors():
    # If you already configured CORS in the Function App settings, you can remove these headers.
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization"
    }

def _json(status: int, payload: dict) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(payload), status_code=status, mimetype="application/json", headers=_cors())

def _safe_name(name: str) -> str:
    # keep it simple: strip path, trim, and remove weird chars
    name = (name or "").split("/")[-1].split("\\")[-1].strip()
    return re.sub(r'[^A-Za-z0-9._ -]', "_", name) or "upload.bin"

def main(req: func.HttpRequest) -> func.HttpResponse:
    # CORS preflight
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors())

    try:
        youtube_url = req.form.get("youtube_url").strip() if (req.form and req.form.get("youtube_url")) else None
        upfile = req.files.get("file") if req.files else None

        # Must provide exactly one
        if bool(youtube_url) == bool(upfile):
            return _json(400, {"error": "Provide exactly one of: file or youtube_url"})

        if youtube_url:
            if not YTLINK_RE.match(youtube_url):
                return _json(400, {"error": "youtube_url must be a valid YouTube link"})
            job_id = job_id_for(youtube_url)
            put_status(job_id, {"state": "queued", "progress": 0})
            src = {"type": "youtube", "url": youtube_url}

        else:
            # file path
            if not upfile or not upfile.filename:
                return _json(400, {"error": "Empty file"})
            fname = _safe_name(upfile.filename)
            job_id = job_id_for(fname)
            put_status(job_id, {"state": "queued", "progress": 0})

            name = f"{job_id}/{fname}"
            BLOB.get_container_client(INPUT).upload_blob(
                name,
                upfile.stream.read(),
                overwrite=True,
                content_settings=ContentSettings(
                    content_type=upfile.mimetype or "application/octet-stream"
                ),
            )
            src = {"type": "blob", "blob": name}

        # enqueue work
        enqueue_job({"job_id": job_id, "src": src})

        payload = {"job_id": job_id}
        try:
            payload["vm"] = ensure_vm_running()
        except Exception as e:
            logging.warning("ensure_vm_running: %s", e)

        return _json(200, payload)

    except Exception as e:
        logging.exception("submit failed")
        return _json(500, {"error": str(e)})