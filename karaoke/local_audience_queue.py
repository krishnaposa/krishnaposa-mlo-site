#!/usr/bin/env python3
"""
Local audience queue server.

This runs the same local queue functionality as local_folder_queue.py and adds
audience session endpoints used by `host.html` / `audience.html`:
  GET  /api/audience/session?room_id=...
  POST /api/audience/session
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import urllib.parse

import local_folder_queue as lfq

_audience_lock = threading.Lock()
_audience_sessions: dict[str, Dict[str, Any]] = {}


def _audience_get(room_id: str) -> Optional[Dict[str, Any]]:
    rid = (room_id or "").strip()
    if not rid:
        return None
    with _audience_lock:
        data = _audience_sessions.get(rid)
        if not data:
            return None
        return dict(data)


def _audience_upsert(room_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    rid = (room_id or "").strip()
    if not rid:
        raise ValueError("room_id required")
    with _audience_lock:
        cur = dict(_audience_sessions.get(rid) or {"room_id": rid})
        cur.update(patch)
        cur["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        _audience_sessions[rid] = cur
        return dict(cur)


class AudienceHandler(lfq.Handler):
    def _handle_get_audience_session(self, parsed: urllib.parse.ParseResult) -> None:
        qs = urllib.parse.parse_qs(parsed.query)
        room_id = ((qs.get("room_id") or [""])[0] or "").strip()
        if not room_id:
            self._send(400, json.dumps({"error": "room_id required"}).encode())
            return
        data = _audience_get(room_id)
        if not data:
            self._send(200, json.dumps({"found": False, "room_id": room_id}).encode("utf-8"))
            return
        self._send(200, json.dumps({"found": True, "session": data}, ensure_ascii=False).encode("utf-8"))

    def _handle_post_audience_session(self) -> None:
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
        room_id = (body.get("room_id") or "").strip()
        if not room_id:
            self._send(400, json.dumps({"error": "room_id required"}).encode())
            return
        patch = {
            "host_name": (body.get("host_name") or "").strip(),
            "job_id": (body.get("job_id") or "").strip(),
            "title": (body.get("title") or "").strip(),
            "vocals_url": (body.get("vocals_url") or "").strip(),
            "band_url": (body.get("band_url") or "").strip(),
            "playing": bool(body.get("playing", False)),
            "position_sec": float(body.get("position_sec") or 0.0),
            "synced": bool(body.get("synced", False)),
            "lrc": (body.get("lrc") or "").strip(),
            "text": body.get("text") or "",
        }
        saved = _audience_upsert(room_id, patch)
        self._send(200, json.dumps({"ok": True, "session": saved}, ensure_ascii=False).encode("utf-8"))

    def do_HEAD(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path_norm = parsed.path.rstrip("/")
        if path_norm == "/api/audience/session":
            qs = urllib.parse.parse_qs(parsed.query)
            room_id = ((qs.get("room_id") or [""])[0] or "").strip()
            if not room_id:
                raw = json.dumps({"error": "room_id required"}).encode()
                self.send_response(400)
                for k, v in self._cors().items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                return
            data = _audience_get(room_id)
            if not data:
                raw = json.dumps({"found": False, "room_id": room_id}).encode("utf-8")
            else:
                raw = json.dumps({"found": True, "session": data}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            for k, v in self._cors().items():
                self.send_header(k, v)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            return
        super().do_HEAD()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path_norm = parsed.path.rstrip("/")
        if path_norm == "/api/audience/session":
            self._handle_get_audience_session(parsed)
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path.rstrip("/")
        if route == "/api/audience/session":
            self._handle_post_audience_session()
            return
        super().do_POST()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    lfq._ensure_dirs()
    lfq._ffmpeg_path_prep()
    lfq.LOG.info("KARAOKE_LOCAL_ROOT=%s", lfq.ROOT)
    lfq.LOG.info("SEPARATOR=%s", lfq.SEPARATOR)
    lfq.LOG.info("KARAOKE_LIST_CACHE_TTL=%ss", lfq.KARAOKE_LIST_CACHE_TTL)
    if lfq.KARAOKE_PRETRIM:
        lfq.LOG.info(
            "KARAOKE_PRETRIM=1 silence_db=%s min_silence=%s",
            lfq.KARAOKE_PRETRIM_SILENCE_DB,
            lfq.KARAOKE_PRETRIM_MIN_SILENCE,
        )
    if lfq.SEPARATOR == "demucs":
        lfq.LOG.info("DEMUCS_MODEL=%s DEMUCS_JOBS=%s", lfq.DEMUCS_MODEL, lfq.DEMUCS_JOBS)
    try:
        selected = lfq.resolve_separator()
        lfq.LOG.info("Resolved separator=%s", selected)
    except Exception as e:
        lfq.LOG.error("Separator check failed: %s", e)
    lfq.LOG.info("Serving %s — audience + local queue mode", lfq.PUBLIC_BASE)

    t = threading.Thread(target=lfq.worker_loop, name="karaoke-worker", daemon=True)
    t.start()

    server = lfq.ThreadingHTTPServer((lfq.HOST, lfq.PORT), AudienceHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        lfq.LOG.info("shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
