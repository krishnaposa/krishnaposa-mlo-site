"""
Shared helpers for PMCC (Poor Man's Covered Call) opportunities and lifecycle.
"""

from __future__ import annotations

import datetime as dt
import math
import os
from typing import Callable, Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

PMCC_SHORT_PROFIT_TARGET = float(os.getenv("PMCC_SHORT_PROFIT_TARGET", "50"))
PMCC_SHORT_MIN_DTE = int(os.getenv("PMCC_SHORT_MIN_DTE", "7"))
PMCC_SHORT_ROLL_DTE = int(os.getenv("PMCC_SHORT_ROLL_DTE", "21"))
PMCC_CHALLENGE_PCT = float(os.getenv("PMCC_CHALLENGE_PCT", "0.02"))
PMCC_STRIKE_MATCH_TOL = float(os.getenv("PMCC_STRIKE_MATCH_TOL", "0.02"))
PMCC_RISK_FREE = float(os.getenv("PMCC_RISK_FREE_RATE", "0.04"))

PMCC_LEAP_MIN_DTE = int(os.getenv("PMCC_LEAP_MIN_DTE", "540"))
PMCC_LEAP_MAX_DTE = int(os.getenv("PMCC_LEAP_MAX_DTE", "900"))
PMCC_LEAP_TARGET_DTE = int(os.getenv("PMCC_LEAP_TARGET_DTE", "730"))
PMCC_LEAP_DELTA_MIN = float(os.getenv("PMCC_LEAP_DELTA_MIN", "0.80"))
PMCC_LEAP_DELTA_MAX = float(os.getenv("PMCC_LEAP_DELTA_MAX", "0.95"))
PMCC_LEAP_DELTA_TARGET = float(os.getenv("PMCC_LEAP_DELTA_TARGET", "0.87"))
PMCC_MAX_EXTRINSIC_PCT = float(os.getenv("PMCC_MAX_EXTRINSIC_PCT", "0.15"))

PMCC_SHORT_MIN_DTE_WIN = int(os.getenv("PMCC_SHORT_MIN_DTE_WIN", "30"))
PMCC_SHORT_MAX_DTE_WIN = int(os.getenv("PMCC_SHORT_MAX_DTE_WIN", "45"))
PMCC_SHORT_DELTA_MIN = float(os.getenv("PMCC_SHORT_DELTA_MIN", "0.15"))
PMCC_SHORT_DELTA_MAX = float(os.getenv("PMCC_SHORT_DELTA_MAX", "0.25"))
PMCC_SHORT_DELTA_TARGET = float(os.getenv("PMCC_SHORT_DELTA_TARGET", "0.20"))

PMCC_SHORT_MIN_OI = int(os.getenv("PMCC_SHORT_MIN_OI", "50"))
PMCC_SHORT_MAX_SPREAD_PCT = float(os.getenv("PMCC_SHORT_MAX_SPREAD_PCT", "0.10"))

PMCC_LEAP_EXIT_MIN_DTE = int(os.getenv("PMCC_LEAP_EXIT_MIN_DTE", "365"))
PMCC_LEAP_EXIT_GAIN_MIN = float(os.getenv("PMCC_LEAP_EXIT_GAIN_MIN", "75"))
PMCC_LEAP_EXIT_DELTA_MIN = float(os.getenv("PMCC_LEAP_EXIT_DELTA_MIN", "0.70"))
PMCC_TARGET_ANNUAL_RETURN = float(os.getenv("PMCC_TARGET_ANNUAL_RETURN", "25"))
PMCC_BETTER_OPP_MIN_SCORE = float(os.getenv("PMCC_BETTER_OPP_MIN_SCORE", "8.0"))

PMCC_MODE = os.getenv("PMCC_MODE", "core").strip().lower()
PMCC_EARNINGS_BLOCK_DAYS = int(os.getenv("PMCC_EARNINGS_BLOCK_DAYS", "7"))
PMCC_MIN_MONTHLY_ON_DEBIT = float(os.getenv("PMCC_MIN_MONTHLY_ON_DEBIT", "1.0"))
PMCC_SHORT_DELTA_TIEBREAK = float(os.getenv("PMCC_SHORT_DELTA_TIEBREAK", "0.15"))
PMCC_MAX_BREAKEVEN_PCT_ABOVE_SPOT = float(os.getenv("PMCC_MAX_BREAKEVEN_PCT_ABOVE_SPOT", "5"))


