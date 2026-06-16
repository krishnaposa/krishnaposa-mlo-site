"""
PCS entry ideas for daily email.

Scans tickers from:
  1. PIE_TICKERS_FILE
  2. Azure blob my_tickers.txt
  3. local_list + holdings_list fallback

Then:
  ticker universe -> pie scanner -> Grade A/B and Grade C groups -> option chain -> PCS plans.

Important:
  Credit% = credit / spread width.
  This is NOT true probability of profit.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from html import escape as _esc
from typing import Any, Dict, List, Optional

import yfinance as yf

from .pie_scanner import run_scan

logger = logging.getLogger(__name__)

PIE_TICKERS_BLOB = os.getenv("PIE_TICKERS_BLOB", "my_tickers.txt")
PIE_TICKERS_FILE = os.getenv("PIE_TICKERS_FILE", "").strip()

PIE_TARGET_DTE = int(os.getenv("PIE_TARGET_DTE", "35"))
PIE_OTM_PCT = float(os.getenv("PIE_OTM_PCT", "0.06"))
PIE_SPREAD_WIDTH_PCT = float(os.getenv("PIE_SPREAD_WIDTH_PCT", "0.03"))
PIE_MAX_PCS_CANDIDATES = int(os.getenv("PIE_MAX_PCS_CANDIDATES", "12"))

MIN_OPEN_INTEREST = int(os.getenv("PCS_MIN_OPEN_INTEREST", "100"))
MAX_SPREAD_PCT = float(os.getenv("PCS_MAX_SPREAD_PCT", "20"))
MIN_CREDIT_WIDTH = float(os.getenv("PCS_MIN_CREDIT_WIDTH", "0.10"))

PCS_MIN_WIDTH = float(os.getenv("PCS_MIN_WIDTH", "1"))
PCS_MAX_WIDTH = float(os.getenv("PCS_MAX_WIDTH", "10"))


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
    credit_width_pct: float
    otm_pct: float
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
        from local_list_utils import LOCAL_LIST_CONTAINER, _get_named_blob_client

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
    if bid <= 0 or ask <= 0 or ask < bid:
        return False

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
    if not symbol or price <= 0:
        return None

    tk = yf.Ticker(symbol)

    try:
        expiries = list(tk.options or [])
    except Exception as e:
        logger.info("[pcs_opportunities] %s options unavailable: %s", symbol, e)
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
    except Exception as e:
        logger.info("[pcs_opportunities] %s option_chain failed for %s: %s", symbol, expiry, e)
        return None

    if puts is None or puts.empty:
        return None

    puts = puts.sort_values("strike")

    liquid = puts[
        puts.apply(
            lambda r: _leg_is_liquid(r, min_oi=MIN_OPEN_INTEREST, max_spread_pct=MAX_SPREAD_PCT),
            axis=1,
        )
    ]

    if liquid.empty:
        return None

    short_candidates = liquid[liquid["strike"] <= price * (1.0 - otm_pct)]
    if short_candidates.empty:
        return None

    short_row = short_candidates.iloc[-1]
    short_strike = float(short_row["strike"])

    target_long = short_strike * (1.0 - spread_width_pct)
    long_candidates = liquid[liquid["strike"] <= target_long]

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

    if width < PCS_MIN_WIDTH or width > PCS_MAX_WIDTH:
        return None

    credit = _mid_price(short_row) - _mid_price(long_row)

    if credit <= 0:
        return None

    credit_width_pct = credit / width

    if credit_width_pct < MIN_CREDIT_WIDTH:
        return None

    max_risk = width - credit
    if max_risk <= 0:
        return None

    iv_pct = float(short_row.get("impliedVolatility") or 0.0) * 100.0
    actual_otm_pct = ((price - short_strike) / price * 100.0) if price > 0 else 0.0

    return PutCreditSpread(
        symbol=symbol,
        expiration=expiry,
        dte=dte,
        short_put=round(short_strike, 2),
        long_put=round(long_strike, 2),
        width=round(width, 2),
        credit=round(credit, 2),
        max_risk=round(max_risk, 2),
        credit_width_pct=round(credit_width_pct, 3),
        otm_pct=round(actual_otm_pct, 1),
        iv_pct=round(iv_pct, 1),
    )


def _row_from_plan(plan: PutCreditSpread, grade: str) -> dict:
    return {
        "Ticker": plan.symbol,
        "Grade": grade,
        "Expiry": plan.expiration,
        "DTE": plan.dte,
        "Short": plan.short_put,
        "Long": plan.long_put,
        "Width": plan.width,
        "Credit": plan.credit,
        "MaxRisk": plan.max_risk,
        "Credit%": plan.credit_width_pct,
        "OTM%": plan.otm_pct,
        "IV%": plan.iv_pct,
    }


def _build_rows_from_scan(scan_group, label: str) -> List[dict]:
    rows: List[dict] = []

    for _, row in scan_group.head(PIE_MAX_PCS_CANDIDATES).iterrows():
        sym = str(row["Ticker"]).upper().strip()
        price = float(row["Price"])
        grade = str(row.get("Grade", label)).upper().strip()

        plan = build_pcs_plan(sym, price)
        if plan is None:
            continue

        rows.append(_row_from_plan(plan, grade))

    return rows


def run_pcs_opportunities() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "enabled": True,
        "html": "",
        "tickers": [],
        "rows": [],
        "rows_b": [],
        "rows_c": [],
    }

    if os.getenv("PCS_OPPORTUNITIES_ENABLED", "1") != "1":
        out["enabled"] = False
        return out

    tickers = load_pie_scan_tickers()

    if not tickers:
        out["scanned"] = 0
        out["grade_b_count"] = 0
        out["grade_c_count"] = 0
        hint = (
            f"<code>{_esc(PIE_TICKERS_BLOB)}</code> to signals container, "
            "set PIE_TICKERS_FILE, or populate local_list."
        )
        out["html"] = f"<p><i>No scan tickers — upload {hint}</i></p>"
        return out

    scan = run_scan(tickers)

    grade_b = scan[scan["Grade"].isin(["A", "B"])].copy()
    grade_c = scan[scan["Grade"] == "C"].copy()

    rows_b = _build_rows_from_scan(grade_b, "B")
    rows_c = _build_rows_from_scan(grade_c, "C")

    rows_all = rows_b + rows_c

    out["rows_b"] = rows_b
    out["rows_c"] = rows_c
    out["rows"] = rows_all
    out["tickers"] = [r["Ticker"] for r in rows_all]
    out["scanned"] = len(tickers)
    out["grade_b_count"] = len(grade_b)
    out["grade_c_count"] = len(grade_c)
    out["html"] = format_pcs_opportunities_html(
        rows_b,
        rows_c,
        scanned=len(tickers),
        grade_b_count=len(grade_b),
        grade_c_count=len(grade_c),
    )

    return out


PCS_TABLE_COLS = [
    "Ticker",
    "Grade",
    "Expiry",
    "DTE",
    "Short",
    "Long",
    "Width",
    "Credit",
    "MaxRisk",
    "Credit%",
    "OTM%",
    "IV%",
]


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

    if col == "Credit%":
        try:
            return f"{float(val) * 100.0:.1f}%"
        except (TypeError, ValueError):
            return str(val)

    if col in ("OTM%", "IV%"):
        try:
            return f"{float(val):.1f}"
        except (TypeError, ValueError):
            return str(val)

    return str(val)


def _pcs_session_label() -> str:
    return (os.getenv("PCS_SESSION_LABEL") or "next session").strip() or "next session"


def _format_table(rows: List[dict]) -> str:
    if not rows:
        return "<p><i>None passed option-chain liquidity/credit filters.</i></p>"

    cols = PCS_TABLE_COLS
    head = "".join(f"<th align='left'>{_esc(c)}</th>" for c in cols)

    body = []
    for r in rows:
        tds = "".join(f"<td>{_esc(_fmt_cell(c, r.get(c)))}</td>" for c in cols)
        body.append(f"<tr>{tds}</tr>")

    return (
        "<table border='1' cellspacing='0' cellpadding='4' "
        "style='border-collapse:collapse;font-family:ui-monospace,monospace;font-size:13px'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def format_pcs_opportunities_html(
    rows_b: List[dict],
    rows_c: List[dict],
    *,
    scanned: int,
    grade_b_count: int,
    grade_c_count: int,
) -> str:
    total_rows = len(rows_b) + len(rows_c)

    if total_rows == 0:
        return (
            f"<p>Scanned {scanned} symbols · "
            f"{grade_b_count} Grade A/B · {grade_c_count} Grade C · "
            "<i>no PCS plans passed option-chain liquidity/credit filters.</i></p>"
        )

    return (
        f"<p><b>PUT CREDIT SPREAD PLAN</b> — "
        f"{scanned} scanned, {grade_b_count} Grade A/B, {grade_c_count} Grade C, "
        f"{total_rows} PCS for {_pcs_session_label()}.</p>"

        "<p><b>Grade A/B PCS Candidates</b></p>"
        f"{_format_table(rows_b)}"

        "<p><b>Grade C PCS Candidates</b></p>"
        f"{_format_table(rows_c)}"

        "<p style='font-size:11px;color:#666'>"
        "Grade A/B = stronger setup. Grade C = secondary/watchlist setup. "
        "Credit% = credit / spread width. This is not true POP. "
        "Estimates only — verify option chain, bid/ask, earnings, and liquidity before trading."
        "</p>"
    )


def format_pcs_opportunities_text(
    rows_b: List[dict],
    rows_c: List[dict],
    *,
    scanned: int,
    grade_b_count: int,
    grade_c_count: int,
) -> str:
    lines = [
        f"Scanned {scanned} symbols · {grade_b_count} Grade A/B · {grade_c_count} Grade C",
        "",
        "Grade A/B PCS Candidates:",
    ]

    def add_rows(rows: List[dict]) -> None:
        if not rows:
            lines.append("  None passed filters.")
            return

        for r in rows:
            lines.append(
                f"  {r.get('Ticker','')} Grade={r.get('Grade','')} "
                f"Exp={r.get('Expiry','')} DTE={r.get('DTE','')} "
                f"Short={r.get('Short','')} Long={r.get('Long','')} "
                f"Credit={r.get('Credit','')} Credit%={_fmt_cell('Credit%', r.get('Credit%'))} "
                f"OTM%={r.get('OTM%','')} IV%={r.get('IV%','')}"
            )

    add_rows(rows_b)

    lines.append("")
    lines.append("Grade C PCS Candidates:")
    add_rows(rows_c)

    lines.append("")
    lines.append("Estimates only — verify option chain, bid/ask, earnings, and liquidity before trading.")

    return "\n".join(lines)