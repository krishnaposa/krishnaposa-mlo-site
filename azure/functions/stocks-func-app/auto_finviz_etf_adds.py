#!/usr/bin/env python3
"""
Auto ETF Adds via Finviz Screener (polite version)
- Discovers ETFs from Finviz filters
- Parses Top Holdings from each ETF Finviz page
- Pulls Wayback snapshot near --since for historical holdings
- Compares weights and outputs top adds

New:
- Randomized delays + exponential backoff (handles 429)
- Rotating User-Agents
- --max-etfs limiter
- Parser more robust (doesn’t rely solely on 'Top Holdings' text)

Usage:
pip install requests beautifulsoup4 pandas

python auto_finviz_etf_adds.py \
  --filters "ind_exchangetradedfund,geo_usa,ta_highlow52w_nh" \
  --since 2025-08-30 \
  --out out_finviz_adds \
  --top-k 3 \
  --min-delta 0.02 \
  --max-etfs 25 \
  --delay 1.5 --jitter 1.0 --retries 6
"""

import argparse
import sys
import re
import time
import random
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import pandas as pd

FINVIZ_BASE = "https://finviz.com"
SCREENER_URL = FINVIZ_BASE + "/screener.ashx"
QUOTE_URL    = FINVIZ_BASE + "/quote.ashx?t={ticker}"

CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
WAYBACK_FETCH = "https://web.archive.org/web/{timestamp}if_/{url}"

# ---------- Polite HTTP helpers ----------

