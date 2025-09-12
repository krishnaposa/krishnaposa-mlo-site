import json, logging
from azure.storage.blob import ContentSettings
import azure.functions as func
from shared_local import BLOB, INPUT, enqueue_job, job_id_for, put_status

async def main(req: func.HttpRequest) -> func.HttpResponse:
    # Grab fields safely
    youtube_url = None
    upfile = None
    try:
        if req.form:
            youtube_url = req.form.get("youtube_url")
        if req.files:
            upfile = req.files.get("file")
    except Exception as e:
        logging.error(f"Form parse error: {e}")

    if not youtube_url and not upfile:
        return func.HttpResponse("Provide file or youtube_url", status_code=400)

    job_id = job_id_for(youtube_url or upfile.filename)
    put_status(job_id, {"state": "queued", "progress": 0})

    if upfile:
        name = f"{job_id}/{upfile.filename}"
        BLOB.get_container_client(INPUT).upload_blob(
            name, upfile.stream.read(),
            overwrite=True,
            content_settings=ContentSettings(
                content_type=upfile.mimetype or "application/octet-stream"
            ),
        )
        src = {"type": "blob", "blob": name}
    else:
        src = {"type": "youtube", "url": youtube_url}

    enqueue_job({"job_id": job_id, "src": src})

    return func.HttpResponse(
        json.dumps({"job_id": job_id}),
        mimetype="application/json"
    )