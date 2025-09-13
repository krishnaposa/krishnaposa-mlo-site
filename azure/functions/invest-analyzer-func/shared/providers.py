# shared/providers.py
import os, csv, io, requests
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
    """Returns property profile (and value estimate if available)."""
    # Docs: https://www.rentcast.io/api
    url = f"{RENTCAST_BASE}/properties?address={requests.utils.quote(address)}&city={city}&state={state}&zip={zip_code}"
    r = requests.get(url, headers=rentcast_headers(), timeout=20)
    r.raise_for_status()
    data = r.json()
    return data[0] if data else {}

def rentcast_rent_estimate(address: str, city: str, state: str, zip_code: str,
                           beds: Optional[int]=None, baths: Optional[float]=None, sqft: Optional[int]=None) -> Dict[str, Any]:
    """Returns rent estimate (amount + range)."""
    params = {"address": address, "city": city, "state": state, "zip": zip_code}
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
    """Example endpoint: get details by ZPID (exact path depends on the RapidAPI provider you choose)."""
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
#  HPI Appreciation (free) via FRED API (FHFA All-Transactions HPI)
#  Series id pattern: '<STATE>HPI'  e.g., 'GAHPI', 'CAHPI'
#  Get a free FRED key: https://fred.stlouisfed.org/docs/api/api_key.html
#  Set env var: FRED_KEY
# ----------------------------
FRED_KEY = os.environ.get("FRED_KEY")
FRED_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"

def fred_state_cagr(state_abbr: str, years: int = 5) -> Optional[float]:
    """
    Compute trailing CAGR from FHFA All-Transactions HPI via FRED.
    Returns a float like 0.025 or None on failure.
    """
    if not FRED_KEY:
        return None

    series_id = f"{state_abbr.upper()}HPI"
    # Pull enough quarters (years*4 + a small buffer)
    obs_limit = years * 4 + 8
    params = {
        "series_id": series_id,
        "api_key": FRED_KEY,
        "file_type": "json",
        "sort_order": "asc",
        "limit": obs_limit
    }
    try:
        r = requests.get(FRED_OBS_URL, params=params, timeout=30)
        r.raise_for_status()
        j = r.json()
        obs = j.get("observations", [])
        vals = [float(o["value"]) for o in obs if o.get("value") not in (None, ".", "")]
        if len(vals) < years * 4 + 1:
            return None
        end_idx = vals[-1]
        start_idx = vals[-(years * 4 + 1)]
        if start_idx <= 0:
            return None
        cagr = (end_idx / start_idx) ** (1 / years) - 1
        return float(cagr)
    except Exception:
        return None

# Wrapper maintained for compatibility with your gatherData() usage
def fhfa_state_cagr(state_abbr: str, years: int = 5) -> Optional[float]:
    """Try FRED-backed state HPI CAGR; caller should fall back to a default if None."""
    return fred_state_cagr(state_abbr, years)

# ----------------------------
#  Taxes: simple heuristic (free)
# ----------------------------
STATE_PROP_TAX_RATE_GUESS = {
    # very rough average effective property tax rate (% of value per year)
    # Placeholder; replace with your preferred dataset later
    "GA": 0.009, "FL": 0.008, "TX": 0.016, "CA": 0.007, "NY": 0.017, "NC": 0.008,
    "SC": 0.006, "AL": 0.004, "TN": 0.007, "NJ": 0.024, "IL": 0.018, "PA": 0.014,
}

def estimate_monthly_tax(price_est: float, state_abbr: str) -> float:
    rate = STATE_PROP_TAX_RATE_GUESS.get(state_abbr.upper(), 0.01)  # default 1%
    return round((price_est * rate) / 12.0, 2)

# ----------------------------
#  Insurance: heuristic (free)
#  Note: scraping Zillow for insurance violates their ToS — don’t do it.
# ----------------------------
STATE_INS_PER_100K_PER_MONTH = {
    # VERY rough baseline monthly premium per $100k of coverage
    "GA": 28, "FL": 55, "TX": 38, "CA": 30, "NC": 29, "SC": 31,
    "AL": 32, "TN": 27, "NJ": 35, "NY": 36
}

def estimate_monthly_insurance(price_est: float, state_abbr: str, coverage_ratio: float = 0.8) -> float:
    """coverage_ratio ~ how much dwelling coverage vs price (80% default)."""
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
    # 1) Extract provider values if present
    rent_est = None
    if rent_resp:
        # RentCast fields could be 'rent', 'amount', or 'estimate'
        rent_est = rent_resp.get("rent") or rent_resp.get("amount") or rent_resp.get("estimate")

    price_est = None
    if value_resp:
        # RentCast AVM returns {"value": 321000, "low":..., "high":...}
        price_est = value_resp.get("value") or value_resp.get("estimate") or value_resp.get("zestimate")

    # 2) Heuristic bridging if one side is missing
    # If we have RENT but not PRICE -> estimate PRICE via a conservative GRM
    # Typical GRM ranges wildly; use 130–160 as a simple fallback. We'll pick 140.
    if (not price_est or float(price_est) <= 0) and (rent_est and float(rent_est) > 0):
        try:
            price_est = float(rent_est) * 12.0 * 140.0
        except Exception:
            price_est = 0.0

    # If we have PRICE but not RENT -> estimate RENT via "monthly rent ≈ 0.6–0.8% of price"
    if (not rent_est or float(rent_est) <= 0) and (price_est and float(price_est) > 0):
        try:
            rent_est = float(price_est) * 0.0065  # 0.65% rule (middle-of-road)
        except Exception:
            rent_est = 0.0

    # Final numeric guards
    try:
        rent_est = float(rent_est or 0.0)
    except Exception:
        rent_est = 0.0

    try:
        price_est = float(price_est or 0.0)
    except Exception:
        price_est = 0.0

    # 3) Taxes/insurance derived even if provider AVM failed
    taxes_month = estimate_monthly_tax(price_est, state_abbr) if price_est > 0 else 0.0
    ins_month   = estimate_monthly_insurance(price_est, state_abbr) if price_est > 0 else 0.0

    return {
        "rent_est": float(rent_est),
        "price_est": float(price_est),
        "taxes_month": float(taxes_month),
        "ins_month": float(ins_month),
        "hoa_month": 0.0,   # leave 0; UI/computeMetrics will override from user entry if provided
    }