# routes/rent_prefetch.py
from app import app
import azure.functions as func
import json

from utils.common import cors_headers, bad_request, n
from services.tax_providers import fetch_from_county, estimate_fallback
from services.aoai_expenses import ai_expense_pack       # <— unified expense AI (tax + others)
from services.aoai import prefetch_estimate              # <— rent AI

# Confidence gating for AI tax replacing county/fallback
_CONF = {"low": 0, "medium": 1, "high": 2}
OVERRIDE_CONF = _CONF["high"]  # require "high" confidence to override county/fallback tax

def _rank(label: str) -> int:
    return _CONF.get(str(label or "").lower(), 0)

@app.function_name(name="rent_prefetch")
@app.route(route="rent-prefetch", methods=["POST","OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def rent_prefetch(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers())

    try:
        body = req.get_json()
    except ValueError:
        return bad_request("Invalid JSON body.")

    inputs = (body or {}).get("inputs") or {}
    if not (inputs.get("state") or inputs.get("zip")):
        return bad_request("Provide at least 'state' or 'zip' for better estimates.")

    # ---------- 1) BASE TAX via county provider or heuristic fallback ----------
    county = fetch_from_county(inputs) or estimate_fallback(inputs)
    chosen_tax = dict(county) if isinstance(county, dict) else {}

    # ---------- 2) ALL-EXPENSE AI (tax + insurance + HOA + utilities + PM% + maint%) ----------
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
    ai_exp = ai_expense_pack(ai_payload)  # may be None

    # Decide if AI tax should override the county/fallback tax
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

    # Build normalized expense block from AI
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

    # ---------- 3) RENT AI using the chosen taxes & expense context ----------
    # (So rent model knows the carrying costs and locale.)
    rent_ai_inputs = dict(inputs)  # shallow copy is fine (we only read)
    rent_context   = { "taxes": chosen_tax, "expenses": expense_block }
    rent_ai = prefetch_estimate(rent_ai_inputs, chosen_tax)  # your existing rent prefetch (kept simple)

    # ---------- 4) Return a single normalized prefetch object ----------
    out = {
        "ok": True,
        "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                          inputs.get("state"), inputs.get("zip")] if s]),
        "taxes": chosen_tax,            # {prior_year, prior_amount, current_year_est, source}
        "ai": {
            "rent": (rent_ai or {}).get("rent") if isinstance(rent_ai, dict) else None,
            "expenses": expense_block
        }
    }

    return func.HttpResponse(json.dumps(out, ensure_ascii=False),
                             mimetype="application/json", headers=cors_headers())