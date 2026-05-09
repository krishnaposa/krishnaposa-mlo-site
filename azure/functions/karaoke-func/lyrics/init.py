import json, os, re, logging, datetime
import azure.functions as func
from azure.storage.blob import BlobServiceClient
import requests

# ==================== CONFIG ====================
STORAGE_CONN       = os.environ.get("STORAGE_CONN") or os.environ.get("AzureWebJobsStorage")
LYRICS_CONTAINER   = os.environ.get("LYRICS_CONTAINER", "karaoke-lyrics")
LRCLIB_GET         = "https://lrclib.net/api/get"
LRCLIB_SEARCH      = "https://lrclib.net/api/search"
REQ_HEADERS        = {"User-Agent": "kp-karaoke/1.0 (+https://www.krishposa.com)"}

_blob = None
if STORAGE_CONN:
    _blob = BlobServiceClient.from_connection_string(STORAGE_CONN)
    try:
        _blob.create_container(LYRICS_CONTAINER)
    except Exception:
        pass  # exists

# ==================== HELPERS ====================
def _cors():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
    }

def _ok(payload: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload, ensure_ascii=False),
        status_code=status,
        mimetype="application/json; charset=utf-8",
        headers=_cors(),
    )

def _err(msg: str, status: int = 400) -> func.HttpResponse:
    return _ok({"error": msg}, status)

def _int_or_none(v):
    try:
        if v is None or v == "":
            return None
        return int(float(v))
    except Exception:
        return None

def clean(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\s*\((official|audio|video|lyrics?|hd|4k|remastered)[^)]*\)\s*$",
               "", s, flags=re.I).strip()
    return re.sub(r"\s+", " ", s)

def _job_blob_path(job_id: str) -> str:
    return f"by-job/{job_id}.json"

def _download_job_lyrics(job_id: str) -> dict | None:
    if not _blob:
        return None
    cc = _blob.get_container_client(LYRICS_CONTAINER)
    key = _job_blob_path(job_id)
    try:
        raw = cc.download_blob(key).readall()
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None

def _save_job_lyrics(job_id: str, data: dict) -> str:
    if not _blob:
        raise RuntimeError("No storage configured")
    cc = _blob.get_container_client(LYRICS_CONTAINER)
    key = _job_blob_path(job_id)
    cc.upload_blob(name=key, data=json.dumps(data, ensure_ascii=False).encode("utf-8"), overwrite=True)
    return key

def _to_payload_from_lrclib(track: dict, fallback_title: str, fallback_artist: str) -> dict:
    title  = track.get("trackName")  or fallback_title
    artist = track.get("artistName") or fallback_artist
    return {
        "found":  True,
        "title":  title,
        "artist": artist,
        "synced": bool(track.get("syncedLyrics")),
        "lrc":    track.get("syncedLyrics") or "",
        "text":   track.get("plainLyrics") or ""
    }

def _lrclib_lookup(title: str, artist: str, dur: int | None) -> dict | None:
    # Try precise GET
    if title:
        params = {"track_name": title}
        if artist: params["artist_name"] = artist
        if dur:    params["duration"] = dur
        try:
            r = requests.get(LRCLIB_GET, params=params, headers=REQ_HEADERS, timeout=10)
            if r.status_code != 404:
                r.raise_for_status()
                return _to_payload_from_lrclib(r.json(), title, artist)
        except Exception:
            pass
    # Fallback SEARCH
    try:
        params = {"track_name": title, "limit": 5}
        if artist: params["artist_name"] = artist
        if dur:    params["duration"] = dur
        rs = requests.get(LRCLIB_SEARCH, params=params, headers=REQ_HEADERS, timeout=10)
        if rs.status_code == 404:
            return None
        rs.raise_for_status()
        items = rs.json() or []
        if not isinstance(items, list) or not items:
            return None

        def norm(x): return (x or "").strip().lower()
        t_norm, a_norm = norm(title), norm(artist)
        best = None
        for it in items:
            if norm(it.get("trackName")) == t_norm and (not a_norm or norm(it.get("artistName")) == a_norm):
                best = it; break
        if best is None: best = items[0]
        return _to_payload_from_lrclib(best, title, artist)
    except Exception:
        return None

# ==================== MAIN ====================
def main(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors())

    try:
        if req.method == "POST":
            body = req.get_json()
            job_id = (body.get("job_id") or "").strip()
            if not job_id:
                return _err("job_id required", 400)

            # Accept either plain text or lrc; 'synced' is optional
            text = (body.get("text") or "").strip()
            lrc  = (body.get("lrc") or "").strip()
            synced = bool(body.get("synced", bool(lrc)))

            payload = {
                "job_id": job_id,
                "title":  clean(body.get("title") or ""),
                "artist": clean(body.get("artist") or ""),
                "synced": synced,
                "lrc":    lrc if synced else "",
                "text":   "" if synced else text,
                "saved_at": datetime.datetime.utcnow().isoformat() + "Z",
            }
            key = _save_job_lyrics(job_id, payload)
            return _ok({"ok": True, "saved": key})

        # GET
        job_id  = (req.params.get("job_id") or "").strip()
        title   = clean(req.params.get("title", ""))
        artist  = clean(req.params.get("artist", ""))
        dur     = _int_or_none(req.params.get("duration"))

        # 1) Try saved-by-job first (if provided)
        if job_id:
            saved = _download_job_lyrics(job_id)
            if saved:
                return _ok({
                    "found": True,
                    "title":  saved.get("title",""),
                    "artist": saved.get("artist",""),
                    "synced": bool(saved.get("synced")),
                    "lrc":    saved.get("lrc",""),
                    "text":   saved.get("text",""),
                    "source": "by-job"
                })

        # 2) Optional: fall back to LRCLIB if we have title/artist/duration
        if title:
            lib = _lrclib_lookup(title, artist, dur)
            if lib:
                lib["source"] = "lrclib"
                return _ok(lib)

        # Nothing found
        return _ok({"found": False})

    except Exception as e:
        logging.exception("lyrics failed")
        return _err(str(e), 500)