USER_AGENTS = [
    # Rotate to reduce fingerprinting
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

def make_session():
    s = requests.Session()
    s.headers.update({"User-Agent": random.choice(USER_AGENTS), "Accept-Language": "en-US,en;q=0.9"})
    return s

def polite_get(session: requests.Session, url: str, delay: float, jitter: float, retries: int, referer: Optional[str]=None):
    """
    GET with randomized sleep, exponential backoff on 429/5xx, and UA rotation.
    """
    if referer:
        session.headers["Referer"] = referer

    backoff = delay
    attempt = 0
    while True:
        # polite base delay + jitter
        sleep_for = max(0, delay + random.uniform(0, jitter))
        time.sleep(sleep_for)

        try:
            resp = session.get(url, timeout=30)
        except requests.RequestException as e:
            attempt += 1
            if attempt > retries:
                raise
            time.sleep(backoff)
            backoff = min(backoff * 2, 20.0)
            continue

        # Handle rate limiting or transient server errors
        if resp.status_code in (429, 503, 502, 520, 522):
            attempt += 1
            if attempt > retries:
                resp.raise_for_status()
            # rotate UA and back off
            session.headers["User-Agent"] = random.choice(USER_AGENTS)
            time.sleep(backoff + random.uniform(0, 1.0))
            backoff = min(backoff * 2, 30.0)
            continue

        resp.raise_for_status()
        return resp

# ---------- Wayback helpers (polite) ----------

def yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")

def find_wayback_timestamp(session: requests.Session, url: str, target: date, flex_days: int,
                           delay: float, jitter: float, retries: int) -> Optional[str]:
    params = {
        "url": url,
        "from": yyyymmdd(target - timedelta(days=flex_days)),
        "to":   yyyymmdd(target + timedelta(days=flex_days)),
        "output": "json",
        "filter": "statuscode:200",
        "limit": "1"
    }
    r = polite_get(session, CDX_ENDPOINT, delay, jitter, retries)
    r = session.get(CDX_ENDPOINT, params=params, timeout=30)
    r.raise_for_status()
    js = r.json()
    if len(js) >= 2:
        return js[1][1]
    return None

def fetch_wayback(session: requests.Session, url: str, target: date, delay: float, jitter: float, retries: int) -> Optional[bytes]:
    for flex in (7, 30, 90, 180):
        ts = find_wayback_timestamp(session, url, target, flex, delay, jitter, retries)
        if ts:
            snap = WAYBACK_FETCH.format(timestamp=ts, url=url)
            rr = polite_get(session, snap, delay, jitter, retries)
            return rr.content
    return None

# ---------- Screener ----------

def screener_fetch_etfs(filters: str, session: requests.Session, delay: float, jitter: float, retries: int, max_pages: int = 50) -> List[str]:
    all_tickers = []
    page = 1
    while page <= max_pages:
        start_row = 1 + (page - 1) * 20
        params = { "v": "111", "f": filters, "r": str(start_row) }
        r = polite_get(session, SCREENER_URL, delay, jitter, retries, referer=FINVIZ_BASE + "/")
        r = session.get(SCREENER_URL, params=params, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")

        tickers = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = re.search(r"quote\.ashx\?t=([A-Z0-9\.\-]+)", href, re.I)
            if m:
                tick = m.group(1).upper()
                if tick not in tickers:
                    tickers.append(tick)

        new = [t for t in tickers if t not in all_tickers]
        if not new:
            break
        all_tickers.extend(new)
        page += 1

    return all_tickers

# ---------- Parser (robust) ----------

TICKER_RE = re.compile(r"\b([A-Z]{1,5}(?:\.[A-Z])?)\b")
PCT_RE    = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")

def parse_finviz_holdings(html: bytes) -> pd.DataFrame:
    """
    Try to find a table with ticker-like text and % weights.
    This is more robust than relying on an exact 'Top Holdings' label.
    """
    soup = BeautifulSoup(html, "html.parser")

    tables = soup.find_all("table")
    candidates = []
    for tbl in tables:
        txt = tbl.get_text(" ", strip=True)
        # Must contain at least a few % and a few ticker-like tokens
        if len(PCT_RE.findall(txt)) >= 3 and len(TICKER_RE.findall(txt)) >= 3:
            candidates.append(tbl)

    if not candidates:
        # fallback: try to locate heading by string
        for h in soup.find_all(string=re.compile(r"Top Holdings", re.I)):
            parent = h.parent
            for _ in range(5):
                if parent and parent.find("table"):
                    candidates.append(parent.find("table"))
                    break
                parent = parent.parent

    if not candidates:
        return pd.DataFrame(columns=["Ticker","WeightPct"])

    # parse first candidate thoroughly
    rows = []
    for tr in candidates[0].find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if not cells:
            continue
        row_text = " ".join(cells)
        m_tick = TICKER_RE.search(row_text)
        m_pct  = PCT_RE.search(row_text)
        if m_tick and m_pct:
            ticker = m_tick.group(1)
            weight = float(m_pct.group(1))
            rows.append([ticker, weight])

    return pd.DataFrame(rows, columns=["Ticker","WeightPct"]).drop_duplicates(subset=["Ticker"])

# ---------- Diff ----------

def compute_adds(prev_df: pd.DataFrame, curr_df: pd.DataFrame) -> pd.DataFrame:
    prev = prev_df.groupby("Ticker", as_index=False)["WeightPct"].sum().rename(columns={"WeightPct":"PrevWeightPct"})
    curr = curr_df.groupby("Ticker", as_index=False)["WeightPct"].sum().rename(columns={"WeightPct":"CurrWeightPct"})
    merged = pd.merge(curr, prev, on="Ticker", how="left")
    merged["PrevWeightPct"] = merged["PrevWeightPct"].fillna(0.0)
    merged["DeltaWeightPct"] = merged["CurrWeightPct"] - merged["PrevWeightPct"]
    adds = merged[merged["DeltaWeightPct"] > 0].copy()
    adds.sort_values("DeltaWeightPct", ascending=False, inplace=True)
    return adds[["Ticker","PrevWeightPct","CurrWeightPct","DeltaWeightPct"]]

# ---------- Driver ----------

def run(filters: str, since: date, out_dir: Path, top_k: int, min_delta: float,
        delay: float, jitter: float, retries: int, max_etfs: int):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "details").mkdir(parents=True, exist_ok=True)

    session = make_session()

    # 1) Discover ETFs
    tickers = screener_fetch_etfs(filters, session, delay, jitter, retries)
    if max_etfs and len(tickers) > max_etfs:
        tickers = tickers[:max_etfs]

    if not tickers:
        print("[INFO] No ETFs found for given filters.")
        (out_dir / "log.txt").write_text("No ETFs found.\n", encoding="utf-8")
        return

    summary_rows = []
    logs = []

    for etf in tickers:
        url = QUOTE_URL.format(ticker=etf)
        print(f"[INFO] Processing {etf} ...")

        # Current page
        try:
            rc = polite_get(session, url, delay, jitter, retries, referer=FINVIZ_BASE + "/screener.ashx")
            curr_df = parse_finviz_holdings(rc.content)
        except Exception as e:
            msg = f"[WARN] Failed to fetch/parse current page for {etf}: {e}"
            print(msg)
            logs.append(msg)
            continue

        if curr_df.empty:
            msg = f"[WARN] No holdings found on current Finviz page for {etf}."
            print(msg)
            logs.append(msg)
            continue

        # Historical snapshot
        prior_bytes = None
        try:
            prior_bytes = fetch_wayback(session, url, since, delay, jitter, retries)
        except Exception as e:
            msg = f"[WARN] Wayback error for {etf}: {e}"
            print(msg)
            logs.append(msg)

        if prior_bytes is None:
            logs.append(f"[WARN] No prior snapshot found for {etf} near {since}.")
            continue

        try:
            prev_df = parse_finviz_holdings(prior_bytes)
        except Exception as e:
            msg = f"[WARN] Failed to parse historical page for {etf}: {e}"
            print(msg)
            logs.append(msg)
            continue

        adds_df = compute_adds(prev_df, curr_df)
        if min_delta > 0:
            adds_df = adds_df[adds_df["DeltaWeightPct"] >= min_delta]

        # Save details
        adds_df.to_csv(out_dir / "details" / f"{etf}_adds.csv", index=False)

        # Top-K
        for _, r in adds_df.head(top_k).iterrows():
            summary_rows.append({
                "ETF": etf,
                "Ticker": r["Ticker"],
                "PrevWeightPct": float(r["PrevWeightPct"]),
                "CurrWeightPct": float(r["CurrWeightPct"]),
                "DeltaWeightPct": float(r["DeltaWeightPct"]),
            })

    if summary_rows:
        sdf = pd.DataFrame(summary_rows).sort_values(["ETF","DeltaWeightPct"], ascending=[True, False])
        sdf.to_csv(out_dir / "summary_top_adds.csv", index=False)

    (out_dir / "log.txt").write_text("\n".join(logs) if logs else "OK\n", encoding="utf-8")

def parse_args():
    ap = argparse.ArgumentParser(description="Finviz ETF adds (polite).")
    ap.add_argument("--filters", type=str, required=True, help="Finviz filter string for ETFs (e.g., 'ind_exchangetradedfund,geo_usa,ta_highlow52w_nh')")
    ap.add_argument("--since", type=str, default=None, help="Baseline date YYYY-MM-DD (default: 30 days ago)")
    ap.add_argument("--out", type=str, default="out_finviz_adds")
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--min-delta", type=float, default=0.0)
    # Politeness knobs
    ap.add_argument("--delay", type=float, default=1.5, help="Base delay between requests (seconds)")
    ap.add_argument("--jitter", type=float, default=1.0, help="Random jitter added to each delay (seconds)")
    ap.add_argument("--retries", type=int, default=6, help="Max retries on 429/5xx")
    ap.add_argument("--max-etfs", type=int, default=25, help="Limit number of ETFs to process (helps avoid 429s)")
    return ap.parse_args()

if __name__ == "__main__":
    args = parse_args()
    today = date.today()
    since = datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else (today - timedelta(days=30))
    run(
        filters=args.filters,
        since=since,
        out_dir=Path(args.out),
        top_k=args.top_k,
        min_delta=args.min_delta,
        delay=args.delay,
        jitter=args.jitter,
        retries=args.retries,
        max_etfs=args.max_etfs
    )