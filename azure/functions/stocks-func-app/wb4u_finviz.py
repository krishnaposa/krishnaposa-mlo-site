import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import requests
from lxml import html

# ----------- Config ----------
_DEFAULT_TIMEOUT = 20  # seconds per HTTP call
_MAX_RETRIES = 3
_RETRY_SLEEP_S = 2  # base backoff
_PAGE_SIZE = 20
_MAX_PAGES = 25  # hard cap (~500 tickers)
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

# Finviz screener view codes (same as finviz.screener.TABLE_TYPES)
_TABLE_CODES = {
    "Overview": "111",
    "Valuation": "121",
    "Ownership": "131",
    "Performance": "141",
    "Custom": "152",
    "Financial": "161",
    "Technical": "171",
}


def _is_valid_symbol(sym: str) -> bool:
    if not sym:
        return False
    s = str(sym).upper().strip()
    # Reject 1-char junk from broken Finviz HTML parses (real 1-letter names are rare).
    if len(s) < 2 or len(s) > 8:
        return False
    # allow letters, dot, dash (US tickers like BRK.B, RDS-A / PBR-A)
    return s.replace(".", "").replace("-", "").isalpha()


def _normalize_symbol(sym: str) -> str:
    if sym is None:
        return ""
    return str(sym).upper().strip()


def _ticker_from_row(row: Dict[str, Any]) -> str:
    """Pull ticker from a screener row dict."""
    if not isinstance(row, dict):
        return ""
    for key in ("Ticker", "ticker", "Symbol", "symbol"):
        if key in row and row[key] is not None:
            return _normalize_symbol(row[key])
    return ""


# ---------- Equity model (unchanged externally) ----------
class Equity:
    def __init__(self, symbol: str):
        self.symbol = _normalize_symbol(symbol)
        self.equityType = None

    def __repr__(self):
        return f"Equity(symbol={self.symbol!r}, equityType={self.equityType!r})"

    def toJSON(self) -> str:
        import json

        return json.dumps(self.__dict__, sort_keys=True, indent=2)

    def createFromJson(self, json_obj: Dict[str, Any]):
        self.__dict__ = dict(json_obj)


def _extract_tickers_from_html(page_html: str) -> List[str]:
    """
    Extract screener tickers from Finviz HTML.

    Finviz embeds a logo fallback letter (<span>S</span>) plus the real ticker
    (<a class="tab-link">SUZ</a>) in the same cell. The stock finviz library's
    ``td//text()`` scrape treats both as columns and shifts every field — so
    Ticker becomes "S" and Company becomes "SUZ". Prefer ``data-boxover-ticker``.
    """
    if not page_html:
        return []
    try:
        doc = html.fromstring(page_html)
    except Exception as e:
        logging.warning("[finviz] HTML parse failed: %s", e)
        return []

    out: List[str] = []
    seen = set()
    for el in doc.xpath("//*[@data-boxover-ticker]"):
        sym = _normalize_symbol(el.get("data-boxover-ticker"))
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)

    if out:
        return out

    # Fallback: stock?t= / quote.ashx?t= links whose visible text looks like a ticker
    for a in doc.xpath("//a[contains(@href,'stock?t=') or contains(@href,'quote.ashx?t=')]"):
        href = a.get("href") or ""
        text = _normalize_symbol(a.text_content())
        if not _is_valid_symbol(text):
            continue
        # Prefer tickers that appear in the href
        if f"t={text}" not in href.upper().replace("%2D", "-"):
            # still accept if text is a plausible ticker and class is tab-link
            cls = (a.get("class") or "").lower()
            if "tab-link" not in cls and "company-ticker" not in cls:
                continue
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _http_get(url: str, params: Dict[str, Any]) -> str:
    last_err: Optional[Exception] = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = requests.get(
                url,
                params=params,
                headers={"User-Agent": _UA},
                timeout=_DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            last_err = e
            logging.warning("[finviz] HTTP attempt %d/%d failed: %s", attempt, _MAX_RETRIES, e)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_SLEEP_S * attempt)
    raise RuntimeError(f"Finviz HTTP failed after {_MAX_RETRIES} attempts: {last_err}")


