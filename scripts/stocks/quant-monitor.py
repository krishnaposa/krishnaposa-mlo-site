#!/usr/bin/env python3
"""
Daily quant monitor — scores tickers and prints a summary (no CSV by default).

Wraps azure/functions/stocks-func-app/monitoring/monitor.run_monitor().
Uses local JSON by default (local-list.json, holdings-list.json, momentum-analyzer.json).

Usage:
  python quant-monitor.py
  python quant-monitor.py --tickers-file watchlist.txt
  python quant-monitor.py --tickers AAPL MSFT NVDA
  python quant-monitor.py --write-csv --out-dir ./monitor_out
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import sys
import warnings
from pathlib import Path

from stocks_common import install_local_monitor_adapters, read_symbols_from_file

warnings.filterwarnings("ignore")

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUT = SCRIPT_DIR / "monitor_out"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run daily quant monitor (terminal summary; CSV optional).")
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
        "--write-csv",
        action="store_true",
        help="Write daily_snapshot_*.csv and leaders_*.csv (off by default).",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT),
        help=f"CSV output directory when --write-csv is set (default: {DEFAULT_OUT}).",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("DAILY_MONITOR_LOG_LEVEL", "INFO"),
        help="Logging level (default INFO).",
    )
    parser.add_argument(
        "--use-azure",
        action="store_true",
        help="Use MONITOR_STORAGE blob for lists/universe (default: local JSON in scripts/stocks/).",
    )
    args = parser.parse_args()

    if args.use_azure:
        os.environ["STOCKS_USE_AZURE_STORAGE"] = "1"

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

    install_local_monitor_adapters()
    from monitoring.monitor import run_monitor  # noqa: E402

    out_dir = Path(args.out_dir).expanduser()

    logging.info("=== Quant monitor (local) ===")
    if tickers:
        logging.info("CLI watchlist: %d symbol(s)", len(tickers))
    else:
        logging.info("Universe from local-list.json, holdings-list.json, momentum-analyzer.json (+ Finviz if enabled)")

    df_all, df_leaders = run_monitor(tickers)

    if args.write_csv:
        out_dir.mkdir(parents=True, exist_ok=True)
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
