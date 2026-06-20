# pmcc_opportunities.py
"""
PMCC entry ideas — stock screening, LEAP purchase plan, short-call sell plan.

Scans tickers from PIE_TICKERS_FILE / my_tickers.txt blob / local_list fallback.
Two-phase: quick trend/price filter, then option-chain analysis for top names.

Env:
  PMCC_OPPORTUNITIES_ENABLED=1
  PMCC_MODE=core  (core/aggressive)
  PMCC_MIN_PRICE=20  PMCC_MAX_PRICE=0 (0 = no upper cap)
  PMCC_MIN_SCORE=6.0
  PMCC_BLOCK_NEG_1Y=1
  PMCC_PREFILTER_N=50  PMCC_MAX_CANDIDATES=12
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from html import escape as _esc
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from .fundamentals import compute_company_profile, compute_quarterly_trends
from .options_metrics import days_to_next_earnings, iv_percentile_proxy
from .pie_scanner import run_scan
from .pcs_opportunities import load_pie_scan_tickers
from .pmcc_common import (
    PMCC_EARNINGS_BLOCK_DAYS,
    PMCC_LEAP_DELTA_MAX,
    PMCC_LEAP_DELTA_MIN,
    PMCC_LEAP_DELTA_TARGET,
    PMCC_LEAP_MAX_DTE,
    PMCC_LEAP_MIN_DTE,
    PMCC_LEAP_TARGET_DTE,
    PMCC_MAX_EXTRINSIC_PCT,
    PMCC_MODE,
    PMCC_SHORT_DELTA_MAX,
    PMCC_SHORT_DELTA_MIN,
    PMCC_SHORT_DELTA_TARGET,
    PMCC_SHORT_MAX_DTE_WIN,
    PMCC_SHORT_MAX_SPREAD_PCT,
    PMCC_SHORT_MIN_DTE_WIN,
    PMCC_SHORT_MIN_OI,
    bs_call_delta,
    choose_expiry,
    extrinsic_pct,
    has_weekly_expiries,
    leg_is_liquid,
    mid_price,
    pmcc_structure_ok,
    pmcc_trade_metrics,
    pmcc_income_score,
    short_leg_pick_score,
    spread_pct,
    PMCC_MIN_MONTHLY_ON_DEBIT,
)

logger = logging.getLogger(__name__)

PMCC_MIN_PRICE = float(os.getenv("PMCC_MIN_PRICE", "20"))
PMCC_MAX_PRICE = float(os.getenv("PMCC_MAX_PRICE", "0"))
PMCC_SWEET_MIN = float(os.getenv("PMCC_SWEET_MIN", "30"))
PMCC_SWEET_MAX = float(os.getenv("PMCC_SWEET_MAX", "100"))

PMCC_MIN_SCORE = float(os.getenv("PMCC_MIN_SCORE", "6.0"))
PMCC_PREFILTER_N = int(os.getenv("PMCC_PREFILTER_N", "120"))
PMCC_MAX_CHAIN_ANALYSIS = int(os.getenv("PMCC_MAX_CHAIN_ANALYSIS", "80"))
PMCC_MAX_CANDIDATES = int(os.getenv("PMCC_MAX_CANDIDATES", "12"))

PMCC_MIN_OI = int(os.getenv("PMCC_MIN_OI", "50"))
PMCC_LEAP_MIN_OI = int(os.getenv("PMCC_LEAP_MIN_OI", "50"))
PMCC_LEAP_MAX_SPREAD_PCT = float(os.getenv("PMCC_LEAP_MAX_SPREAD_PCT", "0.10"))
PMCC_MAX_SPREAD_PCT = float(os.getenv("PMCC_MAX_SPREAD_PCT", "0.08"))

PMCC_MIN_REV_GROWTH = float(os.getenv("PMCC_MIN_REV_GROWTH", "0.15"))
PMCC_BLOCK_FUND_FAIL = os.getenv("PMCC_BLOCK_FUND_FAIL", "1") == "1"
PMCC_MIN_MARKET_CAP = float(os.getenv("PMCC_MIN_MARKET_CAP", "1e9"))
PMCC_MAX_PS = float(os.getenv("PMCC_MAX_PS", "40"))

PMCC_BLOCK_EARNINGS = os.getenv("PMCC_BLOCK_EARNINGS", "1") == "1"
PMCC_BLOCK_NEG_1Y = os.getenv("PMCC_BLOCK_NEG_1Y", "1") == "1"

BENCHMARK = os.getenv("PMCC_BENCHMARK", "SPY")

BIOTECH_KEYWORDS = ("biotech", "biotechnology", "pharmaceutical", "drug manufacturers")

SIGNAL_RANK = {"BUY": 0, "HOLD": 1, "WATCH": 2, "": 3}
GRADE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3, "": 4}


def _price_ok(price: float) -> bool:
    if price != price or price < PMCC_MIN_PRICE:
        return False
    if PMCC_MAX_PRICE > 0 and price > PMCC_MAX_PRICE:
        return False
    return True


def _trend_lookup(trend: pd.DataFrame) -> Dict[str, pd.Series]:
    if trend.empty:
        return {}
    return {str(r["Ticker"]).upper(): r for _, r in trend.iterrows()}


def _chain_analysis_pool(pre: pd.DataFrame) -> pd.DataFrame:
    if pre.empty:
        return pre

    df = pre.copy()
    df["_gr"] = df["Grade"].astype(str).str.upper().map(lambda g: GRADE_RANK.get(g, 4))
    df["_sr"] = df["Signal"].astype(str).str.upper().map(lambda s: SIGNAL_RANK.get(s, 3))
    df["_tp"] = pd.to_numeric(df["TrendPts"], errors="coerce").fillna(0)

    ranked = df.sort_values(
        ["_gr", "_sr", "Prefilter", "_tp"],
        ascending=[True, True, False, False],
    )

    return ranked.head(PMCC_MAX_CHAIN_ANALYSIS).drop(columns=["_gr", "_sr", "_tp"])


def _trend_prefilter(tickers: List[str]) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()

    end = datetime.today()
    start = end - timedelta(days=420)
    all_syms = sorted(set(tickers) | {BENCHMARK})

    try:
        data = yf.download(all_syms, start=start, end=end, auto_adjust=True, progress=False)
    except Exception as e:
        logger.warning("[pmcc] download failed: %s", e)
        return pd.DataFrame()

    if data is None or data.empty:
        return pd.DataFrame()

    close = data["Close"]

    if BENCHMARK not in close.columns:
        return pd.DataFrame()

    bench = close[BENCHMARK]
    rows = []

    for sym in tickers:
        if sym == BENCHMARK or sym not in close.columns:
            continue

        try:
            s = close[sym].dropna()

            if len(s) < 50:
                continue

            dma50 = float(s.rolling(50).mean().iloc[-1])
            dma200 = float(s.rolling(200).mean().iloc[-1]) if len(s) >= 200 else float("nan")
            rs = float(s.pct_change(20).iloc[-1] - bench.pct_change(20).iloc[-1])
            price = float(s.iloc[-1])

            if not _price_ok(price):
                continue

            above50 = price > dma50
            above200 = price > dma200 if dma200 == dma200 else False

            trend_pts = (
                (2 if above200 else 0)
                + (2 if above50 else 0)
                + (2 if rs > 0 else 0)
            )

            price_pts = 2 if PMCC_SWEET_MIN <= price <= PMCC_SWEET_MAX else 1

            rows.append(
                {
                    "Ticker": sym,
                    "Price": round(price, 2),
                    "DMA50": round(dma50, 2),
                    "DMA200": round(dma200, 2),
                    "RS%": round(rs * 100, 2),
                    "Above50": above50,
                    "Above200": above200,
                    "TrendPts": trend_pts,
                    "PricePts": price_pts,
                    "Prefilter": trend_pts + price_pts,
                }
            )
        except Exception:
            continue

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    return df.sort_values("Prefilter", ascending=False).head(PMCC_PREFILTER_N)


def _build_pmcc_pool(tickers: List[str], scan: pd.DataFrame, trend: pd.DataFrame) -> pd.DataFrame:
    grade_boost = {"A": 20, "B": 16, "C": 12, "D": 6}

    cols = [
        "Ticker",
        "Price",
        "Prefilter",
        "TrendPts",
        "PricePts",
        "RS%",
        "Above50",
        "Above200",
        "DMA50",
        "DMA200",
        "Grade",
        "Signal",
    ]

    trend_by_sym = _trend_lookup(trend)
    scan_rows: List[dict] = []

    if not scan.empty:
        pool_scan = scan[~scan["Signal"].isin(["REDUCE", "SELL"])].copy()
        pool_scan = pool_scan[pool_scan["Price"].astype(float).apply(_price_ok)]

        for _, r in pool_scan.iterrows():
            g = str(r.get("Grade", "D")).upper()
            sym = str(r["Ticker"]).upper()
            trow = trend_by_sym.get(sym)

            scan_rows.append(
                {
                    "Ticker": sym,
                    "Price": round(float(r["Price"]), 2),
                    "Prefilter": grade_boost.get(g, 6),
                    "TrendPts": int(trow["TrendPts"]) if trow is not None and trow.get("TrendPts") == trow.get("TrendPts") else 4,
                    "PricePts": int(trow["PricePts"]) if trow is not None and trow.get("PricePts") == trow.get("PricePts") else 2,
                    "RS%": round(float(trow["RS%"]), 2) if trow is not None and trow.get("RS%") == trow.get("RS%") else None,
                    "Above50": bool(trow["Above50"]) if trow is not None and trow.get("Above50") is not None else None,
                    "Above200": bool(trow["Above200"]) if trow is not None and trow.get("Above200") is not None else None,
                    "DMA50": round(float(trow["DMA50"]), 2) if trow is not None and trow.get("DMA50") == trow.get("DMA50") else None,
                    "DMA200": round(float(trow["DMA200"]), 2) if trow is not None and trow.get("DMA200") == trow.get("DMA200") else np.nan,
                    "Grade": g,
                    "Signal": str(r.get("Signal", "")),
                }
            )

    scan_df = pd.DataFrame(scan_rows)

    if not scan_df.empty:
        scan_df = scan_df.sort_values(["Prefilter", "TrendPts"], ascending=[False, False])

    trend_df = trend.copy() if not trend.empty else pd.DataFrame()

    if not trend_df.empty:
        for c in ("Grade", "Signal"):
            if c not in trend_df.columns:
                trend_df[c] = ""

        trend_df = trend_df[[c for c in cols if c in trend_df.columns]]

    if scan_df.empty and trend_df.empty:
        return pd.DataFrame()

    if scan_df.empty:
        merged = trend_df
    elif trend_df.empty:
        merged = scan_df
    else:
        seen = set(scan_df["Ticker"])
        trend_extra = trend_df[~trend_df["Ticker"].isin(seen)].copy()

        for c in cols:
            if c not in trend_extra.columns:
                trend_extra[c] = np.nan if c == "DMA200" else ""

        trend_extra = trend_extra[cols]
        merged = pd.concat([scan_df[cols], trend_extra], ignore_index=True)

    return merged.head(PMCC_PREFILTER_N)


def _enrich_prefilter_with_scan(prefilter: pd.DataFrame, tickers: List[str]) -> pd.DataFrame:
    if not tickers:
        return prefilter

    try:
        scan = run_scan(tickers)
        return _build_pmcc_pool(tickers, scan, prefilter)
    except Exception as e:
        logger.info("[pmcc] pool build failed: %s", e)
        return prefilter


def _batch_return_metrics(symbols: List[str]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}

    if not symbols:
        return out

    end = datetime.today()
    start = end - timedelta(days=420)

    try:
        data = yf.download(symbols, start=start, end=end, auto_adjust=True, progress=False)
    except Exception as e:
        logger.warning("[pmcc] return batch failed: %s", e)
        return out

    if data is None or data.empty:
        return out

    close = data["Close"]

    if isinstance(close, pd.Series):
        sym = symbols[0] if symbols else ""
        s = close.dropna()

        if len(s) >= 64:
            out[sym] = {
                "ret_63": float(s.pct_change(63).iloc[-1]),
                "ret_252": float(s.pct_change(min(252, len(s) - 1)).iloc[-1]),
            }

        return out

    for sym in symbols:
        if sym not in close.columns:
            continue

        s = close[sym].dropna()

        if len(s) < 64:
            continue

        lookback = min(252, len(s) - 1)

        out[sym] = {
            "ret_63": float(s.pct_change(63).iloc[-1]),
            "ret_252": float(s.pct_change(lookback).iloc[-1]),
        }

    return out


def _load_fundamentals(symbol: str, cache: Dict[str, dict]) -> dict:
    sym = symbol.upper()

    if sym in cache:
        return cache[sym]

    row: dict = {
        "rev_growth": float("nan"),
        "earn_growth": float("nan"),
        "profit_margin": float("nan"),
        "ps_ratio": float("nan"),
        "market_cap": float("nan"),
        "rev_q_yoy": 0.0,
        "earn_q_yoy": 0.0,
        "growth_streak": 0.0,
        "verdict": "WARN",
        "notes": "",
        "sector": "",
        "industry": "",
    }

    try:
        info = yf.Ticker(sym).info or {}
        profile = compute_company_profile(sym)
        qt = compute_quarterly_trends(sym)

        row["rev_growth"] = profile.get("revenue_growth", float("nan"))
        row["earn_growth"] = profile.get("earnings_growth", float("nan"))
        row["profit_margin"] = float(info.get("profitMargins") or float("nan"))
        row["ps_ratio"] = float(info.get("priceToSalesTrailing12Months") or float("nan"))
        row["market_cap"] = float(info.get("marketCap") or float("nan"))
        row["rev_q_yoy"] = float(qt.get("rev_q_yoy") or 0.0)
        row["earn_q_yoy"] = float(qt.get("earn_q_yoy") or 0.0)
        row["growth_streak"] = float(qt.get("growth_streak") or 0.0)
        row["sector"] = str(info.get("sector") or "").lower()
        row["industry"] = str(info.get("industry") or "").lower()

        rev = row["rev_growth"] if row["rev_growth"] == row["rev_growth"] else row["rev_q_yoy"]
        mcap = row["market_cap"]
        margin = row["profit_margin"]
        ps = row["ps_ratio"]

        fails: List[str] = []

        if mcap == mcap and mcap < PMCC_MIN_MARKET_CAP:
            fails.append(f"mcap<{PMCC_MIN_MARKET_CAP / 1e9:.0f}B")

        if rev == rev and rev < 0:
            fails.append("rev shrink")

        if ps == ps and ps > PMCC_MAX_PS:
            fails.append(f"P/S>{PMCC_MAX_PS:g}")

        if fails:
            row["verdict"] = "FAIL"
            row["notes"] = "; ".join(fails)
        elif margin == margin and margin < 0:
            row["verdict"] = "WARN"
            row["notes"] = "unprofitable"
        else:
            row["verdict"] = "PASS"

    except Exception as e:
        row["notes"] = str(e)

    cache[sym] = row
    return row


def _leap_thesis_score(ret_63: float, ret_252: float, fund: dict) -> tuple[float, str]:
    score = 4.0
    notes: List[str] = []

    if ret_252 == ret_252:
        notes.append(f"1Y={ret_252 * 100:.0f}%")

        if ret_252 >= 0.50:
            score += 3.0
        elif ret_252 >= 0.25:
            score += 2.0
        elif ret_252 >= 0.10:
            score += 1.0
        elif ret_252 < 0:
            score -= 2.0

    if ret_63 == ret_63:
        notes.append(f"3M={ret_63 * 100:.0f}%")

        if ret_63 >= 0.20:
            score += 2.0
        elif ret_63 >= 0.05:
            score += 1.0
        elif ret_63 < -0.10:
            score -= 1.0

    rev_yoy = float(fund.get("rev_q_yoy") or 0.0)
    earn_yoy = float(fund.get("earn_q_yoy") or 0.0)

    if rev_yoy >= PMCC_MIN_REV_GROWTH:
        score += 1.0
        notes.append(f"revYoY={rev_yoy * 100:.0f}%")

    if earn_yoy >= 0.10:
        score += 0.5

    if float(fund.get("growth_streak") or 0) >= 1:
        score += 0.5

    return min(max(score, 0.0), 10.0), "; ".join(notes)


def _fundamentals_score(fund: dict) -> tuple[float, str]:
    score = 5.0
    notes: List[str] = []

    rev = fund.get("rev_growth")

    if rev != rev or rev == 0:
        rev = fund.get("rev_q_yoy", float("nan"))

    earn = fund.get("earn_growth")

    if earn != earn:
        earn = fund.get("earn_q_yoy", float("nan"))

    margin = fund.get("profit_margin", float("nan"))
    ps = fund.get("ps_ratio", float("nan"))
    mcap = fund.get("market_cap", float("nan"))

    if rev == rev:
        notes.append(f"rev={rev * 100:.0f}%")

        if rev >= PMCC_MIN_REV_GROWTH:
            score += 2.0
        elif rev >= 0.05:
            score += 1.0
        elif rev < 0:
            score -= 2.0

    if earn == earn:
        notes.append(f"earn={earn * 100:.0f}%")

        if earn >= 0.15:
            score += 1.5
        elif earn >= 0:
            score += 0.5
        elif earn < -0.20:
            score -= 1.0

    if margin == margin:
        notes.append(f"margin={margin * 100:.0f}%")

        if margin >= 0.15:
            score += 1.5
        elif margin >= 0.05:
            score += 0.5
        elif margin < 0:
            score -= 1.0

    if ps == ps:
        notes.append(f"P/S={ps:.1f}")

        if 2 <= ps <= 20:
            score += 1.0
        elif ps > PMCC_MAX_PS:
            score -= 2.0
        elif ps > 25:
            score -= 0.5

    if mcap == mcap:
        if mcap >= 10e9:
            score += 0.5
        elif mcap < 2e9:
            score -= 1.0

    sector = str(fund.get("sector") or "")
    industry = str(fund.get("industry") or "")

    if any(k in sector or k in industry for k in BIOTECH_KEYWORDS):
        score = min(score, 4.0)
        notes.append("biotech-flag")

    if fund.get("verdict") == "FAIL":
        score = min(score, 3.0)

    return min(max(score, 0.0), 10.0), "; ".join(notes)


def _pick_leap_leg(calls: pd.DataFrame, spot: float, dte: int) -> Optional[dict]:
    if calls is None or calls.empty:
        return None

    liquid = calls[
        calls.apply(
            lambda r: leg_is_liquid(
                r,
                min_oi=PMCC_LEAP_MIN_OI,
                max_spread_pct=PMCC_LEAP_MAX_SPREAD_PCT,
            ),
            axis=1,
        )
    ]

    itm = liquid[liquid["strike"].astype(float) < spot * 0.98]

    if itm.empty:
        return None

    best = None
    best_delta_dist = float("inf")

    for _, row in itm.iterrows():
        strike = float(row["strike"])
        iv = float(row.get("impliedVolatility") or 0.0)

        if iv <= 0:
            continue

        delta = bs_call_delta(spot, strike, dte, iv)

        if delta != delta or delta < PMCC_LEAP_DELTA_MIN or delta > PMCC_LEAP_DELTA_MAX:
            continue

        mid = mid_price(row)

        if mid <= 0:
            continue

        ext_pct = extrinsic_pct(spot, strike, mid)

        if ext_pct != ext_pct or ext_pct > PMCC_MAX_EXTRINSIC_PCT:
            continue

        dist = abs(delta - PMCC_LEAP_DELTA_TARGET)

        if dist < best_delta_dist:
            best_delta_dist = dist
            best = {
                "strike": strike,
                "mid": round(mid, 2),
                "delta": round(delta, 2),
                "ext_pct": round(ext_pct * 100, 1),
                "oi": _safe_oi(row),
                "iv_pct": round(iv * 100, 1),
            }

    return best


def _pmcc_structure_ok(leap: dict, short: dict) -> bool:
    return pmcc_structure_ok(
        leap_strike=float(leap["strike"]),
        leap_debit=float(leap["mid"]),
        short_strike=float(short["strike"]),
        short_credit=float(short["credit"]),
    )


def _pmcc_metrics(leap: dict, short: dict, spot: float, short_dte: int) -> dict:
    return pmcc_trade_metrics(
        leap_strike=float(leap["strike"]),
        leap_debit=float(leap["mid"]),
        short_strike=float(short["strike"]),
        short_credit=float(short["credit"]),
        spot=spot,
        short_dte=short_dte,
    )


def _safe_oi(row) -> int:
    raw = row.get("openInterest")
    if raw is None or (isinstance(raw, float) and raw != raw):
        return 0
    return int(raw or 0)


def _pick_short_call_relaxed(
    calls: pd.DataFrame,
    spot: float,
    dte: int,
    leap: dict,
) -> Optional[dict]:
    if calls is None or calls.empty:
        return None

    otm = calls[calls["strike"].astype(float) > spot * 1.005]
    best = None
    best_rank = float("-inf")

    for _, row in otm.iterrows():
        bid = float(row.get("bid") or 0.0)
        ask = float(row.get("ask") or 0.0)

        if bid <= 0 or ask <= 0:
            continue

        oi = _safe_oi(row)

        if oi < 10:
            continue

        strike = float(row["strike"])
        iv = float(row.get("impliedVolatility") or 0.0)

        if iv <= 0:
            continue

        delta = bs_call_delta(spot, strike, dte, iv)

        if delta != delta or delta < PMCC_SHORT_DELTA_MIN or delta > PMCC_SHORT_DELTA_MAX:
            continue

        mid = mid_price(row)

        if mid <= 0:
            continue

        sp = spread_pct(row)

        if sp == sp and sp > 0.15:
            continue

        short = {
            "strike": strike,
            "credit": round(mid, 2),
            "delta": round(delta, 2),
            "oi": oi,
            "iv_pct": round(iv * 100, 1),
        }

        if not _pmcc_structure_ok(leap, short):
            continue

        metrics = _pmcc_metrics(leap, short, spot, dte)
        short.update(metrics)
        short["monthly_pct"] = metrics["MonthlyOnDebit%"]

        rank = short_leg_pick_score(short, delta=delta)

        if rank > best_rank:
            best_rank = rank
            best = short

    return best


def _pick_short_call(
    calls: pd.DataFrame,
    spot: float,
    dte: int,
    leap: dict,
) -> Optional[dict]:
    if calls is None or calls.empty:
        return None

    liquid = calls[
        calls.apply(
            lambda r: leg_is_liquid(
                r,
                min_oi=PMCC_SHORT_MIN_OI,
                max_spread_pct=PMCC_SHORT_MAX_SPREAD_PCT,
            ),
            axis=1,
        )
    ]

    otm = liquid[liquid["strike"].astype(float) > spot * 1.01]

    if otm.empty:
        return None

    best = None
    best_rank = float("-inf")

    for _, row in otm.iterrows():
        strike = float(row["strike"])
        iv = float(row.get("impliedVolatility") or 0.0)

        if iv <= 0:
            continue

        delta = bs_call_delta(spot, strike, dte, iv)

        if delta != delta or delta < PMCC_SHORT_DELTA_MIN or delta > PMCC_SHORT_DELTA_MAX:
            continue

        mid = mid_price(row)

        if mid <= 0:
            continue

        short = {
            "strike": strike,
            "credit": round(mid, 2),
            "delta": round(delta, 2),
            "oi": _safe_oi(row),
            "iv_pct": round(iv * 100, 1),
        }

        if not _pmcc_structure_ok(leap, short):
            continue

        metrics = _pmcc_metrics(leap, short, spot, dte)
        short.update(metrics)
        short["monthly_pct"] = metrics["MonthlyOnDebit%"]

        rank = short_leg_pick_score(short, delta=delta)
        if _safe_oi(row) < PMCC_MIN_OI:
            rank -= 0.5

        if rank > best_rank:
            best_rank = rank
            best = short

    return best


def _fundamentals_blocked(sym: str, fund: dict) -> bool:
    if PMCC_MODE == "aggressive":
        return False

    return PMCC_BLOCK_FUND_FAIL and fund.get("verdict") == "FAIL"


def _analyze_symbol(
    row: pd.Series,
    *,
    returns_map: Dict[str, dict],
    fund_cache: Dict[str, dict],
) -> Optional[dict]:
    sym = str(row["Ticker"]).upper()
    spot = float(row["Price"])

    rets = returns_map.get(sym, {})
    ret_63 = rets.get("ret_63", float("nan"))
    ret_252 = rets.get("ret_252", float("nan"))

    if PMCC_BLOCK_NEG_1Y and ret_252 == ret_252 and ret_252 < 0:
        logger.info("[pmcc] %s blocked — negative 1Y return (%.1f%%)", sym, ret_252 * 100)
        return None

    try:
        tk = yf.Ticker(sym)
        expiries = list(tk.options or [])
    except Exception:
        return None

    if not expiries:
        return None

    today = datetime.today().date()

    leap_exp, leap_dte = choose_expiry(
        expiries,
        min_dte=PMCC_LEAP_MIN_DTE,
        max_dte=PMCC_LEAP_MAX_DTE,
        target_dte=PMCC_LEAP_TARGET_DTE,
        today=today,
    )

    short_exp, short_dte = choose_expiry(
        expiries,
        min_dte=PMCC_SHORT_MIN_DTE_WIN,
        max_dte=PMCC_SHORT_MAX_DTE_WIN,
        today=today,
    )

    if not leap_exp:
        return None

    fund = _load_fundamentals(sym, fund_cache)

    if _fundamentals_blocked(sym, fund):
        logger.info("[pmcc] %s blocked — fundamentals FAIL (%s)", sym, fund.get("notes"))
        return None

    leap_thesis, leap_note = _leap_thesis_score(ret_63, ret_252, fund)
    fund_score, fund_note = _fundamentals_score(fund)

    if PMCC_MODE == "aggressive":
        fund_score = max(fund_score, 5.0)

    weekly = has_weekly_expiries(expiries, today=today)

    try:
        leap_calls = tk.option_chain(leap_exp).calls
    except Exception:
        return None

    leap = _pick_leap_leg(leap_calls, spot, leap_dte or 0)

    if not leap:
        return None

    short = None
    short_expiry_used: Optional[str] = None
    short_dte_used: Optional[int] = None
    best_short_rank = float("-inf")

    short_exp_candidates: List[str] = []

    if short_exp:
        short_exp_candidates.append(short_exp)

    for exp in expiries:
        try:
            dte = (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
        except Exception:
            continue

        if 25 <= dte <= 55 and exp not in short_exp_candidates:
            short_exp_candidates.append(exp)

    for exp in short_exp_candidates[:8]:
        try:
            dte = (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
            short_calls = tk.option_chain(exp).calls
        except Exception:
            continue

        candidate = _pick_short_call(short_calls, spot, dte, leap)
        if candidate is None:
            candidate = _pick_short_call_relaxed(short_calls, spot, dte, leap)

        if not candidate:
            continue

        pick_rank = short_leg_pick_score(candidate, delta=float(candidate["delta"]))
        if pick_rank > best_short_rank:
            best_short_rank = pick_rank
            short = candidate
            short_expiry_used = exp
            short_dte_used = dte

    if not short:
        return None

    monthly_on_debit = float(short.get("MonthlyOnDebit%") or 0.0)
    if monthly_on_debit == monthly_on_debit and monthly_on_debit < PMCC_MIN_MONTHLY_ON_DEBIT:
        logger.info(
            "[pmcc] %s blocked — short income %.2f%%/mo on debit < %.2f%%",
            sym,
            monthly_on_debit,
            PMCC_MIN_MONTHLY_ON_DEBIT,
        )
        return None

    try:
        short_calls = tk.option_chain(short_expiry_used).calls
    except Exception:
        short_calls = pd.DataFrame()

    ivp = iv_percentile_proxy(short_calls, spot)

    atm = short_calls.iloc[(short_calls["strike"].astype(float) - spot).abs().argsort()[:1]]
    atm_oi = int(atm.iloc[0].get("openInterest") or 0) if not atm.empty else 0
    atm_spread = spread_pct(atm.iloc[0]) if not atm.empty else float("nan")

    liq_score = 3.0

    if weekly:
        liq_score += 2.0

    if atm_oi >= 1000:
        liq_score += 3.0
    elif atm_oi >= 500:
        liq_score += 2.0
    elif atm_oi >= 100:
        liq_score += 1.0

    if atm_spread == atm_spread and atm_spread <= 0.05:
        liq_score += 2.0

    liq_score = min(liq_score, 10.0)

    iv_score = 5.0

    try:
        iv_med = float(np.nanmedian(short_calls["impliedVolatility"].astype(float))) * 100
    except Exception:
        iv_med = float("nan")

    if ivp == ivp and ivp >= 0.30:
        iv_score += 2.0

    if iv_med == iv_med and 40 <= iv_med <= 80:
        iv_score += 2.0

    iv_score = min(iv_score, 10.0)

    trend_score = min(float(row.get("TrendPts", 0)) * 1.25, 10.0)
    income_score = pmcc_income_score(monthly_on_debit)

    total = (
        0.25 * leap_thesis
        + 0.25 * fund_score
        + 0.20 * income_score
        + 0.10 * liq_score
        + 0.10 * iv_score
        + 0.10 * trend_score
    )

    if total < PMCC_MIN_SCORE:
        return None

    if PMCC_BLOCK_EARNINGS:
        dte_earn = days_to_next_earnings(sym)

        if dte_earn is not None and 0 <= dte_earn <= PMCC_EARNINGS_BLOCK_DAYS:
            logger.info("[pmcc] %s blocked — earnings within %s days", sym, PMCC_EARNINGS_BLOCK_DAYS)
            return None

    return {
        "Ticker": sym,
        "Price": spot,
        "Score": round(total, 1),
        "LeapThesis": round(leap_thesis, 1),
        "Fund": round(fund_score, 1),
        "Income": round(income_score, 1),
        "FundVerdict": fund.get("verdict", ""),
        "Ret1Y%": round(ret_252 * 100, 1) if ret_252 == ret_252 else None,
        "Ret3M%": round(ret_63 * 100, 1) if ret_63 == ret_63 else None,
        "Margin%": round(fund["profit_margin"] * 100, 1) if fund.get("profit_margin") == fund.get("profit_margin") else None,
        "P/S": round(fund["ps_ratio"], 1) if fund.get("ps_ratio") == fund.get("ps_ratio") else None,
        "Liq": round(liq_score, 1),
        "IV": round(iv_score, 1),
        "Trend": round(trend_score, 1),
        "Weekly": "Y" if weekly else "N",
        "RS%": row.get("RS%"),
        "Grade": row.get("Grade", ""),
        "Signal": row.get("Signal", ""),
        "LeapNote": leap_note,
        "FundNote": fund_note,
        "LeapExp": leap_exp,
        "LeapDTE": leap_dte,
        "LeapStrike": leap["strike"],
        "LeapDebit": leap["mid"],
        "LeapDelta": leap["delta"],
        "LeapExt%": leap["ext_pct"],
        "LeapOI": leap["oi"],
        "ShortExp": short_expiry_used,
        "ShortDTE": short_dte_used,
        "ShortStrike": short["strike"],
        "ShortCredit": short["credit"],
        "ShortDelta": short["delta"],
        "ShortMonthly%": short["monthly_pct"],
        "ShortOI": short["oi"],
        "IV%": round(iv_med, 1) if iv_med == iv_med else None,
        "NetDebit": short["NetDebit"],
        "MaxRisk": short["MaxRisk"],
        "Breakeven": short["Breakeven"],
        "UpsideRoom%": short["UpsideRoom%"],
        "MonthlyOnDebit%": short["MonthlyOnDebit%"],
        "AnnualizedOnDebit%": short["AnnualizedOnDebit%"],
    }


def run_pmcc_opportunities() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "enabled": True,
        "html": "",
        "tickers": [],
        "rows": [],
        "scanned": 0,
        "prefiltered": 0,
    }

    if os.getenv("PMCC_OPPORTUNITIES_ENABLED", "1") != "1":
        out["enabled"] = False
        return out

    tickers = load_pie_scan_tickers()
    out["scanned"] = len(tickers)

    if not tickers:
        out["html"] = "<p><i>No scan tickers — set PIE_TICKERS_FILE or upload my_tickers.txt.</i></p>"
        return out

    trend = _trend_prefilter(tickers)
    scan = run_scan(tickers)
    pre = _build_pmcc_pool(tickers, scan, trend)
    out["prefiltered"] = len(pre)

    if pre.empty:
        out["html"] = (
            f"<p>Scanned {len(tickers)} symbols · "
            f"<i>none passed price prefilter min ${PMCC_MIN_PRICE:g}"
            + (f", max ${PMCC_MAX_PRICE:g}" if PMCC_MAX_PRICE > 0 else ", no max")
            + ".</i></p>"
        )
        return out

    rows: List[dict] = []
    chain_pool = _chain_analysis_pool(pre)
    symbols = [str(r["Ticker"]).upper() for _, r in chain_pool.iterrows()]
    returns_map = _batch_return_metrics(symbols)
    fund_cache: Dict[str, dict] = {}

    for _, r in chain_pool.iterrows():
        try:
            plan = _analyze_symbol(r, returns_map=returns_map, fund_cache=fund_cache)

            if plan:
                rows.append(plan)
        except Exception as e:
            logger.info("[pmcc] %s analyze failed: %s", r.get("Ticker"), e)

    rows.sort(
        key=lambda x: (float(x.get("Score") or 0), float(x.get("MonthlyOnDebit%") or 0)),
        reverse=True,
    )
    rows = rows[:PMCC_MAX_CANDIDATES]

    out["rows"] = rows
    out["tickers"] = [r["Ticker"] for r in rows]
    out["mode"] = PMCC_MODE
    out["html"] = format_pmcc_opportunities_html(rows, scanned=len(tickers), prefiltered=len(pre))

    return out


PMCC_TABLE_COLS = [
    "Ticker",
    "Grade",
    "Signal",
    "Price",
    "Score",
    "Ret1Y%",
    "Ret3M%",
    "LeapExp",
    "LeapStrike",
    "LeapDebit",
    "LeapDelta",
    "ShortExp",
    "ShortStrike",
    "ShortCredit",
    "ShortDelta",
    "NetDebit",
    "Breakeven",
    "MaxRisk",
    "UpsideRoom%",
    "MonthlyOnDebit%",
    "AnnualizedOnDebit%",
]


def _fmt_pmcc(col: str, val) -> str:
    if val is None or val == "":
        return ""

    try:
        if isinstance(val, float) and val != val:
            return ""
    except TypeError:
        pass

    if col in (
        "Price",
        "LeapDebit",
        "ShortCredit",
        "LeapStrike",
        "ShortStrike",
        "NetDebit",
        "Breakeven",
    ):
        try:
            return f"{float(val):.2f}"
        except (TypeError, ValueError):
            return str(val)

    if col in ("LeapDelta", "ShortDelta"):
        try:
            return f"{float(val):.2f}"
        except (TypeError, ValueError):
            return str(val)

    if col in (
        "Score",
        "Ret1Y%",
        "Ret3M%",
        "ShortMonthly%",
        "UpsideRoom%",
        "MonthlyOnDebit%",
        "AnnualizedOnDebit%",
        "MaxRisk",
    ):
        try:
            fval = float(val)

            if fval != fval:
                return ""

            return f"{fval:.1f}"
        except (TypeError, ValueError):
            return str(val)

    return str(val)


def format_pmcc_opportunities_html(
    rows: List[dict],
    *,
    scanned: int,
    prefiltered: int,
) -> str:
    if not rows:
        return (
            f"<p>Scanned {scanned} · prefiltered {prefiltered} price/trend · "
            f"<i>no PMCC plans passed score ≥{PMCC_MIN_SCORE:g} and chain filters.</i></p>"
        )

    head = "".join(f"<th align='left'>{_esc(c)}</th>" for c in PMCC_TABLE_COLS)
    body = []

    for r in rows:
        tds = "".join(f"<td>{_esc(_fmt_pmcc(c, r.get(c)))}</td>" for c in PMCC_TABLE_COLS)
        body.append(f"<tr>{tds}</tr>")

    table = (
        "<table border='1' cellspacing='0' cellpadding='4' "
        "style='border-collapse:collapse;font-family:ui-monospace,monospace;font-size:12px'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )

    return (
        f"<p><b>PMCC IDEAS</b> — {scanned} scanned, {prefiltered} prefiltered, "
        f"{len(rows)} passed score ≥{PMCC_MIN_SCORE:g}. Mode={_esc(PMCC_MODE)}.</p>"
        f"{table}"
        "<p style='font-size:11px;color:#666'>"
        "Score weights: thesis 25%, fundamentals 25%, short income 20%, liquidity 10%, IV 10%, trend 10%. "
        "Short call picked for max premium (MonthlyOnDebit%) within Δ 0.15–0.25 across 25–55 DTE expiries. "
        "Long LEAP: 18–30mo, Δ 0.80–0.95, low extrinsic. "
        "PMCC structure requires short strike > long strike + net debit. "
        "MonthlyOnDebit% = short credit / LEAPS debit. "
        "Close short at 50% profit. Verify chain before trading."
        "</p>"
    )


def format_pmcc_opportunities_text(rows: List[dict], *, scanned: int, prefiltered: int) -> str:
    lines = [
        f"Scanned {scanned} · prefiltered {prefiltered} · {len(rows)} PMCC ideas · mode={PMCC_MODE}",
        "",
    ]

    if not rows:
        lines.append("  None passed filters.")
        return "\n".join(lines)

    for r in rows:
        lines.append(
            f"  {r.get('Ticker','')} Grade={r.get('Grade','')} Signal={r.get('Signal','')} "
            f"score={r.get('Score','')} 1Y={r.get('Ret1Y%','')}% 3M={r.get('Ret3M%','')}% "
            f"LEAP {r.get('LeapExp','')} {r.get('LeapStrike','')} @ {r.get('LeapDebit','')} "
            f"Δ={r.get('LeapDelta','')} | short {r.get('ShortExp','')} "
            f"{r.get('ShortStrike','')} cr {r.get('ShortCredit','')} "
            f"Δ={r.get('ShortDelta','')} netDebit={r.get('NetDebit','')} "
            f"BE={r.get('Breakeven','')} risk=${r.get('MaxRisk','')} "
            f"moDebit%={r.get('MonthlyOnDebit%','')} annDebit%={r.get('AnnualizedOnDebit%','')}"
        )

    lines.append("")
    lines.append("Close short at 50% profit. Verify option chain before trading.")

    return "\n".join(lines)


def format_pmcc_opportunities_result_text(result: Dict[str, Any]) -> str:
    return format_pmcc_opportunities_text(
        list(result.get("rows") or []),
        scanned=int(result.get("scanned") or 0),
        prefiltered=int(result.get("prefiltered") or 0),
    )