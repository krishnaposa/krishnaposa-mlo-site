# monitoring/model_predict.py
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd

# Reuse your indicator helpers so we don't duplicate logic
from .indicators import rsi, adx, mfi, macd, true_range, realized_vol, zscore

# ============== Tiny helpers ==============

def _safe_pct_change(s: pd.Series, n: int) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = s.pct_change(n)
    return out.replace([np.inf, -np.inf], np.nan)

def _clip01(x: np.ndarray) -> np.ndarray:
    return np.minimum(0.999, np.maximum(0.001, x))

# ============== Feature engineering ==============

FEATURES: List[str] = [
    # trend & momentum
    "ret_5d", "ret_21d", "ret_63", "ret_252",
    "ret_20_z", "ret_60_z", "ret_120_z",
    # oscillators / signals
    "rsi14", "adx14", "mfi14", "macd_hist",
    # moving average structure
    "sma50_slope", "sma200_slope", "close_above_sma50", "close_above_sma200",
    # breakouts / proximity to highs
    "dist_52w_high", "new_55d_high",
    # liquidity / volatility
    "vol20", "vol60", "vol_surge",
]

def _features_from_history(df: pd.DataFrame) -> pd.DataFrame:
    """Compute daily feature matrix from a single ticker's OHLCV history."""
    d = df.copy()
    d["CloseAdj"] = d["Adj Close"]

    # returns
    d["ret"]     = d["CloseAdj"].pct_change()
    d["ret_5d"]  = _safe_pct_change(d["CloseAdj"], 5)
    d["ret_21d"] = _safe_pct_change(d["CloseAdj"], 21)
    d["ret_63"]  = _safe_pct_change(d["CloseAdj"], 63)
    d["ret_252"] = _safe_pct_change(d["CloseAdj"], 252)
    d["ret_20"]  = _safe_pct_change(d["CloseAdj"], 20)
    d["ret_60"]  = _safe_pct_change(d["CloseAdj"], 60)
    d["ret_120"] = _safe_pct_change(d["CloseAdj"], 120)

    # momentum z
    for col in ["ret_20", "ret_60", "ret_120"]:
        mu = d[col].rolling(180).mean()
        sd = d[col].rolling(180).std()
        d[f"{col}_z"] = (d[col] - mu) / sd.replace(0, np.nan)

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

    # liquidity / volume
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

    return d

def build_dataset(frames: Dict[str, pd.DataFrame], horizon_days: int = 30
                  ) -> Tuple[pd.DataFrame, pd.Series, pd.Index]:
    """
    Turn per-ticker OHLCV frames into a panel of features X and binary labels y.
    y = 1 if price in +horizon_days is above today.
    Returns X, y, index for (ticker, date).
    """
    rows: List[pd.DataFrame] = []
    keys: List[pd.Index] = []
    for tkr, df in frames.items():
        d = _features_from_history(df)
        # Label: forward return sign (finish higher than 0)
        fwd = d["CloseAdj"].shift(-horizon_days) / d["CloseAdj"] - 1.0
        d["y_up"] = (fwd > 0).astype(float)

        # keep only the rows where we have all features
        cols = FEATURES + ["y_up"]
        dd = d[cols].dropna().copy()
        if dd.empty:
            continue
        dd["ticker"] = tkr
        rows.append(dd)
        keys.append(dd.index)

    if not rows:
        raise RuntimeError("No rows for training dataset — not enough history or bad frames.")

    panel = pd.concat(rows, axis=0)
    index = panel.index
    y = panel["y_up"].astype(int)
    X = panel[FEATURES].astype(float)

    # Standardize a few heavy-tailed features (safe scaling)
    X = X.replace([np.inf, -np.inf], np.nan).fillna(X.median())
    return X, y, index

# ============== Model(s) ==============

