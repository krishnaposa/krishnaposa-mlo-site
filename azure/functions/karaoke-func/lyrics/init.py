# init.py  — Azure Function: /api/lyrics
# - GET:  first return user-uploaded lyrics from Blob; otherwise query LRCLIB
# - POST: save uploaded lyrics JSON (UTF-8) to Blob
# - OPTIONS: CORS preflight

import json, os, re, logging, datetime
import azure.functions as func
import requests
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError

# ---------- External source (fallback) ----------
LRCLIB_GET    = "https://lrclib.net/api/get"
LRCLIB_SEARCH = "https://lrclib.net/api/search"
REQ_HEADERS   = {"User-Agent": "kp-karaoke/1.0 (+https://www.krishposa.com)"}

# ---------- Storage ----------
STORAGE_CONN      = os.getenv("AzureWebJobsStorage") or os.getenv("STORAGE_CONN")
LYRICS_CONTAINER  = os.getenv("LYRICS_CONTAINER", "karaoke-lyrics")

BLOB = BlobServiceClient.from_connection_string(STORAGE_CONN) if STORAGE_CONN else None
if BLOB:
    try:
        BLOB.create_container(LYRICS_CONTAINER)
    except Exception:
        pass

# ---------- CORS ----------
def _cors():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization"
    }

def _ok(payload: dict, status: int = 200) -> func.HttpResponse:
    body = json.dumps(payload, ensure_ascii=False)
    return func.HttpResponse(body, status_code=status,
                             mimetype="application/json; charset=utf-8",
                             headers=_cors())

def _err(msg: str, status: int = 400) -> func.HttpResponse:
    return _ok({"error": msg}, status)

# ---------- Helpers ----------
_slug_re = re.compile(r"[^a-z0-9]+")
def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = _slug_re.sub("-", s).strip("-")
    return re.sub(r"-{2,}", "-", s)[:120] or "untitled"

def make_blob_key(title: str, artist: str) -> str:
    # We keep a simple, stable key scheme. You can change prefixing if desired.
    return f"{slugify(title)}__{slugify(artist or 'unknown')}.json"

def clean(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\s*\((official|audio|video|lyrics?|hd|4k|remastered)[^)]*\)\s*$",
               "", s, flags=re.I).strip()
    s = re.sub(r"\s+", " ", s)
    return s

def _int_or_none(v):
    try:
        if v is None or v == "":
            return None
        return int(float(v))
    except Exception:
        return None

def _to_payload(track: dict, fallback_title: str, fallback_artist: str, source: str) -> dict:
    title  = track.get("trackName")  or fallback_title
    artist = track.get("artistName") or fallback_artist
    synced = bool(track.get("syncedLyrics"))
    return {
        "found":  True,
        "source": source,   # "user" or "lrclib"
        "title":  title,
        "artist": artist,
        "synced": synced,
        "lrc":    track.get("syncedLyrics") or "",
        "text":   track.get("plainLyrics")  or ""
    }

def fetch_user_lyrics(title: str, artist: str):
    """Return JSON dict from Blob if present, else None."""
    if not BLOB:
        logging.warning("No STORAGE connection; cannot read user lyrics.")
        return None
    key = make_blob_key(title, artist)
    logging.info("Checking user-lyrics blob: container=%s key=%s", LYRICS_CONTAINER, key)
    try:
        data = BLOB.get_container_client(LYRICS_CONTAINER).download_blob(key).readall()
        doc = json.loads(data.decode("utf-8"))
        # Normalize to the same payload shape we return from LRCLIB
        payload = {
            "found":  True,
            "source": "user",
            "title":  doc.get("title")  or title,
            "artist": doc.get("artist") or artist,
            "synced": bool(doc.get("synced")),
            "lrc":    doc.get("lrc")  or "",
            "text":   doc.get("text") or ""
        }
        logging.info("User lyrics FOUND for %s - %s", title, artist)
        return payload
    except ResourceNotFoundError:
        logging.info("User lyrics NOT found for %s - %s", title, artist)
        return None

def save_user_lyrics(doc: dict):
    """Persist JSON to Blob (UTF-8) under normalized key."""
    if not BLOB:
        raise RuntimeError("Storage not configured (AzureWebJobsStorage)")
    title  = doc.get("title")  or ""
    artist = doc.get("artist") or ""
    key = make_blob_key(title, artist)
    body = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    meta = {"uploaded": "true"}
    cc = BLOB.get_container_client(LYRICS_CONTAINER)
    cc.upload_blob(key, body, overwrite=True, metadata=meta)
    logging.info("Saved user lyrics → %s/%s", LYRICS_CONTAINER, key)
    return key

# ---------- Main ----------
def main(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors())

    try:
        if req.method == "POST":
            # Expected JSON: { title, artist?, synced?, lrc? or text?, job_id? }
            try:
                body = req.get_json()
            except Exception as e:
                logging.error("POST invalid JSON: %s", e)
                return _err("invalid JSON", 400)

            logging.info("POST /lyrics body: %s", body)
            title  = clean(body.get("title", ""))
            artist = clean(body.get("artist", ""))
            if not title:
                return _err("title required", 400)

            lrc  = body.get("lrc")
            text = body.get("text")
            if not (lrc or text):
                return _err("either 'lrc' or 'text' required", 400)

            synced = bool(body.get("synced")) or bool(lrc)
            doc = {
                "title":   title,
                "artist":  artist,
                "synced":  synced,
                "lrc":     lrc or "",
                "text":    text or "",
                "job_id":  body.get("job_id") or "",
                "uploaded_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
            }
            key = save_user_lyrics(doc)
            return _ok({"ok": True, "saved_as": key})

        # ---------- GET ----------
        # Query: ?title=...&artist=...&duration=...
        title   = clean(req.params.get("title", ""))
        artist  = clean(req.params.get("artist", ""))
        album   = clean(req.params.get("album", ""))
        dur     = _int_or_none(req.params.get("duration"))

        logging.info("GET /lyrics title='%s' artist='%s' dur=%s", title, artist, dur)

        if not title:
            return _err("title required", 400)

        # 1) User-uploaded first
        user_hit = fetch_user_lyrics(title, artist)
        if user_hit:
            return _ok(user_hit)

        # 2) LRCLIB precise
        get_params = {"track_name": title}
        if artist: get_params["artist_name"] = artist
        if dur:    get_params["duration"]   = dur

        try:
            r = requests.get(LRCLIB_GET, params=get_params, headers=REQ_HEADERS, timeout=10)
            logging.info("LRCLIB /get status=%s url=%s", r.status_code, r.url)
            if r.status_code == 404:
                raise requests.HTTPError("not found", response=r)
            r.raise_for_status()
            data = r.json()
            return _ok(_to_payload(data, title, artist, source="lrclib"))
        except requests.HTTPError:
            logging.info("LRCLIB /get miss → trying /search")

        # 3) LRCLIB fallback /search (pick best)
        search_params = {"track_name": title, "limit": 5}
        if artist: search_params["artist_name"] = artist
        if album:  search_params["album_name"]  = album
        if dur:    search_params["duration"]    = dur

        rs = requests.get(LRCLIB_SEARCH, params=search_params, headers=REQ_HEADERS, timeout=10)
        logging.info("LRCLIB /search status=%s url=%s", rs.status_code, rs.url)
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

        return _ok(_to_payload(best, title, artist, source="lrclib"))

    except Exception as e:
        logging.exception("lyrics failed")
        return _err(str(e), 500)