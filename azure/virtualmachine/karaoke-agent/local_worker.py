# local_worker.py
import os, json, time, tempfile, subprocess, pathlib, traceback
from azure.storage.queue import QueueClient
from azure.storage.blob import BlobServiceClient

# ---- CONFIG: fill these from your Function App settings ----
STORAGE_CONN     = os.environ.get("STORAGE_CONN") or "<PUT YOUR STORAGE CONNECTION STRING HERE>"
INPUT_CONTAINER  = os.environ.get("INPUT_CONTAINER",  "karaoke-input")
OUTPUT_CONTAINER = os.environ.get("OUTPUT_CONTAINER", "karaoke-output")
STATUS_CONTAINER = os.environ.get("STATUS_CONTAINER", "karaoke-status")
QUEUE_NAME       = os.environ.get("QUEUE_NAME",       "karaoke-jobs")
DEMUCS_MODEL     = os.environ.get("DEMUCS_MODEL",     "htdemucs_ft")  # fast
JOBS_PER_RUN     = int(os.environ.get("JOBS_PER_RUN", "0"))  # 0 = loop forever

# ------------------------------------------------------------
BLOB = BlobServiceClient.from_connection_string(STORAGE_CONN)
QCLI = QueueClient.from_connection_string(STORAGE_CONN, QUEUE_NAME)

def put_status(job_id, payload):
    data = json.dumps(payload).encode()
    BLOB.get_container_client(STATUS_CONTAINER).upload_blob(f"{job_id}.json", data, overwrite=True)

def download_input(src, dest_dir):
    if src["type"] == "blob":
        name = src["blob"]
        fn = os.path.join(dest_dir, pathlib.Path(name).name)
        with open(fn, "wb") as f:
            f.write(BLOB.get_container_client(INPUT_CONTAINER).download_blob(name).readall())
        return fn
    else:
        # youtube
        # download best audio and convert to mp3 via ffmpeg
        outtmpl = os.path.join(dest_dir, "input.%(ext)s")
        cmd = ["yt-dlp", "-f", "bestaudio/best", "-x", "--audio-format", "mp3", "-o", outtmpl, src["url"]]
        subprocess.run(cmd, check=True)
        for cand in ("input.mp3","input.m4a","input.webm","input.opus","input.wav"):
            p = os.path.join(dest_dir, cand)
            if os.path.exists(p): return p
        raise RuntimeError("yt-dlp produced no audio file")

def run_demucs(inp, out_dir):
    # CPU fast model; add "--mp3" if you want mp3 outputs
    cmd = ["demucs", "--two-stems", "vocals", "-n", DEMUCS_MODEL, "-j", "2", inp, "-o", out_dir]
    subprocess.run(cmd, check=True)

def find_outputs(base_out_dir, model, basename):
    # demucs writes: {out_dir}/{model}/{basename}/{vocals.wav,no_vocals.wav}
    p = pathlib.Path(base_out_dir) / model / basename
    if p.is_dir():
        voc = p / "vocals.wav"
        band = p / "no_vocals.wav"
        if voc.exists() and band.exists():
            return str(voc), str(band)
    # Fallback scan (model folder may vary)
    for root, dirs, files in os.walk(base_out_dir):
        if "vocals.wav" in files and "no_vocals.wav" in files:
            return os.path.join(root,"vocals.wav"), os.path.join(root,"no_vocals.wav")
    raise RuntimeError("Outputs not found")

def upload_outputs(job_id, vocals, band):
    cc = BLOB.get_container_client(OUTPUT_CONTAINER)
    voc_key = f"{job_id}/vocals.wav"
    band_key= f"{job_id}/no_vocals.wav"
    with open(vocals, "rb") as f: cc.upload_blob(voc_key, f, overwrite=True)
    with open(band,   "rb") as f: cc.upload_blob(band_key,  f, overwrite=True)
    # Not generating SAS here—the Function's status endpoint will already return SAS if you implemented that.
    # If you want direct links (public container), return HTTPS URLs instead.
    return {"vocals.wav": voc_key, "no_vocals.wav": band_key}

def process_one_message():
    msg = QCLI.receive_message(visibility_timeout=60)
    if not msg:
        return False
    try:
        body = json.loads(msg.content)
        job_id = body["job_id"]
        src = body["src"]
        model = DEMUCS_MODEL

        put_status(job_id, {"state":"running","progress":10})
        with tempfile.TemporaryDirectory() as td:
            inp = download_input(src, td)
            basename = pathlib.Path(inp).stem
            put_status(job_id, {"state":"running","progress":40})
            outbase = os.path.join(td, "out")
            run_demucs(inp, outbase)
            put_status(job_id, {"state":"running","progress":85})
            vocals, band = find_outputs(outbase, model, basename)
            outputs = upload_outputs(job_id, vocals, band)
            # You can switch to SAS URLs by generating SAS here, or let your Function compose SAS.
            put_status(job_id, {"state":"done","outputs": outputs})
    except Exception as e:
        traceback.print_exc()
        try:
            put_status(body.get("job_id","unknown"), {"state":"failed","error": str(e)})
        except Exception:
            pass
    finally:
        QCLI.delete_message(msg)
    return True

def main():
    processed = 0
    while True:
        got = process_one_message()
        if got:
            processed += 1
            if JOBS_PER_RUN and processed >= JOBS_PER_RUN:
                break
            continue
        # no message → brief sleep
        time.sleep(2)

if __name__ == "__main__":
    # allow override via env
    main()