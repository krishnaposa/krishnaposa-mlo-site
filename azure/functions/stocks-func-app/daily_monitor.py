


# daily_monitor.py
import os
import time
import logging
import datetime
from typing import List, Tuple, Dict

import numpy as np
import pandas as pd
import yfinance as yf
import smtplib, ssl
from email.message import EmailMessage
import warnings

# shared cache reader (avoid circular imports by keeping in a separate module)
from universe_utils import read_universe_blob
# dynamic local list utils (Blob-backed)
from local_list_utils import load_local_list, save_local_list
# <<< NEW: local AI scorer (shared util, no HTTP)
from ai_utils import ai_rank_tickers

logging.getLogger("yfinance").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)

# --------------------------- Logging ---------------------------------
logger = logging.getLogger(__name__)
if not logger.handlers:
    LOG_LEVEL = os.getenv("DAILY_MONITOR_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

# --------------------------- Tunables --------------------------------
BATCH_SIZE = int(os.getenv("YF_BATCH_SIZE", "50"))
MAX_RETRIES = int(os.getenv("YF_MAX_RETRIES", "2"))
RETRY_BACKOFF_S = float(os.getenv("YF_RETRY_BACKOFF_S", "3.0"))
MIN_DOLLAR_VOL_DEFAULT = int(os.getenv("MIN_DOLLAR_VOL", "1000000"))
PENNY_PRICE = float(os.getenv("PENNY_PRICE", "5"))

# Prune/replenish policy (env-tunable)
LOCAL_PRUNE_COUNT = int(os.getenv("LOCAL_PRUNE_COUNT", "5"))
LOCAL_MAX_SIZE = int(os.getenv("LOCAL_MAX_SIZE", "0")) or None
LOCAL_ADD_MIN_PRICE = float(os.getenv("LOCAL_MIN_PRICE", str(PENNY_PRICE)))
LOCAL_ADD_MIN_STRENGTH_Z = float(os.getenv("LOCAL_MIN_STRENGTH_Z", "0.0"))

# AI email length
AI_EMAIL_TOPK = int(os.getenv("AI_EMAIL_TOPK", "8"))

# --------------------------- Weight configurations ------------------
WEIGHTS_DEBIT_SPREAD = {
    "ret_20_z": 0.5,
    "ret_60_z": 1.0,
    "ret_120_z": 1.2,
    "dist_52w_high": 0.8,
    "new_55d_high": 0.5,
    "adx14": 0.3,
    "mfi14": 0.2,
    "vol20_penalty": -0.3,
    "mdd_60_penalty": -1.2,
}

WEIGHTS_LEAPS = {
    "ret_20_z": 0.3,
    "ret_60_z": 0.8,
    "ret_120_z": 1.2,
    "dist_52w_high": 0.6,
    "new_55d_high": 0.4,
    "adx14": 0.4,
    "mfi14": 0.1,
    "vol20_penalty": -0.2,
    "mdd_60_penalty": -0.8,
}

def _render_compact_ai_table(df: pd.DataFrame, max_rows: int) -> str:
    if df is None or df.empty:
        return "<i>No picks</i>"
    d = df.copy()
    # pick/order columns if present
    cols = [c for c in ["ticker","ai_score","last_price","thesis"] if c in d.columns]
    d = d[cols].head(max_rows)
    # one-line thesis
    if "thesis" in d.columns:
        d["thesis"] = d["thesis"].astype(str).str.replace(r"\s+", " ", regex=True).str.slice(0, 140)
    # format ai_score if present
    if "ai_score" in d.columns:
        d["ai_score"] = pd.to_numeric(d["ai_score"], errors="coerce").round(2)
    # light HTML table
    return d.to_html(index=False, border=0, justify="left")
    
# --------------------------- Helpers ---------------------------------
def _wilder_smooth(s: pd.Series, n: int) -> pd.Series:
    s = s.copy()
    sm = s.ewm(alpha=1/n, adjust=False).mean()
    return sm

def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    H = df["High"]; L = df["Low"]; C = df.get("CloseAdj", df["Adj Close"])
    up_move = H.diff(); down_move = -L.diff()
    plus_dm  = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)
    tr = pd.concat([H - L, (H - C.shift(1)).abs(), (L - C.shift(1)).abs()], axis=1).max(axis=1)
    atr = _wilder_smooth(tr, n)
    plus_di  = 100 * _wilder_smooth(plus_dm, n) / atr
    minus_di = 100 * _wilder_smooth(minus_dm, n) / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = _wilder_smooth(dx, n).fillna(0.0)
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

