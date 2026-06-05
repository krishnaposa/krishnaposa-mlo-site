"""
Momentum scanner (pie_analyzer logic) for Azure daily email PCS funnel.
Mirrors scripts/stocks/pie_analyzer.py — keep in sync when rules change.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import List

import pandas as pd
import yfinance as yf

BENCHMARK = "QQQ"
LOOKBACK_DAYS = 180
GRADE_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}
MAX_EXT_PCT = 20.0
MAX_RSI = 80.0
MAX_RUN5 = 25.0


class Signal(str, Enum):
    BUY = "BUY"
    WATCH = "WATCH"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    SELL = "SELL"


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, float("nan"))
    return 100.0 - (100.0 / (1.0 + rs))


def is_spiked(ext20_pct, rsi_val, run5_pct, *, max_ext_pct=MAX_EXT_PCT, max_rsi=MAX_RSI, max_run5=MAX_RUN5):
    if ext20_pct == ext20_pct and ext20_pct > max_ext_pct:
        return True
    if rsi_val == rsi_val and rsi_val > max_rsi:
        return True
    if run5_pct == run5_pct and run5_pct > max_run5:
        return True
    return False


def calculate_score(price, dma5, dma10, dma20, dma50, rs_value, volume_ratio) -> int:
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


def determine_signal(bullish_stack, bearish_stack, rs_value, volume_ratio, below10_2days, below20_2days) -> Signal:
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


def run_scan(tickers: List[str], *, lookback_days: int = LOOKBACK_DAYS, benchmark: str = BENCHMARK) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()

    end_date = datetime.today()
    start_date = end_date - timedelta(days=lookback_days)
    all_tickers = sorted(set(tickers) | {benchmark})

    data = yf.download(all_tickers, start=start_date, end=end_date, auto_adjust=True, progress=False)
    if data is None or data.empty:
        return pd.DataFrame()

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
            dma5, dma10, dma20, dma50 = latest["DMA5"], latest["DMA10"], latest["DMA20"], latest["DMA50"]
            rs_value = latest["RS"]
            volume_ratio = latest["Volume"] / latest["AvgVolume20"]
            rsi_val = float(latest["RSI"]) if latest["RSI"] == latest["RSI"] else float("nan")
            run5_pct = float(latest["Run5"]) if latest["Run5"] == latest["Run5"] else float("nan")

            bullish_stack = price > dma5 > dma10 > dma20 > dma50
            bearish_stack = price < dma5 < dma10 < dma20 < dma50
            below10_2days = latest["Close"] < latest["DMA10"] and prev1["Close"] < prev1["DMA10"]
            below20_2days = latest["Close"] < latest["DMA20"] and prev1["Close"] < prev1["DMA20"]
            distance_from_20dma = (price - dma20) / dma20 * 100
            gap_pct = (latest["Open"] - prev1["Close"]) / prev1["Close"] * 100

            signal = determine_signal(
                bullish_stack, bearish_stack, rs_value, volume_ratio, below10_2days, below20_2days
            )
            if is_spiked(distance_from_20dma, rsi_val, run5_pct) and signal == Signal.BUY:
                signal = Signal.WATCH

            score = calculate_score(price, dma5, dma10, dma20, dma50, rs_value, volume_ratio)
            results.append({
                "Ticker": ticker,
                "Price": round(price, 2),
                "Grade": grade_setup(score),
                "Signal": signal.value,
            })
        except Exception:
            continue

    results_df = pd.DataFrame(results)
    if not results_df.empty:
        results_df = results_df.sort_values(by=["Grade", "Ticker"], ascending=[True, True]).reset_index(drop=True)
    return results_df


def select_buy_candidates(results_df: pd.DataFrame, *, min_grade: str = "B") -> pd.DataFrame:
    if results_df.empty:
        return results_df
    threshold = GRADE_RANK.get(min_grade.upper(), GRADE_RANK["B"])
    mask = (results_df["Signal"] == Signal.BUY.value) & (
        results_df["Grade"].map(GRADE_RANK) >= threshold
    )
    return results_df[mask].copy()
