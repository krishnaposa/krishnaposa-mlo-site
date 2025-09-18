# local_worker.py
import os, sys, json, time, tempfile, subprocess, pathlib, logging
from typing import Tuple, Optional, Any
from azure.storage.queue import QueueClient
from azure.storage.blob import BlobServiceClient

# -------------------- LOGGING --------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
log = logging.getLogger("karaoke-worker")

def jlog(job_id: Optional[str], msg: str, **extra: Any):
    prefix = f"[job {job_id}] " if job_id else ""
    if extra:
        msg = f"{msg} | " + " ".join(f"{k}={v}" for k,v in extra.items())
    log.info(prefix + msg)

def jwarn(job_id: Optional[str], msg: str, **extra: Any):
    prefix = f"[job {job_id}] " if job_id else ""
    if extra:
        msg = f"{msg} | " + " ".join(f"{k}={v}" for k,v in extra.items())
    log.warning(prefix + msg)

def jerr(job_id: Optional[str], msg: str, **extra: Any):
    prefix = f"[job {job_id}] " if job_id else ""
    if extra:
        msg = f"{msg} | " + " ".join(f"{k}={v}" for k,v in extra.items())
    log.error(prefix + msg)

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

# Log config summary (no secrets)
log.info(
    "Startup | sep=%s demucs_model=%s jobs_per_run=%s ffmpeg_dir=%s",
    SEPARATOR, DEMUCS_MODEL, JOBS_PER_RUN, FFMPEG_DIR
)

# -------------------- HELPERS --------------------
def put_status(job_id: str, payload: dict) -> None:
    try:
        data = json.dumps(payload).encode()
        BLOB.get_container_client(STATUS_CONTAINER).upload_blob(
            f"{job_id}.json", data, overwrite=True
        )
        jlog(job_id, "status updated", **payload)
    except Exception as e:
        jwarn(job_id, "status update failed", error=str(e))

def backoff_seconds(attempt: int) -> int:
    # attempt starts at 1 on first failure
    return min(MAX_DELAY_SEC, BASE_DELAY_SEC * (2 ** (attempt - 1)))

def run_cmd(cmd: list, job_id: Optional[str], desc: str, cwd: Optional[str] = None, env: Optional[dict] = None):
    """Run a subprocess and log stdout/stderr on error. Returns CompletedProcess."""
    jlog(job_id, f"run {desc} start", cmd=" ".join(cmd))
    t0 = time.time()
    try:
        cp = subprocess.run(
            cmd, cwd=cwd, env=env, check=True,
            capture_output=True, text=True
        )
        dur = time.time() - t0
        if cp.stdout:
            log.debug("[job %s] %s stdout:\n%s", job_id, desc, cp.stdout[:4000])
        jlog(job_id, f"run {desc} ok", duration_s=f"{dur:.2f}")
        return cp
    except subprocess.CalledProcessError as e:
        dur = time.time() - t0
        jerr(job_id, f"run {desc} failed", duration_s=f"{dur:.2f}", returncode=e.returncode)
        if e.stdout:
            log.error("[job %s] %s stdout:\n%s", job_id, desc, e.stdout[:8000])
        if e.stderr:
            log.error("[job %s] %s stderr:\n%s", job_id, desc, e.stderr[:8000])
        raise

def download_input_from_blob(blob_key: str, dest_dir: str, job_id: Optional[str]) -> str:
    """Download input from INPUT_CONTAINER/<blob_key> to dest_dir and return local path."""
    t0 = time.time()
    jlog(job_id, "download input blob start", blob=blob_key)
    data = (
        BLOB.get_container_client(INPUT_CONTAINER)
        .download_blob(blob_key)
        .readall()
    )
    fn = os.path.join(dest_dir, pathlib.Path(blob_key).name)
    with open(fn, "wb") as f:
        f.write(data)
    jlog(job_id, "download input blob ok",
         bytes=len(data), seconds=f"{time.time()-t0:.2f}", path=fn)
    return fn

