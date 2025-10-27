# monitoring/monitor.py

import os
import logging
import datetime
import numpy as np
import pandas as pd
import yfinance as yf

from .config import (
    DAILY_MONITOR_LOG_LEVEL,
    MIN_DOLLAR_VOL_DEFAULT, PENNY_PRICE,
    LOCAL_PRUNE_COUNT, LOCAL_MAX_SIZE, LOCAL_ADD_MIN_PRICE, LOCAL_ADD_MIN_STRENGTH_Z,
    AI_EMAIL_TOPK, ADD_LEADERS_TOPK,
    USE_MC_HMM_FILTER, MC_MIN_PUP, HMM_MIN_BULL,
)
from .indicators import adx, mfi, rsi, macd, true_range, realized_vol, zscore
from .fundamentals import eps_surprise_trend, compute_quarterly_trends, cap_multiplier
from .simulations import mc_paths_prob_up, fit_hmm_regime
from .data_fetch import fetch_prices_batched
from .scoring import score_row
from .local_list_ops import prune_and_replenish_local_list
from .emailer import send_email_report_with_sims  # emailer that shows sims + options + performance table

# external utils
from universe_utils import read_universe_blob
from local_list_utils import load_local_list, save_local_list
from ai_utils import ai_rank_tickers

# 30-day direction ML model
from .model_predict import train_direction_model, predict_up_probability_for_latest

