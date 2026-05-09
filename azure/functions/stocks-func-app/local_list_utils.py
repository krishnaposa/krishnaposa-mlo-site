# local_list_utils.py
import os, json, logging
from typing import List, Tuple, Dict, Optional

try:
    from azure.storage.blob import BlobServiceClient, ContentSettings
except Exception:  # pragma: no cover
    BlobServiceClient = None  # type: ignore
    ContentSettings = None    # type: ignore

logger = logging.getLogger(__name__)

# --------------------------- Config ---------------------------
# Container/blob name (defaults to the same container your signals/parquets use)
LOCAL_LIST_CONTAINER = os.getenv("LOCAL_LIST_CONTAINER", os.getenv("SIGNALS_CONTAINER", "signals"))
LOCAL_LIST_BLOB_NAME = os.getenv("LOCAL_LIST_BLOB_NAME", "local_list.json")
HOLDINGS_LIST_CONTAINER = os.getenv("HOLDINGS_LIST_CONTAINER", LOCAL_LIST_CONTAINER)
HOLDINGS_LIST_BLOB_NAME = os.getenv("HOLDINGS_LIST_BLOB_NAME", "holdings_list.json")

# Connection string:
# Prefer MONITOR_STORAGE (new storage account), fall back to AzureWebJobsStorage for local/test.
AZ_CONN = os.getenv("MONITOR_STORAGE") or os.getenv("AzureWebJobsStorage")

# If the blob is missing and you passed initial_fallback to load_local_list(),
# set this to "1" to seed the blob on first run.
LOCAL_LIST_SEED_ON_MISSING = os.getenv("LOCAL_LIST_SEED_ON_MISSING", "0") == "1"

# --------------------------- Blob helpers ---------------------------
def _blob_container():
    if BlobServiceClient is None:
        raise RuntimeError("azure.storage.blob not available. Install azure-storage-blob.")
    if not AZ_CONN:
        raise RuntimeError("Storage connection not found. Set MONITOR_STORAGE or AzureWebJobsStorage.")
    svc = BlobServiceClient.from_connection_string(AZ_CONN)
    cont = svc.get_container_client(LOCAL_LIST_CONTAINER)
    try:
        cont.create_container()
    except Exception:
        pass
    return cont

def _get_blob_client():
    cont = _blob_container()
    return cont.get_blob_client(LOCAL_LIST_BLOB_NAME)

def _get_named_blob_client(container_name: str, blob_name: str):
    if BlobServiceClient is None:
        raise RuntimeError("azure.storage.blob not available. Install azure-storage-blob.")
    if not AZ_CONN:
        raise RuntimeError("Storage connection not found. Set MONITOR_STORAGE or AzureWebJobsStorage.")
    svc = BlobServiceClient.from_connection_string(AZ_CONN)
    cont = svc.get_container_client(container_name)
    try:
        cont.create_container()
    except Exception:
        pass
    return cont.get_blob_client(blob_name)

# --------------------------- Public API ---------------------------
def load_local_list(initial_fallback: Optional[List[str]] = None) -> List[str]:
    """
    Load local_list.json from Blob. If missing, return initial_fallback (or empty list).
    If LOCAL_LIST_SEED_ON_MISSING=1 and initial_fallback is provided, it will also seed the blob.
    """
    try:
        blob = _get_blob_client()
        data = blob.download_blob().readall()
        js = json.loads(data.decode("utf-8", errors="ignore"))
        tickers = [str(t).upper().strip() for t in (js.get("tickers") or []) if str(t).strip()]
        tickers = sorted(set(tickers))
        logger.info(f"[local_list] loaded {len(tickers)} symbols from {LOCAL_LIST_CONTAINER}/{LOCAL_LIST_BLOB_NAME}")
        return tickers
    except Exception as e:
        fb = [str(t).upper().strip() for t in (initial_fallback or []) if str(t).strip()]
        fb = sorted(set(fb))
        if fb:
            logger.warning(f"[local_list] not found; using fallback ({len(fb)} symbols) — {e}")
            # Optionally seed the blob on first run
            if LOCAL_LIST_SEED_ON_MISSING:
                try:
                    save_local_list(fb, meta={"seeded_from_fallback": True})
                    logger.info(f"[local_list] seeded blob with {len(fb)} fallback symbols")
                except Exception as se:
                    logger.warning(f"[local_list] failed to seed blob: {se}")
            return fb
        logger.warning(f"[local_list] not found; returning empty list ({e})")
        return []

