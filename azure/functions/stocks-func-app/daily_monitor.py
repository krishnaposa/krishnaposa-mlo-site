# requirements:
#   pip install pandas yfinance numpy

from __future__ import annotations
import math
import os
from datetime import datetime, timedelta
from typing import List

import numpy as np
import pandas as pd
import yfinance as yf

TICKERS: List[str] = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AMD","AVGO","CRM"
]  # edit this list

LOOKBACK_CAL_DAYS = 400           # enough to compute long indicators
OUT_DIR = "daily_stock_monitor"   # outputs here
MIN_DOLLAR_VOL = 1_000_000        # liquidity floor
EARNINGS_BLACKOUT_DAYS = 7        # avoid buying right before earnings
TODAY = datetime.now().date()

os.makedirs(OUT_DIR, exist_ok=True)

def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).rolling(n).mean()
    roll_down = pd.Series(down, index=series.index).rolling(n).mean()
    rs = roll_up / (roll_down.replace(0, np.nan))
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
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

def max_drawdown(series: pd.Series, window: int) -> pd.Series:
    roll_max = series.rolling(window, min_periods=1).max()
    dd = series / roll_max - 1.0
    return dd.rolling(window, min_periods=1).min()  # most negative within window

def realized_vol(returns: pd.Series, n: int = 20) -> pd.Series:
    return returns.rolling(n).std() * np.sqrt(252)

def beta_vs_spy(ret: pd.Series, ret_spy: pd.Series, n: int = 60) -> pd.Series:
    cov = ret.rolling(n).cov(ret_spy)
    var = ret_spy.rolling(n).var()
    return cov / var

def fetch_prices(tickers: List[str]) -> dict[str, pd.DataFrame]:
    end = TODAY + timedelta(days=1)
    start = TODAY - timedelta(days=LOOKBACK_CAL_DAYS)
    data = yf.download(
        tickers=tickers, start=start.isoformat(), end=end.isoformat(),
        auto_adjust=False, group_by="ticker", progress=False
    )
    frames = {}
    for t in tickers:
        df = data[t].copy()
        df = df.dropna(subset=["Adj Close"])
        frames[t] = df
    return frames

def fetch_events_df(tickers: List[str]) -> pd.DataFrame:
    rows = []
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            cal = tk.calendar  # may be empty
            earn = cal.get("Earnings Date")
            exdiv = cal.get("Ex-Dividend Date")
            rows.append({
                "ticker": t,
                "earnings_date": pd.to_datetime(earn).date() if pd.notna(earn) else None,
                "ex_div_date":   pd.to_datetime(exdiv).date() if pd.notna(exdiv) else None
            })
        except Exception:
            rows.append({"ticker": t, "earnings_date": None, "ex_div_date": None})
    return pd.DataFrame(rows).set_index("ticker")

def score_row(r):
    momentum = (
        r["ret_20_z"] + r["ret_60_z"]
        + max(0.0, 1.0 - max(0.0, r["dist_52w_high"]))  # closer to high helps
        + (1.0 if r["sma20"] > r["sma50"] > r["sma200"] else 0.0)
        + (1.0 if r["macd_hist"] > 0 else 0.0)
    )
    risk_penalty = (
        max(0.0, (r["vol20"] - 0.4)) * 2.0  # penalize very high vol
        + abs(min(0.0, r["mdd_60"])) * 1.5
    )
    liq = 1.0 if r["adv_usd_20"] >= MIN_DOLLAR_VOL else -1.0
    event_penalty = 1.0 if r["earnings_within_7d"] else 0.0
    return momentum + liq - risk_penalty - event_penalty

