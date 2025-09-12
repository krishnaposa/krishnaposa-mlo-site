# shared/providers.py
import os, math, csv, io, requests
from typing import Dict, Any, Optional

# ----------------------------
#  RentCast (free/cheap)
# ----------------------------
RENTCAST_BASE = "https://api.rentcast.io/v1"

def rentcast_headers():
    key = os.environ.get("RENTCAST_KEY")
    if not key:
        raise RuntimeError("Missing RENTCAST_KEY in settings")
    return {"X-Api-Key": key}

def rentcast_property_search(address: str, city: str, state: str, zip_code: str) -> Dict[str, Any]:
    """Returns property profile + value estimate (if available)."""
    # Docs: https://www.rentcast.io/api
    url = f"{RENTCAST_BASE}/properties?address={requests.utils.quote(address)}&city={city}&state={state}&zip={zip_code}"
    r = requests.get(url, headers=rentcast_headers(), timeout=20)
    r.raise_for_status()
    data = r.json()
    return data[0] if data else {}

def rentcast_rent_estimate(address: str, city: str, state: str, zip_code: str,
                           beds: Optional[int]=None, baths: Optional[float]=None, sqft: Optional[int]=None) -> Dict[str, Any]:
    """Returns rent estimate (amount + range)"""
    params = {
        "address": address, "city": city, "state": state, "zip": zip_code
    }
    if beds:  params["bedrooms"] = beds
    if baths: params["bathrooms"] = baths
    if sqft:  params["squareFootage"] = sqft

    url = f"{RENTCAST_BASE}/rent/estimate"
    r = requests.get(url, headers=rentcast_headers(), params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def rentcast_avm(address: str, city: str, state: str, zip_code: str) -> Dict[str, Any]:
    """Value (price) estimate for SFR/condo etc."""
    url = f"{RENTCAST_BASE}/avm/value"
    params = {"address": address, "city": city, "state": state, "zip": zip_code}
    r = requests.get(url, headers=rentcast_headers(), params=params, timeout=20)
    r.raise_for_status()
    return r.json()

# ----------------------------
#  Zillow via RapidAPI (cheap)
#  (Pick a specific API on RapidAPI and set env vars below)
# ----------------------------
RAPIDAPI_ZILLOW_HOST = os.environ.get("RAPIDAPI_ZILLOW_HOST")  # e.g., "zillow-com1.p.rapidapi.com"
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")

def rapid_headers():
    if not (RAPIDAPI_KEY and RAPIDAPI_ZILLOW_HOST):
        raise RuntimeError("Missing RAPIDAPI_KEY or RAPIDAPI_ZILLOW_HOST")
    return {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": RAPIDAPI_ZILLOW_HOST
    }

def zillow_property_details_zpid(zpid: str) -> Dict[str, Any]:
    """Example endpoint: get details by ZPID (the exact path depends on the RapidAPI listing you choose)."""
    url = f"https://{RAPIDAPI_ZILLOW_HOST}/property"
    r = requests.get(url, headers=rapid_headers(), params={"zpid": zpid}, timeout=20)
    r.raise_for_status()
    return r.json()

def zillow_search_address(address: str) -> Dict[str, Any]:
    """Search by address to find zpid; exact endpoint name depends on provider."""
    url = f"https://{RAPIDAPI_ZILLOW_HOST}/locations"
    r = requests.get(url, headers=rapid_headers(), params={"location": address}, timeout=20)
    r.raise_for_status()
    return r.json()

# ----------------------------
#  FHFA HPI (free) – appreciation
#  We’ll fetch state-level quarterly HPI and compute a trailing CAGR.
#  You can swap to CBSA/county series if you prefer (FHFA publishes CSVs).
# ----------------------------
FHFA_STATE_CSV = "https://www.fhfa.gov/DataTools/Downloads/Documents/HPI/HPI_AT_state.csv"

def _parse_fhfa_state_csv(csv_bytes: bytes) -> Dict[str, Dict[str, float]]:
    """
    Returns { 'GA': {'YYYYQq': index_value, ...}, ... }
    CSV header example: 'State','Quarter','Index','...'
    """
    txt = csv_bytes.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(txt))
    out: Dict[str, Dict[str, float]] = {}
    for row in reader:
        st = row.get("State")
        q = row.get("Quarter")
        idx = row.get("Index")
        if not (st and q and idx):
            continue
        out.setdefault(st, {})[q] = float(idx)
    return out

