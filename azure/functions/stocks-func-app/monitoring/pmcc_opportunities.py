"""
PMCC entry ideas — stock screening, LEAP purchase plan, short-call sell plan.

Scans tickers from PIE_TICKERS_FILE / my_tickers.txt blob / local_list fallback.
Two-phase: quick trend/price filter, then option-chain analysis for top names.

Env:
  PMCC_OPPORTUNITIES_ENABLED=1
  PMCC_MIN_PRICE=20  PMCC_MAX_PRICE=200
  PMCC_MIN_SCORE=6.0
  PMCC_PREFILTER_N=50  PMCC_MAX_CANDIDATES=12
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from html import escape as _esc
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from .options_metrics import days_to_next_earnings, iv_percentile_proxy
from .pie_scanner import run_scan
from .pcs_opportunities import load_pie_scan_tickers
from .pmcc_common import (
    PMCC_LEAP_DELTA_MAX,
    PMCC_LEAP_DELTA_MIN,
    PMCC_LEAP_DELTA_TARGET,
    PMCC_LEAP_MAX_DTE,
    PMCC_LEAP_MIN_DTE,
    PMCC_LEAP_TARGET_DTE,
    PMCC_MAX_EXTRINSIC_PCT,
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
    spread_pct,
)

logger = logging.getLogger(__name__)

PMCC_MIN_PRICE = float(os.getenv("PMCC_MIN_PRICE", "20"))
PMCC_MAX_PRICE = float(os.getenv("PMCC_MAX_PRICE", "200"))
PMCC_SWEET_MIN = float(os.getenv("PMCC_SWEET_MIN", "30"))
PMCC_SWEET_MAX = float(os.getenv("PMCC_SWEET_MAX", "100"))
PMCC_MIN_SCORE = float(os.getenv("PMCC_MIN_SCORE", "5.5"))
PMCC_PREFILTER_N = int(os.getenv("PMCC_PREFILTER_N", "80"))
PMCC_MAX_CHAIN_ANALYSIS = int(os.getenv("PMCC_MAX_CHAIN_ANALYSIS", "30"))
PMCC_MAX_CANDIDATES = int(os.getenv("PMCC_MAX_CANDIDATES", "12"))
PMCC_MIN_OI = int(os.getenv("PMCC_MIN_OI", "100"))
PMCC_MAX_SPREAD_PCT = float(os.getenv("PMCC_MAX_SPREAD_PCT", "0.05"))
PMCC_MIN_REV_GROWTH = float(os.getenv("PMCC_MIN_REV_GROWTH", "0.15"))
PMCC_BLOCK_EARNINGS = os.getenv("PMCC_BLOCK_EARNINGS", "1") == "1"
PMCC_EARNINGS_BLOCK_DAYS = int(os.getenv("PMCC_EARNINGS_BLOCK_DAYS", "14"))

BENCHMARK = os.getenv("PMCC_BENCHMARK", "SPY")
BIOTECH_KEYWORDS = ("biotech", "biotechnology", "pharmaceutical", "drug manufacturers")


def _trend_prefilter(tickers: List[str]) -> pd.DataFrame:
    """Batch price screen: 50/200 DMA, RS vs benchmark."""
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
            if price < PMCC_MIN_PRICE or price > PMCC_MAX_PRICE:
                continue
            above50 = price > dma50
            above200 = price > dma200 if dma200 == dma200 else False
            trend_pts = (2 if above200 else 0) + (2 if above50 else 0) + (2 if rs > 0 else 0)
            price_pts = 2 if PMCC_SWEET_MIN <= price <= PMCC_SWEET_MAX else 1
            rows.append({
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
            })
        except Exception:
            continue

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("Prefilter", ascending=False).head(PMCC_PREFILTER_N)


def _enrich_prefilter_with_scan(prefilter: pd.DataFrame, tickers: List[str]) -> pd.DataFrame:
    """Union pie Grade A/B/C (non REDUCE/SELL) names into the PMCC prefilter pool."""
    if not tickers:
        return prefilter

    try:
        scan = run_scan(tickers)
        if scan.empty:
            return prefilter
        extra = scan[
            scan["Grade"].isin(["A", "B", "C"])
            & ~scan["Signal"].isin(["REDUCE", "SELL"])
        ].copy()
        extra = extra[extra["Price"].astype(float).between(PMCC_MIN_PRICE, PMCC_MAX_PRICE)]
        extra = extra[["Ticker", "Price"]].copy()
        extra["Prefilter"] = 6
        extra["TrendPts"] = 4
        extra["PricePts"] = 2
        extra["RS%"] = None
        extra["Above50"] = True
        extra["Above200"] = None
        extra["DMA50"] = None
        extra["DMA200"] = np.nan

        cols = ["Ticker", "Price", "Prefilter", "TrendPts", "PricePts", "RS%", "Above50", "Above200", "DMA50", "DMA200"]
        extra = extra[cols]
        if prefilter.empty:
            merged = extra
        else:
            merged = pd.concat([prefilter[cols], extra], ignore_index=True)
        merged = merged.drop_duplicates(subset=["Ticker"], keep="first")
        return merged.sort_values("Prefilter", ascending=False).head(PMCC_PREFILTER_N)
    except Exception as e:
        logger.info("[pmcc] scan enrich failed: %s", e)
        return prefilter


def _growth_score(symbol: str) -> tuple[float, str]:
    try:
        info = yf.Ticker(symbol).info or {}
        rev = info.get("revenueGrowth")
        sector = str(info.get("sector") or "").lower()
        industry = str(info.get("industry") or "").lower()
        notes = []
        score = 5.0

        if rev is not None and rev == rev:
            rev = float(rev)
            if rev >= PMCC_MIN_REV_GROWTH:
                score = 9.0 if rev >= 0.25 else 7.5
            elif rev >= 0.05:
                score = 5.0
            else:
                score = 2.0
            notes.append(f"rev={rev*100:.0f}%")
        else:
            notes.append("rev=n/a")

        if any(k in sector or k in industry for k in BIOTECH_KEYWORDS):
            score = min(score, 3.0)
            notes.append("biotech-flag")

        return score, "; ".join(notes)
    except Exception:
        return 5.0, "growth=n/a"


def _pick_leap_leg(
    calls: pd.DataFrame,
    spot: float,
    dte: int,
) -> Optional[dict]:
    if calls is None or calls.empty:
        return None

    liquid = calls[
        calls.apply(
            lambda r: leg_is_liquid(r, min_oi=PMCC_MIN_OI, max_spread_pct=PMCC_MAX_SPREAD_PCT),
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
                "oi": int(row.get("openInterest") or 0),
                "iv_pct": round(iv * 100, 1),
            }
    return best


def _pick_short_call(
    calls: pd.DataFrame,
    spot: float,
    dte: int,
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
    best_rank = float("inf")

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
        delta_dist = abs(delta - PMCC_SHORT_DELTA_TARGET)
        oi_penalty = 0.0 if int(row.get("openInterest") or 0) >= PMCC_MIN_OI else 0.5
        rank = delta_dist + oi_penalty
        if rank < best_rank:
            best_rank = rank
            monthly_pct = (mid / spot * 100.0) * (30.0 / max(dte, 1))
            best = {
                "strike": strike,
                "credit": round(mid, 2),
                "delta": round(delta, 2),
                "oi": int(row.get("openInterest") or 0),
                "iv_pct": round(iv * 100, 1),
                "monthly_pct": round(monthly_pct, 2),
            }
    return best


def _analyze_symbol(row: pd.Series) -> Optional[dict]:
    sym = str(row["Ticker"]).upper()
    spot = float(row["Price"])

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
    if not leap_exp or not short_exp:
        return None

    growth_score, growth_note = _growth_score(sym)
    weekly = has_weekly_expiries(expiries, today=today)

    try:
        leap_calls = tk.option_chain(leap_exp).calls
        short_calls = tk.option_chain(short_exp).calls
    except Exception:
        return None

    leap = _pick_leap_leg(leap_calls, spot, leap_dte or 0)
    short = _pick_short_call(short_calls, spot, short_dte or 0)
    if not leap or not short:
        return None

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
    iv_med = float(np.nanmedian(short_calls["impliedVolatility"].astype(float))) * 100
    if ivp == ivp and ivp >= 0.30:
        iv_score += 2.0
    if 40 <= iv_med <= 80:
        iv_score += 2.0
    iv_score = min(iv_score, 10.0)

    trend_score = min(float(row.get("TrendPts", 0)) * 1.25, 10.0)
    price_score = float(row.get("PricePts", 1)) * 5.0
    leaps_score = 10.0

    total = (
        0.35 * growth_score
        + 0.20 * liq_score
        + 0.20 * iv_score
        + 0.15 * trend_score
        + 0.10 * leaps_score
    )

    if total < PMCC_MIN_SCORE:
        return None

    if PMCC_BLOCK_EARNINGS:
        dte_earn = days_to_next_earnings(sym)
        if dte_earn is not None and 0 <= dte_earn <= PMCC_EARNINGS_BLOCK_DAYS:
            logger.info("[pmcc] %s blocked — earnings in %d days", sym, dte_earn)
            return None

    return {
        "Ticker": sym,
        "Price": spot,
        "Score": round(total, 1),
        "Growth": round(growth_score, 1),
        "Liq": round(liq_score, 1),
        "IV": round(iv_score, 1),
        "Trend": round(trend_score, 1),
        "Weekly": "Y" if weekly else "N",
        "RS%": row.get("RS%"),
        "GrowthNote": growth_note,
        "LeapExp": leap_exp,
        "LeapDTE": leap_dte,
        "LeapStrike": leap["strike"],
        "LeapDebit": leap["mid"],
        "LeapDelta": leap["delta"],
        "LeapExt%": leap["ext_pct"],
        "LeapOI": leap["oi"],
        "ShortExp": short_exp,
        "ShortDTE": short_dte,
        "ShortStrike": short["strike"],
        "ShortCredit": short["credit"],
        "ShortDelta": short["delta"],
        "ShortMonthly%": short["monthly_pct"],
        "ShortOI": short["oi"],
        "IV%": round(iv_med, 1),
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

    pre = _trend_prefilter(tickers)
    pre = _enrich_prefilter_with_scan(pre, tickers)
    out["prefiltered"] = len(pre)

    if pre.empty:
        out["html"] = (
            f"<p>Scanned {len(tickers)} symbols · "
            "<i>none passed price ($20–$200) / trend prefilter.</i></p>"
        )
        return out

    rows: List[dict] = []
    chain_pool = pre.head(PMCC_MAX_CHAIN_ANALYSIS)
    for _, r in chain_pool.iterrows():
        try:
            plan = _analyze_symbol(r)
            if plan:
                rows.append(plan)
        except Exception as e:
            logger.info("[pmcc] %s analyze failed: %s", r.get("Ticker"), e)

    rows.sort(key=lambda x: float(x.get("Score") or 0), reverse=True)
    rows = rows[:PMCC_MAX_CANDIDATES]

    out["rows"] = rows
    out["tickers"] = [r["Ticker"] for r in rows]
    out["html"] = format_pmcc_opportunities_html(rows, scanned=len(tickers), prefiltered=len(pre))
    return out


PMCC_TABLE_COLS = [
    "Ticker",
    "Price",
    "Score",
    "RS%",
    "LeapExp",
    "LeapDTE",
    "LeapStrike",
    "LeapDebit",
    "LeapDelta",
    "LeapExt%",
    "ShortExp",
    "ShortDTE",
    "ShortStrike",
    "ShortCredit",
    "ShortDelta",
    "ShortMonthly%",
]


def _fmt_pmcc(col: str, val) -> str:
    if val is None or val == "":
        return ""
    if col in ("Price", "LeapDebit", "ShortCredit", "LeapStrike", "ShortStrike"):
        try:
            return f"{float(val):.2f}"
        except (TypeError, ValueError):
            return str(val)
    if col in ("LeapDelta", "ShortDelta", "Score", "RS%", "LeapExt%", "ShortMonthly%"):
        try:
            return f"{float(val):.1f}"
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
            f"<p>Scanned {scanned} · prefiltered {prefiltered} (price/trend) · "
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
        f"{len(rows)} passed (score ≥{PMCC_MIN_SCORE:g}).</p>"
        f"{table}"
        "<p style='font-size:11px;color:#666'>"
        "Long LEAP: 18–30mo, Δ 0.80–0.95, extrinsic &lt;15%. "
        "Short call: 30–45 DTE, Δ 0.15–0.25. Close short at 50% profit. "
        "Score weights: growth 35%, liquidity 20%, IV 20%, trend 15%, LEAPS 10%. "
        "Estimates only — verify chain before trading."
        "</p>"
    )


def format_pmcc_opportunities_text(rows: List[dict], *, scanned: int, prefiltered: int) -> str:
    lines = [
        f"Scanned {scanned} · prefiltered {prefiltered} · {len(rows)} PMCC ideas",
        "",
    ]
    if not rows:
        lines.append("  None passed filters.")
        return "\n".join(lines)

    for r in rows:
        lines.append(
            f"  {r.get('Ticker','')} score={r.get('Score','')} price={r.get('Price','')} "
            f"LEAP {r.get('LeapExp','')} {r.get('LeapStrike','')} @ {r.get('LeapDebit','')} "
            f"Δ={r.get('LeapDelta','')} | short {r.get('ShortExp','')} "
            f"{r.get('ShortStrike','')} cr {r.get('ShortCredit','')} "
            f"Δ={r.get('ShortDelta','')} mo%={r.get('ShortMonthly%','')}"
        )
    lines.append("")
    lines.append("Close short at 50% profit. Verify chain before trading.")
    return "\n".join(lines)


def format_pmcc_opportunities_result_text(result: Dict[str, Any]) -> str:
    return format_pmcc_opportunities_text(
        list(result.get("rows") or []),
        scanned=int(result.get("scanned") or 0),
        prefiltered=int(result.get("prefiltered") or 0),
    )
