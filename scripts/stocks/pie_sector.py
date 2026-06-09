"""
Advanced Momentum Rotation System
---------------------------------

Reads tickers from my_tickers.txt and sectors from pie_sector_map.txt.

Adds relative strength ranking, sector momentum, composite score, rotation signals.

Install:
pip install yfinance pandas numpy

Run (from scripts/stocks):
python pie_sector.py
python pie_sector.py --tickers-file my_tickers.txt --sector-map pie_sector_map.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from stocks_common import is_valid_symbol, normalize_symbol, read_symbols_from_file

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TICKERS_FILE = SCRIPT_DIR / "my_tickers.txt"
DEFAULT_SECTOR_MAP_FILE = SCRIPT_DIR / "pie_sector_map.txt"

BENCHMARK = "QQQ"
LOOKBACK_DAYS = 250
TOP_N = 8
DEFAULT_SECTOR = "OTHER"


def load_sector_map(path: str) -> dict[str, str]:
    """
    Load ticker→sector from pie_sector_map.txt.

    Expected line format::

        AI_SEMI=ALAB, MRVL, COHR

    (sector name left of ``=``, comma/space-separated tickers on the right).
    """
    path_exp = Path(path).expanduser()
    if not path_exp.is_file():
        raise FileNotFoundError(f"Sector map not found: {path}")

    sector_map: dict[str, str] = {}
    with path_exp.open(encoding="utf-8", errors="replace") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.split("#", 1)[0].strip()
            if not line or "=" not in line:
                continue
            sector_part, tickers_part = line.split("=", 1)
            sector = sector_part.strip().upper()
            if not sector:
                continue
            for part in re.split(r"[,;\s]+", tickers_part.strip()):
                part = part.strip()
                if not part:
                    continue
                ticker = normalize_symbol(part)
                if not is_valid_symbol(ticker):
                    continue
                if ticker in sector_map and sector_map[ticker] != sector:
                    print(
                        f"Warning: {path_exp.name}:{line_no} — {ticker} "
                        f"already mapped to {sector_map[ticker]}; keeping first assignment"
                    )
                    continue
                sector_map[ticker] = sector
    return sector_map


def build_stocks_with_sectors(
    tickers: list[str],
    sector_map: dict[str, str],
    *,
    default_sector: str = DEFAULT_SECTOR,
) -> dict[str, str]:
    """Join watchlist tickers with sector map; unmapped tickers use default_sector."""
    return {t: sector_map.get(t, default_sector) for t in tickers}


def signal_label(score: float) -> str:
    if score >= 160:
        return "STRONG BUY"
    if score >= 120:
        return "BUY"
    if score >= 80:
        return "HOLD"
    if score >= 50:
        return "REDUCE"
    return "SELL"


def main() -> None:
    parser = argparse.ArgumentParser(description="Sector momentum rotation vs QQQ.")
    parser.add_argument(
        "--tickers-file",
        default=str(DEFAULT_TICKERS_FILE),
        help=f"Ticker list file (default: {DEFAULT_TICKERS_FILE.name}).",
    )
    parser.add_argument(
        "--sector-map",
        default=str(DEFAULT_SECTOR_MAP_FILE),
        help=f"Sector map file SECTOR=TICKER,... (default: {DEFAULT_SECTOR_MAP_FILE.name}).",
    )
    args = parser.parse_args()

    tickers = read_symbols_from_file(args.tickers_file)
    if not tickers:
        raise SystemExit(f"No tickers in {args.tickers_file}")

    sector_map = load_sector_map(args.sector_map)
    stocks = build_stocks_with_sectors(tickers, sector_map)

    unmapped = [t for t in tickers if t not in sector_map]
    print(f"Loaded {len(tickers)} symbol(s) from {args.tickers_file}")
    print(f"Sector map: {len(sector_map)} entries from {args.sector_map}")
    if unmapped:
        print(
            f"  {len(unmapped)} without map → {DEFAULT_SECTOR}: "
            + ", ".join(unmapped[:12])
            + (" …" if len(unmapped) > 12 else "")
        )

    end_date = datetime.today()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)
    tickers = list(stocks.keys()) + [BENCHMARK]

    data = yf.download(
        tickers,
        start=start_date,
        end=end_date,
        auto_adjust=True,
        progress=False,
    )

    close_df = data["Close"]
    volume_df = data["Volume"]
    benchmark = close_df[BENCHMARK]

    results = []

    for ticker, sector in stocks.items():
        try:
            df = pd.DataFrame({
                "Close": close_df[ticker],
                "Volume": volume_df[ticker],
            }).dropna()

            if len(df) < 60:
                continue

            df["DMA20"] = df["Close"].rolling(20).mean()
            df["DMA50"] = df["Close"].rolling(50).mean()
            df["Ret_20"] = df["Close"].pct_change(20)
            df["Ret_50"] = df["Close"].pct_change(50)

            qqq_20 = benchmark.pct_change(20)
            qqq_50 = benchmark.pct_change(50)
            df["RS_20"] = df["Ret_20"] - qqq_20
            df["RS_50"] = df["Ret_50"] - qqq_50

            df["Vol20"] = df["Volume"].rolling(20).mean()
            df["Vol_Ratio"] = df["Volume"] / df["Vol20"]

            latest = df.iloc[-1]
            price = latest["Close"]
            dma20 = latest["DMA20"]
            dma50 = latest["DMA50"]
            rs20 = latest["RS_20"]
            rs50 = latest["RS_50"]
            vol_ratio = latest["Vol_Ratio"]

            trend_score = 0
            if price > dma20:
                trend_score += 1
            if price > dma50:
                trend_score += 1
            if dma20 > dma50:
                trend_score += 1

            rs_score = 0
            if rs20 > 0:
                rs_score += 1
            if rs50 > 0:
                rs_score += 1

            vol_score = 1 if vol_ratio > 1 else 0
            total_score = trend_score * 40 + rs_score * 40 + vol_score * 20

            results.append({
                "Ticker": ticker,
                "Sector": sector,
                "Price": round(price, 2),
                "RS20": round(rs20 * 100, 2),
                "RS50": round(rs50 * 100, 2),
                "TrendScore": trend_score,
                "RSScore": rs_score,
                "VolScore": vol_score,
                "TotalScore": total_score,
            })

        except Exception as e:
            print(f"Error: {ticker} -> {e}")

    results_df = pd.DataFrame(results)
    if results_df.empty:
        print("\nNo results (check tickers or Yahoo data).")
        print("Done.")
        return

    sector_scores = (
        results_df.groupby("Sector")["TotalScore"]
        .mean()
        .sort_values(ascending=False)
    )
    results_df["SectorMomentum"] = results_df["Sector"].map(sector_scores.to_dict())
    results_df["CompositeScore"] = (
        results_df["TotalScore"] * 0.7 + results_df["SectorMomentum"] * 0.3
    )
    results_df = results_df.sort_values(by="CompositeScore", ascending=False)
    results_df["Signal"] = results_df["CompositeScore"].apply(signal_label)

    print("\n")
    print("=" * 120)
    print(" ADVANCED MOMENTUM ROTATION SYSTEM ")
    print("=" * 120)

    display_cols = [
        "Ticker", "Sector", "RS20", "RS50", "TrendScore",
        "SectorMomentum", "CompositeScore", "Signal",
    ]
    print(results_df[display_cols].to_string(index=False))

    print("\n")
    print("=" * 80)
    print(" TOP ROTATION TARGETS ")
    print("=" * 80)
    top_buys = results_df[results_df["Signal"].isin(["STRONG BUY", "BUY"])]
    print(top_buys[["Ticker", "Sector", "CompositeScore"]].to_string(index=False))

    print("\n")
    print("=" * 80)
    print(" WEAKENING / ROTATE OUT ")
    print("=" * 80)
    weak = results_df[results_df["Signal"].isin(["REDUCE", "SELL"])]
    print(weak[["Ticker", "Sector", "CompositeScore"]].to_string(index=False))

    print("\n")
    print("=" * 80)
    print(f" SUGGESTED TOP {TOP_N} MOMENTUM HOLDINGS ")
    print("=" * 80)
    top_positions = results_df.head(TOP_N)
    equal_weight = round(100 / TOP_N, 2)
    for _, row in top_positions.iterrows():
        print(
            f"{row['Ticker']:6} "
            f" | Sector: {row['Sector']:10} "
            f" | Weight: {equal_weight}% "
            f" | Score: {round(row['CompositeScore'], 2)}"
        )

    print("\nDone.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
