#!/usr/bin/env python3
"""
redfin_property_analyzer.py
Find a Redfin property from an address, extract key details, and
pull ZIP-level appreciation data from Redfin's public data center.

Usage:
  python redfin_property_analyzer.py "2450 Clairview St, Alpharetta, GA 30009"

Requirements:
  pip install requests beautifulsoup4 pandas python-dateutil

Env:
  export BING_SEARCH_KEY="...your key..."   # for Bing Web Search API
"""

import os, re, json, sys, time, math
import urllib.parse as up
from typing import Optional, Dict, Any

import requests
import pandas as pd
from bs4 import BeautifulSoup
from dateutil import parser as dtparser

# -----------------------------
# Config
# -----------------------------
BING_SEARCH_KEY = os.environ.get("BING_SEARCH_KEY")
BING_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"
RF_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9"
}

# Redfin public data center (median sale price by region)
# This CSV contains rows for region types (zip, county, etc.)
RED_FIN_MEDIAN_SALE_PRICE_CSV = (
    "https://redfin-public-data.s3-us-west-2.amazonaws.com/"
    "housing-market-data/market-tracker/median_sale_price.csv"
)


# -----------------------------
# Helpers
# -----------------------------
def log(msg: str):
    print(f"[INFO] {msg}", flush=True)

def warn(msg: str):
    print(f"[WARN] {msg}", flush=True)

def deep_find_keys(obj: Any, wanted: set[str]) -> Dict[str, Any]:
    """
    Walk a nested dict/list and return a map of {key: value} for first hits
    of keys that appear in `wanted`. Case-insensitive on keys.
    """
    found = {}
    stack = [obj]
    seen = 0
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                kl = str(k).lower()
                if kl in wanted and kl not in found:
                    found[kl] = v
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
        seen += 1
        if seen > 200000:  # safety cut-off in pathological cases
            break
    return found

def http_get(url: str, headers: dict = None, timeout: int = 20) -> Optional[requests.Response]:
    try:
        r = requests.get(url, headers=headers or RF_UA, timeout=timeout)
        if r.status_code == 200:
            return r
        warn(f"GET {url} -> HTTP {r.status_code}")
        return None
    except Exception as e:
        warn(f"GET {url} failed: {e}")
        return None

def extract_zip(address: str) -> Optional[str]:
    m = re.search(r"\b(\d{5})(?:-\d{4})?\b", address)
    return m.group(1) if m else None

def pct_change(new: float, old: float) -> Optional[float]:
    try:
        if old == 0:
            return None
        return (new - old) / old
    except Exception:
        return None

def cagr(final: float, initial: float, years: float) -> Optional[float]:
    try:
        if initial <= 0 or years <= 0:
            return None
        return (final / initial) ** (1.0 / years) - 1.0
    except Exception:
        return None


# -----------------------------
# Step 1: Find Redfin URL for an address (via Bing)
# -----------------------------
def redfin_url_via_bing(address: str) -> Optional[str]:
    if not BING_SEARCH_KEY:
        warn("BING_SEARCH_KEY not set. Cannot search for Redfin URL automatically.")
        return None

    q = f"site:redfin.com {address}"
    log(f"Searching Bing for Redfin URL: {q}")
    try:
        resp = requests.get(
            BING_ENDPOINT,
            params={"q": q, "count": 10, "mkt": "en-US"},
            headers={"Ocp-Apim-Subscription-Key": BING_SEARCH_KEY},
            timeout=15,
        )
        resp.raise_for_status()
        items = (resp.json().get("webPages", {}) or {}).get("value", []) or []
        for item in items:
            url = item.get("url") or ""
            if "redfin.com" in url and "/home/" in url:
                log(f"Found Redfin URL: {url}")
                return url
        warn("No Redfin property URL found in Bing results.")
        return None
    except Exception as e:
        warn(f"Bing search failed: {e}")
        return None