def mid_price(row) -> float:
    bid = float(row.get("bid") or 0.0)
    ask = float(row.get("ask") or 0.0)
    if bid > 0 and ask > 0 and ask >= bid:
        return (bid + ask) / 2.0
    return float(row.get("lastPrice") or 0.0)


def spread_pct(row) -> float:
    bid = float(row.get("bid") or 0.0)
    ask = float(row.get("ask") or 0.0)
    mid = mid_price(row)
    if mid <= 0 or bid <= 0 or ask <= 0:
        return float("nan")
    return (ask - bid) / mid


def leg_is_liquid(row, *, min_oi: int, max_spread_pct: float) -> bool:
    raw_oi = row.get("openInterest")
    if raw_oi is None or (isinstance(raw_oi, float) and raw_oi != raw_oi):
        oi = 0
    else:
        oi = int(raw_oi or 0)
    if oi < min_oi:
        return False
    sp = spread_pct(row)
    return sp == sp and sp <= max_spread_pct


def bs_call_delta(spot: float, strike: float, dte: int, iv: float, *, r: float = PMCC_RISK_FREE) -> float:
    if spot <= 0 or strike <= 0 or dte <= 0 or iv <= 0:
        return float("nan")
    t = dte / 365.0
    try:
        d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
        return float(norm.cdf(d1))
    except (ValueError, ZeroDivisionError):
        return float("nan")


def intrinsic_call(spot: float, strike: float) -> float:
    return max(spot - strike, 0.0)


def extrinsic_pct(spot: float, strike: float, option_mid: float) -> float:
    if option_mid <= 0:
        return float("nan")
    ext = option_mid - intrinsic_call(spot, strike)
    return max(ext, 0.0) / option_mid


def breakeven_pct_above_spot(spot: float, breakeven: float) -> float:
    if spot <= 0 or breakeven != breakeven:
        return float("nan")
    return (breakeven / spot - 1.0) * 100.0


def breakeven_ok_vs_spot(spot: float, breakeven: float) -> bool:
    """Breakeven at or slightly above spot; ideal is BE <= spot (<= 0%)."""
    pct = breakeven_pct_above_spot(spot, breakeven)
    if pct != pct:
        return False
    return pct <= PMCC_MAX_BREAKEVEN_PCT_ABOVE_SPOT


def pmcc_structure_ok(
    *,
    leap_strike: float,
    leap_debit: float,
    short_strike: float,
    short_credit: float,
    spot: float | None = None,
) -> bool:
    """Short strike > breakeven; breakeven within PMCC_MAX_BREAKEVEN_PCT_ABOVE_SPOT of spot."""
    net_debit = leap_debit - short_credit
    breakeven = leap_strike + net_debit
    if short_strike <= breakeven:
        return False
    if spot is not None and spot > 0:
        return breakeven_ok_vs_spot(spot, breakeven)
    return True


def pmcc_trade_metrics(
    *,
    leap_strike: float,
    leap_debit: float,
    short_strike: float,
    short_credit: float,
    spot: float,
    short_dte: int,
) -> dict:
    net_debit = leap_debit - short_credit
    breakeven = leap_strike + net_debit
    max_risk = net_debit * 100.0
    upside_room = (short_strike / spot - 1.0) * 100.0 if spot > 0 else float("nan")
    monthly_on_debit = short_credit / leap_debit * 100.0 if leap_debit > 0 else float("nan")
    annualized_on_debit = monthly_on_debit * (365.0 / max(short_dte, 1))
    be_vs_spot = breakeven_pct_above_spot(spot, breakeven)

    return {
        "NetDebit": round(net_debit, 2),
        "MaxRisk": round(max_risk, 0),
        "Breakeven": round(breakeven, 2),
        "BreakevenVsSpot%": round(be_vs_spot, 2) if be_vs_spot == be_vs_spot else None,
        "UpsideRoom%": round(upside_room, 1),
        "MonthlyOnDebit%": round(monthly_on_debit, 2),
        "AnnualizedOnDebit%": round(annualized_on_debit, 1),
    }


def pmcc_income_score(monthly_on_debit_pct: float) -> float:
    """Score short-call income vs LEAP debit (typical PMCC: ~1.5–6%/month on debit)."""
    if monthly_on_debit_pct != monthly_on_debit_pct:
        return 5.0
    m = monthly_on_debit_pct
    if m >= 6.0:
        return 10.0
    if m >= 5.0:
        return 9.0
    if m >= 4.0:
        return 8.0
    if m >= 3.0:
        return 7.0
    if m >= 2.0:
        return 6.0
    if m >= 1.5:
        return 5.0
    if m >= 1.0:
        return 4.0
    return 3.0


