"""Price metrics for held symbols: 1-day / 5-day change and 20-DMA."""

from __future__ import annotations

from typing import Dict, List

import pandas as pd
import yfinance as yf


def get_position_price_metrics(symbols: List[str], period: str = "3mo") -> Dict[str, dict]:
    """
    Per symbol:
      last, chg_1d_pct, chg_5d_pct, dma20, below_20dma (bool)
    """
    syms = sorted({str(s).upper().strip() for s in symbols if str(s).strip()})
    empty = {
        "last": float("nan"),
        "chg_1d_pct": float("nan"),
        "chg_5d_pct": float("nan"),
        "dma20": float("nan"),
        "below_20dma": False,
    }
    if not syms:
        return {}

    data = yf.download(syms, period=period, interval="1d", progress=False, auto_adjust=True)
    if data is None or data.empty:
        return {s: dict(empty) for s in syms}

    closes = data["Close"]
    out: Dict[str, dict] = {}

    for s in syms:
        try:
            if isinstance(closes, pd.DataFrame):
                series = closes[s].dropna() if s in closes.columns else pd.Series(dtype=float)
            else:
                series = closes.dropna()
        except Exception:
            series = pd.Series(dtype=float)

        if series.empty or len(series) < 2:
            out[s] = dict(empty)
            continue

        last = float(series.iloc[-1])
        prev = float(series.iloc[-2])
        chg_1d = ((last - prev) / prev * 100.0) if prev else float("nan")

        chg_5d = float("nan")
        if len(series) >= 6:
            ref = float(series.iloc[-6])
            if ref:
                chg_5d = (last - ref) / ref * 100.0

        dma20 = float("nan")
        below = False
        if len(series) >= 20:
            dma20 = float(series.iloc[-20:].mean())
            below = last < dma20

        out[s] = {
            "last": last,
            "chg_1d_pct": chg_1d,
            "chg_5d_pct": chg_5d,
            "dma20": dma20,
            "below_20dma": below,
        }

    return out


def fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and not pd.notna(v)):
        return "—"
    return f"{float(v):+.2f}%"


def fmt_below(v: bool) -> str:
    return "Yes" if v else "No"


def needs_attention(m: dict) -> bool:
    """Highlight when down today, down over ~1 week, or under 20-DMA."""
    if not m:
        return False
    c1 = m.get("chg_1d_pct")
    c5 = m.get("chg_5d_pct")
    if c1 == c1 and float(c1) < 0:
        return True
    if c5 == c5 and float(c5) < 0:
        return True
    if m.get("below_20dma"):
        return True
    return False