def _eps_surprise_trend(ticker: str, lookback: int = 10) -> dict:
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

def clamp(x: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, x)))

def cap_multiplier(mcap: float | None) -> float:
    if mcap is None or (isinstance(mcap, float) and np.isnan(mcap)): return 1.0
    try: m = float(mcap)
    except Exception: return 1.0
    if m < 2e9: return 0.85
    if m < 10e9: return 1.05
    if m < 200e9: return 1.10
    return 1.12

def _shrink_df(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    for c in d.select_dtypes(include=["float64"]).columns:
        d[c] = pd.to_numeric(d[c], downcast="float")
    for c in d.select_dtypes(include=["int64"]).columns:
        d[c] = pd.to_numeric(d[c], downcast="integer")
    if "ticker" in d.columns and d["ticker"].dtype != "category":
        d["ticker"] = d["ticker"].astype("category")
    return d

# -------------------- Trend-follow scoring ---------------------------
def score_row(r: pd.Series, min_dollar_vol: int, strategy: str = "debit_call_spread") -> float:
    if strategy == "leaps":
        w = WEIGHTS_LEAPS
    else:
        w = WEIGHTS_DEBIT_SPREAD

    trend = (
        w.get("ret_20_z", 0)  * r.get("ret_20_z", 0.0) +
        w.get("ret_60_z", 0)  * r.get("ret_60_z", 0.0) +
        w.get("ret_120_z", 0) * r.get("ret_120_z", 0.0)
    )
    trend += 1.0 * (1.0 if (r.get("sma20", 0) > r.get("sma50", 0) > r.get("sma200", 0)) else 0.0)
    trend += 0.8 * r.get("close_above_sma50", 0.0)
    trend += 0.5 * r.get("close_above_sma200", 0.0)
    trend += 0.6 * (1.0 if r.get("macd_hist", 0.0) > 0 else 0.0)
    trend += w.get("dist_52w_high", 0.8) * (1.0 if r.get("dist_52w_high", -1.0) > -0.05 else 0.0)
    trend += w.get("new_55d_high", 0.5) * r.get("new_55d_high", 0.0)

    adx_norm = clamp((r.get("adx14", 0.0) - 20.0) / 40.0, 0.0, 1.0)
    mfi_centered = clamp((r.get("mfi14", 50.0) - 50.0) / 50.0, -1.0, 1.0)
    trend += w.get("adx14", 0.3) * adx_norm + w.get("mfi14", 0.1) * mfi_centered

    liquidity = 1.0 if r.get("adv_usd_20", 0.0) >= min_dollar_vol else -1.0
    risk = w.get("vol20_penalty", -0.15) * r.get("vol20", 0.0) + w.get("mdd_60_penalty", -1.0) * abs(min(0.0, r.get("mdd_60", 0.0)))

    penny_penalty = 0.6 if r.get("last_price", np.inf) < PENNY_PRICE else 0.0
    return float(trend + liquidity - risk - penny_penalty)

# ----------------- Fundamentals for LEAPs -----------------------------
def _growth_rate(series: pd.Series) -> pd.Series:
    try:
        return series.pct_change().replace([np.inf, -np.inf], np.nan)
    except Exception:
        return pd.Series(dtype=float)

def _compute_quarterly_trends(ticker: str) -> Dict[str, float]:
    """
    Uses yf.Ticker(...).quarterly_financials (not deprecated) to build
    last-4-quarter revenue & earnings trends.

    Returns:
      rev_q_yoy, earn_q_yoy  -> avg YoY growth for last 4 matching quarters (needs >=8 qtrs)
      rev_q_qoq, earn_q_qoq  -> avg QoQ growth (fallback if YoY unavailable)
      growth_streak          -> 1.0 if last 4 (YoY) or last 3 (QoQ) readings all positive, else 0.0
      fundamentals_quality   -> 1.0 if YoY used, 0.5 if QoQ fallback, 0.0 if missing
    """
    out = {
        "rev_q_yoy": 0.0, "earn_q_yoy": 0.0,
        "rev_q_qoq": 0.0, "earn_q_qoq": 0.0,
        "growth_streak": 0.0,
        "fundamentals_quality": 0.0,
    }

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tf = yf.Ticker(ticker).quarterly_financials  # wide format, index = fields

        if tf is None or tf.empty:
            return out

        # We want quarters as rows
        qf = tf.T.copy()  # rows=quarters, cols=fields
        # Normalize column names we need
        cols = {c.lower(): c for c in qf.columns}
        rev_col = cols.get("total revenue") or cols.get("revenue")
        ni_col  = cols.get("net income")   or cols.get("netincome")

        if not rev_col or not ni_col:
            return out

        # Ensure numeric, sort oldest->newest by index if possible
        qf = qf.sort_index()
        rev = pd.to_numeric(qf[rev_col], errors="coerce")
        ern = pd.to_numeric(qf[ni_col],  errors="coerce")

        # Prefer YoY if we have >=8 quarters (compare t vs t-4 for last 4)
        if len(rev.dropna()) >= 8 and len(ern.dropna()) >= 8:
            yoy_rev = (rev / rev.shift(4) - 1.0)
            yoy_ern = (ern / ern.shift(4) - 1.0)

            last4_rev = yoy_rev.tail(4).dropna()
            last4_ern = yoy_ern.tail(4).dropna()

            if len(last4_rev) >= 3:
                out["rev_q_yoy"] = float(np.nanmean(last4_rev.values))
            if len(last4_ern) >= 3:
                out["earn_q_yoy"] = float(np.nanmean(last4_ern.values))

            # streak: both revenue & earnings YoY positive in each of last 4
            pos = []
            r4, e4 = yoy_rev.tail(4), yoy_ern.tail(4)
            for r, e in zip(r4.values, e4.values):
                pos.append(pd.notna(r) and r > 0 and pd.notna(e) and e > 0)
            out["growth_streak"] = 1.0 if len(pos) == 4 and all(pos) else 0.0
            out["fundamentals_quality"] = 1.0
            return out

        # Fallback: QoQ (if fewer quarters)
        qoq_rev = rev.pct_change().replace([np.inf, -np.inf], np.nan)
        qoq_ern = ern.pct_change().replace([np.inf, -np.inf], np.nan)

        last3_rev = qoq_rev.tail(3).dropna()
        last3_ern = qoq_ern.tail(3).dropna()

        if len(last3_rev) >= 2:
            out["rev_q_qoq"] = float(np.nanmean(last3_rev.values))
        if len(last3_ern) >= 2:
            out["earn_q_qoq"] = float(np.nanmean(last3_ern.values))

        # streak: last 3 quarters both positive QoQ
        pairs = list(zip(qoq_rev.dropna().tail(3).values, qoq_ern.dropna().tail(3).values))
        out["growth_streak"] = 1.0 if len(pairs) == 3 and all((r > 0 and e > 0) for r, e in pairs) else 0.0
        out["fundamentals_quality"] = 0.5
        return out

    except Exception as e:
        logger.debug(f"[fundamentals] {ticker} failed: {e}")
        return out

# --------------------------- Yahoo fetch ------------------------------
def _clean_tickers(raw: List[str]) -> List[str]:
    return [t.strip().upper() for t in raw if t and t.strip() and t.strip().upper() not in {"US"}]

def _fetch_batch(batch: List[str], start: datetime.date, end: datetime.date) -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    if not batch:
        return out
    attempt = 0
    while attempt <= MAX_RETRIES:
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
                if df.empty:
                    continue
                out[t] = df
            return out
        except Exception:
            attempt += 1
            time.sleep(RETRY_BACKOFF_S * attempt)
    return out

def fetch_prices_batched(tickers: List[str], start: datetime.date, end: datetime.date) -> Dict[str, pd.DataFrame]:
    tickers = _clean_tickers(tickers)
    frames: Dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), BATCH_SIZE):
        frames.update(_fetch_batch(tickers[i:i+BATCH_SIZE], start, end))
    return frames

