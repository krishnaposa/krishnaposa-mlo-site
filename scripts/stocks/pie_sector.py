"""
Advanced Momentum Rotation System
---------------------------------

Adds:
1. Relative Strength Ranking
2. Sector Momentum Scoring
3. Weighted Momentum Score
4. Rotation Ranking

Install:
pip install yfinance pandas numpy tabulate

Run:
python advanced_rotation.py
"""

import yfinance as yf
import pandas as pd
import numpy as np
from tabulate import tabulate
from datetime import datetime, timedelta

# ============================================================
# CONFIG
# ============================================================

STOCKS = {
    "LUNR": "SPACE",
    "RKLB": "SPACE",

    "IONQ": "QUANTUM",
    "RGTI": "QUANTUM",
    "QBTS": "QUANTUM",

    "ALAB": "AI_SEMI",
    "MRVL": "AI_SEMI",
    "COHR": "AI_SEMI",
    "LITE": "AI_SEMI",
    "MPWR": "AI_SEMI",
    "AVGO": "AI_SEMI",

    "STX": "STORAGE",
    "WDC": "STORAGE",
    "SNDK": "STORAGE",

    "DOCN": "CLOUD",
    "BAND": "CLOUD",

    "APP": "ADTECH",
    "RDDT": "ADTECH",

    "FLEX": "INFRA",
    "AGX": "INFRA",
    "NBIS": "INFRA",
    "MXL": "NETWORK",
    "AXTI": "MATERIALS"
}

BENCHMARK = "QQQ"

LOOKBACK_DAYS = 250

# ============================================================
# DOWNLOAD DATA
# ============================================================

end_date = datetime.today()
start_date = end_date - timedelta(days=LOOKBACK_DAYS)

tickers = list(STOCKS.keys()) + [BENCHMARK]

data = yf.download(
    tickers,
    start=start_date,
    end=end_date,
    auto_adjust=True,
    progress=False
)

close_df = data["Close"]
volume_df = data["Volume"]

benchmark = close_df[BENCHMARK]

# ============================================================
# RELATIVE STRENGTH CALCULATION
# ============================================================

results = []

for ticker, sector in STOCKS.items():

    try:

        df = pd.DataFrame({
            "Close": close_df[ticker],
            "Volume": volume_df[ticker]
        }).dropna()

        if len(df) < 60:
            continue

        # ----------------------------------------------------
        # Moving averages
        # ----------------------------------------------------

        df["DMA20"] = df["Close"].rolling(20).mean()
        df["DMA50"] = df["Close"].rolling(50).mean()

        # ----------------------------------------------------
        # Momentum windows
        # ----------------------------------------------------

        df["Ret_20"] = df["Close"].pct_change(20)
        df["Ret_50"] = df["Close"].pct_change(50)

        # ----------------------------------------------------
        # Relative strength vs QQQ
        # ----------------------------------------------------

        qqq_20 = benchmark.pct_change(20)
        qqq_50 = benchmark.pct_change(50)

        df["RS_20"] = df["Ret_20"] - qqq_20
        df["RS_50"] = df["Ret_50"] - qqq_50

        # ----------------------------------------------------
        # Volume strength
        # ----------------------------------------------------

        df["Vol20"] = df["Volume"].rolling(20).mean()
        df["Vol_Ratio"] = df["Volume"] / df["Vol20"]

        latest = df.iloc[-1]

        price = latest["Close"]
        dma20 = latest["DMA20"]
        dma50 = latest["DMA50"]

        rs20 = latest["RS_20"]
        rs50 = latest["RS_50"]

        vol_ratio = latest["Vol_Ratio"]

        # ----------------------------------------------------
        # TREND SCORE
        # ----------------------------------------------------

        trend_score = 0

        if price > dma20:
            trend_score += 1

        if price > dma50:
            trend_score += 1

        if dma20 > dma50:
            trend_score += 1

        # ----------------------------------------------------
        # RELATIVE STRENGTH SCORE
        # ----------------------------------------------------

        rs_score = 0

        if rs20 > 0:
            rs_score += 1

        if rs50 > 0:
            rs_score += 1

        # ----------------------------------------------------
        # VOLUME SCORE
        # ----------------------------------------------------

        vol_score = 1 if vol_ratio > 1 else 0

        # ----------------------------------------------------
        # TOTAL SCORE
        # ----------------------------------------------------

        total_score = (
            trend_score * 40 +
            rs_score * 40 +
            vol_score * 20
        )

        results.append({
            "Ticker": ticker,
            "Sector": sector,
            "Price": round(price, 2),

            "RS20": round(rs20 * 100, 2),
            "RS50": round(rs50 * 100, 2),

            "TrendScore": trend_score,
            "RSScore": rs_score,
            "VolScore": vol_score,

            "TotalScore": total_score
        })

    except Exception as e:
        print(f"Error: {ticker} -> {e}")

