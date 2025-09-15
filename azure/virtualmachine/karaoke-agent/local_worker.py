# local_worker.py
import os, sys, json, time, tempfile, subprocess, pathlib, traceback
from typing import Tuple
from azure.storage.queue import QueueClient
from azure.storage.blob import BlobServiceClient

# -------------------- CONFIG --------------------
STORAGE_CONN      = os.environ.get("STORAGE_CONN") or "<PUT YOUR STORAGE CONNECTION STRING HERE>"
INPUT_CONTAINER   = os.environ.get("INPUT_CONTAINER",  "karaoke-input")
OUTPUT_CONTAINER  = os.environ.get("OUTPUT_CONTAINER", "karaoke-output")
STATUS_CONTAINER  = os.environ.get("STATUS_CONTAINER", "karaoke-status")
QUEUE_NAME        = os.environ.get("QUEUE_NAME",       "karaoke-jobs")
POISON_QUEUE_NAME = os.environ.get("POISON_QUEUE",     f"{QUEUE_NAME}-poison")

# Separator selection: 'spleeter' (fast, default) or 'demucs' (slower, higher quality)
SEPARATOR         = os.environ.get("SEPARATOR",        "spleeter").lower()

DEMUCS_MODEL      = os.environ.get("DEMUCS_MODEL",     "htdemucs_ft")
JOBS_PER_RUN      = int(os.environ.get("JOBS_PER_RUN", "0"))   # 0 = loop forever
OUTPUT_BASE       = os.environ.get("OUTPUT_BASE",       r"C:\pers\karaoke-out")

# retry policy
MAX_ATTEMPTS      = int(os.environ.get("MAX_ATTEMPTS", "5"))
BASE_DELAY_SEC    = int(os.environ.get("BASE_DELAY_SEC", "5"))   # initial backoff
MAX_DELAY_SEC     = int(os.environ.get("MAX_DELAY_SEC", "900"))  # cap

# ffmpeg path (Windows)
FFMPEG_DIR        = os.environ.get("FFMPEG_DIR", r"C:\pers\ffmpeg\bin")

# -------------------- CLIENTS --------------------
BLOB   = BlobServiceClient.from_connection_string(STORAGE_CONN)
QCLI   = QueueClient.from_connection_string(STORAGE_CONN, QUEUE_NAME)
PCLI   = QueueClient.from_connection_string(STORAGE_CONN, POISON_QUEUE_NAME)

# Ensure containers/queues exist
for cname in (INPUT_CONTAINER, OUTPUT_CONTAINER, STATUS_CONTAINER):
    try:
        BLOB.create_container(cname)
    except Exception:
        pass

for q in (QCLI, PCLI):
    try:
        q.create_queue()
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

def backoff_seconds(attempt: int) -> int:
    # attempt starts at 1 on first failure
    return min(MAX_DELAY_SEC, BASE_DELAY_SEC * (2 ** (attempt - 1)))

def download_input(src: dict, dest_dir: str) -> str:
    """Return local path to audio to process."""
    if src["type"] == "blob":
        name = src["blob"]  # "<job_id>/<filename>"
        fn = os.path.join(dest_dir, pathlib.Path(name).name)
        with open(fn, "wb") as f:
            f.write(
                BLOB.get_container_client(INPUT_CONTAINER)
                .download_blob(name)
                .readall()
            )
        return fn
    else:
        # YouTube: download best audio to mp3 using yt-dlp module (so venv python finds it)
        outtmpl = os.path.join(dest_dir, "input.%(ext)s")
        cmd = [sys.executable, "-m", "yt_dlp",
               "-f", "bestaudio/best", "-x", "--audio-format", "mp3",
               "-o", outtmpl, src["url"]]
        subprocess.run(cmd, check=True)
        for cand in ("input.mp3","input.m4a","input.webm","input.opus","input.wav"):
            p = os.path.join(dest_dir, cand)
            if os.path.exists(p): 
                return p
        raise RuntimeError("yt-dlp produced no audio file")

# -------------------- SEPARATORS --------------------
def run_spleeter(inp: str) -> str:
    """
    Run Spleeter 2-stems (vocals + accompaniment).
    Writes: {OUTPUT_BASE}/spleeter/{basename}/{vocals.wav, accompaniment.wav}
    """
    out_dir = os.path.join(OUTPUT_BASE, "spleeter")
    os.makedirs(out_dir, exist_ok=True)
    cmd = [
        sys.executable, "-m", "spleeter", "separate",
        "-p", "spleeter:2stems",
        "-o", out_dir,
        inp
    ]
    subprocess.run(cmd, check=True)
    return out_dir

def find_outputs_spleeter(base_out_dir: str, basename: str) -> Tuple[str, str]:
    p = pathlib.Path(base_out_dir) / basename
    voc = p / "vocals.wav"
    acc = p / "accompaniment.wav"
    if voc.exists() and acc.exists():
        # Return accompaniment as "band"
        return str(voc), str(acc)
    # fallback scan (just in case)
    for root, _dirs, files in os.walk(base_out_dir):
        if "vocals.wav" in files and "accompaniment.wav" in files:
            return os.path.join(root, "vocals.wav"), os.path.join(root, "accompaniment.wav")
    raise RuntimeError(f"Spleeter outputs not found for {basename}")

