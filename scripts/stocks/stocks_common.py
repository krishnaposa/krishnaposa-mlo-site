"""
Shared helpers for scripts/stocks CLI tools.

Adds azure/functions/stocks-func-app to sys.path so monitoring.* and wb4u_* imports work.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent
_FUNC_APP = _REPO_ROOT / "azure" / "functions" / "stocks-func-app"

# Default local JSON paths (scripts/stocks/)
LOCAL_LIST_FILE = Path(os.getenv("LOCAL_LIST_FILE", str(_SCRIPT_DIR / "local-list.json"))).expanduser()
HOLDINGS_LIST_FILE = Path(os.getenv("HOLDINGS_LIST_FILE", str(_SCRIPT_DIR / "holdings-list.json"))).expanduser()
UNIVERSE_FILE = Path(os.getenv("UNIVERSE_FILE", str(_SCRIPT_DIR / "universe.json"))).expanduser()
MOMENTUM_PORTFOLIO_FILE = Path(
    os.getenv("MOMENTUM_PORTFOLIO_FILE", str(_SCRIPT_DIR / "momentum-analyzer.json"))
).expanduser()

logger = logging.getLogger(__name__)


def use_azure_storage() -> bool:
    """When true, scripts use Azure blob (MONITOR_STORAGE) instead of local JSON patches."""
    return os.getenv("STOCKS_USE_AZURE_STORAGE", "").strip().lower() in ("1", "true", "yes", "on")


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


def install_local_holdings_adapters(
    *,
    list_file: Path | None = None,
    state_file: Path | None = None,
) -> None:
    """Point local_list_utils holdings APIs at local JSON (no MONITOR_STORAGE)."""
    if use_azure_storage():
        ensure_func_app_path()
        return

    ensure_func_app_path()
    import local_list_utils as ll  # noqa: E402

    list_path = (list_file or HOLDINGS_LIST_FILE).expanduser()
    state_path = (state_file or Path(os.getenv("HOLDINGS_STATE_FILE", str(_SCRIPT_DIR / "holdings-trailing-state.json")))).expanduser()

    def _load_list(initial_fallback: Optional[List[str]] = None) -> List[str]:
        return load_ticker_list_json(list_path, fallback=initial_fallback)

    def _save_list(tickers: List[str], meta: Optional[Dict[str, Any]] = None) -> None:
        save_ticker_list_json(list_path, tickers, meta=meta)

    def _load_state() -> Dict[str, Dict[str, Any]]:
        return load_trailing_state_json(state_path)

    def _save_state(positions: Dict[str, Dict[str, Any]], meta: Optional[Dict[str, Any]] = None) -> None:
        save_trailing_state_json(state_path, positions, meta=meta)

    def _state_desc() -> str:
        return f"file:{state_path}"

    ll.load_holdings_list = _load_list
    ll.save_holdings_list = _save_list
    ll.load_holdings_trailing_state = _load_state
    ll.save_holdings_trailing_state = _save_state
    ll.holdings_trailing_storage_description = _state_desc


def install_local_monitor_adapters(
    *,
    local_list_file: Path | None = None,
    holdings_list_file: Path | None = None,
    universe_file: Path | None = None,
    momentum_file: Path | None = None,
) -> None:
    """
    Use local JSON for quant monitor / run_monitor (no MONITOR_STORAGE required).

    Files: local-list.json, holdings-list.json, universe.json (optional), momentum-analyzer.json

    Set STOCKS_USE_AZURE_STORAGE=1 to keep Azure blob behavior instead.
    """
    if use_azure_storage():
        ensure_func_app_path()
        return

    ensure_func_app_path()
    import local_list_utils as ll  # noqa: E402
    import momentum_portfolio_utils as mpu  # noqa: E402

    local_path = (local_list_file or LOCAL_LIST_FILE).expanduser()
    holdings_path = (holdings_list_file or HOLDINGS_LIST_FILE).expanduser()
    universe_path = (universe_file or UNIVERSE_FILE).expanduser()
    momentum_path = (momentum_file or MOMENTUM_PORTFOLIO_FILE).expanduser()
    os.environ["MOMENTUM_PORTFOLIO_FILE"] = str(momentum_path)

    def _load_local_list(initial_fallback: Optional[List[str]] = None) -> List[str]:
        return load_ticker_list_json(local_path, fallback=initial_fallback)

    def _save_local_list(tickers: List[str], meta: Optional[Dict[str, Any]] = None) -> None:
        save_ticker_list_json(local_path, tickers, meta=meta)

    def _load_holdings(initial_fallback: Optional[List[str]] = None) -> List[str]:
        return load_ticker_list_json(holdings_path, fallback=initial_fallback)

    def _save_holdings(tickers: List[str], meta: Optional[Dict[str, Any]] = None) -> None:
        save_ticker_list_json(holdings_path, tickers, meta=meta)

    def _read_universe_blob() -> Optional[Dict[str, Any]]:
        if not universe_path.is_file():
            return None
        try:
            data = json.loads(universe_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception as e:
            logger.warning("[universe] could not read %s: %s", universe_path, e)
            return None

    ll.load_local_list = _load_local_list
    ll.save_local_list = _save_local_list
    ll.load_holdings_list = _load_holdings
    ll.save_holdings_list = _save_holdings
    # Avoid importing universe_utils (pulls azure.storage.blob). Stub before monitor loads.
    if "universe_utils" not in sys.modules:
        _uu = types.ModuleType("universe_utils")
        _uu.read_universe_blob = _read_universe_blob
        sys.modules["universe_utils"] = _uu
    else:
        sys.modules["universe_utils"].read_universe_blob = _read_universe_blob
    mon = sys.modules.get("monitoring.monitor")
    if mon is not None:
        mon.read_universe_blob = _read_universe_blob
    mpu._use_blob = lambda: False
    mpu.default_local_portfolio_path = lambda: momentum_path


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