# --------------------------- Email -----------------------------------
def _render_html_table(df: pd.DataFrame, max_rows=15) -> str:
    dfv = df.head(max_rows).copy()
    for col in dfv.columns:
        dfv[col] = pd.to_numeric(dfv[col], errors="ignore")
    return dfv.to_html(index=False, border=0, justify="left")

def _render_list_html(items: List[str], max_items=60) -> str:
    if not items:
        return "<i>None</i>"
    clip = items[:max_items]
    more = "" if len(items) <= max_items else f" … (+{len(items)-max_items} more)"
    return "<div style='font-family:monospace'>" + ", ".join(clip) + more + "</div>"

def _render_ai_table(df: pd.DataFrame, max_rows: int) -> str:
    if df is None or df.empty:
        return "<i>No AI picks</i>"
    cols = [c for c in ["ticker","ai_score","thesis","risks","suggested_action"] if c in df.columns]
    return df[cols].head(max_rows).to_html(index=False, border=0, justify="left")

def send_email_report(
    df_all: pd.DataFrame,
    df_leaders: pd.DataFrame,
    df_leaps: pd.DataFrame,
    stamp: str,
    *,
    only_in_universe: List[str] | None = None,
    only_in_local: List[str] | None = None,
    changes: Dict[str, List[str]] | None = None,
    ai_leaps_df: pd.DataFrame | None = None,          # <<< NEW
    ai_spreads_df: pd.DataFrame | None = None         # <<< NEW
):
    if os.getenv("SEND_EMAIL","0") != "1":
        return
    email_from = os.getenv("EMAIL_FROM"); pwd = os.getenv("EMAIL_PASSWORD")
    tos = [t.strip() for t in os.getenv("EMAIL_TO","").split(",") if t.strip()]
    subj_prefix = os.getenv("EMAIL_SUBJECT_PREFIX", "Daily Stock Picks")
    if not (email_from and pwd and tos):
        return

    top_picks = df_all[df_all.get("buy_flag", False) == True]
    best5 = df_all.sort_values("final_rank", ascending=False).head(5)
    leaps5 = df_leaps.head(5)

    html_top = "<i>No strict picks today</i>" if top_picks.empty else _render_html_table(
        top_picks[["ticker","final_rank","score","strength_score","last_price"]], max_rows=10
    )
    html_best5 = _render_html_table(best5[["ticker","final_rank","score","strength_score","last_price"]], max_rows=5)
    html_lead = _render_html_table(df_leaders, max_rows=15)
    html_leaps = _render_html_table(leaps5[["ticker","leap_rank","leap_score","ret_63","ret_252","market_cap"]], max_rows=5)

    html_only_universe = _render_list_html(only_in_universe or [])
    html_only_local    = _render_list_html(only_in_local or [])
    added  = (changes or {}).get("added", [])
    removed= (changes or {}).get("removed", [])
    html_added   = _render_list_html(added)
    html_removed = _render_list_html(removed)

    # <<< NEW: AI sections
    ai_k = int(os.getenv("AI_EMAIL_TOPK", str(AI_EMAIL_TOPK)))
    html_ai_leaps   = _render_ai_table(ai_leaps_df, ai_k)
    html_ai_spreads = _render_ai_table(ai_spreads_df, ai_k)

    html_body = f"""<html><body>
      <h2>Daily Stock Picks — {stamp}</h2>

      <h3>Universe vs Local List</h3>
      <p><b>In Universe but NOT in Local:</b><br>{html_only_universe}</p>
      <p><b>In Local but NOT in Universe:</b><br>{html_only_local}</p>

      <h3>Local List Updates</h3>
      <p><b>Added:</b><br>{html_added}</p>
      <p><b>Removed:</b><br>{html_removed}</p>

      <h3>Top Picks (strict buy_flag)</h3>{html_top}
      <h3>Best 5 Overall (by Final Rank)</h3>{html_best5}
      <h3>Leaders (5d &amp; 21d positive, 21d-weighted)</h3>{html_lead}
      <h3>LEAP Picks (Top 5)</h3>{html_leaps}

      <hr>
      <h3>AI: LEAPS (12–24 months) — Top {ai_k}</h3>
      {html_ai_leaps}

      <h3>AI: 30–40 Day Debit Call Spreads — Top {ai_k}</h3>
      {html_ai_spreads}
    </body></html>"""

    msg = EmailMessage()
    msg["From"] = email_from
    msg["To"] = ", ".join(tos)
    msg["Subject"] = f"{subj_prefix} — {stamp}"
    msg.set_content("See HTML version")
    msg.add_alternative(html_body, subtype="html")

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(email_from, pwd)
        s.send_message(msg)

