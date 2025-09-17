# services/tax_providers.py
"""
Heuristic property tax fallback (no external calls).

Entry point:
    estimate_fallback(inputs: dict) -> dict
Returns a dict:
    {
        "prior_year": <int|None>,
        "prior_amount": <float>,
        "current_year_est": <float>,
        "source": "fallback"
    }

Inputs we pay attention to (all optional):
    - state: 2-letter (GA) or full name ("Georgia")
    - purchasePrice / homeValue: proxy for market value
    - assessedValue: assessed value (if known)
    - millage or millage_per_1000: tax per $1,000 of assessed value
    - ownerOccupied: True/False (small homestead-like reduction if True)
    - priorTaxYear / prior_year
    - priorTaxAmount / prior_amount
    - taxGrowthPct: expected YOY growth in taxes (percent, e.g., 3 for 3%)
Notes:
    - If millage & assessedValue exist → tax = assessedValue * (millage / 1000).
    - Else use state effective rate % * market value.
    - Applies small homestead-like reduction (-5%) if ownerOccupied=True and we used the
      state effective rate path (not applied to explicit millage math).
"""

import datetime
from typing import Dict, Optional

# ----- small utils -----
def _n(x) -> float:
    try:
        v = float(str(x).replace(",", "").strip())
        if v != v: return 0.0  # NaN
        if v in (float("inf"), float("-inf")): return 0.0
        return v
    except Exception:
        return 0.0

def _pct(x) -> float:
    """
    Coerce to percent number (not fraction).
    Accepts "1.1" => 1.1% or "0.011" => 1.1% if <= 0.2.
    """
    v = _n(x)
    if v == 0: return 0.0
    return v if v > 0.2 else v * 100.0

def _clamp_nonneg(x: float) -> float:
    return x if x > 0 else 0.0

def _normalize_state(s: Optional[str]) -> str:
    if not s: return ""
    s = s.strip().upper()
    # Allow full names for a few common ones (expand as desired)
    full = {
        "ALABAMA":"AL","ALASKA":"AK","ARIZONA":"AZ","ARKANSAS":"AR","CALIFORNIA":"CA","COLORADO":"CO",
        "CONNECTICUT":"CT","DELAWARE":"DE","DISTRICT OF COLUMBIA":"DC","WASHINGTON DC":"DC","DC":"DC",
        "FLORIDA":"FL","GEORGIA":"GA","HAWAII":"HI","IDAHO":"ID","ILLINOIS":"IL","INDIANA":"IN",
        "IOWA":"IA","KANSAS":"KS","KENTUCKY":"KY","LOUISIANA":"LA","MAINE":"ME","MARYLAND":"MD",
        "MASSACHUSETTS":"MA","MICHIGAN":"MI","MINNESOTA":"MN","MISSISSIPPI":"MS","MISSOURI":"MO",
        "MONTANA":"MT","NEBRASKA":"NE","NEVADA":"NV","NEW HAMPSHIRE":"NH","NEW JERSEY":"NJ","NEW MEXICO":"NM",
        "NEW YORK":"NY","NORTH CAROLINA":"NC","NORTH DAKOTA":"ND","OHIO":"OH","OKLAHOMA":"OK","OREGON":"OR",
        "PENNSYLVANIA":"PA","RHODE ISLAND":"RI","SOUTH CAROLINA":"SC","SOUTH DAKOTA":"SD","TENNESSEE":"TN",
        "TEXAS":"TX","UTAH":"UT","VERMONT":"VT","VIRGINIA":"VA","WASHINGTON":"WA","WEST VIRGINIA":"WV",
        "WISCONSIN":"WI","WYOMING":"WY",
    }
    return full.get(s, s[:2])

