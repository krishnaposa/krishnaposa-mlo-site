#!/usr/bin/env python3
"""
Auto ETF Adds via Finviz Screener
=================================

What this does
--------------
- Pulls a list of **ETFs** from the Finviz screener using your filter string (e.g. `ind_exchangetradedfund,geo_usa,ta_highlow52w_nh`).
- For each ETF (ticker), scrapes its **Finviz quote page** to collect the "Top Holdings" table (tickers & weights).
- Fetches a **historical snapshot** of that same Finviz page ~"since" date via the **Wayback Machine**.
- Compares Top Holdings weights (current vs snapshot) and outputs the **top 2–3 increases per ETF**.

Why Finviz pages?
-----------------
Finviz aggregates an ETF's top holdings and usually shows weight percentages. This means you can run the whole workflow
without juggling multiple issuer-specific downloads, while still spotting holdings being added over time.

Usage
-----
pip install requests beautifulsoup4 pandas
python auto_finviz_etf_adds.py \
  --filters "ind_exchangetradedfund,geo_usa,ta_highlow52w_nh" \
  --since 2025-08-30 \
  --out out_finviz_adds \
  --top-k 3 \
  --min-delta 0.02

Parameters
----------
--filters     Comma-separated Finviz filter tokens (exactly as you'd put in `f=` param)
--since       Baseline date (YYYY-MM-DD). We'll grab a Wayback snapshot near this date.
--until       Optional, unused for Finviz (present for symmetry).
--top-k       How many increased holdings per ETF to summarize (default 3)
--min-delta   Minimum increase in percentage points (0.02 = +0.02 pp) to include (default 0)

Outputs
-------
- out_finviz_adds/summary_top_adds.csv
- out_finviz_adds/details/<ETF>_adds.csv
- out_finviz_adds/log.txt

Notes
-----
- Finviz paginates the screener. We follow pages until exhausted.
- Not all ETFs show weights or many holdings; such tickers may be skipped.
- Wayback snapshots for a given date may not exist; we automatically widen the window (±7→30→90 days).
- Top Holdings on Finviz are not full portfolios; treat results as a **momentum-of-ownership hint**, not full truth.
"""

import argparse
import sys
import re
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple, Dict

import requests
from bs4 import BeautifulSoup
import pandas as pd

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
}

FINVIZ_BASE = "https://finviz.com"
SCREENER_URL = FINVIZ_BASE + "/screener.ashx"
QUOTE_URL = FINVIZ_BASE + "/quote.ashx?t={ticker}"

CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
WAYBACK_FETCH = "https://web.archive.org/web/{timestamp}if_/{url}"

def yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")

