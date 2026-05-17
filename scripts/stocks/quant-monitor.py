#!/usr/bin/env python3
"""
Daily quant monitor — scores tickers and writes CSV snapshots locally.

Wraps azure/functions/stocks-func-app/monitoring/monitor.run_monitor() (same as run_daily_monitor.py).

Usage:
  python quant-monitor.py
  python quant-monitor.py --tickers-file watchlist.txt
  python quant-monitor.py --tickers AAPL MSFT NVDA
  python quant-monitor.py --out-dir ./monitor_out
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import sys
import warnings
from pathlib import Path

from stocks_common import ensure_func_app_path, read_symbols_from_file

warnings.filterwarnings("ignore")

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUT = SCRIPT_DIR / "monitor_out"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run daily quant monitor (local CSV output).")
    parser.add_argument(
        "--tickers-file",
        metavar="PATH",
        help="Optional watchlist file (txt/csv) — limits the run to these symbols.",
    )
    parser.add_argument(
        "--tickers",
        nargs="*",
        help="Optional tickers on the command line (combined with --tickers-file).",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT),
        help=f"Directory for CSV output (default: {DEFAULT_OUT}).",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("DAILY_MONITOR_LOG_LEVEL", "INFO"),
        help="Logging level (default INFO).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    tickers: list[str] = []
    if args.tickers_file:
        tickers.extend(read_symbols_from_file(args.tickers_file))
    if args.tickers:
        from stocks_common import is_valid_symbol, normalize_symbol

        tickers.extend(normalize_symbol(t) for t in args.tickers if is_valid_symbol(t))
    tickers = sorted(set(tickers))

    ensure_func_app_path()
    from monitoring.monitor import run_monitor  # noqa: E402

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    logging.info("=== Quant monitor (local) ===")
    if tickers:
        logging.info("Watchlist: %d symbol(s)", len(tickers))
    else:
        logging.info("No watchlist — using monitor default universe / local_list from Azure if configured")

    df_all, df_leaders = run_monitor(tickers)

    stamp = datetime.date.today().strftime("%Y-%m-%d")
    csv_all = out_dir / f"daily_snapshot_{stamp}.csv"
    csv_lead = out_dir / f"leaders_{stamp}.csv"
    df_all.to_csv(csv_all, index=False)
    df_leaders.to_csv(csv_lead, index=False)
    logging.info("Saved %s and %s", csv_all, csv_lead)

    if not df_all.empty and "buy_flag" in df_all.columns:
        picks = df_all[df_all["buy_flag"]]
        if not picks.empty and "ticker" in picks.columns:
            print("\nTop buy_flag picks:")
            cols = [c for c in ("ticker", "score") if c in picks.columns]
            print(picks[cols].head(12).reset_index(drop=True))

    if not df_leaders.empty:
        print("\nLeaders (5d & 21d up):")
        print(df_leaders.head(15).reset_index(drop=True))

    logging.info("=== Done ===")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
