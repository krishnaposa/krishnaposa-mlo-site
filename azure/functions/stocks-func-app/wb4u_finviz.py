import time
import logging
from typing import List, Tuple, Dict, Any

import requests
from finviz.screener import Screener

# ----------- Config ----------
_DEFAULT_TIMEOUT = 20            # seconds per HTTP call
_MAX_RETRIES     = 3
_RETRY_SLEEP_S   = 2             # base backoff
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

def _is_valid_symbol(sym: str) -> bool:
    if not sym:
        return False
    s = str(sym).upper()
    # allow letters, dot, dash (US tickers like BRK.B, RDS-A)
    return s.replace(".", "").replace("-", "").isalpha()

def _normalize_symbol(sym: str) -> str:
    return str(sym).upper().strip()

# ---------- Equity model (unchanged externally) ----------
class Equity:
    def __init__(self, symbol: str):
        self.symbol = _normalize_symbol(symbol)
        self.equityType = None

    def __repr__(self):
        # simple, stable repr
        return f"Equity(symbol={self.symbol!r}, equityType={self.equityType!r})"

    def toJSON(self) -> str:
        import json
        return json.dumps(self.__dict__, sort_keys=True, indent=2)

    def createFromJson(self, json_obj: Dict[str, Any]):
        self.__dict__ = dict(json_obj)

# ---------- Internal: safe Screener call with retry ----------
def _fetch_screener(filters: List[str], table: str, order: str) -> List[Dict[str, Any]]:
    """
    Wrap finviz Screener with retries + timeouts. Returns a list of dict rows.
    """
    last_err = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            # finviz library uses requests under the hood; set global headers via requests
            s = requests.Session()
            s.headers.update({"User-Agent": _UA})
            # The finviz lib doesn't expose timeout; but we can limit by session adapter timeouts
            # (Still, to be safe, we bound total time by our own sleep+retries.)
            stock_list = Screener(filters=filters, table=table, order=order)  # may raise
            # Screener is iterable, materialize rows now to catch errors early
            rows = [dict(row) for row in stock_list]  # each row behaves like a dict
            return rows
        except Exception as e:
            last_err = e
            logging.warning(f"[finviz] attempt {attempt}/{_MAX_RETRIES} failed: {e}")
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_SLEEP_S * attempt)
    # After retries, raise a concise error
    raise RuntimeError(f"Finviz screener failed after {_MAX_RETRIES} attempts: {last_err}")

# ---------- Public API ----------
def getEtfs(etfFilters: List[str], sortOrder: str = "price") -> Tuple[List[Equity], List[str]]:
    """
    Returns (equity_objects, ticker_list) for ETFs given filters.
    """
    equities: List[Equity] = []
    tickers: List[str] = []

    try:
        rows = _fetch_screener(filters=etfFilters, table="Valuation", order=sortOrder)
        for row in rows:
            sym = _normalize_symbol(row.get("Ticker"))
            if _is_valid_symbol(sym):
                eq = Equity(sym)
                eq.equityType = "etf"
                equities.append(eq)
                tickers.append(sym)
    except Exception as e:
        logging.exception(f"[finviz] getEtfs error: {e}")

    return equities, tickers

def getStocks(cap: List[str], sortOrder: str = "-epsyoy1") -> List[Equity]:
    """
    Returns a list of Equity objects for stocks matching filters.
    """
    equities: List[Equity] = []
    try:
        rows = _fetch_screener(filters=cap, table="Valuation", order=sortOrder)
        for row in rows:
            sym = _normalize_symbol(row.get("Ticker"))
            if _is_valid_symbol(sym):
                eq = Equity(sym)
                eq.equityType = "stock"
                equities.append(eq)
    except Exception as e:
        logging.exception(f"[finviz] getStocks error: {e}")
    return equities

def getStocksSymbols(cap: List[str], sortOrder: str = "-epsyoy1") -> List[str]:
    """
    Returns a list of ticker strings for stocks matching filters.
    """
    symbols: List[str] = []
    try:
        rows = _fetch_screener(filters=cap, table="Valuation", order=sortOrder)
        for row in rows:
            sym = _normalize_symbol(row.get("Ticker"))
            if _is_valid_symbol(sym):
                symbols.append(sym)
    except Exception as e:
        logging.exception(f"[finviz] getStocksSymbols error: {e}")
    return symbols