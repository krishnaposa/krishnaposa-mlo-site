# routes/expense_all.py
from function_app import app
import azure.functions as func
import json
from utils.common import cors_headers, bad_request, n
from services.tax_providers import fetch_from_county, estimate_fallback
from services.aoai_expenses import ai_expense_pack

# Confidence gating for AI tax override
_CONF = {"low": 0, "medium": 1, "high": 2}
OVERRIDE_CONF = _CONF["high"]  # require "high" to override county/fallback tax

def _rank(c): return _CONF.get(str(c or "").lower(), 0)

@app.function_name(name="all_expense")
@app.route(route="all-expense", methods=["POST","OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def all_expense(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers())

    try:
        body = req.get_json()
    except ValueError:
        return bad_request("Invalid JSON body.")

    inputs = (body or {}).get("inputs") or {}
    if not (inputs.get("state") or inputs.get("zip")):
        return bad_request("Provide at least 'state' or 'zip' for expense estimation.")

    # 1) County/fallback taxes first
    county = fetch_from_county(inputs) or estimate_fallback(inputs)
    chosen_tax = dict(county) if isinstance(county, dict) else {}

    # 2) Ask AOAI for the full expense pack (including its own tax view)
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

    # 3) Merge logic (prefer county unless AI is high-confidence and plausible)
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

    # Build normalized expense pack
    pack = {
        "taxes": chosen_tax,  # {prior_year, prior_amount, current_year_est, source}
        "insurance_annual_est": n(ai.get("insurance_annual_est")) if ai else None,
        "hoa_monthly_est": n(ai.get("hoa_monthly_est")) if ai else None,
        "utilities_monthly_est": n(ai.get("utilities_monthly_est")) if ai else None,
        "pm_pct_est": n(ai.get("pm_pct_est")) if ai else None,
        "maint_pct_est": n(ai.get("maint_pct_est")) if ai else None,
        "restriction_hint": (ai or {}).get("restriction_hint"),
        "notes": (ai or {}).get("notes"),
        "confidence": (ai or {}).get("confidence")
    }

    out = {
        "ok": True,
        "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                          inputs.get("state"), inputs.get("zip")] if s]),
        "expense_pack": pack
    }
    return func.HttpResponse(json.dumps(out, ensure_ascii=False),
                             mimetype="application/json", headers=cors_headers())