def save_local_list(tickers: List[str], meta: Optional[Dict] = None) -> None:
    """
    Save local list to Blob as JSON.
    """
    if BlobServiceClient is None:
        raise RuntimeError("azure.storage.blob not available. Install azure-storage-blob.")
    if ContentSettings is None:
        raise RuntimeError("ContentSettings import failed; ensure azure-storage-blob is installed.")

    tickers_norm = sorted({str(t).upper().strip() for t in tickers if str(t).strip()})
    payload = {"tickers": tickers_norm}
    if meta:
        payload.update(meta)

    cont = _blob_container()
    cont.upload_blob(
        LOCAL_LIST_BLOB_NAME,
        data=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json"),
    )
    logger.info(
        f"[local_list] saved {len(tickers_norm)} symbols -> {LOCAL_LIST_CONTAINER}/{LOCAL_LIST_BLOB_NAME}"
    )

def load_holdings_list(initial_fallback: Optional[List[str]] = None) -> List[str]:
    """
    Load holdings_list.json from Blob. This is the user's actual holdings list
    used for exit-watch emails.
    """
    try:
        blob = _get_named_blob_client(HOLDINGS_LIST_CONTAINER, HOLDINGS_LIST_BLOB_NAME)
        data = blob.download_blob().readall()
        js = json.loads(data.decode("utf-8", errors="ignore"))
        tickers = [str(t).upper().strip() for t in (js.get("tickers") or []) if str(t).strip()]
        tickers = sorted(set(tickers))
        logger.info(f"[holdings_list] loaded {len(tickers)} symbols from {HOLDINGS_LIST_CONTAINER}/{HOLDINGS_LIST_BLOB_NAME}")
        return tickers
    except Exception as e:
        fb = sorted({str(t).upper().strip() for t in (initial_fallback or []) if str(t).strip()})
        if fb:
            logger.warning(f"[holdings_list] not found; using fallback ({len(fb)} symbols) - {e}")
            return fb
        logger.warning(f"[holdings_list] not found; returning empty list ({e})")
        return []

def save_holdings_list(tickers: List[str], meta: Optional[Dict] = None) -> None:
    if BlobServiceClient is None:
        raise RuntimeError("azure.storage.blob not available. Install azure-storage-blob.")
    if ContentSettings is None:
        raise RuntimeError("ContentSettings import failed; ensure azure-storage-blob is installed.")

    tickers_norm = sorted({str(t).upper().strip() for t in tickers if str(t).strip()})
    payload = {"tickers": tickers_norm}
    if meta:
        payload.update(meta)

    blob = _get_named_blob_client(HOLDINGS_LIST_CONTAINER, HOLDINGS_LIST_BLOB_NAME)
    blob.upload_blob(
        data=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json"),
    )
    logger.info(f"[holdings_list] saved {len(tickers_norm)} symbols -> {HOLDINGS_LIST_CONTAINER}/{HOLDINGS_LIST_BLOB_NAME}")

# ---------- Dynamic update policy (optional; kept for flexibility) ----------
def update_local_list(
    df_all,                       # DataFrame from daily_monitor (after scoring)
    local_list: List[str],
    universe_list: List[str],
    *,
    add_top_quantile: float = 0.90,    # add if final_rank in top 10% of *today's* distribution
    min_strength_z: float = 0.0,       # require strength_score >= 0-z
    min_price: float = 5.0,            # skip < $5
    remove_days_fail: int = 5,         # placeholder for stateful logic
    max_local_size: Optional[int] = None
) -> Tuple[List[str], Dict[str, List[str]]]:
    """
    Stateless one-day heuristic (kept for optional usage):
      ADD: names with strong ranks today.
      REMOVE: weak names by simple filters.
    Returns (new_list, changes_dict).
    """
    S_local = {t.upper().strip() for t in local_list}
    S_univ  = {t.upper().strip() for t in universe_list}

    df = df_all.copy()
    df = df.dropna(subset=["final_rank", "last_price"])

    fr = df["final_rank"]
    thr = fr.quantile(add_top_quantile)
    eligible_add = df[
        (df["final_rank"] >= thr) &
        (df["strength_score"] >= min_strength_z) &
        (df["last_price"] >= min_price)
    ]["ticker"].astype(str).str.upper().tolist()

    rm_thr = fr.quantile(0.20)
    eligible_remove = df[
        (df["ticker"].isin(S_local)) & (
            (df["last_price"] < min_price) |
            (df["final_rank"] <= rm_thr) |
            (df["strength_score"] < -0.5)
        )
    ]["ticker"].astype(str).str.upper().tolist()

    S_new = (S_local | set(eligible_add)) - set(eligible_remove)

    if max_local_size and len(S_new) > max_local_size:
        top = df.sort_values("final_rank", ascending=False)["ticker"].astype(str).str.upper().tolist()
        pruned: List[str] = []
        for t in top:
            if t in S_new:
                pruned.append(t)
            if len(pruned) >= max_local_size:
                break
        S_new = set(pruned)

    additions = sorted([t for t in S_new - S_local])
    removals  = sorted([t for t in S_local - S_new])
    changes = {"added": additions, "removed": removals}

    return sorted(S_new), changes