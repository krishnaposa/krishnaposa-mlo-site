#!/usr/bin/env python3
"""
ETF Top Adds Scanner
====================

Purpose
-------
Given two snapshots of ETF holdings (previous and current), find the top 2–3 stocks
per ETF that the fund has **recently increased** (by weight). Outputs a summary table,
per-ETF detail CSVs, and an Excel workbook with one sheet per ETF.

Snapshot Input Model
--------------------
- You provide TWO folders:
    1) PREV: previous holdings CSVs (one file per ETF)
    2) CURR: current holdings CSVs (one file per ETF)

- Each folder must contain one CSV per ETF. Filenames should include an identifiable
  ETF name (e.g., "QQQ_holdings.csv", "ARKK_2025-09-15.csv"). The script uses the
  filename stem (without extension) as the ETF label by default, unless you override
  with --etf-label-from-column.

- Each CSV must contain at least:
    * Ticker column (any of: 'ticker','Ticker','Symbol','Holding Ticker','Asset')
    * Weight column (any of: 'weight','Weight','% Weight','Weight %','Portfolio Weight')

  Weights can be in percent (e.g., 3.25) or fraction (e.g., 0.0325). The script will
  auto-normalize to PERCENT (0–100 scale).

Optional Instrument Master
--------------------------
You may pass an optional CSV with columns to filter for tradability:
  - 'Ticker' (or 'Symbol')
  - optionally: 'Price', 'AvgVol' (average daily volume)
If provided, you can enable --min-price and --min-avgvol thresholds.

Outputs
-------
- out/summary_top_adds.csv            : Top 2–3 adds per ETF (ranked by delta weight)
- out/details/<ETF_LABEL>_adds.csv    : Full adds for each ETF with delta weight
- out/etf_top_adds.xlsx               : Excel with one sheet per ETF (adds sorted by delta)
- out/log.txt                         : Processing log & any warnings

Usage
-----
python etf_top_adds.py \
  --prev ./prev_holdings \
  --curr ./curr_holdings \
  --out ./out \
  --top-k 3 \
  --min-delta 0.02 \
  --instrument-master ./instrument_master.csv \
  --min-price 5 \
  --min-avgvol 400000

Notes
-----
- "min-delta" is in PERCENT points (e.g., 0.02 = +0.02 percentage points).
- If both snapshots are present but tickers are renamed or delisted, those will be
  treated as new additions if not found in PREV.
- If a PREV ETF file is missing, the script will still produce "new" adds from CURR.
- This script does **no** web requests; it relies solely on your CSV snapshots.
"""

import argparse
import os
from pathlib import Path
import sys
import re
import pandas as pd

# -------------------------
# Helpers
# -------------------------

TICKER_CANDIDATES = ['ticker','symbol','holding ticker','asset','holding','security','name']
WEIGHT_CANDIDATES = ['weight','% weight','weight %','portfolio weight','percent','%']

def _normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase columns and strip spaces for matching, but keep original for data."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df

def _find_col(df: pd.DataFrame, candidates) -> str:
    lower_map = {c.lower(): c for c in df.columns}
    for cand in candidates:
        for col_lower, col_orig in lower_map.items():
            if cand == col_lower:
                return col_orig
    # fuzzy: contains cand
    for cand in candidates:
        pat = re.compile(r'\b' + re.escape(cand) + r'\b', re.IGNORECASE)
        for col in df.columns:
            if pat.search(col):
                return col
    return None

def _ensure_percent(weight_series: pd.Series) -> pd.Series:
    """If weights look like 0–1, convert to 0–100. If already 0–100, leave as-is."""
    s = pd.to_numeric(weight_series, errors='coerce')
    # Heuristic: if median <= 1.5, assume fractional; else percent
    med = s.median(skipna=True)
    if pd.notna(med) and med <= 1.5:
        return s * 100.0
    return s

