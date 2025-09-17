from app import app
import azure.functions as func
import json, math

from utils.common import cors_headers, bad_request, n
from services.tax_providers import fetch_from_county, estimate_fallback
from services.aoai import prefetch_estimate       # AI rent + expenses
from services.aoai_tax import ai_tax_estimate     # AI tax

# Confidence gating for AI tax to override county/fallback
AI_TAX_MIN_CONFIDENCE = (  # low < medium < high
    {"low": 0, "medium": 1, "high": 2}
)
AI_TAX_OVERRIDE_THRESHOLD = AI_TAX_MIN_CONFIDENCE["high"]  # require "high" to override

def _conf_rank(label: str) -> int:
    return AI_TAX_MIN_CONFIDENCE.get(str(label or "").lower(), 0)

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

    # ---------- 1) TAX from county provider or heuristic ----------
    county = fetch_from_county(inputs) or estimate_fallback(inputs)
    chosen_tax = dict(county) if isinstance(county, dict) else {}

    # ---------- 2) AI TAX (optional) ----------
    # Give AOAI any hints we have (address/value/assessed/millage)
    ai_tax_payload = {
        "address": inputs.get("address"), "city": inputs.get("city"),
        "state": inputs.get("state"), "zip": inputs.get("zip"),
        "county": inputs.get("county"),
        "value": inputs.get("purchasePrice") or inputs.get("homeValue"),
        "assessed_value": inputs.get("assessedValue"),
        "millage_per_1000": inputs.get("millage"),
        "owner_occupied": bool(inputs.get("ownerOccupied")),
        "raw_assessor_text": inputs.get("rawAssessorText")  # optional
    }
    ai_tax = ai_tax_estimate(ai_tax_payload)

    # Decide whether AI tax should override county/fallback
    if ai_tax:
        # if county is missing OR AI has high confidence and numbers are plausible (within 50% band)
        ai_conf = _conf_rank(ai_tax.get("confidence"))
        if not chosen_tax or ai_conf >= AI_TAX_OVERRIDE_THRESHOLD:
            # sanity check: avoid wild outliers
            ai_curr = n(ai_tax.get("current_year_est"))
            base_curr = n(chosen_tax.get("current_year_est"))
            if ai_curr > 0 and (base_curr == 0 or 0.5 * base_curr <= ai_curr <= 1.5 * base_curr):
                chosen_tax = {
                    "prior_year": ai_tax.get("prior_year"),
                    "prior_amount": n(ai_tax.get("prior_amount")),
                    "current_year_est": n(ai_tax.get("current_year_est")),
                    "source": "ai_tax"
                }

    # ---------- 3) AI RENT + EXPENSES, with chosen tax fed as context ----------
    ai_rent_exp = prefetch_estimate(inputs, chosen_tax)  # may be None

    # Normalize output shape for the analyzer
    out = {
        "ok": True,
        "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                          inputs.get("state"), inputs.get("zip")] if s]),
        "taxes": chosen_tax,        # {prior_year, prior_amount, current_year_est, source}
        "ai": ai_rent_exp or None   # { rent:{est,low,high,confidence,notes}, expenses:{...} }
    }

    return func.HttpResponse(json.dumps(out, ensure_ascii=False),
                             mimetype="application/json", headers=cors_headers())