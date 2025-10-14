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
    # NEW: options gates (with safe defaults)
    OPT_MIN_OI, OPT_MAX_SPREAD_PCT,
    IVP_MIN, IVP_MAX,
    DTE_MIN, DTE_MAX,
    EARNINGS_BLOCK_DAYS,
    OTM_LONG_PCT, OTM_SHORT_PCT,
)
from .indicators import adx, mfi, rsi, macd, true_range, realized_vol, zscore
from .fundamentals import eps_surprise_trend, compute_quarterly_trends, cap_multiplier
from .simulations import mc_paths_prob_up, fit_hmm_regime
from .data_fetch import fetch_prices_batched
from .scoring import score_row
from .local_list_ops import prune_and_replenish_local_list
from .emailer import send_email_report_with_sims
from .options_metrics import option_liquidity_and_debit

# external utils (existing files)
from universe_utils import read_universe_blob
from local_list_utils import load_local_list, save_local_list
from ai_utils import ai_rank_tickers

# (optional ML; if you’ve added it)
try:
    from .model_predict import train_direction_model, predict_up_probability_for_latest
    _HAS_ML = True
except Exception:
    _HAS_ML = False

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
    for t in merged_tickers:
        try:
            fi = yf.Ticker(t).fast_info
            mc = fi.get("market_cap")
            if mc:
                fast_caps[t] = float(mc)
        except Exception:
            pass

    fundamentals_map = {}

    for t, df in frames.items():
        d = df.copy()
        d["CloseAdj"] = d["Adj Close"]

        # trend & flow
        d["adx14"] = adx(d, 14)
        d["mfi14"] = mfi(d, 14)

        # returns
        d["ret"]     = d["CloseAdj"].pct_change()
        d["ret_5d"]  = d["CloseAdj"].pct_change(5)
        d["ret_20"]  = d["CloseAdj"].pct_change(20)
        d["ret_21d"] = d["CloseAdj"].pct_change(21)
        d["ret_63"]  = d["CloseAdj"].pct_change(63)
        d["ret_252"] = d["CloseAdj"].pct_change(252)
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

        # EPS surprises
        eps_sig = eps_surprise_trend(t)

        # Monte Carlo (GBM) & HMM
        mu_d    = float(d["ret"].rolling(63).mean().iloc[-1])
        sigma_d = float(d["ret"].rolling(20).std().iloc[-1])
        mc_p30  = mc_paths_prob_up(float(d["CloseAdj"].iloc[-1]), mu_d, sigma_d, 30, 5000, 0.0)
        mc_p40  = mc_paths_prob_up(float(d["CloseAdj"].iloc[-1]), mu_d, sigma_d, 40, 5000, 0.0)
        state_today, prob_bull = fit_hmm_regime(d["ret"])

        # fundamentals (cached)
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

        # cap bonus
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

    if not rows:
        raise RuntimeError("No rows produced—check data availability or ticker list.")

    out = pd.DataFrame(rows)
    out = out[out["last_price"] >= PENNY_PRICE].copy()
    if out.empty:
        raise RuntimeError("All tickers filtered out by penny-stock exclusion.")

    # Composite trend score (your existing)
    out["adv_usd_20_z"] = zscore(out.get("adv_usd_20", pd.Series(dtype=float))).fillna(0.0)
    out["score"] = out.apply(lambda r: score_row(r, min_dollar_vol, "debit_call_spread"), axis=1)

    # Base trend buy flag
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

    # Strength/ranks
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

    # LEAPS score (unchanged)
    out["z_ret_63"]  = zscore(out.get("ret_63", pd.Series(dtype=float))).fillna(0.0)
    out["z_ret_252"] = zscore(out.get("ret_252", pd.Series(dtype=float))).fillna(0.0)

    rev_growth = np.where(out["fundamentals_quality"] >= 1.0, out["rev_q_yoy"], out["rev_q_qoq"])
    ern_growth = np.where(out["fundamentals_quality"] >= 1.0, out["earn_q_yoy"], out["earn_q_qoq"])
    rev_growth = pd.Series(rev_growth, index=out.index).clip(-1.0, 1.0).fillna(0.0)
    ern_growth = pd.Series(ern_growth, index=out.index).clip(-1.0, 1.0).fillna(0.0)
    streak     = out.get("growth_streak", pd.Series(0.0, index=out.index)).fillna(0.0)
    eps_avg    = out["eps_surprise_avg"].astype(float).fillna(0.0).clip(-0.20, 0.20)
    eps_beat   = out["eps_beat_share"].astype(float).fillna(0.0)

    out["leap_score"] = (
        0.30 * out["z_ret_63"] +
        0.35 * out["z_ret_252"] +
        0.10 * out["cap_bonus"] -
        0.15 * out.get("vol60", pd.Series(0.0, index=out.index)).fillna(0.0) +
        0.10 * rev_growth + 0.10 * ern_growth +
        0.05 * streak + 0.06 * eps_avg + 0.04 * eps_beat
    )
    out["leap_rank"] = _pctl0_10(out["leap_score"])

    # ---------- OPTIONS GATES: debit call spread metrics ----------
    opt_cols = [
        "opt_expiry", "opt_dte", "opt_long_k", "opt_short_k", "opt_mid_debit",
        "opt_leg1_spread_pct", "opt_leg2_spread_pct", "opt_combo_spread_pct",
        "opt_oi_long", "opt_oi_short", "opt_ivp_proxy", "opt_days_to_earnings",
    ]
    for c in opt_cols:
        out[c] = np.nan

    for i, r in out.iterrows():
        t = str(r["ticker"])
        try:
            res = option_liquidity_and_debit(
                tkr=t,
                min_dte=DTE_MIN, max_dte=DTE_MAX,
                pct_otm_long=OTM_LONG_PCT, pct_otm_short=OTM_SHORT_PCT,
                today=today,
            )
            if res.get("ok"):
                out.at[i, "opt_expiry"] = res.get("expiry")
                out.at[i, "opt_dte"] = res.get("dte")
                out.at[i, "opt_long_k"] = res.get("long_k")
                out.at[i, "opt_short_k"] = res.get("short_k")
                out.at[i, "opt_mid_debit"] = res.get("mid_debit")
                out.at[i, "opt_leg1_spread_pct"] = res.get("leg1_spread_pct")
                out.at[i, "opt_leg2_spread_pct"] = res.get("leg2_spread_pct")
                out.at[i, "opt_combo_spread_pct"] = res.get("combo_spread_pct")
                out.at[i, "opt_oi_long"] = res.get("oi_long")
                out.at[i, "opt_oi_short"] = res.get("oi_short")
                out.at[i, "opt_ivp_proxy"] = res.get("ivp_proxy")
                out.at[i, "opt_days_to_earnings"] = res.get("days_to_earnings")
        except Exception as e:
            logger.debug(f"[options] {t} metrics failed: {e}")

    # Hard gates for debit call spreads
    opt_ok = (
        (pd.to_numeric(out["opt_oi_long"], errors="coerce").fillna(0) >= OPT_MIN_OI) &
        (pd.to_numeric(out["opt_oi_short"], errors="coerce").fillna(0) >= OPT_MIN_OI) &
        (pd.to_numeric(out["opt_combo_spread_pct"], errors="coerce") <= OPT_MAX_SPREAD_PCT) &
        (pd.to_numeric(out["opt_ivp_proxy"], errors="coerce").between(IVP_MIN, IVP_MAX, inclusive="both")) &
        (pd.to_numeric(out["opt_dte"], errors="coerce").between(DTE_MIN, DTE_MAX, inclusive="both")) &
        (
            pd.to_numeric(out["opt_days_to_earnings"], errors="coerce").isna() |
            (pd.to_numeric(out["opt_days_to_earnings"], errors="coerce") > EARNINGS_BLOCK_DAYS)
        )
    )

    # Optional directional confirms (already in base_buy if enabled)
    spread_base = out["buy_flag"].astype(bool)
    out["buy_flag_spread"] = (spread_base & opt_ok)

    # Spread score: boost trend score with direction + options quality
    dir_boost = 0.5 * np.clip(out["mc_p_up_30d"].fillna(0.5) * 2 - 1, -1, 1) \
              + 0.3 * np.clip(out.get("ml_prob_up_30d", pd.Series(0.5, index=out.index)) * 2 - 1, -1, 1)
    qual_boost = 0.2 * opt_ok.astype(float)
    out["spread_score"] = out["score"] + dir_boost + qual_boost

    # Leaders & leaps tables
    leaders = out[(out.get("ret_5d", 0) > 0) & (out.get("ret_21d", 0) > 0)].copy().sort_values("strength_score", ascending=False)
    leaps   = out.sort_values("leap_rank", ascending=False)

    # AI ranking for email lists (unchanged)
    price_map = dict(zip(out["ticker"].astype(str).str.upper(), out["last_price"].astype(float)))
    combined = [t for t in merged_tickers if price_map.get(t.upper(), float("inf")) >= PENNY_PRICE]
    ai_leaps_df   = ai_rank_tickers(combined, strategy="leaps",             horizon_text="12–24 months", top_k=AI_EMAIL_TOPK)
    ai_spreads_df = ai_rank_tickers(combined, strategy="debit_call_spread", horizon_text="30–40 days",   top_k=AI_EMAIL_TOPK)

    # Prune & persist local list
    try:
        new_local_list, changes = prune_and_replenish_local_list(
            df_all=out,
            local_list=list(local_list),
            universe_list=universe_tickers,
            prune_count=LOCAL_PRUNE_COUNT,
            min_price=LOCAL_ADD_MIN_PRICE,
            min_strength_z=LOCAL_ADD_MIN_STRENGTH_Z,
            max_size=LOCAL_MAX_SIZE,
        )
        save_local_list(new_local_list, meta={"updated_utc": datetime.datetime.utcnow().isoformat()+"Z"})
        logger.info(f"[local_list] removed={len(changes.get('removed',[]))} added={len(changes.get('added',[]))} size={len(new_local_list)}")
    except Exception as e:
        logger.warning(f"[local_list] update/save failed: {e}")

    # ------- Email (use spread-focused picks) -------
    # Use spread signal: top spread names (strict) + a few leaders
    picks = out[out["buy_flag_spread"]].copy().sort_values("spread_score", ascending=False)
    leaders_top = leaders.head(ADD_LEADERS_TOPK)
    picks_tickers = list(dict.fromkeys([*picks["ticker"].astype(str).tolist(),
                                        *leaders_top["ticker"].astype(str).tolist()]))

    def _tickers_only(df):
        if df is None or df.empty:
            return []
        d = df.copy()
        if "ai_score" in d.columns:
            d = d.sort_values("ai_score", ascending=False)
        return d["ticker"].astype(str).tolist()

    ai_spreads_list = _tickers_only(ai_spreads_df)[:AI_EMAIL_TOPK]
    ai_leaps_list   = _tickers_only(ai_leaps_df)[:AI_EMAIL_TOPK]

    # Sim table (same format your emailer expects)
    sim_df = out[out["ticker"].isin(picks_tickers)][
        ["ticker", "mc_p_up_30d", "hmm_prob_bull"]
    ].copy()
    sim_df["ml_prob"] = 0.5  # default
    if "ml_prob_up_30d" in out.columns:
        sim_df["ml_prob"] = out.set_index("ticker").loc[sim_df["ticker"], "ml_prob_up_30d"].values

    sim_df = sim_df.sort_values(["mc_p_up_30d", "hmm_prob_bull", "ml_prob"], ascending=False)
    sim_rows = [
        {"ticker": str(r["ticker"]),
         "mc30": float(r["mc_p_up_30d"]) if pd.notna(r["mc_p_up_30d"]) else np.nan,
         "hmm_bull": float(r["hmm_prob_bull"]) if pd.notna(r["hmm_prob_bull"]) else np.nan,
         "ml_prob": float(r["ml_prob"]) if pd.notna(r["ml_prob"]) else np.nan}
        for _, r in sim_df.iterrows()
    ]

    stamp = today.strftime("%Y-%m-%d")
    send_email_report_with_sims(
        stamp=stamp,
        picks_tickers=picks_tickers,
        ai_spreads_list=ai_spreads_list,
        ai_leaps_list=ai_leaps_list,
        sim_rows=sim_rows,
        subj_prefix=os.getenv("EMAIL_SUBJECT_PREFIX", "Daily Stock Picks"),
    )

    # return tables
    cols_order = [
        "ticker", "final_rank", "final_60_40", "cap_mult",
        "norm_score_0_10", "norm_strength_0_10",
        "score", "strength_score", "ret_5d", "ret_21d",
        "last_price", "market_cap",
        "adv_usd_20", "adv_usd_20_z", "vol_surge",
        "rsi14", "close_above_sma50", "close_above_sma200", "dist_52w_high",
        "buy_flag", "buy_flag_spread", "spread_score",
        "rev_q_yoy", "earn_q_yoy", "rev_q_qoq", "earn_q_qoq", "growth_streak", "fundamentals_quality",
        "z_ret_63", "z_ret_252", "cap_bonus", "leap_score", "leap_rank",
        "adx14", "mfi14", "eps_surprise_avg", "eps_beat_share",
        "mc_p_up_30d", "mc_p_up_40d", "hmm_state", "hmm_prob_bull",
        # options metrics
        "opt_expiry", "opt_dte", "opt_long_k", "opt_short_k", "opt_mid_debit",
        "opt_leg1_spread_pct", "opt_leg2_spread_pct", "opt_combo_spread_pct",
        "opt_oi_long", "opt_oi_short", "opt_ivp_proxy", "opt_days_to_earnings",
    ]
    for c in cols_order:
        if c not in out.columns:
            out[c] = np.nan
    df_all_sorted = _shrink_df(out[cols_order].sort_values("spread_score", ascending=False))
    leaders = _shrink_df(leaders[["ticker","ret_5d","ret_21d","strength_score"]])
    return df_all_sorted, leaders