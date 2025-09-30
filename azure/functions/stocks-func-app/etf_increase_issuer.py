#!/usr/bin/env python3
"""
For each Finviz ETF filter:
  - take top 2 ETFs
  - fetch current holdings (issuer)
  - fetch prior month-end from issuer (if supported) OR local snapshot cache
  - check top 5 current holdings for % weight increase vs prior
Outputs:
  out_etf_increases/summary_by_filter.csv
  out_etf_increases/details/{FILTERKEY}_{ETF}.csv
  out_etf_increases/snapshots/{TICKER}/{YYYYMMDD}.{csv|xlsx.raw}  (local cache)
"""

import io
import json
import logging
import re
from dataclasses import dataclass
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
from finviz.screener import Screener  # pip install finviz

# ------------- Logging -------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

# ------------- Constants -------------
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
OUT_DIR = Path("out_etf_increases")
DETAILS_DIR = OUT_DIR / "details"
SNAP_DIR = OUT_DIR / "snapshots"
CACHE_PATH = Path("issuer_cache.json")  # for discovered endpoints (if you extend later)

# ------------- Date helpers -------------
def prev_month_end(ref: date) -> date:
    y = ref.year if ref.month > 1 else ref.year - 1
    m = ref.month - 1 if ref.month > 1 else 12
    last = monthrange(y, m)[1]
    return date(y, m, last)

def ymd(d: date) -> str:
    return d.strftime("%Y-%m-%d")

def yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")

# ------------- HTTP session -------------
def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s

# ------------- Finviz discovery -------------
def finviz_top_etfs(finviz_filters: List[str], top_n: int = 2, order: str = "price",
                    fallback: Optional[List[str]] = None) -> List[str]:
    logging.info("Finviz: filters=%s → top %d ETFs ...", ",".join(finviz_filters), top_n)
    out = []
    try:
        rows = Screener(filters=finviz_filters, table="Valuation", order=order)
        for r in rows:
            t = str(r.get("Ticker", "")).upper().strip()
            if t and t not in out:
                out.append(t)
            if len(out) >= top_n:
                break
        logging.info("Selected ETFs: %s", ", ".join(out))
        return out
    except Exception as e:
        logging.warning("Finviz discovery failed (%s). Using fallback: %s", e, fallback)

    return fallback[:top_n] if fallback else []
    
# ------------- Issuer registry -------------
@dataclass
class HoldingSource:
    fmt: str   # 'csv' or 'xlsx'
    url: str   # current holdings URL (no date)

ISSUER_REGISTRY: Dict[str, HoldingSource] = {
    # ARK (no public date param; use snapshot cache fallback)
    "ARKK": HoldingSource("csv","https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv"),
    "ARKG": HoldingSource("csv","https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv"),
    "ARKF": HoldingSource("csv","https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_FINTECH_INNOVATION_ETF_ARKF_HOLDINGS.csv"),
    "ARKQ": HoldingSource("csv","https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_AUTONOMOUS_TECHNOLOGY_&_ROBOTICS_ETF_ARKQ_HOLDINGS.csv"),
    "ARKX": HoldingSource("csv","https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_SPACE_EXPLORATION_&_INNOVATION_ETF_ARKX_HOLDINGS.csv"),

    # Invesco (current CSV via ticker; dated not consistently public → snapshot fallback)
    "QQQ":  HoldingSource("csv","https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?action=download&audienceType=Investor&ticker=QQQ"),
    "SOXQ": HoldingSource("csv","https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?action=download&audienceType=Investor&ticker=SOXQ"),

    # SPDR (supports as-of param on XLSX)
    "SPY": HoldingSource("xlsx","https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"),
    "XLK": HoldingSource("xlsx","https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xlk.xlsx"),
    "XLY": HoldingSource("xlsx","https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xly.xlsx"),
    "XLF": HoldingSource("xlsx","https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xlf.xlsx"),
    "XLE": HoldingSource("xlsx","https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xle.xlsx"),
    "XLV": HoldingSource("xlsx","https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xlv.xlsx"),
    "XLI": HoldingSource("xlsx","https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xli.xlsx"),
    "XLB": HoldingSource("xlsx","https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xlb.xlsx"),
    "XLU": HoldingSource("xlsx","https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xlu.xlsx"),
    "XLC": HoldingSource("xlsx","https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xlc.xlsx"),
    "XBI": HoldingSource("xlsx","https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xbi.xlsx"),

    # iShares (most accept &asofDate=YYYYMMDD on ajax CSV; some need product IDs embedded — these work)
    "IVV": HoldingSource("csv","https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf/1467271812596.ajax?fileType=csv"),
    "IWF": HoldingSource("csv","https://www.ishares.com/us/products/239726/ishares-russell-1000-growth-etf/1467271812596.ajax?fileType=csv"),
    "IWD": HoldingSource("csv","https://www.ishares.com/us/products/239710/ishares-russell-1000-value-etf/1467271812596.ajax?fileType=csv"),
    "IWM": HoldingSource("csv","https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/1467271812596.ajax?fileType=csv"),

    # Vanguard (current CSV via ?csv=true; dated often not public → snapshot fallback)
    "VOO": HoldingSource("csv","https://investor.vanguard.com/investment-products/etfs/profile/portfolio/voo?csv=true"),
    "VTI": HoldingSource("csv","https://investor.vanguard.com/investment-products/etfs/profile/portfolio/vti?csv=true"),
}

