import json, os, re, logging
import azure.functions as func
import requests

LRCLIB_GET    = "https://lrclib.net/api/get"
LRCLIB_SEARCH = "https://lrclib.net/api/search"

# A simple UA helps some endpoints that are strict about clients
REQ_HEADERS = {"User-Agent": "kp-karaoke/1.0 (+https://www.krishposa.com)"}

def _cors():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization"
    }

def clean(s: str) -> str:
    if not s:
        return ""
    # strip common decorations: "(Official Video)" etc.
    s = re.sub(r"\s*\((official|audio|video|lyrics?|hd|4k|remastered)[^)]*\)\s*$",
               "", s, flags=re.I).strip()
    # collapse whitespace
    s = re.sub(r"\s+", " ", s)
    return s

def _int_or_none(v):
    try:
        if v is None or v == "":
            return None
        return int(float(v))
    except Exception:
        return None

def _ok(resp: dict, status: int = 200) -> func.HttpResponse:
    # ensure_ascii=False => send real UTF-8 characters, not \uXXXX escapes
    body = json.dumps(resp, ensure_ascii=False)
    return func.HttpResponse(
        body,
        status_code=status,
        # be explicit about UTF-8 so every client renders it correctly
        mimetype="application/json; charset=utf-8",
        headers=_cors(),
    )

def _err(msg: str, status: int = 400) -> func.HttpResponse:
    return _ok({"error": msg}, status)

def _to_payload(track: dict, fallback_title: str, fallback_artist: str) -> dict:
    # LRC Lib uses these keys in both /get and /search payloads
    title  = track.get("trackName")  or fallback_title
    artist = track.get("artistName") or fallback_artist
    synced = bool(track.get("syncedLyrics"))
    return {
        "found":  True,
        "title":  title,
        "artist": artist,
        "synced": synced,
        "lrc":    track.get("syncedLyrics") or "",
        "text":   track.get("plainLyrics") or ""
    }

def main(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors())

    try:
        title   = clean(req.params.get("title", ""))
        artist  = clean(req.params.get("artist", ""))
        album   = clean(req.params.get("album", ""))  # optional; used only for search hint
        dur     = _int_or_none(req.params.get("duration"))

        if not title:
            return _err("title required", 400)

        # ---- First try the precise /api/get endpoint
        get_params = {"track_name": title}
        if artist:
            get_params["artist_name"] = artist
        if dur:
            get_params["duration"] = dur

        try:
            r = requests.get(LRCLIB_GET, params=get_params, headers=REQ_HEADERS, timeout=10)
            if r.status_code == 404:
                # Not found, we’ll try search next
                raise requests.HTTPError("not found", response=r)
            r.raise_for_status()
            data = r.json()
            return _ok(_to_payload(data, title, artist))
        except requests.HTTPError:
            # If /get fails (400/404), fall back to /search to be forgiving
            pass

        # ---- Fallback: /api/search (returns an array; we’ll pick the best item)
        search_params = {"track_name": title, "limit": 5}
        if artist:
            search_params["artist_name"] = artist
        if album:
            search_params["album_name"] = album
        if dur:
            search_params["duration"] = dur

        rs = requests.get(LRCLIB_SEARCH, params=search_params, headers=REQ_HEADERS, timeout=10)
        if rs.status_code == 404:
            return _ok({"found": False})
        rs.raise_for_status()
        items = rs.json() or []

        if not isinstance(items, list) or not items:
            return _ok({"found": False})

        # Prefer exact/near-exact match on title/artist (case-insensitive); otherwise first item
        def norm(x): return (x or "").strip().lower()
        t_norm = norm(title)
        a_norm = norm(artist)
        best = None
        for it in items:
            if norm(it.get("trackName")) == t_norm and (not a_norm or norm(it.get("artistName")) == a_norm):
                best = it
                break
        if best is None:
            best = items[0]

        return _ok(_to_payload(best, title, artist))

    except Exception as e:
        logging.exception("lyrics failed")
        return _err(str(e), 500)