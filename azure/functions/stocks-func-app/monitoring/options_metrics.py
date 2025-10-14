# monitoring/options_metrics.py

from __future__ import annotations
import datetime as dt
from typing import Dict, Tuple, Optional

import numpy as np
import pandas as pd
import yfinance as yf


def _safe_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return float("nan")


def _choose_expiry(tkr: str, *, min_dte: int, max_dte: int, today: Optional[dt.date] = None) -> Tuple[Optional[str], Optional[int]]:
    """
    Pick the nearest options expiry with DTE in [min_dte, max_dte].
    Returns (expiry_str, dte) or (None, None) if not found.
    """
    if today is None:
        today = dt.date.today()

    tk = yf.Ticker(tkr)
    try:
        exps = tk.options or []
    except Exception:
        exps = []
    if not exps:
        return None, None

    best = None
    best_dte = None
    for e in exps:
        try:
            d = dt.datetime.strptime(e, "%Y-%m-%d").date()
            dte = (d - today).days
        except Exception:
            continue
        if dte < min_dte or dte > max_dte:
            continue
        if best is None or abs(dte - (min_dte + max_dte) // 2) < abs(best_dte - (min_dte + max_dte) // 2):
            best = e
            best_dte = dte

    if best is None:
        # fallback: take nearest > min_dte
        try:
            cands = []
            for e in exps:
                d = dt.datetime.strptime(e, "%Y-%m-%d").date()
                dte = (d - today).days
                if dte >= min_dte:
                    cands.append((e, dte))
            if cands:
                best, best_dte = sorted(cands, key=lambda x: abs(x[1] - (min_dte + max_dte) // 2))[0]
        except Exception:
            pass

    return (best, best_dte) if best else (None, None)


def _pick_strikes_by_moneyness(spot: float, calls_df: pd.DataFrame, *, pct_otm_long: float, pct_otm_short: float) -> Tuple[Optional[float], Optional[float]]:
    """
    Choose long/short call strikes using %OTM offsets (e.g., 5% and 10% above spot).
    """
    if not np.isfinite(spot) or spot <= 0 or calls_df is None or calls_df.empty:
        return None, None

    k_long_target = spot * (1.0 + pct_otm_long)
    k_short_target = spot * (1.0 + pct_otm_short)

    strikes = sorted([_safe_float(k) for k in calls_df["strike"].tolist() if np.isfinite(_safe_float(k))])
    if not strikes:
        return None, None

    k1 = min(strikes, key=lambda k: abs(k - k_long_target))
    k2 = min(strikes, key=lambda k: abs(k - k_short_target))
    if k2 <= k1:  # ensure short further OTM than long
        # try to nudge one step higher
        higher = [k for k in strikes if k > k1]
        if higher:
            k2 = higher[0]
        else:
            return None, None
    return float(k1), float(k2)


def _mid_price(bid: float, ask: float) -> float:
    b = _safe_float(bid)
    a = _safe_float(ask)
    if not np.isfinite(b) or not np.isfinite(a) or b <= 0 or a <= 0:
        return float("nan")
    return (b + a) / 2.0


def _spread_pct(bid: float, ask: float) -> float:
    mid = _mid_price(bid, ask)
    if not np.isfinite(mid) or mid <= 0:
        return float("nan")
    return (ask - bid) / mid


def iv_percentile_proxy(calls_df: pd.DataFrame, spot: float, band: float = 0.20) -> float:
    """
    Rough IV percentile proxy using *cross-sectional* IV across strikes
    near-ATM for the chosen expiry (not a time-series IV rank).
    """
    if calls_df is None or calls_df.empty or not np.isfinite(spot) or spot <= 0:
        return float("nan")
    df = calls_df.copy()
    df = df[pd.to_numeric(df["impliedVolatility"], errors="coerce").notna()]
    if df.empty:
        return float("nan")
    df["moneyness"] = df["strike"].astype(float) / spot - 1.0
    focus = df[df["moneyness"].abs() <= band]
    if focus.empty:
        focus = df  # fallback to all
    ivs = np.clip(pd.to_numeric(focus["impliedVolatility"], errors="coerce").dropna().values, 1e-6, None)
    if ivs.size < 5:
        return float("nan")
    current_iv = float(np.median(ivs))  # median near-ATM IV
    iv_min, iv_max = float(np.min(ivs)), float(np.max(ivs))
    if iv_max <= iv_min:
        return 0.5
    return float((current_iv - iv_min) / (iv_max - iv_min))


def days_to_next_earnings(tkr: str, today: Optional[dt.date] = None) -> Optional[int]:
    if today is None:
        today = dt.date.today()
    try:
        cal = yf.Ticker(tkr).calendar
        if isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
            val = cal.loc["Earnings Date"].values[0]
        elif isinstance(cal, dict):
            val = cal.get("Earnings Date")
        else:
            val = None

        if val is None:
            return None
        # yfinance sometimes returns Timestamp or str
        if hasattr(val, "to_pydatetime"):
            ed = val.to_pydatetime().date()
        elif isinstance(val, (list, tuple)) and val:
            # sometimes a list of two timestamps
            ed0 = val[0]
            if hasattr(ed0, "to_pydatetime"):
                ed = ed0.to_pydatetime().date()
            else:
                ed = pd.to_datetime(ed0).date()
        else:
            ed = pd.to_datetime(val).date()

        dte = (ed - today).days
        return int(dte)
    except Exception:
        return None


def option_liquidity_and_debit(
    tkr: str,
    *,
    min_dte: int = 25,
    max_dte: int = 50,
    pct_otm_long: float = 0.05,
    pct_otm_short: float = 0.10,
    today: Optional[dt.date] = None,
) -> Dict:
    """
    Pull chain, pick a 30–45 DTE expiry, build a simple OTM debit call spread,
    and compute basic liquidity metrics + IV percentile proxy.
    """
    if today is None:
        today = dt.date.today()

    # pick expiry
    expiry, dte = _choose_expiry(tkr, min_dte=min_dte, max_dte=max_dte, today=today)
    if not expiry:
        return {"ok": False, "reason": "no_expiry_in_window"}

    # fetch chain
    try:
        chain = yf.Ticker(tkr).option_chain(expiry)
        calls = chain.calls.copy()
    except Exception:
        return {"ok": False, "reason": "chain_fetch_failed"}

    if calls is None or calls.empty:
        return {"ok": False, "reason": "empty_chain"}

    # spot
    try:
        spot = float(yf.Ticker(tkr).fast_info.get("last_price") or yf.Ticker(tkr).fast_info.get("lastPrice") or 0.0)
        if not np.isfinite(spot) or spot <= 0:
            spot = float(pd.to_numeric(calls["lastPrice"], errors="coerce").median())
    except Exception:
        spot = float(pd.to_numeric(calls["lastPrice"], errors="coerce").median())

    if not np.isfinite(spot) or spot <= 0:
        return {"ok": False, "reason": "bad_spot"}

    # choose strikes
    k1, k2 = _pick_strikes_by_moneyness(spot, calls, pct_otm_long=pct_otm_long, pct_otm_short=pct_otm_short)
    if k1 is None or k2 is None:
        return {"ok": False, "reason": "no_strikes"}

    # slice rows
    r1 = calls.loc[(calls["strike"].astype(float) == k1)]
    r2 = calls.loc[(calls["strike"].astype(float) == k2)]
    if r1.empty or r2.empty:
        return {"ok": False, "reason": "strike_rows_missing"}

    # take best row (if multiple, pick highest OI)
    r1 = r1.sort_values("openInterest", ascending=False).iloc[0]
    r2 = r2.sort_values("openInterest", ascending=False).iloc[0]

    # metrics
    bid1, ask1 = _safe_float(r1.get("bid")), _safe_float(r1.get("ask"))
    bid2, ask2 = _safe_float(r2.get("bid")), _safe_float(r2.get("ask"))
    mid1 = _mid_price(bid1, ask1)
    mid2 = _mid_price(bid2, ask2)

    spread1 = _spread_pct(bid1, ask1)
    spread2 = _spread_pct(bid2, ask2)

    # net debit (buy k1, sell k2)
    mid_debit = mid1 - mid2 if np.isfinite(mid1) and np.isfinite(mid2) else float("nan")

    # “combined spread%” — how wide the two legs are vs debit:
    # If debit is small, this can blow up; cap it.
    if np.isfinite(mid_debit) and mid_debit > 0:
        combo_spread_pct = np.clip(((ask1 - bid1) + (ask2 - bid2)) / (2 * mid_debit), 0.0, 5.0)  # cap @ 500%
    else:
        combo_spread_pct = float("nan")

    # OI
    oi1 = _safe_float(r1.get("openInterest"))
    oi2 = _safe_float(r2.get("openInterest"))

    # IV percentile proxy (cross-sectional)
    ivp = iv_percentile_proxy(calls, spot, band=0.20)

    # earnings window
    dte_earn = days_to_next_earnings(tkr, today=today)

    return {
        "ok": True,
        "expiry": expiry,
        "dte": dte,
        "long_k": k1,
        "short_k": k2,
        "mid_debit": mid_debit,
        "leg1_spread_pct": spread1,
        "leg2_spread_pct": spread2,
        "combo_spread_pct": combo_spread_pct,
        "oi_long": oi1,
        "oi_short": oi2,
        "ivp_proxy": ivp,
        "days_to_earnings": dte_earn,
    }