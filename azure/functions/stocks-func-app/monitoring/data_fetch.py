import time
import datetime
from typing import Dict, List
import pandas as pd
import yfinance as yf
from .config import YF_BATCH_SIZE, YF_MAX_RETRIES, YF_RETRY_BACKOFF_S

def clean_tickers(raw: List[str]) -> List[str]:
    return [t.strip().upper() for t in raw if t and t.strip() and t.strip().upper() not in {"US"}]

def _fetch_batch(batch: List[str], start: datetime.date, end: datetime.date) -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    if not batch: return out
    attempt = 0
    while attempt <= YF_MAX_RETRIES:
        try:
            data = yf.download(
                tickers=batch, start=start, end=end,
                auto_adjust=False, group_by="ticker",
                progress=False, threads=True
            )
            for t in batch:
                if t in data:
                    df = data[t]
                elif len(batch) == 1 and isinstance(data, pd.DataFrame) and \
                     set(["Adj Close","Close","High","Low","Open","Volume"]).issubset(data.columns):
                    df = data
                else:
                    continue
                df = df.dropna(subset=["Adj Close"]).copy()
                if df.empty: continue
                out[t] = df
            return out
        except Exception:
            attempt += 1
            time.sleep(YF_RETRY_BACKOFF_S * attempt)
    return out

def fetch_prices_batched(tickers: List[str], start: datetime.date, end: datetime.date) -> Dict[str, pd.DataFrame]:
    tickers = clean_tickers(tickers)
    frames: Dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), YF_BATCH_SIZE):
        frames.update(_fetch_batch(tickers[i:i+YF_BATCH_SIZE], start, end))
    return frames