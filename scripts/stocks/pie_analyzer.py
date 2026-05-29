"""
Momentum Rotation Scanner
-------------------------

Reads tickers from my_tickers.txt (or --tickers-file), then:
1. Downloads stock data using yfinance
2. Calculates 5/10/20/50 DMA, RS vs QQQ, volume confirmation, daily gap
3. Scores + grades each name and emits a signal: BUY / WATCH / HOLD / REDUCE / SELL

This module is the shared scanner. Other tools (e.g. pie_analyze_swing.py)
import `run_scan` and `select_buy_candidates` to funnel BUY names downstream.

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
from enum import Enum
from pathlib import Path

import pandas as pd
import yfinance as yf

from stocks_common import read_symbols_from_file

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TICKERS_FILE = SCRIPT_DIR / "my_tickers.txt"

BENCHMARK = "QQQ"
LOOKBACK_DAYS = 180

GRADE_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}

# Overextension / "spiked" defaults — a BUY this stretched is demoted to WATCH.
MAX_EXT_PCT = 20.0   # max % above the 20 DMA
MAX_RSI = 80.0       # RSI(14) overbought
MAX_RUN5 = 25.0      # max 5-day run-up %


class Signal(str, Enum):
    BUY = "BUY"
    WATCH = "WATCH"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    SELL = "SELL"


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, float("nan"))
    return 100.0 - (100.0 / (1.0 + rs))


def is_spiked(
    ext20_pct: float,
    rsi_val: float,
    run5_pct: float,
    *,
    max_ext_pct: float = MAX_EXT_PCT,
    max_rsi: float = MAX_RSI,
    max_run5: float = MAX_RUN5,
) -> bool:
    """True if the move looks overextended/parabolic (don't chase)."""
    if ext20_pct == ext20_pct and ext20_pct > max_ext_pct:
        return True
    if rsi_val == rsi_val and rsi_val > max_rsi:
        return True
    if run5_pct == run5_pct and run5_pct > max_run5:
        return True
    return False


def calculate_score(
    price: float,
    dma5: float,
    dma10: float,
    dma20: float,
    dma50: float,
    rs_value: float,
    volume_ratio: float,
) -> int:
    """Weighted trend + RS + volume score (max 15)."""
    score = 0
    if price > dma5:
        score += 1
    if price > dma10:
        score += 1
    if price > dma20:
        score += 2
    if price > dma50:
        score += 2
    if dma10 > dma20:
        score += 2
    if dma20 > dma50:
        score += 2
    if rs_value > 0:
        score += 3
    if volume_ratio > 1:
        score += 2
    return score


def grade_setup(score: int) -> str:
    if score >= 13:
        return "A"
    if score >= 10:
        return "B"
    if score >= 7:
        return "C"
    return "D"


def determine_signal(
    bullish_stack: bool,
    bearish_stack: bool,
    rs_value: float,
    volume_ratio: float,
    below10_2days: bool,
    below20_2days: bool,
) -> Signal:
    signal = Signal.HOLD

    if bullish_stack and rs_value > 0 and volume_ratio > 1.0:
        signal = Signal.BUY
    elif below20_2days:
        signal = Signal.REDUCE
    elif below10_2days:
        signal = Signal.WATCH

    if bearish_stack:
        signal = Signal.SELL

    return signal


def run_scan(
    tickers: list[str],
    *,
    lookback_days: int = LOOKBACK_DAYS,
    benchmark: str = BENCHMARK,
    max_ext_pct: float = MAX_EXT_PCT,
    max_rsi: float = MAX_RSI,
    max_run5: float = MAX_RUN5,
) -> pd.DataFrame:
    """
    Download prices and build the momentum dashboard.

    Overextended ("spiked") names that would otherwise be BUY are demoted to
    WATCH (Spiked=Y) so you don't chase blow-off tops.

    Returns a DataFrame (one row per scored ticker) with columns:
    Ticker, Price, 5DMA, 10DMA, 20DMA, 50DMA, Dist10DMA%, Dist20DMA%,
    RS_vs_QQQ%, VolRatio, Gap%, RSI, Run5%, Spiked, Score, Grade, Signal.
    """
    if not tickers:
        return pd.DataFrame()

    end_date = datetime.today()
    start_date = end_date - timedelta(days=lookback_days)
    all_tickers = sorted(set(tickers) | {benchmark})

    data = yf.download(
        all_tickers,
        start=start_date,
        end=end_date,
        auto_adjust=True,
        progress=False,
    )

    close_df = data["Close"]
    volume_df = data["Volume"]
    open_df = data["Open"]
    benchmark_close = close_df[benchmark]

    results = []

    for ticker in tickers:
        if ticker == benchmark:
            continue
        try:
            df = pd.DataFrame({
                "Open": open_df[ticker],
                "Close": close_df[ticker],
                "Volume": volume_df[ticker],
            }).dropna()

            if len(df) < 60:
                continue

            df["DMA5"] = df["Close"].rolling(5).mean()
            df["DMA10"] = df["Close"].rolling(10).mean()
            df["DMA20"] = df["Close"].rolling(20).mean()
            df["DMA50"] = df["Close"].rolling(50).mean()
            df["RS"] = df["Close"].pct_change(20) - benchmark_close.pct_change(20)
            df["AvgVolume20"] = df["Volume"].rolling(20).mean()
            df["RSI"] = rsi(df["Close"])
            df["Run5"] = df["Close"].pct_change(5) * 100.0

            latest = df.iloc[-1]
            prev1 = df.iloc[-2]

            price = latest["Close"]
            dma5 = latest["DMA5"]
            dma10 = latest["DMA10"]
            dma20 = latest["DMA20"]
            dma50 = latest["DMA50"]
            rs_value = latest["RS"]
            volume_ratio = latest["Volume"] / latest["AvgVolume20"]
            rsi_val = float(latest["RSI"]) if latest["RSI"] == latest["RSI"] else float("nan")
            run5_pct = float(latest["Run5"]) if latest["Run5"] == latest["Run5"] else float("nan")

            bullish_stack = price > dma5 > dma10 > dma20 > dma50
            bearish_stack = price < dma5 < dma10 < dma20 < dma50

            below10_2days = (
                latest["Close"] < latest["DMA10"]
                and prev1["Close"] < prev1["DMA10"]
            )
            below20_2days = (
                latest["Close"] < latest["DMA20"]
                and prev1["Close"] < prev1["DMA20"]
            )

            distance_from_10dma = (price - dma10) / dma10 * 100
            distance_from_20dma = (price - dma20) / dma20 * 100

            # True overnight gap: today's open vs prior close.
            gap_pct = (latest["Open"] - prev1["Close"]) / prev1["Close"] * 100

            signal = determine_signal(
                bullish_stack=bullish_stack,
                bearish_stack=bearish_stack,
                rs_value=rs_value,
                volume_ratio=volume_ratio,
                below10_2days=below10_2days,
                below20_2days=below20_2days,
            )

            # Overextension guard: a stretched BUY is demoted to WATCH (don't chase).
            spiked = is_spiked(
                distance_from_20dma, rsi_val, run5_pct,
                max_ext_pct=max_ext_pct, max_rsi=max_rsi, max_run5=max_run5,
            )
            if spiked and signal == Signal.BUY:
                signal = Signal.WATCH

            score = calculate_score(
                price=price,
                dma5=dma5,
                dma10=dma10,
                dma20=dma20,
                dma50=dma50,
                rs_value=rs_value,
                volume_ratio=volume_ratio,
            )

            results.append({
                "Ticker": ticker,
                "Price": round(price, 2),
                "5DMA": round(dma5, 2),
                "10DMA": round(dma10, 2),
                "20DMA": round(dma20, 2),
                "50DMA": round(dma50, 2),
                "Dist10DMA%": round(distance_from_10dma, 2),
                "Dist20DMA%": round(distance_from_20dma, 2),
                "RS_vs_QQQ%": round(rs_value * 100, 2),
                "VolRatio": round(volume_ratio, 2),
                "Gap%": round(gap_pct, 2),
                "RSI": round(rsi_val, 1) if rsi_val == rsi_val else None,
                "Run5%": round(run5_pct, 2) if run5_pct == run5_pct else None,
                "Spiked": "Y" if spiked else "",
                "Score": score,
                "Grade": grade_setup(score),
                "Signal": signal.value,
            })

        except Exception as e:
            print(f"Error processing {ticker}: {e}")

    results_df = pd.DataFrame(results)
    if not results_df.empty:
        results_df = results_df.sort_values(
            by=["Score", "RS_vs_QQQ%"],
            ascending=False,
        ).reset_index(drop=True)
    return results_df


def select_buy_candidates(results_df: pd.DataFrame, *, min_grade: str = "B") -> pd.DataFrame:
    """Filter scan output to BUY signals at or above `min_grade` (A best)."""
    if results_df.empty:
        return results_df
    threshold = GRADE_RANK.get(min_grade.upper(), GRADE_RANK["B"])
    mask = (results_df["Signal"] == Signal.BUY.value) & (
        results_df["Grade"].map(GRADE_RANK) >= threshold
    )
    return results_df[mask].copy()


def main() -> None:
    parser = argparse.ArgumentParser(description="Momentum rotation scanner vs QQQ.")
    parser.add_argument(
        "--tickers-file",
        default=str(DEFAULT_TICKERS_FILE),
        help=f"Ticker list file (default: {DEFAULT_TICKERS_FILE.name}).",
    )
    parser.add_argument("--max-ext-pct", type=float, default=MAX_EXT_PCT,
                        help=f"Spike guard: max %% above 20 DMA (default {MAX_EXT_PCT:g}).")
    parser.add_argument("--max-rsi", type=float, default=MAX_RSI,
                        help=f"Spike guard: max RSI(14) (default {MAX_RSI:g}).")
    parser.add_argument("--max-run5", type=float, default=MAX_RUN5,
                        help=f"Spike guard: max 5-day run-up %% (default {MAX_RUN5:g}).")
    args = parser.parse_args()

    tickers = read_symbols_from_file(args.tickers_file)
    if not tickers:
        raise SystemExit(f"No tickers in {args.tickers_file}")

    print(f"Loaded {len(tickers)} symbol(s) from {args.tickers_file}")

    results_df = run_scan(
        tickers,
        max_ext_pct=args.max_ext_pct,
        max_rsi=args.max_rsi,
        max_run5=args.max_run5,
    )

    print("\n")
    print("=" * 140)
    print(" MOMENTUM ROTATION DASHBOARD ")
    print("=" * 140)

    if results_df.empty:
        print("No results (check tickers or Yahoo data).")
        print("Done.")
        return

    print(results_df.to_string(index=False))
    print("\n")

    for sig in Signal:
        names = results_df[results_df["Signal"] == sig.value]["Ticker"].tolist()
        print(f"{sig.value}: {names}")

    print("\nDone.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