# -----------------------------
# Step 2: Parse Redfin property page
# -----------------------------
def parse_redfin_property(url: str) -> Dict[str, Any]:
    log(f"Fetching Redfin page: {url}")
    r = http_get(url, headers=RF_UA, timeout=25)
    if not r:
        return {"error": f"Failed to fetch Redfin URL: {url}"}

    soup = BeautifulSoup(r.text, "html.parser")
    data_tag = soup.find("script", {"id": "__NEXT_DATA__"})
    if not data_tag or not data_tag.string:
        warn("No __NEXT_DATA__ JSON blob found on the page.")
        return {"raw_html_snippet": r.text[:2000]}

    try:
        data = json.loads(data_tag.string)
    except Exception as e:
        warn(f"Failed to parse __NEXT_DATA__: {e}")
        return {"raw_next_data_snippet": data_tag.string[:2000]}

    # Try to find initialReduxState.homeDetails (common location)
    # But be robust: search the whole object for keys we care about
    wanted_keys = {
        "address", "streetline", "city", "state", "zipcode", "zip", "postalcode",
        "beds", "baths", "bathsdecimal", "sqft", "lotsize", "yearbuilt",
        "propertytype", "homefacts", "monthlyhoa", "hoadues", "propertytax",
        "lastsaledate", "lastsaleprice", "price", "publicrecords",
        "latitude", "longitude"
    }
    hits = deep_find_keys(data, wanted_keys)

    # Attempt reasonable field assembly
    def gn(k, default=None):  # get normalized
        return hits.get(k, default)

    # Address pieces: prefer combined if available
    address_line = gn("address") or gn("streetline")
    city = gn("city")
    state = gn("state")
    zipc = gn("zipcode") or gn("zip") or gn("postalcode")

    # Parse numbers carefully
    def to_float(x):
        try:
            return float(x)
        except Exception:
            return None

    beds = to_float(gn("beds"))
    baths = to_float(gn("bathsdecimal") or gn("baths"))
    sqft = to_float(gn("sqft"))
    lot = to_float(gn("lotsize"))
    year_built = gn("yearbuilt")
    prop_type = gn("propertytype")

    # HOA (monthly)
    hoa = gn("monthlyhoa") or gn("hoadues")
    hoa = to_float(hoa) if hoa is not None else None

    # Taxes (best-effort: some pages store annual tax differently)
    taxes = gn("propertytax")
    if isinstance(taxes, dict):
        # look for annual amount
        for k in ("amount", "annual", "value"):
            if k in taxes:
                taxes = taxes.get(k)
                break
    taxes = to_float(taxes)

    # Last sale
    last_sale_price = gn("lastsaleprice") or gn("price")
    # if it's like {"amount": 12345}
    if isinstance(last_sale_price, dict):
        last_sale_price = last_sale_price.get("amount")
    last_sale_price = to_float(last_sale_price)

    last_sale_date = gn("lastsaledate")
    if isinstance(last_sale_date, str):
        try:
            last_sale_date = dtparser.parse(last_sale_date).date().isoformat()
        except Exception:
            pass

    # Coordinates (optional)
    lat = to_float(hits.get("latitude"))
    lon = to_float(hits.get("longitude"))

    # Final address string
    address_full = ", ".join([s for s in [address_line, city, state, zipc] if s])

    return {
        "address_text": address_full or None,
        "address_parts": {
            "street": address_line, "city": city, "state": state, "zip": zipc
        },
        "geo": {"lat": lat, "lon": lon},
        "property_details": {
            "beds": beds,
            "baths": baths,
            "sqft": sqft,
            "lot_sqft": lot,
            "year_built": year_built,
            "property_type": prop_type,
            "hoa_monthly": hoa,
            "property_tax_annual": taxes,
            "last_sale_price": last_sale_price,
            "last_sale_date": last_sale_date,
        },
        "raw_keys_found": list(hits.keys()),  # for debugging transparency
    }


