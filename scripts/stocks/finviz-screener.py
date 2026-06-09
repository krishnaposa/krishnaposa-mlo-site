#!/usr/bin/env python3
"""
Print tickers from a Finviz screener URL (wb4u_finviz).

Usage:
  python finviz-screener.py
  python finviz-screener.py --url "https://finviz.com/screener.ashx?v=111&f=..."
  python finviz-screener.py --max 40 --out finviz_picks.txt
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from stocks_common import ensure_func_app_path, save_ticker_list_json

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_URL = os.getenv(
    "MOMENTUM_FINVIZ_URL",
    "https://finviz.com/screener.ashx?v=111&f=cap_midover,sh_price_o5,ta_highlow52w_nh",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Finviz screener symbols.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Finviz screener URL with ?f= filters.")
    parser.add_argument("--max", type=int, default=60, help="Max symbols to return (default 60).")
    parser.add_argument(
        "--out",
        metavar="PATH",
        help="Optional: write tickers to a txt file (one per line) or JSON list via .json extension.",
    )
    parser.add_argument(
        "--save-json",
        metavar="PATH",
        help="Write { \"tickers\": [...] } JSON (e.g. holdings-list.json).",
    )
    args = parser.parse_args()

    ensure_func_app_path()
    import wb4u_finviz  # noqa: E402

    syms = wb4u_finviz.symbols_from_screener_url(args.url, max_symbols=max(1, args.max))
    print(f"Finviz: {len(syms)} symbol(s)")
    if syms:
        preview = ", ".join(syms[:50])
        more = f" … (+{len(syms) - 50} more)" if len(syms) > 50 else ""
        print(preview + more)

    if args.out:
        out = Path(args.out).expanduser()
        if out.suffix.lower() == ".json":
            save_ticker_list_json(out, syms, meta={"source": "finviz_screener"})
        else:
            out.write_text("\n".join(syms) + "\n", encoding="utf-8")
        print(f"Wrote {out}")

    if args.save_json:
        save_ticker_list_json(Path(args.save_json).expanduser(), syms, meta={"source": "finviz_screener"})
        print(f"Wrote {args.save_json}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