def _read_holdings_csv(path: Path, log) -> pd.DataFrame:
    try:
        df = pd.read_csv(path)
    except Exception as e:
        log.append(f"[ERROR] Failed to read {path}: {e}")
        return pd.DataFrame()

    if df.empty:
        log.append(f"[WARN] Empty file: {path}")
        return df

    df = _normalize_cols(df)

    tcol = _find_col(df, TICKER_CANDIDATES)
    wcol = _find_col(df, WEIGHT_CANDIDATES)

    if tcol is None or wcol is None:
        log.append(f"[ERROR] Missing required columns in {path}. Found cols: {list(df.columns)}")
        return pd.DataFrame()

    out = pd.DataFrame({
        'Ticker': df[tcol].astype(str).str.upper().str.strip(),
        'WeightPct': _ensure_percent(df[wcol])
    })
    out = out.dropna(subset=['Ticker','WeightPct'])
    out['Ticker'] = out['Ticker'].str.replace(r'[^A-Z0-9\.\-]', '', regex=True)
    return out

def _etf_label_from_filename(path: Path) -> str:
    stem = path.stem
    # strip trivial suffixes like "_holdings", dates, etc.
    stem = re.sub(r'(_holdings?|_positions?)$', '', stem, flags=re.IGNORECASE)
    return stem

def _load_instrument_master(path: Path, log) -> pd.DataFrame:
    try:
        df = pd.read_csv(path)
        if df.empty:
            log.append(f"[WARN] Instrument master is empty: {path}")
            return pd.DataFrame()
        df = _normalize_cols(df)
        tcol = _find_col(df, ['ticker','symbol'])
        if tcol is None:
            log.append(f"[ERROR] Instrument master missing Ticker/Symbol column.")
            return pd.DataFrame()
        out = df.copy()
        out.rename(columns={tcol:'Ticker'}, inplace=True)
        out['Ticker'] = out['Ticker'].astype(str).str.upper().str.strip()
        return out
    except Exception as e:
        log.append(f"[ERROR] Failed to read instrument master {path}: {e}")
        return pd.DataFrame()

# -------------------------
# Core logic
# -------------------------