# ------------- Prior-report builders (issuer-specific) -------------
def build_prior_url(ticker: str, src: HoldingSource, as_of: date) -> Optional[str]:
    """Return issuer URL for prior report if pattern is known; else None (use snapshot cache)."""
    u = src.url
    # SPDR: supports ?asOfDate=YYYY-MM-DD
    if "ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-" in u and src.fmt == "xlsx":
        joiner = "&" if "?" in u else "?"
        return f"{u}{joiner}asOfDate={ymd(as_of)}"

    # iShares ajax CSV: append &asofDate=YYYYMMDD (works for many)
    if "ishares.com" in u and "ajax?fileType=csv" in u and src.fmt == "csv":
        joiner = "&" if "?" in u else "?"
        return f"{u}{joiner}asofDate={yyyymmdd(as_of)}"

    # Invesco / Vanguard / ARK: no reliable public as-of param → None
    return None

# ------------- Parse holdings (robust) -------------
TICKER_LIKE = re.compile(r"^[A-Z]{1,5}(?:\.[A-Z])?$")

def _guess_ticker_col(df: pd.DataFrame) -> Optional[str]:
    best, score = None, -1
    for c in df.columns:
        s = df[c].astype(str).str.strip().str.upper()
        m = s.str.match(TICKER_LIKE).sum()
        if m > score:
            best, score = c, int(m)
    return best if score >= 3 else None

def _guess_weight_col(df: pd.DataFrame) -> Optional[str]:
    for c in df.columns:
        if "weight" in str(c).lower():
            return c
    best, score = None, -1
    for c in df.columns:
        s = pd.to_numeric(df[c], errors="coerce")
        m = s.between(0, 100, inclusive="both").sum()
        if m > score:
            best, score = c, int(m)
    return best if score >= 3 else None

def _read_xlsx(bytes_: bytes) -> pd.DataFrame:
    raw = pd.read_excel(io.BytesIO(bytes_), sheet_name=0, engine="openpyxl", header=None)
    raw = raw.dropna(axis=1, how="all")
    # scan for header
    for hdr in range(min(25, len(raw))):
        vals = [str(x).strip().lower() for x in list(raw.iloc[hdr].values)]
        if any(k in vals for k in ["ticker", "symbol"]) and any("weight" in v or v == "%" for v in vals):
            cols = [str(x).strip() for x in raw.iloc[hdr].values]
            df = raw.iloc[hdr+1:].copy()
            df.columns = cols
            return df.dropna(how="all")
    # fallback: first non-empty row as header
    for hdr in range(min(25, len(raw))):
        if raw.iloc[hdr].notna().sum() >= 2:
            cols = [str(x).strip() for x in raw.iloc[hdr].values]
            df = raw.iloc[hdr+1:].copy()
            df.columns = cols
            return df.dropna(how="all")
    return raw

