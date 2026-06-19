"""
PMCC position lifecycle — long LEAP + short call management.

positions.json shape (pmcc array):
  {
    "pmcc": [{
      "symbol": "PLTR",
      "long_call": 20.0,
      "long_expiration": "2028-01-21",
      "long_debit": 22.50,
      "entry_date": "2026-03-01",
      "contracts": 2,
      "short_call": 28.0,
      "short_expiration": "2026-07-18",
      "short_credit": 0.85,
      "short_entry_date": "2026-06-10"
    }]
  }

Short call: close at PMCC_SHORT_PROFIT_TARGET (50%), roll if challenged.
Long LEAP: hold; flag if price below 200 DMA.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from html import escape as _esc
from typing import Any, Dict, List

import yfinance as yf
import pandas as pd

from .pmcc_common import (
    PMCC_SHORT_PROFIT_TARGET,
    call_row_for_strike,
    determine_short_call_phase,
    is_pmcc_highlight_action,
    is_pmcc_urgent_action,
    mid_price,
    short_call_action_for_phase,
)
from .position_metrics import format_weak_symbols_html, get_position_price_metrics

logger = logging.getLogger(__name__)

POSITIONS_BLOB_NAME = os.getenv("PMCC_POSITIONS_BLOB_NAME", os.getenv("PCS_POSITIONS_BLOB_NAME", "positions.json"))


def load_pmcc_positions() -> List[dict]:
    js: dict | None = None

    try:
        from local_list_utils import LOCAL_LIST_CONTAINER, _get_named_blob_client

        blob = _get_named_blob_client(LOCAL_LIST_CONTAINER, POSITIONS_BLOB_NAME)
        data = blob.download_blob().readall()
        js = json.loads(data.decode("utf-8", errors="ignore"))
        logger.info("[pmcc_lifecycle] loaded from %s/%s", LOCAL_LIST_CONTAINER, POSITIONS_BLOB_NAME)
    except Exception as e:
        logger.info("[pmcc_lifecycle] no positions blob (%s); trying local", e)

    if js is None:
        local = os.getenv("PMCC_POSITIONS_FILE", os.getenv("PCS_POSITIONS_FILE", ""))
        if local and os.path.isfile(local):
            try:
                with open(local, encoding="utf-8") as f:
                    js = json.loads(f.read())
            except Exception as e:
                logger.warning("[pmcc_lifecycle] failed to read %s: %s", local, e)

    if js is None:
        return []

    return list(js.get("pmcc") or [])


def _dma200_map(symbols: List[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if not symbols:
        return out
    try:
        import yfinance as yf
        from datetime import timedelta

        end = datetime.today()
        start = end - timedelta(days=280)
        data = yf.download(symbols, start=start, end=end, auto_adjust=True, progress=False)
        if data is None or data.empty:
            return out
        close = data["Close"]
        if isinstance(close, pd.Series):
            s = close.dropna()
            if len(s) >= 200:
                out[symbols[0]] = float(s.rolling(200).mean().iloc[-1])
            return out
        for sym in symbols:
            if sym not in close.columns:
                continue
            s = close[sym].dropna()
            if len(s) >= 200:
                out[sym] = float(s.rolling(200).mean().iloc[-1])
    except Exception as e:
        logger.info("[pmcc_lifecycle] dma200 fetch failed: %s", e)
    return out


def _dte(expiry: str) -> int:
    try:
        d = datetime.strptime(str(expiry), "%Y-%m-%d").date()
    except Exception:
        return 0
    return (d - datetime.today().date()).days


def review_pmcc_positions(positions: List[dict]) -> List[dict]:
    if not positions:
        return []

    syms = [str(p.get("symbol", "")).upper().strip() for p in positions if p.get("symbol")]
    metrics = get_position_price_metrics(syms)
    dma200_by_sym = _dma200_map(syms)
    rows = []

    for pos in positions:
        sym = str(pos.get("symbol", "")).upper().strip()
        if not sym:
            continue

        long_k = float(pos.get("long_call") or 0.0)
        long_exp = str(pos.get("long_expiration", ""))
        long_debit = float(pos.get("long_debit") or 0.0)
        short_k = float(pos.get("short_call") or 0.0)
        short_exp = str(pos.get("short_expiration", ""))
        short_credit = float(pos.get("short_credit") or 0.0)
        contracts = int(pos.get("contracts") or 1)

        m = metrics.get(sym, {})
        price = m.get("last", float("nan"))
        dma200 = dma200_by_sym.get(sym, float("nan"))

        long_dte = _dte(long_exp)
        short_dte = _dte(short_exp)

        long_value = float("nan")
        short_cost = float("nan")
        short_profit_pct = float("nan")

        try:
            tk = yf.Ticker(sym)
            opts = tk.options or []

            if long_exp in opts:
                long_row = call_row_for_strike(tk.option_chain(long_exp).calls, long_k)
                if long_row is not None:
                    long_value = mid_price(long_row)

            if short_exp in opts and short_k > 0:
                short_row = call_row_for_strike(tk.option_chain(short_exp).calls, short_k)
                if short_row is not None:
                    short_cost = mid_price(short_row)
        except Exception as e:
            logger.info("[pmcc_lifecycle] chain failed %s: %s", sym, e)

        profit_known = short_cost == short_cost and short_credit > 0
        if profit_known:
            short_profit_pct = ((short_credit - short_cost) / short_credit * 100.0)

        if short_k <= 0 or short_credit <= 0:
            short_phase = "NO_SHORT"
            short_action = short_call_action_for_phase(short_phase)
        elif short_dte < 0:
            short_phase = "EXPIRING"
            short_action = short_call_action_for_phase("EXPIRING", verify_suffix=" (expired — check assignment)")
        else:
            short_phase = determine_short_call_phase(
                dte=short_dte,
                profit_pct=short_profit_pct if profit_known else float("nan"),
                spot=float(price) if price == price else float("nan"),
                short_strike=short_k,
                profit_known=profit_known,
            )
            suffix = "" if profit_known else " (verify $ before close)"
            short_action = short_call_action_for_phase(short_phase, verify_suffix=suffix)

        long_pnl_pct = float("nan")
        if long_debit > 0 and long_value == long_value:
            long_pnl_pct = ((long_value - long_debit) / long_debit * 100.0)

        long_action = "HOLD LEAP"
        if price == price and dma200 == dma200 and price < dma200:
            long_action = "WATCH LEAP (below 200 DMA)"
        if long_dte < 180:
            long_action = "REVIEW LEAP (DTE < 6mo — roll LEAP?)"

        combined_action = short_action
        if "WATCH" in long_action or "REVIEW" in long_action:
            combined_action = f"{short_action}; {long_action}"

        rows.append({
            "Ticker": sym,
            "Price": round(price, 2) if price == price else None,
            "Contracts": contracts,
            "LongExp": long_exp,
            "LongDTE": long_dte,
            "LongStrike": long_k,
            "LongDebit": round(long_debit, 2),
            "LongMark": round(long_value, 2) if long_value == long_value else None,
            "LongPnL%": round(long_pnl_pct, 1) if long_pnl_pct == long_pnl_pct else None,
            "ShortExp": short_exp or "—",
            "ShortDTE": short_dte if short_k > 0 else None,
            "ShortStrike": short_k if short_k > 0 else None,
            "ShortCredit": round(short_credit, 2) if short_credit > 0 else None,
            "ShortCost": round(short_cost, 2) if short_cost == short_cost else None,
            "ShortProfit%": round(short_profit_pct, 1) if short_profit_pct == short_profit_pct else None,
            "ShortPhase": short_phase,
            "Action": combined_action,
        })

    return rows


def run_pmcc_lifecycle() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "enabled": True,
        "found": False,
        "html": "",
        "actionable": [],
        "rows": [],
    }

    if os.getenv("PMCC_LIFECYCLE_ENABLED", "1") != "1":
        out["enabled"] = False
        return out

    positions = load_pmcc_positions()
    if not positions:
        out["html"] = (
            "<p><i>No PMCC positions in positions.json — add a "
            "<code>pmcc</code> array with long LEAP + short call legs.</i></p>"
        )
        return out

    out["found"] = True
    rows = review_pmcc_positions(positions)
    out["rows"] = rows

    actionable = sorted({
        r["Ticker"] for r in rows if is_pmcc_urgent_action(r.get("Action", ""))
    })
    out["actionable"] = actionable
    out["html"] = format_pmcc_lifecycle_email_section(rows)
    return out


PMCC_COLS = [
    "Ticker",
    "Price",
    "LongExp",
    "LongDTE",
    "LongStrike",
    "LongMark",
    "LongPnL%",
    "ShortExp",
    "ShortDTE",
    "ShortStrike",
    "ShortCredit",
    "ShortCost",
    "ShortProfit%",
    "Action",
]


def _table(rows: List[dict], cols: List[str]) -> str:
    if not rows:
        return "<p><i>None.</i></p>"

    head = "".join(f"<th align='left'>{_esc(c)}</th>" for c in cols)
    body = []
    for r in rows:
        act = str(r.get("Action", ""))
        hl = " style='background:#fff4e5'" if is_pmcc_highlight_action(act) else ""
        tds = "".join(
            f"<td>{_esc('' if r.get(c) is None else str(r.get(c)))}</td>"
            for c in cols
        )
        body.append(f"<tr{hl}>{tds}</tr>")

    return (
        "<table border='0' cellspacing='0' cellpadding='4' style='font-size:13px'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def format_pmcc_lifecycle_email_section(rows: List[dict]) -> str:
    if not rows:
        return "<p><i>No PMCC positions to review.</i></p>"

    symbols = [r["Ticker"] for r in rows]
    weak_block = format_weak_symbols_html(symbols, "PMCC positions — price watch")

    actionable = sorted({
        r["Ticker"] for r in rows if is_pmcc_urgent_action(r.get("Action", ""))
    })
    summary = ""
    if actionable:
        summary = f"<p><b>Needs action:</b> {_esc(', '.join(actionable))}</p>"

    return "".join([
        summary,
        weak_block,
        "<p style='font-size:11px;color:#666'>"
        f"Short call: close at ≥{PMCC_SHORT_PROFIT_TARGET:g}% profit; roll if challenged. "
        "Long LEAP: hold unless below 200 DMA or LEAP DTE &lt; 6 months."
        "</p>",
        "<p><b>PMCC open positions</b></p>",
        _table(rows, PMCC_COLS),
    ])


def format_pmcc_lifecycle_text(rows: List[dict]) -> str:
    if not rows:
        return "  (no PMCC positions in positions.json)"

    lines: List[str] = []
    actionable = sorted({
        r["Ticker"] for r in rows if is_pmcc_urgent_action(r.get("Action", ""))
    })
    if actionable:
        lines.append(f"  Needs action: {', '.join(actionable)}")

    for r in rows:
        lines.append(
            f"    {r.get('Ticker','')} price={r.get('Price','')} "
            f"LEAP {r.get('LongExp','')} {r.get('LongStrike','')} "
            f"mark={r.get('LongMark','')} pnl={r.get('LongPnL%','')}% | "
            f"short {r.get('ShortExp','')} {r.get('ShortStrike','')} "
            f"cr={r.get('ShortCredit','')} cost={r.get('ShortCost','')} "
            f"profit={r.get('ShortProfit%','')}% -> {r.get('Action','')}"
        )
    return "\n".join(lines)
