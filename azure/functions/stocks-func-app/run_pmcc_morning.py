#!/usr/bin/env python3
"""Local entry: morning PMCC screening email only."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from monitoring.pmcc_morning import run_pmcc_morning  # noqa: E402


def main() -> None:
    result = run_pmcc_morning()
    opp = result.get("opportunities") or {}
    life = result.get("lifecycle") or {}
    print(
        f"PMCC morning done — ideas={len(opp.get('tickers') or [])} "
        f"actionable={len(life.get('actionable') or [])} "
        f"email_sent={result.get('email_sent')}"
    )


if __name__ == "__main__":
    main()
