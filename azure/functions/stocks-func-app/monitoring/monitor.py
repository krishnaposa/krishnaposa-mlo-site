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
    ADD_LEADERS_TOPK,
    USE_MC_HMM_FILTER, MC_MIN_PUP, HMM_MIN_BULL,
    WHEEL_ENABLED, WHEEL_DEBUG, WHEEL_INCLUDE_FINVIZ, WHEEL_FINVIZ_TOPN,
    WHEEL_TOPK, WHEEL_PREFILTER_TOPN, WHEEL_MIN_DTE, WHEEL_MAX_DTE,
    WHEEL_PUT_OTM_PCT, WHEEL_MIN_MARKET_CAP, WHEEL_MIN_PRICE, WHEEL_MAX_RSI,
    WHEEL_MIN_REL_VOLUME, WHEEL_MAX_DIST_52W_HIGH, WHEEL_MAX_DEBT_TO_EQUITY,
    WHEEL_MIN_INSIDER_OWNERSHIP, WHEEL_MIN_GROWTH, WHEEL_MIN_OI,
    WHEEL_MAX_SPREAD_PCT, WHEEL_BLOCK_EARNINGS, EARNINGS_BLOCK_DAYS,
)
from .indicators import adx, mfi, rsi, macd, true_range, realized_vol, zscore
from .fundamentals import eps_surprise_trend, compute_quarterly_trends, compute_company_profile, cap_multiplier
from .simulations import mc_paths_prob_up, fit_hmm_regime
from .data_fetch import fetch_prices_batched
from .options_metrics import cash_secured_put_candidate
from .scoring import score_row, score_wheel_put_row
from .local_list_ops import prune_and_replenish_local_list
from .emailer import send_email_report_with_sims  # emailer that shows sims + options + performance table

