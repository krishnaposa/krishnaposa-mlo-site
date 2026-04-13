#!/usr/bin/env python3
"""
Local karaoke pipeline without Azure: HTTP API + filesystem queue + optional split worker.

Layout under KARAOKE_LOCAL_ROOT (default: ~/.karaoke-local):
  input/   — uploads land here as {job_id}_{original_name} (queue)
  output/  — {job_id}/vocals.wav and {job_id}/no_vocals.wav
  status/  — {job_id}.json (same shape as cloud status blobs)

Implements the same routes the web UI expects:
  POST /api/submit     — multipart field "file" (combined mp3/wav/…)
  GET  /api/status/{job_id}
  GET  /api/out/{job_id}/vocals.wav|no_vocals.wav — audio for the player

Run:
  set SEPARATOR=spleeter   (or demucs)
  python karaoke/local_folder_queue.py

Then open karaoke/index-local.html (set KARAOKE_API_BASE to match, default http://127.0.0.1:8787).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Dict, Optional, Tuple

# --- config ---
LOG = logging.getLogger("karaoke-local")

ROOT = Path(os.environ.get("KARAOKE_LOCAL_ROOT", Path.home() / ".karaoke-local")).expanduser()
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
STATUS_DIR = ROOT / "status"

HOST = os.environ.get("KARAOKE_LOCAL_HOST", "127.0.0.1")
PORT = int(os.environ.get("KARAOKE_LOCAL_PORT", "8787"))
PUBLIC_BASE = os.environ.get("KARAOKE_LOCAL_PUBLIC_BASE", f"http://{HOST}:{PORT}").rstrip("/")

SEPARATOR = os.environ.get("SEPARATOR", "spleeter").lower().strip()
DEMUCS_MODEL = os.environ.get("DEMUCS_MODEL", "htdemucs_ft")

JOB_ID_RE = re.compile(r"^([a-f0-9]{16})_(.+)$", re.I)

_processing: set[str] = set()
_lock = threading.Lock()


def _ensure_dirs() -> None:
    for d in (INPUT_DIR, OUTPUT_DIR, STATUS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _ffmpeg_path_prep() -> None:
    d = (os.environ.get("FFMPEG_DIR") or "").strip()
    if d:
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


def job_id_for(name: str) -> str:
    return hashlib.sha1(f"{name}-{time.time()}".encode()).hexdigest()[:16]


def safe_name(name: str) -> str:
    name = (name or "").split("/")[-1].split("\\")[-1].strip()
    return re.sub(r"[^A-Za-z0-9._ -]", "_", name) or "upload.bin"


def status_path(job_id: str) -> Path:
    return STATUS_DIR / f"{job_id}.json"


def put_status(job_id: str, payload: Dict[str, Any]) -> None:
    p = status_path(job_id)
    p.write_text(json.dumps(payload), encoding="utf-8")


def get_status(job_id: str) -> Optional[Dict[str, Any]]:
    p = status_path(job_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def run_cmd(cmd: list[str], job_id: str, desc: str) -> subprocess.CompletedProcess[str]:
    LOG.info("[%s] starting %s: %s", job_id, desc, " ".join(cmd))
    return subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def run_spleeter(inp: Path, work_base: Path, job_id: str) -> Path:
    out_dir = work_base / "spleeter"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "spleeter",
        "separate",
        "-p",
        "spleeter:2stems",
        "-o",
        str(out_dir),
        str(inp),
    ]
    run_cmd(cmd, job_id, "spleeter")
    return out_dir


def find_spleeter_vocals_band(base: Path, basename: str, job_id: str) -> Tuple[Path, Path]:
    p = base / basename
    voc, acc = p / "vocals.wav", p / "accompaniment.wav"
    if voc.is_file() and acc.is_file():
        return voc, acc
    for root, _, files in os.walk(base):
        if "vocals.wav" in files and "accompaniment.wav" in files:
            return Path(root) / "vocals.wav", Path(root) / "accompaniment.wav"
    raise RuntimeError("Spleeter outputs not found")


def run_demucs(inp: Path, work_base: Path, job_id: str) -> Path:
    work_base.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "demucs",
        "--two-stems",
        "vocals",
        "-n",
        DEMUCS_MODEL,
        "-j",
        "2",
        str(inp),
        "-o",
        str(work_base),
    ]
    run_cmd(cmd, job_id, "demucs")
    return work_base


def find_demucs_vocals_band(base: Path, model: str, basename: str, job_id: str) -> Tuple[Path, Path]:
    p = base / model / basename
    voc, band = p / "vocals.wav", p / "no_vocals.wav"
    if voc.is_file() and band.is_file():
        return voc, band
    for root, _, files in os.walk(base):
        if "vocals.wav" in files and "no_vocals.wav" in files:
            return Path(root) / "vocals.wav", Path(root) / "no_vocals.wav"
    raise RuntimeError("Demucs outputs not found")


def process_job_file(input_file: Path, job_id: str, original_name: str) -> None:
    """Split input_file, write output/{job_id}/*.wav, update status."""
    with _lock:
        if job_id in _processing:
            return
        _processing.add(job_id)

    st = get_status(job_id) or {}
    if st.get("state") not in (None, "queued"):
        with _lock:
            _processing.discard(job_id)
        return

    basename = Path(original_name).stem
    put_status(
        job_id,
        {
            "state": "running",
            "progress": 15,
            "original_name": original_name,
            "attempt": 0,
        },
    )

    try:
        with tempfile.TemporaryDirectory(prefix=f"karaoke-{job_id}-") as td:
            tdp = Path(td)
            work_audio = tdp / Path(original_name).name
            shutil.copy2(input_file, work_audio)
            put_status(job_id, {"state": "running", "progress": 35, "original_name": original_name})

            if SEPARATOR == "demucs":
                out_base = run_demucs(work_audio, tdp / "demucs_out", job_id)
                put_status(job_id, {"state": "running", "progress": 70, "original_name": original_name})
                voc, band = find_demucs_vocals_band(out_base, DEMUCS_MODEL, basename, job_id)
            else:
                sp_out = run_spleeter(work_audio, tdp, job_id)
                put_status(job_id, {"state": "running", "progress": 70, "original_name": original_name})
                voc, band = find_spleeter_vocals_band(sp_out, basename, job_id)

            out_job = OUTPUT_DIR / job_id
            out_job.mkdir(parents=True, exist_ok=True)
            shutil.copy2(voc, out_job / "vocals.wav")
            shutil.copy2(band, out_job / "no_vocals.wav")

        outputs = {
            "vocals.wav": f"{PUBLIC_BASE}/api/out/{job_id}/vocals.wav",
            "no_vocals.wav": f"{PUBLIC_BASE}/api/out/{job_id}/no_vocals.wav",
        }
        put_status(
            job_id,
            {
                "state": "done",
                "progress": 100,
                "original_name": original_name,
                "outputs": outputs,
                "seconds": "0",
            },
        )
        try:
            input_file.unlink()
        except OSError:
            pass
        LOG.info("[%s] done -> %s", job_id, out_job)
    except Exception as e:
        LOG.exception("[%s] failed", job_id)
        put_status(
            job_id,
            {
                "state": "failed",
                "error": str(e),
                "original_name": original_name,
                "retrying": False,
            },
        )
    finally:
        with _lock:
            _processing.discard(job_id)


def worker_loop() -> None:
    _ffmpeg_path_prep()
    while True:
        try:
            if not INPUT_DIR.is_dir():
                time.sleep(2)
                continue
            for p in sorted(INPUT_DIR.iterdir(), key=lambda x: x.stat().st_mtime):
                if not p.is_file():
                    continue
                m = JOB_ID_RE.match(p.name)
                if not m:
                    continue
                job_id, _rest = m.group(1), m.group(2)
                st = get_status(job_id)
                if not st or st.get("state") != "queued":
                    continue
                original_name = st.get("original_name") or _rest
                process_job_file(p, job_id, original_name)
        except Exception:
            LOG.exception("worker tick")
        time.sleep(2)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.info("%s - %s", self.address_string(), fmt % args)

    def _cors(self) -> Dict[str, str]:
        return {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }

    def _send(self, code: int, body: bytes | None, ctype: str = "application/json") -> None:
        self.send_response(code)
        for k, v in self._cors().items():
            self.send_header(k, v)
        if body is not None:
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body is not None:
            self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self._send(204, None)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/status/"):
            job_id = path.split("/api/status/", 1)[-1].strip("/").split("/")[0]
            st = get_status(job_id)
            if not st:
                self.send_error(404)
                return
            raw = json.dumps(st).encode("utf-8")
            self._send(200, raw)
            return

        if path.startswith("/api/out/"):
            rest = path[len("/api/out/") :].strip("/")
            parts = rest.split("/")
            if len(parts) != 2:
                self.send_error(404)
                return
            job_id, fname = parts[0], parts[1]
            if fname not in ("vocals.wav", "no_vocals.wav"):
                self.send_error(404)
                return
            fp = OUTPUT_DIR / job_id / fname
            if not fp.is_file():
                self.send_error(404)
                return
            data = fp.read_bytes()
            self.send_response(200)
            for k, v in self._cors().items():
                self.send_header(k, v)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.rstrip("/") != "/api/submit":
            self.send_error(404)
            return

        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            raw = json.dumps({"error": "Expected multipart file upload"}).encode()
            self._send(400, raw)
            return

        try:
            length = int(self.headers["Content-Length"])
        except (KeyError, ValueError):
            self._send(400, json.dumps({"error": "Missing Content-Length"}).encode())
            return

        body = self.rfile.read(length)
        try:
            from io import BytesIO

            import cgi  # noqa: PLC0415 — stdlib multipart

            env = os.environ.copy()
            env["REQUEST_METHOD"] = "POST"
            env["CONTENT_TYPE"] = ctype
            env["CONTENT_LENGTH"] = str(len(body))
            fs = cgi.FieldStorage(fp=BytesIO(body), environ=env, keep_blank_values=True)
        except Exception as e:
            self._send(400, json.dumps({"error": f"Bad upload: {e}"}).encode())
            return

        up = fs["file"] if "file" in fs else None
        if not up or not getattr(up, "filename", None):
            self._send(400, json.dumps({"error": "Provide a file field"}).encode())
            return

        fname = safe_name(up.filename)
        job_id = job_id_for(fname)
        dest = INPUT_DIR / f"{job_id}_{fname}"

        try:
            with open(dest, "wb") as out:
                if hasattr(up, "file") and up.file:
                    shutil.copyfileobj(up.file, out)
                else:
                    out.write(up.value if isinstance(up.value, bytes) else up.value.encode())
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}).encode())
            return

        put_status(
            job_id,
            {"state": "queued", "progress": 0, "original_name": fname},
        )
        raw = json.dumps({"job_id": job_id}).encode()
        self._send(200, raw)


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    _ensure_dirs()
    _ffmpeg_path_prep()
    LOG.info("KARAOKE_LOCAL_ROOT=%s", ROOT)
    LOG.info("SEPARATOR=%s (set SEPARATOR=demucs for Demucs)", SEPARATOR)
    LOG.info("Serving %s — submit/status compatible with karaoke/index-local.html", PUBLIC_BASE)

    t = threading.Thread(target=worker_loop, name="karaoke-worker", daemon=True)
    t.start()

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
