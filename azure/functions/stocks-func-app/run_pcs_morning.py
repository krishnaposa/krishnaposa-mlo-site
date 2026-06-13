#!/usr/bin/env python3
"""Local entry: morning PCS execution email only."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from monitoring.pcs_morning import run_pcs_morning  # noqa: E402


def main() -> None:
    result = run_pcs_morning()
    opp = result.get("opportunities") or {}
    life = result.get("lifecycle") or {}
    print(
        f"PCS morning done — ideas={len(opp.get('tickers') or [])} "
        f"actionable={len(life.get('actionable') or [])} "
        f"email_sent={result.get('email_sent')}"
    )


if __name__ == "__main__":
    main()
