"""
PCS / swing position lifecycle for the daily email.

Self-contained (mirrors scripts/stocks/pie_analyze_swing.py lifecycle) so the
Azure function app can run without depending on the scripts/ folder.

Reads held positions from blob ``signals/positions.json`` (or PCS_POSITIONS_FILE
local fallback), prices them with yfinance, classifies each into a phase, and
renders an HTML section for send_email_report_with_sims().

positions.json shape:
  {
    "swings":  [{"symbol","entry_price","entry_date","shares","stop_price"}],
    "spreads": [{"symbol","short_put","long_put","expiration","credit","entry_date"}]
  }

Env:
  PCS_LIFECYCLE_ENABLED   default 1
  PCS_POSITIONS_BLOB_NAME default positions.json   (container = signals)
  PCS_POSITIONS_FILE      local fallback path if blob missing
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

import pandas as pd
import yfinance as yf

from .position_metrics import (
    format_weak_symbols_html,
    get_position_price_metrics,
)

logger = logging.getLogger(__name__)

PROFIT_TARGET = float(os.getenv("PCS_PROFIT_TARGET", "50"))
STOP_LOSS = float(os.getenv("PCS_STOP_LOSS", "-100"))
ROLL_DTE = int(os.getenv("PCS_ROLL_DTE", "14"))
ROLL_BUFFER = float(os.getenv("PCS_ROLL_BUFFER", "3"))
MANAGE_DTE = int(os.getenv("PCS_MANAGE_DTE", "21"))
TRAIL_STOP_PCT = float(os.getenv("PCS_TRAIL_STOP_PCT", "0.15"))

POSITIONS_BLOB_NAME = os.getenv("PCS_POSITIONS_BLOB_NAME", "positions.json")


# ------------------------------------------------------------------
# Positions source (blob with local fallback)
# ------------------------------------------------------------------

def load_positions() -> Dict[str, list] | None:
    """Return positions dict, or None if no positions source is found (skip lifecycle)."""
    # 1) Blob (signals/positions.json), reusing local_list_utils helpers.
    try:
        from local_list_utils import _get_named_blob_client, LOCAL_LIST_CONTAINER

        blob = _get_named_blob_client(LOCAL_LIST_CONTAINER, POSITIONS_BLOB_NAME)
        data = blob.download_blob().readall()
        js = json.loads(data.decode("utf-8", errors="ignore"))
        logger.info("[pcs_lifecycle] loaded positions from %s/%s",
                    LOCAL_LIST_CONTAINER, POSITIONS_BLOB_NAME)
        return {"swings": list(js.get("swings") or []), "spreads": list(js.get("spreads") or [])}
    except Exception as e:
        logger.info("[pcs_lifecycle] no positions blob (%s); trying local fallback", e)

    # 2) Local file fallback.
    local = os.getenv("PCS_POSITIONS_FILE", "")
    if local and os.path.isfile(local):
        try:
            js = json.loads(open(local, encoding="utf-8").read())
            return {"swings": list(js.get("swings") or []), "spreads": list(js.get("spreads") or [])}
        except Exception as e:
            logger.warning("[pcs_lifecycle] failed to read %s: %s", local, e)

    # No blob and no local file -> skip the lifecycle section entirely.
    logger.info("[pcs_lifecycle] positions.json not found (blob or local); skipping")
    return None


# ------------------------------------------------------------------
# Phase logic (identical thresholds to scripts/stocks)
# ------------------------------------------------------------------

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


def determine_pcs_phase_live(dte: int, profit_pct: float, buffer_pct: float) -> str:
    if profit_pct >= PROFIT_TARGET:
        return "EXIT"
    if profit_pct <= STOP_LOSS:
        return "STOP"
    if buffer_pct < 0:
        return "DEFENSIVE"
    if dte < ROLL_DTE and buffer_pct < ROLL_BUFFER:
        return "ROLL"
    if dte <= MANAGE_DTE:
        return "MANAGE"
    return "OPENED"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _days_since(date_str: str) -> int:
    try:
        d = datetime.strptime(str(date_str), "%Y-%m-%d").date()
    except Exception:
        return 0
    return (datetime.today().date() - d).days


def _mid(opt_row) -> float:
    bid = float(opt_row.get("bid") or 0.0)
    ask = float(opt_row.get("ask") or 0.0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return float(opt_row.get("lastPrice") or 0.0)


# ------------------------------------------------------------------
# Reviews
# ------------------------------------------------------------------

def review_swings(swings: List[dict]) -> List[dict]:
    if not swings:
        return []
    syms = [s.get("symbol", "") for s in swings]
    metrics = get_position_price_metrics(syms)
    rows = []
    for pos in swings:
        sym = str(pos.get("symbol", "")).upper().strip()
        entry = float(pos.get("entry_price") or 0.0)
        stored_stop = float(pos.get("stop_price") or 0.0)
        m = metrics.get(sym, {})
        price = m.get("last", float("nan"))

        days_held = _days_since(pos.get("entry_date", ""))
        return_pct = ((price - entry) / entry * 100.0) if entry > 0 and price == price else 0.0
        phase = determine_swing_phase(days_held, return_pct)

        trail_stop = price * (1.0 - TRAIL_STOP_PCT) if price == price else float("nan")
        suggested_stop = max(stored_stop, trail_stop) if trail_stop == trail_stop else stored_stop

        if price == price and price <= stored_stop:
            action = "STOP HIT -> EXIT"
        elif phase == "TRAIL":
            action = "RAISE STOP (trail winner)"
        elif phase == "REVIEW":
            action = "REVIEW (held 60d+)"
        elif suggested_stop > stored_stop:
            action = "RAISE STOP"
        else:
            action = "HOLD"

        rows.append({
            "Ticker": sym,
            "Price": round(price, 2) if price == price else None,
            "Entry": round(entry, 2),
            "Ret%": round(return_pct, 2),
            "Days": days_held,
            "Stop": round(stored_stop, 2),
            "Phase": phase,
            "Action": action,
        })
    return rows


def review_spreads(spreads: List[dict]) -> List[dict]:
    if not spreads:
        return []
    syms = [s.get("symbol", "") for s in spreads]
    metrics = get_position_price_metrics(syms)
    rows = []
    for pos in spreads:
        sym = str(pos.get("symbol", "")).upper().strip()
        expiry = str(pos.get("expiration", ""))
        short_k = float(pos.get("short_put") or 0.0)
        long_k = float(pos.get("long_put") or 0.0)
        credit0 = float(pos.get("credit") or 0.0)
        width = short_k - long_k

        dte = _days_since(expiry) * -1
        m = metrics.get(sym, {})
        price = m.get("last", float("nan"))
        cur_cost = float("nan")
        try:
            tk = yf.Ticker(sym)
            if expiry in (tk.options or []):
                puts = tk.option_chain(expiry).puts.set_index("strike")
                if short_k in puts.index and long_k in puts.index:
                    cur_cost = _mid(puts.loc[short_k]) - _mid(puts.loc[long_k])
        except Exception:
            pass

        profit_pct = ((credit0 - cur_cost) / credit0 * 100.0) if credit0 > 0 and cur_cost == cur_cost else float("nan")
        buffer_pct = ((price - short_k) / price * 100.0) if price == price and price > 0 else float("nan")
        phase = determine_pcs_phase_live(
            dte=dte,
            profit_pct=profit_pct if profit_pct == profit_pct else 0.0,
            buffer_pct=buffer_pct if buffer_pct == buffer_pct else 0.0,
        )

        action = {
            "EXIT": f"CLOSE (>={PROFIT_TARGET:g}% profit)",
            "STOP": f"CLOSE (stop, <={STOP_LOSS:g}% loss)",
            "DEFENSIVE": "DEFEND (under short)",
            "ROLL": f"ROLL (<{ROLL_DTE}DTE, tight)",
            "MANAGE": f"MANAGE (<={MANAGE_DTE}DTE: close/roll)",
            "OPENED": "HOLD",
        }[phase]

        rows.append({
            "Ticker": sym,
            "Price": round(price, 2) if price == price else None,
            "DTE": dte,
            "Short": short_k,
            "Long": long_k,
            "Profit%": round(profit_pct, 1) if profit_pct == profit_pct else None,
            "Phase": phase,
            "Action": action,
        })
    return rows


def _is_action(action: str) -> bool:
    return not str(action).startswith(("HOLD", "LET DECAY"))


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------

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
        # No positions.json anywhere -> skip the section (html stays empty).
        return out
    out["found"] = True

    swing_rows = review_swings(positions.get("swings", []))
    pcs_rows = review_spreads(positions.get("spreads", []))
    out["swing_rows"] = swing_rows
    out["pcs_rows"] = pcs_rows

    actionable = sorted(set(
        [r["Ticker"] for r in swing_rows if _is_action(r["Action"])]
        + [r["Ticker"] for r in pcs_rows if _is_action(r["Action"])]
    ))
    out["actionable"] = actionable
    out["html"] = format_pcs_lifecycle_email_section(swing_rows, pcs_rows)
    return out


# ------------------------------------------------------------------
# Email rendering
# ------------------------------------------------------------------

def _action_lines(rows: List[dict]) -> str:
    lines = [
        f"<div>{_esc(r['Ticker'])}: {_esc(r['Action'])}</div>"
        for r in rows
        if _is_action(r.get("Action", ""))
    ]
    return "".join(lines) if lines else "<p><i>No position actions today.</i></p>"


def format_pcs_lifecycle_email_section(swing_rows: List[dict], pcs_rows: List[dict]) -> str:
    if not swing_rows and not pcs_rows:
        return "<p><i>No tracked positions (positions.json empty or missing).</i></p>"

    symbols = [r["Ticker"] for r in swing_rows] + [r["Ticker"] for r in pcs_rows]
    weak_block = format_weak_symbols_html(
        symbols,
        "Open positions — weak (down today, down week, below 20-DMA)",
    )

    actionable = sorted(set(
        [r["Ticker"] for r in swing_rows if _is_action(r["Action"])]
        + [r["Ticker"] for r in pcs_rows if _is_action(r["Action"])]
    ))
    summary = ""
    if actionable:
        summary = f"<p><b>Position actions:</b> {_esc(', '.join(actionable))}</p>"

    parts = [
        weak_block,
        summary,
        "<p style='font-size:11px;color:#666'>Weak = all three: lower today, lower vs 5 sessions ago, below 20-DMA.</p>",
    ]
    if swing_rows:
        parts.append("<p><b>Swing — actions</b></p>" + _action_lines(swing_rows))
    if pcs_rows:
        parts.append("<p><b>PCS — actions</b></p>" + _action_lines(pcs_rows))

    return "".join(parts)
