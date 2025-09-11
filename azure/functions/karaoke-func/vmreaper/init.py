import os, json, tempfile, shutil, pathlib
from shared import (
    blob_client, containers, get_status, put_status, run_demucs, results_dir,
    upload_file, make_sas_url
)
import yt_dlp

def download_youtube_audio(url: str, out_path: str):
    # Best audio only (m4a/mp3)
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_path,  # e.g., /tmp/in.%(ext)s
        "noplaylist": True,
        "quiet": True,
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    # Return the first existing file path based on template
    for ext in ("mp3", "m4a", "webm", "wav", "flac"):
        p = out_path.replace("%(ext)s", ext)
        if os.path.exists(p): return p
    raise RuntimeError("Audio download failed")

def main(msg: str):
    data = json.loads(msg)
    job_id = data["job_id"]
    model = data.get("model", "htdemucs_ft")
    max_seconds = int(data.get("max_seconds", 600))
    bsc = blob_client()
    in_cont, out_cont, status_cont = containers()

    put_status(bsc, job_id, {"job_id": job_id, "state": "working"})

    with tempfile.TemporaryDirectory() as tmp:
        # Input prep
        in_file = None
        if data.get("youtube_url"):
            # Download into tmp/in.%(ext)s
            in_file = os.path.join(tmp, "in.%(ext)s")
            in_file = download_youtube_audio(data["youtube_url"], in_file)
        elif data.get("blob_name"):
            # Copy blob to tmp file
            bc = bsc.get_blob_client(in_cont, data["blob_name"])
            in_file = os.path.join(tmp, os.path.basename(data["blob_name"]))
            with open(in_file, "wb") as f:
                f.write(bc.download_blob().readall())
        else:
            put_status(bsc, job_id, {"job_id": job_id, "state": "failed", "error": "No input provided"})
            return

        # Demucs out
        out_root = os.path.join(tmp, "out")
        os.makedirs(out_root, exist_ok=True)

        code, out, err = run_demucs(in_file, out_root, model=model, max_seconds=max_seconds)
        if code != 0:
            put_status(bsc, job_id, {"job_id": job_id, "state": "failed", "error": err or out})
            return

        base = os.path.splitext(os.path.basename(in_file))[0]
        res_dir = results_dir(out_root, model, base)
        if not res_dir:
            put_status(bsc, job_id, {"job_id": job_id, "state": "failed", "error": "Output folder not found"})
            return

        # Upload outputs (expect vocals.wav and no_vocals.wav)
        outputs = {}
        for name in ("vocals.wav", "no_vocals.wav"):
            p = os.path.join(res_dir, name)
            if os.path.exists(p):
                blob_name = f"{job_id}/{name}"
                upload_file(bsc, out_cont, blob_name, p, content_type="audio/wav")
                outputs[name] = make_sas_url(bsc, out_cont, blob_name, minutes=240)

        # Final status
        put_status(bsc, job_id, {"job_id": job_id, "state": "done", "outputs": outputs})