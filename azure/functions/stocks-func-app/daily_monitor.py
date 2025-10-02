# daily_monitor.py
import os
import time
import math
import logging
import datetime
from typing import List, Tuple, Dict
import json
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

import numpy as np
import pandas as pd
import yfinance as yf
import smtplib, ssl
from email.message import EmailMessage

# ---------------------------------------------------------------------
# Logging (inherits level/handlers from Function App or local script)
# ---------------------------------------------------------------------
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

# ---------------------------------------------------------------------
# Tunables (can be overridden via env)
# ---------------------------------------------------------------------
BATCH_SIZE      = int(os.getenv("YF_BATCH_SIZE", "50"))    # tickers per download call
MAX_RETRIES     = int(os.getenv("YF_MAX_RETRIES", "2"))    # per-batch retries
RETRY_BACKOFF_S = float(os.getenv("YF_RETRY_BACKOFF_S", "3.0"))
MIN_DOLLAR_VOL_DEFAULT = int(os.getenv("MIN_DOLLAR_VOL", "1000000"))

# Universe fetch
UNIVERSE_URL        = os.getenv("UNIVERSE_URL", "http://localhost:7071/api/universe")
UNIVERSE_TIMEOUT_S  = float(os.getenv("UNIVERSE_TIMEOUT_S", "8.0"))

# ---------------------------------------------------------------------
# Indicators & helpers
# ---------------------------------------------------------------------
def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    logger.debug(f"Computing RSI n={n}")
    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).rolling(n).mean()
    roll_down = pd.Series(down, index=series.index).rolling(n).mean()
    rs = roll_up / (roll_down.replace(0, np.nan))
    return (100 - (100 / (1 + rs))).fillna(50)

