"""
Momentum Rotation System
------------------------

Reads tickers from my_tickers.txt (or --tickers-file), then:
1. Downloads stock data using yfinance
2. Calculates:
   - 5 DMA
   - 10 DMA
   - 20 DMA
   - 50 DMA
   - Relative Strength vs QQQ
   - Volume confirmation
3. Signals:
   - BUY
   - WATCH
   - HOLD
   - REDUCE
   - SELL

Install:
pip install yfinance pandas numpy

Run:
python pie_analyzer.py
python pie_analyzer.py --tickers-file my_tickers.txt
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from stocks_common import read_symbols_from_file

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TICKERS_FILE = SCRIPT_DIR / "my_tickers.txt"

BENCHMARK = "QQQ"
LOOKBACK_DAYS = 180


def main() -> None:

    parser = argparse.ArgumentParser(
        description="Momentum rotation dashboard vs QQQ."
    )

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

    # =========================================================
    # DATE RANGE
    # =========================================================

    end_date = datetime.today()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)

    all_tickers = tickers + [BENCHMARK]

    # =========================================================
    # DOWNLOAD DATA
    # =========================================================

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

    # =========================================================
    # ANALYZE EACH STOCK
    # =========================================================

    for ticker in tickers:

        try:

            df = pd.DataFrame({
                "Close": close_df[ticker],
                "Volume": volume_df[ticker],
            }).dropna()

            if len(df) < 60:
                continue

            # -------------------------------------------------
            # Moving averages
            # -------------------------------------------------

            df["DMA5"] = df["Close"].rolling(5).mean()
            df["DMA10"] = df["Close"].rolling(10).mean()
            df["DMA20"] = df["Close"].rolling(20).mean()
            df["DMA50"] = df["Close"].rolling(50).mean()

            # -------------------------------------------------
            # Relative Strength vs QQQ
            # -------------------------------------------------

            rs = (
                df["Close"].pct_change(20)
                - benchmark_close.pct_change(20)
            )

            df["RS"] = rs

            # -------------------------------------------------
            # Volume
            # -------------------------------------------------

            df["AvgVolume20"] = df["Volume"].rolling(20).mean()

            # -------------------------------------------------
            # Latest rows
            # -------------------------------------------------

            latest = df.iloc[-1]
            prev1 = df.iloc[-2]

            # -------------------------------------------------
            # Prices / averages
            # -------------------------------------------------

            price = latest["Close"]

            dma5 = latest["DMA5"]
            dma10 = latest["DMA10"]
            dma20 = latest["DMA20"]
            dma50 = latest["DMA50"]

            rs_value = latest["RS"]

            volume_ratio = (
                latest["Volume"] / latest["AvgVolume20"]
            )

            # -------------------------------------------------
            # Trend structure
            # -------------------------------------------------

            bullish_stack = (
                price > dma10 > dma20 > dma50
            )

            bearish_stack = (
                price < dma10 < dma20 < dma50
            )

            # -------------------------------------------------
            # 2-day confirmation rules
            # -------------------------------------------------

            below10_2days = (
                latest["Close"] < latest["DMA10"]
                and prev1["Close"] < prev1["DMA10"]
            )

            below20_2days = (
                latest["Close"] < latest["DMA20"]
                and prev1["Close"] < prev1["DMA20"]
            )

            # -------------------------------------------------
            # Distance from moving averages
            # -------------------------------------------------

            distance_from_10dma = (
                (price - dma10) / dma10
            ) * 100

            distance_from_20dma = (
                (price - dma20) / dma20
            ) * 100

            # -------------------------------------------------
            # SIGNAL LOGIC
            # -------------------------------------------------

            signal = "HOLD"

            # Strong momentum
            if (
                bullish_stack
                and rs_value > 0
                and volume_ratio > 1.0
            ):
                signal = "BUY"

            # Early weakness
            elif below10_2days:
                signal = "WATCH"

            # Momentum deterioration
            elif below20_2days:
                signal = "REDUCE"

            # Major trend breakdown
            if bearish_stack:
                signal = "SELL"

            # -------------------------------------------------
            # SCORING MODEL
            # -------------------------------------------------

            score = 0

            # Short-term trend
            if price > dma5:
                score += 1

            if price > dma10:
                score += 1

            # Core trend
            if price > dma20:
                score += 2

            if price > dma50:
                score += 2

            # Trend structure
            if dma10 > dma20:
                score += 2

            if dma20 > dma50:
                score += 2

            # Relative strength
            if rs_value > 0:
                score += 3

            # Institutional volume
            if volume_ratio > 1:
                score += 2

            # -------------------------------------------------
            # RESULTS
            # -------------------------------------------------

            results.append({
                "Ticker": ticker,

                "Price": round(price, 2),

                "5DMA": round(dma5, 2),
                "10DMA": round(dma10, 2),
                "20DMA": round(dma20, 2),
                "50DMA": round(dma50, 2),

                "Dist_10DMA_%": round(distance_from_10dma, 2),
                "Dist_20DMA_%": round(distance_from_20dma, 2),

                "RS_vs_QQQ_%": round(rs_value * 100, 2),

                "Vol_Ratio": round(volume_ratio, 2),

                "Score": score,

                "Signal": signal,
            })

        except Exception as e:
            print(f"Error processing {ticker}: {e}")

    # =========================================================
    # RESULTS DATAFRAME
    # =========================================================

    results_df = pd.DataFrame(results)

    if not results_df.empty:

        results_df = results_df.sort_values(
            by=["Score", "RS_vs_QQQ_%"],
            ascending=False,
        )

    # =========================================================
    # OUTPUT
    # =========================================================

    print("\n")
    print("=" * 140)
    print(" MOMENTUM ROTATION DASHBOARD ")
    print("=" * 140)

    if results_df.empty:
        print("No results (check tickers or Yahoo data).")
    else:
        print(results_df.to_string(index=False))

    print("\n")

    if results_df.empty:
        print("Done.")
        return

    # =========================================================
    # SIGNAL GROUPS
    # =========================================================

    buy_list = results_df[
        results_df["Signal"] == "BUY"
    ]["Ticker"].tolist()

    watch_list = results_df[
        results_df["Signal"] == "WATCH"
    ]["Ticker"].tolist()

    reduce_list = results_df[
        results_df["Signal"] == "REDUCE"
    ]["Ticker"].tolist()

    sell_list = results_df[
        results_df["Signal"] == "SELL"
    ]["Ticker"].tolist()

    # =========================================================
    # DISPLAY SIGNALS
    # =========================================================

    print("BUY / ADD CANDIDATES:")
    print(buy_list)

    print("\nWATCH CLOSELY:")
    print(watch_list)

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