#!/usr/bin/env python3
import os, json, time, tempfile, subprocess, sys, pathlib, traceback
from azure.storage.queue import QueueClient
from azure.storage.blob import BlobServiceClient

STOR = os.environ["STORAGE_CONN"]
INPUT = os.environ.get("INPUT_CONTAINER","karaoke-input")
OUTPUT = os.environ.get("OUTPUT_CONTAINER","karaoke-output")
STATUS = os.environ.get("STATUS_CONTAINER","karaoke-status")
QUEUE  = os.environ.get("QUEUE_NAME","karaoke-jobs")

BLOB = BlobServiceClient.from_connection_string(STOR)
QCLI = QueueClient.from_connection_string(STOR, QUEUE)

def put_status(job_id, payload):
    data = json.dumps(payload).encode()
    BLOB.get_container_client(STATUS).upload_blob(f"{job_id}.json", data, overwrite=True)

def set_last_done():
    BLOB.get_container_client(STATUS).upload_blob("_last_done_epoch.txt", str(int(time.time())), overwrite=True)

def download_input(src, dest_dir):
    if src["type"] == "blob":
        name = src["blob"]
        fn = os.path.join(dest_dir, pathlib.Path(name).name)
        with open(fn, "wb") as f:
            f.write(BLOB.get_container_client(INPUT).download_blob(name).readall())
        return fn
    else:
        # youtube
        fn = os.path.join(dest_dir, "input.m4a")
        cmd = ["yt-dlp", "-f", "bestaudio/best", "-x", "--audio-format", "mp3", "-o", os.path.join(dest_dir, "input.%(ext)s"), src["url"]]
        subprocess.run(cmd, check=True)
        # pick mp3/wav produced
        for cand in ("input.mp3","input.m4a","input.webm","input.opus","input.wav"):
            p = os.path.join(dest_dir, cand)
            if os.path.exists(p): return p
        raise RuntimeError("yt-dlp produced no audio file")

def run_demucs(inp, out_dir):
    # fast model
    cmd = ["demucs", "--two-stems", "vocals", "-n", "htdemucs_ft", "-j", "2", inp, "-o", out_dir]
    subprocess.run(cmd, check=True)

def find_outputs(base_out_dir):
    # demucs writes: <outdir>/htdemucs_ft/<basename>/{vocals.wav,no_vocals.wav}
    for root, dirs, files in os.walk(base_out_dir):
        if "vocals.wav" in files:
            return os.path.join(root,"vocals.wav"), os.path.join(root,"no_vocals.wav")
    raise RuntimeError("Outputs not found")

def upload_outputs(job_id, vocals, band):
    cc = BLOB.get_container_client(OUTPUT)
    voc_key = f"{job_id}/vocals.wav"
    band_key= f"{job_id}/no_vocals.wav"
    for key, path in [(voc_key,vocals),(band_key,band)]:
        with open(path, "rb") as f:
            cc.upload_blob(key, f, overwrite=True)
    # build public URLs (if container has SAS policy you can generate SAS; else Function can serve)
    return {"vocals.wav": f"/{OUTPUT}/{voc_key}", "no_vocals.wav": f"/{OUTPUT}/{band_key}"}

def main_loop():
    idle_streak = 0
    while True:
        msg = QCLI.receive_message(visibility_timeout=60)
        if not msg:
            idle_streak += 1
            if idle_streak >= 5:
                set_last_done()
            time.sleep(10)
            continue

        idle_streak = 0
        body = json.loads(msg.content)
        job_id = body["job_id"]
        try:
            put_status(job_id, {"state":"running","progress":10})
            with tempfile.TemporaryDirectory() as td:
                inp = download_input(body["src"], td)
                put_status(job_id, {"state":"running","progress":40})
                outbase = os.path.join(td, "out")
                run_demucs(inp, outbase)
                put_status(job_id, {"state":"running","progress":85})
                vocals, band = find_outputs(outbase)
                urls = upload_outputs(job_id, vocals, band)
                put_status(job_id, {"state":"done","outputs": urls})
                set_last_done()
        except Exception as e:
            traceback.print_exc()
            put_status(job_id, {"state":"failed","error": str(e)})
        finally:
            QCLI.delete_message(msg)

if __name__ == "__main__":
    # Read env from /etc/karaoke-agent.env if present
    envf = "/etc/karaoke-agent.env"
    if os.path.exists(envf):
        with open(envf) as f:
            for line in f:
                if "=" in line:
                    k,v=line.strip().split("=",1)
                    os.environ.setdefault(k,v)
    main_loop()