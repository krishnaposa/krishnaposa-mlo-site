#!/usr/bin/env python3
"""
Holdings list — trailing stop + RS exits (local JSON files).

Mirrors monitoring.momentum_portfolio.run_holdings_trailing_daily() but persists under
scripts/stocks/ by default (no Azure required).

Files (same folder as this script):
  holdings-list.json           — { "tickers": ["AAPL", ...] }
  holdings-trailing-state.json — { "positions": { "AAPL": { "high_seen": 195.5 } } }

Env (optional, passed through to momentum_portfolio):
  MOMENTUM_RS_EXIT_THRESHOLD     — default 70
  MOMENTUM_TRAILING_STOP_PCT     — default 0.15
  MOMENTUM_RS_LOOKBACK_PERIOD    — default 6mo
  MOMENTUM_RS_INCLUDE_SPY=0      — rank RS only within holdings (recommended for “best in list”); default 1 includes SPY
  HOLDINGS_LIST_REMOVE_ON_EXIT=1 — remove exited tickers from holdings-list.json

Usage:
  python holdings-analyzer.py --set-from-file my_tickers.txt
  python holdings-analyzer.py --set-from-file picks.txt --merge
  python holdings-analyzer.py --set-from-file my_tickers.txt --push-azure
  python holdings-analyzer.py --push-azure       # upload holdings-list.json to Azure blob
  python holdings-analyzer.py                    # daily trailing + RS check
  python holdings-analyzer.py --remove-on-exit   # also drop exits from list file

  --push-azure requires MONITOR_STORAGE (or AzureWebJobsStorage).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from stocks_common import (
    HOLDINGS_LIST_FILE,
    install_local_holdings_adapters,
    load_ticker_list_json,
    print_run_messages,
    push_holdings_list_to_azure,
    read_symbols_from_file,
    save_ticker_list_json,
)

SCRIPT_DIR = Path(__file__).resolve().parent
HOLDINGS_STATE_FILE = Path(
    os.getenv("HOLDINGS_STATE_FILE", str(SCRIPT_DIR / "holdings-trailing-state.json"))
).expanduser()


def set_holdings_from_file(path: str, *, merge: bool) -> List[str]:
    incoming = read_symbols_from_file(path)
    if merge:
        cur = load_ticker_list_json(HOLDINGS_LIST_FILE)
        merged = sorted(set(cur) | set(incoming))
        save_ticker_list_json(HOLDINGS_LIST_FILE, merged, meta={"source": "merge_file"})
        print(f"Merged {len(incoming)} symbol(s) → {len(merged)} total in {HOLDINGS_LIST_FILE}")
        return merged
    save_ticker_list_json(HOLDINGS_LIST_FILE, incoming, meta={"source": "replace_file"})
    print(f"Wrote {len(incoming)} symbol(s) to {HOLDINGS_LIST_FILE}")
    return incoming


def push_holdings_to_azure(*, meta_source: str = "push_azure") -> None:
    tickers = load_ticker_list_json(HOLDINGS_LIST_FILE)
    if not tickers:
        raise SystemExit(f"No tickers in {HOLDINGS_LIST_FILE} — use --set-from-file first.")
    dest = push_holdings_list_to_azure(tickers, meta={"source": meta_source})
    print(f"Pushed {len(tickers)} symbol(s) to Azure ({dest})")


def run_daily(*, remove_on_exit: bool) -> None:
    install_local_holdings_adapters(list_file=HOLDINGS_LIST_FILE, state_file=HOLDINGS_STATE_FILE)
    if remove_on_exit:
        os.environ["HOLDINGS_LIST_REMOVE_ON_EXIT"] = "1"
    from monitoring.momentum_portfolio import run_holdings_trailing_daily  # noqa: E402

    result = run_holdings_trailing_daily()
    print_run_messages(result)
    if result.get("state_saved"):
        print(f"\nTrailing state saved: {HOLDINGS_STATE_FILE}")
    if result.get("list_saved"):
        print(f"Holdings list updated: {HOLDINGS_LIST_FILE}")
    print(f"\nDaily check complete ({result.get('timestamp', '')}).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Holdings list trailing stop + RS (local JSON).")
    parser.add_argument(
        "--set-from-file",
        metavar="PATH",
        help="Set holdings-list.json from a ticker file (txt/csv).",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="With --set-from-file: union with existing symbols instead of replace.",
    )
    parser.add_argument(
        "--push-azure",
        action="store_true",
        help="Upload holdings-list.json to Azure blob (MONITOR_STORAGE / AzureWebJobsStorage).",
    )
    parser.add_argument(
        "--remove-on-exit",
        action="store_true",
        help="Remove exited symbols from holdings-list.json after daily run.",
    )
    args = parser.parse_args()

    if args.set_from_file:
        set_holdings_from_file(args.set_from_file, merge=args.merge)

    if args.push_azure:
        src = "merge_file_push" if (args.set_from_file and args.merge) else (
            "replace_file_push" if args.set_from_file else "push_azure"
        )
        push_holdings_to_azure(meta_source=src)

    run_daily_after = args.remove_on_exit or (not args.set_from_file and not args.push_azure)
    if not run_daily_after:
        return

    run_daily(remove_on_exit=args.remove_on_exit)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