# external utils
from universe_utils import read_universe_blob
from local_list_utils import load_local_list, save_local_list
# from ai_utils import ai_rank_tickers  # Disabled: LEAPS/debit-spread AI rankings are not currently needed.
from wb4u_main import get_large_strongbuy_alltime_high_symbols, get_wheel_finviz_symbols

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
    alltime_high_value_list = []
    wheel_finviz_list = []
    if WHEEL_ENABLED and WHEEL_INCLUDE_FINVIZ:
        try:
            alltime_high_value_list = get_large_strongbuy_alltime_high_symbols(max_count=WHEEL_FINVIZ_TOPN)
        except Exception as e:
            logger.warning(f"[finviz] all-time-high wheel source failed: {e}")
        try:
            wheel_finviz_list = get_wheel_finviz_symbols(max_count=WHEEL_FINVIZ_TOPN)
        except Exception as e:
            logger.warning(f"[finviz] wheel source failed: {e}")
        if WHEEL_DEBUG:
            logger.info(
                "[wheel] Finviz sources: "
                f"all_time_high={len(alltime_high_value_list)}, wheel_query={len(wheel_finviz_list)}"
            )

    merged_tickers = sorted(set(local_list) | set(universe_tickers) | set(alltime_high_value_list) | set(wheel_finviz_list))
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
    company_profile_map = {}

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
        d["ret_60"]  = d["CloseAdj"].pct_change(60)
        d["ret_63"]  = d["CloseAdj"].pct_change(63)
        d["ret_120"] = d["CloseAdj"].pct_change(120)
        d["ret_252"] = d["CloseAdj"].pct_change(252)

        # MAs & states
        d["sma20"]   = d["CloseAdj"].rolling(20).mean()
        d["sma50"]   = d["CloseAdj"].rolling(50).mean()
        d["sma200"]  = d["CloseAdj"].rolling(200).mean()
        d["sma50_slope"]  = (d["sma50"].diff(5) / d["sma50"].shift(5)).replace([np.inf, -np.inf], np.nan)
        d["sma200_slope"] = (d["sma200"].diff(10) / d["sma200"].shift(10)).replace([np.inf, -np.inf], np.nan)
        d["close_above_sma20"]  = (d["CloseAdj"] > d["sma20"]).astype(float)
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
        d["rel_volume_20"] = d["Volume"].astype(float) / d["Volume"].astype(float).rolling(20).mean()

        # highs / breakouts
        d["hi_252"] = d["CloseAdj"].rolling(252, min_periods=60).max()
        d["dist_52w_high"] = d["CloseAdj"] / d["hi_252"] - 1.0

        # momentum z-scores
        for col in ["ret_20", "ret_60", "ret_120"]:
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
        if t not in company_profile_map:
            company_profile_map[t] = compute_company_profile(t)

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
        latest.update(company_profile_map[t])

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
        model_tuple = train_direction_model(enriched_frames, horizon_days=30)
        ml_prob_map = predict_up_probability_for_latest(enriched_frames, model_tuple)
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
    out["rev_growth"] = out.get("revenue_growth", pd.Series(np.nan, index=out.index)).fillna(rev_growth)
    out["earn_growth"] = out.get("earnings_growth", pd.Series(np.nan, index=out.index)).fillna(ern_growth)

    out["leap_score"] = (
        0.30 * out["z_ret_63"] +
        0.35 * out["z_ret_252"] +
        0.10 * out["cap_bonus"] -
        0.15 * out.get("vol60", pd.Series(0.0)).fillna(0.0) +
        0.10 * rev_growth + 0.10 * ern_growth
    )
    out["leap_rank"] = _pctl0_10(out["leap_score"])

    out["ml_prob_up_30d"] = out["ticker"].map(ml_prob_map).astype(float).fillna(0.5)

    wheel_rows = []
    if WHEEL_ENABLED:
        def _wheel_log(step: str, mask: pd.Series, prev_count: int | None = None) -> int:
            count = int(mask.sum())
            if WHEEL_DEBUG:
                removed = "" if prev_count is None else f", removed {prev_count - count}"
                logger.info(f"[wheel] {step}: {count} candidates{removed}")
            return count

        base_mask = pd.Series(True, index=out.index)
        prev = _wheel_log("start", base_mask)

        price_mask = base_mask & (out["last_price"].fillna(0.0) > WHEEL_MIN_PRICE)
        prev = _wheel_log(f"price > {WHEEL_MIN_PRICE:g}", price_mask, prev)

        cap_mask = price_mask & (out["market_cap"].fillna(0.0) >= WHEEL_MIN_MARKET_CAP)
        prev = _wheel_log(f"market cap >= {WHEEL_MIN_MARKET_CAP:,.0f}", cap_mask, prev)

        rsi_mask = cap_mask & (out["rsi14"].fillna(100.0) < WHEEL_MAX_RSI)
        prev = _wheel_log(f"RSI < {WHEEL_MAX_RSI:g}", rsi_mask, prev)

        sma20_mask = rsi_mask & (out["close_above_sma20"].fillna(0.0) == 1.0)
        prev = _wheel_log("above SMA20", sma20_mask, prev)

        sma50_mask = sma20_mask & (out["close_above_sma50"].fillna(0.0) == 1.0)
        prev = _wheel_log("above SMA50", sma50_mask, prev)

        high_mask = sma50_mask & (out["dist_52w_high"].fillna(-1.0) >= -WHEEL_MAX_DIST_52W_HIGH)
        prev = _wheel_log(f"within {WHEEL_MAX_DIST_52W_HIGH:.0%} of 52w high", high_mask, prev)

        relvol_mask = high_mask & (out["rel_volume_20"].fillna(0.0) >= WHEEL_MIN_REL_VOLUME)
        prev = _wheel_log(f"relative volume >= {WHEEL_MIN_REL_VOLUME:g}", relvol_mask, prev)

        debt_mask = relvol_mask & (out["debt_to_equity"].fillna(np.inf) < WHEEL_MAX_DEBT_TO_EQUITY)
        prev = _wheel_log(f"debt/equity < {WHEEL_MAX_DEBT_TO_EQUITY:g}", debt_mask, prev)

        insider_mask = debt_mask & (out["insider_ownership"].fillna(0.0) >= WHEEL_MIN_INSIDER_OWNERSHIP)
        prev = _wheel_log(f"insider ownership >= {WHEEL_MIN_INSIDER_OWNERSHIP:.0%}", insider_mask, prev)

        growth_ok = (
            (out["rev_growth"].fillna(0.0) >= WHEEL_MIN_GROWTH) |
            (out["earn_growth"].fillna(0.0) >= WHEEL_MIN_GROWTH) |
            (out["growth_streak"].fillna(0.0) == 1.0)
        )
        final_mask = insider_mask & growth_ok
        prev = _wheel_log(f"growth >= {WHEEL_MIN_GROWTH:.0%} or growth streak", final_mask, prev)

        if WHEEL_DEBUG:
            logger.info(
                "[wheel] missing fundamentals in filtered universe: "
                f"debt_to_equity={int(out.loc[relvol_mask, 'debt_to_equity'].isna().sum())}, "
                f"insider_ownership={int(out.loc[debt_mask, 'insider_ownership'].isna().sum())}"
            )

        wheel_base = out[final_mask].copy()
        wheel_base = wheel_base.sort_values("final_rank", ascending=False).head(WHEEL_PREFILTER_TOPN)
        if WHEEL_DEBUG:
            logger.info(f"[wheel] option-chain prefilter topN: {len(wheel_base)} candidates")

        reject_counts: dict[str, int] = {}
        for _, r in wheel_base.iterrows():
            t = str(r["ticker"]).upper()
            try:
                opt = cash_secured_put_candidate(
                    t,
                    min_dte=WHEEL_MIN_DTE,
                    max_dte=WHEEL_MAX_DTE,
                    pct_otm=WHEEL_PUT_OTM_PCT,
                    today=today,
                )
                if not opt.get("ok"):
                    reason = str(opt.get("reason", "option_chain_rejected"))
                    reject_counts[reason] = reject_counts.get(reason, 0) + 1
                    continue
                open_interest = float(opt.get("open_interest", 0.0) or 0.0)
                spread_pct = float(opt.get("spread_pct", np.nan))
                if open_interest < WHEEL_MIN_OI:
                    reject_counts["open_interest_too_low"] = reject_counts.get("open_interest_too_low", 0) + 1
                    continue
                if not np.isfinite(spread_pct) or spread_pct > WHEEL_MAX_SPREAD_PCT:
                    reject_counts["spread_too_wide"] = reject_counts.get("spread_too_wide", 0) + 1
                    continue
                dte_earn = opt.get("days_to_earnings")
                if WHEEL_BLOCK_EARNINGS and dte_earn is not None and 0 <= int(dte_earn) <= EARNINGS_BLOCK_DAYS:
                    reject_counts["earnings_blocked"] = reject_counts.get("earnings_blocked", 0) + 1
                    continue
                score = score_wheel_put_row(r, opt)
                wheel_rows.append({
                    "ticker": t,
                    "score": score,
                    "expiry": opt.get("expiry"),
                    "dte": opt.get("dte"),
                    "spot": opt.get("spot"),
                    "strike": opt.get("strike"),
                    "credit": opt.get("mid_credit"),
                    "roc": opt.get("return_on_cash"),
                    "ann_return": opt.get("annualized_return"),
                    "breakeven": opt.get("break_even"),
                    "buffer": opt.get("downside_buffer"),
                    "oi": opt.get("open_interest"),
                    "volume": opt.get("volume"),
                    "iv": opt.get("implied_volatility"),
                    "spread": opt.get("spread_pct"),
                    "earnings_days": dte_earn,
                    "rsi": r.get("rsi14"),
                    "rel_volume": r.get("rel_volume_20"),
                    "debt_to_equity": r.get("debt_to_equity"),
                    "insider_ownership": r.get("insider_ownership"),
                    "rev_growth": r.get("rev_growth"),
                    "earn_growth": r.get("earn_growth"),
                })
            except Exception as e:
                reject_counts["exception"] = reject_counts.get("exception", 0) + 1
                logger.debug(f"[wheel] skipped {t}: {e}")
        wheel_rows = sorted(wheel_rows, key=lambda x: x.get("score", 0.0), reverse=True)[:WHEEL_TOPK]
        if WHEEL_DEBUG:
            logger.info(f"[wheel] accepted option candidates: {len(wheel_rows)}")
            if reject_counts:
                logger.info(f"[wheel] option reject counts: {reject_counts}")
            if wheel_rows:
                logger.info("[wheel] selected: " + ", ".join([str(r.get("ticker")) for r in wheel_rows]))

    # leaders
    leaders = out[(out.get("ret_5d", 0) > 0) & (out.get("ret_21d", 0) > 0)].copy().sort_values("strength_score", ascending=False)

    # Disabled for now: LEAPS/debit-spread AI rankings are not needed in the daily email.
    # ai_leaps_df = ai_rank_tickers(merged_tickers, strategy="leaps", horizon_text="12–24 months", top_k=AI_EMAIL_TOPK)
    # ai_spreads_df = ai_rank_tickers(merged_tickers, strategy="debit_call_spread", horizon_text="30–40 days", top_k=AI_EMAIL_TOPK)

    # ------- Email data -------
    picks = out[out["buy_flag"]].copy()
    leaders_top = leaders.head(ADD_LEADERS_TOPK)
    picks_tickers = list(dict.fromkeys(
        [*picks["ticker"].astype(str).tolist(), *leaders_top["ticker"].astype(str).tolist()]
    ))

    # Disabled for now with LEAPS/debit-spread AI rankings.
    # def _tickers_only(df):
    #     if df is None or df.empty:
    #         return []
    #     d = df.copy()
    #     if "ai_score" in d.columns:
    #         d = d.sort_values("ai_score", ascending=False)
    #     return d["ticker"].astype(str).tolist()

    ai_spreads_list = []
    ai_leaps_list = []

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
        universe_tickers=universe_tickers,
        picks_tickers=picks_tickers,
        ai_spreads_list=ai_spreads_list,
        ai_leaps_list=ai_leaps_list,
        alltime_high_value_list=alltime_high_value_list,
        sim_rows=sim_rows,
        opt_rows=[],       # placeholder — still valid
        wheel_rows=wheel_rows,
        perf_rows=perf_rows,  # new table
        subj_prefix=os.getenv("EMAIL_SUBJECT_PREFIX", "Daily Stock Picks"),
    )

    df_all_sorted = _shrink_df(out.sort_values("final_rank", ascending=False))
    leaders = _shrink_df(leaders[["ticker", "ret_5d", "ret_21d", "strength_score"]])
    return df_all_sorted, leaders