"""Independent PCS recommendation section for the morning email.

PCS-oriented second opinion: short-strike buffer, structure quality, pie Grade/Signal,
breakdown/spike filters, light market regime. Alpha Trend is only a soft tie-breaker —
not a hard READY gate.
"""

from __future__ import annotations

import os
from functools import lru_cache
from html import escape
from typing import Any, Dict, Iterable, List, Mapping, Optional

import pandas as pd
import yfinance as yf

from .pcs_common import earnings_blocks_new_spread, pcs_buffer_pct
from .pie_scanner import GRADE_RANK, is_spiked

BENCHMARK = os.getenv("PCS_REC_BENCHMARK", "SPY").upper()
READY_SCORE = int(os.getenv("PCS_REC_READY_SCORE", "75"))
CAUTION_SCORE = int(os.getenv("PCS_REC_CAUTION_SCORE", "55"))
MIN_BUFFER = float(os.getenv("PCS_REC_MIN_BUFFER", "6"))
READY_BUFFER = float(os.getenv("PCS_REC_READY_BUFFER", "10"))
MIN_CREDIT_WIDTH = float(os.getenv("PCS_REC_MIN_CREDIT_WIDTH", "0.15"))
READY_CREDIT_WIDTH = float(os.getenv("PCS_REC_READY_CREDIT_WIDTH", "0.18"))
DEFAULT_OTM_PCT = float(os.getenv("PCS_REC_DEFAULT_OTM_PCT", "6"))  # % if no short strike
MAX_ROWS = int(os.getenv("PCS_REC_MAX_ROWS", "20"))
ATR_MULT = float(os.getenv("PCS_REC_ATR_MULT", "2"))


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    gain = d.clip(lower=0)
    loss = -d.clip(upper=0)
    ag = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    al = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = ag / al.replace(0, float("nan"))
    return (100 - 100 / (1 + rs)).fillna(100)