logging.basicConfig(
    level=getattr(logging, DAILY_MONITOR_LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _shrink_df(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    for c in d.select_dtypes(include=["float64"]).columns:
        d[c] = pd.to_numeric(d[c], downcast="float")
    for c in d.select_dtypes(include=["int64"]).columns:
        d[c] = pd.to_numeric(d[c], downcast="integer")
    if "ticker" in d.columns and d["ticker"].dtype != "category":
        d["ticker"] = d["ticker"].astype("category")
    return d


def run_monitor(tickers, *, today=None, min_dollar_vol=MIN_DOLLAR_VOL_DEFAULT):
    if today is None:
        today = datetime.date.today()

    # Universe + local list
    seed_list = [t.upper().strip() for t in (tickers or []) if t]
    cached = read_universe_blob()
    universe_tickers = [t.upper().strip() for t in (cached.get("tickers", []) if cached else []) if t]
    local_list = load_local_list(initial_fallback=seed_list)

    merged_tickers = sorted(set(local_list) | set(universe_tickers))
    end = today + datetime.timedelta(days=1)
    start = today - datetime.timedelta(days=420)
    frames = fetch_prices_batched(merged_tickers, start, end)

    rows = []
    fast_caps = {}
    enriched_frames: dict[str, pd.DataFrame] = {}

    # best-effort market caps
    for t in merged_tickers:
        try:
            fi = yf.Ticker(t).fast_info
            mc = fi.get("market_cap")
            if mc:
                fast_caps[t] = float(mc)
        except Exception:
            pass

    fundamentals_map = {}

    # ---- per-ticker feature engineering ----
    for t, df in frames.items():
        d = df.copy()
        d["CloseAdj"] = d["Adj Close"]

        # trend & flow
        d["adx14"] = adx(d, 14)
        d["mfi14"] = mfi(d, 14)

        # returns (needed by sims & other features)
        d["ret"]     = d["CloseAdj"].pct_change()
        d["ret_5d"]  = d["CloseAdj"].pct_change(5)
        d["ret_20"]  = d["CloseAdj"].pct_change(20)
        d["ret_21d"] = d["CloseAdj"].pct_change(21)
        d["ret_63"]  = d["CloseAdj"].pct_change(63)
        d["ret_120"] = d["CloseAdj"].pct_change(120)
        d["ret_252"] = d["CloseAdj"].pct_change(252)

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

        # highs / breakouts
        d["hi_252"] = d["CloseAdj"].rolling(252, min_periods=60).max()
        d["dist_52w_high"] = d["CloseAdj"] / d["hi_252"] - 1.0

        # momentum z-scores
        for col in ["ret_20", "ret_60", "ret_120"]:
           if col not in d.columns:
              d[col] = np.nan  # ensure column exists even if data is short
           mu = d[col].rolling(180).mean()
           sd = d[col].rolling(180).std()
           d[f"{col}_z"] = (d[col] - mu) / sd.replace(0, np.nan)
        
        eps_sig = eps_surprise_trend(t)

        # ---- Monte Carlo & HMM ----
        mu_d    = float(d["ret"].rolling(63).mean().iloc[-1])
        sigma_d = float(d["ret"].rolling(20).std().iloc[-1])
        mc_p30  = mc_paths_prob_up(float(d["CloseAdj"].iloc[-1]), mu_d, sigma_d, 30, 5000, 0.0)
        mc_p40  = mc_paths_prob_up(float(d["CloseAdj"].iloc[-1]), mu_d, sigma_d, 40, 5000, 0.0)
        state_today, prob_bull = fit_hmm_regime(d["ret"])

        if t not in fundamentals_map:
            fundamentals_map[t] = compute_quarterly_trends(t)

        latest = d.iloc[-1].to_dict()
        latest["ticker"] = t
        latest["last_price"] = float(d["CloseAdj"].iloc[-1])
        latest["market_cap"] = fast_caps.get(t, np.nan)
        latest["adx14"] = float(d["adx14"].iloc[-1])
        latest["mfi14"] = float(d["mfi14"].iloc[-1])
        latest["eps_surprise_avg"] = float(eps_sig.get("eps_surprise_avg", 0.0))
        latest["eps_beat_share"]   = float(eps_sig.get("eps_beat_share", 0.0))
        latest["mc_p_up_30d"]      = mc_p30
        latest["mc_p_up_40d"]      = mc_p40
        latest["hmm_state"]        = state_today
        latest["hmm_prob_bull"]    = prob_bull
        latest.update(fundamentals_map[t])

        mc_val = latest.get("market_cap")
        try:
            mc_val = float(mc_val) if mc_val is not None else np.nan
        except Exception:
            mc_val = np.nan
        if np.isnan(mc_val):
            latest["cap_bonus"] = 0.0
        elif mc_val < 2e9:
            latest["cap_bonus"] = -0.3
        elif mc_val < 10e9:
            latest["cap_bonus"] = 0.1
        elif mc_val < 200e9:
            latest["cap_bonus"] = 0.2
        else:
            latest["cap_bonus"] = 0.25

        rows.append(latest)
        enriched_frames[t] = d

    out = pd.DataFrame(rows)
    out = out[out["last_price"] >= PENNY_PRICE].copy()

    # ---- ML 30-day probability ----
    try:
        mdl, _, _ = train_direction_model(enriched_frames, horizon_days=30)
        ml_prob_map = predict_up_probability_for_latest(enriched_frames, mdl)
    except Exception as e:
        logger.warning(f"[ML] training/predict failed: {e}")
        ml_prob_map = {}

    out["adv_usd_20_z"] = zscore(out.get("adv_usd_20", pd.Series(dtype=float))).fillna(0.0)
    out["score"] = out.apply(lambda r: score_row(r, min_dollar_vol, "debit_call_spread"), axis=1)

    base_buy = (
        (out["score"] > 1.5) &
        (out["rsi14"].between(45, 80)) &
        (out["close_above_sma50"] == 1.0) &
        (out["close_above_sma200"] == 1.0) &
        (out["dist_52w_high"] > -0.10)
    )
    if USE_MC_HMM_FILTER:
        mc_ok  = out["mc_p_up_30d"].fillna(0.0) >= MC_MIN_PUP
        hmm_ok = out["hmm_prob_bull"].fillna(0.0) >= HMM_MIN_BULL
        out["buy_flag"] = base_buy & mc_ok & hmm_ok
    else:
        out["buy_flag"] = base_buy

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

    out["z_ret_63"]  = zscore(out.get("ret_63", pd.Series(dtype=float))).fillna(0.0)
    out["z_ret_252"] = zscore(out.get("ret_252", pd.Series(dtype=float))).fillna(0.0)

    rev_growth = np.where(out["fundamentals_quality"] >= 1.0, out["rev_q_yoy"], out["rev_q_qoq"])
    ern_growth = np.where(out["fundamentals_quality"] >= 1.0, out["earn_q_yoy"], out["earn_q_qoq"])
    rev_growth = pd.Series(rev_growth, index=out.index).clip(-1.0, 1.0).fillna(0.0)
    ern_growth = pd.Series(ern_growth, index=out.index).clip(-1.0, 1.0).fillna(0.0)

    out["leap_score"] = (
        0.30 * out["z_ret_63"] +
        0.35 * out["z_ret_252"] +
        0.10 * out["cap_bonus"] -
        0.15 * out.get("vol60", pd.Series(0.0)).fillna(0.0) +
        0.10 * rev_growth + 0.10 * ern_growth
    )
    out["leap_rank"] = _pctl0_10(out["leap_score"])

    out["ml_prob_up_30d"] = out["ticker"].map(ml_prob_map).astype(float).fillna(0.5)

    # leaders & leaps
    leaders = out[(out.get("ret_5d", 0) > 0) & (out.get("ret_21d", 0) > 0)].copy().sort_values("strength_score", ascending=False)

    ai_leaps_df = ai_rank_tickers(merged_tickers, strategy="leaps", horizon_text="12–24 months", top_k=AI_EMAIL_TOPK)
    ai_spreads_df = ai_rank_tickers(merged_tickers, strategy="debit_call_spread", horizon_text="30–40 days", top_k=AI_EMAIL_TOPK)

    # ------- Email data -------
    picks = out[out["buy_flag"]].copy()
    leaders_top = leaders.head(ADD_LEADERS_TOPK)
    picks_tickers = list(dict.fromkeys(
        [*picks["ticker"].astype(str).tolist(), *leaders_top["ticker"].astype(str).tolist()]
    ))

    def _tickers_only(df):
        if df is None or df.empty:
            return []
        d = df.copy()
        if "ai_score" in d.columns:
            d = d.sort_values("ai_score", ascending=False)
        return d["ticker"].astype(str).tolist()

    ai_spreads_list = _tickers_only(ai_spreads_df)[:AI_EMAIL_TOPK]
    ai_leaps_list = _tickers_only(ai_leaps_df)[:AI_EMAIL_TOPK]

    sim_df = out[out["ticker"].isin(picks_tickers)][["ticker", "mc_p_up_30d", "hmm_prob_bull", "ml_prob_up_30d"]]
    sim_rows = [
        {"ticker": str(r["ticker"]), "mc30": r["mc_p_up_30d"], "hmm_bull": r["hmm_prob_bull"], "ml_prob": r["ml_prob_up_30d"]}
        for _, r in sim_df.iterrows()
    ]

    # --- NEW: performance table for email ---
    perf_rows = []
    for _, r in out[out["ticker"].isin(picks_tickers)].iterrows():
        perf_rows.append({
            "ticker": str(r["ticker"]),
            "perf_5d": float(r.get("ret_5d", 0)) * 100,
            "perf_1m": float(r.get("ret_21d", 0)) * 100,
            "perf_6m": float(r.get("ret_120", 0)) * 100,
        })

    stamp = today.strftime("%Y-%m-%d")
    send_email_report_with_sims(
        stamp=stamp,
        picks_tickers=picks_tickers,
        ai_spreads_list=ai_spreads_list,
        ai_leaps_list=ai_leaps_list,
        sim_rows=sim_rows,
        opt_rows=[],       # placeholder — still valid
        perf_rows=perf_rows,  # new table
        subj_prefix=os.getenv("EMAIL_SUBJECT_PREFIX", "Daily Stock Picks"),
    )

    df_all_sorted = _shrink_df(out.sort_values("final_rank", ascending=False))
    leaders = _shrink_df(leaders[["ticker", "ret_5d", "ret_21d", "strength_score"]])
    return df_all_sorted, leaders