"""
PCS / swing position lifecycle for the daily email.

Reads held positions from blob signals/positions.json or PCS_POSITIONS_FILE.

positions.json shape:
  {
    "swings":  [{"symbol","entry_price","entry_date","shares","stop_price"}],
    "spreads": [{"symbol","short_put","long_put","expiration","credit","entry_date"}]
  }

Env:
  PCS_LIFECYCLE_ENABLED   default 1
  PCS_POSITIONS_BLOB_NAME default positions.json
  PCS_POSITIONS_FILE      local fallback path
  PCS_PROFIT_TARGET       default 50
  PCS_STOP_LOSS           default -100
  PCS_ROLL_DTE            default 14
  PCS_MANAGE_DTE          default 21
  PCS_TRAIL_STOP_PCT      default 0.15
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from html import escape as _esc
from typing import Any, Dict, List

import yfinance as yf

from .pcs_common import (
    MANAGE_DTE,
    PROFIT_TARGET,
    ROLL_DTE,
    STOP_LOSS,
    determine_pcs_phase_fallback,
    determine_pcs_phase_live,
    is_highlight_action,
    is_urgent_action,
    pcs_action_for_phase,
    pcs_buffer_pct,
    put_row_for_strike,
    spread_mid_cost,
)
from .position_metrics import (
    format_weak_symbols_html,
    get_position_price_metrics,
)

logger = logging.getLogger(__name__)

TRAIL_STOP_PCT = float(os.getenv("PCS_TRAIL_STOP_PCT", "0.15"))

POSITIONS_BLOB_NAME = os.getenv("PCS_POSITIONS_BLOB_NAME", "positions.json")


def load_positions() -> Dict[str, list] | None:
    """Return positions dict, or None if no positions source is found."""
    try:
        from local_list_utils import LOCAL_LIST_CONTAINER, _get_named_blob_client

        blob = _get_named_blob_client(LOCAL_LIST_CONTAINER, POSITIONS_BLOB_NAME)
        data = blob.download_blob().readall()
        js = json.loads(data.decode("utf-8", errors="ignore"))

        logger.info(
            "[pcs_lifecycle] loaded positions from %s/%s",
            LOCAL_LIST_CONTAINER,
            POSITIONS_BLOB_NAME,
        )

        return {
            "swings": list(js.get("swings") or []),
            "spreads": list(js.get("spreads") or []),
        }

    except Exception as e:
        logger.info("[pcs_lifecycle] no positions blob (%s); trying local fallback", e)

    local = os.getenv("PCS_POSITIONS_FILE", "")
    if local and os.path.isfile(local):
        try:
            with open(local, encoding="utf-8") as f:
                js = json.loads(f.read())

            return {
                "swings": list(js.get("swings") or []),
                "spreads": list(js.get("spreads") or []),
            }

        except Exception as e:
            logger.warning("[pcs_lifecycle] failed to read %s: %s", local, e)

    logger.info("[pcs_lifecycle] positions.json not found; skipping")
    return None


def determine_swing_phase(days_held: int, return_pct: float) -> str:
    if return_pct >= 25:
        return "TRAIL"
    if days_held >= 60:
        return "REVIEW"
    if days_held >= 30:
        return "MANAGE"
    if days_held >= 10:
        return "HOLD"
    return "WATCH"


def _days_since(date_str: str) -> int:
    try:
        d = datetime.strptime(str(date_str), "%Y-%m-%d").date()
    except Exception:
        return 0
    return (datetime.today().date() - d).days


def _dte(expiry: str) -> int:
    try:
        d = datetime.strptime(str(expiry), "%Y-%m-%d").date()
    except Exception:
        return 0
    return (d - datetime.today().date()).days


def _mid(opt_row) -> float:
    bid = float(opt_row.get("bid") or 0.0)
    ask = float(opt_row.get("ask") or 0.0)

    if bid > 0 and ask > 0 and ask >= bid:
        return (bid + ask) / 2.0

    return float(opt_row.get("lastPrice") or 0.0)


def review_swings(swings: List[dict]) -> List[dict]:
    if not swings:
        return []

    syms = [str(s.get("symbol", "")).upper().strip() for s in swings if s.get("symbol")]
    metrics = get_position_price_metrics(syms)

    rows = []

    for pos in swings:
        sym = str(pos.get("symbol", "")).upper().strip()
        if not sym:
            continue

        entry = float(pos.get("entry_price") or 0.0)
        stored_stop = float(pos.get("stop_price") or 0.0)

        m = metrics.get(sym, {})
        price = m.get("last", float("nan"))

        days_held = _days_since(pos.get("entry_date", ""))

        return_pct = (
            ((price - entry) / entry * 100.0)
            if entry > 0 and price == price
            else 0.0
        )

        phase = determine_swing_phase(days_held, return_pct)

        trail_stop = price * (1.0 - TRAIL_STOP_PCT) if price == price else float("nan")
        suggested_stop = max(stored_stop, trail_stop) if trail_stop == trail_stop else stored_stop

        if price == price and stored_stop > 0 and price <= stored_stop:
            action = "STOP HIT -> EXIT"
        elif phase == "TRAIL":
            action = "RAISE STOP (trail winner)"
        elif phase == "REVIEW":
            action = "REVIEW (held 60d+)"
        elif suggested_stop > stored_stop:
            action = "RAISE STOP"
        else:
            action = "HOLD"

        rows.append(
            {
                "Ticker": sym,
                "Price": round(price, 2) if price == price else None,
                "Entry": round(entry, 2),
                "Ret%": round(return_pct, 2),
                "Days": days_held,
                "Stop": round(stored_stop, 2),
                "SuggestedStop": round(suggested_stop, 2) if suggested_stop == suggested_stop else None,
                "Phase": phase,
                "Action": action,
            }
        )

    return rows


def review_spreads(spreads: List[dict]) -> List[dict]:
    if not spreads:
        return []

    syms = [str(s.get("symbol", "")).upper().strip() for s in spreads if s.get("symbol")]
    metrics = get_position_price_metrics(syms)

    rows = []

    for pos in spreads:
        sym = str(pos.get("symbol", "")).upper().strip()
        if not sym:
            continue

        expiry = str(pos.get("expiration", ""))
        short_k = float(pos.get("short_put") or 0.0)
        long_k = float(pos.get("long_put") or 0.0)
        credit0 = float(pos.get("credit") or 0.0)
        width = short_k - long_k

        dte = _dte(expiry)

        m = metrics.get(sym, {})
        price = m.get("last", float("nan"))

        cur_cost = float("nan")
        profit_pct = float("nan")
        buffer_pct = pcs_buffer_pct(float(price), short_k)

        phase = "UNKNOWN"
        action = "VERIFY MANUALLY"

        if dte < 0:
            phase = "EXPIRED"
            action = pcs_action_for_phase(phase)

        elif width <= 0 or credit0 <= 0:
            phase = "BAD DATA"
            action = pcs_action_for_phase(phase)

        else:
            try:
                tk = yf.Ticker(sym)
                if expiry in (tk.options or []):
                    puts = tk.option_chain(expiry).puts
                    cur_cost = spread_mid_cost(puts, short_k, long_k, _mid)
            except Exception as e:
                logger.info("[pcs_lifecycle] option pricing failed for %s %s: %s", sym, expiry, e)

            profit_known = cur_cost == cur_cost and cur_cost >= 0
            safe_buffer = buffer_pct if buffer_pct == buffer_pct else 0.0

            if profit_known:
                profit_pct = ((credit0 - cur_cost) / credit0 * 100.0)
                phase = determine_pcs_phase_live(
                    dte=dte,
                    profit_pct=profit_pct,
                    buffer_pct=safe_buffer,
                )
                action = pcs_action_for_phase(phase)
            elif safe_buffer == safe_buffer:
                phase = determine_pcs_phase_fallback(dte, safe_buffer)
                action = pcs_action_for_phase(phase, verify_suffix=" (verify $ before close)")

        rows.append(
            {
                "Ticker": sym,
                "Price": round(price, 2) if price == price else None,
                "Expiry": expiry,
                "DTE": dte,
                "Short": short_k,
                "Long": long_k,
                "Width": round(width, 2),
                "Credit": round(credit0, 2),
                "CurCost": round(cur_cost, 2) if cur_cost == cur_cost else None,
                "Profit%": round(profit_pct, 1) if profit_pct == profit_pct else None,
                "Buffer%": round(buffer_pct, 1) if buffer_pct == buffer_pct else None,
                "Phase": phase,
                "Action": action,
            }
        )

    return rows


def _is_action(action: str) -> bool:
    return is_highlight_action(action)


def _is_urgent(action: str) -> bool:
    return is_urgent_action(action)


def run_pcs_lifecycle() -> Dict[str, Any]:
    """Returns {enabled, html, actionable, swing_rows, pcs_rows}."""
    out: Dict[str, Any] = {
        "enabled": True,
        "found": False,
        "html": "",
        "actionable": [],
        "swing_rows": [],
        "pcs_rows": [],
    }

    if os.getenv("PCS_LIFECYCLE_ENABLED", "1") != "1":
        out["enabled"] = False
        return out

    positions = load_positions()

    if positions is None:
        out["html"] = (
            "<p><i>No positions.json found — upload to signals/positions.json "
            "or set PCS_POSITIONS_FILE.</i></p>"
        )
        return out

    out["found"] = True

    swing_rows = review_swings(positions.get("swings", []))
    pcs_rows = review_spreads(positions.get("spreads", []))

    out["swing_rows"] = swing_rows
    out["pcs_rows"] = pcs_rows

    actionable = sorted(
        set(
            [r["Ticker"] for r in swing_rows if _is_urgent(r["Action"])]
            + [r["Ticker"] for r in pcs_rows if _is_urgent(r["Action"])]
        )
    )

    out["actionable"] = actionable
    out["html"] = format_pcs_lifecycle_email_section(swing_rows, pcs_rows)

    return out


def _table(rows: List[dict], cols: List[str]) -> str:
    if not rows:
        return "<p><i>None.</i></p>"

    head = "".join(f"<th align='left'>{_esc(c)}</th>" for c in cols)

    body = []
    for r in rows:
        act = str(r.get("Action", ""))
        hl = " style='background:#fff4e5'" if _is_action(act) else ""

        tds = "".join(
            f"<td>{_esc('' if r.get(c) is None else str(r.get(c)))}</td>"
            for c in cols
        )

        body.append(f"<tr{hl}>{tds}</tr>")

    return (
        "<table border='0' cellspacing='0' cellpadding='4' style='font-size:13px'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


SWING_COLS = [
    "Ticker",
    "Price",
    "Entry",
    "Ret%",
    "Days",
    "Stop",
    "SuggestedStop",
    "Phase",
    "Action",
]

PCS_COLS = [
    "Ticker",
    "Expiry",
    "DTE",
    "Short",
    "Long",
    "Width",
    "Credit",
    "CurCost",
    "Profit%",
    "Buffer%",
    "Phase",
    "Action",
]


def format_pcs_lifecycle_email_section(swing_rows: List[dict], pcs_rows: List[dict]) -> str:
    if not swing_rows and not pcs_rows:
        return "<p><i>No tracked positions found in positions.json.</i></p>"

    symbols = [r["Ticker"] for r in swing_rows] + [r["Ticker"] for r in pcs_rows]

    weak_block = format_weak_symbols_html(
        symbols,
        "Open positions — price watch",
    )

    actionable = sorted(
        set(
            [r["Ticker"] for r in swing_rows if _is_urgent(r["Action"])]
            + [r["Ticker"] for r in pcs_rows if _is_urgent(r["Action"])]
        )
    )

    summary = ""
    if actionable:
        summary = f"<p><b>Needs action:</b> {_esc(', '.join(actionable))}</p>"

    parts = [
        summary,
        weak_block,
        "<p style='font-size:11px;color:#666'>"
        "Price watch: down today / down week / below 20-DMA. "
        "Highlighted rows = lifecycle action. "
        "PCS Profit% from live option chain; Buffer% = (price − short) / price. "
        f"Exit ≥{PROFIT_TARGET:g}% profit · stop ≤{STOP_LOSS:g}% · roll &lt;{ROLL_DTE}DTE · manage ≤{MANAGE_DTE}DTE."
        "</p>",
    ]

    if pcs_rows:
        parts.append("<p><b>Put credit spreads — exits &amp; management</b></p>" + _table(pcs_rows, PCS_COLS))

    if swing_rows:
        parts.append("<p><b>Swing positions review</b></p>" + _table(swing_rows, SWING_COLS))

    return "".join(parts)


def format_pcs_lifecycle_text(swing_rows: List[dict], pcs_rows: List[dict]) -> str:
    if not swing_rows and not pcs_rows:
        return "  (no open positions in positions.json)"

    lines: List[str] = []

    actionable = sorted(
        set(
            [r["Ticker"] for r in swing_rows if _is_urgent(r["Action"])]
            + [r["Ticker"] for r in pcs_rows if _is_urgent(r["Action"])]
        )
    )

    if actionable:
        lines.append(f"  Needs action: {', '.join(actionable)}")

    if pcs_rows:
        lines.append("  Put credit spreads:")
        for r in pcs_rows:
            lines.append(
                f"    {r.get('Ticker','')} {r.get('Expiry','')} DTE={r.get('DTE','')} "
                f"short={r.get('Short','')} long={r.get('Long','')} "
                f"credit={r.get('Credit','')} curCost={r.get('CurCost','')} "
                f"profit={r.get('Profit%','')}% buffer={r.get('Buffer%','')}% "
                f"phase={r.get('Phase','')} -> {r.get('Action','')}"
            )

    if swing_rows:
        lines.append("  Swings:")
        for r in swing_rows:
            lines.append(
                f"    {r.get('Ticker','')} ret={r.get('Ret%','')}% days={r.get('Days','')} "
                f"stop={r.get('Stop','')} suggestedStop={r.get('SuggestedStop','')} "
                f"phase={r.get('Phase','')} -> {r.get('Action','')}"
            )

    return "\n".join(lines)