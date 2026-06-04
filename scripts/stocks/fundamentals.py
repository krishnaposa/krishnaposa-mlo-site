"""
Lightweight fundamentals check for BUY candidates (yfinance).

Intended for the small set of BUY survivors, NOT the whole scan universe —
yfinance .info is slow (~1-2s/ticker) and flaky, so we fetch per symbol with
try/except and treat missing data as WARN (never crash, never hard-block on
missing data).

Verdict per ticker:
  PASS  meets all hard checks
  WARN  some data missing, or soft concern (e.g. negative margin)
  FAIL  violates a hard filter (small cap, shrinking revenue, absurd valuation)
"""

from __future__ import annotations

from dataclasses import dataclass

import yfinance as yf

# Defaults (soft profile): hard-fail only on clearly bad fundamentals.
MIN_MARKET_CAP = 1_000_000_000.0   # $1B
MIN_REV_GROWTH = 0.0               # revenue growth >= 0 (YoY)
MAX_PS = 40.0                      # price/sales sanity cap


@dataclass
class FundamentalResult:
    ticker: str
    market_cap: float
    rev_growth: float
    profit_margin: float
    ps_ratio: float
    verdict: str
    notes: str


def _f(val) -> float:
    try:
        if val is None:
            return float("nan")
        return float(val)
    except Exception:
        return float("nan")


def check_fundamentals(
    symbol: str,
    *,
    min_market_cap: float = MIN_MARKET_CAP,
    min_rev_growth: float = MIN_REV_GROWTH,
    max_ps: float = MAX_PS,
) -> FundamentalResult:
    """Fetch + grade fundamentals for one symbol. Never raises."""
    info: dict = {}
    try:
        info = yf.Ticker(symbol).info or {}
    except Exception:
        info = {}

    market_cap = _f(info.get("marketCap"))
    rev_growth = _f(info.get("revenueGrowth"))
    profit_margin = _f(info.get("profitMargins"))
    ps_ratio = _f(info.get("priceToSalesTrailing12Months"))

    notes: list[str] = []
    fails: list[str] = []
    missing = False

    if market_cap == market_cap:
        if market_cap < min_market_cap:
            fails.append(f"mcap ${market_cap/1e9:.1f}B < ${min_market_cap/1e9:.1f}B")
    else:
        missing = True

    if rev_growth == rev_growth:
        if rev_growth < min_rev_growth:
            fails.append(f"rev growth {rev_growth*100:.0f}% < {min_rev_growth*100:.0f}%")
    else:
        missing = True

    if ps_ratio == ps_ratio and ps_ratio > max_ps:
        fails.append(f"P/S {ps_ratio:.0f} > {max_ps:g}")

    if profit_margin == profit_margin and profit_margin < 0:
        notes.append(f"unprofitable (margin {profit_margin*100:.0f}%)")

    if fails:
        verdict = "FAIL"
        notes = fails + notes
    elif missing:
        verdict = "WARN"
        notes.append("missing fundamentals")
    elif notes:
        verdict = "WARN"
    else:
        verdict = "PASS"

    return FundamentalResult(
        ticker=symbol,
        market_cap=market_cap,
        rev_growth=rev_growth,
        profit_margin=profit_margin,
        ps_ratio=ps_ratio,
        verdict=verdict,
        notes="; ".join(notes),
    )