@dataclass
class Direction30DModel:
    """A thin wrapper that prefers sklearn, but falls back to a hand-rolled logistic."""
    model_name: str
    scaler_mean_: Optional[np.ndarray]
    scaler_std_: Optional[np.ndarray]
    coef_: Optional[np.ndarray]
    intercept_: float
    clf_: Optional[object] = None  # sklearn estimator if available

    @staticmethod
    def _fit_fallback_logit(X: np.ndarray, y: np.ndarray, max_iter: int = 200) -> Tuple[np.ndarray, float]:
        """
        Simple logistic regression via gradient ascent (no L2), used only if sklearn isn't available.
        """
        n, k = X.shape
        w = np.zeros(k, dtype=float)
        b = 0.0
        lr = 0.1
        for _ in range(max_iter):
            z = X @ w + b
            p = 1 / (1 + np.exp(-z))
            g_w = X.T @ (y - p) / n
            g_b = np.mean(y - p)
            w += lr * g_w
            b += lr * g_b
        return w, b

    @classmethod
    def fit(cls, X_df: pd.DataFrame, y: pd.Series) -> "Direction30DModel":
        X = X_df.values.astype(float)
        yv = y.values.astype(int)

        # Standardize (z-score) for stability
        mu = X.mean(axis=0)
        sd = X.std(axis=0)
        sd[sd == 0] = 1.0
        Xz = (X - mu) / sd

        # Try sklearn first
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.ensemble import GradientBoostingClassifier
            from sklearn.model_selection import train_test_split
            from sklearn.metrics import roc_auc_score

            # quick split for model selection
            Xtr, Xva, ytr, yva = train_test_split(Xz, yv, test_size=0.25, random_state=7, stratify=yv)

            # 1) Gradient Boosting (captures nonlinearity)
            gb = GradientBoostingClassifier(random_state=7)
            gb.fit(Xtr, ytr)
            p_gb = gb.predict_proba(Xva)[:, 1]
            auc_gb = roc_auc_score(yva, p_gb) if len(np.unique(yva)) > 1 else 0.5

            # 2) Logistic (interpretable)
            lr = LogisticRegression(max_iter=200)
            lr.fit(Xtr, ytr)
            p_lr = lr.predict_proba(Xva)[:, 1]
            auc_lr = roc_auc_score(yva, p_lr) if len(np.unique(yva)) > 1 else 0.5

            # pick the better validation AUC
            if auc_gb >= auc_lr:
                chosen = gb
                name = f"GradientBoosting(AUC={auc_gb:.3f})"
                coef = None
                intercept = 0.0
            else:
                chosen = lr
                name = f"Logistic(AUC={auc_lr:.3f})"
                coef = getattr(lr, "coef_", np.zeros((1, X.shape[1])))[0]
                intercept = float(getattr(lr, "intercept_", [0.0])[0])

            return cls(
                model_name=name,
                scaler_mean_=mu,
                scaler_std_=sd,
                coef_=coef,
                intercept_=intercept,
                clf_=chosen
            )

        except Exception:
            # Fallback: home-grown logistic
            w, b = cls._fit_fallback_logit(Xz, yv, max_iter=250)
            return cls(
                model_name="FallbackLogit",
                scaler_mean_=mu, scaler_std_=sd,
                coef_=w, intercept_=float(b),
                clf_=None
            )

    def predict_proba(self, X_df: pd.DataFrame) -> np.ndarray:
        X = X_df.values.astype(float)
        mu = self.scaler_mean_
        sd = self.scaler_std_
        Xz = (X - mu) / sd

        if self.clf_ is not None:
            try:
                p = self.clf_.predict_proba(Xz)[:, 1]
                return _clip01(p)
            except Exception:
                pass

        # fallback path
        w = self.coef_
        b = self.intercept_
        z = Xz @ w + b
        p = 1 / (1 + np.exp(-z))
        return _clip01(p)

# ============== Top-level helpers you can call from monitor.py ==============

def train_direction_model(frames: Dict[str, pd.DataFrame], horizon_days: int = 30
                          ) -> Tuple[Direction30DModel, pd.DataFrame, pd.Series]:
    """
    Build X, y from frames and fit the 30D direction model.
    Returns (model, X, y) for optional diagnostics.
    """
    X, y, _ = build_dataset(frames, horizon_days=horizon_days)
    model = Direction30DModel.fit(X, y)
    return model, X, y

def predict_up_probability_for_latest(
    frames: Dict[str, pd.DataFrame],
    model: Direction30DModel
) -> Dict[str, float]:
    """
    For each ticker, compute features for the **latest row only** and score with the trained model.
    Returns {ticker: prob_up_30d}.
    """
    out: Dict[str, float] = {}
    for tkr, df in frames.items():
        d = _features_from_history(df).dropna(subset=FEATURES)
        if d.empty:
            out[tkr] = float("nan")
            continue
        x_last = d[FEATURES].iloc[[-1]]
        p = float(model.predict_proba(x_last)[0])
        out[tkr] = p
    return out