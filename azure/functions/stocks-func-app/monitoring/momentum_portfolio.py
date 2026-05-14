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
  MOMENTUM_FINVIZ_URL            — Finviz screener URL (?f=...) for momentum only (separate from WHEEL_* Finviz)
  MOMENTUM_FINVIZ_SORT          — default sort if URL has no &o= (default -marketcap)
  MOMENTUM_RS_ENTRY_THRESHOLD    — default 90 (Finviz seed filter when MOMENTUM_FINVIZ_RS_FILTER=1)
  MOMENTUM_RS_EXIT_THRESHOLD     — default 70 (exit when RS is strictly below this; RS == threshold does not exit)
  MOMENTUM_RS_LOOKBACK_PERIOD    — yfinance period for RS (default 6mo); total return first-to-last Close, rank(pct)*100 vs peers + SPY (same as scripts/stocks/momentum-analyzer.py)
  MOMENTUM_TRAILING_STOP_PCT     — default 0.15
  MOMENTUM_FINVIZ_RS_FILTER      — default 1: only Finviz-seed names with RS %ile >= entry threshold
  Same-day Finviz seeds: RS exit is skipped until the next daily run (trailing stop still applies).
  Finviz momentum seeding prints staged lists to stdout under prefix ``[momentum Finviz]`` (raw URL list, new-slot filter, RS / Yahoo).
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
FINVIZ_RS_FILTER = os.getenv("MOMENTUM_FINVIZ_RS_FILTER", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
RS_LOOKBACK_PERIOD = (os.getenv("MOMENTUM_RS_LOOKBACK_PERIOD") or "6mo").strip()


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
    Symbols appended here are recorded in ``out["seeded_this_run"]`` so ``run_momentum_daily`` can
    defer RS-based exits until the next run (trailing stop still evaluated same day).
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

    need_pre_rs = list(need)
    out["finviz_seed_pre_rs_rows"] = []

    if FINVIZ_RS_FILTER:
        # RS %ile for seeding: Finviz new-slot names + SPY only (not current book — matches original design).
        rs_all = get_rs_ratings(need_pre_rs)
        for sym in need_pre_rs:
            rv = rs_all.get(sym)
            rs_f = float(rv) if rv is not None and pd.notna(rv) else None
            out["finviz_seed_pre_rs_rows"].append({"ticker": sym, "rs": rs_f})
        filtered_syms: List[str] = []
        below_thr = 0
        nan_rs = 0
        for sym in need_pre_rs:
            rv = rs_all.get(sym)
            if rv is None or pd.isna(rv):
                nan_rs += 1
                continue
            if float(rv) >= RS_ENTRY_THRESHOLD:
                filtered_syms.append(sym)
            else:
                below_thr += 1
        rs_parts: List[str] = []
        for sym in need_pre_rs:
            rv = rs_all.get(sym)
            if rv is not None and pd.notna(rv):
                rs_parts.append(f"{sym}={float(rv):.1f}")
            else:
                rs_parts.append(f"{sym}=—")
        print("[momentum Finviz] RS %ile by ticker (Finviz new-slot set + SPY peer rank): " + ", ".join(rs_parts))
        _print_momentum_finviz_stage(
            f"after RS entry filter (keep RS ≥ {RS_ENTRY_THRESHOLD:g})",
            filtered_syms,
        )
        if not filtered_syms:
            out["messages"].append(
                f"Finviz RS filter: no symbols meet RS ≥ {RS_ENTRY_THRESHOLD:g} "
                f"({below_thr} below threshold, {nan_rs} insufficient RS data)."
            )
            return
        out["messages"].append(
            f"Finviz RS filter: {len(filtered_syms)}/{len(need_pre_rs)} pass RS ≥ {RS_ENTRY_THRESHOLD:g} "
            f"({below_thr} below, {nan_rs} no RS)."
        )
        need = filtered_syms
    else:
        out["finviz_seed_pre_rs_rows"] = [{"ticker": s, "rs": None} for s in need_pre_rs]
        print(
            "[momentum Finviz] RS entry filter disabled (MOMENTUM_FINVIZ_RS_FILTER=0); "
            "same list as new-slot step."
        )

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


def get_rs_ratings(tickers: List[str]) -> pd.Series:
    """
    Percentile RS vs peers — **same construction as** ``scripts/stocks/momentum-analyzer.get_rs_ratings``.

    1. Download daily **Close** (split/dividend-adjusted) for ``tickers`` + **SPY** (deduped) over
       ``RS_LOOKBACK_PERIOD`` (env ``MOMENTUM_RS_LOOKBACK_PERIOD``, default ``6mo``).
    2. Total return per symbol: ``last_close / first_close - 1`` (first/last row of the panel).
    3. ``rank(pct=True) * 100`` on those returns (peer set includes SPY).

    **Entry:** Finviz candidates only. **Exit:** open position tickers (or holdings list) only.
    """
    if not tickers:
        return pd.Series(dtype=float)
    tix = list(dict.fromkeys([str(t).upper().strip() for t in tickers if str(t).strip()]))
    bench = list(dict.fromkeys(tix + ["SPY"]))
    raw = yf.download(
        bench,
        period=RS_LOOKBACK_PERIOD,
        interval="1d",
        progress=False,
        threads=False,
        auto_adjust=True,
    )
    if raw is None or raw.empty:
        return pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        data = raw["Close"].copy()
    else:
        if "Close" not in raw.columns:
            return pd.Series(dtype=float)
        sym = str(bench[0]).upper()
        data = pd.DataFrame({sym: raw["Close"].values}, index=raw.index)
    data.columns = [str(c).upper() for c in data.columns]
    if "SPY" not in data.columns:
        return pd.Series(dtype=float)

    rets = (data.iloc[-1] / data.iloc[0]) - 1.0
    rets = rets.replace([np.inf, -np.inf], np.nan)
    out = rets.rank(pct=True, method="average", ascending=True) * 100.0
    return out


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
        f"RS = total return over {RS_LOOKBACK_PERIOD} (adj. Close), pct-rank among holdings + SPY "
        f"(same as momentum-analyzer.py)"
        f"</div>"
    )

    return f"{meta}{msg_html}<div style='margin-top:10px'>{table}</div>"