def _fetch_screener(filters: List[str], table: str, order: str) -> List[Dict[str, Any]]:
    """
    Fetch Finviz screener rows as ``[{"Ticker": ...}, ...]``.

    Uses ``data-boxover-ticker`` instead of the finviz package Screener parser,
    which is broken by Finviz's logo + ticker dual text nodes (Jul 2026).
    """
    v = _TABLE_CODES.get(table) or _TABLE_CODES["Overview"]
    if table not in _TABLE_CODES and str(table).isdigit():
        v = str(table)

    base_params: Dict[str, Any] = {
        "v": v,
        "f": ",".join(filters or []),
        "o": order or "",
    }
    logging.info(
        "[finviz] fetching screener filters=%s table=%s(%s) order=%s",
        filters,
        table,
        v,
        order,
    )

    all_syms: List[str] = []
    seen = set()
    for page in range(_MAX_PAGES):
        r_start = 1 + page * _PAGE_SIZE
        params = dict(base_params, r=str(r_start))
        page_html = _http_get("https://finviz.com/screener.ashx", params)
        page_syms = _extract_tickers_from_html(page_html)
        if not page_syms:
            break
        new = [s for s in page_syms if s not in seen]
        if not new:
            break
        for s in new:
            seen.add(s)
            all_syms.append(s)
        if len(page_syms) < _PAGE_SIZE:
            break
        time.sleep(0.25)

    logging.info("[finviz] screener returned %d tickers", len(all_syms))
    return [{"Ticker": s} for s in all_syms]


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
            sym = _ticker_from_row(row)
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
            sym = _ticker_from_row(row)
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
            sym = _ticker_from_row(row)
            if _is_valid_symbol(sym):
                symbols.append(sym)
            elif sym:
                logging.debug("[finviz] skipped invalid symbol %r", sym)
        if rows and not symbols:
            logging.warning(
                "[finviz] getStocksSymbols: %d raw rows but 0 valid tickers",
                len(rows),
            )
    except Exception as e:
        logging.exception(f"[finviz] getStocksSymbols error: {e}")
    return symbols


def parse_finviz_screener_url(url: str, *, default_sort: str = "-marketcap") -> Tuple[List[str], str]:
    """
    Extract Finviz filter tokens and sort order from a screener URL (same as the site's ?f=...&o=...).

    Examples:
      https://finviz.com/screener.ashx?v=111&f=cap_midover,ta_highlow52w_nh&o=-marketcap
    """
    raw = (url or "").strip()
    if not raw:
        return [], default_sort
    if raw.startswith("/"):
        raw = "https://finviz.com" + raw
    elif not raw.lower().startswith("http"):
        raw = "https://finviz.com/" + raw.lstrip("/")
    parsed = urlparse(raw)
    qs = parse_qs(parsed.query)
    f_raw = (qs.get("f") or [""])[0]
    f_raw = unquote(str(f_raw).replace("+", ","))
    filters = [x.strip() for x in f_raw.split(",") if x.strip()]
    order = (qs.get("o") or [default_sort])[0] or default_sort
    return filters, order


def symbols_from_screener_url(
    url: str,
    *,
    max_symbols: int = 60,
    default_sort: Optional[str] = None,
) -> List[str]:
    """
    Run the Finviz screener implied by a pasted browser URL and return tickers (same order as screen).

    Requires query parameter ``f=`` (comma-separated Finviz filter codes).
    """
    ds = default_sort if default_sort is not None else "-marketcap"
    filters, order = parse_finviz_screener_url(url, default_sort=ds)
    if not filters:
        raise ValueError(
            "No Finviz filters in URL — paste a full screener link including "
            "?f=filter1,filter2,... (see Finviz URL while viewing your screen)."
        )
    syms = getStocksSymbols(filters, sortOrder=order)
    return syms[: max(1, int(max_symbols))]
