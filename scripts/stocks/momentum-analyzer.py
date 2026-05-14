import yfinance as yf
import pandas as pd
import json
import os
import time
import argparse
import csv
import re
import requests
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from finviz.screener import Screener

# --- SETTINGS ---
PORTFOLIO_FILE = "momentum-analyzer.json"
FINVIZ_SCREENER_URL = (
    "https://finviz.com/screener.ashx?v=111&f=cap_midover,sh_price_o5,ta_highlow52w_nh"
)
_MAX_RETRIES = 3
_RETRY_SLEEP_S = 2
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
RS_ENTRY_THRESHOLD = 90
RS_EXIT_THRESHOLD = 70
TRAILING_STOP_PCT = 0.15
PORTFOLIO_SIZE = 20
# Relative-strength lookback for get_rs_ratings (yfinance period, e.g. "6mo", "1y")
RS_LOOKBACK_PERIOD = "6mo"

# --- DATA PERSISTENCE ---
def load_portfolio() -> Dict[str, Any]:
    """
    Load portfolio document. Always returns a dict with at least ``positions`` (may be empty).
    """
    if not os.path.exists(PORTFOLIO_FILE):
        return {"positions": {}, "updated_at": None}
    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {"positions": {}, "updated_at": None}
    if "positions" in data and isinstance(data["positions"], dict):
        return data
    skip = {"meta", "updated_at", "tickers"}
    legacy = {
        k: v
        for k, v in data.items()
        if str(k) not in skip and isinstance(v, dict)
    }
    if legacy:
        return {"positions": legacy, "updated_at": data.get("updated_at")}
    return {"positions": {}, "updated_at": data.get("updated_at")}


