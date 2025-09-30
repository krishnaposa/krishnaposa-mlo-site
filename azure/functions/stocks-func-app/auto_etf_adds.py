#!/usr/bin/env python3
"""
Auto ETF Adds (no manual inputs)
================================

What it does
------------
- For a built-in set of popular ETFs (editable list below), fetch **current holdings**
  from the issuer's public CSV/XLSX endpoints.
- Fetch a **historical snapshot ~30 days ago** of the *same* holdings file via the
  Internet Archive **Wayback Machine CDX API**.
- Compare weights and surface the **Top 2–3 increased positions per ETF**.

Why Wayback?
------------
Issuers usually only publish *current* holdings. To compare against "last month",
we ask the Wayback Machine for the closest archived copy around your target date.

Built-in ETFs (edit as needed)
------------------------------
- ARKK  (ARK Funds)      CSV
- QQQ   (Invesco)        CSV download endpoint
- SPY   (State Street)   XLSX

You can add more ETFs by extending ETF_CATALOG with a stable holdings URL.
If a fund family changes URL structure, update here once—no other inputs needed.

Usage
-----
pip install pandas requests openpyxl
python auto_etf_adds.py --since 2025-08-30 --until 2025-09-30 --out out_etf_adds --top-k 3 --min-delta 0.02

Notes
-----
- The Wayback snapshot near your dates might not exist. The script widens the search
  window (±7d → ±30d → ±90d) automatically.
- If a prior snapshot can't be found, the ETF is skipped with a warning.
- Weights are normalized to **percent (0–100)**.
- If an endpoint serves XLSX, we read the first sheet and auto-detect columns.
- All network I/O happens via requests (no API keys needed).

References
----------
- ARK CSV endpoint (example): https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv
- Invesco QQQ CSV endpoint: https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?action=download&audienceType=Investor&ticker=QQQ
- SPDR SPY daily XLSX: https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx
- Wayback CDX API docs: https://archive.org/developers/wayback-cdx-server.html
"""

import argparse
import io
import sys
import time
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
from datetime import date, datetime, timedelta

import pandas as pd
import requests

# -----------------------------
# Config: add/edit ETFs here
# -----------------------------

@dataclass
class EtfSource:
    ticker: str
    name: str
    url: str         # direct holdings file (CSV or XLSX)
    fmt: str         # 'csv' or 'xlsx'

ETF_CATALOG: List[EtfSource] = [
    EtfSource("ARKK", "ARK Innovation ETF", "https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv", "csv"),
    EtfSource("QQQ",  "Invesco QQQ Trust", "https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?action=download&audienceType=Investor&ticker=QQQ", "csv"),
    EtfSource("SPY",  "SPDR S&P 500 ETF Trust", "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx", "xlsx"),
]

# -----------------------------
# Wayback helpers
# -----------------------------

CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
WAYBACK_FETCH = "https://web.archive.org/web/{timestamp}if_/{url}"

def _yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")

def find_wayback_timestamp(url: str, target: date, flex_days: int) -> Optional[str]:
    """
    Ask CDX API for a capture within [target - flex_days, target + flex_days].
    Return the first timestamp (closest available), else None.
    """
    params = {
        "url": url,
        "from": _yyyymmdd(target - timedelta(days=flex_days)),
        "to":   _yyyymmdd(target + timedelta(days=flex_days)),
        "output": "json",
        "filter": "statuscode:200",
        "limit": "1"
    }
    try:
        r = requests.get(CDX_ENDPOINT, params=params, timeout=20)
        r.raise_for_status()
        js = r.json()
        # js[0] is header; rows afterwards are captures: [urlkey, timestamp, original, mimetype, statuscode, digest, length]
        if len(js) >= 2:
            ts = js[1][1]
            return ts
        return None
    except Exception as e:
        print(f"[WARN] Wayback query failed for {url}: {e}", file=sys.stderr)
        return None

def fetch_with_wayback(url: str, target: date) -> Optional[bytes]:
    """Find a nearby snapshot; widen flex windows automatically."""
    for flex in (7, 30, 90, 180):
        ts = find_wayback_timestamp(url, target, flex)
        if ts:
            snap = WAYBACK_FETCH.format(timestamp=ts, url=url)
            try:
                rr = requests.get(snap, timeout=30)
                rr.raise_for_status()
                return rr.content
            except Exception as e:
                print(f"[WARN] Wayback fetch failed {snap}: {e}", file=sys.stderr)
                continue
    return None

# -----------------------------
# File readers with heuristics
# -----------------------------

TICKER_CANDS = ["ticker", "symbol", "holding ticker", "asset", "security", "name"]
WEIGHT_CANDS = ["weight", "weight %", "% weight", "weight pct", "% of fund", "percent", "%"]

def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df

def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    lower = {c.lower(): c for c in df.columns}
    # exact lower match
    for cand in candidates:
        if cand in lower:
            return lower[cand]
    # contains match
    for cand in candidates:
        for c in df.columns:
            if cand in c.lower():
                return c
    return None

def _ensure_percent(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series.astype(str).str.replace('%','', regex=False).str.replace(',',''), errors="coerce")
    med = s.median(skipna=True)
    if pd.notna(med) and med <= 1.5:
        return s * 100.0
    return s