# ----------------- Prune & replenish local list ----------------------
def _prune_and_replenish_local_list(
    df_all: pd.DataFrame,
    local_list: List[str],
    universe_list: List[str],
    *,
    prune_count: int,
    min_price: float,
    min_strength_z: float,
    max_size: int | None
) -> Tuple[List[str], Dict[str, List[str]]]:
    removed, added = [], []

    # prune worst N by final_rank from the current local list
    if prune_count > 0 and len(local_list) > 0:
        pool = df_all[df_all["ticker"].isin(local_list)].copy()
        pool = pool.sort_values("final_rank", ascending=True)
        to_drop = pool["ticker"].head(prune_count).tolist()
        if to_drop:
            removed = to_drop
            local_list = [t for t in local_list if t not in set(to_drop)]

    # replenish from universe by best final_rank not already in list
    candidates = df_all[
        (df_all["ticker"].isin(universe_list)) &
        (~df_all["ticker"].isin(local_list)) &
        (df_all["last_price"] >= min_price) &
        (df_all["strength_score"] >= min_strength_z)
    ].sort_values("final_rank", ascending=False)

    for t in candidates["ticker"].tolist():
        if max_size and len(local_list) >= max_size:
            break
        local_list.append(t)
        added.append(t)

    return local_list, {"added": added, "removed": removed}

