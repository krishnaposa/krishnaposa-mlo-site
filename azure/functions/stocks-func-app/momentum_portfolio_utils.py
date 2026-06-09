"""
Momentum portfolio persistence — same pattern as local_list_utils (Azure Blob + optional local file).

Blob (when MONITOR_STORAGE / AzureWebJobsStorage is set):
  Container: MOMENTUM_PORTFOLIO_CONTAINER (default: same as LOCAL_LIST_CONTAINER / signals)
  Blob:      MOMENTUM_PORTFOLIO_BLOB_NAME (default: momentum_portfolio.json)

JSON shape (matches local_list style with a named payload):
  {
    "positions": { "AAPL": { "high_seen": 195.5 }, ... },
    "meta": { "updated_at": "...", ... }
  }

Legacy files that are a flat map { "TICKER": { "high_seen": ... } } without "positions"
are still loaded.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from azure.storage.blob import BlobServiceClient, ContentSettings
except Exception:  # pragma: no cover
    BlobServiceClient = None  # type: ignore
    ContentSettings = None  # type: ignore

logger = logging.getLogger(__name__)

_APP_ROOT = Path(__file__).resolve().parent

MOMENTUM_PORTFOLIO_CONTAINER = os.getenv(
    "MOMENTUM_PORTFOLIO_CONTAINER",
    os.getenv("LOCAL_LIST_CONTAINER", os.getenv("SIGNALS_CONTAINER", "signals")),
)
MOMENTUM_PORTFOLIO_BLOB_NAME = os.getenv("MOMENTUM_PORTFOLIO_BLOB_NAME", "momentum_portfolio.json")
AZ_CONN = os.getenv("MONITOR_STORAGE") or os.getenv("AzureWebJobsStorage")


def default_local_portfolio_path() -> Path:
    p = (os.getenv("MOMENTUM_PORTFOLIO_FILE") or "").strip()
    if p:
        return Path(p).expanduser()
    return _APP_ROOT / "momentum_portfolio.json"


def storage_description() -> str:
    """Human-readable source label for emails / logs."""
    if _use_blob():
        return f"blob:{MOMENTUM_PORTFOLIO_CONTAINER}/{MOMENTUM_PORTFOLIO_BLOB_NAME}"
    return f"file:{default_local_portfolio_path()}"


def _use_blob() -> bool:
    return bool(AZ_CONN and BlobServiceClient is not None)


def _blob_client():
    if BlobServiceClient is None:
        raise RuntimeError("azure.storage.blob not available")
    if not AZ_CONN:
        raise RuntimeError("Storage connection not found")
    svc = BlobServiceClient.from_connection_string(AZ_CONN)
    cont = svc.get_container_client(MOMENTUM_PORTFOLIO_CONTAINER)
    try:
        cont.create_container()
    except Exception:
        pass
    return cont.get_blob_client(MOMENTUM_PORTFOLIO_BLOB_NAME)


def _normalize_positions(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for k, v in raw.items():
        kk = str(k).upper().strip()
        if not kk or not isinstance(v, dict):
            continue
        try:
            hi = float(v.get("high_seen", 0.0) or 0.0)
        except (TypeError, ValueError):
            hi = 0.0
        out[kk] = {"high_seen": hi}
    return out


def _parse_positions_doc(js: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(js, dict):
        return {}
    pos = js.get("positions")
    if isinstance(pos, dict):
        return _normalize_positions(pos)
    port = js.get("portfolio")
    if isinstance(port, dict):
        return _normalize_positions(port)
    # Legacy: ticker keys at root (exclude local_list-style keys)
    skip = {"positions", "portfolio", "meta", "tickers", "updated_at"}
    legacy = {k: v for k, v in js.items() if str(k) not in skip}
    return _normalize_positions(legacy)


def _load_from_blob() -> Dict[str, Dict[str, Any]]:
    blob = _blob_client()
    data = blob.download_blob().readall()
    js = json.loads(data.decode("utf-8", errors="ignore"))
    pos = _parse_positions_doc(js)
    logger.info(
        "[momentum_portfolio] loaded %s positions from %s/%s",
        len(pos),
        MOMENTUM_PORTFOLIO_CONTAINER,
        MOMENTUM_PORTFOLIO_BLOB_NAME,
    )
    return pos


def _load_from_local_file() -> Dict[str, Dict[str, Any]]:
    fp = default_local_portfolio_path()
    if not fp.is_file():
        return {}
    try:
        with open(fp, encoding="utf-8") as f:
            js = json.load(f)
        pos = _parse_positions_doc(js)
        logger.info("[momentum_portfolio] loaded %s positions from %s", len(pos), fp)
        return pos
    except Exception as e:
        logger.warning("[momentum_portfolio] cannot read %s: %s", fp, e)
        return {}


def load_momentum_portfolio(
    initial_fallback: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Load positions: try Blob first (if storage configured), then local JSON file.
    """
    if _use_blob():
        try:
            return _load_from_blob()
        except Exception as e:
            logger.warning("[momentum_portfolio] blob load failed, trying local file: %s", e)
    pos = _load_from_local_file()
    if pos:
        return pos
    fb = initial_fallback or {}
    return _normalize_positions(fb) if fb else {}


def _build_payload(
    positions: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    norm = _normalize_positions(positions)
    m = dict(meta or {})
    m.setdefault("updated_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    m.setdefault("schema", "momentum_portfolio_v1")
    return {"positions": norm, "meta": m}


def _write_local_bytes(raw: bytes) -> None:
    fp = default_local_portfolio_path()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_bytes(raw)
    logger.info("[momentum_portfolio] saved -> %s", fp)


def save_momentum_portfolio(
    positions: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Save to Blob when storage is configured (same pattern as local_list).
    If Blob succeeds, return unless MOMENTUM_PORTFOLIO_MIRROR_LOCAL=1 (also write local copy).
    If Blob is unavailable or fails, write local JSON (dev / fallback).
    """
    payload = _build_payload(positions, meta=meta)
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    blob_ok = False
    if _use_blob() and ContentSettings is not None:
        try:
            blob = _blob_client()
            blob.upload_blob(
                data=raw,
                overwrite=True,
                content_settings=ContentSettings(content_type="application/json"),
            )
            blob_ok = True
            logger.info(
                "[momentum_portfolio] saved -> %s/%s",
                MOMENTUM_PORTFOLIO_CONTAINER,
                MOMENTUM_PORTFOLIO_BLOB_NAME,
            )
        except Exception as e:
            logger.warning("[momentum_portfolio] blob save failed: %s", e)

    if blob_ok:
        if os.getenv("MOMENTUM_PORTFOLIO_MIRROR_LOCAL", "0") == "1":
            try:
                _write_local_bytes(raw)
            except Exception as e:
                logger.warning("[momentum_portfolio] local mirror failed: %s", e)
        return

    try:
        _write_local_bytes(raw)
    except Exception as e:
        raise RuntimeError(f"momentum portfolio save failed (no blob / blob error): {e}") from e
