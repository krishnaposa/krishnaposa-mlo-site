import json, os, uuid, tempfile
from azure.storage.blob import ContentSettings
import logging
import azure.functions as func
from shared_local import BLOB, INPUT, enqueue_job, job_id_for, put_status, ensure_vm_running

async def main(req: func.HttpRequest) -> func.HttpResponse:
    form = await req.form()
    youtube_url = form.get('youtube_url')
    upfile = req.files.get('file')

    if not youtube_url and not upfile:
        return func.HttpResponse("Provide file or youtube_url", status_code=400)

    job_id = job_id_for(youtube_url or upfile.filename)

    # initial status
    put_status(job_id, {"state":"queued","progress":0})

    # upload input
    if upfile:
        name = f"{job_id}/{upfile.filename}"
        BLOB.get_container_client(INPUT).upload_blob(
            name, upfile.stream.read(),
            overwrite=True,
            content_settings=ContentSettings(content_type=upfile.mimetype or "application/octet-stream"),
        )
        src = {"type":"blob", "blob": name}
    else:
        # just pass the URL; VM will download with yt-dlp
        src = {"type":"youtube", "url": youtube_url}

    # enqueue job
    enqueue_job({"job_id": job_id, "src": src})

    # make sure VM is waking up
    state = ensure_vm_running()

    return func.HttpResponse(
        json.dumps({"job_id": job_id, "vm": state}),
        mimetype="application/json"
    )