def run_demucs(inp: str) -> str:
    """
    Run Demucs (WAV export). Writes:
      {OUTPUT_BASE}/{model}/{basename}/{vocals.wav, no_vocals.wav}
    """
    os.makedirs(OUTPUT_BASE, exist_ok=True)
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

def find_outputs_demucs(base_out_dir: str, model: str, basename: str) -> Tuple[str, str]:
    p = pathlib.Path(base_out_dir) / model / basename
    if p.is_dir():
        voc, band = p / "vocals.wav", p / "no_vocals.wav"
        if voc.exists() and band.exists():
            return str(voc), str(band)
    for root, _dirs, files in os.walk(base_out_dir):
        if "vocals.wav" in files and "no_vocals.wav" in files:
            return os.path.join(root,"vocals.wav"), os.path.join(root,"no_vocals.wav")
    raise RuntimeError(f"Demucs outputs not found for {basename}")

def upload_outputs(job_id: str, vocals: str, bandlike: str) -> dict:
    """
    Upload results to OUTPUT_CONTAINER under {job_id}/.
    If bandlike is Spleeter's 'accompaniment.wav', it will still be published as 'no_vocals.wav'.
    """
    cc = BLOB.get_container_client(OUTPUT_CONTAINER)
    voc_key  = f"{job_id}/vocals.wav"
    band_key = f"{job_id}/no_vocals.wav"
    with open(vocals,  "rb") as f: cc.upload_blob(voc_key,  f, overwrite=True)
    with open(bandlike,"rb") as f: cc.upload_blob(band_key, f, overwrite=True)
    return {"vocals.wav": voc_key, "no_vocals.wav": band_key}

# -------------------- MAIN LOOP --------------------
def process_one_message() -> bool:
    # receive single message; keep it invisible for 60s while we work
    msg = QCLI.receive_message(visibility_timeout=60)
    if not msg:
        return False

    # Parse body; maintain an explicit 'attempt' counter in content
    try:
        body = json.loads(msg.content)
    except Exception:
        # if message is corrupted, move to poison
        PCLI.send_message(json.dumps({"error": "invalid json", "raw": msg.content}))
        QCLI.delete_message(msg.id, msg.pop_receipt)
        return True

    job_id  = body.get("job_id") or "unknown"
    src     = body.get("src") or {}
    attempt = int(body.get("attempt", 0))  # 0 on first try

    try:
        put_status(job_id, {"state": "running", "progress": 10, "attempt": attempt})

        with tempfile.TemporaryDirectory() as td:
            inp = download_input(src, td)
            basename = pathlib.Path(inp).stem

            put_status(job_id, {"state": "running", "progress": 40, "attempt": attempt})

            if SEPARATOR == "spleeter":
                outbase = run_spleeter(inp)
                put_status(job_id, {"state": "running", "progress": 75, "attempt": attempt})
                vocals, band = find_outputs_spleeter(outbase, basename)
            else:
                outbase = run_demucs(inp)
                put_status(job_id, {"state": "running", "progress": 75, "attempt": attempt})
                vocals, band = find_outputs_demucs(outbase, DEMUCS_MODEL, basename)

            put_status(job_id, {"state": "running", "progress": 85, "attempt": attempt})
            outputs = upload_outputs(job_id, vocals, band)

        put_status(job_id, {"state": "done", "outputs": outputs})
        # success → delete
        QCLI.delete_message(msg.id, msg.pop_receipt)
        return True

    except subprocess.CalledProcessError as e:
        # demucs/spleeter/ffmpeg/yt-dlp exit non-zero → retry
        return _handle_failure(msg, body, job_id, f"process error: {e}")

    except Exception as e:
        # any other error → retry up to MAX_ATTEMPTS
        return _handle_failure(msg, body, job_id, str(e))


def _handle_failure(msg, body, job_id, err_text) -> bool:
    attempt = int(body.get("attempt", 0)) + 1
    body["attempt"] = attempt

    # human-friendly status
    if attempt < MAX_ATTEMPTS:
        delay = backoff_seconds(attempt)
        put_status(job_id, {
            "state": "failed",
            "error": err_text,
            "retrying": True,
            "attempt": attempt,
            "next_retry_in_seconds": delay
        })
        # Requeue by updating the SAME message: set new body + visibility timeout
        try:
            QCLI.update_message(msg.id, msg.pop_receipt,
                                content=json.dumps(body),
                                visibility_timeout=delay)
        except Exception:
            # If update fails, last resort: delete and re-send (rare)
            try:
                QCLI.delete_message(msg.id, msg.pop_receipt)
            except Exception:
                pass
            QCLI.send_message(json.dumps(body))
        return True
    else:
        # move to poison and delete original
        put_status(job_id, {
            "state": "failed",
            "error": err_text,
            "retrying": False,
            "attempt": attempt,
            "poisoned": True
        })
        try:
            PCLI.send_message(json.dumps({"job_id": job_id, "src": body.get("src"), "error": err_text}))
        finally:
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