def short_leg_pick_score(short: dict, *, delta: float) -> float:
    """Higher is better — maximize short premium while staying in delta band."""
    monthly = float(short.get("MonthlyOnDebit%") or 0.0)
    ann = float(short.get("AnnualizedOnDebit%") or 0.0)
    delta_fit = max(0.0, PMCC_SHORT_DELTA_MAX - abs(delta - PMCC_SHORT_DELTA_TARGET))
    oi = float(short.get("oi") or 0.0)
    score = monthly * 4.0 + ann * 0.03 + delta_fit * PMCC_SHORT_DELTA_TIEBREAK + min(oi, 1000) / 2000.0
    be_vs = short.get("BreakevenVsSpot%")
    if be_vs is not None and be_vs == be_vs:
        if be_vs <= 0:
            score += 2.0
        elif be_vs <= 3.0:
            score += 1.0
    return score


def call_row_for_strike(calls: pd.DataFrame, strike: float, *, tol: float | None = None) -> Optional[pd.Series]:
    if calls is None or calls.empty or "strike" not in calls.columns:
        return None
    tol = PMCC_STRIKE_MATCH_TOL if tol is None else tol
    target = float(strike)
    diffs = (calls["strike"].astype(float) - target).abs()
    if diffs.empty:
        return None
    idx = diffs.idxmin()
    if float(diffs.loc[idx]) > tol:
        return None
    return calls.loc[idx]


def choose_expiry(
    expiries: list[str],
    *,
    min_dte: int,
    max_dte: int,
    target_dte: int | None = None,
    today: dt.date | None = None,
) -> tuple[Optional[str], Optional[int]]:
    if today is None:
        today = dt.date.today()
    if target_dte is None:
        target_dte = (min_dte + max_dte) // 2

    best: Optional[str] = None
    best_dte: Optional[int] = None
    for exp in expiries or []:
        try:
            dte = (dt.datetime.strptime(exp, "%Y-%m-%d").date() - today).days
        except Exception:
            continue
        if dte < min_dte or dte > max_dte:
            continue
        if best is None or abs(dte - target_dte) < abs((best_dte or 0) - target_dte):
            best = exp
            best_dte = dte
    return (best, best_dte) if best else (None, None)


def has_weekly_expiries(expiries: list[str], today: dt.date | None = None) -> bool:
    if today is None:
        today = dt.date.today()
    for exp in expiries or []:
        try:
            dte = (dt.datetime.strptime(exp, "%Y-%m-%d").date() - today).days
        except Exception:
            continue
        if 1 <= dte <= 10:
            return True
    return False


def determine_short_call_phase(
    *,
    dte: int,
    profit_pct: float,
    spot: float,
    short_strike: float,
    profit_known: bool,
) -> str:
    if profit_known and profit_pct >= PMCC_SHORT_PROFIT_TARGET:
        return "CLOSE_PROFIT"
    if spot == spot and short_strike > 0 and spot >= short_strike:
        return "CHALLENGED"
    if (
        spot == spot
        and short_strike > 0
        and spot >= short_strike * (1.0 - PMCC_CHALLENGE_PCT)
        and dte <= PMCC_SHORT_ROLL_DTE
    ):
        return "ROLL"
    if dte <= PMCC_SHORT_MIN_DTE:
        return "EXPIRING"
    if dte <= PMCC_SHORT_ROLL_DTE:
        return "MANAGE"
    return "HOLD"


def short_call_action_for_phase(phase: str, *, verify_suffix: str = "") -> str:
    mapping = {
        "CLOSE_PROFIT": f"CLOSE short (≥{PMCC_SHORT_PROFIT_TARGET:g}% profit)",
        "CHALLENGED": "DEFEND / ROLL short (price at/above short strike)",
        "ROLL": f"ROLL short (<{PMCC_SHORT_ROLL_DTE}DTE, near strike)",
        "EXPIRING": f"CLOSE/ROLL short (≤{PMCC_SHORT_MIN_DTE}DTE)",
        "MANAGE": f"MANAGE short (≤{PMCC_SHORT_ROLL_DTE}DTE)",
        "HOLD": "HOLD short (let decay)",
        "NO_SHORT": "SELL short call (30–45 DTE, Δ 0.15–0.25)",
        "BAD_DATA": "VERIFY position data",
    }
    base = mapping.get(phase, "VERIFY MANUALLY")
    return f"{base}{verify_suffix}" if verify_suffix else base