def _tr(df: pd.DataFrame) -> pd.Series:
    pc = df["Close"].shift()
    return pd.concat(
        [
            (df["High"] - df["Low"]),
            (df["High"] - pc).abs(),
            (df["Low"] - pc).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return _tr(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def _alpha_trend(df: pd.DataFrame) -> pd.Series:
    """Soft trend trail — used only as a small bonus/penalty."""
    atr = _atr(df)
    rsi = _rsi(df["Close"])
    bull = df["Low"] - ATR_MULT * atr
    bear = df["High"] + ATR_MULT * atr
    values: List[float] = []
    for i in range(len(df)):
        if i == 0 or pd.isna(atr.iloc[i]):
            values.append(float(df["Close"].iloc[i]))
        elif float(rsi.iloc[i]) >= 50:
            values.append(max(float(bull.iloc[i]), values[-1]))
        else:
            values.append(min(float(bear.iloc[i]), values[-1]))
    return pd.Series(values, index=df.index)


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] for c in df.columns]
    needed = ["Open", "High", "Low", "Close", "Volume"]
    # Open optional for gap; require HLCV
    core = ["High", "Low", "Close", "Volume"]
    if any(c not in df.columns for c in core):
        return pd.DataFrame()
    cols = [c for c in needed if c in df.columns]
    out = df[cols].apply(pd.to_numeric, errors="coerce").dropna(subset=["High", "Low", "Close"])
    if "Open" not in out.columns:
        out = out.copy()
        out["Open"] = out["Close"]
    return out


@lru_cache(maxsize=512)
def _history(symbol: str) -> pd.DataFrame:
    try:
        return _normalize(
            yf.download(
                symbol,
                period="12mo",
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=False,
            )
        )
    except Exception:
        return pd.DataFrame()


def _safe_float(val: Any, default: float = float("nan")) -> float:
    try:
        if val is None or val == "":
            return default
        x = float(val)
        if x != x:
            return default
        return x
    except (TypeError, ValueError):
        return default


def _ctx_get(ctx: Optional[Mapping[str, Any]], *keys: str) -> Any:
    if not ctx:
        return None
    for k in keys:
        if k in ctx and ctx[k] is not None and ctx[k] != "":
            return ctx[k]
    return None


def assess_ticker(
    symbol: str,
    *,
    context: Optional[Mapping[str, Any]] = None,
) -> Optional[dict]:
    """
    Score a name for PCS entry/hold quality.

    ``context`` may include opportunity/lifecycle fields:
      Grade, Signal, Short, Long, Credit, Width, Credit%, OTM%, IV%, DTE, Buffer%
    """
    symbol = symbol.upper().strip()
    df = _history(symbol)
    spy = _history(BENCHMARK)
    if len(df) < 60 or len(spy) < 60:
        return None

    close = df["Close"]
    volume = df["Volume"]
    dma10, dma20, dma50 = _sma(close, 10), _sma(close, 20), _sma(close, 50)
    rsi = _rsi(close)
    atr = _atr(df)
    alpha = _alpha_trend(df)

    price = float(close.iloc[-1])
    prev = df.iloc[-2]
    d10, d20, d50 = float(dma10.iloc[-1]), float(dma20.iloc[-1]), float(dma50.iloc[-1])
    rsin = float(rsi.iloc[-1])
    run5 = float((close.iloc[-1] / close.iloc[-6] - 1.0) * 100.0) if len(close) >= 6 else 0.0
    ext20 = ((price - d20) / d20 * 100.0) if d20 > 0 else 0.0
    vol_avg = float(volume.rolling(20).mean().iloc[-1] or 0.0)
    vol_ratio = float(volume.iloc[-1] / vol_avg) if vol_avg > 0 else 1.0
    gap_pct = float((df["Open"].iloc[-1] - prev["Close"]) / prev["Close"] * 100.0)

    # RS vs SPY (20d relative)
    joined = pd.concat([close.rename("stock"), spy["Close"].rename("bench")], axis=1).dropna()
    if len(joined) < 25:
        return None
    rs_val = float(
        joined["stock"].pct_change(20).iloc[-1] - joined["bench"].pct_change(20).iloc[-1]
    )
    rs_ok = rs_val > 0
    rs_strong = rs_val > 0.02

    spy_close = spy["Close"]
    spy50 = float(_sma(spy_close, 50).iloc[-1])
    spy_px = float(spy_close.iloc[-1])
    market_bullish = spy_px > spy50
    market_weak = spy_px < spy50 * 0.98  # clearly below 50DMA

    bull_stack = price > d10 > d20 > d50
    soft_bull = price > d20 and d20 >= d50
    below10_2d = float(close.iloc[-1]) < float(dma10.iloc[-1]) and float(close.iloc[-2]) < float(
        dma10.iloc[-2]
    )
    below20_2d = float(close.iloc[-1]) < float(dma20.iloc[-1]) and float(close.iloc[-2]) < float(
        dma20.iloc[-2]
    )
    bear_stack = price < d10 < d20 < d50

    alpha_n = float(alpha.iloc[-1])
    alpha_bull = price > alpha_n and alpha_n >= float(alpha.iloc[-3])
    alpha_bear = price < alpha_n and alpha_n <= float(alpha.iloc[-3])
    spiked = is_spiked(ext20, rsin, run5)

    # --- Context from PCS plan / open position ---
    grade = str(_ctx_get(context, "Grade") or "").upper().strip()
    signal = str(_ctx_get(context, "Signal") or "").upper().strip()
    short_k = _safe_float(_ctx_get(context, "Short", "short_put"))
    credit_width = _safe_float(_ctx_get(context, "Credit%", "credit_width_pct"))
    # Credit% may be stored as 0.18 or 18
    if credit_width == credit_width and credit_width > 1.5:
        credit_width = credit_width / 100.0
    otm_pct = _safe_float(_ctx_get(context, "OTM%", "otm_pct"))
    dte = _safe_float(_ctx_get(context, "DTE", "dte"), default=35.0)
    iv_pct = _safe_float(_ctx_get(context, "IV%", "iv_pct"))
    ctx_buffer = _safe_float(_ctx_get(context, "Buffer%"))

    if short_k == short_k and short_k > 0:
        buffer_pct = pcs_buffer_pct(price, short_k)
        buffer_label = "to short"
    elif ctx_buffer == ctx_buffer:
        buffer_pct = ctx_buffer
        buffer_label = "pos"
    elif otm_pct == otm_pct and otm_pct > 0:
        buffer_pct = otm_pct
        buffer_label = "OTM"
    else:
        # Fallback: distance to a synthetic short at DEFAULT_OTM_PCT below spot
        synth = price * (1.0 - DEFAULT_OTM_PCT / 100.0)
        buffer_pct = pcs_buffer_pct(price, synth)
        buffer_label = f"~{DEFAULT_OTM_PCT:.0f}% OTM"

    if buffer_pct != buffer_pct:
        buffer_pct = 0.0

    swing_low = float(df["Low"].rolling(20).min().iloc[-1])
    support_buf = (price - swing_low) / price * 100.0 if price > 0 else 0.0

    earnings_block = False
    try:
        earnings_block = earnings_blocks_new_spread(symbol, int(dte) if dte == dte else 35)
    except Exception:
        earnings_block = False

    # --- Score (PCS-weighted) ---
    score = 0
    why_bits: List[str] = []

    # Structure / MAs (pie-aligned)
    if bull_stack:
        score += 18
        why_bits.append("DMA stack")
    elif soft_bull:
        score += 10
        why_bits.append("above 20/50")
    elif below20_2d or bear_stack:
        score -= 18
        why_bits.append("breakdown")
    elif below10_2d:
        score -= 6
        why_bits.append("below 10DMA")

    if rs_strong:
        score += 12
        why_bits.append("RS strong")
    elif rs_ok:
        score += 6
    else:
        score -= 4
        why_bits.append("RS weak")

    if 0.9 <= vol_ratio <= 2.5:
        score += 4
    elif vol_ratio > 3.0 and run5 < 0:
        score -= 6
        why_bits.append("heavy sell vol")

    # Buffer to short (primary PCS risk)
    if buffer_pct >= READY_BUFFER:
        score += 20
        why_bits.append(f"buf {buffer_pct:.1f}%")
    elif buffer_pct >= MIN_BUFFER:
        score += 10
        why_bits.append(f"buf {buffer_pct:.1f}%")
    else:
        score -= 12
        why_bits.append(f"thin buf {buffer_pct:.1f}%")

    if support_buf >= READY_BUFFER:
        score += 6
    elif support_buf < MIN_BUFFER:
        score -= 4

    # Spread quality when known
    if credit_width == credit_width:
        if credit_width >= READY_CREDIT_WIDTH:
            score += 14
            why_bits.append(f"cred/w {credit_width:.0%}")
        elif credit_width >= MIN_CREDIT_WIDTH:
            score += 8
            why_bits.append(f"cred/w {credit_width:.0%}")
        else:
            score -= 8
            why_bits.append(f"poor cred/w {credit_width:.0%}")

    if iv_pct == iv_pct:
        if 25 <= iv_pct <= 80:
            score += 6
        elif iv_pct > 100:
            score -= 4  # panic / binary risk
            why_bits.append(f"IV {iv_pct:.0f}% hot")

    # Pie Grade / Signal when known
    gr = GRADE_RANK.get(grade, 0)
    if gr >= 4:  # A
        score += 14
        why_bits.append("Grade A")
    elif gr == 3:  # B
        score += 10
        why_bits.append("Grade B")
    elif gr == 2:  # C
        score += 4
        why_bits.append("Grade C")
    elif grade == "D":
        score -= 8
        why_bits.append("Grade D")

    if signal in ("SELL", "REDUCE"):
        score -= 20
        why_bits.append(signal)
    elif signal == "BUY":
        score += 8
        why_bits.append("BUY")
    elif signal == "WATCH":
        score -= 4
        why_bits.append("WATCH")
    elif signal == "HOLD":
        score += 3

    # Market regime (light)
    if market_bullish:
        score += 6
    elif market_weak:
        score -= 10
        why_bits.append("SPY weak")
    else:
        score += 2

    # Spike / gap (avoid chasing)
    if spiked:
        score -= 12
        why_bits.append("extended")
    if gap_pct <= -3.0:
        score -= 10
        why_bits.append(f"gap {gap_pct:.1f}%")

    if earnings_block:
        score -= 25
        why_bits.append("earnings in window")

    # Soft Alpha Trend (tie-breaker only)
    if alpha_bull:
        score += 4
    elif alpha_bear:
        score -= 6
        why_bits.append("alpha bear")

    # RSI sweet spot for short premium (not overbought melt-up)
    if 45 <= rsin <= 70:
        score += 5
    elif rsin > 78:
        score -= 6
        why_bits.append("RSI hot")
    elif rsin < 35:
        score -= 8
        why_bits.append("RSI washed")

    score = max(0, min(100, int(round(score))))

    # --- Labels ---
    hard_avoid = (
        earnings_block
        or signal in ("SELL", "REDUCE")
        or bear_stack
        or (below20_2d and market_weak)
        or (alpha_bear and price < d50 and buffer_pct < MIN_BUFFER)
    )
    structure_ok = bull_stack or soft_bull
    buffer_ready = buffer_pct >= READY_BUFFER
    buffer_ok = buffer_pct >= MIN_BUFFER
    credit_ok = (credit_width != credit_width) or (credit_width >= MIN_CREDIT_WIDTH)
    grade_ok = (not grade) or gr >= 3 or grade == "C"  # allow C for CAUTION path

    if hard_avoid:
        recommendation = "AVOID"
    elif (
        score >= READY_SCORE
        and structure_ok
        and buffer_ready
        and credit_ok
        and not spiked
        and not market_weak
        and signal not in ("WATCH",)
        and (not grade or gr >= 3)
    ):
        recommendation = "PCS READY"
    elif score >= CAUTION_SCORE and buffer_ok and grade_ok and not earnings_block:
        recommendation = "CAUTION"
    else:
        recommendation = "WAIT"

    trend = "Bullish" if structure_ok and not below20_2d else ("Bearish" if bear_stack or below20_2d else "Mixed")
    market = "Bullish" if market_bullish else ("Weak" if market_weak else "Neutral")

    short_disp = round(short_k, 2) if short_k == short_k and short_k > 0 else "—"
    cred_disp = f"{credit_width:.0%}" if credit_width == credit_width else "—"

    return {
        "Ticker": symbol,
        "Recommendation": recommendation,
        "Score": score,
        "Price": round(price, 2),
        "Grade": grade or "—",
        "Signal": signal or "—",
        "Short": short_disp,
        "Buffer%": round(buffer_pct, 1),
        "BufSrc": buffer_label,
        "Cred/W": cred_disp,
        "Trend": trend,
        "RSI": round(rsin, 1),
        "RSvsSPY": "Strong" if rs_strong else ("OK" if rs_ok else "Weak"),
        "Market": market,
        "Why": ", ".join(why_bits[:6]) if why_bits else "neutral",
    }


def build_recommendation_context(
    opportunities: Optional[Mapping[str, Any]] = None,
    lifecycle: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Merge opportunity + open-spread fields keyed by ticker (ideas win on Grade/plan)."""
    ctx: Dict[str, Dict[str, Any]] = {}

    def _merge(row: Mapping[str, Any], *, prefer_plan: bool) -> None:
        sym = str(row.get("Ticker") or "").upper().strip()
        if not sym:
            return
        cur = ctx.setdefault(sym, {})
        for key in (
            "Grade",
            "Signal",
            "Short",
            "Long",
            "Credit",
            "Width",
            "Credit%",
            "OTM%",
            "IV%",
            "DTE",
            "Buffer%",
        ):
            if key not in row or row[key] is None or row[key] == "":
                continue
            if prefer_plan or key not in cur:
                cur[key] = row[key]

    if lifecycle:
        for row in lifecycle.get("pcs_rows") or []:
            if isinstance(row, dict):
                _merge(row, prefer_plan=False)
    if opportunities:
        for rows_key in ("rows", "rows_b", "rows_c"):
            for row in opportunities.get(rows_key) or []:
                if isinstance(row, dict):
                    _merge(row, prefer_plan=True)
    return ctx


def run_pcs_recommendations(
    tickers: Iterable[str],
    *,
    context_by_ticker: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    rows: List[dict] = []
    ctx_map = context_by_ticker or {}
    for symbol in sorted({str(t).upper().strip() for t in tickers if str(t).strip()}):
        assessment = assess_ticker(symbol, context=ctx_map.get(symbol))
        if assessment:
            rows.append(assessment)

    rank = {"PCS READY": 0, "CAUTION": 1, "WAIT": 2, "AVOID": 3}
    rows.sort(key=lambda r: (rank.get(r["Recommendation"], 9), -r["Score"]))
    rows = rows[:MAX_ROWS]

    return {
        "rows": rows,
        "html": format_pcs_recommendations_html(rows),
        "text": format_pcs_recommendations_text(rows),
    }


def _badge(value: str) -> str:
    colors = {
        "PCS READY": "#1b5e20",
        "CAUTION": "#ef6c00",
        "WAIT": "#616161",
        "AVOID": "#b71c1c",
    }
    return (
        f"<span style='background:{colors.get(value, '#616161')};color:white;"
        f"padding:2px 6px;border-radius:4px;font-weight:bold'>{escape(value)}</span>"
    )


def format_pcs_recommendations_html(rows: List[dict]) -> str:
    if not rows:
        return (
            "<hr><p><b>PCS RECOMMENDATIONS</b></p>"
            "<p><i>No recommendations available.</i></p>"
        )

    cols = [
        "Ticker",
        "Recommendation",
        "Score",
        "Grade",
        "Signal",
        "Price",
        "Short",
        "Buffer%",
        "Cred/W",
        "Trend",
        "RSvsSPY",
        "Market",
        "Why",
    ]
    head = "".join(f"<th align='left'>{escape(c)}</th>" for c in cols)
    body = []
    for row in rows:
        cells = []
        for col in cols:
            value = row.get(col, "")
            if col == "Buffer%" and row.get("BufSrc"):
                value = f"{value} ({row.get('BufSrc')})"
            cells.append(
                f"<td>{_badge(str(value)) if col == 'Recommendation' else escape(str(value))}</td>"
            )
        body.append(f"<tr>{''.join(cells)}</tr>")

    return (
        "<hr><p><b>PCS RECOMMENDATIONS</b></p>"
        "<p style='font-size:12px'>Second opinion focused on short-put buffer, spread quality, "
        "and breakdown risk — does not change candidate strikes or credits.</p>"
        "<table border='1' cellspacing='0' cellpadding='4' "
        "style='border-collapse:collapse;font-family:Arial,sans-serif;font-size:12px'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
        "<p style='font-size:11px;color:#666'>READY needs structure + buffer≥"
        f"{READY_BUFFER:.0f}% + acceptable credit/width; AVOID on earnings-in-window, "
        "REDUCE/SELL, or clear breakdown. Verify chain before trading.</p>"
    )


def format_pcs_recommendations_text(rows: List[dict]) -> str:
    lines = ["PCS RECOMMENDATIONS", ""]
    if not rows:
        return "\n".join(lines + ["No recommendations available."])
    for row in rows:
        lines.append(
            f"{row['Ticker']} {row['Recommendation']} Score={row['Score']} "
            f"Grade={row.get('Grade','—')} Signal={row.get('Signal','—')} "
            f"Short={row.get('Short','—')} Buffer={row['Buffer%']}%({row.get('BufSrc','')}) "
            f"Cred/W={row.get('Cred/W','—')} Trend={row['Trend']} "
            f"RS={row['RSvsSPY']} Mkt={row['Market']} Why={row['Why']}"
        )
    return "\n".join(lines)
