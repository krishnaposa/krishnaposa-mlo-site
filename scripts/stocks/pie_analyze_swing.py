"""
Advanced Momentum + Swing + PCS Framework
-----------------------------------------

Features:
- Momentum rotation scanner
- Swing lifecycle engine
- Risk governance
- Put Credit Spread framework
- Position grading
- Portfolio heat analysis
- Workflow-oriented signals

Install:
pip install yfinance pandas numpy

Run:
python pie_analyzer.py
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

import pandas as pd
import yfinance as yf

from stocks_common import read_symbols_from_file


# =========================================================
# CONFIG
# =========================================================

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TICKERS_FILE = SCRIPT_DIR / "my_tickers.txt"

BENCHMARK = "QQQ"
LOOKBACK_DAYS = 180

MAX_PORTFOLIO_HEAT = 0.30
MAX_POSITION_SIZE = 0.10


# =========================================================
# ENUMS
# =========================================================

class Signal(str, Enum):
    BUY = "BUY"
    WATCH = "WATCH"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    SELL = "SELL"


class SwingPhase(str, Enum):
    WATCH = "WATCH"
    HOLD = "HOLD"
    MANAGE = "MANAGE"
    TRAIL = "TRAIL"
    REVIEW = "REVIEW"


class PCSPhase(str, Enum):
    OPENED = "OPENED"
    THETA_DECAY = "THETA_DECAY"
    DEFENSIVE = "DEFENSIVE"
    ROLL = "ROLL"
    EXIT = "EXIT"


# =========================================================
# MODELS
# =========================================================

@dataclass
class SwingPosition:
    symbol: str
    entry_price: float
    current_price: float
    days_held: int
    stop_price: float
    position_size: float


@dataclass
class PutCreditSpread:
    symbol: str
    short_put: float
    long_put: float
    expiration: str
    credit_received: float
    max_risk: float
    delta: float
    theta: float
    iv_rank: float
    probability_of_profit: float


# =========================================================
# LIFECYCLE ENGINE
# =========================================================

def determine_swing_phase(
    days_held: int,
    return_pct: float,
) -> SwingPhase:

    if return_pct >= 25:
        return SwingPhase.TRAIL

    if days_held >= 60:
        return SwingPhase.REVIEW

    if days_held >= 30:
        return SwingPhase.MANAGE

    if days_held >= 10:
        return SwingPhase.HOLD

    return SwingPhase.WATCH


def determine_pcs_phase(
    delta: float,
    dte: int,
    profit_pct: float,
) -> PCSPhase:

    if profit_pct >= 50:
        return PCSPhase.EXIT

    if delta > 0.30 and dte < 14:
        return PCSPhase.ROLL

    if delta > 0.35:
        return PCSPhase.DEFENSIVE

    if dte < 21:
        return PCSPhase.THETA_DECAY

    return PCSPhase.OPENED


# =========================================================
# RISK ENGINE
# =========================================================

def calculate_position_heat(
    position_size: float,
    stop_distance_pct: float,
) -> float:

    return position_size * stop_distance_pct


def calculate_portfolio_heat(
    heats: list[float],
) -> float:

    return sum(heats)


# =========================================================
# SCORING
# =========================================================

def calculate_score(
    price: float,
    dma5: float,
    dma10: float,
    dma20: float,
    dma50: float,
    rs_value: float,
    volume_ratio: float,
) -> int:

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


# =========================================================
# SIGNAL ENGINE
# =========================================================

def determine_signal(
    bullish_stack: bool,
    bearish_stack: bool,
    rs_value: float,
    volume_ratio: float,
    below10_2days: bool,
    below20_2days: bool,
) -> Signal:

    signal = Signal.HOLD

    if (
        bullish_stack
        and rs_value > 0
        and volume_ratio > 1.0
    ):
        signal = Signal.BUY

    elif below20_2days:
        signal = Signal.REDUCE

    elif below10_2days:
        signal = Signal.WATCH

    if bearish_stack:
        signal = Signal.SELL

    return signal


# =========================================================
# GAP ANALYSIS
# =========================================================

def analyze_gap(open_gap_pct: float) -> str:

    if open_gap_pct > 6:
        return "SKIP"

    if open_gap_pct > 3:
        return "REDUCE SIZE"

    return "NORMAL ENTRY"


# =========================================================
# MAIN
# =========================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description="Advanced Momentum Rotation System"
    )

    parser.add_argument(
        "--tickers-file",
        default=str(DEFAULT_TICKERS_FILE),
    )

    args = parser.parse_args()

    tickers = read_symbols_from_file(
        args.tickers_file
    )

    if not tickers:
        raise SystemExit("No tickers loaded.")

    print(f"Loaded {len(tickers)} tickers.")

    end_date = datetime.today()
    start_date = end_date - timedelta(
        days=LOOKBACK_DAYS
    )

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

    portfolio_heats = []

    for ticker in tickers:

        try:

            df = pd.DataFrame({
                "Close": close_df[ticker],
                "Volume": volume_df[ticker],
            }).dropna()

            if len(df) < 60:
                continue

            # =============================================
            # MOVING AVERAGES
            # =============================================

            df["DMA5"] = (
                df["Close"].rolling(5).mean()
            )

            df["DMA10"] = (
                df["Close"].rolling(10).mean()
            )

            df["DMA20"] = (
                df["Close"].rolling(20).mean()
            )

            df["DMA50"] = (
                df["Close"].rolling(50).mean()
            )

            # =============================================
            # RELATIVE STRENGTH
            # =============================================

            rs = (
                df["Close"].pct_change(20)
                - benchmark_close.pct_change(20)
            )

            df["RS"] = rs

            # =============================================
            # VOLUME
            # =============================================

            df["AvgVolume20"] = (
                df["Volume"].rolling(20).mean()
            )

            latest = df.iloc[-1]
            prev1 = df.iloc[-2]

            price = latest["Close"]

            dma5 = latest["DMA5"]
            dma10 = latest["DMA10"]
            dma20 = latest["DMA20"]
            dma50 = latest["DMA50"]

            rs_value = latest["RS"]

            volume_ratio = (
                latest["Volume"]
                / latest["AvgVolume20"]
            )

            bullish_stack = (
                price > dma5 > dma10 > dma20 > dma50
            )

            bearish_stack = (
                price < dma10 < dma20 < dma50
            )

            below10_2days = (
                latest["Close"] < latest["DMA10"]
                and prev1["Close"] < prev1["DMA10"]
            )

            below20_2days = (
                latest["Close"] < latest["DMA20"]
                and prev1["Close"] < prev1["DMA20"]
            )

            distance_from_10dma = (
                (price - dma10) / dma10
            ) * 100

            distance_from_20dma = (
                (price - dma20) / dma20
            ) * 100

            signal = determine_signal(
                bullish_stack=bullish_stack,
                bearish_stack=bearish_stack,
                rs_value=rs_value,
                volume_ratio=volume_ratio,
                below10_2days=below10_2days,
                below20_2days=below20_2days,
            )

            score = calculate_score(
                price=price,
                dma5=dma5,
                dma10=dma10,
                dma20=dma20,
                dma50=dma50,
                rs_value=rs_value,
                volume_ratio=volume_ratio,
            )

            grade = grade_setup(score)

            # =============================================
            # POSITION MANAGEMENT
            # =============================================

            mock_return_pct = (
                (price - dma20) / dma20
            ) * 100

            mock_days_held = 24

            phase = determine_swing_phase(
                days_held=mock_days_held,
                return_pct=mock_return_pct,
            )

            stop_distance_pct = abs(
                (price - dma20) / price
            )

            heat = calculate_position_heat(
                position_size=MAX_POSITION_SIZE,
                stop_distance_pct=stop_distance_pct,
            )

            portfolio_heats.append(heat)

            # =============================================
            # GAP LOGIC
            # =============================================

            daily_gap_pct = (
                (latest["Close"] - prev1["Close"])
                / prev1["Close"]
            ) * 100

            gap_action = analyze_gap(
                daily_gap_pct
            )

            results.append({
                "Ticker": ticker,
                "Price": round(price, 2),
                "5DMA": round(dma5, 2),
                "10DMA": round(dma10, 2),
                "20DMA": round(dma20, 2),
                "50DMA": round(dma50, 2),

                "Dist10DMA%": round(
                    distance_from_10dma, 2
                ),

                "Dist20DMA%": round(
                    distance_from_20dma, 2
                ),

                "RS_vs_QQQ%": round(
                    rs_value * 100, 2
                ),

                "VolRatio": round(
                    volume_ratio, 2
                ),

                "Score": score,
                "Grade": grade,
                "Signal": signal.value,
                "Phase": phase.value,
                "GapAction": gap_action,

                "Heat": round(heat, 4),
            })

        except Exception as e:
            print(f"Error processing {ticker}: {e}")

    results_df = pd.DataFrame(results)

    if not results_df.empty:

        results_df = results_df.sort_values(
            by=["Score", "RS_vs_QQQ%"],
            ascending=False,
        )

    print("\n")
    print("=" * 160)
    print(" ADVANCED MOMENTUM + SWING DASHBOARD ")
    print("=" * 160)

    if results_df.empty:
        print("No results.")
        return

    print(results_df.to_string(index=False))

    print("\n")

    total_heat = calculate_portfolio_heat(
        portfolio_heats
    )

    print("=" * 80)
    print(" PORTFOLIO RISK ")
    print("=" * 80)

    print(f"Portfolio Heat: {total_heat:.2%}")

    if total_heat > MAX_PORTFOLIO_HEAT:
        print("WARNING: Portfolio heat elevated.")

    # =============================================
    # SIGNAL GROUPS
    # =============================================

    for signal in Signal:

        tickers_for_signal = results_df[
            results_df["Signal"] == signal.value
        ]["Ticker"].tolist()

        print(f"\n{signal.value}:")
        print(tickers_for_signal)

    print("\nDone.")


if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:
        sys.exit(130)