# -----------------------------
# Step 3: Pull Redfin market data for ZIP (appreciation)
# -----------------------------
def market_metrics_for_zip(zip_code: str) -> Dict[str, Any]:
    """
    Load Redfin 'median_sale_price.csv', filter to this ZIP,
    compute YoY and 5-year CAGR on most recent periods.
    """
    log(f"Loading Redfin market CSV for ZIP {zip_code} ...")
    try:
        df = pd.read_csv(RED_FIN_MEDIAN_SALE_PRICE_CSV)
    except Exception as e:
        warn(f"Failed to load Redfin data: {e}")
        return {"error": "failed_to_load_redfin_data"}

    # Columns vary slightly by dataset version; standard ones include:
    # region_type, region, period_end, median_sale_price
    req_cols = {"region_type", "region", "period_end", "median_sale_price"}
    if not req_cols.issubset(df.columns):
        # Try a fallback common variant (sometimes property_type, etc.)
        warn("Unexpected columns in Redfin CSV; returning sample columns for debugging.")
        return {"columns": list(df.columns)[:20]}

    zdf = df[(df["region_type"] == "zip") & (df["region"].astype(str) == str(zip_code))].copy()
    if zdf.empty:
        warn(f"No Redfin ZIP data for {zip_code}.")
        return {"zip": zip_code, "found": False}

    # Parse dates and sort
    zdf["period_end"] = pd.to_datetime(zdf["period_end"])
    zdf = zdf.sort_values("period_end")

    # Use latest value, 1 year ago, and 5 years ago (approx by months)
    latest = zdf.iloc[-1]
    latest_price = float(latest["median_sale_price"]) if pd.notna(latest["median_sale_price"]) else None
    latest_date = latest["period_end"].date().isoformat()

    # 12 months back row
    one_year_back_idx = zdf.index.get_loc(zdf.index[-1]) - 12 if len(zdf) > 12 else None
    yoy = None
    if one_year_back_idx is not None and one_year_back_idx >= 0:
        price_prev = float(zdf.iloc[one_year_back_idx]["median_sale_price"]) if pd.notna(zdf.iloc[one_year_back_idx]["median_sale_price"]) else None
        if latest_price is not None and price_prev is not None:
            yoy = pct_change(latest_price, price_prev)

    # 60 months back (5y)
    five_year_back_idx = zdf.index.get_loc(zdf.index[-1]) - 60 if len(zdf) > 60 else None
    cagr5 = None
    if five_year_back_idx is not None and five_year_back_idx >= 0:
        price_5y = float(zdf.iloc[five_year_back_idx]["median_sale_price"]) if pd.notna(zdf.iloc[five_year_back_idx]["median_sale_price"]) else None
        if latest_price is not None and price_5y is not None:
            cagr5 = cagr(latest_price, price_5y, 5)

    return {
        "zip": str(zip_code),
        "latest_period_end": latest_date,
        "median_sale_price_latest": latest_price,
        "median_sale_price_yoy": round(yoy, 4) if yoy is not None else None,
        "median_sale_price_cagr_5y": round(cagr5, 4) if cagr5 is not None else None,
        "observations": int(len(zdf)),
    }


# -----------------------------
# Optional: Rent estimate stub (wire your own source)
# -----------------------------
def rent_estimate_stub(address: str) -> Optional[float]:
    """
    Placeholder. Replace with RentCast/Rentometer/Zillow Playwright call.
    Return a float for monthly rent if available; else None.
    """
    return None


# -----------------------------
# Orchestrator
# -----------------------------
def analyze_with_redfin(address: str) -> Dict[str, Any]:
    log(f"Starting analysis for: {address}")

    # 1) Find Redfin URL (via Bing)
    url = redfin_url_via_bing(address)
    if not url:
        warn("Could not discover Redfin URL from address. You can paste one manually next time.")
        return {"input_address": address, "ok": False, "error": "redfin_url_not_found"}

    # 2) Parse Redfin property page
    prop = parse_redfin_property(url)

    # Determine ZIP for market analysis
    zip_code = None
    if isinstance(prop, dict):
        # Try from parsed address parts
        zip_code = (
            prop.get("address_parts", {}).get("zip")
            or extract_zip(prop.get("address_text") or "")
            or extract_zip(address)
        )
    else:
        zip_code = extract_zip(address)

    # 3) Market metrics
    market = market_metrics_for_zip(zip_code) if zip_code else {"error": "no_zip_found"}

    # 4) (Optional) Rent estimate
    rent = rent_estimate_stub(address)

    result = {
        "input_address": address,
        "redfin_url": url,
        "property": prop,
        "market": market,
        "rent_estimate_monthly": rent,
        "ok": True,
        "notes": [
            "Property fields are best-effort from Redfin's embedded JSON; keys vary by page.",
            "Market metrics use Redfin Data Center (median sale price) at ZIP level.",
            "Plug in a rent data source to complete cash-flow analysis."
        ]
    }
    return result


# -----------------------------
# CLI
# -----------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python redfin_property_analyzer.py \"2450 Clairview St, Alpharetta, GA 30009\"")
        sys.exit(1)

    address = " ".join(sys.argv[1:])
    t0 = time.time()
    out = analyze_with_redfin(address)
    print(json.dumps(out, indent=2))
    log(f"Done in {time.time() - t0:.2f}s")

if __name__ == "__main__":
    main()