# --------------------------- Public API ------------------------------
def run_monitor(tickers: List[str], *, today=None, min_dollar_vol=MIN_DOLLAR_VOL_DEFAULT):
    if today is None:
        today = datetime.date.today()

    # Universe + local list
    seed_list = [t.upper().strip() for t in (tickers or []) if t]
    cached = read_universe_blob()
    universe_tickers = [t.upper().strip() for t in (cached.get("tickers", []) if cached else []) if t]
    local_list = load_local_list(initial_fallback=seed_list)

    merged_tickers = sorted(set(local_list) | set(universe_tickers))
    only_in_universe = sorted(list(set(universe_tickers) - set(local_list)))
    only_in_local    = sorted(list(set(local_list) - set(universe_tickers)))

    end = today + datetime.timedelta(days=1)
    start = today - datetime.timedelta(days=420)
    frames = fetch_prices_batched(merged_tickers, start, end)

    rows: List[Dict] = []
    fast_caps: Dict[str, float] = {}

    # best-effort market caps
    for t in merged_tickers:
        try:
            fi = yf.Ticker(t).fast_info
            mc = fi.get("market_cap")
            if mc:
                fast_caps[t] = float(mc)
        except Exception:
            pass

    # fundamentals cache (avoid per-ticker re-fetch of quarterly_earnings inside apply)
    fundamentals_map: Dict[str, Dict[str, float]] = {}

    for t, df in frames.items():
        d = df.copy()
        d["CloseAdj"] = d["Adj Close"]

        # --- NEW: ADX & MFI (trend strength + volume flow) ---
        d["adx14"] = adx(d, 14)
        d["mfi14"] = mfi(d, 14)

        # --- NEW: EPS surprise (cache per ticker to avoid repeat calls) ---
        # put a small cache dict above the loop if you want (eps_map = {})
        # but simplest inline:
        eps_sig = _eps_surprise_trend(t)
        
        # returns
        d["ret"]     = d["CloseAdj"].pct_change()
        d["ret_5d"]  = d["CloseAdj"].pct_change(5)
        d["ret_20"]  = d["CloseAdj"].pct_change(20)
        d["ret_21d"] = d["CloseAdj"].pct_change(21)
        d["ret_63"]  = d["CloseAdj"].pct_change(63)     # 3m
        d["ret_252"] = d["CloseAdj"].pct_change(252)    # 12m
        d["ret_60"]  = d["CloseAdj"].pct_change(60)
        d["ret_120"] = d["CloseAdj"].pct_change(120)

        # MAs & states
        d["sma20"]   = d["CloseAdj"].rolling(20).mean()
        d["sma50"]   = d["CloseAdj"].rolling(50).mean()
        d["sma200"]  = d["CloseAdj"].rolling(200).mean()
        d["sma50_slope"]  = (d["sma50"].diff(5) / d["sma50"].shift(5)).replace([np.inf, -np.inf], np.nan)
        d["sma200_slope"] = (d["sma200"].diff(10) / d["sma200"].shift(10)).replace([np.inf, -np.inf], np.nan)
        d["close_above_sma50"]  = (d["CloseAdj"] > d["sma50"]).astype(float)
        d["close_above_sma200"] = (d["CloseAdj"] > d["sma200"]).astype(float)

        # oscillators
        d["rsi14"] = rsi(d["CloseAdj"])
        _, _, hist = macd(d["CloseAdj"])
        d["macd_hist"] = hist

        # risk/vol
        d["tr"] = true_range(d)
        d["atr14"] = d["tr"].rolling(14).mean()
        d["vol20"] = realized_vol(d["ret"], 20)
        d["vol60"] = realized_vol(d["ret"], 60)
        d["mdd_60"] = (d["CloseAdj"] / d["CloseAdj"].cummax() - 1.0).rolling(60).min()

        # liquidity & volume
        d["vol20_sh"] = d["Volume"].rolling(20).mean()
        d["vol60_sh"] = d["Volume"].rolling(60).mean()
        d["adv_usd_20"] = d["vol20_sh"] * d["CloseAdj"].rolling(20).mean()
        d["adv_usd_60"] = d["vol60_sh"] * d["CloseAdj"].rolling(60).mean()
        d["vol_surge"]  = (d["adv_usd_20"] / d["adv_usd_60"]).replace([np.inf, -np.inf], np.nan)

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

        latest = d.iloc[-1].to_dict()
        latest["ticker"] = t
        latest["last_price"] = float(d["CloseAdj"].iloc[-1])
        latest["market_cap"] = fast_caps.get(t, np.nan)
        latest["adx14"] = float(d["adx14"].iloc[-1])
        latest["mfi14"] = float(d["mfi14"].iloc[-1])

        latest["eps_surprise_avg"] = float(eps_sig.get("eps_surprise_avg", 0.0))
        latest["eps_beat_share"]   = float(eps_sig.get("eps_beat_share", 0.0))
        # -------- fundamentals (4-quarter trend) ----------
        if t not in fundamentals_map:
            fundamentals_map[t] = _compute_quarterly_trends(t)
        latest.update(fundamentals_map[t])

        # cap bonus for LEAPs (reused later)
        try:
            mc = float(latest["market_cap"]) if latest.get("market_cap") is not None else np.nan
        except Exception:
            mc = np.nan
        if np.isnan(mc):
            latest["cap_bonus"] = 0.0
        elif mc < 2e9:
            latest["cap_bonus"] = -0.3
        elif mc < 10e9:
            latest["cap_bonus"] = 0.1
        elif mc < 200e9:
            latest["cap_bonus"] = 0.2
        else:
            latest["cap_bonus"] = 0.25

        rows.append(latest)

    if not rows:
        raise RuntimeError("No rows produced—check data availability or ticker list.")

    out = pd.DataFrame(rows)

    # Strictly drop penny stocks (< $5) from all further processing
    out = out[out["last_price"] >= PENNY_PRICE].copy()
    if out.empty:
        raise RuntimeError("All tickers filtered out by penny-stock exclusion.")
        
    # x-sectional ADV z
    out["adv_usd_20_z"] = zscore(out.get("adv_usd_20", pd.Series(dtype=float))).fillna(0.0)

    # composite score & buy flag
    out["score"] = out.apply(lambda r: score_row(r, min_dollar_vol), axis=1)
    out["buy_flag"] = (
        (out["score"] > 1.5) &
        (out["rsi14"].between(45, 80)) &
        (out["close_above_sma50"] == 1.0) &
        (out["close_above_sma200"] == 1.0) &
        (out["dist_52w_high"] > -0.10) &
        (out["last_price"] >= PENNY_PRICE)
    )

    # strength & final rank (60/40 + cap bias)
    out["z_5d"] = zscore(out.get("ret_5d", pd.Series(dtype=float))).fillna(0.0)
    out["z_21d"] = zscore(out.get("ret_21d", pd.Series(dtype=float))).fillna(0.0)
    out["strength_score"] = 0.3 * out["z_5d"] + 0.7 * out["z_21d"]

    def _pctl0_10(s: pd.Series) -> pd.Series:
        return (s.rank(pct=True).fillna(0.0) * 10.0)

    out["norm_score_0_10"]    = _pctl0_10(out["score"])
    out["norm_strength_0_10"] = _pctl0_10(out["strength_score"])
    out["final_60_40"]        = 0.6 * out["norm_score_0_10"] + 0.4 * out["norm_strength_0_10"]
    out["cap_mult"]           = out["market_cap"].apply(cap_multiplier)
    out["final_rank"]         = out["final_60_40"] * out["cap_mult"]

    # ----------------- LEAP scoring (with fundamentals) ----------------
    out["z_ret_63"]  = zscore(out.get("ret_63", pd.Series(dtype=float))).fillna(0.0)
    out["z_ret_252"] = zscore(out.get("ret_252", pd.Series(dtype=float))).fillna(0.0)

    # Use YoY when quality==1.0, otherwise QoQ fallback
    rev_growth = np.where(out["fundamentals_quality"] >= 1.0, out["rev_q_yoy"], out["rev_q_qoq"])
    ern_growth = np.where(out["fundamentals_quality"] >= 1.0, out["earn_q_yoy"], out["earn_q_qoq"])

    # Clip extremes
    rev_growth = pd.Series(rev_growth, index=out.index).clip(lower=-1.0, upper=1.0).fillna(0.0)
    ern_growth = pd.Series(ern_growth, index=out.index).clip(lower=-1.0, upper=1.0).fillna(0.0)
    streak     = out.get("growth_streak", pd.Series(0.0, index=out.index)).fillna(0.0)
    # --- NEW: EPS surprise contributions ---
    eps_avg = out["eps_surprise_avg"].astype(float).fillna(0.0)
    # Clamp to +/-20% in decimal to avoid outliers (i.e., [-0.20, +0.20])
    eps_avg = eps_avg.clip(lower=-0.20, upper=0.20)
    # Share of last 4 beats in [0..1]
    eps_beat = out["eps_beat_share"].astype(float).fillna(0.0)
    
    out["leap_score"] = (
        0.30 * out["z_ret_63"] +
        0.35 * out["z_ret_252"] +
        0.10 * out["cap_bonus"] -
        0.15 * out.get("vol60", pd.Series(0.0, index=out.index)).fillna(0.0) +
        0.10 * rev_growth +
        0.10 * ern_growth +
        0.05 * streak +
        0.06 * eps_avg +       # avg surprise (decimal)
        0.04 * eps_beat 
    )
    out["leap_rank"]  = _pctl0_10(out["leap_score"])

    # leaders & leaps tables
    leaders = out[(out.get("ret_5d", 0) > 0) & (out.get("ret_21d", 0) > 0)].copy().sort_values("strength_score", ascending=False)
    leaps   = out.sort_values("leap_rank", ascending=False)

    # --------- AI: rank combined local + universe for email -----------
    # Build combined candidate set (and enforce >=$5 using our computed prices)
    price_map = dict(zip(out["ticker"].astype(str).str.upper(), out["last_price"].astype(float)))
    combined = sorted(set(local_list) | set(universe_tickers))
    combined = [t.upper().strip() for t in combined if price_map.get(t.upper().strip(), float("inf")) >= PENNY_PRICE]

    ai_leaps_df   = ai_rank_tickers(combined, strategy="leaps",               horizon_text="12–24 months", top_k=AI_EMAIL_TOPK)
    ai_spreads_df = ai_rank_tickers(combined, strategy="debit_call_spread",   horizon_text="30–40 days",   top_k=AI_EMAIL_TOPK)

    out["score"] = out.apply(lambda r: score_row(r, min_dollar_vol, "debit_call_spread"), axis=1)
    # --------- prune & replenish local list, then persist ------------
    try:
        new_local_list, changes = _prune_and_replenish_local_list(
            df_all=out,
            local_list=list(local_list),  # copy
            universe_list=universe_tickers,
            prune_count=LOCAL_PRUNE_COUNT,
            min_price=LOCAL_ADD_MIN_PRICE,
            min_strength_z=LOCAL_ADD_MIN_STRENGTH_Z,
            max_size=LOCAL_MAX_SIZE
        )
        save_local_list(new_local_list, meta={"updated_utc": datetime.datetime.utcnow().isoformat()+"Z"})
        logger.info(f"[local_list] removed={len(changes.get('removed',[]))} added={len(changes.get('added',[]))} size={len(new_local_list)}")
    except Exception as e:
        logger.warning(f"[local_list] update/save failed: {e}")
        changes = {"added": [], "removed": []}

    # email report (now with AI sections)
    stamp = today.strftime("%Y-%m-%d")
    send_email_report(
        out,
        leaders[["ticker","ret_5d","ret_21d","strength_score"]],
        leaps,
        stamp,
        only_in_universe=only_in_universe,
        only_in_local=only_in_local,
        changes=changes,
        ai_leaps_df=ai_leaps_df,
        ai_spreads_df=ai_spreads_df
    )

    # return main tables
    cols_order = [
        "ticker", "final_rank", "final_60_40", "cap_mult",
        "norm_score_0_10", "norm_strength_0_10",
        "score", "strength_score", "ret_5d", "ret_21d",
        "last_price", "market_cap",
        "adv_usd_20", "adv_usd_20_z", "vol_surge",
        "rsi14", "close_above_sma50", "close_above_sma200", "dist_52w_high", "buy_flag",
        # LEAP fundamentals we now compute
        "rev_q_yoy", "earn_q_yoy", "rev_q_qoq", "earn_q_qoq", "growth_streak", "fundamentals_quality",
        "z_ret_63", "z_ret_252", "cap_bonus", "leap_score", "leap_rank",
            # include near the end of cols_order
        "adx14", "mfi14", "eps_surprise_avg", "eps_beat_share"
    ]
    for c in cols_order:
        if c not in out.columns:
            out[c] = np.nan
    df_all_sorted = out[cols_order].sort_values("final_rank", ascending=False)

    df_all_sorted = _shrink_df(df_all_sorted)
    leaders = _shrink_df(leaders[["ticker","ret_5d","ret_21d","strength_score"]])

    return df_all_sorted, leaders