import json, os, re, logging
import azure.functions as func
import requests
from azure.storage.blob import BlobServiceClient

# -------- External lyrics provider --------
LRCLIB_GET    = "https://lrclib.net/api/get"
LRCLIB_SEARCH = "https://lrclib.net/api/search"
REQ_HEADERS   = {"User-Agent": "kp-karaoke/1.0 (+https://www.krishposa.com)"}

# -------- Storage for user-uploaded lyrics (status blobs) --------
STORAGE_CONN     = os.environ.get("STORAGE_CONN", "")
STATUS_CONTAINER = os.environ.get("STATUS_CONTAINER", "karaoke-status")
BLOB = BlobServiceClient.from_connection_string(STORAGE_CONN) if STORAGE_CONN else None


def _cors():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization"
    }


def clean(s: str) -> str:
    if not s:
        return ""
    s = re.sub(
        r"\s*\((official|audio|video|lyrics?|hd|4k|remastered)[^)]*\)\s*$",
        "", s, flags=re.I
    )
    return re.sub(r"\s+", " ", s).strip()


def _int_or_none(v):
    try:
        if v is None or v == "":
            return None
        return int(float(v))
    except Exception:
        return None


def _ok(resp: dict, status: int = 200) -> func.HttpResponse:
    body = json.dumps(resp, ensure_ascii=False)
    return func.HttpResponse(
        body,
        status_code=status,
        mimetype="application/json; charset=utf-8",
        headers=_cors(),
    )


def _err(msg: str, status: int = 400) -> func.HttpResponse:
    return _ok({"error": msg}, status)


def _payload(track_title: str, track_artist: str, synced: bool, lrc: str, text: str, source: str):
    return {
        "found":  True,
        "title":  track_title or "",
        "artist": track_artist or "",
        "synced": bool(synced),
        "lrc":    lrc or "",
        "text":   text or "",
        "source": source
    }


def _to_payload_from_lrclib(track: dict, fallback_title: str, fallback_artist: str) -> dict:
    title  = track.get("trackName")  or fallback_title
    artist = track.get("artistName") or fallback_artist
    synced = bool(track.get("syncedLyrics"))
    return _payload(
        track_title=title,
        track_artist=artist,
        synced=synced,
        lrc=track.get("syncedLyrics") or "",
        text=track.get("plainLyrics") or "",
        source="lrclib"
    )


def _get_user_lyrics(job_id: str) -> dict | None:
    if not (BLOB and job_id):
        return None
    try:
        cc = BLOB.get_container_client(STATUS_CONTAINER)
        blob_name = f"{job_id}.json"
        data = cc.download_blob(blob_name).readall()
        doc = json.loads(data)

        lyr = doc.get("lyrics") or {}
        lrc  = (lyr.get("lrc")  or "").strip()
        text = (lyr.get("text") or "").strip()
        if not lrc and not text:
            return None

        meta_title  = (doc.get("title")  or "").strip()
        meta_artist = (doc.get("artist") or "").strip()

        return _payload(
            track_title = meta_title,
            track_artist= meta_artist,
            synced = bool(lrc),
            lrc    = lrc,
            text   = text,
            source = "user"
        )
    except Exception:
        return None


def _save_user_lyrics(job_id: str, title: str, artist: str, lrc: str, text: str) -> None:
    if not (BLOB and job_id):
        raise RuntimeError("STORAGE_CONN and job_id required for upload")

    cc = BLOB.get_container_client(STATUS_CONTAINER)
    blob_name = f"{job_id}.json"

    # Merge with any existing status JSON
    doc = {}
    try:
        data = cc.download_blob(blob_name).readall()
        doc = json.loads(data)
    except Exception:
        pass  # not found or invalid → start new

    doc["title"]  = title or doc.get("title", "")
    doc["artist"] = artist or doc.get("artist", "")
    doc["lyrics"] = {
        "lrc":  lrc or "",
        "text": text or ""
    }

    cc.upload_blob(blob_name, json.dumps(doc, ensure_ascii=False).encode("utf-8"), overwrite=True)


def main(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors())

    try:
        if req.method == "POST":
            body = req.get_json()
            job_id = (body.get("job_id") or "").strip()
            title  = clean(body.get("title", ""))
            artist = clean(body.get("artist", ""))
            lrc    = body.get("lrc", "")
            text   = body.get("text", "")

            if not job_id:
                return _err("job_id required", 400)
            if not (lrc or text):
                return _err("either 'lrc' or 'text' must be provided", 400)

            _save_user_lyrics(job_id, title, artist, lrc, text)
            return _ok({"uploaded": True, "job_id": job_id})

        # --------- GET flow (as before) ----------
        job_id = (req.params.get("job_id") or "").strip()
        title   = clean(req.params.get("title", ""))
        artist  = clean(req.params.get("artist", ""))
        album   = clean(req.params.get("album", ""))
        dur     = _int_or_none(req.params.get("duration"))

        if job_id:
            user_payload = _get_user_lyrics(job_id)
            if user_payload:
                if title and not user_payload.get("title"):
                    user_payload["title"] = title
                if artist and not user_payload.get("artist"):
                    user_payload["artist"] = artist
                return _ok(user_payload)

        if not title:
            return _err("title required (or provide job_id with uploaded lyrics)", 400)

        # Try LRCLIB /get
        get_params = {"track_name": title}
        if artist: get_params["artist_name"] = artist
        if dur:    get_params["duration"] = dur

        try:
            r = requests.get(LRCLIB_GET, params=get_params, headers=REQ_HEADERS, timeout=10)
            if r.status_code == 404:
                raise requests.HTTPError("not found", response=r)
            r.raise_for_status()
            return _ok(_to_payload_from_lrclib(r.json(), title, artist))
        except requests.HTTPError:
            pass

        # Fallback /search
        search_params = {"track_name": title, "limit": 5}
        if artist: search_params["artist_name"] = artist
        if album:  search_params["album_name"]  = album
        if dur:    search_params["duration"]    = dur

        rs = requests.get(LRCLIB_SEARCH, params=search_params, headers=REQ_HEADERS, timeout=10)
        if rs.status_code == 404:
            return _ok({"found": False})
        rs.raise_for_status()
        items = rs.json() or []
        if not isinstance(items, list) or not items:
            return _ok({"found": False})

        def norm(x): return (x or "").strip().lower()
        t_norm, a_norm = norm(title), norm(artist)
        best = None
        for it in items:
            if norm(it.get("trackName")) == t_norm and (not a_norm or norm(it.get("artistName")) == a_norm):
                best = it
                break
        if best is None:
            best = items[0]

        return _ok(_to_payload_from_lrclib(best, title, artist))

    except Exception as e:
        logging.exception("lyrics failed")
        return _err(str(e), 500)