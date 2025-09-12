# submit/__init__.py
import json, logging
from azure.storage.blob import ContentSettings
import azure.functions as func
from shared import BLOB, INPUT, enqueue_job, job_id_for, put_status

def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        # ---- read inputs (no await) ----
        youtube_url = req.form.get("youtube_url") if req.form else None
        upfile = req.files.get("file") if req.files else None

        if not youtube_url and not upfile:
            return func.HttpResponse("Provide file or youtube_url", status_code=400)

        job_id = job_id_for(youtube_url or upfile.filename)

        # initial status
        put_status(job_id, {"state": "queued", "progress": 0})

        # upload input
        if upfile:
            name = f"{job_id}/{upfile.filename}"
            BLOB.get_container_client(INPUT).upload_blob(
                name,
                upfile.stream.read(),
                overwrite=True,
                content_settings=ContentSettings(
                    content_type=upfile.mimetype or "application/octet-stream"
                ),
            )
            src = {"type": "blob", "blob": name}
        else:
            src = {"type": "youtube", "url": youtube_url}

        # enqueue
        enqueue_job({"job_id": job_id, "src": src})

        # success
        body = {"job_id": job_id}
        return func.HttpResponse(json.dumps(body), mimetype="application/json", status_code=200)

    except Exception as e:
        logging.exception("submit failed")
        # Return a tiny hint to the client; full stack goes to logs
        body = {"error": str(e)}
        return func.HttpResponse(json.dumps(body), mimetype="application/json", status_code=500)