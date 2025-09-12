# local_worker.py
import os, sys, json, time, tempfile, subprocess, pathlib, traceback
from typing import Optional, Tuple
from azure.storage.queue import QueueClient
from azure.storage.blob import BlobServiceClient

# -------------------- CONFIG --------------------
STORAGE_CONN     = os.environ.get("STORAGE_CONN") or "<PUT YOUR STORAGE CONNECTION STRING HERE>"
INPUT_CONTAINER  = os.environ.get("INPUT_CONTAINER",  "karaoke-input")
OUTPUT_CONTAINER = os.environ.get("OUTPUT_CONTAINER", "karaoke-output")
STATUS_CONTAINER = os.environ.get("STATUS_CONTAINER", "karaoke-status")
QUEUE_NAME       = os.environ.get("QUEUE_NAME",       "karaoke-jobs")

# Demucs
DEMUCS_MODEL     = os.environ.get("DEMUCS_MODEL",     "htdemucs_ft")  # fast CPU model
JOBS_PER_RUN     = int(os.environ.get("JOBS_PER_RUN", "0"))  # 0 = loop forever

# Local output directory to KEEP separated files
OUTPUT_BASE      = os.environ.get("OUTPUT_BASE", r"C:\pers\karaoke-out")

# Optional: where ffmpeg.exe lives; auto-prepend to PATH on Windows
FFMPEG_DIR       = os.environ.get("FFMPEG_DIR", r"C:\pers\ffmpeg\bin")

# -------------------- CLIENTS --------------------
BLOB = BlobServiceClient.from_connection_string(STORAGE_CONN)
QCLI = QueueClient.from_connection_string(STORAGE_CONN, QUEUE_NAME)

# Ensure containers exist (idempotent)
for cname in (INPUT_CONTAINER, OUTPUT_CONTAINER, STATUS_CONTAINER):
    try:
        BLOB.create_container(cname)
    except Exception:
        pass
try:
    QCLI.create_queue()
except Exception:
    pass

# Prepend ffmpeg dir to PATH on Windows if present
if os.name == "nt" and FFMPEG_DIR and os.path.isdir(FFMPEG_DIR):
    os.environ["PATH"] = FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")

# -------------------- HELPERS --------------------
def put_status(job_id: str, payload: dict) -> None:
    data = json.dumps(payload).encode()
    BLOB.get_container_client(STATUS_CONTAINER).upload_blob(
        f"{job_id}.json", data, overwrite=True
    )

def download_input(src: dict, dest_dir: str) -> str:
    """
    Returns a local file path to the audio to process.
    """
    if src["type"] == "blob":
        name = src["blob"]  # e.g. "<job_id>/<filename>"
        fn = os.path.join(dest_dir, pathlib.Path(name).name)
        with open(fn, "wb") as f:
            f.write(
                BLOB.get_container_client(INPUT_CONTAINER)
                .download_blob(name)
                .readall()
            )
        return fn
    else:
        # youtube: best audio -> mp3
        outtmpl = os.path.join(dest_dir, "input.%(ext)s")
        # call yt-dlp as a module to avoid PATH issues
        cmd = [sys.executable, "-m", "yt_dlp",
               "-f", "bestaudio/best", "-x", "--audio-format", "mp3",
               "-o", outtmpl, src["url"]]
        subprocess.run(cmd, check=True)
        for cand in ("input.mp3", "input.m4a", "input.webm", "input.opus", "input.wav"):
            p = os.path.join(dest_dir, cand)
            if os.path.exists(p):
                return p
        raise RuntimeError("yt-dlp produced no audio file")

def run_demucs(inp: str) -> str:
    """
    Runs demucs and returns the base output directory (OUTPUT_BASE).
    Keeps files in OUTPUT_BASE so you have local copies.
    """
    os.makedirs(OUTPUT_BASE, exist_ok=True)
    # run demucs as a module to avoid PATH issues
    cmd = [
        sys.executable, "-m", "demucs",
        "--two-stems", "vocals",
        "-n", DEMUCS_MODEL,
        "-j", "2",
        inp,
        "-o", OUTPUT_BASE
    ]
    subprocess.run(cmd, check=True)
    return OUTPUT_BASE

def find_outputs(base_out_dir: str, model: str, basename: str) -> Tuple[str, str]:
    """
    demucs writes: {base_out_dir}/{model}/{basename}/{vocals.wav,no_vocals.wav}
    """
    p = pathlib.Path(base_out_dir) / model / basename
    if p.is_dir():
        voc = p / "vocals.wav"
        band = p / "no_vocals.wav"
        if voc.exists() and band.exists():
            return str(voc), str(band)

    # Fallback scan
    for root, _dirs, files in os.walk(base_out_dir):
        if "vocals.wav" in files and "no_vocals.wav" in files:
            return os.path.join(root, "vocals.wav"), os.path.join(root, "no_vocals.wav")

    raise RuntimeError(f"Outputs not found for {basename} under {base_out_dir}")

def upload_outputs(job_id: str, vocals: str, band: str) -> dict:
    cc = BLOB.get_container_client(OUTPUT_CONTAINER)
    voc_key  = f"{job_id}/vocals.wav"
    band_key = f"{job_id}/no_vocals.wav"
    with open(vocals, "rb") as f:
        cc.upload_blob(voc_key, f, overwrite=True)
    with open(band, "rb") as f:
        cc.upload_blob(band_key, f, overwrite=True)
    return {"vocals.wav": voc_key, "no_vocals.wav": band_key}

def process_one_message() -> bool:
    # receive one message; visibility timeout guards against double-work
    msg = QCLI.receive_message(visibility_timeout=60)
    if not msg:
        return False

    # Azure Queue SDK v12: content is already a string
    body = None
    try:
        body = json.loads(msg.content)
        job_id = body["job_id"]
        src    = body["src"]

        put_status(job_id, {"state": "running", "progress": 10})

        with tempfile.TemporaryDirectory() as td:
            inp = download_input(src, td)
            basename = pathlib.Path(inp).stem

            put_status(job_id, {"state": "running", "progress": 40})

            outbase = run_demucs(inp)

            put_status(job_id, {"state": "running", "progress": 75})

            vocals, band = find_outputs(outbase, DEMUCS_MODEL, basename)

            put_status(job_id, {"state": "running", "progress": 85})

            outputs = upload_outputs(job_id, vocals, band)

            put_status(job_id, {"state": "done", "outputs": outputs})

    except Exception as e:
        traceback.print_exc()
        try:
            jid = (body or {}).get("job_id", "unknown")
            put_status(jid, {"state": "failed", "error": str(e)})
        except Exception:
            pass
    finally:
        # IMPORTANT: delete using id + pop_receipt
        try:
            QCLI.delete_message(msg.id, msg.pop_receipt)
        except Exception:
            pass

    return True

def main():
    processed = 0
    while True:
        got = process_one_message()
        if got:
            processed += 1
            if JOBS_PER_RUN and processed >= JOBS_PER_RUN:
                break
        else:
            time.sleep(2)

if __name__ == "__main__":
    main()