# routes/rent_prefetch.py
import logging
from utils.common import n
from utils.cache import make_cache_key, blob_cache_get, blob_cache_put
from services.aoai_expenses import ai_expense_pack
from services.aoai import prefetch_estimate
from services.aoai_appreciation import ai_appreciation
from services.aoai_tax import ai_tax_estimate
from services.tax_providers import estimate_fallback  # keep heuristic fallback only

_CONF = {"low": 0, "medium": 1, "high": 2}
OVERRIDE_CONF = _CONF["high"]

CACHE_GROUP = "rent-prefetch"
CACHE_TTL_SEC = 12 * 60 * 60

def _rank(label: str) -> int:
    return _CONF.get(str(label or "").lower(), 0)

def _normalize_tax(ai_tax: dict | None) -> dict:
    if not isinstance(ai_tax, dict):
        return {}
    return {
        "prior_year":  ai_tax.get("prior_year"),
        "prior_amount": n(ai_tax.get("prior_amount")),
        "current_year_est": n(ai_tax.get("current_year_est")),
        "source": "ai_tax"
    }

def run_rent_prefetch(inputs: dict) -> dict:
    if not (inputs.get("state") or inputs.get("zip")):
        raise ValueError("Provide at least 'state' or 'zip' for better estimates.")

    # ---------- CACHE LOOKUP ----------
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
    cache_key = make_cache_key(key_payload, version="prefetch-v4-aitax")
    cached = blob_cache_get(CACHE_GROUP, cache_key, max_age_sec=CACHE_TTL_SEC)
    if cached:
        return cached

    # ---------- 1) TAX via AOAI (primary) ----------
    chosen_tax = {}
    try:
        ai_tax = ai_tax_estimate(inputs)
        if ai_tax:
            chosen_tax = _normalize_tax(ai_tax)
    except Exception:
        logging.exception("[tax] ai_tax_estimate failed")

    # Fallback heuristic if AI unavailable or produced no usable current_year_est
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

    # ---------- 2) ALL-EXPENSE AI ----------
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
    ai_exp = None
    try:
        ai_exp = ai_expense_pack(ai_payload)
    except Exception:
        logging.exception("[expense] ai_expense_pack failed")

    # If expense AI has a strong tax and it’s plausible, allow it to override
    if ai_exp and "tax" in ai_exp:
        ai_tax2 = ai_exp["tax"] or {}
        ai_conf = _rank(ai_tax2.get("confidence"))
        ai_curr = n(ai_tax2.get("current_year_est"))
        base_curr = n(chosen_tax.get("current_year_est"))
        if (ai_conf >= OVERRIDE_CONF and ai_curr > 0 and (base_curr == 0 or 0.5*base_curr <= ai_curr <= 1.5*base_curr)):
            chosen_tax = {
                "prior_year": ai_tax2.get("prior_year"),
                "prior_amount": n(ai_tax2.get("prior_amount")),
                "current_year_est": ai_curr,
                "source": "ai_expense"
            }

    expense_block = {
        "tax_current_year_est": chosen_tax.get("current_year_est"),
        "insurance_annual_est": n((ai_exp or {}).get("insurance_annual_est")),
        "hoa_monthly_est": n((ai_exp or {}).get("hoa_monthly_est")),
        "utilities_monthly_est": n((ai_exp or {}).get("utilities_monthly_est")),
        "pm_pct_est": n((ai_exp or {}).get("pm_pct_est")),
        "maint_pct_est": n((ai_exp or {}).get("maint_pct_est")),
        "restriction_hint": (ai_exp or {}).get("restriction_hint"),
        "notes": (ai_exp or {}).get("notes"),
        "confidence": (ai_exp or {}).get("confidence")
    }

    # ---------- 3) APPRECIATION AI ----------
    ai_appr = None
    try:
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
        })
    except Exception:
        logging.exception("[appr] ai_appreciation failed")

    # ---------- 4) RENT AI ----------
    rent_ai = None
    try:
        rent_ai = prefetch_estimate(dict(inputs), chosen_tax)
    except Exception:
        logging.exception("[rent] prefetch_estimate failed")

    # ---------- 5) Normalized output ----------
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