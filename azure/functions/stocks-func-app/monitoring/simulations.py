# simulations.py

import numpy as np
import pandas as pd
import logging

# ----------------------------- Monte Carlo -----------------------------

def _neutral_prob(value: float = 0.50) -> float:
    return float(value)


def mc_paths_prob_up(
    last_price: float,
    mu_d: float,
    sigma_d: float,
    horizon_days: int = 30,
    n_paths: int = 5000,
    up_threshold: float = 0.0,
    seed: int | None = 42
) -> float:
    """
    Geometric Brownian Motion one-step Monte Carlo.
    Returns the probability that S_T / S_0 - 1 >= up_threshold after `horizon_days`.

    Args:
        last_price: current price (S0)
        mu_d: daily drift (mean daily return)
        sigma_d: daily volatility (std of daily returns)
        horizon_days: forecast horizon in trading days
        n_paths: number of simulated paths
        up_threshold: required return threshold (e.g., 0.0 for "finish up")
        seed: RNG seed for reproducibility (None -> non-deterministic)

    Returns:
        float in [0,1], or np.nan if inputs are invalid.
    """
    if not np.isfinite(last_price) or last_price <= 0:
        return np.nan
    if not np.isfinite(mu_d) or not np.isfinite(sigma_d) or sigma_d < 0:
        return np.nan
    if horizon_days <= 0 or n_paths <= 0:
        return np.nan
    if sigma_d < 1e-10:
        deterministic_ret = np.expm1(float(mu_d) * int(horizon_days))
        return float(deterministic_ret >= up_threshold)

    rng = np.random.default_rng(seed)
    mu_T = float(mu_d) * int(horizon_days)
    sigma_T = float(sigma_d) * np.sqrt(int(horizon_days))
    z = rng.standard_normal(n_paths)
    # GBM closed form
    ST = last_price * np.exp((mu_T - 0.5 * sigma_T**2) + sigma_T * z)
    ret = ST / last_price - 1.0
    return float(np.mean(ret >= up_threshold))


# ------------------------------ HMM -----------------------------------

try:
    from hmmlearn.hmm import GaussianHMM
    _HMM_AVAILABLE = True
except Exception:
    _HMM_AVAILABLE = False
    logging.getLogger(__name__).warning("[HMM] hmmlearn not available; using neutral fallback")


def fit_hmm_regime(
    daily_ret: pd.Series,
    n_states: int = 2,
    min_len: int = 150,
    clip_abs: float = 0.15,
    random_state: int = 42
):
    """
    Fit a Gaussian HMM on daily returns to estimate 'bull' probability today.

    Returns:
        (state_today, prob_bull_today)

        - state_today: int in [0..n_states-1], or -1 if model unavailable/failed.
        - prob_bull_today: float in [0,1]; if model can't be fit, returns 0.50
          (neutral) instead of NaN so downstream filters don't break.

    Notes on robustness vs your previous version:
        • Cleans and clips inputs (drops non-finite, caps outliers).
        • Requires at least `min_len` data points (default 150).
        • Labels the *higher-mean* state as 'bull' (more reliable than min-cov).
        • Uses diag covariance + tol for stable convergence.
        • On any failure or missing hmmlearn, returns (-1, 0.50).
    """
    logger = logging.getLogger(__name__)

    # Library check
    if not _HMM_AVAILABLE:
        return -1, _neutral_prob()

    try:
        if int(n_states) < 2:
            return -1, _neutral_prob()

        # Convert & clean
        r = pd.Series(daily_ret, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
        if r.empty:
            return -1, _neutral_prob()

        # Clip extreme daily moves to improve numerical stability
        if np.isfinite(clip_abs) and clip_abs > 0:
            r = r.clip(lower=-clip_abs, upper=clip_abs)

        if r.shape[0] < int(min_len):
            # Not enough history → neutral
            return -1, _neutral_prob()

        if float(r.std(ddof=0)) < 1e-10:
            return -1, _neutral_prob()

        X = r.values.reshape(-1, 1)

        # Fit HMM
        model = GaussianHMM(
            n_components=int(n_states),
            covariance_type="diag",
            n_iter=200,
            tol=1e-4,
            random_state=int(random_state)
        )
        model.fit(X)

        # Identify which state is "bull" = higher mean
        means = model.means_.ravel()
        bull_state = int(np.argmax(means))

        # Posterior probabilities for the last observation
        post = model.predict_proba(X)
        prob_bull_today = float(post[-1, bull_state])
        state_today = int(np.argmax(post[-1]))
        return state_today, prob_bull_today

    except Exception as e:
        logger.debug(f"[HMM] fit failed, using neutral fallback: {e}")
        return -1, _neutral_prob()