# -------------------- SEPARATORS --------------------
def run_spleeter(inp: str, job_id: Optional[str]) -> str:
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
    run_cmd(cmd, job_id, "spleeter")
    return out_dir

def find_outputs_spleeter(base_out_dir: str, basename: str, job_id: Optional[str]) -> Tuple[str, str]:
    p = pathlib.Path(base_out_dir) / basename
    jlog(job_id, "scan spleeter outputs", path=str(p))
    voc = p / "vocals.wav"
    acc = p / "accompaniment.wav"
    if voc.exists() and acc.exists():
        jlog(job_id, "spleeter outputs found", vocals=str(voc), band=str(acc))
        return str(voc), str(acc)  # acc -> band
    # fallback scan
    for root, _dirs, files in os.walk(base_out_dir):
        if "vocals.wav" in files and "accompaniment.wav" in files:
            voc = os.path.join(root, "vocals.wav")
            acc = os.path.join(root, "accompaniment.wav")
            jlog(job_id, "spleeter outputs found (fallback)", vocals=voc, band=acc)
            return voc, acc
    raise RuntimeError(f"Spleeter outputs not found for {basename}")

def run_demucs(inp: str, job_id: Optional[str]) -> str:
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
    run_cmd(cmd, job_id, "demucs")
    return OUTPUT_BASE

def find_outputs_demucs(base_out_dir: str, model: str, basename: str, job_id: Optional[str]) -> Tuple[str, str]:
    p = pathlib.Path(base_out_dir) / model / basename
    jlog(job_id, "scan demucs outputs", path=str(p))
    if p.is_dir():
        voc, band = p / "vocals.wav", p / "no_vocals.wav"
        if voc.exists() and band.exists():
            jlog(job_id, "demucs outputs found", vocals=str(voc), band=str(band))
            return str(voc), str(band)
    for root, _dirs, files in os.walk(base_out_dir):
        if "vocals.wav" in files and "no_vocals.wav" in files:
            voc = os.path.join(root,"vocals.wav")
            band = os.path.join(root,"no_vocals.wav")
            jlog(job_id, "demucs outputs found (fallback)", vocals=voc, band=band)
            return voc, band
    raise RuntimeError(f"Demucs outputs not found for {basename}")

def upload_outputs(job_id: str, vocals: str, bandlike: str) -> dict:
    """
    Upload results to OUTPUT_CONTAINER under {job_id}/.
    If bandlike is Spleeter's 'accompaniment.wav', it will still be published as 'no_vocals.wav'.
    """
    cc = BLOB.get_container_client(OUTPUT_CONTAINER)
    voc_key  = f"{job_id}/vocals.wav"
    band_key = f"{job_id}/no_vocals.wav"
    jlog(job_id, "upload start", vocals=vocals, band=bandlike)
    t0 = time.time()
    with open(vocals,  "rb") as f:
        data = f.read()
        cc.upload_blob(voc_key, data, overwrite=True)
        jlog(job_id, "upload vocals ok", bytes=len(data))
    with open(bandlike,"rb") as f:
        data = f.read()
        cc.upload_blob(band_key, data, overwrite=True)
        jlog(job_id, "upload band ok", bytes=len(data))
    jlog(job_id, "upload complete", seconds=f"{time.time()-t0:.2f}")
    return {"vocals.wav": voc_key, "no_vocals.wav": band_key}