def read_holdings(data: bytes, fmt: str) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(data)) if fmt == "csv" else _read_xlsx(data)
    if df.empty:
        raise ValueError("Empty holdings file")
    # map columns
    dfc = {str(c).strip(): c for c in df.columns}
    def pick(cands):
        lower = {k.lower(): k for k in dfc}
        for x in cands:
            if x in lower: return dfc[lower[x]]
        for x in cands:
            for k in dfc:
                if x in k.lower(): return dfc[k]
        return None
    tcol = pick(["ticker","symbol","identifier","security","name"])
    wcol = pick(["weight","weight %","% weight","portfolio weight","percent","% of fund","weighting","weight (%)"])
    if not tcol: tcol = _guess_ticker_col(df)
    if not wcol: wcol = _guess_weight_col(df)
    if not tcol or not wcol:
        raise ValueError(f"Can't find Ticker/Weight columns. Columns: {list(df.columns)}")
    weights = pd.to_numeric(
        df[wcol].astype(str).str.replace("%","", regex=False).str.replace(",",""),
        errors="coerce"
    )
    if pd.notna(weights.median()) and weights.median() <= 1.5:
        weights = weights * 100.0
    out = pd.DataFrame({
        "Ticker": df[tcol].astype(str).str.upper().str.strip().str.replace(r"[^A-Z0-9\.\-]", "", regex=True),
        "WeightPct": weights
    }).dropna(subset=["Ticker","WeightPct"])
    logging.info("Parsed holdings: %d rows (ticker=%s, weight=%s)", len(out), tcol, wcol)
    return out

# ------------- Local snapshot cache -------------
def save_snapshot(ticker: str, fmt: str, bytes_: bytes, asof: date) -> None:
    tdir = SNAP_DIR / ticker
    tdir.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        (tdir / f"{yyyymmdd(asof)}.csv").write_bytes(bytes_)
    else:
        (tdir / f"{yyyymmdd(asof)}.xlsx.raw").write_bytes(bytes_)

def load_snapshot(ticker: str, asof: date) -> Optional[bytes]:
    tdir = SNAP_DIR / ticker
    if not tdir.exists(): return None
    for ext in (".csv", ".xlsx.raw"):
        p = tdir / f"{yyyymmdd(asof)}{ext}"
        if p.exists():
            return p.read_bytes()
    return None

# ------------- Diff -------------
def compute_adds(prev_df: pd.DataFrame, curr_df: pd.DataFrame) -> pd.DataFrame:
    prev = prev_df.groupby("Ticker", as_index=False)["WeightPct"].sum().rename(columns={"WeightPct":"PrevWeightPct"})
    curr = curr_df.groupby("Ticker", as_index=False)["WeightPct"].sum().rename(columns={"WeightPct":"CurrWeightPct"})
    merged = pd.merge(curr, prev, on="Ticker", how="left")
    merged["PrevWeightPct"] = merged["PrevWeightPct"].fillna(0.0)
    merged["DeltaWeightPct"] = merged["CurrWeightPct"] - merged["PrevWeightPct"]
    adds = merged.sort_values("DeltaWeightPct", ascending=False)
    return adds[["Ticker","PrevWeightPct","CurrWeightPct","DeltaWeightPct"]]

# ------------- Core workflow for one ETF -------------
def analyze_etf(session: requests.Session, etf: str, src: HoldingSource, prior_asof: date,
                top_holdings: int = 5) -> Optional[pd.DataFrame]:
    # current
    logging.info("Fetching CURRENT holdings for %s", etf)
    rc = session.get(src.url, timeout=30)
    rc.raise_for_status()
    curr_df = read_holdings(rc.content, src.fmt).sort_values("WeightPct", ascending=False)
    top_names = curr_df["Ticker"].head(top_holdings).tolist()
    curr_df = curr_df[curr_df["Ticker"].isin(top_names)]

    # prior (issuer if possible)
    prior_url = build_prior_url(etf, src, prior_asof)
    prior_bytes = None
    if prior_url:
        try:
            logging.info("Fetching PRIOR holdings for %s via issuer: %s", etf, prior_url)
            rp = session.get(prior_url, timeout=30)
            if rp.status_code == 200 and len(rp.content) > 200:
                prior_bytes = rp.content
        except Exception as e:
            logging.info("Issuer prior fetch failed for %s: %s", etf, e)

    # fallback: local snapshot
    if prior_bytes is None:
        prior_bytes = load_snapshot(etf, prior_asof)
        if prior_bytes:
            logging.info("Loaded PRIOR holdings for %s from snapshot cache (%s).", etf, yyyymmdd(prior_asof))
        else:
            logging.info("No issuer prior & no snapshot for %s; saving CURRENT snapshot for future runs.", etf)

    # save current snapshot for today
    today = date.today()
    save_snapshot(etf, src.fmt, rc.content, today)

    if prior_bytes is None:
        # not enough info to compare yet
        return None

    prev_df = read_holdings(prior_bytes, src.fmt)
    prev_df = prev_df[prev_df["Ticker"].isin(top_names)]
    adds = compute_adds(prev_df, curr_df)
    return adds

