import numpy as np
import pandas as pd
import warnings
import yfinance as yf

def eps_surprise_trend(ticker: str, lookback: int = 10) -> dict:
    out = {"eps_surprise_avg": 0.0, "eps_beat_share": 0.0}
    try:
        ed = yf.Ticker(ticker).earnings_dates(limit=lookback)
        if ed is None or ed.empty: return out
        cols = [c for c in ed.columns if "surprise" in c.lower()]
        if not cols: return out
        s = ed[cols[0]].astype(float).dropna()
        last4 = s.tail(4)
        if last4.empty: return out
        if last4.abs().median() > 1.0: last4 = last4 / 100.0
        out["eps_surprise_avg"] = float(last4.mean())
        out["eps_beat_share"]   = float(np.mean(last4 > 0))
        return out
    except Exception:
        return out

def compute_quarterly_trends(ticker: str) -> dict:
    out = {
        "rev_q_yoy": 0.0, "earn_q_yoy": 0.0,
        "rev_q_qoq": 0.0, "earn_q_qoq": 0.0,
        "growth_streak": 0.0, "fundamentals_quality": 0.0,
    }
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tf = yf.Ticker(ticker).quarterly_financials
        if tf is None or tf.empty:
            return out
        qf = tf.T.copy().sort_index()
        cols = {c.lower(): c for c in qf.columns}
        rev_col = cols.get("total revenue") or cols.get("revenue")
        ni_col  = cols.get("net income")   or cols.get("netincome")
        if not rev_col or not ni_col:
            return out
        rev = pd.to_numeric(qf[rev_col], errors="coerce")
        ern = pd.to_numeric(qf[ni_col],  errors="coerce")
        if len(rev.dropna()) >= 8 and len(ern.dropna()) >= 8:
            yoy_rev = (rev / rev.shift(4) - 1.0)
            yoy_ern = (ern / ern.shift(4) - 1.0)
            last4_rev = yoy_rev.tail(4).dropna()
            last4_ern = yoy_ern.tail(4).dropna()
            if len(last4_rev) >= 3: out["rev_q_yoy"] = float(np.nanmean(last4_rev.values))
            if len(last4_ern) >= 3: out["earn_q_yoy"] = float(np.nanmean(last4_ern.values))
            pos = []
            for r, e in zip(yoy_rev.tail(4).values, yoy_ern.tail(4).values):
                pos.append(pd.notna(r) and r > 0 and pd.notna(e) and e > 0)
            out["growth_streak"] = 1.0 if len(pos) == 4 and all(pos) else 0.0
            out["fundamentals_quality"] = 1.0
            return out
        # QoQ fallback
        qoq_rev = rev.pct_change().replace([np.inf, -np.inf], np.nan)
        qoq_ern = ern.pct_change().replace([np.inf, -np.inf], np.nan)
        last3_rev = qoq_rev.tail(3).dropna(); last3_ern = qoq_ern.tail(3).dropna()
        if len(last3_rev) >= 2: out["rev_q_qoq"] = float(np.nanmean(last3_rev.values))
        if len(last3_ern) >= 2: out["earn_q_qoq"] = float(np.nanmean(last3_ern.values))
        pairs = list(zip(qoq_rev.dropna().tail(3).values, qoq_ern.dropna().tail(3).values))
        out["growth_streak"] = 1.0 if len(pairs) == 3 and all((r > 0 and e > 0) for r, e in pairs) else 0.0
        out["fundamentals_quality"] = 0.5
        return out
    except Exception:
        return out

def cap_multiplier(mcap: float | None) -> float:
    if mcap is None or (isinstance(mcap, float) and np.isnan(mcap)): return 1.0
    try: m = float(mcap)
    except Exception: return 1.0
    if m < 2e9:   return 0.85
    if m < 10e9:  return 1.05
    if m < 200e9: return 1.10
    return 1.12