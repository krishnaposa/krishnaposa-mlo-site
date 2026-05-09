# routes/all_expense.py
import logging
from typing import Optional, Dict, Any

from utils.common import n
from utils.cache import make_cache_key, blob_cache_get, blob_cache_put
from services.aoai_expenses import ai_expense_pack
from services.aoai_tax import ai_tax_estimate
from services.tax_providers import estimate_fallback  # fallback only

# Confidence gating for letting expense-AI override AI-tax/fallback
_CONF = {"low": 0, "medium": 1, "high": 2}
OVERRIDE_CONF = _CONF["high"]
def _rank(c): return _CONF.get(str(c or "").lower(), 0)

# Cache config
CACHE_GROUP = "all-expense"
CACHE_TTL_SEC = 6 * 60 * 60  # 6h


def _normalize_tax(ai_tax: Optional[dict], source: str = "ai_tax") -> dict:
    if not isinstance(ai_tax, dict):
        return {}
    return {
        "prior_year":  ai_tax.get("prior_year"),
        "prior_amount": n(ai_tax.get("prior_amount")),
        "current_year_est": n(ai_tax.get("current_year_est")),
        "source": source
    }


def _expense_payload(inputs: dict) -> dict:
    return {
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


def run_all_expense(inputs: dict, ai_mode: str = "auto") -> dict:
    """
    Return a normalized expense pack:
      - taxes {prior_year, prior_amount, current_year_est, source}
      - insurance_annual_est, hoa_monthly_est, utilities_monthly_est
      - pm_pct_est, maint_pct_est
      - restriction_hint, notes, confidence

    ai_mode:
      - "auto"     : try AI, fallback if needed (default)
      - "required" : AI must succeed; on failure return error
      - "off"      : skip AI; use non-AI fallback for taxes only
    """
    if not (inputs.get("state") or inputs.get("zip")):
        raise ValueError("Provide at least 'state' or 'zip' for expense estimation.")

    ai_mode = (ai_mode or "auto").lower().strip()
    errors: Dict[str, str] = {}

    # ---- Cache key includes ai_mode (so you can compare behaviors) ----
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
        "mode": ai_mode,
    }
    cache_key = make_cache_key(key_payload, version="all-expense-v2-aimode")
    try:
        cached = blob_cache_get(CACHE_GROUP, cache_key, max_age_sec=CACHE_TTL_SEC)
    except Exception as e:
        logging.warning("[all-expense] cache get failed: %s", e)
        cached = None
    if cached:
        return cached

    # ---- 1) Taxes: AI first unless ai_mode == "off" ----
    chosen_tax = {}
    if ai_mode != "off":
        try:
            ai_tax = ai_tax_estimate(inputs)  # may be None
            if ai_tax:
                chosen_tax = _normalize_tax(ai_tax, "ai_tax")
        except Exception as e:
            logging.exception("[tax] ai_tax_estimate failed")
            errors["ai_tax"] = str(e)
            if ai_mode == "required":
                out = {
                    "ok": False,
                    "error": "ai_tax_estimate failed in required mode",
                    "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                                      inputs.get("state"), inputs.get("zip")] if s]),
                    "debug": {"errors": errors, "mode": ai_mode}
                }
                return out

    # ---- 2) Tax fallback (allowed in auto/off) ----
    if not chosen_tax or n(chosen_tax.get("current_year_est")) <= 0:
        try:
            fb = estimate_fallback(inputs)
            if isinstance(fb, dict) and n(fb.get("current_year_est")) > 0:
                chosen_tax = _normalize_tax(fb, "fallback")
        except Exception as e:
            logging.exception("[tax] estimate_fallback failed")
            errors["tax_fallback"] = str(e)
            # In "off" mode we proceed; chosen_tax may be {}

    # ---- 3) Expense AI (hoa/ins/util/pm/maint + optional tax) ----
    ai = None
    if ai_mode != "off":
        try:
            ai = ai_expense_pack(_expense_payload(inputs))
        except Exception as e:
            logging.exception("[expense] ai_expense_pack failed")
            errors["ai_expense"] = str(e)
            if ai_mode == "required":
                out = {
                    "ok": False,
                    "error": "ai_expense_pack failed in required mode",
                    "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                                      inputs.get("state"), inputs.get("zip")] if s]),
                    "debug": {"errors": errors, "mode": ai_mode}
                }
                return out

    # ---- 4) Let expense-AI override tax if high-confidence and plausible ----
    if ai and "tax" in ai and ai_mode != "off":
        t = ai["tax"] or {}
        ai_conf = _rank(t.get("confidence"))
        ai_curr = n(t.get("current_year_est"))
        base_curr = n(chosen_tax.get("current_year_est"))
        if (ai_conf >= OVERRIDE_CONF and ai_curr > 0 and
            (base_curr == 0 or 0.5 * base_curr <= ai_curr <= 1.5 * base_curr)):
            chosen_tax = {
                "prior_year": t.get("prior_year"),
                "prior_amount": n(t.get("prior_amount")),
                "current_year_est": ai_curr,
                "source": "ai_expense"
            }

    # ---- 5) Build normalized pack ----
    pack = {
        "taxes": chosen_tax,  # {prior_year, prior_amount, current_year_est, source}
        "insurance_annual_est": n((ai or {}).get("insurance_annual_est")) if ai_mode != "off" else None,
        "hoa_monthly_est": n((ai or {}).get("hoa_monthly_est")) if ai_mode != "off" else None,
        "utilities_monthly_est": n((ai or {}).get("utilities_monthly_est")) if ai_mode != "off" else None,
        "pm_pct_est": n((ai or {}).get("pm_pct_est")) if ai_mode != "off" else None,
        "maint_pct_est": n((ai or {}).get("maint_pct_est")) if ai_mode != "off" else None,
        "restriction_hint": (ai or {}).get("restriction_hint") if ai_mode != "off" else None,
        "notes": (ai or {}).get("notes") if ai_mode != "off" else None,
        "confidence": (ai or {}).get("confidence") if ai_mode != "off" else None,
    }

    out = {
        "ok": True,
        "mode": ai_mode,
        "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                          inputs.get("state"), inputs.get("zip")] if s]),
        "expense_pack": pack
    }

    # ---- 6) Cache & return ----
    try:
        blob_cache_put(CACHE_GROUP, cache_key, out)
    except Exception as e:
        logging.warning("[all-expense] cache put failed: %s", e)

    # Attach non-fatal debug if there were AI errors in auto/off
    if errors and ai_mode in ("auto", "off"):
        out["debug"] = {"errors": errors, "mode": ai_mode}

    return out