# ------------- Orchestrator -------------
def run_for_filters(filters_list: List[List[str]], order: str = "price",
                    top_etfs: int = 2, top_holdings: int = 5) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DETAILS_DIR.mkdir(parents=True, exist_ok=True)
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    session = _session()
    prior_asof = prev_month_end(date.today())

    summary_rows: List[Dict] = []

    for fset in filters_list:
        key = "_".join(fset[:3]) if fset else "filter"
        etfs = finviz_top_etfs(fset, top_n=top_etfs, order=order)
        for etf in etfs:
            src = ISSUER_REGISTRY.get(etf)
            if not src:
                logging.info("Skipping %s (issuer URL not registered)", etf)
                continue
            try:
                adds = analyze_etf(session, etf, src, prior_asof, top_holdings=top_holdings)
            except Exception as e:
                logging.warning("Error for %s: %s", etf, e)
                continue

            if adds is None or adds.empty:
                logging.info("%s: no prior available yet or no increases.", etf)
                continue

            adds["ETF"] = etf
            adds["FilterKey"] = key
            adds_sorted = adds.sort_values("DeltaWeightPct", ascending=False)
            adds_sorted.to_csv(DETAILS_DIR / f"{key}_{etf}.csv", index=False)

            # keep only top 5 names in summary (already restricted)
            for _, r in adds_sorted.iterrows():
                summary_rows.append({
                    "FilterKey": key,
                    "ETF": etf,
                    "Ticker": r["Ticker"],
                    "PrevWeightPct": float(r["PrevWeightPct"]),
                    "CurrWeightPct": float(r["CurrWeightPct"]),
                    "DeltaWeightPct": float(r["DeltaWeightPct"]),
                    "Increased": r["DeltaWeightPct"] > 0
                })

    if summary_rows:
        pd.DataFrame(summary_rows).sort_values(
            ["FilterKey","ETF","DeltaWeightPct"], ascending=[True, True, False]
        ).to_csv(OUT_DIR / "summary_by_filter.csv", index=False)
        logging.info("Wrote %s", OUT_DIR / "summary_by_filter.csv")
    else:
        logging.info("No results to summarize yet.")

# ------------- Example run -------------
if __name__ == "__main__":
    # Add the Finviz ETF filters you care about:
    finviz_filters_list = [
        ['geo_usa','ind_exchangetradedfund','ta_rsi_nob60','ta_sma20_cross50a','ta_sma200_pa','ta_sma50_pa','sh_avgvol_o200000','sh_price_o10'],          # new highs
        ['ind_exchangetradedfund','ta_highlow20d_nh','ta_perf2_4wup','ta_sma20_pa','ta_sma200_pa','ta_sma50_pa','geo_usa','sh_avgvol_o200000','sh_price_o10'],              # 1-week up
        ['geo_usa','ind_exchangetradedfund','ta_highlow52w_nh','sh_avgvol_o200000','ta_rsi_nob70'],  
        ['ind_exchangetradedfund','sh_avgvol_o2000','ta_change_u1','ta_highlow20d_nh']
    ]
    run_for_filters(
        filters_list=finviz_filters_list,
        order="price",
        top_etfs=2,        # top 2 ETFs per filter
        top_holdings=5     # analyze top 5 current holdings in each ETF
    )