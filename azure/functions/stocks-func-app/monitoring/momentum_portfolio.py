"""
Momentum portfolio — Finviz seeding + trailing stop exits.

Separate from the main quant monitor; optional daily hook updates JSON and feeds the email.

Holdings list (holdings_list.json) uses trailing-stop exits via run_holdings_trailing_daily()
(state: holdings_trailing_state.json). Disable with HOLDINGS_TRAILING_EXITS_ENABLED=0.
Set HOLDINGS_LIST_REMOVE_ON_EXIT=1 to drop exited tickers from holdings_list.json automatically (default: manual edits only).

Env:
  MOMENTUM_PORTFOLIO_ENABLED=1   — run update + include email section
  MOMENTUM_PORTFOLIO_FILE        — local JSON path fallback (default: stocks-func-app/momentum_portfolio.json)
  MOMENTUM_PORTFOLIO_CONTAINER / MOMENTUM_PORTFOLIO_BLOB_NAME — Azure Blob (same pattern as local_list)
  MOMENTUM_PORTFOLIO_MIRROR_LOCAL=1 — after successful blob save, also write local file
  MOMENTUM_FINVIZ_URL            — Finviz screener URL (?f=...) for momentum only (separate from WHEEL_* Finviz)
  MOMENTUM_FINVIZ_SORT          — default sort if URL has no &o= (default -marketcap)
  MOMENTUM_TRAILING_STOP_PCT     — default 0.15
  Finviz momentum seeding prints staged lists to stdout under prefix ``[momentum Finviz]`` (raw URL list, new-slot filter, Yahoo).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

try:
    from momentum_portfolio_utils import (
        load_momentum_portfolio,
        save_momentum_portfolio,
        storage_description,
    )
    from local_list_utils import (
        load_holdings_list,
        save_holdings_list,
        load_holdings_trailing_state,
        save_holdings_trailing_state,
        holdings_trailing_storage_description,
    )
except ImportError:
    import sys

    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from momentum_portfolio_utils import (
        load_momentum_portfolio,
        save_momentum_portfolio,
        storage_description,
    )
    from local_list_utils import (
        load_holdings_list,
        save_holdings_list,
        load_holdings_trailing_state,
        save_holdings_trailing_state,
        holdings_trailing_storage_description,
    )

TRAILING_STOP_PCT = float(os.getenv("MOMENTUM_TRAILING_STOP_PCT", "0.15"))
PORTFOLIO_SIZE = int(os.getenv("MOMENTUM_PORTFOLIO_SIZE", "20"))


def _close_panel(
    tickers: List[str], *, period: str, interval: str, adjusted: bool = True
) -> pd.DataFrame:
    """
    One column per ticker (uppercase). When adjusted=True (default), yfinance returns
    split/dividend-adjusted closes so trailing levels and 1y returns match total-return math.
    """
    if not tickers:
        return pd.DataFrame()
    tix = [str(t).upper().strip() for t in tickers if str(t).strip()]
    raw = yf.download(
        tix,
        period=period,
        interval=interval,
        progress=False,
        threads=False,
        auto_adjust=adjusted,
    )
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"].copy()
    else:
        if "Close" not in raw.columns:
            return pd.DataFrame()
        # Single ticker: flat OHLCV table
        closes = pd.DataFrame({tix[0]: raw["Close"].values}, index=raw.index)
    closes.columns = [str(c).upper() for c in closes.columns]
    return closes


def _last_close_from_panel(closes: pd.DataFrame, ticker: str) -> float:
    """Last non-NaN close for ticker, or NaN if column missing or all empty (Yahoo miss)."""
    t = str(ticker).upper().strip()
    if closes.empty or t not in closes.columns:
        return float("nan")
    series = closes[t].dropna()
    if series.empty:
        return float("nan")
    return float(series.iloc[-1])


def _print_momentum_finviz_stage(label: str, syms: List[str], *, max_show: int = 150) -> None:
    """Console trace for Finviz momentum seeding (stdout / Azure log stream)."""
    u = [str(s).upper().strip() for s in syms if str(s).strip()]
    n = len(u)
    if n == 0:
        print(f"[momentum Finviz] {label}: (empty)")
        return
    if n <= max_show:
        body = ", ".join(u)
    else:
        body = ", ".join(u[:max_show]) + f" … (+{n - max_show} more)"
    print(f"[momentum Finviz] {label} ({n}): {body}")


def _seed_portfolio_from_finviz_url(portfolio: Dict[str, Any], out: Dict[str, Any]) -> None:
    """
    Fill empty slots in portfolio using tickers from a Finviz screener URL (wb4u_finviz).
    Does not remove existing holdings; caps total size at PORTFOLIO_SIZE.
    Symbols appended here are recorded in ``out["seeded_this_run"]`` for email/logging.
    """
    out["seeded_this_run"] = []
    url = (os.getenv("MOMENTUM_FINVIZ_URL") or "https://finviz.com/screener.ashx?v=111&f=cap_midover,sh_price_o5,ta_sma200_pa,ta_highlow52w_nh&ft=3").strip()
    if not url:
        return

    sort_fallback = (os.getenv("MOMENTUM_FINVIZ_SORT") or "").strip() or None

    try:
        import wb4u_finviz

        sym_list = wb4u_finviz.symbols_from_screener_url(
            url,
            max_symbols=max(PORTFOLIO_SIZE * 4, 80),
            default_sort=sort_fallback,
        )
    except Exception as e:
        msg = f"Finviz URL seed failed: {e}"
        out["messages"].append(msg)
        logger.warning("[momentum] %s", msg)
        return

    if not sym_list:
        out["messages"].append("Finviz screener returned no symbols.")
        return

    sym_list_norm = [str(s).upper().strip() for s in sym_list if str(s).strip()]
    out["finviz_screen_symbols"] = sym_list_norm
    _print_momentum_finviz_stage("raw screener (from URL, capped by fetch)", sym_list_norm)

    cap_left = PORTFOLIO_SIZE - len(portfolio)
    if cap_left <= 0:
        out["messages"].append(
            f"Finviz seed skipped — portfolio already at cap ({len(portfolio)}/{PORTFOLIO_SIZE})."
        )
        return

    need = [s for s in sym_list_norm if s not in portfolio][:cap_left]
    _print_momentum_finviz_stage(
        f"after new-slot filter (not in book; first {cap_left} empty slots)",
        need,
    )

    if not need:
        out["messages"].append(
            "Finviz seed: no new symbols to add (screen overlap with current holdings)."
        )
        return

    closes_seed = _close_panel(need, period="5d", interval="1d")
    added: List[str] = []
    for sym in need:
        if len(portfolio) >= PORTFOLIO_SIZE:
            break
        if sym not in closes_seed.columns:
            logger.warning("[momentum] seed skip %s: no Yahoo Close column", sym)
            continue
        series = closes_seed[sym].dropna()
        if series.empty:
            continue
        px = float(series.iloc[-1])
        portfolio[sym] = {"high_seen": px}
        added.append(sym)

    skipped_yahoo = [s for s in need if s not in added]
    _print_momentum_finviz_stage("after Yahoo 5d Close gate (actually seeded)", added)
    if skipped_yahoo:
        _print_momentum_finviz_stage(
            "skipped at Yahoo / portfolio cap (not seeded this run)",
            skipped_yahoo,
        )

    out["seeded_this_run"] = list(added)

    if added:
        save_momentum_portfolio(portfolio, meta={"source": "finviz_seed"})
        out["portfolio_saved"] = True
        preview = ", ".join(added[:12]) + (" …" if len(added) > 12 else "")
        out["messages"].append(
            f"Finviz seed: added {len(added)} — {preview}"
        )
    else:
        out["messages"].append("Finviz seed: could not price any new symbols via Yahoo.")


def run_holdings_trailing_daily() -> Dict[str, Any]:
    """
    Trailing stop exits for symbols in holdings_list.json (blob).
    Email: weak symbols (price watch) + trailing stop messages.
    Persists high_seen in holdings_trailing_state.json.
    """
    from .position_metrics import get_position_price_metrics

    out: Dict[str, Any] = {
        "enabled": True,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "state_file": holdings_trailing_storage_description(),
        "messages": [],
        "exited": [],
        "holdings_rows": [],
        "state_saved": False,
        "list_saved": False,
    }

    if os.getenv("HOLDINGS_TRAILING_EXITS_ENABLED", "1") != "1":
        out["enabled"] = False
        out["messages"].append("Holdings trailing exits disabled (set HOLDINGS_TRAILING_EXITS_ENABLED=1).")
        return out

    holdings = load_holdings_list()
    if not holdings:
        out["messages"].append("No symbols in holdings_list.json — nothing to manage.")
        return out

    tickers = sorted({str(t).upper().strip() for t in holdings if str(t).strip()})

    state = load_holdings_trailing_state()
    hold_set = set(tickers)
    for k in list(state.keys()):
        if k not in hold_set:
            del state[k]

    closes = _close_panel(tickers, period="5d", interval="1d")
    if closes.empty:
        out["messages"].append("yfinance returned no price data for holdings.")
        return out

    price_metrics = get_position_price_metrics(tickers)

    to_delete: List[str] = []
    updates_made = False

    for ticker in tickers:
        if ticker not in closes.columns:
            out["messages"].append(f"{ticker}: missing from latest download — skipped.")
            continue

        series = closes[ticker].dropna()
        if series.empty:
            out["messages"].append(f"{ticker}: no closes — skipped.")
            continue

        current_price = float(series.iloc[-1])
        entry = state.setdefault(ticker, {})
        high_seen = float(entry.get("high_seen") or 0.0)
        if high_seen <= 0:
            high_seen = current_price
            entry["high_seen"] = high_seen
            updates_made = True

        if current_price > high_seen:
            entry["high_seen"] = current_price
            updates_made = True
            stop_px = current_price * (1.0 - TRAILING_STOP_PCT)
            out["messages"].append(
                f"NEW HIGH {ticker} @ ${current_price:.2f} → trailing stop ${stop_px:.2f}"
            )

        stop_price = float(entry["high_seen"]) * (1.0 - TRAILING_STOP_PCT)
        if current_price <= stop_price:
            out["messages"].append(
                f"EXIT {ticker} — trailing stop (price ${current_price:.2f} ≤ stop ${stop_price:.2f})"
            )
            to_delete.append(ticker)
            continue

    to_delete = list(dict.fromkeys(str(x).upper() for x in to_delete))
    exited_set = set(to_delete)
    out["exited"] = list(to_delete)
    for t in to_delete:
        state.pop(t, None)

    if to_delete:
        if os.getenv("HOLDINGS_LIST_REMOVE_ON_EXIT", "0") == "1":
            remaining = sorted(hold_set - exited_set)
            save_holdings_list(remaining, meta={"source": "holdings_trailing_exit"})
            out["list_saved"] = True
        updates_made = True  # state popped for exits — persist trailing state

    if updates_made:
        try:
            save_holdings_trailing_state(state, meta={"source": "daily_holdings_trailing"})
            out["state_saved"] = True
        except Exception as e:
            msg = f"Failed to save holdings trailing state: {e}"
            out["messages"].append(msg)
            logger.warning("[holdings_trailing] %s", msg)

    # Table: all symbols still in holdings_list (exits alert only; list blob unchanged unless REMOVE_ON_EXIT).
    for t in sorted(hold_set):
        hi = float((state.get(t) or {}).get("high_seen") or 0.0)
        cp = _last_close_from_panel(closes, t)
        pm = price_metrics.get(t, {})
        stop_px = hi * (1.0 - TRAILING_STOP_PCT) if hi else float("nan")
        out["holdings_rows"].append(
            {
                "ticker": t,
                "last": cp,
                "today_pct": pm.get("chg_1d_pct"),
                "week_pct": pm.get("chg_5d_pct"),
                "below_20dma": pm.get("below_20dma"),
                "high_seen": hi,
                "stop": stop_px,
            }
        )

    if not updates_made and not out["messages"]:
        out["messages"].append(
            f"Holdings check OK — no exits ({datetime.now().strftime('%Y-%m-%d')})."
        )

    return out


def format_holdings_trailing_email_section(result: Dict[str, Any]) -> str:
    """HTML fragment: price watch table + trailing-stop messages/exits."""
    from .position_metrics import format_weak_symbols_html

    if result.get("enabled") is False:
        return (
            "<p><i>Holdings trailing exits disabled — set HOLDINGS_TRAILING_EXITS_ENABLED=1 to enable.</i></p>"
        )

    rows = result.get("holdings_rows") or []
    msgs = result.get("messages") or []
    exited = result.get("exited") or []
    tickers = [str(r.get("ticker", "")).upper().strip() for r in rows if str(r.get("ticker", "")).strip()]

    msg_html = "".join(f"<div style='margin:2px 0'>{_esc(m)}</div>" for m in msgs)

    if exited:
        msg_html += (
            f"<div style='margin-top:6px'><b>Exit signal today:</b> {_esc(', '.join(exited))} "
            f"<span style='font-size:11px;color:#666'>(holdings_list.json is not auto-edited unless HOLDINGS_LIST_REMOVE_ON_EXIT=1.)</span></div>"
        )

    weak_block = format_weak_symbols_html(
        tickers,
        "Holdings — price watch",
    )

    meta = (
        f"<div style='font-size:11px;color:#666;margin-bottom:6px'>"
        f"Source: holdings_list.json · State: {_esc(str(result.get('state_file','')))} · "
        f"Trailing exit {TRAILING_STOP_PCT:.0%} off high_seen"
        f"</div>"
    )

    return f"{meta}{weak_block}{msg_html}"


def run_momentum_daily() -> Dict[str, Any]:
    """
    Update trailing highs, exits, persist JSON. Returns a dict for logging + email HTML.
    Persists to blob/local every successful run so storage matches the email snapshot,
    even when no highs/exits occurred that day.
    """
    out: Dict[str, Any] = {
        "enabled": True,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "portfolio_file": storage_description(),
        "messages": [],
        "exited": [],
        "holdings_rows": [],
        "portfolio_saved": False,
    }

    portfolio = load_momentum_portfolio()
    _seed_portfolio_from_finviz_url(portfolio, out)

    if not portfolio:
        out["messages"].append(
            "Portfolio empty — set MOMENTUM_FINVIZ_URL (Finviz screener with ?f=...) "
            "or add positions via blob/local JSON (see momentum_portfolio_utils)."
        )
        return out

    tickers = [str(k).upper().strip() for k in portfolio.keys() if str(k).strip()]
    closes = _close_panel(tickers, period="5d", interval="1d")
    if closes.empty:
        out["messages"].append("yfinance returned no price data for momentum holdings.")
        return out

    to_delete: List[str] = []
    updates_made = False

    for ticker in tickers:
        if ticker not in portfolio or not isinstance(portfolio[ticker], dict):
            portfolio[ticker] = {}

        if ticker not in closes.columns:
            out["messages"].append(f"{ticker}: missing from latest download — skipped.")
            continue

        series = closes[ticker].dropna()
        if series.empty:
            out["messages"].append(f"{ticker}: no closes — skipped.")
            continue

        current_price = float(series.iloc[-1])
        entry = portfolio.get(ticker) or {}
        high_seen = float(entry.get("high_seen", current_price))

        if current_price > high_seen:
            portfolio[ticker]["high_seen"] = current_price
            updates_made = True
            stop_px = current_price * (1.0 - TRAILING_STOP_PCT)
            out["messages"].append(
                f"NEW HIGH {ticker} @ ${current_price:.2f} → trailing stop ${stop_px:.2f}"
            )

        stop_price = float(portfolio[ticker]["high_seen"]) * (1.0 - TRAILING_STOP_PCT)
        if current_price <= stop_price:
            out["messages"].append(
                f"EXIT {ticker} — trailing stop (price ${current_price:.2f} ≤ stop ${stop_price:.2f})"
            )
            to_delete.append(ticker)

    for ticker in to_delete:
        portfolio.pop(ticker, None)
        out["exited"].append(ticker)
        updates_made = True

    try:
        save_momentum_portfolio(
            portfolio,
            meta={
                "source": "daily_momentum",
                "daily_snapshot": True,
            },
        )
        out["portfolio_saved"] = True
    except Exception as e:
        msg = f"Momentum portfolio save failed: {e}"
        out["messages"].append(msg)
        logger.warning("[momentum] %s", msg)

    # Holdings snapshot for email table
    for ticker in sorted(portfolio.keys()):
        t = str(ticker).upper().strip()
        hi = float((portfolio[t].get("high_seen")) or 0.0)
        cp = _last_close_from_panel(closes, t)
        stop_px = hi * (1.0 - TRAILING_STOP_PCT) if hi else float("nan")
        out["holdings_rows"].append(
            {
                "ticker": t,
                "last": cp,
                "high_seen": hi,
                "stop": stop_px,
            }
        )

    if not updates_made and not out["messages"]:
        out["messages"].append(
            f"Daily check OK — no exits ({datetime.now().strftime('%Y-%m-%d')})."
        )

    return out


def _format_finviz_screen_email_html(result: Dict[str, Any]) -> str:
    """Email HTML: Finviz screener preview + symbols seeded this run."""
    screen = result.get("finviz_screen_symbols") or []
    seeded = [str(s).upper().strip() for s in (result.get("seeded_this_run") or []) if str(s).strip()]
    if not screen and not seeded:
        return ""

    parts: List[str] = [
        "<h4 style='margin:14px 0 6px;font-size:14px'>Finviz momentum seed</h4>"
    ]
    if screen:
        preview = ", ".join(screen[:50])
        if len(screen) > 50:
            preview += f" … (+{len(screen) - 50} more)"
        parts.append(
            "<div style='font-size:12px;margin-bottom:6px'>"
            f"<b>Screener</b> ({len(screen)}): "
            f"<span style='font-family:ui-monospace,monospace'>{_esc(preview)}</span></div>"
        )
    if seeded:
        parts.append(
            f"<div style='font-size:12px;margin-bottom:6px'>"
            f"<b>Seeded this run:</b> {_esc(', '.join(seeded))}</div>"
        )
    return "".join(parts)


def format_momentum_email_section(result: Dict[str, Any]) -> str:
    """HTML fragment for send_email_report_with_sims."""
    # Default missing key to on — only skip when explicitly disabled.
    if result.get("enabled") is False:
        return ""

    rows = result.get("holdings_rows") or []
    msgs = result.get("messages") or []
    exited = result.get("exited") or []

    msg_html = "".join(f"<div style='margin:2px 0'>{_esc(m)}</div>" for m in msgs)

    if exited:
        msg_html += f"<div style='margin-top:6px'><b>Removed:</b> {_esc(', '.join(exited))}</div>"

    table = ""
    if rows:
        parts = [
            "<table border='0' cellspacing='0' cellpadding='4'>",
            "<thead><tr>",
            "<th align='left'>Ticker</th>",
            "<th align='right'>Last</th>",
            "<th align='right'>High seen</th>",
            "<th align='right'>Trailing stop</th>",
            "</tr></thead><tbody>",
        ]
        for r in rows[: PORTFOLIO_SIZE + 5]:
            parts.append(
                "<tr>"
                f"<td>{_esc(str(r.get('ticker','')))}</td>"
                f"<td align='right'>{_fmt_money(r.get('last'))}</td>"
                f"<td align='right'>{_fmt_money(r.get('high_seen'))}</td>"
                f"<td align='right'>{_fmt_money(r.get('stop'))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
        table = "".join(parts)
    else:
        table = "<i>No open momentum positions.</i>"

    meta = (
        f"<div style='font-size:11px;color:#666;margin-bottom:6px'>"
        f"Storage: {_esc(str(result.get('portfolio_file','')))} · "
        f"Trailing exit {TRAILING_STOP_PCT:.0%} off high_seen"
        f"</div>"
    )

    finviz_block = _format_finviz_screen_email_html(result)
    return f"{meta}{finviz_block}{msg_html}<div style='margin-top:10px'>{table}</div>"


def _momentum_holdings_table_text(rows: List[Dict[str, Any]], *, max_rows: int = 80) -> str:
    if not rows:
        return "  (none)"
    lines = [f"  {'Ticker':<8} {'Last':>10} {'High':>10} {'Stop':>10}"]
    for r in rows[:max_rows]:
        lines.append(
            f"  {str(r.get('ticker', '')):<8} "
            f"{_fmt_money(r.get('last')):>10} "
            f"{_fmt_money(r.get('high_seen')):>10} "
            f"{_fmt_money(r.get('stop')):>10}"
        )
    if len(rows) > max_rows:
        lines.append(f"  … {len(rows) - max_rows} more")
    return "\n".join(lines)


def format_holdings_trailing_text(result: Dict[str, Any]) -> str:
    """Plain-text holdings trailing section (same data as email HTML)."""
    from .position_metrics import format_weak_symbols_text

    if result.get("enabled") is False:
        return "  Holdings trailing exits disabled (HOLDINGS_TRAILING_EXITS_ENABLED=0)."

    rows = result.get("holdings_rows") or []
    tickers = [str(r.get("ticker", "")).upper().strip() for r in rows if str(r.get("ticker", "")).strip()]

    lines: List[str] = [
        f"  Trailing exit {TRAILING_STOP_PCT:.0%} off high_seen",
        format_weak_symbols_text(tickers, label="Price watch"),
    ]
    for m in result.get("messages") or []:
        lines.append(f"  • {m}")
    exited = result.get("exited") or []
    if exited:
        lines.append(f"  Exit signal today: {', '.join(exited)}")
    return "\n".join(lines)


def _format_finviz_screen_text(result: Dict[str, Any]) -> str:
    screen = result.get("finviz_screen_symbols") or []
    seeded = [str(s).upper().strip() for s in (result.get("seeded_this_run") or []) if str(s).strip()]
    if not screen and not seeded:
        return ""
    lines: List[str] = ["  Finviz momentum seed"]
    if screen:
        preview = ", ".join(screen[:50])
        if len(screen) > 50:
            preview += f" … (+{len(screen) - 50} more)"
        lines.append(f"  Screener ({len(screen)}): {preview}")
    if seeded:
        lines.append(f"  Seeded this run: {', '.join(seeded)}")
    return "\n".join(lines)


def format_momentum_text(result: Dict[str, Any]) -> str:
    """Plain-text momentum portfolio section (same data as email HTML)."""
    if result.get("enabled") is False:
        return "  Momentum portfolio disabled."

    lines: List[str] = [
        f"  Storage: {result.get('portfolio_file', '')} · "
        f"Trailing exit {TRAILING_STOP_PCT:.0%} off high_seen",
    ]
    finviz = _format_finviz_screen_text(result)
    if finviz:
        lines.append(finviz)
    for m in result.get("messages") or []:
        lines.append(f"  • {m}")
    exited = result.get("exited") or []
    if exited:
        lines.append(f"  Removed: {', '.join(exited)}")
    lines.append(_momentum_holdings_table_text(result.get("holdings_rows") or [], max_rows=PORTFOLIO_SIZE + 5))
    return "\n".join(lines)


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _fmt_money(x: Any) -> str:
    try:
        v = float(x)
        if v != v:  # NaN
            return "—"
        return f"${v:.2f}"
    except Exception:
        return "—"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import pprint

    pprint.pprint(run_momentum_daily())
