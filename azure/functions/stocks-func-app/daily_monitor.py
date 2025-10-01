# daily_monitor.py
import datetime
from typing import List, Tuple

import numpy as np
import pandas as pd
import yfinance as yf


# ---------------- Indicators & helpers ----------------
def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).rolling(n).mean()
    roll_down = pd.Series(down, index=series.index).rolling(n).mean()
    rs = roll_up / (roll_down.replace(0, np.nan))
    return (100 - (100 / (1 + rs))).fillna(50)

def macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Adj Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr

def realized_vol(returns: pd.Series, n=20):
    return returns.rolling(n).std() * np.sqrt(252)

def zscore(s: pd.Series) -> pd.Series:
    mu, sd = s.mean(), s.std()
    if pd.isna(sd) or sd == 0:
        return pd.Series(0.0, index=s.index)
    return (s - mu) / sd


# ---------------- Trend-follow scoring ----------------
def score_row(r: pd.Series, min_dollar_vol: int) -> float:
    momentum_trend = (
        0.50 * r.get("ret_20_z", 0.0) +
        1.00 * r.get("ret_60_z", 0.0) +
        1.20 * r.get("ret_120_z", 0.0) +
        1.00 * (1.0 if (r.get("sma20", 0) > r.get("sma50", 0) > r.get("sma200", 0)) else 0.0) +
        0.80 * r.get("close_above_sma50", 0.0) +
        0.50 * r.get("close_above_sma200", 0.0) +
        0.60 * (1.0 if r.get("macd_hist", 0.0) > 0 else 0.0) +
        0.80 * (1.0 if r.get("dist_52w_high", -1.0) > -0.05 else 0.0) +
        0.50 * r.get("new_55d_high", 0.0) +
        0.50 * max(0.0, r.get("sma50_slope", 0.0)) +
        0.50 * max(0.0, r.get("sma200_slope", 0.0))
    )
    liquidity = 1.0 if r.get("adv_usd_20", 0.0) >= min_dollar_vol else -1.0
    vol20 = r.get("vol20", 0.0)
    mdd_60 = r.get("mdd_60", 0.0)
    risk_penalty = 0.30 * vol20 + 1.20 * abs(min(0.0, mdd_60))
    event_penalty = 0.0  # earnings check omitted here
    return float(momentum_trend + liquidity - risk_penalty - event_penalty)


# ---------------- Public API ----------------
def run_monitor(
    tickers: List[str],
    *,
    today: datetime.date | None = None,
    min_dollar_vol: int = 1_000_000
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fetches data, computes indicators, builds:
      - df_all (sorted by trend-follow score)
      - df_leaders (5d & 21d positive, strength weighted to 21d)
    Returns (df_all, df_leaders)
    """
    if today is None:
        today = datetime.date.today()

    end = today + datetime.timedelta(days=1)
    start = today - datetime.timedelta(days=420)
    data = yf.download(tickers=tickers, start=start, end=end,
                       auto_adjust=False, group_by="ticker", progress=False)

    rows = []
    for t in tickers:
        if t not in data:
            continue
        df = data[t].dropna(subset=["Adj Close"]).copy()
        if df.empty:
            continue

        d = df.copy()
        d["CloseAdj"] = d["Adj Close"]

        # returns
        d["ret"] = d["CloseAdj"].pct_change()
        d["ret_5d"] = d["CloseAdj"].pct_change(5)
        d["ret_20"] = d["CloseAdj"].pct_change(20)
        d["ret_21d"] = d["CloseAdj"].pct_change(21)
        d["ret_60"] = d["CloseAdj"].pct_change(60)
        d["ret_120"] = d["CloseAdj"].pct_change(120)

        # MAs, slopes, positions
        d["sma20"] = d["CloseAdj"].rolling(20).mean()
        d["sma50"] = d["CloseAdj"].rolling(50).mean()
        d["sma200"] = d["CloseAdj"].rolling(200).mean()
        d["sma50_slope"] = (d["sma50"].diff(5) / d["sma50"].shift(5)).replace([np.inf, -np.inf], np.nan)
        d["sma200_slope"] = (d["sma200"].diff(10) / d["sma200"].shift(10)).replace([np.inf, -np.inf], np.nan)
        d["close_above_sma50"] = (d["CloseAdj"] > d["sma50"]).astype(float)
        d["close_above_sma200"] = (d["CloseAdj"] > d["sma200"]).astype(float)

        # oscillators
        d["rsi14"] = rsi(d["CloseAdj"])
        _, _, hist = macd(d["CloseAdj"])
        d["macd_hist"] = hist

        # risk/vol
        d["tr"] = true_range(d)
        d["atr14"] = d["tr"].rolling(14).mean()
        d["vol20"] = realized_vol(d["ret"], 20)
        d["mdd_60"] = (d["CloseAdj"] / d["CloseAdj"].cummax() - 1.0).rolling(60).min()

        # liquidity
        d["adv_usd_20"] = d["Volume"].rolling(20).mean() * d["CloseAdj"].rolling(20).mean()

        # highs / breakouts
        d["hi_252"] = d["CloseAdj"].rolling(252, min_periods=60).max()
        d["dist_52w_high"] = d["CloseAdj"] / d["hi_252"] - 1.0
        d["hi_55"] = d["CloseAdj"].rolling(55, min_periods=30).max()
        d["new_55d_high"] = (d["CloseAdj"] >= d["hi_55"]).astype(float)

        # momentum z-scores
        for col in ["ret_20", "ret_60", "ret_120"]:
            mu = d[col].rolling(180).mean()
            sd = d[col].rolling(180).std()
            d[f"{col}_z"] = (d[col] - mu) / sd.replace(0, np.nan)

        if d.dropna(subset=["CloseAdj", "sma50", "sma200"]).empty:
            continue

        latest = d.iloc[-1].to_dict()
        latest["ticker"] = t
        rows.append(latest)

    if not rows:
        raise RuntimeError("No rows produced—check data availability or ticker list.")

    out = pd.DataFrame(rows)

    # Trend-follow score and buy flag
    out["score"] = out.apply(lambda r: score_row(r, min_dollar_vol), axis=1)
    out["buy_flag"] = (
        (out["score"] > 1.5) &
        (out["rsi14"].between(45, 80)) &
        (out["close_above_sma50"] == 1.0) &
        (out["close_above_sma200"] == 1.0) &
        (out["dist_52w_high"] > -0.10)
    )

    # Leaders (5d & 21d positive; 21d weighted heavier)
    out["z_5d"] = zscore(out["ret_5d"]).fillna(0.0)
    out["z_21d"] = zscore(out["ret_21d"]).fillna(0.0)
    out["strength_score"] = 0.3 * out["z_5d"] + 0.7 * out["z_21d"]
    leaders = out[(out["ret_5d"] > 0) & (out["ret_21d"] > 0)].copy()
    leaders = leaders.sort_values("strength_score", ascending=False)

    # Ordered views
    out_sorted = out.sort_values("score", ascending=False)
    leaders_view = leaders[["ticker", "ret_5d", "ret_21d", "strength_score"]].copy()

    return out_sorted, leaders_view