# ============================================================
# DATAFRAME
# ============================================================

results_df = pd.DataFrame(results)

# ============================================================
# SECTOR MOMENTUM SCORING
# ============================================================

sector_scores = (
    results_df
    .groupby("Sector")["TotalScore"]
    .mean()
    .sort_values(ascending=False)
)

sector_score_map = sector_scores.to_dict()

results_df["SectorMomentum"] = results_df["Sector"].map(
    sector_score_map
)

# ============================================================
# FINAL COMPOSITE SCORE
# ============================================================

results_df["CompositeScore"] = (
    results_df["TotalScore"] * 0.7 +
    results_df["SectorMomentum"] * 0.3
)

results_df = results_df.sort_values(
    by="CompositeScore",
    ascending=False
)

# ============================================================
# SIGNALS
# ============================================================

def signal(score):

    if score >= 160:
        return "STRONG BUY"

    elif score >= 120:
        return "BUY"

    elif score >= 80:
        return "HOLD"

    elif score >= 50:
        return "REDUCE"

    return "SELL"


results_df["Signal"] = results_df["CompositeScore"].apply(signal)

# ============================================================
# OUTPUT
# ============================================================

print("\n")
print("=" * 120)
print(" ADVANCED MOMENTUM ROTATION SYSTEM ")
print("=" * 120)

display_cols = [
    "Ticker",
    "Sector",
    "RS20",
    "RS50",
    "TrendScore",
    "SectorMomentum",
    "CompositeScore",
    "Signal"
]

print(
    tabulate(
        results_df[display_cols],
        headers="keys",
        tablefmt="pretty",
        showindex=False
    )
)

# ============================================================
# TOP ROTATION CANDIDATES
# ============================================================

print("\n")
print("=" * 80)
print(" TOP ROTATION TARGETS ")
print("=" * 80)

top_buys = results_df[
    results_df["Signal"].isin(["STRONG BUY", "BUY"])
]

print(top_buys[["Ticker", "Sector", "CompositeScore"]])

# ============================================================
# WEAKENING POSITIONS
# ============================================================

print("\n")
print("=" * 80)
print(" WEAKENING / ROTATE OUT ")
print("=" * 80)

weak = results_df[
    results_df["Signal"].isin(["REDUCE", "SELL"])
]

print(weak[["Ticker", "Sector", "CompositeScore"]])

# ============================================================
# OPTIONAL WEEKLY REBALANCE
# ============================================================

TOP_N = 8

top_positions = results_df.head(TOP_N)

equal_weight = round(100 / TOP_N, 2)

print("\n")
print("=" * 80)
print(f" SUGGESTED TOP {TOP_N} MOMENTUM HOLDINGS ")
print("=" * 80)

for _, row in top_positions.iterrows():

    print(
        f"{row['Ticker']:6} "
        f" | Sector: {row['Sector']:10} "
        f" | Weight: {equal_weight}% "
        f" | Score: {round(row['CompositeScore'],2)}"
    )

print("\nDone.")