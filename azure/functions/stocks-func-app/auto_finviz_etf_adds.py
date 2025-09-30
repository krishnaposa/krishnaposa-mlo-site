import logging, io, time, random, json, re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, Dict, List
from pathlib import Path

import requests
import pandas as pd
from finviz.screener import Screener  # pip install finviz

# =========================
# Logging
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

# =========================
# Constants
# =========================
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
WAYBACK_FETCH = "https://web.archive.org/web/{timestamp}if_/{url}"
CACHE_PATH = Path("issuer_cache.json")  # cache discovered endpoints so you don't rediscover every run

# =========================
# Helpers
# =========================
def yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s

# =========================
# 1) ETF discovery via Finviz package
# =========================
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

# =========================
# 2) Issuer endpoints registry (pre-populated) + DTO
# =========================
@dataclass
class HoldingSource:
    fmt: str     # 'csv' or 'xlsx'
    url: str     # direct holdings file

# Big starter set (add/remove as you like)
ISSUER_REGISTRY: Dict[str, HoldingSource] = {
    # --- ARK (CSV) ---
    "ARKK": HoldingSource("csv","https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv"),
    "ARKG": HoldingSource("csv","https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv"),
    "ARKF": HoldingSource("csv","https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_FINTECH_INNOVATION_ETF_ARKF_HOLDINGS.csv"),
    "ARKQ": HoldingSource("csv","https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_AUTONOMOUS_TECHNOLOGY_&_ROBOTICS_ETF_ARKQ_HOLDINGS.csv"),
    "ARKX": HoldingSource("csv","https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_SPACE_EXPLORATION_&_INNOVATION_ETF_ARKX_HOLDINGS.csv"),

    # --- Invesco (CSV; ticker param works for many) ---
    "QQQ":  HoldingSource("csv","https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?action=download&audienceType=Investor&ticker=QQQ"),
    "SOXQ": HoldingSource("csv","https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?action=download&audienceType=Investor&ticker=SOXQ"),

    # --- SPDR (XLSX; stable pattern) ---
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

    # --- iShares (CSV; product IDs vary; include popular ones) ---
    "IVV": HoldingSource("csv","https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf/1467271812596.ajax?fileType=csv"),
    "IWF": HoldingSource("csv","https://www.ishares.com/us/products/239726/ishares-russell-1000-growth-etf/1467271812596.ajax?fileType=csv"),
    "IWD": HoldingSource("csv","https://www.ishares.com/us/products/239710/ishares-russell-1000-value-etf/1467271812596.ajax?fileType=csv"),
    "IWM": HoldingSource("csv","https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/1467271812596.ajax?fileType=csv"),
    "EEM": HoldingSource("csv","https://www.ishares.com/us/products/239637/ishares-msci-emerging-markets-etf/1467271812596.ajax?fileType=csv"),
    "EFA": HoldingSource("csv","https://www.ishares.com/us/products/239623/ishares-msci-eafe-etf/1467271812596.ajax?fileType=csv"),
    "LQD": HoldingSource("csv","https://www.ishares.com/us/products/239566/ishares-iboxx-investment-grade-corporate-bond-etf/1467271812596.ajax?fileType=csv"),
    "HYG": HoldingSource("csv","https://www.ishares.com/us/products/239565/ishares-iboxx-high-yield-corporate-bond-etf/1467271812596.ajax?fileType=csv"),
    "IYR": HoldingSource("csv","https://www.ishares.com/us/products/239521/ishares-us-real-estate-etf/1467271812596.ajax?fileType=csv"),

    # --- Vanguard (CSV; many support ?csv=true) ---
    "VOO": HoldingSource("csv","https://investor.vanguard.com/investment-products/etfs/profile/portfolio/voo?csv=true"),
    "VTI": HoldingSource("csv","https://investor.vanguard.com/investment-products/etfs/profile/portfolio/vti?csv=true"),
    "VXUS":HoldingSource("csv","https://investor.vanguard.com/investment-products/etfs/profile/portfolio/vxus?csv=true"),
    "VUG": HoldingSource("csv","https://investor.vanguard.com/investment-products/etfs/profile/portfolio/vug?csv=true"),
    "VTV": HoldingSource("csv","https://investor.vanguard.com/investment-products/etfs/profile/portfolio/vtv?csv=true"),
}