def run_momentum_daily() -> Dict[str, Any]:
    """
    Update trailing highs, exits, persist JSON. Returns a dict for logging + email HTML.
    Persists to blob/local every successful run so storage matches the email snapshot,
    even when no highs/exits occurred that day.
    RS exit is not applied on the same run to tickers just added from the Finviz seed step
    (trailing stop still applies); those tickers are evaluated on the next daily run.
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

    skip_rs_exit_today = {
        str(s).upper().strip()
        for s in (out.get("seeded_this_run") or [])
        if str(s).strip()
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
        rs_would_exit = (
            rs_val is not None
            and pd.notna(rs_val)
            and float(rs_val) < RS_EXIT_THRESHOLD
        )
        if rs_would_exit:
            if ticker in skip_rs_exit_today:
                out["messages"].append(
                    f"{ticker}: RS exit deferred (Finviz seed this run; RS {float(rs_val):.1f} "
                    f"< {RS_EXIT_THRESHOLD:g} — evaluated next day)."
                )
            else:
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


def _format_finviz_pre_rs_email_html(result: Dict[str, Any]) -> str:
    """Email HTML: Finviz screener list + new-slot candidates before RS entry filter."""
    screen = result.get("finviz_screen_symbols") or []
    rows = result.get("finviz_seed_pre_rs_rows") or []
    if not screen and not rows:
        return ""

    parts: List[str] = [
        "<h4 style='margin:14px 0 6px;font-size:14px'>Finviz screen (before RS entry filter)</h4>"
    ]
    if screen:
        preview = ", ".join(screen[:50])
        if len(screen) > 50:
            preview += f" … (+{len(screen) - 50} more)"
        parts.append(
            "<div style='font-size:12px;margin-bottom:8px'>"
            f"<b>Screener tickers</b> ({len(screen)} — Finviz order; list length capped by screener fetch):<br>"
            f"<span style='font-family:ui-monospace,monospace'>{_esc(preview)}</span></div>"
        )
    if rows:
        gate = (
            f"RS ≥ {RS_ENTRY_THRESHOLD:g} required to seed"
            if FINVIZ_RS_FILTER
            else "RS entry filter off (MOMENTUM_FINVIZ_RS_FILTER=0) — all below subject to Yahoo pricing"
        )
        parts.append(
            "<div style='font-size:12px;margin-bottom:4px'>"
            f"<b>New-slot candidates</b> (not already in momentum book; {gate}). "
            "RS %ile = total return over "
            f"{RS_LOOKBACK_PERIOD} (adj. daily Close), then pct-rank among <b>these Finviz candidates + SPY only</b> "
            "(same construction as scripts/stocks/momentum-analyzer.py). "
            "(same formula as open positions; book not in this peer set for seeding). "
            f"<span style='color:#444'>This table only gates <i>new seeds</i>; open positions still exit if "
            f"RS &lt; {RS_EXIT_THRESHOLD:g} (MOMENTUM_RS_EXIT_THRESHOLD) or trailing stop hits "
            f"(RS exit skipped same day for symbols just seeded from Finviz).</span></div>"
        )
        ent_col = (
            f"Seed if RS≥{RS_ENTRY_THRESHOLD:g}?"
            if FINVIZ_RS_FILTER
            else "RS gate"
        )
        parts.extend(
            [
                "<table border='0' cellspacing='0' cellpadding='4' style='font-size:12px'>",
                "<thead><tr><th align='left'>Ticker</th><th align='right'>RS %ile</th>"
                f"<th align='left'>{_esc(ent_col)}</th></tr></thead><tbody>",
            ]
        )
        for r in rows[:40]:
            t = str(r.get("ticker", ""))
            rs = r.get("rs")
            if rs is not None and isinstance(rs, (int, float)) and rs == rs and np.isfinite(rs):
                rs_s = f"{float(rs):.1f}"
                if FINVIZ_RS_FILTER:
                    thr = RS_ENTRY_THRESHOLD
                    fv = float(rs)
                    flag = f"yes (≥{thr:g})" if fv >= thr else f"no (<{thr:g})"
                else:
                    flag = "—"
            else:
                rs_s = "—"
                flag = "no data" if FINVIZ_RS_FILTER else "—"
            parts.append(
                "<tr>"
                f"<td>{_esc(t)}</td>"
                f"<td align='right'>{_esc(rs_s)}</td>"
                f"<td>{_esc(flag)}</td>"
                "</tr>"
            )
        if len(rows) > 40:
            parts.append(
                f"<tr><td colspan='3'><i>… {len(rows) - 40} more</i></td></tr>"
            )
        parts.append("</tbody></table>")
    elif screen:
        parts.append(
            "<div style='font-size:12px;color:#666'>Portfolio full or no new slots — candidate table omitted.</div>"
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

    momf = result.get("finviz_screen_symbols") or []
    rs_note = (
        "open book + SPY (momentum table). Finviz block = seed RS (candidates+SPY)."
        if momf
        else "open book + SPY"
    )
    meta = (
        f"<div style='font-size:11px;color:#666;margin-bottom:6px'>"
        f"Storage: {_esc(str(result.get('portfolio_file','')))} · "
        f"Exit RS &lt; {RS_EXIT_THRESHOLD:g} (next run for same-day Finviz seeds) · "
        f"Trailing {TRAILING_STOP_PCT:.0%} · "
        f"RS = total return over {RS_LOOKBACK_PERIOD} (adj. Close), pct-rank vs {_esc(rs_note)} "
        f"(momentum-analyzer.py)"
        f"</div>"
    )

    finviz_pre = _format_finviz_pre_rs_email_html(result)
    return f"{meta}{finviz_pre}{msg_html}<div style='margin-top:10px'>{table}</div>"


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
