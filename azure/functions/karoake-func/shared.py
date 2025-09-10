import os, uuid, io, json, re, tempfile, zipfile, time, pathlib, subprocess
from datetime import timedelta
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions

SAFE_RX = re.compile(r"[^A-Za-z0-9._-]")

def env(key, default=None): 
    v = os.environ.get(key)
    return v if v is not None else default

def blob_client():
    return BlobServiceClient.from_connection_string(env("STORAGE_CONN") or env("AzureWebJobsStorage"))

def containers():
    return (
        env("INPUT_CONTAINER", "karaoke-input"),
        env("OUTPUT_CONTAINER", "karaoke-output"),
        env("STATUS_CONTAINER", "karaoke-status"),
    )

def queue_name():
    return env("QUEUE_NAME", "karaoke-jobs")

def safe_name(name: str) -> str:
    b = os.path.basename(name or "track")
    return (SAFE_RX.sub("_", b) or "track")[:120]

def put_status(bsc, job_id: str, payload: dict):
    _, _, status_cont = containers()
    bc = bsc.get_blob_client(status_cont, f"{job_id}.json")
    bc.upload_blob(json.dumps(payload).encode("utf-8"), overwrite=True, content_type="application/json")

def get_status(bsc, job_id: str):
    _, _, status_cont = containers()
    bc = bsc.get_blob_client(status_cont, f"{job_id}.json")
    if not bc.exists(): return None
    return json.loads(bc.download_blob().readall().decode("utf-8"))

def upload_input_stream(bsc, job_id: str, filename: str, stream: io.BytesIO):
    in_cont, _, _ = containers()
    name = f"{job_id}/{safe_name(filename)}"
    bc = bsc.get_blob_client(in_cont, name)
    stream.seek(0)
    bc.upload_blob(stream, overwrite=True)
    return name

def upload_file(bsc, container: str, blob_name: str, file_path: str, content_type=None):
    bc = bsc.get_blob_client(container, blob_name)
    with open(file_path, "rb") as f:
        bc.upload_blob(f, overwrite=True, content_type=content_type)

def make_sas_url(bsc, container: str, blob_name: str, minutes=120):
    acc = bsc.account_name
    key = bsc.credential.account_key  # works with conn string auth
    token = generate_blob_sas(
        account_name=acc,
        container_name=container,
        blob_name=blob_name,
        account_key=key,
        permission=BlobSasPermissions(read=True),
        expiry=(time.time() + minutes*60)
    )
    return f"https://{acc}.blob.core.windows.net/{container}/{blob_name}?{token}"

def run_demucs(input_path: str, out_dir: str, model: str, max_seconds: int):
    cmd = [
        "python", "-m", "demucs.separate",
        "--two-stems", "vocals",
        "-n", model,
        "-j", "1",
        "--out", out_dir,
        input_path
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=max_seconds)
    return proc.returncode, proc.stdout, proc.stderr

def results_dir(root_out: str, model: str, basename_no_ext: str):
    # demucs writes: {root}/{model}/{basename}/
    p = pathlib.Path(root_out) / model / basename_no_ext
    if p.is_dir(): return str(p)
    # fallback to first subdir model if name differs
    for d in pathlib.Path(root_out).iterdir():
        if d.is_dir():
            cand = d / basename_no_ext
            if cand.is_dir(): return str(cand)
    return None

def zip_dir_to_bytes(path: str):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in pathlib.Path(path).rglob("*"):
            if p.is_file():
                rel = p.relative_to(path)
                z.write(str(p), str(rel))
    buf.seek(0)
    return buf.read()