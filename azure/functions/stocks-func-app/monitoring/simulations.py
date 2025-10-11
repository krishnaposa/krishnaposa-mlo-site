import numpy as np
import pandas as pd

def mc_paths_prob_up(last_price: float, mu_d: float, sigma_d: float,
                     horizon_days: int = 30, n_paths: int = 5000,
                     up_threshold: float = 0.0, seed: int | None = 42) -> float:
    if not np.isfinite(last_price) or last_price <= 0 or sigma_d < 1e-8:
        return np.nan
    if seed is not None:
        np.random.seed(seed)
    mu_T = mu_d * horizon_days
    sigma_T = sigma_d * np.sqrt(horizon_days)
    z = np.random.randn(n_paths)
    ST = last_price * np.exp((mu_T - 0.5 * sigma_T**2) + sigma_T * z)
    ret = ST / last_price - 1.0
    return float(np.mean(ret >= up_threshold))

def fit_hmm_regime(daily_ret: pd.Series, n_states: int = 2):
    try:
        from hmmlearn.hmm import GaussianHMM
    except Exception:
        return np.nan, np.nan
    r = daily_ret.dropna().values.reshape(-1, 1)
    if r.shape[0] < 200:
        return np.nan, np.nan
    model = GaussianHMM(n_components=n_states, covariance_type="full", n_iter=200, random_state=7)
    model.fit(r)
    covs = model.covars_.reshape(-1)
    bull_state = int(np.argmin(covs))
    post = model.predict_proba(r)
    prob_bull = float(post[-1, bull_state])
    state_today = int(np.argmax(post[-1]))
    return state_today, prob_bull