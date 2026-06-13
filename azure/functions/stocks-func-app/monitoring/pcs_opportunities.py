"""
PCS entry ideas for daily email (pie_analyze_swing funnel).
Scans tickers from blob my_tickers.txt or local_list + holdings_list, then builds PCS plans.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from html import escape as _esc
from typing import Any, Dict, List, Optional

import pandas as pd
import yfinance as yf

from .pie_scanner import run_scan, select_buy_candidates

logger = logging.getLogger(__name__)

PIE_TICKERS_BLOB = os.getenv("PIE_TICKERS_BLOB", "my_tickers.txt")
PIE_TICKERS_FILE = os.getenv("PIE_TICKERS_FILE", "").strip()
PIE_MIN_GRADE = os.getenv("PIE_MIN_GRADE", "B")
PIE_TARGET_DTE = int(os.getenv("PIE_TARGET_DTE", "35"))
PIE_OTM_PCT = float(os.getenv("PIE_OTM_PCT", "0.06"))
PIE_SPREAD_WIDTH_PCT = float(os.getenv("PIE_SPREAD_WIDTH_PCT", "0.03"))
PIE_MAX_PCS_CANDIDATES = int(os.getenv("PIE_MAX_PCS_CANDIDATES", "12"))
MIN_OPEN_INTEREST = int(os.getenv("PCS_MIN_OPEN_INTEREST", "100"))
MAX_SPREAD_PCT = float(os.getenv("PCS_MAX_SPREAD_PCT", "15"))
MIN_CREDIT_WIDTH = float(os.getenv("PCS_MIN_CREDIT_WIDTH", "0.20"))


@dataclass
class PutCreditSpread:
    symbol: str
    expiration: str
    dte: int
    short_put: float
    long_put: float
    width: float
    credit: float
    max_risk: float
    pop: float
    iv_pct: float


def _parse_ticker_text(raw: str) -> List[str]:
    tickers = []
    for line in raw.replace(",", " ").splitlines():
        for tok in re.split(r"[\s\t;]+", line.strip()):
            t = tok.upper().strip().lstrip("$")
            if t and re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", t):
                tickers.append(t)
    return sorted(set(tickers))


def load_pie_scan_tickers() -> List[str]:
    """PIE_TICKERS_FILE, else blob my_tickers.txt, else local_list + holdings_list."""
    if PIE_TICKERS_FILE:
        try:
            path = os.path.expanduser(PIE_TICKERS_FILE)
            if os.path.isfile(path):
                with open(path, encoding="utf-8", errors="ignore") as f:
                    tickers = _parse_ticker_text(f.read())
                if tickers:
                    logger.info("[pcs_opportunities] %d tickers from file %s", len(tickers), path)
                    return tickers
        except Exception as e:
            logger.warning("[pcs_opportunities] PIE_TICKERS_FILE read failed (%s): %s", PIE_TICKERS_FILE, e)

    try:
        from local_list_utils import (
            LOCAL_LIST_CONTAINER,
            _get_named_blob_client,
            load_holdings_list,
            load_local_list,
        )

        blob = _get_named_blob_client(LOCAL_LIST_CONTAINER, PIE_TICKERS_BLOB)
        raw = blob.download_blob().readall().decode("utf-8", errors="ignore")
        tickers = _parse_ticker_text(raw)
        if tickers:
            logger.info("[pcs_opportunities] %d tickers from %s/%s", len(tickers), LOCAL_LIST_CONTAINER, PIE_TICKERS_BLOB)
            return tickers
    except Exception as e:
        logger.info("[pcs_opportunities] no %s blob (%s)", PIE_TICKERS_BLOB, e)

    try:
        from local_list_utils import load_holdings_list, load_local_list

        merged = sorted(set(load_local_list()) | set(load_holdings_list()))
        if merged:
            logger.info("[pcs_opportunities] %d tickers from local_list + holdings_list", len(merged))
            return merged
    except Exception as e:
        logger.warning("[pcs_opportunities] ticker fallback failed: %s", e)
    return []


def _mid_price(row) -> float:
    bid = float(row.get("bid") or 0.0)
    ask = float(row.get("ask") or 0.0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return float(row.get("lastPrice") or 0.0)


def _leg_is_liquid(row, *, min_oi: int, max_spread_pct: float) -> bool:
    oi = int(row.get("openInterest") or 0)
    if oi < min_oi:
        return False
    bid = float(row.get("bid") or 0.0)
    ask = float(row.get("ask") or 0.0)
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return False
    return ((ask - bid) / mid * 100.0) <= max_spread_pct


def build_pcs_plan(
    symbol: str,
    price: float,
    *,
    target_dte: int = PIE_TARGET_DTE,
    otm_pct: float = PIE_OTM_PCT,
    spread_width_pct: float = PIE_SPREAD_WIDTH_PCT,
) -> Optional[PutCreditSpread]:
    tk = yf.Ticker(symbol)
    try:
        expiries = list(tk.options or [])
    except Exception:
        return None
    if not expiries:
        return None

    today = datetime.today().date()

    def dte_of(exp: str) -> int:
        return (datetime.strptime(exp, "%Y-%m-%d").date() - today).days

    valid = [e for e in expiries if dte_of(e) > 0]
    if not valid:
        return None
    expiry = min(valid, key=lambda e: abs(dte_of(e) - target_dte))
    dte = dte_of(expiry)

    try:
        puts = tk.option_chain(expiry).puts
    except Exception:
        return None
    if puts is None or puts.empty:
        return None

    puts = puts.sort_values("strike")
    liquid = puts[puts.apply(
        lambda r: _leg_is_liquid(r, min_oi=MIN_OPEN_INTEREST, max_spread_pct=MAX_SPREAD_PCT),
        axis=1,
    )]
    if liquid.empty:
        return None

    short_candidates = liquid[liquid["strike"] <= price * (1 - otm_pct)]
    if short_candidates.empty:
        return None
    short_row = short_candidates.iloc[-1]
    short_strike = float(short_row["strike"])

    long_candidates = liquid[liquid["strike"] <= short_strike * (1 - spread_width_pct)]
    if long_candidates.empty:
        lower = liquid[liquid["strike"] < short_strike]
        if lower.empty:
            return None
        long_row = lower.iloc[-1]
    else:
        long_row = long_candidates.iloc[-1]
    long_strike = float(long_row["strike"])

    width = short_strike - long_strike
    if width <= 0:
        return None

    credit = _mid_price(short_row) - _mid_price(long_row)
    if credit <= 0 or (credit / width) < MIN_CREDIT_WIDTH:
        return None

    iv_pct = float(short_row.get("impliedVolatility") or 0.0) * 100.0

    return PutCreditSpread(
        symbol=symbol,
        expiration=expiry,
        dte=dte,
        short_put=short_strike,
        long_put=long_strike,
        width=round(width, 2),
        credit=round(credit, 2),
        max_risk=round(width - credit, 2),
        pop=round(1.0 - (credit / width), 3),
        iv_pct=round(iv_pct, 1),
    )


def run_pcs_opportunities() -> Dict[str, Any]:
    """
    Returns {enabled, html, tickers, rows}.
    rows: list of dicts for email table (next-day PCS ideas).
    """
    out: Dict[str, Any] = {"enabled": True, "html": "", "tickers": [], "rows": []}
    if os.getenv("PCS_OPPORTUNITIES_ENABLED", "1") != "1":
        out["enabled"] = False
        return out

    tickers = load_pie_scan_tickers()
    if not tickers:
        out["scanned"] = 0
        out["buys"] = 0
        hint = (
            f"<code>{_esc(PIE_TICKERS_BLOB)}</code> to signals container, "
            "set PIE_TICKERS_FILE (local), or populate local_list."
        )
        out["html"] = f"<p><i>No scan tickers — upload {hint}</i></p>"
        return out

    scan = run_scan(tickers)
    buys = select_buy_candidates(scan, min_grade=PIE_MIN_GRADE)
    if buys.empty:
        out["scanned"] = len(tickers)
        out["buys"] = 0
        out["html"] = (
            f"<p><i>No BUY candidates (Grade &gt;= {_esc(PIE_MIN_GRADE)}) from {len(tickers)} scanned symbols.</i></p>"
        )
        return out

    rows: List[dict] = []
    for _, row in buys.head(PIE_MAX_PCS_CANDIDATES).iterrows():
        sym = str(row["Ticker"])
        plan = build_pcs_plan(sym, float(row["Price"]))
        if plan is None:
            continue
        rows.append({
            "Ticker": plan.symbol,
            "Expiry": plan.expiration,
            "DTE": plan.dte,
            "Short": plan.short_put,
            "Long": plan.long_put,
            "Width": plan.width,
            "Credit": plan.credit,
            "MaxRisk": plan.max_risk,
            "POP~": plan.pop,
            "IV%": plan.iv_pct,
        })

    out["rows"] = rows
    out["tickers"] = [r["Ticker"] for r in rows]
    out["scanned"] = len(tickers)
    out["buys"] = len(buys)
    out["html"] = format_pcs_opportunities_html(rows, scanned=len(tickers), buys=len(buys))
    return out


PCS_TABLE_COLS = ["Ticker", "Expiry", "DTE", "Short", "Long", "Width", "Credit", "MaxRisk", "POP~", "IV%"]


def _fmt_cell(col: str, val) -> str:
    if val is None or val == "":
        return ""
    if col in ("Credit", "MaxRisk"):
        try:
            return f"{float(val):.2f}"
        except (TypeError, ValueError):
            return str(val)
    if col in ("Short", "Long", "Width"):
        try:
            return f"{float(val):.1f}"
        except (TypeError, ValueError):
            return str(val)
    if col == "POP~":
        try:
            return f"{float(val):.3f}"
        except (TypeError, ValueError):
            return str(val)
    if col == "IV%":
        try:
            return f"{float(val):.1f}"
        except (TypeError, ValueError):
            return str(val)
    return str(val)


def _pcs_session_label() -> str:
    return (os.getenv("PCS_SESSION_LABEL") or "next session").strip() or "next session"


def format_pcs_opportunities_text(rows: List[dict], *, scanned: int, buys: int) -> str:
    """Plain-text table matching pie_analyze_swing PCS output."""
    header = (
        f"  {'Ticker':<8} {'Expiry':<10} {'DTE':>4} {'Short':>7} {'Long':>7} "
        f"{'Width':>6} {'Credit':>7} {'MaxRisk':>7} {'POP~':>6} {'IV%':>6}"
    )
    if not rows:
        return (
            f"  Scanned {scanned} symbols · {buys} BUY (grade >= {PIE_MIN_GRADE}) · "
            "no PCS plans passed liquidity/credit filters."
        )
    lines = [
        f"  Scanned {scanned} symbols · {buys} BUY (grade >= {PIE_MIN_GRADE}) · "
        f"{len(rows)} PCS plan(s) for {_pcs_session_label()}.",
        header,
    ]
    for r in rows:
        lines.append(
            f"  {str(r.get('Ticker', '')):<8} "
            f"{str(r.get('Expiry', '')):<10} "
            f"{int(r.get('DTE', 0)):>4} "
            f"{_fmt_cell('Short', r.get('Short')):>7} "
            f"{_fmt_cell('Long', r.get('Long')):>7} "
            f"{_fmt_cell('Width', r.get('Width')):>6} "
            f"{_fmt_cell('Credit', r.get('Credit')):>7} "
            f"{_fmt_cell('MaxRisk', r.get('MaxRisk')):>7} "
            f"{_fmt_cell('POP~', r.get('POP~')):>6} "
            f"{_fmt_cell('IV%', r.get('IV%')):>6}"
        )
    lines.append("  Estimates only — verify option chain before trading.")
    return "\n".join(lines)


def format_pcs_opportunities_html(rows: List[dict], *, scanned: int, buys: int) -> str:
    if not rows:
        return (
            f"<p>Scanned {scanned} symbols · {buys} BUY names (grade &gt;= {_esc(PIE_MIN_GRADE)}) · "
            "<i>no PCS plans passed liquidity/credit filters.</i></p>"
        )

    cols = PCS_TABLE_COLS
    head = "".join(f"<th align='left'>{_esc(c)}</th>" for c in cols)
    body = []
    for r in rows:
        tds = "".join(f"<td>{_esc(_fmt_cell(c, r.get(c)))}</td>" for c in cols)
        body.append(f"<tr>{tds}</tr>")

    table = (
        "<table border='1' cellspacing='0' cellpadding='4' style='border-collapse:collapse;font-family:ui-monospace,monospace;font-size:13px'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )
    return (
        f"<p><b>PUT CREDIT SPREAD PLAN</b> (pie_analyze_swing funnel) — "
        f"{scanned} scanned, {buys} BUY, {len(rows)} PCS for {_pcs_session_label()}.</p>"
        f"{table}"
        "<p style='font-size:11px;color:#666'>Estimates only — verify chain before trading.</p>"
    )