def find_wayback_timestamp(url: str, target: date, flex_days: int) -> Optional[str]:
    params = {
        "url": url,
        "from": yyyymmdd(target - timedelta(days=flex_days)),
        "to":   yyyymmdd(target + timedelta(days=flex_days)),
        "output": "json",
        "filter": "statuscode:200",
        "limit": "1"
    }
    try:
        r = requests.get(CDX_ENDPOINT, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        js = r.json()
        if len(js) >= 2:
            return js[1][1]
        return None
    except Exception as e:
        print(f"[WARN] Wayback query failed for {url}: {e}", file=sys.stderr)
        return None

def fetch_wayback(url: str, target: date) -> Optional[bytes]:
    for flex in (7, 30, 90, 180):
        ts = find_wayback_timestamp(url, target, flex)
        if ts:
            snap = WAYBACK_FETCH.format(timestamp=ts, url=url)
            try:
                rr = requests.get(snap, headers=HEADERS, timeout=30)
                rr.raise_for_status()
                return rr.content
            except Exception as e:
                print(f"[WARN] Wayback fetch failed for {url} @ {ts}: {e}", file=sys.stderr)
    return None

def parse_finviz_holdings(html: bytes) -> pd.DataFrame:
    """
    Parse the 'Top Holdings' table from a Finviz ETF quote page.
    Returns DataFrame with columns: Ticker, WeightPct (float).
    """
    soup = BeautifulSoup(html, "html.parser")

    # Find a section with "Top Holdings" title
    # Finviz often uses table blocks; we'll search by text
    heading = None
    for h in soup.find_all(text=re.compile(r"Top Holdings", re.I)):
        heading = h
        break
    if not heading:
        return pd.DataFrame(columns=["Ticker", "WeightPct"])

    # The table is typically near this heading; find the nearest table following it
    # Heuristic: find next <table> after heading
    table = None
    if hasattr(heading, 'parent'):
        nxt = heading.parent
        # climb a little, then scan subsequent elements for a table
        for _ in range(5):
            if nxt is None: break
            nxt = nxt.parent
            if nxt and nxt.find("table"):
                table = nxt.find("table")
                break
        # Fallback: global find the first table after heading
        if table is None:
            tables = soup.find_all("table")
            if tables:
                table = tables[-1]  # heuristic fallback

    if table is None:
        return pd.DataFrame(columns=["Ticker","WeightPct"])

    rows = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        # Usually first cell has holding name/ticker link; scan for ticker-like strings
        text_all = " ".join(td.get_text(" ", strip=True) for td in tds)
        # extract ticker-like token
        tickers = re.findall(r"\b[A-Z]{1,5}(\.[A-Z])?\b", text_all)
        ticker = None
        if tickers:
            # re.findall returned groups; flatten
            # quick approach: recompute compact tickers by matching pattern without group
            m = re.search(r"\b([A-Z]{1,5}(?:\.[A-Z])?)\b", text_all)
            if m:
                ticker = m.group(1)

        # find weight as a percent number
        m2 = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", text_all)
        weight = None
        if m2:
            weight = float(m2.group(1))

        if ticker and (weight is not None):
            rows.append([ticker, weight])

    df = pd.DataFrame(rows, columns=["Ticker","WeightPct"]).drop_duplicates(subset=["Ticker"])
    return df

def screener_fetch_etfs(filters: str, max_pages: int = 50) -> List[str]:
    """
    Use Finviz screener to fetch ETF tickers based on filter string (f=...).
    We'll page through results (20 per page) until no more results or max_pages.
    """
    all_tickers = []
    page = 1
    while page <= max_pages:
        params = {
            "v": "111",           # ticker view
            "f": filters,
            "r": str(1 + (page-1)*20)  # start row: 1,21,41,...
        }
        try:
            r = requests.get(SCREENER_URL, params=params, headers=HEADERS, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print(f"[WARN] Screener fetch failed on page {page}: {e}", file=sys.stderr)
            break

        soup = BeautifulSoup(r.content, "html.parser")
        # Find all quote links ? e.g., <a href="quote.ashx?t=QQQ"...>
        tickers = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = re.search(r"quote\.ashx\?t=([A-Z0-9\.\-]+)", href, re.I)
            if m:
                tick = m.group(1).upper()
                if tick not in tickers:
                    tickers.append(tick)

        # Remove duplicates and already seen
        new = [t for t in tickers if t not in all_tickers]
        if not new:
            break

        all_tickers.extend(new)
        page += 1

    return all_tickers

def compute_adds(prev_df: pd.DataFrame, curr_df: pd.DataFrame) -> pd.DataFrame:
    prev = prev_df.groupby("Ticker", as_index=False)["WeightPct"].sum().rename(columns={"WeightPct":"PrevWeightPct"})
    curr = curr_df.groupby("Ticker", as_index=False)["WeightPct"].sum().rename(columns={"WeightPct":"CurrWeightPct"})
    merged = pd.merge(curr, prev, on="Ticker", how="left")
    merged["PrevWeightPct"] = merged["PrevWeightPct"].fillna(0.0)
    merged["DeltaWeightPct"] = merged["CurrWeightPct"] - merged["PrevWeightPct"]
    adds = merged[merged["DeltaWeightPct"] > 0].copy()
    adds.sort_values("DeltaWeightPct", ascending=False, inplace=True)
    return adds[["Ticker","PrevWeightPct","CurrWeightPct","DeltaWeightPct"]]

def run(filters: str, since: date, out_dir: Path, top_k: int, min_delta: float):
    out_dir.mkdir(parents=True, exist_ok=True)
    details_dir = out_dir / "details"
    details_dir.mkdir(parents=True, exist_ok=True)

    tickers = screener_fetch_etfs(filters)
    if not tickers:
        print("[INFO] No ETFs found for given filters.")
        return

    summary_rows = []
    log_lines = []

    for etf in tickers:
        url = QUOTE_URL.format(ticker=etf)
        print(f"[INFO] Processing {etf} ...")

        try:
            rc = requests.get(url, headers=HEADERS, timeout=30)
            rc.raise_for_status()
            curr_df = parse_finviz_holdings(rc.content)
        except Exception as e:
            msg = f"[WARN] Failed to fetch/parse current page for {etf}: {e}"
            print(msg)
            log_lines.append(msg)
            continue

        if curr_df.empty:
            msg = f"[WARN] No holdings found on current Finviz page for {etf}."
            print(msg)
            log_lines.append(msg)
            continue

        prior_bytes = fetch_wayback(url, since)
        if prior_bytes is None:
            msg = f"[WARN] No prior snapshot found for {etf} near {since}."
            print(msg)
            log_lines.append(msg)
            continue

        try:
            prev_df = parse_finviz_holdings(prior_bytes)
        except Exception as e:
            msg = f"[WARN] Failed to parse historical page for {etf}: {e}"
            print(msg)
            log_lines.append(msg)
            continue

        adds_df = compute_adds(prev_df, curr_df)
        if min_delta > 0:
            adds_df = adds_df[adds_df["DeltaWeightPct"] >= min_delta]

        # Save full details
        adds_df.to_csv(details_dir / f"{etf}_adds.csv", index=False)

        # Top-K
        topk = adds_df.head(top_k)
        for _, r in topk.iterrows():
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
    (out_dir / "log.txt").write_text("\n".join(log_lines) if log_lines else "OK\n", encoding="utf-8")

def parse_args():
    ap = argparse.ArgumentParser(description="Use Finviz ETF screener to find ETFs, compare Top Holdings vs ~1 month ago via Wayback, and list top adds.")
    ap.add_argument("--filters", type=str, required=True, help="Comma-separated Finviz filter string (e.g. 'ind_exchangetradedfund,geo_usa,ta_highlow52w_nh')")
    ap.add_argument("--since", type=str, default=None, help="Baseline date YYYY-MM-DD (default: 30 days ago)")
    ap.add_argument("--out", type=str, default="out_finviz_adds")
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--min-delta", type=float, default=0.0)
    return ap.parse_args()

if __name__ == "__main__":
    args = parse_args()
    today = date.today()
    since = datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else (today - timedelta(days=30))
    run(args.filters, since, Path(args.out), args.top_k, args.min_delta)
