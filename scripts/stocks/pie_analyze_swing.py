"""
Swing + Put-Credit-Spread Funnel
--------------------------------

Funnels BUY candidates from the momentum scanner (pie_analyzer.run_scan) into:
- a swing ENTRY plan  (stop, position size, position heat, gap-based entry timing)
- a put-credit-spread (PCS) plan  (expiry, short/long strike, credit, max risk, POP)

Scanning lives in pie_analyzer.py. This module only analyzes the BUY output.

PCS strikes are chosen by %-out-of-the-money from the live yfinance option chain
(no Greeks). max risk = width - credit; POP is a rough credit/width proxy.

Install:
pip install yfinance pandas numpy

Run:
python pie_analyze_swing.py
python pie_analyze_swing.py --min-grade A --risk-per-trade 0.01 --target-dte 35 --otm-pct 0.06
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

import pandas as pd
import yfinance as yf

from pie_analyzer import run_scan, select_buy_candidates
from stocks_common import read_symbols_from_file

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TICKERS_FILE = SCRIPT_DIR / "my_tickers.txt"

MAX_PORTFOLIO_HEAT = 0.30
MAX_POSITION_SIZE = 0.10


# =========================================================
# ENUMS
# =========================================================

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
class PutCreditSpread:
    symbol: str
    expiration: str
    dte: int
    short_put: float
    long_put: float
    width: float
    credit: float
    max_risk: float
    pop: float
    iv_pct: float


# =========================================================
# LIFECYCLE ENGINE  (for already-open positions)
# =========================================================

def determine_swing_phase(days_held: int, return_pct: float) -> SwingPhase:
    if return_pct >= 25:
        return SwingPhase.TRAIL
    if days_held >= 60:
        return SwingPhase.REVIEW
    if days_held >= 30:
        return SwingPhase.MANAGE
    if days_held >= 10:
        return SwingPhase.HOLD
    return SwingPhase.WATCH


def determine_pcs_phase(delta: float, dte: int, profit_pct: float) -> PCSPhase:
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

def calculate_position_heat(position_size: float, stop_distance_pct: float) -> float:
    return position_size * stop_distance_pct


def calculate_portfolio_heat(heats: list[float]) -> float:
    return sum(heats)


def analyze_gap(open_gap_pct: float) -> str:
    if open_gap_pct > 6:
        return "SKIP"
    if open_gap_pct > 3:
        return "REDUCE SIZE"
    return "NORMAL ENTRY"


# =========================================================
# SWING ENTRY PLAN  (for new BUY candidates)
# =========================================================

def build_swing_plan(
    row: pd.Series,
    *,
    risk_per_trade: float = 0.01,
    max_position_size: float = MAX_POSITION_SIZE,
) -> dict:
    """Entry plan for a fresh BUY: stop below 20 DMA, risk-based size, heat, gap timing."""
    price = float(row["Price"])
    stop = float(row["20DMA"])

    stop_distance_pct = (price - stop) / price if price > stop else 0.02
    stop_distance_pct = max(stop_distance_pct, 1e-4)

    # Size so that (size * stop distance) ≈ risk_per_trade, capped at max position.
    position_size = min(max_position_size, risk_per_trade / stop_distance_pct)
    heat = calculate_position_heat(position_size, stop_distance_pct)

    gap_action = analyze_gap(float(row.get("Gap%", 0.0)))
    phase = determine_swing_phase(days_held=0, return_pct=0.0)

    return {
        "Ticker": row["Ticker"],
        "Grade": row["Grade"],
        "Price": round(price, 2),
        "Stop(20DMA)": round(stop, 2),
        "StopDist%": round(stop_distance_pct * 100, 2),
        "Size%": round(position_size * 100, 2),
        "Heat": round(heat, 4),
        "Gap%": round(float(row.get("Gap%", 0.0)), 2),
        "GapAction": gap_action,
        "Phase": phase.value,
    }


# =========================================================
# PCS PLAN  (%-OTM strike selection from live chain)
# =========================================================

def _mid_price(opt_row) -> float:
    bid = float(opt_row.get("bid") or 0.0)
    ask = float(opt_row.get("ask") or 0.0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return float(opt_row.get("lastPrice") or 0.0)


def build_pcs_plan(
    symbol: str,
    price: float,
    *,
    target_dte: int = 35,
    otm_pct: float = 0.06,
    spread_width_pct: float = 0.03,
) -> PutCreditSpread | None:
    """
    Build a put-credit-spread suggestion from the live yfinance option chain.

    Short put ~otm_pct below price; long put ~spread_width_pct below the short.
    Returns None if no usable expiry/strikes/quotes are available.
    """
    tk = yf.Ticker(symbol)
    try:
        expiries = list(tk.options or [])
    except Exception:
        return None
    if not expiries:
        return None

    today = datetime.today().date()

    def dte_of(exp: str) -> int:
        return (datetime.strptime(exp, "%Y-%m-%d").date() - today).days

    valid = [e for e in expiries if dte_of(e) > 0]
    if not valid:
        return None
    expiry = min(valid, key=lambda e: abs(dte_of(e) - target_dte))
    dte = dte_of(expiry)

    try:
        puts = tk.option_chain(expiry).puts
    except Exception:
        return None
    if puts is None or puts.empty:
        return None

    puts = puts.sort_values("strike")

    short_candidates = puts[puts["strike"] <= price * (1 - otm_pct)]
    if short_candidates.empty:
        return None
    short_row = short_candidates.iloc[-1]
    short_strike = float(short_row["strike"])

    long_candidates = puts[puts["strike"] <= short_strike * (1 - spread_width_pct)]
    if long_candidates.empty:
        lower = puts[puts["strike"] < short_strike]
        if lower.empty:
            return None
        long_row = lower.iloc[-1]
    else:
        long_row = long_candidates.iloc[-1]
    long_strike = float(long_row["strike"])

    width = short_strike - long_strike
    if width <= 0:
        return None

    credit = _mid_price(short_row) - _mid_price(long_row)
    if credit <= 0:
        return None

    max_risk = width - credit
    pop = 1.0 - (credit / width)  # rough proxy (no Greeks)
    iv_pct = float(short_row.get("impliedVolatility") or 0.0) * 100.0

    return PutCreditSpread(
        symbol=symbol,
        expiration=expiry,
        dte=dte,
        short_put=short_strike,
        long_put=long_strike,
        width=round(width, 2),
        credit=round(credit, 2),
        max_risk=round(max_risk, 2),
        pop=round(pop, 3),
        iv_pct=round(iv_pct, 1),
    )


# =========================================================
# MAIN
# =========================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Funnel scanner BUY candidates into swing + PCS plans."
    )
    parser.add_argument("--tickers-file", default=str(DEFAULT_TICKERS_FILE))
    parser.add_argument("--min-grade", default="B", choices=["A", "B", "C", "D"],
                        help="Minimum setup grade for BUY funnel (default B).")
    parser.add_argument("--risk-per-trade", type=float, default=0.01,
                        help="Account risk fraction per trade (default 0.01 = 1%%).")
    parser.add_argument("--target-dte", type=int, default=35,
                        help="Target days-to-expiry for PCS (default 35).")
    parser.add_argument("--otm-pct", type=float, default=0.06,
                        help="Short put %% OTM below price (default 0.06 = 6%%).")
    parser.add_argument("--no-pcs", action="store_true",
                        help="Skip option-chain PCS plans (swing plan only).")
    args = parser.parse_args()

    tickers = read_symbols_from_file(args.tickers_file)
    if not tickers:
        raise SystemExit(f"No tickers in {args.tickers_file}")

    print(f"Loaded {len(tickers)} symbol(s); scanning...")
    results_df = run_scan(tickers)
    if results_df.empty:
        print("No scan results.")
        return

    buys = select_buy_candidates(results_df, min_grade=args.min_grade)
    print(f"BUY candidates (Grade >= {args.min_grade}): {len(buys)}")
    if buys.empty:
        print("No BUY candidates to funnel.")
        return

    # ---- Swing entry plans ----
    swing_rows = [
        build_swing_plan(row, risk_per_trade=args.risk_per_trade)
        for _, row in buys.iterrows()
    ]
    swing_df = pd.DataFrame(swing_rows)

    print("\n")
    print("=" * 120)
    print(" SWING ENTRY PLAN (BUY funnel) ")
    print("=" * 120)
    print(swing_df.to_string(index=False))

    total_heat = calculate_portfolio_heat([r["Heat"] for r in swing_rows])
    print(f"\nPortfolio heat if all entered: {total_heat:.2%} "
          f"(max {MAX_PORTFOLIO_HEAT:.0%})")
    if total_heat > MAX_PORTFOLIO_HEAT:
        print("WARNING: combined heat exceeds limit — size down or take fewer.")

    # ---- PCS plans ----
    if args.no_pcs:
        print("\nDone.")
        return

    print("\n")
    print("=" * 120)
    print(" PUT CREDIT SPREAD PLAN (%-OTM) ")
    print("=" * 120)

    pcs_rows = []
    for _, row in buys.iterrows():
        sym = str(row["Ticker"])
        plan = build_pcs_plan(
            sym,
            float(row["Price"]),
            target_dte=args.target_dte,
            otm_pct=args.otm_pct,
        )
        if plan is None:
            print(f"{sym}: no usable option chain / strikes.")
            continue
        pcs_rows.append({
            "Ticker": plan.symbol,
            "Expiry": plan.expiration,
            "DTE": plan.dte,
            "Short": plan.short_put,
            "Long": plan.long_put,
            "Width": plan.width,
            "Credit": plan.credit,
            "MaxRisk": plan.max_risk,
            "POP~": plan.pop,
            "IV%": plan.iv_pct,
        })

    if pcs_rows:
        print(pd.DataFrame(pcs_rows).to_string(index=False))
    else:
        print("No PCS plans produced.")

    print("\nDone.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