def macd(series: pd.Series, fast=12, slow=26, signal=9):
    logger.debug(f"Computing MACD fast={fast} slow={slow} signal={signal}")
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def true_range(df: pd.DataFrame) -> pd.Series:
    logger.debug("Computing True Range")
    prev_close = df["Adj Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr

def realized_vol(returns: pd.Series, n=20):
    logger.debug(f"Computing realized volatility n={n}")
    return returns.rolling(n).std() * np.sqrt(252)

def zscore(s: pd.Series) -> pd.Series:
    mu, sd = s.mean(), s.std()
    if pd.isna(sd) or sd == 0:
        return pd.Series(0.0, index=s.index)
    return (s - mu) / sd

# ---------------------------------------------------------------------
# Trend-follow scoring (composite, before merge)
# ---------------------------------------------------------------------
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
    event_penalty = 0.0  # no earnings calendar here
    return float(momentum_trend + liquidity - risk_penalty - event_penalty)

# ---------------------------------------------------------------------
# Yahoo fetch (BATCHED + RETRIES + LOGGING)
# ---------------------------------------------------------------------
def _clean_tickers(raw: List[str]) -> List[str]:
    cleaned = []
    for t in raw:
        ts = (t or "").strip().upper()
        if not ts or ts in {"US"}:
            logger.warning(f"[tickers] skipping invalid: '{t}'")
            continue
        cleaned.append(ts)
    return cleaned

def _fetch_batch(batch: List[str], start: datetime.date, end: datetime.date) -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    if not batch:
        return out

    attempt = 0
    while attempt <= MAX_RETRIES:
        try:
            logger.info(f"[yf] downloading batch size={len(batch)} attempt={attempt+1}/{MAX_RETRIES+1}")
            data = yf.download(
                tickers=batch,
                start=start, end=end,
                auto_adjust=False,
                group_by="ticker",
                progress=False,
                threads=True
            )
            for t in batch:
                if t in data:
                    df = data[t]
                else:
                    if len(batch) == 1 and isinstance(data, pd.DataFrame) and \
                       set(["Adj Close","Close","High","Low","Open","Volume"]).issubset(set(data.columns)):
                        df = data
                    else:
                        logger.warning(f"[yf] no data key for {t}")
                        continue

                df = df.dropna(subset=["Adj Close"]).copy()
                if df.empty:
                    logger.warning(f"[yf] empty frame for {t}")
                    continue
                out[t] = df
            return out

        except Exception as e:
            attempt += 1
            logger.error(f"[yf] batch download failed (attempt {attempt}): {e}")
            if attempt <= MAX_RETRIES:
                sleep_s = RETRY_BACKOFF_S * attempt
                logger.info(f"[yf] retrying in {sleep_s:.1f}s …")
                time.sleep(sleep_s)
            else:
                logger.error("[yf] max retries reached; skipping this batch")

    return out

def fetch_prices_batched(tickers: List[str], start: datetime.date, end: datetime.date) -> Dict[str, pd.DataFrame]:
    tickers = _clean_tickers(tickers)
    frames: Dict[str, pd.DataFrame] = {}
    n = len(tickers)
    if n == 0:
        logger.error("[yf] no valid tickers to download")
        return frames

    logger.info(f"[yf] fetching prices for {n} tickers in batches of {BATCH_SIZE}")
    for i in range(0, n, BATCH_SIZE):
        batch = tickers[i:i+BATCH_SIZE]
        got = _fetch_batch(batch, start, end)
        frames.update(got)
        logger.info(f"[yf] batch {i//BATCH_SIZE+1}/{math.ceil(n/BATCH_SIZE)}: downloaded {len(got)}/{len(batch)} symbols")

    missing = [t for t in tickers if t not in frames]
    if missing:
        logger.warning(f"[yf] missing/failed symbols: {len(missing)} e.g. {missing[:10]}{'...' if len(missing)>10 else ''}")
    logger.info(f"[yf] total downloaded symbols: {len(frames)}")
    return frames

# ---------------------------------------------------------------------
# Universe fetch (HTTP GET to your Function App)
# ---------------------------------------------------------------------
def _fetch_universe_tickers() -> List[str]:
    url = UNIVERSE_URL
    if not url:
        logger.info("[universe] UNIVERSE_URL not set; skipping")
        return []
    try:
        logger.info(f"[universe] GET {url}")
        req = Request(url, headers={"User-Agent":"daily-monitor/1.0"})
        with urlopen(req, timeout=UNIVERSE_TIMEOUT_S) as resp:
            data = resp.read()
        js = json.loads(data.decode("utf-8"))
        if not isinstance(js, dict):
            logger.warning("[universe] unexpected response type")
            return []
        if not js.get("ok"):
            logger.warning(f"[universe] ok=false: {js}")
            return []
        raw = js.get("tickers") or []
        out = [str(t).upper().strip() for t in raw if str(t).strip()]
        logger.info(f"[universe] received {len(out)} tickers (stale={js.get('stale')})")
        return out
    except HTTPError as e:
        logger.warning(f"[universe] HTTP error {e.code}: {e.reason}")
    except URLError as e:
        logger.warning(f"[universe] URL error: {e.reason}")
    except Exception as e:
        logger.exception(f"[universe] failed: {e}")
    return []

# ---------------------------------------------------------------------
# SMTP Email
# ---------------------------------------------------------------------
def _render_html_table(df: pd.DataFrame, max_rows=15) -> str:
    dfv = df.head(max_rows).copy()
    for col in ("final_rank","score","ret_5d","ret_21d","strength_score"):
        if col in dfv.columns:
            dfv[col] = pd.to_numeric(dfv[col], errors="coerce").round(4)
    return dfv.to_html(index=False, border=0, justify="left")

def _render_list_html(items: List[str], max_items=50) -> str:
    if not items:
        return "<i>None</i>"
    clip = items[:max_items]
    more = "" if len(items) <= max_items else f" … (+{len(items)-max_items} more)"
    return "<div style='font-family:monospace'>" + ", ".join(clip) + more + "</div>"

def send_email_report(
    df_all: pd.DataFrame,
    df_leaders: pd.DataFrame,
    stamp: str,
    *,
    only_in_universe: List[str] | None = None,
    only_in_local: List[str] | None = None
):
    """
    Send email with picks as HTML, attach CSVs.
    Shows diff between universe vs local list.
    Env vars:
      SEND_EMAIL=1
      SMTP_SERVER, SMTP_PORT (465=SSL, 587=STARTTLS; fallback enabled)
      EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO (comma-separated)
      EMAIL_SUBJECT_PREFIX (optional), MAX_EMAIL_ROWS (optional)
    """
    if os.getenv("SEND_EMAIL","0") != "1":
        logger.info("[email] SEND_EMAIL!=1; skipping email")
        return

    server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    port_env = os.getenv("SMTP_PORT", "").strip()
    email_from = os.getenv("EMAIL_FROM")
    pwd        = os.getenv("EMAIL_PASSWORD")
    tos        = [t.strip() for t in os.getenv("EMAIL_TO","").split(",") if t.strip()]
    subject_prefix = os.getenv("EMAIL_SUBJECT_PREFIX", "Daily Stock Picks")
    max_rows  = int(os.getenv("MAX_EMAIL_ROWS","15"))

    if not (server and email_from and pwd and tos):
        logger.warning("[email] missing SMTP config; need SMTP_SERVER, EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO")
        return

    # Tables for email (by merged final rank)
    top_picks = df_all[df_all.get("buy_flag", False) == True][
        ["ticker","final_rank","score","strength_score"]
    ].sort_values("final_rank", ascending=False)

    overall = df_all[["ticker","final_rank","score","strength_score"]].copy() \
                .sort_values("final_rank", ascending=False)

    html_top  = _render_html_table(top_picks, max_rows)
    html_over = _render_html_table(overall, max_rows)

    # Diff sections
    html_only_universe = _render_list_html(only_in_universe or [])
    html_only_local    = _render_list_html(only_in_local or [])

    html_body = f"""<html><body>
      <h2>Daily Stock Picks — {stamp}</h2>

      <h3>Universe vs Local List</h3>
      <p><b>In Universe but NOT in Local:</b><br>{html_only_universe}</p>
      <p><b>In Local but NOT in Universe (FYI):</b><br>{html_only_local}</p>

      <h3>Top Picks (buy_flag) — ranked by Final (60% Score / 40% Perf)</h3>{html_top}
      <h3>Overall — ranked by Final (60% Score / 40% Perf)</h3>{html_over}
    </body></html>"""

    msg = EmailMessage()
    msg["From"] = email_from
    msg["To"] = ", ".join(tos)
    msg["Subject"] = f"{subject_prefix} — {stamp}"
    msg.set_content("See HTML version")
    msg.add_alternative(html_body, subtype="html")

    # Attach CSVs for convenience
    msg.add_attachment(df_all.to_csv(index=False).encode("utf-8"),
                       maintype="text", subtype="csv",
                       filename=f"daily_snapshot_{stamp}.csv")
    msg.add_attachment(df_leaders.to_csv(index=False).encode("utf-8"),
                       maintype="text", subtype="csv",
                       filename=f"leaders_{stamp}.csv")

    def _try_ssl():
        port = int(port_env or "465")
        logger.info(f"[email] attempting SSL SMTP: host={server} port={port} from={email_from} to={len(tos)}")
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(server, port, context=ctx, timeout=30) as s:
            s.login(email_from, pwd)
            s.send_message(msg)

    def _try_starttls():
        port = int(port_env or "587")
        logger.info(f"[email] attempting STARTTLS SMTP: host={server} port={port} from={email_from} to={len(tos)}")
        ctx = ssl.create_default_context()
        with smtplib.SMTP(server, port, timeout=30) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.ehlo()
            s.login(email_from, pwd)
            s.send_message(msg)

    try:
        _try_ssl()
        logger.info("[email] sent via SSL")
        return
    except Exception as e1:
        logger.warning(f"[email] SSL path failed: {e1}")

    try:
        _try_starttls()
        logger.info("[email] sent via STARTTLS")
    except Exception as e2:
        logger.exception(f"[email] both SSL and STARTTLS failed: {e2}")
        raise

# ---------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------
def run_monitor(
    tickers: List[str],
    *,
    today: datetime.date | None = None,
    min_dollar_vol: int = MIN_DOLLAR_VOL_DEFAULT
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Builds:
      - df_all: full table sorted by FINAL rank (60% composite score, 40% return strength)
      - df_leaders: convenience table (5d & 21d positive, 21d-weighted)
    Also:
      - Fetches 'universe' from Function App and unions with the provided list
      - Email includes which tickers are only in universe vs only in local list
    """
    if today is None:
        today = datetime.date.today()

    # ----- Pull universe & merge -----
    local_list = [str(t).upper().strip() for t in (tickers or []) if str(t).strip()]
    universe_list = _fetch_universe_tickers()
    only_in_universe = sorted(list(set(universe_list) - set(local_list)))
    only_in_local    = sorted(list(set(local_list) - set(universe_list)))
    merged_tickers   = sorted(list(set(local_list).union(set(universe_list))))

    logger.info(f"[monitor] local={len(local_list)} universe={len(universe_list)} merged={len(merged_tickers)}")
    if only_in_universe:
        logger.info(f"[monitor] in universe not in local: {only_in_universe[:20]}{'...' if len(only_in_universe)>20 else ''}")
    if only_in_local:
        logger.info(f"[monitor] in local not in universe: {only_in_local[:20]}{'...' if len(only_in_local)>20 else ''}")

    end = today + datetime.timedelta(days=1)
    start = today - datetime.timedelta(days=420)

    logger.info(f"[monitor] start={start} end={end}")
    frames = fetch_prices_batched(merged_tickers, start, end)
    rows: List[Dict] = []

    for t, df in frames.items():
        try:
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

            d_valid = d.dropna(subset=["CloseAdj", "sma50", "sma200"])
            if d_valid.empty:
                logger.warning(f"[monitor] no valid last row for {t}; skipping")
                continue

            latest = d.iloc[-1].to_dict()
            latest["ticker"] = t
            rows.append(latest)
        except Exception as e:
            logger.exception(f"[monitor] error processing {t}: {e}")

    if not rows:
        raise RuntimeError("No rows produced—check data availability or ticker list.")

    out = pd.DataFrame(rows)

    # Composite trend-follow score
    out["score"] = out.apply(lambda r: score_row(r, min_dollar_vol), axis=1)

    # Buy filter (kept as a sanity gate)
    out["buy_flag"] = (
        (out["score"] > 1.5) &
        (out["rsi14"].between(45, 80)) &
        (out["close_above_sma50"] == 1.0) &
        (out["close_above_sma200"] == 1.0) &
        (out["dist_52w_high"] > -0.10)
    )

    # Performance strength (5d & 21d positive bias to 21d)
    out["z_5d"] = zscore(out["ret_5d"]).fillna(0.0)
    out["z_21d"] = zscore(out["ret_21d"]).fillna(0.0)
    out["strength_score"] = 0.3 * out["z_5d"] + 0.7 * out["z_21d"]

    # ---- 60/40 MERGE: percentile-normalized to 0..10, then weighted ----
    def _pctl0_10(s: pd.Series) -> pd.Series:
        return (s.rank(pct=True).fillna(0.0) * 10.0)

    out["norm_score_0_10"]    = _pctl0_10(out["score"])
    out["norm_strength_0_10"] = _pctl0_10(out["strength_score"])
    out["final_rank"] = 0.6 * out["norm_score_0_10"] + 0.4 * out["norm_strength_0_10"]

    # Leaders view (unchanged)
    leaders = out[(out["ret_5d"] > 0) & (out["ret_21d"] > 0)].copy()
    leaders = leaders.sort_values("strength_score", ascending=False)

    # Email report (with diffs)
    stamp = today.strftime("%Y-%m-%d")
    try:
        send_email_report(
            out,
            leaders[["ticker","ret_5d","ret_21d","strength_score"]],
            stamp,
            only_in_universe=only_in_universe,
            only_in_local=only_in_local
        )
    except Exception as e:
        logger.exception(f"[email] failed to send report: {e}")

    logger.info("[monitor] completed")

    # Return full table sorted by FINAL rank
    cols_order = [
        "ticker", "final_rank", "norm_score_0_10", "norm_strength_0_10",
        "score", "strength_score", "ret_5d", "ret_21d", "rsi14",
        "close_above_sma50", "close_above_sma200", "dist_52w_high", "buy_flag"
    ]
    for c in cols_order:
        if c not in out.columns:
            out[c] = np.nan
    df_all_sorted = out[cols_order].sort_values("final_rank", ascending=False)

    return df_all_sorted, leaders[["ticker","ret_5d","ret_21d","strength_score"]]