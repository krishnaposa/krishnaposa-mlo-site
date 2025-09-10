import io, json, uuid, azure.functions as func
from shared import blob_client, upload_input_stream, put_status, safe_name, queue_name, env

def main(req: func.HttpRequest, msg: func.Out[str]) -> func.HttpResponse:
    bsc = blob_client()

    # Accept either file upload or youtube_url
    youtube_url = req.form.get("youtube_url") if req.form else req.params.get("youtube_url")
    file = None
    try:
        if hasattr(req, "files") and "file" in req.files:
            file = req.files["file"]
    except Exception:
        pass

    if not youtube_url and not file:
        return func.HttpResponse("Send multipart with 'file' OR provide 'youtube_url' param.", status_code=400)

    job_id = uuid.uuid4().hex
    status_url = f"/api/status/{job_id}"

    # Minimal status up front
    put_status(bsc, job_id, {"job_id": job_id, "state": "queued"})

    blob_name = None
    if file:
        stream = io.BytesIO(file.read())
        filename = file.filename or "track"
        blob_name = upload_input_stream(bsc, job_id, filename, stream)

    # Build queue payload
    payload = {
        "job_id": job_id,
        "blob_name": blob_name,          # may be None when using yt
        "youtube_url": youtube_url,      # may be None when using file
        "model": env("DEMUCS_MODEL", "htdemucs_ft"),
        "max_seconds": int(env("MAX_SECONDS", "600"))
    }
    msg.set(json.dumps(payload))

    return func.HttpResponse(
        json.dumps({"ok": True, "job_id": job_id, "status_url": status_url}),
        mimetype="application/json"
    )