# =========================
# 3) Programmatic endpoint discovery (SPDR + Invesco patterns) + cache
# =========================
def _try_get_ok(url: str, session: requests.Session) -> bool:
    try:
        r = session.get(url, timeout=25, allow_redirects=True)
        if r.status_code == 200 and r.content and len(r.content) > 200:
            return True
    except requests.RequestException:
        pass
    return False

def discover_issuer_endpoint_for_ticker(ticker: str, session: requests.Session) -> Optional[HoldingSource]:
    """
    Try common issuer URL patterns to find a direct holdings download for this ticker.
    Returns HoldingSource if found, else None.
    """
    t = ticker.upper()
    tl = t.lower()

    # SPDR pattern
    spdr = f"https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-{tl}.xlsx"
    if _try_get_ok(spdr, session):
        logging.info("Discovered SPDR endpoint for %s", t)
        return HoldingSource("xlsx", spdr)

    # Invesco pattern (works widely)
    inv = f"https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?action=download&audienceType=Investor&ticker={t}"
    if _try_get_ok(inv, session):
        logging.info("Discovered Invesco endpoint for %s", t)
        return HoldingSource("csv", inv)

    # (Optional) add more heuristics for other families here
    return None

def load_cache() -> Dict[str, HoldingSource]:
    if CACHE_PATH.exists():
        try:
            raw = json.loads(CACHE_PATH.read_text())
            return {k: HoldingSource(**v) for k, v in raw.items()}
        except Exception:
            pass
    return {}

def save_cache(cache: Dict[str, HoldingSource]) -> None:
    CACHE_PATH.write_text(json.dumps({k: vars(v) for k, v in cache.items()}, indent=2))

