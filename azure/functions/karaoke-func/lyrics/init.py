# init.py — /api/lyrics
# GET: user-uploaded lyrics (Blob) → LRCLIB fallback
# POST: upsert by job_id (+ lrc or text), inferring title/artist from status blob

import json, os, re, logging, datetime
import azure.functions as func
import requests
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError

LRCLIB_GET    = "https://lrclib.net/api/get"
LRCLIB_SEARCH = "https://lrclib.net/api/search"
REQ_HEADERS   = {"User-Agent": "kp-karaoke/1.0 (+https://www.krishposa.com)"}

# Storage + containers
STORAGE_CONN      = os.getenv("AzureWebJobsStorage") or os.getenv("STORAGE_CONN")
LYRICS_CONTAINER  = os.getenv("LYRICS_CONTAINER", "karaoke-lyrics")
STATUS_CONTAINER  = os.getenv("STATUS_CONTAINER", "karaoke-status")

BLOB = BlobServiceClient.from_connection_string(STORAGE_CONN) if STORAGE_CONN else None
if BLOB:
    for c in (LYRICS_CONTAINER, STATUS_CONTAINER):
        try: BLOB.create_container(c)
        except Exception: pass

# ---------- CORS / helpers ----------
def _cors():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization"
    }

def _ok(payload: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(payload, ensure_ascii=False),
                             status_code=status,
                             mimetype="application/json; charset=utf-8",
                             headers=_cors())

def _err(msg: str, status: int = 400) -> func.HttpResponse:
    return _ok({"error": msg}, status)

_slug_re = re.compile(r"[^a-z0-9]+")
def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = _slug_re.sub("-", s).strip("-")
    return re.sub(r"-{2,}", "-", s)[:120] or "untitled"

def clean_decorations(s: str) -> str:
    if not s: return ""
    s = re.sub(r"\s*\((official|audio|video|lyrics?|hd|4k|remastered)[^)]*\)\s*$", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _int_or_none(v):
    try:
        if v is None or v == "": return None
        return int(float(v))
    except Exception:
        return None

def canonical_key(title: str, artist: str) -> str:
    return f"{slugify(title)}__{slugify(artist or 'unknown')}.json"

def job_alias_key(job_id: str) -> str:
    return f"by-job/{slugify(job_id)}.json"

def _to_payload(track: dict, fallback_title: str, fallback_artist: str, source: str) -> dict:
    title  = track.get("trackName")  or fallback_title
    artist = track.get("artistName") or fallback_artist
    synced = bool(track.get("syncedLyrics"))
    return {
        "found":  True,
        "source": source,
        "title":  title,
        "artist": artist,
        "synced": synced,
        "lrc":    track.get("syncedLyrics") or "",
        "text":   track.get("plainLyrics")  or ""
    }

# ---------- Blob helpers ----------
def fetch_user_lyrics(title: str, artist: str):
    if not BLOB: return None
    key = canonical_key(title, artist)
    logging.info("lookup user lyrics: %s/%s", LYRICS_CONTAINER, key)
    try:
        raw = BLOB.get_container_client(LYRICS_CONTAINER).download_blob(key).readall()
        doc = json.loads(raw.decode("utf-8"))
        return {
            "found":  True,
            "source": "user",
            "title":  doc.get("title")  or title,
            "artist": doc.get("artist") or artist,
            "synced": bool(doc.get("synced")),
            "lrc":    doc.get("lrc")  or "",
            "text":   doc.get("text") or ""
        }
    except ResourceNotFoundError:
        return None

def read_status(job_id: str) -> dict | None:
    if not BLOB: return None
    key = f"{slugify(job_id)}.json"
    try:
        raw = BLOB.get_container_client(STATUS_CONTAINER).download_blob(key).readall()
        return json.loads(raw.decode("utf-8"))
    except ResourceNotFoundError:
        logging.info("status not found for job_id=%s", job_id)
        return None

def save_lyrics_docs(doc: dict, title: str, artist: str, job_id: str):
    if not BLOB:
        raise RuntimeError("Storage not configured")
    body = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    cc   = BLOB.get_container_client(LYRICS_CONTAINER)

    main_key = canonical_key(title, artist)
    cc.upload_blob(main_key, body, overwrite=True, metadata={"uploaded":"true"})
    # also a job alias for future updates by job_id
    alias_key = job_alias_key(job_id)
    cc.upload_blob(alias_key, body, overwrite=True, metadata={"alias":"true","main":main_key})
    return main_key, alias_key

# ---------- Function entry ----------
def main(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors())

    try:
        if req.method == "POST":
            try:
                body = req.get_json()
            except Exception as e:
                logging.error("POST invalid JSON: %s", e)
                return _err("invalid JSON", 400)

            job_id = (body.get("job_id") or "").strip()
            lrc    = body.get("lrc")
            text   = body.get("text")
            # allow optional overrides, but not required:
            override_title  = body.get("title")
            override_artist = body.get("artist")

            if not job_id:
                return _err("job_id required", 400)
            if not (lrc or text):
                return _err("either 'lrc' or 'text' required", 400)

            status = read_status(job_id) or {}
            # infer title/artist from status
            orig = status.get("original_name") or status.get("title") or job_id
            # strip path & extension
            base = orig.split("/")[-1]
            base = re.sub(r"\.(wav|mp3|m4a|flac|aac)$", "", base, flags=re.I)
            title  = clean_decorations(override_title or base)
            artist = clean_decorations(override_artist or status.get("artist",""))

            synced = bool(body.get("synced")) or bool(lrc)
            doc = {
                "title":   title,
                "artist":  artist,
                "synced":  synced,
                "lrc":     lrc or "",
                "text":    text or "",
                "job_id":  job_id,
                "uploaded_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
            }

            main_key, alias_key = save_lyrics_docs(doc, title, artist, job_id)
            logging.info("saved lyrics main=%s alias=%s", main_key, alias_key)
            return _ok({"ok": True, "saved_as": main_key, "alias": alias_key, "title": title, "artist": artist})

        # ---------- GET ----------
        title   = clean_decorations(req.params.get("title", ""))
        artist  = clean_decorations(req.params.get("artist", ""))
        album   = clean_decorations(req.params.get("album", ""))
        dur     = _int_or_none(req.params.get("duration"))

        if not title:
            return _err("title required", 400)

        # 1) user upload first
        hit = fetch_user_lyrics(title, artist)
        if hit:
            return _ok(hit)

        # 2) LRCLIB /get
        get_params = {"track_name": title}
        if artist: get_params["artist_name"] = artist
        if dur:    get_params["duration"]    = dur
        try:
            r = requests.get(LRCLIB_GET, params=get_params, headers=REQ_HEADERS, timeout=10)
            if r.status_code == 404:
                raise requests.HTTPError("not found", response=r)
            r.raise_for_status()
            data = r.json()
            return _ok(_to_payload(data, title, artist, source="lrclib"))
        except requests.HTTPError:
            pass

        # 3) LRCLIB /search
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
                best = it; break
        if best is None: best = items[0]
        return _ok(_to_payload(best, title, artist, source="lrclib"))

    except Exception as e:
        logging.exception("lyrics failed")
        return _err(str(e), 500)