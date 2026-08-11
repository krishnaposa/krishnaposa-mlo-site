"""
Shared helpers for PCS opportunities (entry) and lifecycle (exit).
"""

from __future__ import annotations

import math
import os
from typing import Optional

import pandas as pd
from scipy.stats import norm

from .options_metrics import days_to_next_earnings

PROFIT_TARGET = float(os.getenv("PCS_PROFIT_TARGET", "50"))
STOP_LOSS = float(os.getenv("PCS_STOP_LOSS", "-100"))
ROLL_DTE = int(os.getenv("PCS_ROLL_DTE", "14"))
ROLL_BUFFER = float(os.getenv("PCS_ROLL_BUFFER", "3"))
MANAGE_DTE = int(os.getenv("PCS_MANAGE_DTE", "21"))

PCS_BLOCK_EARNINGS = os.getenv("PCS_BLOCK_EARNINGS", "1") == "1"
PCS_EARNINGS_BLOCK_DAYS = int(
    os.getenv("PCS_EARNINGS_BLOCK_DAYS", os.getenv("EARNINGS_BLOCK_DAYS", "14"))
)
PCS_STRIKE_MATCH_TOL = float(os.getenv("PCS_STRIKE_MATCH_TOL", "0.02"))

PCS_RISK_FREE = float(os.getenv("PCS_RISK_FREE_RATE", os.getenv("PMCC_RISK_FREE_RATE", "0.04")))
# Short-put |Δ| band (positive magnitude). Default ~0.18–0.28, target 0.22.
PCS_SHORT_DELTA_MIN = float(os.getenv("PCS_SHORT_DELTA_MIN", "0.18"))
PCS_SHORT_DELTA_MAX = float(os.getenv("PCS_SHORT_DELTA_MAX", "0.28"))
PCS_SHORT_DELTA_TARGET = float(os.getenv("PCS_SHORT_DELTA_TARGET", "0.22"))
PCS_USE_DELTA = os.getenv("PCS_USE_DELTA", "1") == "1"


def bs_put_delta(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    *,
    r: float = PCS_RISK_FREE,
) -> float:
    """Black–Scholes put delta (negative for long puts). Returns NaN if inputs invalid."""
    if spot <= 0 or strike <= 0 or dte <= 0 or iv <= 0:
        return float("nan")
    t = dte / 365.0
    try:
        d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
        return float(norm.cdf(d1) - 1.0)
    except (ValueError, ZeroDivisionError):
        return float("nan")


def abs_put_delta(spot: float, strike: float, dte: int, iv: float) -> float:
    """Positive short-put delta magnitude for PCS targeting."""
    d = bs_put_delta(spot, strike, dte, iv)
    if d != d:
        return float("nan")
    return abs(d)


def pcs_buffer_pct(price: float, short_strike: float) -> float:
    """Cushion above short put as % of stock price (matches pie_analyze_swing)."""
    if price != price or price <= 0:
        return float("nan")
    return (price - short_strike) / price * 100.0


def put_row_for_strike(puts: pd.DataFrame, strike: float, *, tol: float | None = None) -> Optional[pd.Series]:
    """Return put chain row for strike, allowing small float tolerance."""
    if puts is None or puts.empty or "strike" not in puts.columns:
        return None
    tol = PCS_STRIKE_MATCH_TOL if tol is None else tol
    target = float(strike)
    diffs = (puts["strike"].astype(float) - target).abs()
    if diffs.empty:
        return None
    idx = diffs.idxmin()
    if float(diffs.loc[idx]) > tol:
        return None
    return puts.loc[idx]


def spread_mid_cost(puts: pd.DataFrame, short_k: float, long_k: float, mid_fn) -> float:
    """Current debit to close spread (short mid - long mid), or NaN."""
    short_row = put_row_for_strike(puts, short_k)
    long_row = put_row_for_strike(puts, long_k)
    if short_row is None or long_row is None:
        return float("nan")
    cost = mid_fn(short_row) - mid_fn(long_row)
    if cost != cost or cost < 0:
        return float("nan")
    return float(cost)


def earnings_blocks_new_spread(symbol: str, spread_dte: int) -> bool:
    """
    True if earnings should block opening a new put credit spread.

    Blocks when the next earnings date falls before spread expiry (during the trade).
    """
    if not PCS_BLOCK_EARNINGS:
        return False
    dte_earn = days_to_next_earnings(symbol)
    if dte_earn is None or dte_earn < 0:
        return False
    if dte_earn < int(spread_dte):
        return True
    return False


def determine_pcs_phase_live(dte: int, profit_pct: float, buffer_pct: float) -> str:
    if profit_pct >= PROFIT_TARGET:
        return "EXIT"
    if profit_pct <= STOP_LOSS:
        return "STOP"
    if buffer_pct < 0:
        return "DEFENSIVE"
    if dte < ROLL_DTE and buffer_pct < ROLL_BUFFER:
        return "ROLL"
    if dte <= MANAGE_DTE:
        return "MANAGE"
    return "OPENED"


def determine_pcs_phase_fallback(dte: int, buffer_pct: float) -> str:
    """Phase when option marks are unavailable — buffer + DTE only."""
    safe = buffer_pct if buffer_pct == buffer_pct else 0.0
    if safe < 0:
        return "DEFENSIVE"
    if dte < ROLL_DTE and safe < ROLL_BUFFER:
        return "ROLL"
    if dte <= MANAGE_DTE:
        return "MANAGE"
    return "OPENED"


def pcs_action_for_phase(phase: str, *, verify_suffix: str = "") -> str:
    mapping = {
        "EXIT": f"CLOSE (>={PROFIT_TARGET:g}% profit)",
        "STOP": f"CLOSE (stop, <={STOP_LOSS:g}% credit loss)",
        "DEFENSIVE": "DEFEND / ROLL CHECK (under short)",
        "ROLL": f"ROLL (<{ROLL_DTE}DTE, tight buffer)",
        "MANAGE": f"MANAGE (<={MANAGE_DTE}DTE: close/roll)",
        "OPENED": "HOLD",
        "EXPIRED": "CHECK ASSIGNMENT / REMOVE",
        "BAD DATA": "VERIFY POSITION DATA",
    }
    base = mapping.get(phase, "VERIFY MANUALLY")
    return f"{base}{verify_suffix}" if verify_suffix else base


def is_highlight_action(action: str) -> bool:
    """Table row highlight — includes manage/review style actions."""
    act = str(action).upper()
    keywords = (
        "CLOSE",
        "ROLL",
        "DEFEND",
        "STOP HIT",
        "CHECK ASSIGNMENT",
        "REVIEW",
        "RAISE STOP",
        "VERIFY",
    )
    return any(k in act for k in keywords)


def is_urgent_action(action: str) -> bool:
    """Subject-line / needs-action list — urgent PCS/swing decisions only."""
    act = str(action).upper()
    if act.startswith("HOLD") or act.startswith("LET DECAY"):
        return False
    keywords = ("CLOSE", "ROLL", "DEFEND", "STOP HIT", "CHECK ASSIGNMENT")
    return any(k in act for k in keywords)