def save_portfolio(doc: Dict[str, Any]) -> None:
    """Persist full document (positions + updated_at)."""
    if "positions" not in doc or not isinstance(doc["positions"], dict):
        raise ValueError("save_portfolio expects doc['positions'] dict")
    out = dict(doc)
    out["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=4)

# --- FINVIZ (same pattern as azure/functions/stocks-func-app/wb4u_finviz.py) ---


def _is_valid_symbol(sym: str) -> bool:
    if not sym:
        return False
    s = str(sym).upper()
    return s.replace(".", "").replace("-", "").isalpha()


def _normalize_symbol(sym: str) -> str:
    return str(sym).upper().strip()


def _parse_price_cell(val: Any) -> Optional[float]:
    """Finviz table cells like '$12.34' or 12.34."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).replace("$", "").replace(",", "").strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fetch_screener(filters: List[str], table: str, order: str) -> List[Dict[str, Any]]:
    """Wrap finviz Screener with retries (matches wb4u_finviz._fetch_screener)."""
    last_err = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            sess = requests.Session()
            sess.headers.update({"User-Agent": _UA})
            stock_list = Screener(filters=filters, table=table, order=order)
            return [dict(row) for row in stock_list]
        except Exception as e:
            last_err = e
            print(f"[finviz] attempt {attempt}/{_MAX_RETRIES} failed: {e}")
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_SLEEP_S * attempt)
    raise RuntimeError(f"Finviz screener failed after {_MAX_RETRIES} attempts: {last_err}")


def parse_finviz_screener_url(url: str, *, default_sort: str = "-marketcap") -> Tuple[List[str], str]:
    """Extract Finviz filter tokens and sort order from a screener URL (wb4u_finviz.parse_finviz_screener_url)."""
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


def fetch_finviz_screener_rows() -> List[Dict[str, Any]]:
    """Raw Finviz screener rows (Valuation table), wb4u_finviz-style."""
    filters, order = parse_finviz_screener_url(FINVIZ_SCREENER_URL, default_sort="-marketcap")
    if not filters:
        raise ValueError(
            "No Finviz filters in URL — expected ?f=filter1,filter2,... "
            "(see wb4u_finviz.parse_finviz_screener_url)."
        )
    return _fetch_screener(filters=filters, table="Valuation", order=order)


def fetch_finviz_screener_tickers() -> List[str]:
    """
    Tickers from FINVIZ_SCREENER_URL in screener order (table=Valuation).
    """
    symbols: List[str] = []
    for row in fetch_finviz_screener_rows():
        sym = _normalize_symbol(row.get("Ticker", ""))
        if _is_valid_symbol(sym):
            symbols.append(sym)
    return symbols


def _last_closes(symbols: List[str]) -> Dict[str, float]:
    """Latest daily close per symbol (5d window)."""
    if not symbols:
        return {}
    data = yf.download(symbols, period="5d", interval="1d", progress=False)["Close"]
    out: Dict[str, float] = {}
    if len(symbols) == 1:
        sym = symbols[0]
        ser = data if isinstance(data, pd.Series) else data[sym]
        out[sym] = float(ser.dropna().iloc[-1])
        return out
    for sym in symbols:
        try:
            if sym not in data.columns:
                continue
            out[sym] = float(data[sym].dropna().iloc[-1])
        except Exception:
            continue
    return out


def _safe_rs(rs: pd.Series, sym: str) -> float:
    try:
        v = float(rs.loc[sym])
        if pd.isna(v):
            return 0.0
        return v
    except Exception:
        return 0.0


def _close_column(data: Any, ticker: str) -> pd.Series:
    if isinstance(data, pd.Series):
        return data
    return data[ticker]


def _seed_positions_from_candidates(
    candidates: List[Tuple[str, Optional[float]]],
    *,
    merge: bool,
    source_label: str,
) -> Dict[str, Any]:
    """
    Shared seed: candidates are (symbol, optional_reference_high_price e.g. Finviz Price).
    """
    doc = load_portfolio()
    existing: Dict[str, Any] = dict(doc.get("positions") or {})

    use = list(candidates)
    if merge:
        max_new = max(0, PORTFOLIO_SIZE - len(existing))
        use = use[:max_new]
    else:
        use = use[:PORTFOLIO_SIZE]

    syms = [c[0] for c in use]
    if not syms:
        if merge:
            raise RuntimeError(
                f"No new tickers to add from {source_label} (portfolio full or list empty)."
            )
        raise RuntimeError(f"No tickers to seed from {source_label}.")

    closes = _last_closes(syms)
    rs = get_rs_ratings(syms)
    today = datetime.now().strftime("%Y-%m-%d")

    new_entries: Dict[str, Any] = {}
    for sym, ref_price in use:
        close = closes.get(sym)
        if close is None or close <= 0:
            print(f"[seed] skip {sym}: no yfinance close")
            continue
        hi = close
        if ref_price is not None and ref_price > hi:
            hi = ref_price
        new_entries[sym] = {
            "entry_price": round(close, 4),
            "high_seen": round(hi, 4),
            "entry_date": today,
            "rs_at_entry": round(_safe_rs(rs, sym), 2),
        }

    if not new_entries:
        msg = f"[seed] No positions built from {source_label} (yfinance had no closes)."
        if merge:
            print(msg + " Keeping existing positions.")
            return {"positions": dict(existing), "updated_at": doc.get("updated_at")}
        raise RuntimeError(msg + " Fix symbols or try again later.")

    if merge:
        positions = dict(existing)
        positions.update(new_entries)
    else:
        positions = new_entries

    print(
        f"Seeded {len(new_entries)} position(s) from {source_label} into {PORTFOLIO_FILE} "
        f"({'merge' if merge else 'replace'}). Total positions: {len(positions)}."
    )
    return {"positions": positions, "updated_at": doc.get("updated_at")}


def read_symbols_from_file(path: str) -> List[str]:
    """
    Read ticker symbols from a text or CSV file.

    **Plain text (.txt or non-CSV):** one or more symbols per line; commas, semicolons, or
    whitespace separate symbols. Lines starting with ``#`` are ignored; inline ``#`` starts a comment.

    **CSV:** first row may be a header. Recognized header names for the symbol column:
    ``ticker``, ``symbol``, ``sym`` (case-insensitive). Otherwise the **first column** of each row is used.
    """
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Ticker file not found: {path}")

    symbols: List[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        sym = _normalize_symbol(raw)
        if not _is_valid_symbol(sym):
            return
        if sym not in seen:
            seen.add(sym)
            symbols.append(sym)

    lower = path.lower()
    if lower.endswith(".csv"):
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


def seed_portfolio_from_file(path: str, merge: bool = False) -> Dict[str, Any]:
    """Build positions from a ticker list file + yfinance (no Finviz)."""
    syms = read_symbols_from_file(path)
    doc = load_portfolio()
    existing: Dict[str, Any] = dict(doc.get("positions") or {})
    candidates: List[Tuple[str, Optional[float]]] = []
    for s in syms:
        if merge and s in existing:
            continue
        candidates.append((s, None))
    return _seed_positions_from_candidates(
        candidates, merge=merge, source_label=os.path.basename(path)
    )


def seed_portfolio_from_finviz(merge: bool = False) -> Dict[str, Any]:
    """
    Build ``positions`` from Finviz screener rows + yfinance closes + RS ranks.

    - Default: replace portfolio with up to PORTFOLIO_SIZE names from the screener (in order).
    - merge=True: add Finviz names not already in positions (at most PORTFOLIO_SIZE - len(existing)).
    """
    rows = fetch_finviz_screener_rows()
    doc = load_portfolio()
    existing: Dict[str, Any] = dict(doc.get("positions") or {})

    candidates: List[Tuple[str, Optional[float]]] = []
    for row in rows:
        sym = _normalize_symbol(row.get("Ticker", ""))
        if not _is_valid_symbol(sym):
            continue
        if merge and sym in existing:
            continue
        candidates.append((sym, _parse_price_cell(row.get("Price"))))

    return _seed_positions_from_candidates(
        candidates, merge=merge, source_label="Finviz"
    )


# --- CORE LOGIC ---
def get_rs_ratings(tickers):
    """Percentile RS vs peers over RS_LOOKBACK_PERIOD (total return vs SPY baseline)."""
    if not tickers: return pd.Series()
    # Adding SPY to the mix to provide a market baseline
    data = yf.download(
        tickers + ["SPY"],
        period=RS_LOOKBACK_PERIOD,
        interval="1d",
        progress=False,
    )["Close"]
    print(f"RS lookback ({RS_LOOKBACK_PERIOD}) closes: {data}")
    returns = (data.iloc[-1] / data.iloc[0]) - 1
    return returns.rank(pct=True) * 100

def run_daily_update():
    try:
        fz = fetch_finviz_screener_tickers()
        print(
            f"Finviz screener ({FINVIZ_SCREENER_URL}): {len(fz)} tickers"
        )
        if fz:
            preview = ", ".join(fz[:40])
            more = " …" if len(fz) > 40 else ""
            print(f"  {preview}{more}")
    except Exception as ex:
        print(f"Finviz screener request failed: {ex}")

    doc = load_portfolio()
    portfolio: Dict[str, Any] = dict(doc.get("positions") or {})

    if not portfolio:
        print(
            "Portfolio is empty. Seed with:\n"
            f"  python momentum-analyzer.py --seed-from-finviz\n"
            f"  python momentum-analyzer.py --tickers-file path/to/tickers.txt"
        )
        return
    tickers = list(portfolio.keys())

    # Download latest data
    data = yf.download(tickers, period="5d", interval="1d", progress=False)["Close"]
    print(f"5 days data: {data}")
    rs_ratings = get_rs_ratings(tickers)
    print(f"rs_ratings: {rs_ratings}")

    updates_made = False
    to_delete = []

    for ticker in tickers:
        try:
            px = _close_column(data, ticker)
            current_price = float(px.dropna().iloc[-1])
        except Exception as ex:
            print(f"[daily] skip {ticker}: {ex}")
            continue

        # Update Highest Price Seen (for Trailing Stop)
        if current_price > float(portfolio[ticker].get("high_seen", 0) or 0):
            portfolio[ticker]["high_seen"] = current_price
            updates_made = True
            print(f"NEW HIGH: {ticker} hit ${current_price:.2f}. Stop moved to ${current_price * (1-TRAILING_STOP_PCT):.2f}")

        # EXIT CHECK 1: Trailing Stop
        stop_price = float(portfolio[ticker]["high_seen"]) * (1 - TRAILING_STOP_PCT)
        if current_price <= stop_price:
            print(f"!!! SELL {ticker} !!! Trailing stop hit at ${current_price:.2f}")
            to_delete.append(ticker)
            continue

        # EXIT CHECK 2: RS Decay
        if ticker in rs_ratings.index and rs_ratings[ticker] < RS_EXIT_THRESHOLD:
            print(f"!!! SELL {ticker} !!! RS Rating ({rs_ratings[ticker]:.1f}) dropped below {RS_EXIT_THRESHOLD}")
            to_delete.append(ticker)

    # Clean up portfolio
    for ticker in to_delete:
        del portfolio[ticker]
        updates_made = True

    doc["positions"] = portfolio
    if updates_made:
        save_portfolio(doc)
        print(f"Saved {PORTFOLIO_FILE} after updates.")
    else:
        print(f"Daily Check Complete: {datetime.now().strftime('%Y-%m-%d')}. No actions required.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Momentum analyzer: seed portfolio from Finviz or a ticker file + daily checks.",
    )
    seed = parser.add_mutually_exclusive_group()
    seed.add_argument(
        "--seed-from-finviz",
        action="store_true",
        help=f"Build or refresh {PORTFOLIO_FILE} using Finviz screener + yfinance (see FINVIZ_SCREENER_URL).",
    )
    seed.add_argument(
        "--tickers-file",
        metavar="PATH",
        help="Build or refresh portfolio from a text/CSV list of symbols (no Finviz). Same JSON shape as --seed-from-finviz.",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="With --seed-from-finviz or --tickers-file: only add symbols not already held (total size capped at PORTFOLIO_SIZE).",
    )
    args = parser.parse_args()
    if args.seed_from_finviz:
        doc = seed_portfolio_from_finviz(merge=args.merge)
        save_portfolio(doc)
    elif args.tickers_file:
        doc = seed_portfolio_from_file(args.tickers_file, merge=args.merge)
        save_portfolio(doc)
    else:
        run_daily_update()