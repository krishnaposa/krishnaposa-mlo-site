import numpy as np
import pandas as pd

def wilder_smooth(s: pd.Series, n: int) -> pd.Series:
    s = s.copy()
    return s.ewm(alpha=1/n, adjust=False).mean()

def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    H = df["High"]; L = df["Low"]; C = df.get("CloseAdj", df["Adj Close"])
    up_move = H.diff(); down_move = -L.diff()
    plus_dm  = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)
    tr = pd.concat([H - L, (H - C.shift(1)).abs(), (L - C.shift(1)).abs()], axis=1).max(axis=1)
    atr = wilder_smooth(tr, n)
    plus_di  = 100 * wilder_smooth(plus_dm, n) / atr
    minus_di = 100 * wilder_smooth(minus_dm, n) / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = wilder_smooth(dx, n).fillna(0.0)
    return adx_val.clip(0, 100)

def mfi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    H, L = df["High"], df["Low"]
    C = df.get("CloseAdj", df["Adj Close"])
    V = df["Volume"].astype(float)
    tp = (H + L + C) / 3.0
    rmf = tp * V
    sign = np.sign(tp.diff().fillna(0.0))
    pos_mf = pd.Series(np.where(sign > 0, rmf, 0.0), index=df.index)
    neg_mf = pd.Series(np.where(sign < 0, rmf, 0.0), index=df.index)
    pos = pos_mf.rolling(n).sum()
    neg = neg_mf.rolling(n).sum().replace(0, np.nan)
    mr = pos / neg
    mfi_val = 100 - (100 / (1 + mr))
    return mfi_val.fillna(50.0).clip(0, 100)

def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).rolling(n).mean()
    roll_down = pd.Series(down, index=series.index).rolling(n).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)

def macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line

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
    if pd.isna(sd) or sd == 0: return pd.Series(0.0, index=s.index)
    return (s - mu) / sd

def clamp(x: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, x)))