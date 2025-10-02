# local_list_utils.py
import os, json, logging
from typing import List, Tuple, Dict, Optional

try:
    from azure.storage.blob import BlobServiceClient, ContentSettings
except Exception:
    BlobServiceClient = None  # type: ignore

logger = logging.getLogger(__name__)

# Config via env
LOCAL_LIST_CONTAINER   = os.getenv("LOCAL_LIST_CONTAINER", os.getenv("SIGNALS_CONTAINER", "signals"))
LOCAL_LIST_BLOB_NAME   = os.getenv("LOCAL_LIST_BLOB_NAME", "local_list.json")
AZ_CONN                = os.getenv("MONITOR_STORAGE")

def _blob_container():
    if BlobServiceClient is None or not AZ_CONN:
        raise RuntimeError("azure.storage.blob not available or MONITOR_STORAGE missing")
    svc = BlobServiceClient.from_connection_string(AZ_CONN)
    cont = svc.get_container_client(LOCAL_LIST_CONTAINER)
    try:
        cont.create_container()
    except Exception:
        pass
    return cont

def load_local_list(initial_fallback: Optional[List[str]] = None) -> List[str]:
    """
    Load local_list.json from Blob. If missing, return initial_fallback (or empty list).
    """
    try:
        cont = _blob_container()
        blob = cont.get_blob_client(LOCAL_LIST_BLOB_NAME)
        data = blob.download_blob().readall()
        js = json.loads(data.decode("utf-8"))
        tickers = [str(t).upper().strip() for t in (js.get("tickers") or []) if str(t).strip()]
        logger.info(f"[local_list] loaded {len(tickers)} symbols from blob")
        return tickers
    except Exception as e:
        fb = [str(t).upper().strip() for t in (initial_fallback or []) if str(t).strip()]
        if fb:
            logger.warning(f"[local_list] not found; using fallback ({len(fb)} symbols)")
            return fb
        logger.warning(f"[local_list] not found; returning empty list ({e})")
        return []

def save_local_list(tickers: List[str], meta: Optional[Dict] = None) -> None:
    """
    Save local list to Blob as JSON.
    """
    cont = _blob_container()
    payload = {"tickers": sorted({str(t).upper().strip() for t in tickers if str(t).strip()})}
    if meta:
        payload.update(meta)
    cont.upload_blob(
        LOCAL_LIST_BLOB_NAME,
        data=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json")
    )
    logger.info(f"[local_list] saved {len(payload['tickers'])} symbols -> {LOCAL_LIST_CONTAINER}/{LOCAL_LIST_BLOB_NAME}")

# ---------- Dynamic update policy ----------

def update_local_list(
    df_all,                       # DataFrame from daily_monitor (after scoring)
    local_list: List[str],
    universe_list: List[str],
    *,
    add_top_quantile: float = 0.90,    # add if final_rank in top 10% of *universe*
    min_strength_z: float = 0.0,       # require strength_score >= 0-z
    min_price: float = 5.0,            # skip < $5
    remove_days_fail: int = 5,         # remove if failed 'keep mask' for N consecutive days (requires persistence; here we use one-day heuristic)
    max_local_size: int | None = None  # optional cap on list size
) -> Tuple[List[str], Dict[str, List[str]]]:
    """
    Stateless one-day heuristic:
      ADD: universe names with strong ranks today.
      REMOVE: local names that look weak today (below thresholds).
    Practical and simple to start — you can later make this stateful by tracking streaks in a side blob.

    Returns (new_list, changes_dict).
    """
    # Normalize inputs
    S_local = {t.upper().strip() for t in local_list}
    S_univ  = {t.upper().strip() for t in universe_list}
    union   = sorted(S_local | S_univ)

    # Rank threshold in universe context
    # (if a symbol isn't in today's df, we ignore)
    df = df_all.copy()
    df = df.dropna(subset=["final_rank", "last_price"])

    # Compute universe percentile for final_rank
    # We’ll treat missing as not-eligible for add.
    fr = df["final_rank"]
    thr = fr.quantile(add_top_quantile)
    eligible_add = df[
        (df["final_rank"] >= thr) &
        (df["strength_score"] >= min_strength_z) &
        (df["last_price"] >= min_price)
    ]["ticker"].astype(str).str.upper().tolist()

    # Removal heuristic:
    # drop from local if price < $5 or final_rank in bottom 20% or strength_score < -0.5
    rm_thr = fr.quantile(0.20)
    eligible_remove = df[
        (df["ticker"].isin(S_local)) & (
            (df["last_price"] < min_price) |
            (df["final_rank"] <= rm_thr) |
            (df["strength_score"] < -0.5)
        )
    ]["ticker"].astype(str).str.upper().tolist()

    # New set:
    S_new = (S_local | set(eligible_add)) - set(eligible_remove)

    # Optional cap (keep top by final_rank)
    if max_local_size and len(S_new) > max_local_size:
        top = df.sort_values("final_rank", ascending=False)["ticker"].astype(str).str.upper().tolist()
        pruned = []
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