# =========================
# 4) Wayback helper (fixed: always pass params once; with earliest fallback)
# =========================
def wayback_timestamp(url: str, target: date, session: requests.Session) -> Optional[str]:
    for flex in (7, 30, 90, 180, 365):
        params = {
            "url": url,
            "from": yyyymmdd(target - timedelta(days=flex)),
            "to":   yyyymmdd(target + timedelta(days=flex)),
            "output": "json",
            "filter": "statuscode:200",
            "limit": "1"
        }
        logging.info("Wayback query for %s with window ±%sd", url, flex)
        try:
            r = session.get(CDX_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()
            js = r.json()
            if len(js) >= 2:
                ts = js[1][1]
                logging.info("Wayback hit: %s @ %s", url, ts)
                return ts
        except Exception as e:
            logging.warning("Wayback error for %s: %s", url, e)
        time.sleep(1.0 + random.random())

    # fallback to earliest available snapshot (so we don't skip entirely)
    try:
        params = {"url": url, "output": "json", "filter": "statuscode:200", "limit": "1", "from": "20000101"}
        r = session.get(CDX_ENDPOINT, params=params, timeout=30)
        r.raise_for_status()
        js = r.json()
        if len(js) >= 2:
            ts = js[1][1]
            logging.info("Fallback to earliest Wayback snapshot for %s @ %s", url, ts)
            return ts
    except Exception as e:
        logging.warning("Wayback earliest fallback failed for %s: %s", url, e)

    logging.warning("No Wayback snapshot found for %s near %s (and no earliest fallback).", url, target)
    return None

# =========================
# 5) Read holdings (CSV/XLSX) – robust header detection
# =========================
TICKER_LIKE = re.compile(r"^[A-Z]{1,5}(?:\.[A-Z])?$")

def _guess_ticker_col(df: pd.DataFrame) -> Optional[str]:
    best_col, best_score = None, -1
    for c in df.columns:
        s = df[c].astype(str).str.strip().str.upper()
        score = s.str.match(TICKER_LIKE).sum()
        if score > best_score:
            best_col, best_score = c, int(score)
    return best_col if best_score >= 3 else None  # need at least a few matches

def _guess_weight_col(df: pd.DataFrame) -> Optional[str]:
    for c in df.columns:
        if "weight" in str(c).lower():
            return c
    best_col, best_score = None, -1
    for c in df.columns:
        s = pd.to_numeric(df[c], errors="coerce")
        score = s.between(0, 100, inclusive="both").sum()
        if score > best_score:
            best_col, best_score = c, int(score)
    return best_col if best_score >= 3 else None

def _auto_header_excel(data: bytes) -> pd.DataFrame:
    raw = pd.read_excel(io.BytesIO(data), sheet_name=0, engine="openpyxl", header=None)
    raw = raw.dropna(axis=1, how="all")
    for hdr in range(min(25, len(raw))):
        vals = [str(x).strip() for x in list(raw.iloc[hdr].values)]
        low = [v.lower() for v in vals]
        has_weight = any("weight" in v or v == "%" for v in low)
        has_id = any(any(k in v for k in ("ticker","symbol","identifier","security","name","cusip")) for v in low)
        if has_weight and has_id:
            cols = [str(x).strip() for x in raw.iloc[hdr].values]
            df = raw.iloc[hdr+1:].copy()
            df.columns = cols
            df = df.dropna(how="all")
            logging.info("Detected header row at index %d with columns: %s", hdr, cols)
            return df
    for hdr in range(min(25, len(raw))):
        if raw.iloc[hdr].notna().sum() >= 2:
            cols = [str(x).strip() for x in raw.iloc[hdr].values]
            df = raw.iloc[hdr+1:].copy()
            df.columns = cols
            df = df.dropna(how="all")
            logging.info("Fallback header row at index %d with columns: %s", hdr, cols)
            return
            
def read_holdings_bytes(data: bytes, fmt: str) -> pd.DataFrame:
    if fmt == "csv":
        df = pd.read_csv(io.BytesIO(data))
    else:
        # read with no header first, then scan for header row
        df = pd.read_excel(io.BytesIO(data), sheet_name=0, engine="openpyxl", header=None)

    # Auto-detect header row
    header_row = None
    for i in range(min(25, len(df))):
        row = df.iloc[i].astype(str).str.lower().tolist()
        if any("ticker" in c or "symbol" in c or "cusip" in c for c in row) and \
           any("weight" in c or "%" in c for c in row):
            header_row = i
            break

    if header_row is not None:
        if fmt == "csv":
            df = pd.read_csv(io.BytesIO(data), header=header_row)
        else:
            df = pd.read_excel(io.BytesIO(data), sheet_name=0, engine="openpyxl", header=header_row)

    # Build a lookup of cleaned column names
    dfc = {str(c).strip(): c for c in df.columns}
    def _pick(cands):
        lower = {k.lower(): k for k in dfc}
        for cand in cands:
            if cand in lower: return dfc[lower[cand]]
        for cand in cands:
            for k in dfc:
                if cand in k.lower(): return dfc[k]
        return None

    tcol = _pick(["ticker","symbol","cusip","holding ticker","asset","security","name","identifier"])
    wcol = _pick(["weight","weight %","% weight","portfolio weight","percent","% of fund","%","weighting"])

    if not tcol or not wcol:
        raise ValueError(f"Could not detect Ticker/Weight columns. Columns: {list(df.columns)}")

    # Normalize weights
    s = pd.to_numeric(
        pd.Series(df[wcol].astype(str).str.replace("%","", regex=False).str.replace(",","")),
        errors="coerce"
    )
    med = s.median(skipna=True)
    if pd.notna(med) and med <= 1.5:  # convert 0–1 to percent
        s = s * 100.0

    out = pd.DataFrame({
        "Ticker": df[tcol].astype(str).str.upper().str.strip().str.replace(r"[^A-Z0-9\.\-]", "", regex=True),
        "WeightPct": s
    }).dropna(subset=["Ticker","WeightPct"])

    logging.info("Parsed holdings: %d rows (ticker col=%s, weight col=%s)", len(out), tcol, wcol)
    return out
# =========================
# 6) Compute adds/diffs
# =========================
def compute_adds(prev_df: pd.DataFrame, curr_df: pd.DataFrame) -> pd.DataFrame:
    prev = prev_df.groupby("Ticker", as_index=False)["WeightPct"].sum().rename(columns={"WeightPct": "PrevWeightPct"})
    curr = curr_df.groupby("Ticker", as_index=False)["WeightPct"].sum().rename(columns={"WeightPct": "CurrWeightPct"})
    merged = pd.merge(curr, prev, on="Ticker", how="left")
    merged["PrevWeightPct"] = merged["PrevWeightPct"].fillna(0.0)
    merged["DeltaWeightPct"] = merged["CurrWeightPct"] - merged["PrevWeightPct"]
    adds = merged[merged["DeltaWeightPct"] > 0].copy().sort_values("DeltaWeightPct", ascending=False)
    return adds[["Ticker","PrevWeightPct","CurrWeightPct","DeltaWeightPct"]]

# =========================
# 7) Orchestrator
# =========================
def top_adds_for_etfs(
    filters: List[str],
    since: date,
    top_k: int = 3,
    min_delta: float = 0.0,
    out_dir: Path = Path("out_etf_adds"),
    max_count: int = 50,
    top_holdings: int = 2   # NEW: only process top N current holdings
):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "details").mkdir(parents=True, exist_ok=True)
    session = _session()

    # Load + merge registry + cache
    cache = load_cache()
    registry = {**ISSUER_REGISTRY, **cache}

    etfs = discover_etfs_via_finviz(filters, order="price", max_count=max_count)
    summary = []

    for etf in etfs:
        src = registry.get(etf)
        if not src:
            # try programmatic discovery
            src = discover_issuer_endpoint_for_ticker(etf, session)
            if src:
                registry[etf] = src
                save_cache(registry)
            else:
                logging.info("Skipping %s (no issuer holdings endpoint in registry/cache).", etf)
                continue

        logging.info("Fetching current holdings for %s from %s", etf, src.url)
        try:
            r = session.get(src.url, timeout=30); r.raise_for_status()
            curr_df = read_holdings_bytes(r.content, src.fmt)
        except Exception as e:
            logging.warning("Failed to read current holdings for %s: %s", etf, e)
            continue

        # keep only top N holdings
        curr_df = curr_df.sort_values("WeightPct", ascending=False)
        top_tickers = curr_df["Ticker"].head(top_holdings).tolist()
        curr_df = curr_df[curr_df["Ticker"].isin(top_tickers)].copy()
        logging.info("Restricting %s to top %d holdings: %s", etf, top_holdings, ", ".join(top_tickers))

        ts = wayback_timestamp(src.url, since, session)
        if not ts:
            logging.info("No prior snapshot for %s; skipping.", etf)
            continue
        snap_url = WAYBACK_FETCH.format(timestamp=ts, url=src.url)

        try:
            rp = session.get(snap_url, timeout=30); rp.raise_for_status()
            prev_df = read_holdings_bytes(rp.content, src.fmt)
            prev_df = prev_df[prev_df["Ticker"].isin(top_tickers)].copy()
        except Exception as e:
            logging.warning("Failed to read prior holdings for %s: %s", etf, e)
            continue

        adds = compute_adds(prev_df, curr_df)
        if min_delta > 0:
            adds = adds[adds["DeltaWeightPct"] >= min_delta]
        adds.to_csv(out_dir / "details" / f"{etf}_adds.csv", index=False)
        for _, row in adds.head(top_k).iterrows():
            summary.append({"ETF": etf, **row.to_dict()})

        logging.info("Completed %s: %d adds (top %d saved).", etf, len(adds), min(top_k, len(adds)))

    if summary:
        pd.DataFrame(summary).sort_values(["ETF","DeltaWeightPct"], ascending=[True, False]) \
            .to_csv(out_dir / "summary_top_adds.csv", index=False)
        logging.info("Wrote %s", out_dir / "summary_top_adds.csv")
    else:
        logging.info("No results. Check registry coverage or since-date snapshots.")

# =========================
# Main
# =========================
if __name__ == "__main__":
    filters = ["ind_exchangetradedfund","geo_usa","ta_highlow52w_nh"]
    since = date.today() - timedelta(days=30)
    top_adds_for_etfs(
        filters=filters,
        since=since,
        top_k=3,
        min_delta=0.02,
        out_dir=Path("out_etf_adds"),
        max_count=50,
        top_holdings=2   # process only top 2 holdings of each ETF
    )