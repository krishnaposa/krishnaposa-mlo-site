import json, os, re, logging
import azure.functions as func
import requests

LRCLIB = "https://lrclib.net/api/get"

def _cors():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization"
    }

def clean(s: str) -> str:
    if not s: return ""
    # remove common decorations like " (Official Video)" etc.
    return re.sub(r"\s*\((official|audio|video|lyrics?|hd|4k|remastered)[^)]*\)\s*$", "", s, flags=re.I).strip()

def main(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors())
    try:
        title   = clean(req.params.get("title", ""))
        artist  = clean(req.params.get("artist", ""))
        album   = clean(req.params.get("album", ""))
        dur     = req.params.get("duration")  # seconds (optional, helps matching)
        # LRCLIB requires one of: (track_name & artist_name) OR (track_name & duration)
        if not title:
            return func.HttpResponse(json.dumps({"error":"title required"}), status_code=400, mimetype="application/json", headers=_cors())

        q = {"track_name": title}
        if artist: q["artist_name"] = artist
        if album:  q["album_name"]  = album
        if dur:
            try: q["duration"] = int(float(dur))
            except: pass

        r = requests.get(LRCLIB, params=q, timeout=10)
        if r.status_code == 404:
            return func.HttpResponse(json.dumps({"found": False}), mimetype="application/json", headers=_cors())
        r.raise_for_status()
        data = r.json()  # has 'syncedLyrics' and/or 'plainLyrics'
        resp = {
            "found": True,
            "title": data.get("trackName") or title,
            "artist": data.get("artistName") or artist,
            "synced": bool(data.get("syncedLyrics")),
            "lrc": data.get("syncedLyrics") or "",
            "text": data.get("plainLyrics") or ""
        }
        return func.HttpResponse(json.dumps(resp), mimetype="application/json", headers=_cors())
    except Exception as e:
        logging.exception("lyrics failed")
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, mimetype="application/json", headers=_cors())