# ----- very rough effective property tax rates by state (% of market value) -----
# Source: blended/typical ranges; for fallback only (not official).
_STATE_EFFECTIVE_RATE_PCT = {
    "AL": 0.42, "AK": 1.17, "AZ": 0.62, "AR": 0.64, "CA": 0.76, "CO": 0.55,
    "CT": 1.67, "DE": 0.56, "DC": 0.56, "FL": 0.86, "GA": 0.87, "HI": 0.29,
    "ID": 0.63, "IL": 2.07, "IN": 0.81, "IA": 1.49, "KS": 1.34, "KY": 0.86,
    "LA": 0.56, "ME": 1.09, "MD": 1.05, "MA": 1.12, "MI": 1.64, "MN": 1.05,
    "MS": 0.81, "MO": 0.96, "MT": 0.83, "NE": 1.67, "NV": 0.60, "NH": 1.77,
    "NJ": 2.23, "NM": 0.80, "NY": 1.40, "NC": 0.84, "ND": 0.99, "OH": 1.41,
    "OK": 0.90, "OR": 0.90, "PA": 1.50, "RI": 1.37, "SC": 0.57, "SD": 1.22,
    "TN": 0.56, "TX": 1.68, "UT": 0.57, "VT": 1.82, "VA": 0.80, "WA": 0.90,
    "WV": 0.59, "WI": 1.63, "WY": 0.61,
}
_DEFAULT_EFFECTIVE_RATE_PCT = 1.00  # 1.00% if unknown

def _effective_rate_pct_for_state(state: Optional[str]) -> float:
    return _STATE_EFFECTIVE_RATE_PCT.get(_normalize_state(state), _DEFAULT_EFFECTIVE_RATE_PCT)

# ----- core helpers -----
def _calc_from_millage(assessed_value: float, millage_per_1000: float) -> float:
    # millage is dollars per $1,000 of assessed value
    return assessed_value * (millage_per_1000 / 1000.0)

def _calc_from_effective_rate(market_value: float, state: Optional[str], owner_occupied: bool) -> float:
    rate_pct = _effective_rate_pct_for_state(state)
    tax = market_value * (rate_pct / 100.0)
    # small homestead-like reduction if owner occupied
    if owner_occupied:
        tax *= 0.95
    return tax

def estimate_fallback(inputs: Dict) -> Dict:
    """
    Heuristic estimate of property taxes for the current year.
    Preference:
      1) millage + assessedValue
      2) state effective rate % * market value (purchasePrice/homeValue)

    If priorTaxAmount is supplied, we use it and apply growth to get current year.

    Returns normalized dict expected by your routes.
    """
    # Parse inputs
    state = inputs.get("state")
    owner_occ = bool(inputs.get("ownerOccupied"))
    market_value = _n(inputs.get("purchasePrice") or inputs.get("homeValue"))
    assessed_value = _n(inputs.get("assessedValue"))
    millage = inputs.get("millage")
    if millage is None:
        millage = inputs.get("millage_per_1000")
    millage = _n(millage)

    # prior-year hints (many sources use different keys)
    prior_year = int(_n(inputs.get("priorTaxYear") or inputs.get("prior_year"))) or None
    prior_amount_input = _n(inputs.get("priorTaxAmount") or inputs.get("prior_amount"))

    # user-provided expected YOY growth (percent)
    growth_pct = _pct(inputs.get("taxGrowthPct"))
    if growth_pct <= 0:
        growth_pct = 3.0  # default 3% growth assumption

    # 1) If prior amount supplied, estimate current by growth
    if prior_amount_input > 0:
        curr_est = prior_amount_input * (1.0 + growth_pct / 100.0)
        return {
            "prior_year": prior_year or (datetime.datetime.utcnow().year - 1),
            "prior_amount": round(_clamp_nonneg(prior_amount_input), 2),
            "current_year_est": round(_clamp_nonneg(curr_est), 2),
            "source": "fallback"
        }

    # 2) If we have millage & assessed value, use those (most specific)
    if assessed_value > 0 and millage > 0:
        curr_est = _calc_from_millage(assessed_value, millage)
        return {
            "prior_year": prior_year,  # unknown otherwise
            "prior_amount": 0.0,
            "current_year_est": round(_clamp_nonneg(curr_est), 2),
            "source": "fallback"
        }

    # 3) Else use state effective rate against market value
    if market_value > 0:
        curr_est = _calc_from_effective_rate(market_value, state, owner_occ)
        return {
            "prior_year": prior_year,
            "prior_amount": 0.0,
            "current_year_est": round(_clamp_nonneg(curr_est), 2),
            "source": "fallback"
        }

    # 4) Nothing to go on — return zeros
    return {
        "prior_year": prior_year,
        "prior_amount": 0.0,
        "current_year_est": 0.0,
        "source": "fallback"
    }