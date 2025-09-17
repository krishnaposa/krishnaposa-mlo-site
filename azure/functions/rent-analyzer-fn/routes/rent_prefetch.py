# routes/rent_prefetch.py
import logging
from typing import Optional, Dict, Any

from utils.common import n
from utils.cache import make_cache_key, blob_cache_get, blob_cache_put
from services.aoai_expenses import ai_expense_pack
from services.aoai import prefetch_estimate
from services.aoai_appreciation import ai_appreciation
from services.aoai_tax import ai_tax_estimate
from services.tax_providers import estimate_fallback  # fallback only

# Confidence gating for AI-tax override
_CONF = {"low": 0, "medium": 1, "high": 2}
OVERRIDE_CONF = _CONF["high"]
def _rank(label: str) -> int: return _CONF.get(str(label or "").lower(), 0)

# Cache
CACHE_GROUP = "rent-prefetch"
CACHE_TTL_SEC = 12 * 60 * 60


def _normalize_tax(tax: Optional[dict], source: str) -> dict:
    if not isinstance(tax, dict):
        return {}
    return {
        "prior_year": tax.get("prior_year"),
        "prior_amount": n(tax.get("prior_amount")),
        "current_year_est": n(tax.get("current_year_est")),
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


def run_rent_prefetch(inputs: dict, ai_mode: str = "auto") -> dict:
    """
    ai_mode:
      - "auto"     (default): try AI; fallback if needed (taxes via non-AI fallback)
      - "required": all AI steps must succeed; on any AI failure return error
      - "off"      : skip all AI; use only non-AI (tax fallback); expenses/appreciation/rent omitted
    """
    if not (inputs.get("state") or inputs.get("zip")):
        raise ValueError("Provide at least 'state' or 'zip' for better estimates.")

    ai_mode = (ai_mode or "auto").lower().strip()
    mode_meta: Dict[str, Any] = {"mode": ai_mode}
    errors: Dict[str, str] = {}

    # ---------- Cache key (include mode so you can compare behaviors) ----------
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
    cache_key = make_cache_key(key_payload, version="prefetch-v6-aimode")
    try:
        cached = blob_cache_get(CACHE_GROUP, cache_key, max_age_sec=CACHE_TTL_SEC)
    except Exception as e:
        logging.warning("[prefetch] cache get failed: %s", e)
        cached = None
    if cached:
        return cached

    # ---------- 1) TAXES ----------
    chosen_tax: dict = {}
    if ai_mode != "off":
        try:
            ai_tax = ai_tax_estimate(inputs)  # may be None
            if ai_tax:
                chosen_tax = _normalize_tax(ai_tax, "ai_tax")
        except Exception as e:
            logging.exception("[tax] ai_tax_estimate failed")
            errors["ai_tax"] = str(e)
            if ai_mode == "required":
                # Hard fail: tax AI required
                return {
                    "ok": False,
                    "error": "ai_tax_estimate failed in required mode",
                    "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                                      inputs.get("state"), inputs.get("zip")] if s]),
                    "debug": {"errors": errors, **mode_meta}
                }

    # Fallback for taxes if AI missing/unusable (auto/off only)
    if not chosen_tax or n(chosen_tax.get("current_year_est")) <= 0:
        try:
            fb = estimate_fallback(inputs)
            if isinstance(fb, dict) and n(fb.get("current_year_est")) > 0:
                chosen_tax = _normalize_tax(fb, "fallback")
        except Exception as e:
            logging.exception("[tax] estimate_fallback failed")
            errors["tax_fallback"] = str(e)
            # In "off" mode, if fallback also fails, we still proceed with empty taxes.

    # ---------- 2) EXPENSE AI ----------
    ai_exp = None
    if ai_mode != "off":
        try:
            ai_exp = ai_expense_pack(_expense_payload(inputs))  # may be None
        except Exception as e:
            logging.exception("[expense] ai_expense_pack failed")
            errors["ai_expense"] = str(e)
            if ai_mode == "required":
                return {
                    "ok": False,
                    "error": "ai_expense_pack failed in required mode",
                    "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                                      inputs.get("state"), inputs.get("zip")] if s]),
                    "debug": {"errors": errors, **mode_meta}
                }

    # Let expense-AI override tax only if high-confidence & plausible
    if ai_exp and "tax" in ai_exp and ai_mode != "off":
        t = ai_exp["tax"] or {}
        ai_conf = _rank(t.get("confidence"))
        ai_curr = n(t.get("current_year_est"))
        base_curr = n(chosen_tax.get("current_year_est"))
        if (ai_conf >= OVERRIDE_CONF and ai_curr > 0 and (base_curr == 0 or 0.5 * base_curr <= ai_curr <= 1.5 * base_curr)):
            chosen_tax = {
                "prior_year": t.get("prior_year"),
                "prior_amount": n(t.get("prior_amount")),
                "current_year_est": ai_curr,
                "source": "ai_expense"
            }

    expense_block = {
        "tax_current_year_est": chosen_tax.get("current_year_est"),
        "insurance_annual_est": n((ai_exp or {}).get("insurance_annual_est")) if ai_exp else None,
        "hoa_monthly_est": n((ai_exp or {}).get("hoa_monthly_est")) if ai_exp else None,
        "utilities_monthly_est": n((ai_exp or {}).get("utilities_monthly_est")) if ai_exp else None,
        "pm_pct_est": n((ai_exp or {}).get("pm_pct_est")) if ai_exp else None,
        "maint_pct_est": n((ai_exp or {}).get("maint_pct_est")) if ai_exp else None,
        "restriction_hint": (ai_exp or {}).get("restriction_hint"),
        "notes": (ai_exp or {}).get("notes"),
        "confidence": (ai_exp or {}).get("confidence"),
    }

    # ---------- 3) APPRECIATION AI ----------
    ai_appr = None
    if ai_mode != "off":
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
        except Exception as e:
            logging.exception("[appr] ai_appreciation failed")
            errors["ai_appreciation"] = str(e)
            if ai_mode == "required":
                return {
                    "ok": False,
                    "error": "ai_appreciation failed in required mode",
                    "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                                      inputs.get("state"), inputs.get("zip")] if s]),
                    "debug": {"errors": errors, **mode_meta}
                }

    # ---------- 4) RENT AI (fed with chosen tax) ----------
    rent_ai = None
    if ai_mode != "off":
        try:
            rent_ai = prefetch_estimate(dict(inputs), chosen_tax)
        except Exception as e:
            logging.exception("[rent] prefetch_estimate failed")
            errors["ai_rent"] = str(e)
            if ai_mode == "required":
                return {
                    "ok": False,
                    "error": "prefetch_estimate (rent AI) failed in required mode",
                    "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                                      inputs.get("state"), inputs.get("zip")] if s]),
                    "debug": {"errors": errors, **mode_meta}
                }

    # ---------- 5) Output ----------
    out = {
        "ok": True,
        "mode": ai_mode,
        "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                          inputs.get("state"), inputs.get("zip")] if s]),
        "taxes": chosen_tax,
        "ai": {
            "rent": (rent_ai or {}).get("rent") if isinstance(rent_ai, dict) else None,
            "expenses": expense_block if ai_mode != "off" else {
                # In "off" mode, only taxes (possibly fallback) are present; other lines are None
                "tax_current_year_est": chosen_tax.get("current_year_est"),
                "insurance_annual_est": None,
                "hoa_monthly_est": None,
                "utilities_monthly_est": None,
                "pm_pct_est": None,
                "maint_pct_est": None,
                "restriction_hint": None,
                "notes": None,
                "confidence": None
            },
            "appreciation": ai_appr if ai_mode != "off" else None
        }
    }

    # ---------- 6) Cache & return ----------
    try:
        blob_cache_put(CACHE_GROUP, cache_key, out)
    except Exception as e:
        logging.warning("[prefetch] cache put failed: %s", e)

    # If we had AI errors in auto/off, include lightweight debug (non-fatal)
    if errors and ai_mode in ("auto", "off"):
        out["debug"] = {"errors": errors, **mode_meta}

    return out