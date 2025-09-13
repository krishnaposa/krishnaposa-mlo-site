# shared/providers.py
import os, csv, io, math, requests
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
    url = f"{RENTCAST_BASE}/properties?address={requests.utils.quote(address)}&city={city}&state={state}&zip={zip_code}"
    r = requests.get(url, headers=rentcast_headers(), timeout=20)
    r.raise_for_status()
    data = r.json()
    return data[0] if data else {}

def rentcast_rent_estimate(address: str, city: str, state: str, zip_code: str,
                           beds: Optional[int]=None, baths: Optional[float]=None, sqft: Optional[int]=None) -> Dict[str, Any]:
    params = {"address": address, "city": city, "state": state, "zip": zip_code}
    if beds:  params["bedrooms"] = beds
    if baths: params["bathrooms"] = baths
    if sqft:  params["squareFootage"] = sqft
    url = f"{RENTCAST_BASE}/rent/estimate"
    r = requests.get(url, headers=rentcast_headers(), params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def rentcast_avm(address: str, city: str, state: str, zip_code: str) -> Dict[str, Any]:
    url = f"{RENTCAST_BASE}/avm/value"
    params = {"address": address, "city": city, "state": state, "zip": zip_code}
    r = requests.get(url, headers=rentcast_headers(), params=params, timeout=20)
    r.raise_for_status()
    return r.json()

# ----------------------------
#  Zillow via RapidAPI (cheap)
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

def zillow_search_address_freeform(query: str) -> Dict[str, Any]:
    """
    Search by freeform address text to find a ZPID.
    Provider endpoints vary. Many use /locations, /search or /propertyExtendedSearch.
    This version tries /locations first.
    """
    url = f"https://{RAPIDAPI_ZILLOW_HOST}/locations"
    r = requests.get(url, headers=rapid_headers(), params={"location": query}, timeout=20)
    r.raise_for_status()
    return r.json()

def zillow_property_details_zpid(zpid: str) -> Dict[str, Any]:
    """
    Load details for a ZPID; different RapidAPI providers expose different fields.
    We’ll try typical keys for HOA: 'hoaFee', 'monthlyHoaFee', 'hoa' etc.
    """
    url = f"https://{RAPIDAPI_ZILLOW_HOST}/property"
    r = requests.get(url, headers=rapid_headers(), params={"zpid": zpid}, timeout=20)
    r.raise_for_status()
    data = r.json()
    # Try to surface HOA as a float
    hoa_candidates = []
    if isinstance(data, dict):
        for k in ("hoaFee", "monthlyHoaFee", "hoa", "hoa_fee", "hoa_per_month"):
            if k in data:
                hoa_candidates.append(data.get(k))
        # Some providers wrap details in 'data' or 'result'
        inner = data.get("data") or data.get("result") or {}
        for k in ("hoaFee", "monthlyHoaFee", "hoa", "hoa_fee", "hoa_per_month"):
            if isinstance(inner, dict) and k in inner:
                hoa_candidates.append(inner.get(k))
    hoa_val = 0.0
    for cand in hoa_candidates:
        try:
            v = float(cand)
            if math.isfinite(v) and v > 0:
                hoa_val = v
                break
        except Exception:
            continue
    data["parsed_hoa"] = hoa_val
    return data

def get_zillow_hoa_by_address(address: str, city: str, state: str, zip_code: str) -> float:
    """
    Convenience: search by address -> zpid -> details -> parse HOA.
    Returns monthly HOA or 0.0 if not available.
    """
    try:
        query = f"{address}, {city}, {state} {zip_code}".strip()
        sr = zillow_search_address_freeform(query)
        zpid = None
        # Try common patterns to extract a zpid
        if isinstance(sr, dict):
            zpid = sr.get("zpid")
            if not zpid:
                # Some providers return lists under 'results' or 'addresses'
                for key in ("results", "addresses", "data", "items"):
                    arr = sr.get(key)
                    if isinstance(arr, list) and arr:
                        zpid = (arr[0].get("zpid") or arr[0].get("id") or arr[0].get("zpidId"))
                        if zpid: break
        if not zpid:
            return 0.0
        det = zillow_property_details_zpid(str(zpid))
        return float(det.get("parsed_hoa") or 0.0)
    except Exception:
        return 0.0

# ----------------------------
#  HPI Appreciation (free) via FRED API (FHFA All-Transactions HPI)
# ----------------------------
FRED_KEY = os.environ.get("FRED_KEY")
FRED_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"

def fred_state_cagr(state_abbr: str, years: int = 5) -> Optional[float]:
    if not FRED_KEY:
        return None
    series_id = f"{state_abbr.upper()}HPI"
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

def fhfa_state_cagr(state_abbr: str, years: int = 5) -> Optional[float]:
    return fred_state_cagr(state_abbr, years)

# ----------------------------
#  Taxes & Insurance heuristics
# ----------------------------
STATE_PROP_TAX_RATE_GUESS = {
    "GA": 0.009, "FL": 0.008, "TX": 0.016, "CA": 0.007, "NY": 0.017, "NC": 0.008,
    "SC": 0.006, "AL": 0.004, "TN": 0.007, "NJ": 0.024, "IL": 0.018, "PA": 0.014,
}

def estimate_monthly_tax(price_est: float, state_abbr: str) -> float:
    rate = STATE_PROP_TAX_RATE_GUESS.get(state_abbr.upper(), 0.01)
    return round((price_est * rate) / 12.0, 2)

STATE_INS_PER_100K_PER_MONTH = {
    "GA": 28, "FL": 55, "TX": 38, "CA": 30, "NC": 29, "SC": 31,
    "AL": 32, "TN": 27, "NJ": 35, "NY": 36
}

def estimate_monthly_insurance(price_est: float, state_abbr: str, coverage_ratio: float = 0.8) -> float:
    per100k = STATE_INS_PER_100K_PER_MONTH.get(state_abbr.upper(), 30)
    coverage = price_est * coverage_ratio
    units = coverage / 100_000.0
    return round(units * per100k, 2)

# ----------------------------
#  Normalization + robust fallbacks
# ----------------------------
def _safe_float(x, default=0.0):
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default

def normalize_estimates(address: Dict[str, Any],
                        rent_resp: Optional[Dict[str, Any]],
                        value_resp: Optional[Dict[str, Any]],
                        state_abbr: str) -> Dict[str, Any]:
    # Provider values
    rent_est = None
    if rent_resp:
        rent_est = (rent_resp.get("rent") or rent_resp.get("amount")
                    or rent_resp.get("estimate") or rent_resp.get("value"))
    price_est = None
    if value_resp:
        price_est = (value_resp.get("value") or value_resp.get("estimate")
                     or value_resp.get("zestimate") or value_resp.get("price"))

    rent_est = _safe_float(rent_est, 0.0)
    price_est = _safe_float(price_est, 0.0)

    # Bridge one missing side
    if price_est <= 0 and rent_est > 0:
        price_est = rent_est * 12.0 * 140.0  # GRM fallback
    if rent_est <= 0 and price_est > 0:
        rent_est = price_est * 0.0065       # 0.65%/mo rule

    # Last-resort both missing
    if price_est <= 0 and rent_est <= 0:
        baseline_price_by_state = {
            "GA": 320_000, "FL": 360_000, "TX": 310_000, "NC": 300_000, "SC": 290_000,
            "CA": 700_000, "NY": 520_000, "NJ": 480_000, "TN": 290_000, "AL": 250_000
        }
        price_est = baseline_price_by_state.get(state_abbr.upper(), 300_000)
        rent_est = price_est * 0.0062

    taxes_month = estimate_monthly_tax(price_est, state_abbr) if price_est > 0 else 0.0
    ins_month   = estimate_monthly_insurance(price_est, state_abbr) if price_est > 0 else 0.0

    return {
        "rent_est": float(rent_est),
        "price_est": float(price_est),
        "taxes_month": float(taxes_month),
        "ins_month": float(ins_month),
        "hoa_month": 0.0,  # will be overridden if Zillow HOA found
    }