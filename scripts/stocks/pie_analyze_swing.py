"""
Swing + Put-Credit-Spread Funnel
--------------------------------

Funnels BUY candidates from the momentum scanner (pie_analyzer.run_scan) into:
- a swing ENTRY plan  (stop, position size, position heat, gap-based entry timing)
- a put-credit-spread (PCS) plan  (expiry, short/long strike, credit, max risk, POP)

Scanning lives in pie_analyzer.py. This module only analyzes the BUY output.

PCS strikes are chosen by %-out-of-the-money from the live yfinance option chain
(no Greeks). max risk = width - credit; POP is a rough credit/width proxy.

Install:
pip install yfinance pandas numpy

Lifecycle review of held positions (positions.json):
  python pie_analyze_swing.py --review
  python pie_analyze_swing.py --review --positions positions.json

Run (BUY funnel):
python pie_analyze_swing.py
python pie_analyze_swing.py --min-grade A --risk-per-trade 0.01 --target-dte 35 --otm-pct 0.06
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

import pandas as pd
import yfinance as yf

from pie_analyzer import run_scan, select_buy_candidates
from stocks_common import read_symbols_from_file

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TICKERS_FILE = SCRIPT_DIR / "my_tickers.txt"
DEFAULT_POSITIONS_FILE = SCRIPT_DIR / "positions.json"

MAX_PORTFOLIO_HEAT = 0.30
MAX_POSITION_SIZE = 0.10
TRAIL_STOP_PCT = 0.15


# =========================================================
# ENUMS
# =========================================================

class SwingPhase(str, Enum):
    WATCH = "WATCH"
    HOLD = "HOLD"
    MANAGE = "MANAGE"
    TRAIL = "TRAIL"
    REVIEW = "REVIEW"


class PCSPhase(str, Enum):
    OPENED = "OPENED"
    THETA_DECAY = "THETA_DECAY"
    MANAGE = "MANAGE"
    DEFENSIVE = "DEFENSIVE"
    ROLL = "ROLL"
    EXIT = "EXIT"
    STOP = "STOP"


# =========================================================
# MODELS
# =========================================================

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


# =========================================================
# LIFECYCLE ENGINE  (for already-open positions)
# =========================================================

def determine_swing_phase(days_held: int, return_pct: float) -> SwingPhase:
    if return_pct >= 25:
        return SwingPhase.TRAIL
    if days_held >= 60:
        return SwingPhase.REVIEW
    if days_held >= 30:
        return SwingPhase.MANAGE
    if days_held >= 10:
        return SwingPhase.HOLD
    return SwingPhase.WATCH


def determine_pcs_phase(delta: float, dte: int, profit_pct: float) -> PCSPhase:
    if profit_pct >= 50:
        return PCSPhase.EXIT
    if delta > 0.30 and dte < 14:
        return PCSPhase.ROLL
    if delta > 0.35:
        return PCSPhase.DEFENSIVE
    if dte < 21:
        return PCSPhase.THETA_DECAY
    return PCSPhase.OPENED


def determine_pcs_phase_live(
    dte: int,
    profit_pct: float,
    buffer_pct: float,
    *,
    profit_target: float = 50.0,
    stop_loss: float = -100.0,
    roll_dte: int = 14,
    roll_buffer: float = 3.0,
    manage_dte: int = 21,
) -> PCSPhase:
    """
    Phase for an open spread using data available without Greeks (Option A).

    buffer_pct = (price - short_strike) / price * 100
      > 0  underlying above the short put (good)
      < 0  underlying below the short put (in trouble)

    Thresholds (precedence top to bottom):
      profit_target  close once >= this % of credit captured (default 50)
      stop_loss      close once loss reaches this % of credit (default -100 = -1x credit)
      roll_dte       roll when DTE below this and buffer is tight (default 14)
      roll_buffer    buffer % considered "tight" for rolling (default 3)
      manage_dte     at/below this DTE, manage (close or roll) regardless (default 21)
    """
    if profit_pct >= profit_target:
        return PCSPhase.EXIT
    if profit_pct <= stop_loss:
        return PCSPhase.STOP
    if buffer_pct < 0:
        return PCSPhase.DEFENSIVE
    if dte < roll_dte and buffer_pct < roll_buffer:
        return PCSPhase.ROLL
    if dte <= manage_dte:
        return PCSPhase.MANAGE
    return PCSPhase.OPENED


# =========================================================
# POSITIONS I/O  (held swings + open spreads)
# =========================================================

def load_positions(path: str) -> dict:
    """Load positions.json: {"swings": [...], "spreads": [...]}. Missing file -> empty."""
    p = Path(path).expanduser()
    if not p.is_file():
        return {"swings": [], "spreads": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {
        "swings": list(data.get("swings") or []),
        "spreads": list(data.get("spreads") or []),
    }


def _days_since(date_str: str) -> int:
    try:
        d = datetime.strptime(str(date_str), "%Y-%m-%d").date()
    except Exception:
        return 0
    return (datetime.today().date() - d).days


def _last_prices(symbols: list[str]) -> dict[str, float]:
    """Latest close for each symbol (batch download)."""
    syms = sorted({str(s).upper().strip() for s in symbols if str(s).strip()})
    if not syms:
        return {}
    data = yf.download(syms, period="5d", interval="1d", progress=False, auto_adjust=True)
    if data is None or data.empty:
        return {s: float("nan") for s in syms}
    closes = data["Close"]
    out: dict[str, float] = {}
    for s in syms:
        try:
            if isinstance(closes, pd.DataFrame):
                series = closes[s].dropna() if s in closes.columns else pd.Series(dtype=float)
            else:
                series = closes.dropna()  # single symbol -> Series
            out[s] = float(series.iloc[-1]) if not series.empty else float("nan")
        except Exception:
            out[s] = float("nan")
    return out


def review_swing_positions(swings: list[dict], *, trail_pct: float = TRAIL_STOP_PCT) -> pd.DataFrame:
    """Phase + trailing-stop guidance for held swing positions."""
    if not swings:
        return pd.DataFrame()
    prices = _last_prices([s.get("symbol", "") for s in swings])
    rows = []
    for pos in swings:
        sym = str(pos.get("symbol", "")).upper().strip()
        entry = float(pos.get("entry_price") or 0.0)
        stored_stop = float(pos.get("stop_price") or 0.0)
        price = prices.get(sym, float("nan"))

        days_held = _days_since(pos.get("entry_date", ""))
        return_pct = ((price - entry) / entry * 100.0) if entry > 0 and price == price else 0.0
        phase = determine_swing_phase(days_held=days_held, return_pct=return_pct)

        trail_stop = price * (1.0 - trail_pct) if price == price else float("nan")
        suggested_stop = max(stored_stop, trail_stop) if trail_stop == trail_stop else stored_stop

        if price == price and price <= stored_stop:
            action = "STOP HIT -> EXIT"
        elif phase == SwingPhase.TRAIL:
            action = "RAISE STOP (trail winner)"
        elif phase == SwingPhase.REVIEW:
            action = "REVIEW (held 60d+)"
        elif suggested_stop > stored_stop:
            action = "RAISE STOP"
        else:
            action = "HOLD"

        rows.append({
            "Ticker": sym,
            "Entry": round(entry, 2),
            "Price": round(price, 2) if price == price else None,
            "Ret%": round(return_pct, 2),
            "Days": days_held,
            "Stop": round(stored_stop, 2),
            "SugStop": round(suggested_stop, 2) if suggested_stop == suggested_stop else None,
            "Phase": phase.value,
            "Action": action,
        })
    return pd.DataFrame(rows)


def review_pcs_positions(
    spreads: list[dict],
    *,
    profit_target: float = 50.0,
    stop_loss: float = -100.0,
    roll_dte: int = 14,
    manage_dte: int = 21,
) -> pd.DataFrame:
    """Phase + management guidance for open put credit spreads (no Greeks)."""
    if not spreads:
        return pd.DataFrame()
    prices = _last_prices([s.get("symbol", "") for s in spreads])
    rows = []
    for pos in spreads:
        sym = str(pos.get("symbol", "")).upper().strip()
        expiry = str(pos.get("expiration", ""))
        short_k = float(pos.get("short_put") or 0.0)
        long_k = float(pos.get("long_put") or 0.0)
        credit0 = float(pos.get("credit") or 0.0)
        width = short_k - long_k

        dte = _days_since(expiry) * -1  # expiry is in the future -> positive dte
        price = prices.get(sym, float("nan"))
        cur_cost = float("nan")
        try:
            tk = yf.Ticker(sym)
            if expiry in (tk.options or []):
                puts = tk.option_chain(expiry).puts
                puts = puts.set_index("strike")
                if short_k in puts.index and long_k in puts.index:
                    cur_cost = _mid_price(puts.loc[short_k]) - _mid_price(puts.loc[long_k])
        except Exception:
            pass

        profit_pct = ((credit0 - cur_cost) / credit0 * 100.0) if credit0 > 0 and cur_cost == cur_cost else float("nan")
        buffer_pct = ((price - short_k) / price * 100.0) if price == price and price > 0 else float("nan")
        phase = determine_pcs_phase_live(
            dte=dte,
            profit_pct=profit_pct if profit_pct == profit_pct else 0.0,
            buffer_pct=buffer_pct if buffer_pct == buffer_pct else 0.0,
            profit_target=profit_target,
            stop_loss=stop_loss,
            roll_dte=roll_dte,
            manage_dte=manage_dte,
        )

        action = {
            PCSPhase.EXIT: f"CLOSE (>={profit_target:g}% profit)",
            PCSPhase.STOP: f"CLOSE (stop, <={stop_loss:g}% loss)",
            PCSPhase.DEFENSIVE: "DEFEND (under short)",
            PCSPhase.ROLL: f"ROLL (<{roll_dte}DTE, tight)",
            PCSPhase.MANAGE: f"MANAGE (<={manage_dte}DTE: close/roll)",
            PCSPhase.THETA_DECAY: "LET DECAY",
            PCSPhase.OPENED: "HOLD",
        }[phase]

        rows.append({
            "Ticker": sym,
            "Expiry": expiry,
            "DTE": dte,
            "Short": short_k,
            "Long": long_k,
            "Width": round(width, 2),
            "Credit0": round(credit0, 2),
            "CloseCost": round(cur_cost, 2) if cur_cost == cur_cost else None,
            "Profit%": round(profit_pct, 1) if profit_pct == profit_pct else None,
            "Buffer%": round(buffer_pct, 1) if buffer_pct == buffer_pct else None,
            "Phase": phase.value,
            "Action": action,
        })
    return pd.DataFrame(rows)


# =========================================================
# RISK ENGINE
# =========================================================

def calculate_position_heat(position_size: float, stop_distance_pct: float) -> float:
    return position_size * stop_distance_pct


def calculate_portfolio_heat(heats: list[float]) -> float:
    return sum(heats)


def analyze_gap(open_gap_pct: float) -> str:
    if open_gap_pct > 6:
        return "SKIP"
    if open_gap_pct > 3:
        return "REDUCE SIZE"
    return "NORMAL ENTRY"


# =========================================================
# SWING ENTRY PLAN  (for new BUY candidates)
# =========================================================

def build_swing_plan(
    row: pd.Series,
    *,
    risk_per_trade: float = 0.01,
    max_position_size: float = MAX_POSITION_SIZE,
) -> dict:
    """Entry plan for a fresh BUY: stop below 20 DMA, risk-based size, heat, gap timing."""
    price = float(row["Price"])
    stop = float(row["20DMA"])

    stop_distance_pct = (price - stop) / price if price > stop else 0.02
    stop_distance_pct = max(stop_distance_pct, 1e-4)

    # Size so that (size * stop distance) ≈ risk_per_trade, capped at max position.
    position_size = min(max_position_size, risk_per_trade / stop_distance_pct)
    heat = calculate_position_heat(position_size, stop_distance_pct)

    gap_action = analyze_gap(float(row.get("Gap%", 0.0)))
    phase = determine_swing_phase(days_held=0, return_pct=0.0)

    return {
        "Ticker": row["Ticker"],
        "Grade": row["Grade"],
        "Price": round(price, 2),
        "Stop(20DMA)": round(stop, 2),
        "StopDist%": round(stop_distance_pct * 100, 2),
        "Size%": round(position_size * 100, 2),
        "Heat": round(heat, 4),
        "Gap%": round(float(row.get("Gap%", 0.0)), 2),
        "GapAction": gap_action,
        "Phase": phase.value,
    }


# =========================================================
# PCS PLAN  (%-OTM strike selection from live chain)
# =========================================================

def _mid_price(opt_row) -> float:
    bid = float(opt_row.get("bid") or 0.0)
    ask = float(opt_row.get("ask") or 0.0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return float(opt_row.get("lastPrice") or 0.0)


def _leg_is_liquid(opt_row, *, min_oi: int, max_spread_pct: float) -> bool:
    """Reject illiquid / wide-quote option legs that produce garbage mids."""
    oi = float(opt_row.get("openInterest") or 0.0)
    if oi < min_oi:
        return False
    bid = float(opt_row.get("bid") or 0.0)
    ask = float(opt_row.get("ask") or 0.0)
    if bid <= 0 or ask <= 0:
        return False
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return False
    return ((ask - bid) / mid * 100.0) <= max_spread_pct


def build_pcs_plan(
    symbol: str,
    price: float,
    *,
    target_dte: int = 35,
    otm_pct: float = 0.06,
    spread_width_pct: float = 0.03,
    min_open_interest: int = 100,
    max_spread_pct: float = 15.0,
    min_credit_width: float = 0.20,
) -> PutCreditSpread | None:
    """
    Build a put-credit-spread suggestion from the live yfinance option chain.

    Short put ~otm_pct below price; long put ~spread_width_pct below the short.

    Quality gates (skip the trade, return None, if any fail):
      min_open_interest  both legs need OI >= this (default 100)
      max_spread_pct     both legs need bid/ask spread <= this % of mid (default 15)
      min_credit_width   credit/width must be >= this (default 0.20 = 20% of width)

    Returns None if no usable expiry/strikes/quotes are available.
    """
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

    # Only consider liquid strikes so mids are trustworthy.
    liquid = puts[puts.apply(
        lambda r: _leg_is_liquid(r, min_oi=min_open_interest, max_spread_pct=max_spread_pct),
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
    if credit <= 0:
        return None

    # Reject thin premium relative to risk.
    if (credit / width) < min_credit_width:
        return None

    max_risk = width - credit
    pop = 1.0 - (credit / width)  # rough proxy (no Greeks)
    iv_pct = float(short_row.get("impliedVolatility") or 0.0) * 100.0

    return PutCreditSpread(
        symbol=symbol,
        expiration=expiry,
        dte=dte,
        short_put=short_strike,
        long_put=long_strike,
        width=round(width, 2),
        credit=round(credit, 2),
        max_risk=round(max_risk, 2),
        pop=round(pop, 3),
        iv_pct=round(iv_pct, 1),
    )


# =========================================================
# LIFECYCLE REVIEW
# =========================================================

def _actionable(df: pd.DataFrame) -> pd.DataFrame:
    """Rows that need attention (Action other than HOLD / LET DECAY)."""
    if df.empty or "Action" not in df.columns:
        return df
    keep = ~df["Action"].astype(str).str.startswith(("HOLD", "LET DECAY"))
    return df[keep]


def run_review(
    positions_path: str,
    *,
    pcs_profit_target: float = 50.0,
    pcs_stop_loss: float = -100.0,
    pcs_roll_dte: int = 14,
    pcs_manage_dte: int = 21,
    alerts_only: bool = False,
) -> None:
    positions = load_positions(positions_path)
    swings = positions.get("swings", [])
    spreads = positions.get("spreads", [])

    if not swings and not spreads:
        print(f"No positions in {positions_path} "
              f'(expected {{"swings": [...], "spreads": [...]}}).')
        return

    print(f"Reviewing positions from {positions_path}"
          + (" (alerts only)" if alerts_only else ""))

    swing_df = review_swing_positions(swings)
    pcs_df = review_pcs_positions(
        spreads,
        profit_target=pcs_profit_target,
        stop_loss=pcs_stop_loss,
        roll_dte=pcs_roll_dte,
        manage_dte=pcs_manage_dte,
    )

    if alerts_only:
        swing_df = _actionable(swing_df)
        pcs_df = _actionable(pcs_df)

    print("\n")
    print("=" * 120)
    print(" SWING POSITIONS (lifecycle) ")
    print("=" * 120)
    print(swing_df.to_string(index=False) if not swing_df.empty
          else ("No swing alerts." if alerts_only else "No swing positions."))

    print("\n")
    print("=" * 120)
    print(" PUT CREDIT SPREADS (lifecycle) ")
    print("=" * 120)
    print(pcs_df.to_string(index=False) if not pcs_df.empty
          else ("No spread alerts." if alerts_only else "No spread positions."))

    print("\nDone.")


# =========================================================
# MAIN
# =========================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Funnel scanner BUY candidates into swing + PCS plans."
    )
    parser.add_argument("--tickers-file", default=str(DEFAULT_TICKERS_FILE))
    parser.add_argument("--min-grade", default="B", choices=["A", "B", "C", "D"],
                        help="Minimum setup grade for BUY funnel (default B).")
    parser.add_argument("--risk-per-trade", type=float, default=0.01,
                        help="Account risk fraction per trade (default 0.01 = 1%%).")
    parser.add_argument("--target-dte", type=int, default=35,
                        help="Target days-to-expiry for PCS (default 35).")
    parser.add_argument("--otm-pct", type=float, default=0.06,
                        help="Short put %% OTM below price (default 0.06 = 6%%).")
    parser.add_argument("--no-pcs", action="store_true",
                        help="Skip option-chain PCS plans (swing plan only).")
    parser.add_argument("--review", action="store_true",
                        help="Review held positions from positions.json (lifecycle), skip BUY funnel.")
    parser.add_argument("--positions", default=str(DEFAULT_POSITIONS_FILE),
                        help=f"Positions file for --review (default: {DEFAULT_POSITIONS_FILE.name}).")
    parser.add_argument("--pcs-profit-target", type=float, default=50.0,
                        help="Close spread at this %% of credit captured (default 50).")
    parser.add_argument("--pcs-stop-loss", type=float, default=-100.0,
                        help="Close spread at this %% loss of credit (default -100 = -1x credit).")
    parser.add_argument("--pcs-roll-dte", type=int, default=14,
                        help="Roll spread when DTE below this and buffer tight (default 14).")
    parser.add_argument("--pcs-manage-dte", type=int, default=21,
                        help="Manage (close/roll) at/below this DTE regardless (default 21).")
    parser.add_argument("--alerts-only", action="store_true",
                        help="With --review: show only positions needing action (skip HOLD).")
    args = parser.parse_args()

    if args.review:
        run_review(
            args.positions,
            pcs_profit_target=args.pcs_profit_target,
            pcs_stop_loss=args.pcs_stop_loss,
            pcs_roll_dte=args.pcs_roll_dte,
            pcs_manage_dte=args.pcs_manage_dte,
            alerts_only=args.alerts_only,
        )
        return

    tickers = read_symbols_from_file(args.tickers_file)
    if not tickers:
        raise SystemExit(f"No tickers in {args.tickers_file}")

    print(f"Loaded {len(tickers)} symbol(s); scanning...")
    results_df = run_scan(tickers)
    if results_df.empty:
        print("No scan results.")
        return

    buys = select_buy_candidates(results_df, min_grade=args.min_grade)
    print(f"BUY candidates (Grade >= {args.min_grade}): {len(buys)}")
    if buys.empty:
        print("No BUY candidates to funnel.")
        return

    # ---- Swing entry plans ----
    swing_rows = [
        build_swing_plan(row, risk_per_trade=args.risk_per_trade)
        for _, row in buys.iterrows()
    ]
    swing_df = pd.DataFrame(swing_rows)

    print("\n")
    print("=" * 120)
    print(" SWING ENTRY PLAN (BUY funnel) ")
    print("=" * 120)
    print(swing_df.to_string(index=False))

    total_heat = calculate_portfolio_heat([r["Heat"] for r in swing_rows])
    print(f"\nPortfolio heat if all entered: {total_heat:.2%} "
          f"(max {MAX_PORTFOLIO_HEAT:.0%})")
    if total_heat > MAX_PORTFOLIO_HEAT:
        print("WARNING: combined heat exceeds limit — size down or take fewer.")

    # ---- PCS plans ----
    if args.no_pcs:
        print("\nDone.")
        return

    print("\n")
    print("=" * 120)
    print(" PUT CREDIT SPREAD PLAN (%-OTM) ")
    print("=" * 120)

    pcs_rows = []
    for _, row in buys.iterrows():
        sym = str(row["Ticker"])
        plan = build_pcs_plan(
            sym,
            float(row["Price"]),
            target_dte=args.target_dte,
            otm_pct=args.otm_pct,
        )
        if plan is None:
            print(f"{sym}: no usable option chain / strikes.")
            continue
        pcs_rows.append({
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

    if pcs_rows:
        print(pd.DataFrame(pcs_rows).to_string(index=False))
    else:
        print("No PCS plans produced.")

    print("\nDone.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