def leap_hold_guidance_for_short_phase(short_phase: str) -> str:
    """When LEAP is held, what to do on the short side (ChatGPT 'OTHERWISE' rules)."""
    if short_phase in ("CLOSE_PROFIT", "EXPIRING"):
        return "Roll short call after close"
    if short_phase in ("CHALLENGED", "ROLL"):
        return "Roll short call"
    if short_phase == "NO_SHORT":
        return "Sell next short call (30–45 DTE)"
    return "Keep selling calls; collect income"


def determine_leap_exit_phase(
    *,
    long_dte: int,
    long_pnl_pct: float,
    long_delta: float,
    annualized_return_pct: float,
    thesis_broken: bool,
    better_opportunity: str | None = None,
) -> str:
    """Return LEAP exit phase, or HOLD when no exit trigger fires."""
    if long_dte > 0 and long_dte < PMCC_LEAP_EXIT_MIN_DTE:
        return "EXIT_DTE"
    if thesis_broken:
        return "EXIT_THESIS"
    if long_pnl_pct == long_pnl_pct and long_pnl_pct >= PMCC_LEAP_EXIT_GAIN_MIN:
        return "EXIT_GAIN"
    if long_delta == long_delta and long_delta < PMCC_LEAP_EXIT_DELTA_MIN:
        return "EXIT_DELTA"
    if (
        annualized_return_pct == annualized_return_pct
        and annualized_return_pct >= PMCC_TARGET_ANNUAL_RETURN
    ):
        return "EXIT_TARGET"
    if better_opportunity:
        return "EXIT_BETTER_OPP"
    return "HOLD"


def leap_exit_action_for_phase(phase: str, *, detail: str = "") -> str:
    mapping = {
        "EXIT_DTE": f"EXIT LEAP (<{PMCC_LEAP_EXIT_MIN_DTE // 30}mo DTE — roll or close)",
        "EXIT_THESIS": "EXIT LEAP (thesis broken — scanner REDUCE/SELL)",
        "EXIT_GAIN": f"EXIT LEAP (gain ≥{PMCC_LEAP_EXIT_GAIN_MIN:g}% — take profit)",
        "EXIT_DELTA": f"EXIT LEAP (Δ <{PMCC_LEAP_EXIT_DELTA_MIN:g} — deep ITM, roll LEAP)",
        "EXIT_TARGET": f"EXIT LEAP (annualized ≥{PMCC_TARGET_ANNUAL_RETURN:g}% target)",
        "EXIT_BETTER_OPP": f"EXIT LEAP (better PMCC: {detail})" if detail else "EXIT LEAP (better opportunity in ideas)",
        "HOLD": "HOLD LEAP",
        "WATCH_DMA": "WATCH LEAP (below 200 DMA)",
    }
    return mapping.get(phase, "REVIEW LEAP")


def combine_pmcc_actions(*, leap_phase: str, short_phase: str, short_action: str, leap_detail: str = "") -> str:
    """LEAP exit overrides short hold; otherwise pair short action with income guidance."""
    if leap_phase.startswith("EXIT"):
        return leap_exit_action_for_phase(leap_phase, detail=leap_detail)
    if leap_phase == "WATCH_DMA":
        return f"{short_action}; {leap_exit_action_for_phase(leap_phase)}"
    guidance = leap_hold_guidance_for_short_phase(short_phase)
    if short_action.startswith("HOLD"):
        return f"{short_action} — {guidance}"
    return f"{short_action}; {guidance}"


def is_pmcc_highlight_action(action: str) -> bool:
    act = str(action).upper()
    keywords = ("CLOSE", "ROLL", "DEFEND", "SELL SHORT", "MANAGE", "VERIFY", "EXPIRING", "EXIT LEAP", "WATCH LEAP", "FIX STRUCTURE", "FIX BREAKEVEN")
    return any(k in act for k in keywords)


def is_pmcc_urgent_action(action: str) -> bool:
    act = str(action).upper()
    if act.startswith("HOLD"):
        return False
    keywords = ("CLOSE", "ROLL", "DEFEND", "SELL SHORT", "EXIT LEAP", "FIX STRUCTURE", "FIX BREAKEVEN")
    return any(k in act for k in keywords)