# -------------------- MAIN LOOP --------------------
def process_one_message() -> bool:
    msg = QCLI.receive_message(visibility_timeout=60)
    if not msg:
        log.debug("queue empty")
        return False

    # Parse body; maintain an explicit 'attempt' counter in content
    try:
        body = json.loads(msg.content)
    except Exception:
        log.error("invalid json in queue message; moving to poison")
        PCLI.send_message(json.dumps({"error": "invalid json", "raw": msg.content}))
        QCLI.delete_message(msg.id, msg.pop_receipt)
        return True

    job_id  = body.get("job_id") or "unknown"
    src     = body.get("src") or {}
    attempt = int(body.get("attempt", 0))  # 0 on first try

    jlog(job_id, "message received", attempt=attempt, src_type=src.get("type"))

    try:
        put_status(job_id, {"state": "running", "progress": 10, "attempt": attempt})

        with tempfile.TemporaryDirectory() as td:
            t_total = time.time()
            jlog(job_id, "workdir ready", dir=td)

            # ------ INPUT (BLOB ONLY) ------
            if src.get("type") != "blob" or not src.get("blob"):
                raise RuntimeError("Only blob uploads are supported. Missing src.blob.")
            t0 = time.time()
            inp = download_input_from_blob(src["blob"], td, job_id)
            jlog(job_id, "input ready", path=inp, seconds=f"{time.time()-t0:.2f}")
            basename = pathlib.Path(inp).stem

            put_status(job_id, {"state": "running", "progress": 40, "attempt": attempt})

            # ------ SEPARATE ------
            if SEPARATOR == "spleeter":
                jlog(job_id, "separator start", type="spleeter")
                outbase = run_spleeter(inp, job_id)
                put_status(job_id, {"state": "running", "progress": 75, "attempt": attempt})
                vocals, band = find_outputs_spleeter(outbase, basename, job_id)
            else:
                jlog(job_id, "separator start", type="demucs", model=DEMUCS_MODEL)
                outbase = run_demucs(inp, job_id)
                put_status(job_id, {"state": "running", "progress": 75, "attempt": attempt})
                vocals, band = find_outputs_demucs(outbase, DEMUCS_MODEL, basename, job_id)

            # ------ UPLOAD ------
            put_status(job_id, {"state": "running", "progress": 85, "attempt": attempt})
            outputs = upload_outputs(job_id, vocals, band)

        total_s = f"{time.time()-t_total:.2f}"
        put_status(job_id, {"state": "done", "outputs": outputs, "seconds": total_s})
        jlog(job_id, "job complete", seconds=total_s, outputs=outputs)
        # success → delete
        QCLI.delete_message(msg.id, msg.pop_receipt)
        return True

    except subprocess.CalledProcessError as e:
        # separator/ffmpeg exit non-zero → retry
        return _handle_failure(msg, body, job_id, f"process error: {e}")

    except Exception as e:
        # any other error → retry up to MAX_ATTEMPTS
        jerr(job_id, "exception", error=str(e))
        log.error("traceback:\n%s", traceback.format_exc())
        return _handle_failure(msg, body, job_id, str(e))

def _handle_failure(msg, body, job_id, err_text) -> bool:
    attempt = int(body.get("attempt", 0)) + 1
    body["attempt"] = attempt

    if attempt < MAX_ATTEMPTS:
        delay = backoff_seconds(attempt)
        put_status(job_id, {
            "state": "failed",
            "error": err_text,
            "retrying": True,
            "attempt": attempt,
            "next_retry_in_seconds": delay
        })
        jwarn(job_id, "requeue with backoff", attempt=attempt, delay_s=delay, error=err_text)
        # Requeue by updating the SAME message
        try:
            QCLI.update_message(
                msg.id, msg.pop_receipt,
                content=json.dumps(body),
                visibility_timeout=delay
            )
        except Exception:
            # last resort: delete and re-send
            try:
                QCLI.delete_message(msg.id, msg.pop_receipt)
            except Exception:
                pass
            QCLI.send_message(json.dumps(body))
        return True
    else:
        put_status(job_id, {
            "state": "failed",
            "error": err_text,
            "retrying": False,
            "attempt": attempt,
            "poisoned": True
        })
        jerr(job_id, "poisoned", attempt=attempt, error=err_text)
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