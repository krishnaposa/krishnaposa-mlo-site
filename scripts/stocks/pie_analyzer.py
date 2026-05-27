"""
Momentum Rotation System
------------------------

This script:
1. Downloads stock data using yfinance
2. Calculates:
   - 20 DMA
   - 50 DMA
   - Relative Strength vs QQQ
   - Volume confirmation
3. Generates:
   - BUY
   - HOLD
   - REDUCE
   - SELL

Install:
pip install yfinance pandas numpy

Run (from scripts/stocks):
python pie_analyzer.py
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ============================================================
# CONFIG
# ============================================================

MOMENTUM_PIE = [
    "LUNR",
    "MXL",
    "STX",
    "AGX",
    "WDC",
    "RKLB",
    "COHR",
    "IONQ",
    "ALAB",
    "FLEX",
    "LITE",
    "MPWR",
    "SNDK",
    "NBIS",
    "RGTI",
    "QBTS",
    "MRVL",
    "DOCN",
    "BAND",
    "AXTI",
    "APP",
    "RDDT"
]

BENCHMARK = "QQQ"

LOOKBACK_DAYS = 180

# ============================================================
# DOWNLOAD DATA
# ============================================================

end_date = datetime.today()
start_date = end_date - timedelta(days=LOOKBACK_DAYS)

all_tickers = MOMENTUM_PIE + [BENCHMARK]

data = yf.download(
    all_tickers,
    start=start_date,
    end=end_date,
    auto_adjust=True,
    progress=False
)

close_df = data["Close"]
volume_df = data["Volume"]

benchmark_close = close_df[BENCHMARK]

results = []

# ============================================================
# ANALYSIS
# ============================================================

for ticker in MOMENTUM_PIE:

    try:
        df = pd.DataFrame({
            "Close": close_df[ticker],
            "Volume": volume_df[ticker]
        }).dropna()

        if len(df) < 60:
            continue

        # Moving averages
        df["DMA20"] = df["Close"].rolling(20).mean()
        df["DMA50"] = df["Close"].rolling(50).mean()

        # Relative Strength vs QQQ
        rs = df["Close"].pct_change(20) - benchmark_close.pct_change(20)
        df["RS"] = rs

        # Average volume
        df["AvgVolume20"] = df["Volume"].rolling(20).mean()

        latest = df.iloc[-1]
        prev1 = df.iloc[-2]

        price = latest["Close"]
        dma20 = latest["DMA20"]
        dma50 = latest["DMA50"]

        rs_value = latest["RS"]

        volume_ratio = latest["Volume"] / latest["AvgVolume20"]

        # ====================================================
        # SIGNAL LOGIC
        # ====================================================

        signal = "HOLD"

        # Strong bullish
        if (
            price > dma20 > dma50
            and rs_value > 0
            and volume_ratio > 1.0
        ):
            signal = "BUY"

        # Weakening momentum
        elif (
            price < dma20
            and prev1["Close"] < prev1["DMA20"]
        ):
            signal = "REDUCE"

        # Major trend breakdown
        if (
            price < dma50
            and dma20 < dma50
        ):
            signal = "SELL"

        # ====================================================
        # SCORE
        # ====================================================

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
            "Signal": signal
        })

    except Exception as e:
        print(f"Error processing {ticker}: {e}")

# ============================================================
# OUTPUT
# ============================================================

results_df = pd.DataFrame(results)

results_df = results_df.sort_values(
    by=["Score", "RS_vs_QQQ"],
    ascending=False
)

print("\n")
print("=" * 90)
print(" MOMENTUM ROTATION DASHBOARD ")
print("=" * 90)

if results_df.empty:
    print("No results (check tickers or Yahoo data).")
else:
    print(results_df.to_string(index=False))

print("\n")

# ============================================================
# ROTATION IDEAS
# ============================================================

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