def compute_top_adds(prev_df: pd.DataFrame, curr_df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns a DataFrame with columns: Ticker, PrevWeightPct, CurrWeightPct, DeltaWeightPct,
    filtered to rows with Delta > 0, sorted desc by Delta.
    """
    prev = prev_df.groupby('Ticker', as_index=False)['WeightPct'].sum().rename(columns={'WeightPct':'PrevWeightPct'})
    curr = curr_df.groupby('Ticker', as_index=False)['WeightPct'].sum().rename(columns={'WeightPct':'CurrWeightPct'})
    merged = pd.merge(curr, prev, on='Ticker', how='left')
    merged['PrevWeightPct'] = merged['PrevWeightPct'].fillna(0.0)
    merged['DeltaWeightPct'] = merged['CurrWeightPct'] - merged['PrevWeightPct']
    adds = merged[merged['DeltaWeightPct'] > 0].copy()
    adds.sort_values('DeltaWeightPct', ascending=False, inplace=True)
    return adds[['Ticker','PrevWeightPct','CurrWeightPct','DeltaWeightPct']]

def main():
    parser = argparse.ArgumentParser(description="Find top 2–3 stock adds per ETF based on weight changes.")
    parser.add_argument('--prev', required=True, help='Folder with previous ETF holdings CSVs')
    parser.add_argument('--curr', required=True, help='Folder with current ETF holdings CSVs')
    parser.add_argument('--out', default='./out', help='Output folder (default: ./out)')
    parser.add_argument('--top-k', type=int, default=3, help='Top K adds per ETF (default: 3)')
    parser.add_argument('--min-delta', type=float, default=0.0, help='Minimum delta in PERCENT points to include (e.g., 0.02 = +0.02pp)')
    parser.add_argument('--instrument-master', default=None, help='Optional instrument master CSV')
    parser.add_argument('--min-price', type=float, default=None, help='Min price filter (requires instrument master with Price column)')
    parser.add_argument('--min-avgvol', type=float, default=None, help='Min average volume filter (requires instrument master with AvgVol column)')
    parser.add_argument('--etf-label-from-column', default=None, help='Optional column name in CSVs to use as ETF label (must exist in both prev & curr files)')

    args = parser.parse_args()

    prev_dir = Path(args.prev)
    curr_dir = Path(args.curr)
    out_dir = Path(args.out)
    details_dir = out_dir / 'details'
    out_dir.mkdir(parents=True, exist_ok=True)
    details_dir.mkdir(parents=True, exist_ok=True)

    log = []
    master_df = None
    if args.instrument_master:
        master_df = _load_instrument_master(Path(args.instrument_master), log)
        if master_df.empty:
            master_df = None

    # Map ETF label -> (prev_path, curr_path)
    # We'll match by filename stem ignoring extensions; if an ETF exists only in CURR, we'll still process.
    def index_dir(d: Path):
        files = {}
        for p in d.glob('*.csv'):
            files[_etf_label_from_filename(p).lower()] = p
        return files

    prev_map = index_dir(prev_dir)
    curr_map = index_dir(curr_dir)

    # Union of ETF keys
    etf_keys = sorted(set(prev_map.keys()) | set(curr_map.keys()))

    all_summary_rows = []
    writer = None
    try:
        writer = pd.ExcelWriter(out_dir / 'etf_top_adds.xlsx', engine='xlsxwriter')
    except Exception as e:
        log.append(f"[WARN] Could not open Excel writer: {e}")

    for key in etf_keys:
        prev_path = prev_map.get(key, None)
        curr_path = curr_map.get(key, None)

        if curr_path is None:
            log.append(f"[WARN] Skipping {key}: missing CURRENT file")
            continue

        curr_df = _read_holdings_csv(curr_path, log)
        if curr_df.empty:
            log.append(f"[WARN] Skipping {key}: current holdings empty or invalid")
            continue

        if prev_path is not None:
            prev_df = _read_holdings_csv(prev_path, log)
        else:
            prev_df = pd.DataFrame(columns=['Ticker','WeightPct'])

        adds_df = compute_top_adds(prev_df, curr_df)

        # Liquidity filters if master provided
        if master_df is not None and not adds_df.empty:
            adds_df = adds_df.merge(master_df, on='Ticker', how='left')
            if args.min_price is not None and 'Price' in adds_df.columns:
                adds_df = adds_df[(adds_df['Price'] >= args.min_price) | (adds_df['Price'].isna())]
            if args.min_avgvol is not None:
                av_cols = [c for c in adds_df.columns if c.lower() in ('avgvol','averagevolume','avg_volume','avg_vol')]
                if av_cols:
                    avc = av_cols[0]
                    adds_df = adds_df[(adds_df[avc] >= args.min_avgvol) | (adds_df[avc].isna())]

        # Apply min delta
        if args.min_delta is not None and args.min_delta > 0:
            adds_df = adds_df[adds_df['DeltaWeightPct'] >= args.min_delta]

        # Rank and take top-k
        adds_df = adds_df.sort_values('DeltaWeightPct', ascending=False)
        topk_df = adds_df.head(args.top_k).copy()

        # Save details
        etf_label = key.upper()
        detail_path = details_dir / f"{etf_label}_adds.csv"
        adds_df.to_csv(detail_path, index=False)

        # Write to Excel (if available)
        if writer is not None:
            sheet_name = re.sub(r'[^A-Za-z0-9]', '_', etf_label)[:31]
            try:
                adds_df.to_excel(writer, index=False, sheet_name=sheet_name)
            except Exception as e:
                log.append(f"[WARN] Excel sheet write failed for {etf_label}: {e}")

        # Append to summary
        for _, row in topk_df.iterrows():
            all_summary_rows.append({
                'ETF': etf_label,
                'Ticker': row['Ticker'],
                'PrevWeightPct': round(float(row['PrevWeightPct']), 6) if pd.notna(row['PrevWeightPct']) else None,
                'CurrWeightPct': round(float(row['CurrWeightPct']), 6) if pd.notna(row['CurrWeightPct']) else None,
                'DeltaWeightPct': round(float(row['DeltaWeightPct']), 6) if pd.notna(row['DeltaWeightPct']) else None
            })

    # Write summary
    if all_summary_rows:
        summary_df = pd.DataFrame(all_summary_rows)
        summary_df = summary_df.sort_values(['ETF','DeltaWeightPct'], ascending=[True, False])
        summary_df.to_csv(out_dir / 'summary_top_adds.csv', index=False)
    else:
        log.append("[INFO] No adds found that meet the criteria.")

    # Close Excel
    if writer is not None:
        try:
            writer.close()
        except Exception as e:
            log.append(f"[WARN] Failed to finalize Excel workbook: {e}")

    # Write log
    with open(out_dir / 'log.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(log) if log else "OK\n")

if __name__ == "__main__":
    main()