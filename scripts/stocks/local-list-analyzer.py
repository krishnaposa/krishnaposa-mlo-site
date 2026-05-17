#!/usr/bin/env python3
"""
Manage local-list.json — primary watch universe for quant-monitor.py (local mode, no Azure).

Usage:
  python local-list-analyzer.py --set-from-file watchlist.txt
  python local-list-analyzer.py --set-from-file watchlist.txt --merge
  python local-list-analyzer.py --show
  python local-list-analyzer.py --export watchlist.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stocks_common import (
    LOCAL_LIST_FILE,
    load_ticker_list_json,
    read_symbols_from_file,
    save_ticker_list_json,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage local-list.json ticker universe.")
    parser.add_argument("--set-from-file", metavar="PATH", help="Replace or merge tickers from file.")
    parser.add_argument("--merge", action="store_true", help="Union with existing list.")
    parser.add_argument("--show", action="store_true", help="Print current tickers.")
    parser.add_argument("--export", metavar="PATH", help="Write tickers to a text file (one per line).")
    args = parser.parse_args()

    if args.set_from_file:
        incoming = read_symbols_from_file(args.set_from_file)
        if args.merge:
            cur = load_ticker_list_json(LOCAL_LIST_FILE)
            merged = sorted(set(cur) | set(incoming))
            save_ticker_list_json(LOCAL_LIST_FILE, merged, meta={"source": "merge"})
            print(f"Merged → {len(merged)} symbol(s) in {LOCAL_LIST_FILE}")
        else:
            save_ticker_list_json(LOCAL_LIST_FILE, incoming, meta={"source": "replace"})
            print(f"Wrote {len(incoming)} symbol(s) to {LOCAL_LIST_FILE}")
        return

    if args.export:
        syms = load_ticker_list_json(LOCAL_LIST_FILE)
        Path(args.export).expanduser().write_text("\n".join(syms) + "\n", encoding="utf-8")
        print(f"Exported {len(syms)} symbol(s) to {args.export}")
        return

    syms = load_ticker_list_json(LOCAL_LIST_FILE)
    if args.show or not any([args.set_from_file, args.export]):
        print(f"{LOCAL_LIST_FILE}: {len(syms)} symbol(s)")
        if syms:
            print(", ".join(syms))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