def main():
    frames = fetch_prices(TICKERS)
    spy = yf.download("SPY", period="400d", auto_adjust=True, progress=False)["Close"].pct_change()

    rows = []
    events = fetch_events_df(TICKERS)

    for t, df in frames.items():
        d = df.copy()
        d["CloseAdj"] = d["Adj Close"]
        d["ret"] = d["CloseAdj"].pct_change()
        d["ret_5"] = d["CloseAdj"].pct_change(5)
        d["ret_20"] = d["CloseAdj"].pct_change(20)
        d["ret_60"] = d["CloseAdj"].pct_change(60)

        d["sma20"] = d["CloseAdj"].rolling(20).mean()
        d["sma50"] = d["CloseAdj"].rolling(50).mean()
        d["sma200"] = d["CloseAdj"].rolling(200).mean()

        d["rsi14"] = rsi(d["CloseAdj"], 14)
        macd_line, signal_line, hist = macd(d["CloseAdj"])
        d["macd_line"], d["macd_signal"], d["macd_hist"] = macd_line, signal_line, hist

        d["tr"] = true_range(d)
        d["atr14"] = d["tr"].rolling(14).mean()
        d["vol20"] = realized_vol(d["ret"], 20)

        d["dd_path"] = d["CloseAdj"] / d["CloseAdj"].cummax() - 1.0
        d["mdd_60"] = max_drawdown(d["CloseAdj"], 60)

        # beta vs SPY on overlapping dates
        ret_spy = spy.reindex(d.index).fillna(0.0)
        d["beta60"] = beta_vs_spy(d["ret"].fillna(0.0), ret_spy, 60)

        # liquidity
        d["adv"] = d["Volume"].rolling(20).mean()
        d["adv_usd_20"] = d["adv"] * d["CloseAdj"].rolling(20).mean()

        # 52 week metrics
        d["hi_252"] = d["CloseAdj"].rolling(252, min_periods=60).max()
        d["dist_52w_high"] = d["CloseAdj"] / d["hi_252"] - 1.0

        # z scores for momentum windows
        for col in ["ret_20", "ret_60"]:
            d[f"{col}_z"] = (d[col] - d[col].rolling(120).mean()) / d[col].rolling(120).std()

        d = d.dropna().copy()
        if d.empty:
            continue

        latest = d.iloc[-1].to_dict()
        latest["ticker"] = t

        # events
        earn = events.loc[t, "earnings_date"] if t in events.index else None
        latest["earnings_date"] = earn
        latest["earnings_within_7d"] = bool(earn and 0 <= (earn - TODAY).days <= EARNINGS_BLACKOUT_DAYS)

        rows.append(latest)

    if not rows:
        print("No data rows computed")
        return

    out = pd.DataFrame(rows)
    cols_keep = [
        "ticker","CloseAdj","ret","ret_5","ret_20","ret_60","ret_20_z","ret_60_z",
        "sma20","sma50","sma200","rsi14","macd_hist","atr14","vol20","beta60",
        "mdd_60","adv_usd_20","dist_52w_high","earnings_date","earnings_within_7d"
    ]
    out = out[cols_keep]
    out["score"] = out.apply(score_row, axis=1)
    out["buy_flag"] = (
        (out["score"] >= 1.0)
        & (out["rsi14"].between(40, 75))
        & (out["adv_usd_20"] >= MIN_DOLLAR_VOL)
        & (~out["earnings_within_7d"])
    )

    out = out.sort_values("score", ascending=False)

    # save
    stamp = TODAY.strftime("%Y-%m-%d")
    csv_path = os.path.join(OUT_DIR, f"daily_snapshot_{stamp}.csv")
    out.to_csv(csv_path, index=False)

    # append to rolling store
    pq_path = os.path.join(OUT_DIR, "rolling_store.parquet")
    out2 = out.copy()
    out2["asof_date"] = pd.to_datetime(TODAY)
    if os.path.exists(pq_path):
        hist = pd.read_parquet(pq_path)
        hist = pd.concat([hist, out2], ignore_index=True)
        hist.to_parquet(pq_path, index=False)
    else:
        out2.to_parquet(pq_path, index=False)

    print(f"Wrote {csv_path} with {len(out)} rows")
    print(f"Top picks today:\n{out.loc[out['buy_flag'], ['ticker','score']].head(10)}")

if __name__ == "__main__":
    main()