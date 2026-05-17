"""
Shared helpers for scripts/stocks CLI tools.

Adds azure/functions/stocks-func-app to sys.path so monitoring.* and wb4u_* imports work.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent
_FUNC_APP = _REPO_ROOT / "azure" / "functions" / "stocks-func-app"


def ensure_func_app_path() -> Path:
    """Insert stocks-func-app on sys.path (idempotent). Returns that directory."""
    root = str(_FUNC_APP)
    if root not in sys.path:
        sys.path.insert(0, root)
    return _FUNC_APP


def is_valid_symbol(sym: str) -> bool:
    if not sym:
        return False
    s = str(sym).upper()
    return s.replace(".", "").replace("-", "").isalpha()


def normalize_symbol(sym: str) -> str:
    return str(sym).upper().strip()


def read_symbols_from_file(path: str) -> List[str]:
    """
    Read ticker symbols from a text or CSV file.

    Plain text: one or more symbols per line; commas/semicolons/whitespace OK.
    CSV: column ``ticker``, ``symbol``, or ``sym`` if header present; else column 0.
    """
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Ticker file not found: {path}")

    symbols: List[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        sym = normalize_symbol(raw)
        if not is_valid_symbol(sym):
            return
        if sym not in seen:
            seen.add(sym)
            symbols.append(sym)

    if path.lower().endswith(".csv"):
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            sample = f.read(8192)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.reader(f, dialect)
            rows = list(reader)
        if not rows:
            return []
        header = [str(c or "").strip().lower() for c in rows[0]]
        col_idx = 0
        name_to_idx = {h: i for i, h in enumerate(header) if h}
        for key in ("ticker", "symbol", "sym"):
            if key in name_to_idx:
                col_idx = name_to_idx[key]
                data_rows = rows[1:]
                break
        else:
            data_rows = rows
        for row in data_rows:
            if not row or col_idx >= len(row):
                continue
            cell = (row[col_idx] or "").strip()
            if not cell or cell.startswith("#"):
                continue
            add(cell)
        return symbols

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            for part in re.split(r"[,;\s]+", line):
                part = part.strip()
                if part:
                    add(part)
    return symbols


def load_ticker_list_json(path: Path, *, fallback: Optional[List[str]] = None) -> List[str]:
    if not path.is_file():
        if fallback:
            return sorted({normalize_symbol(t) for t in fallback if is_valid_symbol(t)})
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        raw = data.get("tickers") or []
    elif isinstance(data, list):
        raw = data
    else:
        raw = []
    return sorted({normalize_symbol(t) for t in raw if is_valid_symbol(t)})


def save_ticker_list_json(path: Path, tickers: List[str], *, meta: Optional[Dict[str, Any]] = None) -> None:
    norm = sorted({normalize_symbol(t) for t in tickers if is_valid_symbol(t)})
    payload: Dict[str, Any] = {
        "tickers": norm,
        "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if meta:
        payload.update(meta)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_trailing_state_json(path: Path) -> Dict[str, Dict[str, float]]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("positions") if isinstance(data, dict) else data
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, float]] = {}
    for k, v in raw.items():
        sym = normalize_symbol(k)
        if not sym or not isinstance(v, dict):
            continue
        try:
            hi = float(v.get("high_seen", 0.0) or 0.0)
        except (TypeError, ValueError):
            hi = 0.0
        out[sym] = {"high_seen": hi}
    return out


def save_trailing_state_json(
    path: Path, positions: Dict[str, Dict[str, float]], *, meta: Optional[Dict[str, Any]] = None
) -> None:
    norm: Dict[str, Dict[str, float]] = {}
    for k, v in positions.items():
        sym = normalize_symbol(k)
        if not sym:
            continue
        try:
            hi = float((v or {}).get("high_seen", 0.0) or 0.0)
        except (TypeError, ValueError):
            hi = 0.0
        norm[sym] = {"high_seen": hi}
    payload: Dict[str, Any] = {
        "positions": norm,
        "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if meta:
        payload["meta"] = meta
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def print_run_messages(result: Dict[str, Any]) -> None:
    for msg in result.get("messages") or []:
        print(msg)
    exited = result.get("exited") or []
    if exited:
        print("\nExited:", ", ".join(str(x) for x in exited))
    rows = result.get("holdings_rows") or []
    if rows:
        print("\nHoldings snapshot:")
        print(f"{'Ticker':<8} {'Last':>10} {'High':>10} {'Stop':>10} {'RS':>8}")
        for r in rows:
            t = r.get("ticker", "")
            last = r.get("last")
            hi = r.get("high_seen")
            stop = r.get("stop")
            rs = r.get("rs")
            def _f(x: Any) -> str:
                try:
                    v = float(x)
                    if v != v:
                        return "—"
                    return f"{v:.2f}"
                except (TypeError, ValueError):
                    return "—"
            print(f"{t:<8} {_f(last):>10} {_f(hi):>10} {_f(stop):>10} {_f(rs):>8}")