def fhfa_state_cagr(state_abbr: str, years: int = 5) -> Optional[float]:
    """Compute trailing CAGR from FHFA quarterly index for a state (e.g., 'GA')."""
    resp = requests.get(FHFA_STATE_CSV, timeout=30)
    resp.raise_for_status()
    data = _parse_fhfa_state_csv(resp.content)
    series = data.get(state_abbr.upper())
    if not series:
        return None
    # sort by quarter key 'YYYYQq'
    keys = sorted(series.keys())
    if len(keys) < years*4 + 1:
        return None
    end_idx = series[keys[-1]]
    start_idx = series[keys[-(years*4+1)]]
    if start_idx <= 0:
        return None
    cagr = (end_idx / start_idx) ** (1/years) - 1
    return float(cagr)

# ----------------------------
#  Taxes: simple heuristic (free)
#  You can refine with ACS (Census) later.
# ----------------------------
STATE_PROP_TAX_RATE_GUESS = {
    # very rough average effective property tax rate (% of value per year)
    # Source should be replaced with your chosen dataset; treat as placeholder
    "GA": 0.009, "FL": 0.008, "TX": 0.016, "CA": 0.007, "NY": 0.017, "NC": 0.008,
    "SC": 0.006, "AL": 0.004, "TN": 0.007, "NJ": 0.024, "IL": 0.018, "PA": 0.014,
}

def estimate_monthly_tax(price_est: float, state_abbr: str) -> float:
    rate = STATE_PROP_TAX_RATE_GUESS.get(state_abbr.upper(), 0.01)  # default 1%
    return round((price_est * rate) / 12.0, 2)

# ----------------------------
#  Insurance: heuristic (free)
#  Zillow does not offer an insurance-quote API;
#  Scraping Zillow is against their ToS — do not do it.
# ----------------------------
STATE_INS_PER_100K_PER_MONTH = {
    # VERY rough baseline monthly premium per $100k of coverage
    # Replace with your own dataset or partner later
    "GA": 28, "FL": 55, "TX": 38, "CA": 30, "NC": 29, "SC": 31, "AL": 32, "TN": 27, "NJ": 35, "NY": 36
}

def estimate_monthly_insurance(price_est: float, state_abbr: str, coverage_ratio: float = 0.8) -> float:
    """
    coverage_ratio ~ how much dwelling coverage vs price (80% default).
    """
    per100k = STATE_INS_PER_100K_PER_MONTH.get(state_abbr.upper(), 30)
    coverage = price_est * coverage_ratio
    units = coverage / 100_000.0
    return round(units * per100k, 2)

# ----------------------------
#  Normalization helper
# ----------------------------
def normalize_estimates(address: Dict[str, Any],
                        rent_resp: Optional[Dict[str, Any]],
                        value_resp: Optional[Dict[str, Any]],
                        state_abbr: str) -> Dict[str, Any]:
    rent_est = None
    if rent_resp:
        # RentCast fields: {'rent': 2050, 'low': 1900, 'high': 2200, ...}
        rent_est = rent_resp.get("rent") or rent_resp.get("amount") or rent_resp.get("estimate")

    price_est = None
    if value_resp:
        # RentCast AVM returns {"value": 321000, "low":..., "high":...}
        price_est = value_resp.get("value") or value_resp.get("estimate") or value_resp.get("zestimate")

    if not rent_est:
        rent_est = 0.0
    if not price_est:
        price_est = 0.0

    taxes_month = estimate_monthly_tax(price_est, state_abbr)
    ins_month = estimate_monthly_insurance(price_est, state_abbr)

    return {
        "rent_est": float(rent_est),
        "price_est": float(price_est),
        "taxes_month": taxes_month,
        "ins_month": ins_month,
        "hoa_month": 0.0,   # keep from form or scrape listing you own; default 0
    }