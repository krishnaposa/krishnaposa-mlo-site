"""
Momentum RS portfolio — trailing stop + RS percentile exits.

Separate from the main quant monitor; optional daily hook updates JSON and feeds the email.

Holdings list (holdings_list.json) uses the same trailing-stop + RS exit rules via run_holdings_trailing_daily()
(state: holdings_trailing_state.json). Disable with HOLDINGS_TRAILING_EXITS_ENABLED=0.
Set HOLDINGS_LIST_REMOVE_ON_EXIT=1 to drop exited tickers from holdings_list.json automatically (default: manual edits only).

Env:
  MOMENTUM_PORTFOLIO_ENABLED=1   — run update + include email section
  MOMENTUM_PORTFOLIO_FILE        — local JSON path fallback (default: stocks-func-app/momentum_portfolio.json)
  MOMENTUM_PORTFOLIO_CONTAINER / MOMENTUM_PORTFOLIO_BLOB_NAME — Azure Blob (same pattern as local_list)
  MOMENTUM_PORTFOLIO_MIRROR_LOCAL=1 — after successful blob save, also write local file
  MOMENTUM_FINVIZ_URL            — optional Finviz screener URL (?f=...) to auto-seed new slots up to PORTFOLIO_SIZE
  MOMENTUM_FINVIZ_SORT          — default sort if URL has no &o= (default -marketcap)
  MOMENTUM_RS_ENTRY_THRESHOLD    — default 90 (Finviz seed filter when MOMENTUM_FINVIZ_RS_FILTER=1)
  MOMENTUM_RS_EXIT_THRESHOLD     — default 70 (exit when RS is strictly below this; RS == threshold does not exit)
  MOMENTUM_TRAILING_STOP_PCT     — default 0.15
  MOMENTUM_FINVIZ_RS_FILTER      — default 1: only Finviz-seed names with RS %ile >= entry threshold
  MOMENTUM_RS_MIN_TRADING_DAYS  — min bars of history for RS (default 120) or RS is N/A (no RS exit)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
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

RS_ENTRY_THRESHOLD = float(os.getenv("MOMENTUM_RS_ENTRY_THRESHOLD", "90"))
RS_EXIT_THRESHOLD = float(os.getenv("MOMENTUM_RS_EXIT_THRESHOLD", "70"))
TRAILING_STOP_PCT = float(os.getenv("MOMENTUM_TRAILING_STOP_PCT", "0.15"))
PORTFOLIO_SIZE = int(os.getenv("MOMENTUM_PORTFOLIO_SIZE", "20"))
RS_MIN_TRADING_DAYS = int(os.getenv("MOMENTUM_RS_MIN_TRADING_DAYS", "120"))
FINVIZ_RS_FILTER = os.getenv("MOMENTUM_FINVIZ_RS_FILTER", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)


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


def _seed_portfolio_from_finviz_url(portfolio: Dict[str, Any], out: Dict[str, Any]) -> None:
    """
    Fill empty slots in portfolio using tickers from a Finviz screener URL (wb4u_finviz).
    Does not remove existing holdings; caps total size at PORTFOLIO_SIZE.
    """
    url = (os.getenv("MOMENTUM_FINVIZ_URL") or "").strip()
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

    cap_left = PORTFOLIO_SIZE - len(portfolio)
    if cap_left <= 0:
        out["messages"].append(
            f"Finviz seed skipped — portfolio already at cap ({len(portfolio)}/{PORTFOLIO_SIZE})."
        )
        return

    need = [str(s).upper().strip() for s in sym_list if str(s).strip()]
    need = [s for s in need if s not in portfolio][:cap_left]

    if not need:
        out["messages"].append(
            "Finviz seed: no new symbols to add (screen overlap with current holdings)."
        )
        return

    if FINVIZ_RS_FILTER:
        bench_for_rs = list(dict.fromkeys([*portfolio.keys(), *need]))
        rs_all = get_rs_ratings(bench_for_rs)
        filtered_syms: List[str] = []
        below_thr = 0
        nan_rs = 0
        for sym in need:
            rv = rs_all.get(sym)
            if rv is None or pd.isna(rv):
                nan_rs += 1
                continue
            if float(rv) >= RS_ENTRY_THRESHOLD:
                filtered_syms.append(sym)
            else:
                below_thr += 1
        if not filtered_syms:
            out["messages"].append(
                f"Finviz RS filter: no symbols meet RS ≥ {RS_ENTRY_THRESHOLD:g} "
                f"({below_thr} below threshold, {nan_rs} insufficient RS data)."
            )
            return
        out["messages"].append(
            f"Finviz RS filter: {len(filtered_syms)}/{len(need)} pass RS ≥ {RS_ENTRY_THRESHOLD:g} "
            f"({below_thr} below, {nan_rs} no RS)."
        )
        need = filtered_syms

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

    if added:
        save_momentum_portfolio(portfolio, meta={"source": "finviz_seed"})
        out["portfolio_saved"] = True
        preview = ", ".join(added[:12]) + (" …" if len(added) > 12 else "")
        out["messages"].append(
            f"Finviz seed: added {len(added)} — {preview}"
        )
    else:
        out["messages"].append("Finviz seed: could not price any new symbols via Yahoo.")


def _total_returns_from_adjusted_panel(closes: pd.DataFrame, *, min_bars: int) -> pd.Series:
    """
    Per ticker: total return from first valid adjusted close to last valid close in the panel.
    Tickers with fewer than ``min_bars`` observations get NaN (no RS until history is sufficient).
    """
    out: Dict[str, float] = {}
    for col in closes.columns:
        s = closes[col].dropna()
        if len(s) < min_bars:
            out[str(col)] = np.nan
            continue
        lo = float(s.iloc[0])
        hi = float(s.iloc[-1])
        if lo <= 0 or not np.isfinite(lo) or not np.isfinite(hi):
            out[str(col)] = np.nan
        else:
            out[str(col)] = (hi / lo) - 1.0
    return pd.Series(out, dtype=float)


def get_rs_ratings(tickers: List[str]) -> pd.Series:
    """
    Relative strength on a 0–100 scale: percentile rank of ~1y **adjusted** total returns among
    the given tickers plus SPY (same calendar panel from Yahoo ``period=1y``).

    Exits compare with strict ``RS < MOMENTUM_RS_EXIT_THRESHOLD`` (equality does not exit).
    Insufficient history yields NaN — those names do not trigger an RS exit until bars ≥ minimum.
    """
    if not tickers:
        return pd.Series(dtype=float)
    tix = list(dict.fromkeys([str(t).upper().strip() for t in tickers if str(t).strip()]))
    bench = list(dict.fromkeys(tix + ["SPY"]))
    closes = _close_panel(bench, period="1y", interval="1d", adjusted=True)
    if closes.empty:
        return pd.Series(dtype=float)
    rets = _total_returns_from_adjusted_panel(closes, min_bars=max(RS_MIN_TRADING_DAYS, 20))
    rs = rets.rank(pct=True, method="average", ascending=True) * 100.0
    return rs


def run_holdings_trailing_daily() -> Dict[str, Any]:
    """
    Trailing stop + RS percentile exits for symbols in holdings_list.json (blob).
    Persists high_seen in holdings_trailing_state.json.
    By default does NOT edit holdings_list.json — remove tickers there manually unless HOLDINGS_LIST_REMOVE_ON_EXIT=1.
    Uses same thresholds as momentum: MOMENTUM_RS_EXIT_THRESHOLD (default 70), MOMENTUM_TRAILING_STOP_PCT.
    """
    out: Dict[str, Any] = {
        "enabled": True,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "state_file": holdings_trailing_storage_description(),
        "messages": [],
        "exited": [],
        "holdings_rows": [],
        "state_saved": False,
        "list_saved": False,
        "rs_series": {},
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

    rs_ratings = get_rs_ratings(tickers)
    out["rs_series"] = {
        k: float(v)
        for k, v in rs_ratings.items()
        if k in tickers and pd.notna(v)
    }

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

        rs_val = rs_ratings.get(ticker) if len(rs_ratings) else None
        if rs_val is not None and pd.notna(rs_val) and float(rs_val) < RS_EXIT_THRESHOLD:
            out["messages"].append(
                f"EXIT {ticker} — RS {float(rs_val):.1f} < exit threshold {RS_EXIT_THRESHOLD:g}"
            )
            to_delete.append(ticker)

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
        cp = float(closes[t].dropna().iloc[-1]) if t in closes.columns else float("nan")
        rs_v = rs_ratings.get(t)
        rs_f = float(rs_v) if rs_v is not None and pd.notna(rs_v) else float("nan")
        stop_px = hi * (1.0 - TRAILING_STOP_PCT) if hi else float("nan")
        out["holdings_rows"].append(
            {
                "ticker": t,
                "last": cp,
                "high_seen": hi,
                "stop": stop_px,
                "rs": rs_f,
            }
        )

    if not updates_made and not out["messages"]:
        out["messages"].append(
            f"Holdings check OK — no exits ({datetime.now().strftime('%Y-%m-%d')})."
        )

    return out


def format_holdings_trailing_email_section(result: Dict[str, Any]) -> str:
    """HTML fragment for send_email_report_with_sims (holdings_list trailing + RS)."""
    if result.get("enabled") is False:
        return (
            "<p><i>Holdings trailing exits disabled — set HOLDINGS_TRAILING_EXITS_ENABLED=1 to enable.</i></p>"
        )

    rows = result.get("holdings_rows") or []
    msgs = result.get("messages") or []
    exited = result.get("exited") or []

    msg_html = "".join(f"<div style='margin:2px 0'>{_esc(m)}</div>" for m in msgs)

    if exited:
        msg_html += (
            f"<div style='margin-top:6px'><b>Exit signal today:</b> {_esc(', '.join(exited))} "
            f"<span style='font-size:11px;color:#666'>(holdings_list.json is not auto-edited — remove manually.)</span></div>"
        )

    table = ""
    if rows:
        parts = [
            "<table border='0' cellspacing='0' cellpadding='4'>",
            "<thead><tr>",
            "<th align='left'>Ticker</th>",
            "<th align='right'>Last</th>",
            "<th align='right'>High seen</th>",
            "<th align='right'>Trailing stop</th>",
            "<th align='right'>RS %ile</th>",
            "</tr></thead><tbody>",
        ]
        for r in rows[:80]:
            parts.append(
                "<tr>"
                f"<td>{_esc(str(r.get('ticker','')))}</td>"
                f"<td align='right'>{_fmt_money(r.get('last'))}</td>"
                f"<td align='right'>{_fmt_money(r.get('high_seen'))}</td>"
                f"<td align='right'>{_fmt_money(r.get('stop'))}</td>"
                f"<td align='right'>{_fmt_num(r.get('rs'))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
        table = "".join(parts)
    else:
        table = "<i>No holdings remaining after exits.</i>"

    meta = (
        f"<div style='font-size:11px;color:#666;margin-bottom:6px'>"
        f"Source: holdings_list.json · State: {_esc(str(result.get('state_file','')))} · "
        f"Exit RS &lt; {RS_EXIT_THRESHOLD:g} · Trailing {TRAILING_STOP_PCT:.0%} · "
        f"RS = adjusted 1y return percentile vs holdings + SPY (min {RS_MIN_TRADING_DAYS} bars)"
        f"</div>"
    )

    return f"{meta}{msg_html}<div style='margin-top:10px'>{table}</div>"


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
        "rs_series": {},
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

    rs_ratings = get_rs_ratings(tickers)
    out["rs_series"] = {
        k: float(v)
        for k, v in rs_ratings.items()
        if k in tickers and pd.notna(v)
    }

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
            continue

        rs_val = rs_ratings.get(ticker) if len(rs_ratings) else None
        if rs_val is not None and pd.notna(rs_val) and float(rs_val) < RS_EXIT_THRESHOLD:
            out["messages"].append(
                f"EXIT {ticker} — RS {float(rs_val):.1f} < exit threshold {RS_EXIT_THRESHOLD:g}"
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
        cp = float(closes[t].dropna().iloc[-1]) if t in closes.columns else float("nan")
        rs_v = rs_ratings.get(t)
        rs_f = float(rs_v) if rs_v is not None and pd.notna(rs_v) else float("nan")
        stop_px = hi * (1.0 - TRAILING_STOP_PCT) if hi else float("nan")
        out["holdings_rows"].append(
            {
                "ticker": t,
                "last": cp,
                "high_seen": hi,
                "stop": stop_px,
                "rs": rs_f,
            }
        )

    if not updates_made and not out["messages"]:
        out["messages"].append(
            f"Daily check OK — no exits ({datetime.now().strftime('%Y-%m-%d')})."
        )

    return out


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
            "<th align='right'>RS %ile</th>",
            "</tr></thead><tbody>",
        ]
        for r in rows[: PORTFOLIO_SIZE + 5]:
            parts.append(
                "<tr>"
                f"<td>{_esc(str(r.get('ticker','')))}</td>"
                f"<td align='right'>{_fmt_money(r.get('last'))}</td>"
                f"<td align='right'>{_fmt_money(r.get('high_seen'))}</td>"
                f"<td align='right'>{_fmt_money(r.get('stop'))}</td>"
                f"<td align='right'>{_fmt_num(r.get('rs'))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
        table = "".join(parts)
    else:
        table = "<i>No open momentum positions.</i>"

    meta = (
        f"<div style='font-size:11px;color:#666;margin-bottom:6px'>"
        f"Storage: {_esc(str(result.get('portfolio_file','')))} · "
        f"Exit RS &lt; {RS_EXIT_THRESHOLD:g} · Trailing {TRAILING_STOP_PCT:.0%} · "
        f"RS = adjusted 1y return percentile vs book + SPY (min {RS_MIN_TRADING_DAYS} bars)"
        f"</div>"
    )

    return f"{meta}{msg_html}<div style='margin-top:10px'>{table}</div>"


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


def _fmt_num(x: Any) -> str:
    try:
        v = float(x)
        if v != v:
            return "—"
        return f"{v:.1f}"
    except Exception:
        return "—"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import pprint

    pprint.pprint(run_momentum_daily())
