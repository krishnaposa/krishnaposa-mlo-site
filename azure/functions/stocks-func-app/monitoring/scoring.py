import numpy as np
import pandas as pd
from .indicators import clamp
from .config import PENNY_PRICE

WEIGHTS_DEBIT_SPREAD = {
    "ret_20_z": 0.5, "ret_60_z": 1.0, "ret_120_z": 1.2,
    "dist_52w_high": 0.8, "new_55d_high": 0.5,
    "adx14": 0.3, "mfi14": 0.2,
    "vol20_penalty": -0.3, "mdd_60_penalty": -1.2,
}
WEIGHTS_LEAPS = {
    "ret_20_z": 0.3, "ret_60_z": 0.8, "ret_120_z": 1.2,
    "dist_52w_high": 0.6, "new_55d_high": 0.4,
    "adx14": 0.4, "mfi14": 0.1,
    "vol20_penalty": -0.2, "mdd_60_penalty": -0.8,
}

def score_row(r: pd.Series, min_dollar_vol: int, strategy: str = "debit_call_spread") -> float:
    w = WEIGHTS_LEAPS if strategy == "leaps" else WEIGHTS_DEBIT_SPREAD
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
    risk = (
        w.get("vol20_penalty", -0.15) * r.get("vol20", 0.0) +
        w.get("mdd_60_penalty", -1.0) * abs(min(0.0, r.get("mdd_60", 0.0)))
    )

    penny_penalty = 0.6 if r.get("last_price", np.inf) < PENNY_PRICE else 0.0
    return float(trend + liquidity - risk - penny_penalty)


def score_wheel_put_row(r: pd.Series, option: dict) -> float:
    """
    Score cash-secured put candidates: quality first, then premium/liquidity.
    """
    roc = float(option.get("return_on_cash", 0.0) or 0.0)
    ann = float(option.get("annualized_return", 0.0) or 0.0)
    spread = float(option.get("spread_pct", 1.0) or 1.0)
    oi = float(option.get("open_interest", 0.0) or 0.0)
    buffer = float(option.get("downside_buffer", 0.0) or 0.0)

    quality = 0.0
    quality += 1.0 if r.get("close_above_sma20", 0.0) == 1.0 else 0.0
    quality += 1.0 if r.get("close_above_sma50", 0.0) == 1.0 else 0.0
    quality += 0.8 if r.get("dist_52w_high", -1.0) > -0.05 else 0.0
    quality += 0.6 * clamp((70.0 - float(r.get("rsi14", 70.0))) / 25.0, 0.0, 1.0)
    quality += 0.6 * clamp(float(r.get("rel_volume_20", 0.0)) - 1.0, 0.0, 1.0)
    quality += 0.8 * clamp(float(r.get("ml_prob_up_30d", 0.5)) - 0.5, 0.0, 0.5) * 2.0
    quality += 0.8 * clamp(float(r.get("hmm_prob_bull", 0.5)) - 0.5, 0.0, 0.5) * 2.0

    growth = max(
        float(r.get("rev_growth", 0.0) or 0.0),
        float(r.get("earn_growth", 0.0) or 0.0),
    )
    quality += 0.8 * clamp(growth / 0.5, 0.0, 1.0)

    premium = 1.5 * clamp(roc / 0.03, 0.0, 1.5)
    premium += 0.7 * clamp(ann / 0.30, 0.0, 1.5)
    liquidity = 0.8 * clamp(oi / 1000.0, 0.0, 1.5)
    risk_penalty = 1.0 * clamp(spread / 0.20, 0.0, 2.0)
    risk_penalty += 0.6 if buffer < 0.03 else 0.0

    return float(quality + premium + liquidity - risk_penalty)