def read_holdings_bytes(data: bytes, fmt: str) -> pd.DataFrame:
    if fmt == "csv":
        df = pd.read_csv(io.BytesIO(data))
    elif fmt == "xlsx":
        df = pd.read_excel(io.BytesIO(data), sheet_name=0, engine="openpyxl")
    else:
        raise ValueError(f"Unsupported fmt: {fmt}")
    if df.empty:
        return df
    df = _norm_cols(df)
    tcol = _find_col(df, TICKER_CANDS)
    wcol = _find_col(df, WEIGHT_CANDS)
    if not tcol or not wcol:
        # Try some family-specific fallbacks
        # Invesco QQQ often uses 'Ticker' and a weight column like '% of Fund' or 'Weight'
        # ARK CSV has 'ticker' and 'weight' (with % sign)
        # SPDR XLSX often has 'Ticker' and 'Weight'
        raise ValueError(f"Could not detect Ticker/Weight columns; found: {list(df.columns)}")
    out = pd.DataFrame({
        "Ticker": df[tcol].astype(str).str.upper().str.strip(),
        "WeightPct": _ensure_percent(df[wcol])
    })
    out = out.dropna(subset=["Ticker", "WeightPct"])
    out["Ticker"] = out["Ticker"].str.replace(r"[^A-Z0-9\.\-]", "", regex=True)
    return out

# -----------------------------
# Core diff logic
# -----------------------------

def compute_adds(prev_df: pd.DataFrame, curr_df: pd.DataFrame) -> pd.DataFrame:
    prev = prev_df.groupby("Ticker", as_index=False)["WeightPct"].sum().rename(columns={"WeightPct":"PrevWeightPct"})
    curr = curr_df.groupby("Ticker", as_index=False)["WeightPct"].sum().rename(columns={"WeightPct":"CurrWeightPct"})
    merged = pd.merge(curr, prev, on="Ticker", how="left")
    merged["PrevWeightPct"] = merged["PrevWeightPct"].fillna(0.0)
    merged["DeltaWeightPct"] = merged["CurrWeightPct"] - merged["PrevWeightPct"]
    adds = merged[merged["DeltaWeightPct"] > 0].copy()
    adds.sort_values("DeltaWeightPct", ascending=False, inplace=True)
    return adds[["Ticker","PrevWeightPct","CurrWeightPct","DeltaWeightPct"]]

# -----------------------------
# Driver
# -----------------------------

def run(out_dir: Path, since: date, until: Optional[date], top_k: int, min_delta: float):
    out_dir.mkdir(parents=True, exist_ok=True)
    details_dir = out_dir / "details"
    details_dir.mkdir(parents=True, exist_ok=True)

    summary_rows = []
    log_lines = []

    # default until = today
    if until is None:
        until = date.today()

    # Use 'since' as the baseline date; we'll fetch closest snapshot to 'since'
    for etf in ETF_CATALOG:
        print(f"[INFO] Processing {etf.ticker} ({etf.name}) ...")
        try:
            # 1) Fetch current holdings from live URL
            rc = requests.get(etf.url, timeout=30)
            rc.raise_for_status()
            curr_df = read_holdings_bytes(rc.content, etf.fmt)
        except Exception as e:
            msg = f"[WARN] Current fetch failed for {etf.ticker}: {e}"
            print(msg)
            log_lines.append(msg)
            continue

        # 2) Fetch prior snapshot via Wayback near 'since'
        prior_bytes = fetch_with_wayback(etf.url, since)
        if prior_bytes is None:
            msg = f"[WARN] No prior snapshot found for {etf.ticker} near {since.isoformat()}."
            print(msg)
            log_lines.append(msg)
            continue

        try:
            prev_df = read_holdings_bytes(prior_bytes, etf.fmt)
        except Exception as e:
            msg = f"[WARN] Failed to parse prior snapshot for {etf.ticker}: {e}"
            print(msg)
            log_lines.append(msg)
            continue

        # 3) Compute adds
        adds_df = compute_adds(prev_df, curr_df)
        if min_delta > 0:
            adds_df = adds_df[adds_df["DeltaWeightPct"] >= min_delta]

        # 4) Save full details
        adds_df.to_csv(details_dir / f"{etf.ticker}_adds.csv", index=False)

        # 5) Top-K rows for summary
        topk = adds_df.head(top_k)
        for _, r in topk.iterrows():
            summary_rows.append({
                "ETF": etf.ticker,
                "Ticker": r["Ticker"],
                "PrevWeightPct": float(r["PrevWeightPct"]),
                "CurrWeightPct": float(r["CurrWeightPct"]),
                "DeltaWeightPct": float(r["DeltaWeightPct"]),
            })

    if summary_rows:
        sdf = pd.DataFrame(summary_rows).sort_values(["ETF","DeltaWeightPct"], ascending=[True, False])
        sdf.to_csv(out_dir / "summary_top_adds.csv", index=False)
        print(f"[OK] Wrote summary_top_adds.csv with {len(sdf)} rows.")
    else:
        print("[INFO] No adds found or no snapshots available.")

    # Write log
    (out_dir / "log.txt").write_text("\n".join(log_lines) if log_lines else "OK\n", encoding="utf-8")


def parse_args():
    ap = argparse.ArgumentParser(description="Find top 2–3 holdings increases per ETF over the last month (auto, no manual inputs).")
    ap.add_argument("--since", type=str, default=None, help="Baseline date (YYYY-MM-DD). Default: 30 days ago.")
    ap.add_argument("--until", type=str, default=None, help="Current date (YYYY-MM-DD). Default: today.")
    ap.add_argument("--out", type=str, default="out_etf_adds", help="Output folder")
    ap.add_argument("--top-k", type=int, default=3, help="Top K adds per ETF")
    ap.add_argument("--min-delta", type=float, default=0.0, help="Minimum delta in percentage points to include (e.g., 0.02 = +0.02pp)")
    return ap.parse_args()

if __name__ == "__main__":
    args = parse_args()
    today = date.today()
    since = datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else today - timedelta(days=30)
    until = datetime.strptime(args.until, "%Y-%m-%d").date() if args.until else None
    run(Path(args.out), since, until, args.top_k, args.min_delta)
