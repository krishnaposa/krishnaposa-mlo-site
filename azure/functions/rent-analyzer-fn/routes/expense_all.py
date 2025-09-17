# routes/all_expense.py
import logging
from utils.common import n
from services.aoai_expenses import ai_expense_pack
from services.aoai_tax import ai_tax_estimate
from services.tax_providers import estimate_fallback  # keep heuristic fallback only

# Confidence gating for AI tax override
_CONF = {"low": 0, "medium": 1, "high": 2}
OVERRIDE_CONF = _CONF["high"]
def _rank(c): return _CONF.get(str(c or "").lower(), 0)

def _normalize_tax(ai_tax: dict | None) -> dict:
    if not isinstance(ai_tax, dict):
        return {}
    return {
        "prior_year":  ai_tax.get("prior_year"),
        "prior_amount": n(ai_tax.get("prior_amount")),
        "current_year_est": n(ai_tax.get("current_year_est")),
        "source": "ai_tax"
    }

def run_all_expense(inputs: dict) -> dict:
    if not (inputs.get("state") or inputs.get("zip")):
        raise ValueError("Provide at least 'state' or 'zip' for expense estimation.")

    # 1) Tax via AOAI first
    chosen_tax = {}
    ai_tax = None
    try:
        ai_tax = ai_tax_estimate(inputs)  # may be None
    except Exception:
        logging.exception("[tax] ai_tax_estimate failed")

    if ai_tax:
        chosen_tax = _normalize_tax(ai_tax)

    # 2) If AI tax missing/weak, fallback heuristic
    if not chosen_tax or n(chosen_tax.get("current_year_est")) <= 0:
        try:
            fb = estimate_fallback(inputs)
            if isinstance(fb, dict) and n(fb.get("current_year_est")) > 0:
                chosen_tax = {
                    "prior_year": fb.get("prior_year"),
                    "prior_amount": n(fb.get("prior_amount")),
                    "current_year_est": n(fb.get("current_year_est")),
                    "source": "fallback"
                }
        except Exception:
            logging.exception("[tax] estimate_fallback failed")

    # 3) Ask AOAI for full expense pack (can include its own tax view too)
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
    ai = None
    try:
        ai = ai_expense_pack(ai_payload)
    except Exception:
        logging.exception("[expense] ai_expense_pack failed")

    # 4) If expense AI returns its own tax and it’s high-confidence & plausible, let it replace
    if ai and "tax" in ai:
        t = ai["tax"] or {}
        ai_conf = _rank(t.get("confidence"))
        ai_curr = n(t.get("current_year_est"))
        base_curr = n(chosen_tax.get("current_year_est"))
        if (ai_conf >= OVERRIDE_CONF and ai_curr > 0 and (base_curr == 0 or 0.5*base_curr <= ai_curr <= 1.5*base_curr)):
            chosen_tax = {
                "prior_year": t.get("prior_year"),
                "prior_amount": n(t.get("prior_amount")),
                "current_year_est": ai_curr,
                "source": "ai_expense"
            }

    # 5) Normalized expense pack
    pack = {
        "taxes": chosen_tax,  # {prior_year, prior_amount, current_year_est, source}
        "insurance_annual_est": n((ai or {}).get("insurance_annual_est")),
        "hoa_monthly_est": n((ai or {}).get("hoa_monthly_est")),
        "utilities_monthly_est": n((ai or {}).get("utilities_monthly_est")),
        "pm_pct_est": n((ai or {}).get("pm_pct_est")),
        "maint_pct_est": n((ai or {}).get("maint_pct_est")),
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