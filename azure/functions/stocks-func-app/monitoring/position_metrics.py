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


def is_weak_any(m: dict) -> bool:
    """Down today OR down ~1 week OR below 20-DMA."""
    if not m:
        return False
    c1 = m.get("chg_1d_pct")
    c5 = m.get("chg_5d_pct")
    if c1 == c1 and float(c1) < 0:
        return True
    if c5 == c5 and float(c5) < 0:
        return True
    return bool(m.get("below_20dma"))


def is_weak_all_three(m: dict) -> bool:
    """Down today AND down ~1 week AND below 20-DMA."""
    if not m:
        return False
    c1 = m.get("chg_1d_pct")
    c5 = m.get("chg_5d_pct")
    if not (c1 == c1 and float(c1) < 0):
        return False
    if not (c5 == c5 and float(c5) < 0):
        return False
    return bool(m.get("below_20dma"))


def weak_price_rows(symbols: List[str], *, match: str = "any") -> List[dict]:
    """
    Symbols matching price weakness with Today%, Week%, <20DMA on each row.
    match='any' — down today OR down week OR below 20-DMA (default).
    match='all' — all three required.
    """
    syms = sorted({str(x).upper().strip() for x in symbols if str(x).strip()})
    if not syms:
        return []

    metrics = get_position_price_metrics(syms)
    pred = is_weak_all_three if match == "all" else is_weak_any
    rows: List[dict] = []
    for s in syms:
        m = metrics.get(s, {})
        if not pred(m):
            continue
        rows.append({
            "ticker": s,
            "today_pct": m.get("chg_1d_pct"),
            "week_pct": m.get("chg_5d_pct"),
            "below_20dma": bool(m.get("below_20dma")),
            "all_three": is_weak_all_three(m),
        })
    return rows


def format_weak_symbols_html(symbols: List[str], label: str) -> str:
    from html import escape as _esc

    rows = weak_price_rows(symbols, match="any")
    if not rows:
        return (
            f"<p><b>{_esc(label)}</b></p>"
            "<p><i>(none — no symbol down today, down ~1 week, or below 20-DMA)</i></p>"
        )

    parts = [
        f"<p><b>{_esc(label)}</b> "
        "<span style='font-size:11px;color:#666'>"
        "(any of: down today, down ~1 week, below 20-DMA — all three metrics shown)</span></p>",
        "<table border='0' cellspacing='0' cellpadding='4' style='font-size:13px'>",
        "<thead><tr>",
        "<th align='left'>Ticker</th>",
        "<th align='right'>Today%</th>",
        "<th align='right'>Week%</th>",
        "<th align='center'>&lt;20DMA</th>",
        "</tr></thead><tbody>",
    ]
    for r in rows:
        hl = " style='background:#fff4e5'" if r.get("all_three") else ""
        parts.append(
            f"<tr{hl}>"
            f"<td>{_esc(str(r.get('ticker', '')))}</td>"
            f"<td align='right'>{_esc(fmt_pct(r.get('today_pct')))}</td>"
            f"<td align='right'>{_esc(fmt_pct(r.get('week_pct')))}</td>"
            f"<td align='center'>{_esc(fmt_below(bool(r.get('below_20dma'))))}</td>"
            "</tr>"
        )
    parts.append("</tbody></table>")
    return "".join(parts)


def format_weak_symbols_text(symbols: List[str], *, label: str = "") -> str:
    rows = weak_price_rows(symbols, match="any")
    lines: List[str] = []
    if label:
        lines.append(f"  {label}")
        lines.append("  (any of: down today, down week, below 20-DMA)")
    if not rows:
        lines.append("  (none)")
        return "\n".join(lines)

    lines.append(f"  {'Ticker':<8} {'Today%':>8} {'Week%':>8} {'<20DMA':>6}")
    for r in rows:
        lines.append(
            f"  {str(r.get('ticker', '')):<8} "
            f"{fmt_pct(r.get('today_pct')):>8} "
            f"{fmt_pct(r.get('week_pct')):>8} "
            f"{fmt_below(bool(r.get('below_20dma'))):>6}"
        )
    return "\n".join(lines)
