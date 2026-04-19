#!/usr/bin/env python3
"""
Local karaoke pipeline without Azure: HTTP API + filesystem queue + optional split worker.

Layout under KARAOKE_LOCAL_ROOT (default: ~/.karaoke-local):
  input/   — uploads land here as {job_id}_{original_name} (queue)
  output/  — {job_id}/vocals.wav and {job_id}/no_vocals.wav
  status/  — {job_id}.json (same shape as cloud status blobs)
  lyrics/  — {job_id}.json (saved lyrics; same shape as cloud karaoke-lyrics blobs)

Implements the same routes the web UI expects:
  POST /api/submit     — multipart field "file" (combined mp3/wav/…)
  GET  /api/status/{job_id}
  GET  /api/out/{job_id}/vocals.wav|no_vocals.wav — audio for the player
  GET|POST /api/lyrics — load/save lyrics by job_id (JSON; compatible with karaoke-azure.js)
  GET  /api/list       — { "items": [ { job_id, title, updated, vocals_url, band_url } ] } (like cloud)

  Optional static (default on): GET / → redirect; GET /karaoke/*.html|*.htm|*.txt and GET /assets/* from the
  repo next to this file — so one ngrok tunnel to KARAOKE_LOCAL_PORT can serve both API and pages.
  Disable with KARAOKE_SERVE_REPO_STATIC=0.
  Narrow which repo files are served under assets/: KARAOKE_STATIC_ASSETS_SCOPE=karaoke — only karaoke*.js,
  header.js, footer.js under assets/js/ and styles.css, karaoke.css, dark-surface.css under assets/css/.
  (Ngrok itself cannot path-filter a tunnel; use this env or a local reverse proxy if you need that.)

Run:
  set SEPARATOR=spleeter   (default; matches repo requirements.txt — pip install -r requirements.txt)
  set SEPARATOR=demucs    (needs Demucs: pip install -r karaoke/requirements-demucs.txt — use its own venv)
  set DEMUCS_JOBS=1       (optional; Windows defaults to 1 — avoids many demucs -j2 spawn failures)
  Demucs speed: DEMUCS_MODEL=htdemucs (faster than default htdemucs_ft); install PyTorch with CUDA for GPU;
    optional DEMUCS_DEVICE=cuda, DEMUCS_EXTRA_ARGS e.g. --shifts 1; for fastest splits use SEPARATOR=spleeter.
  python karaoke/local_folder_queue.py

Then open karaoke/index-local.html (set KARAOKE_API_BASE to match, default http://127.0.0.1:8787).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import mimetypes
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Dict, Optional, Tuple

# --- config ---
LOG = logging.getLogger("karaoke-local")

# Repository root (parent of karaoke/) — used to serve a few static paths for “one ngrok → one port”.
REPO_ROOT = Path(__file__).resolve().parent.parent

ROOT = Path(os.environ.get("KARAOKE_LOCAL_ROOT", Path.home() / ".karaoke-local")).expanduser()
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
STATUS_DIR = ROOT / "status"
LYRICS_DIR = ROOT / "lyrics"

HOST = os.environ.get("KARAOKE_LOCAL_HOST", "127.0.0.1")
PORT = int(os.environ.get("KARAOKE_LOCAL_PORT", "8787"))
PUBLIC_BASE = os.environ.get("KARAOKE_LOCAL_PUBLIC_BASE", f"http://{HOST}:{PORT}").rstrip("/")

SEPARATOR = os.environ.get("SEPARATOR", "spleeter").lower().strip()
# htdemucs_ft = higher quality, slower. Use DEMUCS_MODEL=htdemucs for a noticeable speed-up (still good stems).
DEMUCS_MODEL = os.environ.get("DEMUCS_MODEL", "htdemucs_ft")
# Demucs multiprocessing often fails on Windows with -j 2; override with DEMUCS_JOBS.
# For a *single* track, -j mostly affects batching multiple files; model + CPU/GPU dominate runtime.
DEMUCS_JOBS = os.environ.get("DEMUCS_JOBS", "1" if platform.system() == "Windows" else "2")
# Optional: force device, e.g. cuda or cpu (Demucs defaults to cuda when PyTorch has CUDA).
DEMUCS_DEVICE = os.environ.get("DEMUCS_DEVICE", "").strip()
# Optional: extra CLI args (quoted segments), e.g. --segment 7  or  --shifts 1
DEMUCS_EXTRA_ARGS = os.environ.get("DEMUCS_EXTRA_ARGS", "").strip()


def _split_demucs_extra_args(extra: str):
    if not (extra or "").strip():
        return []
    # Windows paths in args are rare; posix=False handles cmd-style quoting on Windows.
    return shlex.split(extra, posix=os.name != "nt")

JOB_ID_RE = re.compile(r"^([a-f0-9]{16})_(.+)$", re.I)
JOB_ID_ONLY_RE = re.compile(r"^[a-f0-9]{16}$", re.I)

_processing: set[str] = set()
_lock = threading.Lock()


def _serve_repo_static_enabled() -> bool:
    v = (os.environ.get("KARAOKE_SERVE_REPO_STATIC") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _static_assets_scope() -> str:
    """all = any file under assets/; karaoke = only scripts/styles used by karaoke pages."""
    return (os.environ.get("KARAOKE_STATIC_ASSETS_SCOPE") or "all").strip().lower()


def _static_asset_repo_rel_allowed(rel: str) -> bool:
    if _static_assets_scope() in ("all", "*", ""):
        return True
    if _static_assets_scope() not in ("karaoke", "minimal"):
        return True
    r = rel.replace("\\", "/")
    rl = r.lower()
    if rl.startswith("assets/js/"):
        leaf = rl.rsplit("/", 1)[-1]
        return leaf.startswith("karaoke") or leaf in ("header.js", "footer.js")
    if rl.startswith("assets/css/"):
        leaf = rl.rsplit("/", 1)[-1]
        return leaf in ("styles.css", "karaoke.css", "dark-surface.css")
    return False


def _static_file_for_url(url_path: str) -> Optional[Path]:
    """Only karaoke/*.html|*.htm|*.txt and assets/* files under REPO_ROOT (no path traversal)."""
    if not _serve_repo_static_enabled():
        return None
    try:
        path = urllib.parse.unquote(urllib.parse.urlparse(url_path).path)
    except Exception:
        return None
    if not path or path.startswith("//") or ".." in path:
        return None
    rel = path.lstrip("/")
    if rel.startswith("karaoke/"):
        low = rel.lower()
        if not (low.endswith(".html") or low.endswith(".htm") or low.endswith(".txt")):
            return None
    elif rel.startswith("assets/"):
        if not _static_asset_repo_rel_allowed(rel):
            return None
    else:
        return None
    fp = (REPO_ROOT / rel).resolve()
    try:
        fp.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return None
    if not fp.is_file():
        return None
    return fp


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def resolve_separator() -> str:
    """
    Select an available separator.
    - Prefer configured SEPARATOR when installed.
    - Fallback to the other supported separator when available.
    - Raise a clear actionable error when none are installed.
    """
    requested = SEPARATOR
    if requested == "spleeter":
        if _module_available("spleeter"):
            return "spleeter"
        if _module_available("demucs"):
            LOG.warning("SEPARATOR=spleeter requested but module missing; falling back to demucs")
            return "demucs"
    elif requested == "demucs":
        if _module_available("demucs"):
            return "demucs"
        if _module_available("spleeter"):
            LOG.warning("SEPARATOR=demucs requested but module missing; falling back to spleeter")
            return "spleeter"
    else:
        LOG.warning("Unknown SEPARATOR=%r; trying available separator", requested)
        if _module_available("spleeter"):
            return "spleeter"
        if _module_available("demucs"):
            return "demucs"

    raise RuntimeError(
        "No supported separator module is installed. "
        "Install one of: `pip install -r requirements.txt` (spleeter) or "
        "`pip install -r karaoke/requirements-demucs.txt` (demucs), "
        "then restart karaoke/local_folder_queue.py."
    )


def _ensure_dirs() -> None:
    for d in (INPUT_DIR, OUTPUT_DIR, STATUS_DIR, LYRICS_DIR):
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


def lyrics_disk_path(job_id: str) -> Path:
    return LYRICS_DIR / f"{job_id}.json"


def get_saved_lyrics(job_id: str) -> Optional[Dict[str, Any]]:
    p = lyrics_disk_path(job_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_completed_jobs() -> list[Dict[str, Any]]:
    """Folders under output/ with both stems; title from status original_name when present."""
    items: list[Dict[str, Any]] = []
    if not OUTPUT_DIR.is_dir():
        return items
    for sub in OUTPUT_DIR.iterdir():
        if not sub.is_dir():
            continue
        job_id = sub.name
        if not JOB_ID_ONLY_RE.match(job_id):
            continue
        voc = sub / "vocals.wav"
        band = sub / "no_vocals.wav"
        band_alt = sub / "accompaniment.wav"
        if not voc.is_file():
            continue
        if not band.is_file() and not band_alt.is_file():
            continue
        st = get_status(job_id) or {}
        orig = (st.get("original_name") or "").strip()
        title = Path(orig).stem if orig else job_id
        try:
            mtime = max(voc.stat().st_mtime, band.stat().st_mtime)
            updated = (
                datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            )
        except OSError:
            updated = None
        items.append(
            {
                "job_id": job_id,
                "title": title,
                "updated": updated,
                "vocals_url": f"{PUBLIC_BASE}/api/out/{job_id}/vocals.wav",
                "band_url": f"{PUBLIC_BASE}/api/out/{job_id}/no_vocals.wav",
            }
        )
    items.sort(key=lambda x: x.get("updated") or "", reverse=True)
    return items


def _lyrics_clean(s: str) -> str:
    if not s:
        return ""
    s = re.sub(
        r"\s*\((official|audio|video|lyrics?|hd|4k|remastered)[^)]*\)\s*$",
        "",
        s,
        flags=re.I,
    ).strip()
    return re.sub(r"\s+", " ", s)


def run_cmd(cmd: list[str], job_id: str, desc: str) -> subprocess.CompletedProcess[str]:
    LOG.info("[%s] starting %s: %s", job_id, desc, " ".join(cmd))
    try:
        return subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "").strip()
        out = (e.stdout or "").strip()
        if err:
            LOG.error("[%s] %s stderr (exit %s):\n%s", job_id, desc, e.returncode, err[-12000:])
        if out:
            LOG.error("[%s] %s stdout:\n%s", job_id, desc, out[-6000:])
        tail = (err or out or "(no output)")[-2500:]
        raise RuntimeError(f"{desc} failed (exit {e.returncode}): {tail}") from e


def _drain_text_stream(stream: Any, chunks: list[str]) -> None:
    """Read a text PIPE to EOF so the child process cannot deadlock on a full buffer."""
    if stream is None:
        return
    try:
        for line in iter(stream.readline, ""):
            chunks.append(line)
    except Exception:
        pass
    try:
        stream.close()
    except Exception:
        pass


def run_cmd_with_progress(
    cmd: list[str],
    job_id: str,
    desc: str,
    original_name: str,
    prog_lo: int,
    prog_hi: int,
) -> subprocess.CompletedProcess[str]:
    """
    Run a long subprocess while periodically writing status progress (prog_lo..prog_hi)
    so the web UI poll sees movement. Demucs/Spleeter do not expose a native % API here.

    Stdout/stderr are drained in background threads (not communicate()) so tqdm-heavy
    Demucs logs cannot fill the PIPE buffer and freeze the separator on Windows.
    """
    LOG.info("[%s] starting %s: %s", job_id, desc, " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    cur = [max(0, min(99, prog_lo))]
    stop_hb = threading.Event()
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    def heartbeat() -> None:
        step = max(1, (prog_hi - prog_lo) // 28)
        while not stop_hb.is_set():
            if proc.poll() is not None:
                return
            if stop_hb.wait(2.0):
                return
            if proc.poll() is not None:
                return
            nxt = min(prog_hi - 1, cur[0] + step)
            if nxt <= cur[0]:
                nxt = min(prog_hi - 1, cur[0] + 1)
            cur[0] = nxt
            put_status(
                job_id,
                {
                    "state": "running",
                    "progress": cur[0],
                    "original_name": original_name,
                    "attempt": 0,
                },
            )

    t_out = threading.Thread(
        target=_drain_text_stream,
        args=(proc.stdout, stdout_chunks),
        name=f"karaoke-out-{desc}",
        daemon=True,
    )
    t_err = threading.Thread(
        target=_drain_text_stream,
        args=(proc.stderr, stderr_chunks),
        name=f"karaoke-err-{desc}",
        daemon=True,
    )
    t_out.start()
    t_err.start()
    hb_thread = threading.Thread(target=heartbeat, name=f"karaoke-hb-{desc}", daemon=True)
    hb_thread.start()
    try:
        rc = proc.wait()
    finally:
        stop_hb.set()
        hb_thread.join(timeout=3.0)
    t_out.join(timeout=600)
    t_err.join(timeout=600)
    out_b = "".join(stdout_chunks)
    err_b = "".join(stderr_chunks)

    if proc.returncode != 0:
        err = (err_b or "").strip()
        out = (out_b or "").strip()
        if err:
            LOG.error("[%s] %s stderr (exit %s):\n%s", job_id, desc, proc.returncode, err[-12000:])
        if out:
            LOG.error("[%s] %s stdout:\n%s", job_id, desc, out[-6000:])
        tail = (err or out or "(no output)")[-2500:]
        raise RuntimeError(f"{desc} failed (exit {proc.returncode}): {tail}")

    return subprocess.CompletedProcess(cmd, proc.returncode, out_b, err_b)


def run_spleeter(inp: Path, work_base: Path, job_id: str, original_name: str) -> Path:
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
    run_cmd_with_progress(cmd, job_id, "spleeter", original_name, prog_lo=38, prog_hi=88)
    return out_dir


def find_spleeter_vocals_band(base: Path, basename: str, job_id: str) -> Tuple[Path, Path]:
    p = base / basename
    voc, acc = p / "vocals.wav", p / "accompaniment.wav"
    if voc.is_file() and acc.is_file():
        return voc, acc
    for root, _, files in os.walk(base):
        if "vocals.wav" in files and "accompaniment.wav" in files:
            return Path(root) / "vocals.wav", Path(root) / "accompaniment.wav"
    hint = ""
    if base.is_dir():
        try:
            hint = " under " + str(base) + ": " + ", ".join(x.name for x in base.iterdir())[:400]
        except OSError:
            pass
    raise RuntimeError(f"Spleeter outputs not found (basename={basename!r}).{hint}")


def run_demucs(inp: Path, work_base: Path, job_id: str, original_name: str) -> Path:
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
        DEMUCS_JOBS,
    ]
    if DEMUCS_DEVICE:
        cmd.extend(["-d", DEMUCS_DEVICE])
    cmd.extend(_split_demucs_extra_args(DEMUCS_EXTRA_ARGS))
    cmd.extend([str(inp), "-o", str(work_base)])
    run_cmd_with_progress(cmd, job_id, "demucs", original_name, prog_lo=38, prog_hi=88)
    return work_base


def find_demucs_vocals_band(base: Path, model: str, basename: str, job_id: str) -> Tuple[Path, Path]:
    """Locate stems; Demucs may use a slightly different folder name than pathlib stem."""
    model_dir = base / model

    def try_pair(folder: Path) -> Optional[Tuple[Path, Path]]:
        voc, band = folder / "vocals.wav", folder / "no_vocals.wav"
        if voc.is_file() and band.is_file():
            return voc, band
        return None

    for folder in (model_dir / basename,):
        hit = try_pair(folder)
        if hit:
            return hit

    if model_dir.is_dir():
        for sub in sorted(model_dir.iterdir(), key=lambda x: x.name.lower()):
            if not sub.is_dir():
                continue
            hit = try_pair(sub)
            if hit:
                LOG.info("[%s] demucs outputs in %s (basename hint was %r)", job_id, sub, basename)
                return hit

    for root, _, files in os.walk(base):
        if "vocals.wav" in files and "no_vocals.wav" in files:
            return Path(root) / "vocals.wav", Path(root) / "no_vocals.wav"

    sub_hint = ""
    if model_dir.is_dir():
        sub_hint = " model_subdirs=" + ",".join(sorted(x.name for x in model_dir.iterdir() if x.is_dir()))[:500]
    raise RuntimeError(
        f"Demucs outputs not found (model={model!r}, basename={basename!r}, base={base}).{sub_hint}"
    )


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
            basename = work_audio.stem
            put_status(job_id, {"state": "running", "progress": 35, "original_name": original_name})
            separator = resolve_separator()
            LOG.info("[%s] separator=%s basename=%r work_audio=%s", job_id, separator, basename, work_audio)

            if separator == "demucs":
                out_base = run_demucs(work_audio, tdp / "demucs_out", job_id, original_name)
                LOG.info("[%s] demucs subprocess finished, scanning outputs under %s", job_id, out_base)
                put_status(job_id, {"state": "running", "progress": 90, "original_name": original_name})
                voc, band = find_demucs_vocals_band(out_base, DEMUCS_MODEL, basename, job_id)
            else:
                sp_out = run_spleeter(work_audio, tdp, job_id, original_name)
                put_status(job_id, {"state": "running", "progress": 90, "original_name": original_name})
                voc, band = find_spleeter_vocals_band(sp_out, basename, job_id)

            out_job = OUTPUT_DIR / job_id
            out_job.mkdir(parents=True, exist_ok=True)
            put_status(job_id, {"state": "running", "progress": 94, "original_name": original_name})
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
            "Access-Control-Allow-Headers": "Content-Type, Authorization, ngrok-skip-browser-warning",
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

    def _handle_get_lyrics(self, parsed: urllib.parse.ParseResult) -> None:
        qs = urllib.parse.parse_qs(parsed.query)

        def qp(name: str) -> str:
            vals = qs.get(name)
            if not vals or not vals[0]:
                return ""
            return (vals[0] or "").strip()

        job_id = qp("job_id")
        if not job_id or not JOB_ID_ONLY_RE.match(job_id):
            self._send(200, json.dumps({"found": False}).encode("utf-8"))
            return
        saved = get_saved_lyrics(job_id)
        if saved:
            out = {
                "found": True,
                "title": saved.get("title") or "",
                "artist": saved.get("artist") or "",
                "synced": bool(saved.get("synced")),
                "lrc": saved.get("lrc") or "",
                "text": saved.get("text") or "",
                "source": "by-job",
            }
            self._send(200, json.dumps(out, ensure_ascii=False).encode("utf-8"))
            return
        self._send(200, json.dumps({"found": False}).encode("utf-8"))

    def _maybe_serve_repo_static(self) -> bool:
        """Serve a small slice of the repo for one public URL (ngrok) → queue port only."""
        parsed = urllib.parse.urlparse(self.path)
        p = parsed.path or ""
        if p in ("/", ""):
            if not _serve_repo_static_enabled():
                return False
            self.send_response(302)
            self.send_header("Location", "/karaoke/player-folder-local-root.html")
            for k, v in self._cors().items():
                self.send_header(k, v)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True
        fp = _static_file_for_url(self.path)
        if not fp:
            return False
        try:
            data = fp.read_bytes()
        except OSError:
            self.send_error(500)
            return True
        ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
        self.send_response(200)
        for k, v in self._cors().items():
            self.send_header(k, v)
        if ctype.startswith("text/"):
            self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        return True

    def _handle_post_lyrics(self) -> None:
        ctype = (self.headers.get("Content-Type") or "").lower()
        if "application/json" not in ctype and "json" not in ctype:
            self._send(400, json.dumps({"error": "Expected application/json"}).encode())
            return
        try:
            length = int(self.headers["Content-Length"])
        except (KeyError, ValueError):
            self._send(400, json.dumps({"error": "Missing Content-Length"}).encode())
            return
        raw_b = self.rfile.read(length)
        try:
            body = json.loads(raw_b.decode("utf-8"))
        except Exception as e:
            self._send(400, json.dumps({"error": f"Invalid JSON: {e}"}).encode())
            return
        job_id = (body.get("job_id") or "").strip()
        if not job_id or not JOB_ID_ONLY_RE.match(job_id):
            self._send(400, json.dumps({"error": "job_id required"}).encode())
            return
        text = (body.get("text") or "").strip()
        lrc = (body.get("lrc") or "").strip()
        synced = bool(body.get("synced", bool(lrc)))
        payload = {
            "job_id": job_id,
            "title": _lyrics_clean(body.get("title") or ""),
            "artist": _lyrics_clean(body.get("artist") or ""),
            "synced": synced,
            "lrc": lrc if synced else "",
            "text": "" if synced else text,
            "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        }
        lyrics_disk_path(job_id).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self._send(200, json.dumps({"ok": True, "saved": f"by-job/{job_id}.json"}).encode())

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path_norm = parsed.path.rstrip("/")

        if path_norm == "/api/lyrics":
            self._handle_get_lyrics(parsed)
            return
        if path_norm == "/api/list":
            items = list_completed_jobs()
            n_sub = sum(1 for _ in OUTPUT_DIR.iterdir()) if OUTPUT_DIR.is_dir() else 0
            LOG.info(
                "GET /api/list -> %d completed job(s) (KARAOKE_LOCAL_ROOT=%s output/ sub-entries=%s)",
                len(items),
                ROOT,
                n_sub,
            )
            raw = json.dumps({"items": items}, ensure_ascii=False).encode("utf-8")
            self._send(200, raw)
            return

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
            if fname == "no_vocals.wav" and not fp.is_file():
                alt = OUTPUT_DIR / job_id / "accompaniment.wav"
                if alt.is_file():
                    fp = alt
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

        if self._maybe_serve_repo_static():
            return

        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path.rstrip("/")
        if route == "/api/lyrics":
            self._handle_post_lyrics()
            return
        if route != "/api/submit":
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

        # FieldStorage forbids `if not up` (__bool__ raises TypeError); test explicitly.
        if "file" not in fs:
            self._send(400, json.dumps({"error": "Provide a file field"}).encode())
            return
        up = fs["file"]
        raw_fn = getattr(up, "filename", None)
        if not raw_fn:
            self._send(400, json.dumps({"error": "Provide a file field"}).encode())
            return

        fname = safe_name(raw_fn)
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
    LOG.info("SEPARATOR=%s", SEPARATOR)
    if SEPARATOR == "demucs":
        LOG.info("DEMUCS_MODEL=%s DEMUCS_JOBS=%s", DEMUCS_MODEL, DEMUCS_JOBS)
    try:
        selected = resolve_separator()
        LOG.info("Resolved separator=%s", selected)
    except Exception as e:
        LOG.error("Separator check failed: %s", e)
    LOG.info("Serving %s — submit/status/lyrics compatible with karaoke/index-local.html", PUBLIC_BASE)
    if _serve_repo_static_enabled():
        LOG.info(
            "Repo static files enabled — e.g. %s/karaoke/player-folder-local-root.html (single ngrok → this port). "
            "Set KARAOKE_SERVE_REPO_STATIC=0 to disable. Static under assets/: scope=%s (set KARAOKE_STATIC_ASSETS_SCOPE=karaoke to limit).",
            PUBLIC_BASE,
            _static_assets_scope(),
        )

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
