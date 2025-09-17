# routes/all_expense.py
import json
from utils.common import cors_headers, bad_request, n
from services.tax_providers import fetch_from_county, estimate_fallback
from services.aoai_expenses import ai_expense_pack

_CONF = {"low": 0, "medium": 1, "high": 2}
OVERRIDE_CONF = _CONF["high"]
def _rank(c): return _CONF.get(str(c or "").lower(), 0)

def run_all_expense(inputs: dict) -> dict:
    if not (inputs.get("state") or inputs.get("zip")):
        raise ValueError("Provide at least 'state' or 'zip' for expense estimation.")

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
    ai = ai_expense_pack(ai_payload)

    if ai and "tax" in ai:
        ai_conf = _rank(ai["tax"].get("confidence"))
        ai_curr = n(ai["tax"].get("current_year_est"))
        base_curr = n(chosen_tax.get("current_year_est"))
        if not chosen_tax or (ai_conf >= OVERRIDE_CONF and ai_curr > 0 and (base_curr == 0 or 0.5*base_curr <= ai_curr <= 1.5*base_curr)):
            chosen_tax = {
                "prior_year": ai["tax"].get("prior_year"),
                "prior_amount": n(ai["tax"].get("prior_amount")),
                "current_year_est": n(ai["tax"].get("current_year_est")),
                "source": "ai_expense"
            }

    pack = {
        "taxes": chosen_tax,
        "insurance_annual_est": n(ai.get("insurance_annual_est")) if ai else None,
        "hoa_monthly_est": n(ai.get("hoa_monthly_est")) if ai else None,
        "utilities_monthly_est": n(ai.get("utilities_monthly_est")) if ai else None,
        "pm_pct_est": n(ai.get("pm_pct_est")) if ai else None,
        "maint_pct_est": n(ai.get("maint_pct_est")) if ai else None,
        "restriction_hint": (ai or {}).get("restriction_hint"),
        "notes": (ai or {}).get("notes"),
        "confidence": (ai or {}).get("confidence")
    }

    return {
        "ok": True,
        "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                          inputs.get("state"), inputs.get("zip")] if s]),
        "expense_pack": pack
    }