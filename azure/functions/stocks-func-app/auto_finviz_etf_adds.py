import logging, io, time, random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, Dict, List
from pathlib import Path

import requests
import pandas as pd
from finviz.screener import Screener  # pip install finviz

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"

# --- 1) ETF discovery via finviz package ---
def discover_etfs_via_finviz(filters: List[str], order: str = "price", max_count: int = 50) -> List[str]:
    logging.info("Discovering ETFs via Finviz with filters=%s order=%s ...", ",".join(filters), order)
    tickers = []
    try:
        rows = Screener(filters=filters, table="Valuation", order=order)
        for r in rows:
            t = str(r.get("Ticker", "")).upper().strip()
            if t and t not in tickers:
                tickers.append(t)
            if len(tickers) >= max_count:
                break
        logging.info("Found %d ETFs (limited to %d).", len(tickers), max_count)
    except Exception as e:
        logging.exception("Finviz discovery failed: %s", e)
    return tickers

# --- 2) Issuer endpoints registry (extend as you go) ---
@dataclass
class HoldingSource:
    fmt: str     # 'csv' or 'xlsx'
    url: str     # direct holdings file

ISSUER_REGISTRY: Dict[str, HoldingSource] = {
    # Add as needed; examples:
    "ARKK": HoldingSource("csv",  "https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv"),
    "QQQ":  HoldingSource("csv",  "https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?action=download&audienceType=Investor&ticker=QQQ"),
    "SPY":  HoldingSource("xlsx", "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"),
    # e.g., add "SOXX": HoldingSource("csv", "<issuer-url>")
}

# --- 3) Polite fetch + Wayback helper ---
CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
WAYBACK_FETCH = "https://web.archive.org/web/{timestamp}if_/{url}"

def yyyymmdd(d: date) -> str: return d.strftime("%Y%m%d")

def wayback_timestamp(url: str, target: date, session: requests.Session) -> Optional[str]:
    for flex in (7, 30, 90, 180):
        params = {"url": url, "from": yyyymmdd(target - timedelta(days=flex)),
                  "to": yyyymmdd(target + timedelta(days=flex)), "output": "json",
                  "filter": "statuscode:200", "limit": "1"}
        logging.info("Wayback query %s window ±%sd", url, flex)
        r = session.get(CDX_ENDPOINT, params=params, timeout=30)
        if r.status_code == 200:
            js = r.json()
            if len(js) >= 2:
                ts = js[1][1]
                logging.info("Wayback hit for %s @ %s", url, ts)
                return ts
        time.sleep(1.0 + random.random())
    logging.warning("No Wayback snapshot for %s near %s", url, target)
    return None

def read_holdings_bytes(data: bytes, fmt: str) -> pd.DataFrame:
    if fmt == "csv":
        df = pd.read_csv(io.BytesIO(data))
    else:
        df = pd.read_excel(io.BytesIO(data), sheet_name=0, engine="openpyxl")
    # try to locate Ticker + Weight columns
    dfc = {c.strip(): c for c in df.columns}
    def _pick(cols, cands):
        lower = {k.lower(): k for k in dfc}
        for cand in cands:
            if cand in lower: return dfc[lower[cand]]
        for cand in cands:
            for k in dfc:
                if cand in k.lower(): return dfc[k]
        return None
    tcol = _pick(dfc, ["ticker","symbol","holding ticker","asset","security","name"])
    wcol = _pick(dfc, ["weight","weight %","% weight","portfolio weight","percent","% of fund","%"])
    if not tcol or not wcol:
        raise ValueError(f"Could not detect Ticker/Weight columns. Found: {list(df.columns)}")
    s = pd.to_numeric(
        pd.Series(df[wcol].astype(str).str.replace("%","", regex=False).str.replace(",","")),
        errors="coerce"
    )
    med = s.median(skipna=True)
    if pd.notna(med) and med <= 1.5:  # convert 0–1 → percent
        s = s * 100.0
    out = pd.DataFrame({"Ticker": df[tcol].astype(str).str.upper().str.strip(),
                        "WeightPct": s})
    out = out.dropna(subset=["Ticker","WeightPct"])
    out["Ticker"] = out["Ticker"].str.replace(r"[^A-Z0-9\.\-]", "", regex=True)
    return out

# --- 4) Compare weights ---
def compute_adds(prev_df: pd.DataFrame, curr_df: pd.DataFrame) -> pd.DataFrame:
    prev = prev_df.groupby("Ticker", as_index=False)["WeightPct"].sum().rename(columns={"WeightPct": "PrevWeightPct"})
    curr = curr_df.groupby("Ticker", as_index=False)["WeightPct"].sum().rename(columns={"WeightPct": "CurrWeightPct"})
    merged = pd.merge(curr, prev, on="Ticker", how="left")
    merged["PrevWeightPct"] = merged["PrevWeightPct"].fillna(0.0)
    merged["DeltaWeightPct"] = merged["CurrWeightPct"] - merged["PrevWeightPct"]
    adds = merged[merged["DeltaWeightPct"] > 0].copy().sort_values("DeltaWeightPct", ascending=False)
    return adds[["Ticker","PrevWeightPct","CurrWeightPct","DeltaWeightPct"]]

# --- 5) Orchestrate ---
def top_adds_for_etfs(filters: List[str], since: date, top_k=3, min_delta=0.0, out_dir: Path = Path("out")):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "details").mkdir(parents=True, exist_ok=True)
    session = requests.Session(); session.headers.update({"User-Agent": UA})

    etfs = discover_etfs_via_finviz(filters, order="price", max_count=50)
    summary = []

    for etf in etfs:
        if etf not in ISSUER_REGISTRY:
            logging.info("Skipping %s (no issuer holdings endpoint in registry).", etf)
            continue
        src = ISSUER_REGISTRY[etf]
        logging.info("Fetching current holdings for %s from %s", etf, src.url)
        r = session.get(src.url, timeout=30); r.raise_for_status()
        curr_df = read_holdings_bytes(r.content, src.fmt)

        ts = wayback_timestamp(src.url, since, session)
        if not ts:
            logging.info("No prior snapshot for %s; skipping.", etf)
            continue
        snap_url = WAYBACK_FETCH.format(timestamp=ts, url=src.url)
        logging.info("Fetching prior snapshot for %s: %s", etf, snap_url)
        rp = session.get(snap_url, timeout=30); rp.raise_for_status()
        prev_df = read_holdings_bytes(rp.content, src.fmt)

        adds = compute_adds(prev_df, curr_df)
        if min_delta > 0:
            adds = adds[adds["DeltaWeightPct"] >= min_delta]
        adds.to_csv(out_dir / "details" / f"{etf}_adds.csv", index=False)
        for _, row in adds.head(top_k).iterrows():
            summary.append({"ETF": etf, **row.to_dict()})

        logging.info("Completed %s: %d adds (top %d saved).", etf, len(adds), min(top_k, len(adds)))

    if summary:
        pd.DataFrame(summary).sort_values(["ETF","DeltaWeightPct"], ascending=[True, False]).to_csv(out_dir / "summary_top_adds.csv", index=False)
        logging.info("Wrote %s", out_dir / "summary_top_adds.csv")
    else:
        logging.info("No results. Check registry coverage or since-date snapshots.")