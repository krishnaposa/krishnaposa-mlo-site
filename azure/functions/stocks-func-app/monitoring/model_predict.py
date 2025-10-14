# monitoring/model_predict.py

from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from .indicators import rsi, realized_vol  # reuse your existing helpers


# ----------------------------- feature utils -----------------------------

def _feat_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build a small, robust feature set from OHLCV only.
    Assumes df has at least: ['Adj Close','High','Low','Open','Volume'].
    All engineering happens here so the model never relies on external columns.
    """
    d = df.copy()
    d = d.dropna(subset=["Adj Close"]).copy()

    px = d["Adj Close"].astype(float)
    vol = d["Volume"].astype(float)

    d["ret1"]   = px.pct_change(1)
    d["ret5"]   = px.pct_change(5)
    d["ret20"]  = px.pct_change(20)
    d["ret60"]  = px.pct_change(60)

    d["sma20"]  = px.rolling(20).mean()
    d["sma50"]  = px.rolling(50).mean()
    d["sma200"] = px.rolling(200).mean()

    d["above50"]  = (px > d["sma50"]).astype(float)
    d["above200"] = (px > d["sma200"]).astype(float)

    d["rsi14"] = rsi(px, 14)
    d["rv20"]  = realized_vol(d["ret1"], 20)
    d["rv60"]  = realized_vol(d["ret1"], 60)

    # Simple liquidity proxy
    d["adv20"] = vol.rolling(20).mean() * px.rolling(20).mean()

    feats = [
        "ret1","ret5","ret20","ret60",
        "above50","above200","rsi14","rv20","rv60","adv20"
    ]
    return d[feats + ["Adj Close"]]


def _latest_features(df: pd.DataFrame) -> np.ndarray | None:
    f = _feat_frame(df).iloc[-1:].dropna(axis=1)
    # ensure consistent column order (match training’s selected cols)
    return f.values.astype(float) if len(f) == 1 and f.notna().all(axis=None) else None


def _train_matrix(frames: Dict[str, pd.DataFrame], horizon_days: int
                  ) -> Tuple[np.ndarray, np.ndarray, list[str]]:
    """
    Build X, y across all tickers.
    y = 1 if forward (horizon_days) return >= 0, else 0.
    Returns (X, y, used_features)
    """
    Xs, ys = [], []

    # use features in fixed order
    feat_cols = ["ret1","ret5","ret20","ret60",
                 "above50","above200","rsi14","rv20","rv60","adv20"]

    for t, df in frames.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        d = _feat_frame(df)
        if len(d) < (horizon_days + 220):  # need enough lookback to avoid all-NaN
            continue

        # target from price
        px = df["Adj Close"].astype(float)
        fwd = (px.shift(-horizon_days) / px - 1.0)
        y = (fwd >= 0).astype(int)

        # align X and y
        dd = d[feat_cols].copy()
        dd["y"] = y
        dd = dd.dropna()
        dd = dd.iloc[:-horizon_days]  # drop tail w/ no fwd return

        if len(dd) < 200:
            continue

        Xs.append(dd[feat_cols].values.astype(float))
        ys.append(dd["y"].values.astype(int))

    if not Xs:
        return np.empty((0, len(feat_cols))), np.empty((0,), dtype=int), feat_cols

    X = np.vstack(Xs)
    y = np.concatenate(ys)
    return X, y, feat_cols


# ----------------------------- fallback/dummy -----------------------------

@dataclass
class _DummyModel:
    """Predicts constant probability p_ (prior)."""
    p_: float
    feat_dim: int

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        p = np.clip(self.p_, 0.0, 1.0)
        n = X.shape[0]
        return np.column_stack([1.0 - p*np.ones(n), p*np.ones(n)])


# ----------------------------- public API --------------------------------

def train_direction_model(frames: Dict[str, pd.DataFrame], horizon_days: int = 30):
    """
    Trains a simple, robust classifier. If training data are insufficient or
    only one class exists, returns a `_DummyModel` with prior = up-rate (or 0.5).
    """
    X, y, feat_cols = _train_matrix(frames, horizon_days)

    # Not enough data → dummy 0.5
    if X.size == 0 or y.size == 0 or np.unique(y).size < 2:
        prior = float(np.mean(y)) if y.size > 0 else 0.5
        mdl = _DummyModel(p_=prior, feat_dim=len(feat_cols))
        return (mdl, feat_cols, prior)

    # Build real model
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression

    # Class weight balances up/down days if imbalanced
    pipe = Pipeline([
        ("scaler", StandardScaler(with_mean=True, with_std=True)),
        ("clf", LogisticRegression(
            max_iter=200,
            class_weight="balanced",
            solver="lbfgs",
            n_jobs=None
        ))
    ])

    pipe.fit(X, y)
    prior = float(np.mean(y))
    return (pipe, feat_cols, prior)


def predict_up_probability_for_latest(frames: Dict[str, pd.DataFrame], model_tuple) -> Dict[str, float]:
    """
    Returns {ticker: prob_up_30d}. Never raises; missing/short tickers return np.nan.
    """
    mdl, feat_cols, prior = model_tuple
    out: Dict[str, float] = {}

    for t, df in frames.items():
        try:
            f_all = _feat_frame(df)
            f = f_all.tail(1)[feat_cols].astype(float)
            if f.isna().any(axis=None) or f.shape[0] != 1:
                out[t] = np.nan
                continue

            proba = mdl.predict_proba(f.values)
            out[t] = float(proba[0, 1])  # P(up)
        except Exception:
            # If anything goes wrong for this ticker, mark NaN
            out[t] = np.nan

    return out