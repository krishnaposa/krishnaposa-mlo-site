# routes/rent_prefetch.py
from utils.common import n
from utils.cache import make_cache_key, blob_cache_get, blob_cache_put, cache_headers
from services.tax_providers import fetch_from_county, estimate_fallback
from services.aoai_expenses import ai_expense_pack
from services.aoai import prefetch_estimate
from services.aoai_tax import ai_tax_estimate
from services.aoai_appreciation import ai_appreciation

_CONF = {"low": 0, "medium": 1, "high": 2}
OVERRIDE_CONF = _CONF["high"]

CACHE_GROUP = "rent-prefetch"
CACHE_TTL_SEC = 12 * 60 * 60

def _rank(label: str) -> int:
    return _CONF.get(str(label or "").lower(), 0)

def run_rent_prefetch(inputs: dict) -> dict:
    if not (inputs.get("state") or inputs.get("zip")):
        raise ValueError("Provide at least 'state' or 'zip' for better estimates.")

    key_payload = {
        "address": inputs.get("address"),
        "city": inputs.get("city"),
        "state": inputs.get("state"),
        "zip": inputs.get("zip"),
        "county": inputs.get("county"),
        "purchasePrice": inputs.get("purchasePrice") or inputs.get("homeValue"),
        "propertyType": inputs.get("propertyType"),
        "units": inputs.get("units") or 1,
        "yearBuilt": inputs.get("yearBuilt"),
        "sqft": inputs.get("sqft"),
        "ownerOccupied": bool(inputs.get("ownerOccupied")),
        "assessedValue": inputs.get("assessedValue"),
        "millage": inputs.get("millage"),
    }
    cache_key = make_cache_key(key_payload, version="prefetch-v3")
    cached = blob_cache_get(CACHE_GROUP, cache_key, max_age_sec=CACHE_TTL_SEC)
    if cached:
        return cached

    county = fetch_from_county(inputs) or estimate_fallback(inputs)
    chosen_tax = dict(county) if isinstance(county, dict) else {}

    ai_payload = {
        "address": inputs.get("address"), "city": inputs.get("city"),
        "state": inputs.get("state"), "zip": inputs.get("zip"), "county": inputs.get("county"),
        "value": inputs.get("purchasePrice") or inputs.get("homeValue"),
        "assessed_value": inputs.get("assessedValue"),
        "millage_per_1000": inputs.get("millage"),
        "propertyType": inputs.get("propertyType"),
        "units": inputs.get("units") or 1,
        "year_built": inputs.get("yearBuilt"),
        "sqft": inputs.get("sqft"),
        "owner_occupied": bool(inputs.get("ownerOccupied")),
        "raw_assessor_text": inputs.get("rawAssessorText")
    }
    ai_exp = ai_expense_pack(ai_payload) if ai_expense_pack else None

    if ai_exp and "tax" in ai_exp:
        ai_tax = ai_exp["tax"]
        ai_conf = _rank(ai_tax.get("confidence"))
        ai_curr = n(ai_tax.get("current_year_est"))
        base_curr = n(chosen_tax.get("current_year_est"))
        if (not chosen_tax) or (ai_conf >= OVERRIDE_CONF and ai_curr > 0 and (base_curr == 0 or 0.5*base_curr <= ai_curr <= 1.5*base_curr)):
            chosen_tax = {
                "prior_year": ai_tax.get("prior_year"),
                "prior_amount": n(ai_tax.get("prior_amount")),
                "current_year_est": n(ai_tax.get("current_year_est")),
                "source": "ai_expense"
            }

    expense_block = {
        "tax_current_year_est": chosen_tax.get("current_year_est"),
        "insurance_annual_est": n(ai_exp.get("insurance_annual_est")) if ai_exp else None,
        "hoa_monthly_est": n(ai_exp.get("hoa_monthly_est")) if ai_exp else None,
        "utilities_monthly_est": n(ai_exp.get("utilities_monthly_est")) if ai_exp else None,
        "pm_pct_est": n(ai_exp.get("pm_pct_est")) if ai_exp else None,
        "maint_pct_est": n(ai_exp.get("maint_pct_est")) if ai_exp else None,
        "restriction_hint": (ai_exp or {}).get("restriction_hint"),
        "notes": (ai_exp or {}).get("notes"),
        "confidence": (ai_exp or {}).get("confidence")
    }

    ai_appr = ai_appreciation({
        "address": inputs.get("address"),
        "city": inputs.get("city"),
        "state": inputs.get("state"),
        "zip": inputs.get("zip"),
        "propertyType": inputs.get("propertyType"),
        "purchasePrice": inputs.get("purchasePrice") or inputs.get("homeValue"),
        "year_built": inputs.get("yearBuilt"),
        "sqft": inputs.get("sqft"),
        "horizon_years": [1, 3, 5]
    }) if ai_appreciation else None

    rent_ai = prefetch_estimate(dict(inputs), chosen_tax) if prefetch_estimate else None

    out = {
        "ok": True,
        "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                          inputs.get("state"), inputs.get("zip")] if s]),
        "taxes": chosen_tax,
        "ai": {
            "rent": (rent_ai or {}).get("rent") if isinstance(rent_ai, dict) else None,
            "expenses": expense_block,
            "appreciation": ai_appr or None
        }
    }
    blob_cache_put(CACHE_GROUP, cache_key, out)
    return out