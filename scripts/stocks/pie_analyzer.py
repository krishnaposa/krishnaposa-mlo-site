"""
Momentum Rotation System
------------------------

Reads tickers from my_tickers.txt (or --tickers-file), then:
1. Downloads stock data using yfinance
2. Calculates 20/50 DMA, RS vs QQQ, volume confirmation
3. Signals: BUY, HOLD, REDUCE, SELL

Install:
pip install yfinance pandas numpy

Run (from scripts/stocks):
python pie_analyzer.py
python pie_analyzer.py --tickers-file my_tickers.txt
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from stocks_common import read_symbols_from_file

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TICKERS_FILE = SCRIPT_DIR / "my_tickers.txt"

BENCHMARK = "QQQ"
LOOKBACK_DAYS = 180


def main() -> None:
    parser = argparse.ArgumentParser(description="Momentum rotation dashboard vs QQQ.")
    parser.add_argument(
        "--tickers-file",
        default=str(DEFAULT_TICKERS_FILE),
        help=f"Ticker list file (default: {DEFAULT_TICKERS_FILE.name}).",
    )
    args = parser.parse_args()

    tickers = read_symbols_from_file(args.tickers_file)
    if not tickers:
        raise SystemExit(f"No tickers in {args.tickers_file}")

    print(f"Loaded {len(tickers)} symbol(s) from {args.tickers_file}")

    end_date = datetime.today()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)
    all_tickers = tickers + [BENCHMARK]

    data = yf.download(
        all_tickers,
        start=start_date,
        end=end_date,
        auto_adjust=True,
        progress=False,
    )

    close_df = data["Close"]
    volume_df = data["Volume"]
    benchmark_close = close_df[BENCHMARK]

    results = []

    for ticker in tickers:
        try:
            df = pd.DataFrame({
                "Close": close_df[ticker],
                "Volume": volume_df[ticker],
            }).dropna()

            if len(df) < 60:
                continue

            df["DMA20"] = df["Close"].rolling(20).mean()
            df["DMA50"] = df["Close"].rolling(50).mean()
            rs = df["Close"].pct_change(20) - benchmark_close.pct_change(20)
            df["RS"] = rs
            df["AvgVolume20"] = df["Volume"].rolling(20).mean()

            latest = df.iloc[-1]
            prev1 = df.iloc[-2]

            price = latest["Close"]
            dma20 = latest["DMA20"]
            dma50 = latest["DMA50"]
            rs_value = latest["RS"]
            volume_ratio = latest["Volume"] / latest["AvgVolume20"]

            signal = "HOLD"

            if price > dma20 > dma50 and rs_value > 0 and volume_ratio > 1.0:
                signal = "BUY"
            elif price < dma20 and prev1["Close"] < prev1["DMA20"]:
                signal = "REDUCE"

            if price < dma50 and dma20 < dma50:
                signal = "SELL"

            score = 0
            if price > dma20:
                score += 1
            if price > dma50:
                score += 1
            if dma20 > dma50:
                score += 1
            if rs_value > 0:
                score += 1
            if volume_ratio > 1:
                score += 1

            results.append({
                "Ticker": ticker,
                "Price": round(price, 2),
                "20DMA": round(dma20, 2),
                "50DMA": round(dma50, 2),
                "RS_vs_QQQ": round(rs_value * 100, 2),
                "Vol_Ratio": round(volume_ratio, 2),
                "Score": score,
                "Signal": signal,
            })

        except Exception as e:
            print(f"Error processing {ticker}: {e}")

    results_df = pd.DataFrame(results)
    if not results_df.empty:
        results_df = results_df.sort_values(by=["Score", "RS_vs_QQQ"], ascending=False)

    print("\n")
    print("=" * 90)
    print(" MOMENTUM ROTATION DASHBOARD ")
    print("=" * 90)

    if results_df.empty:
        print("No results (check tickers or Yahoo data).")
    else:
        print(results_df.to_string(index=False))

    print("\n")

    if results_df.empty:
        print("Done.")
        return

    buy_list = results_df[results_df["Signal"] == "BUY"]["Ticker"].tolist()
    sell_list = results_df[results_df["Signal"] == "SELL"]["Ticker"].tolist()
    reduce_list = results_df[results_df["Signal"] == "REDUCE"]["Ticker"].tolist()

    print("BUY / ADD CANDIDATES:")
    print(buy_list)
    print("\nREDUCE EXPOSURE:")
    print(reduce_list)
    print("\nEXIT / ROTATE OUT:")
    print(sell_list)
    print("\nDone.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
