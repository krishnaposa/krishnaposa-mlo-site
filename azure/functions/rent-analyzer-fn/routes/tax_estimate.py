# routes/tax_estimate.py
import logging
from typing import Optional, Dict, Any

from utils.common import n
from utils.cache import make_cache_key, blob_cache_get, blob_cache_put
from services.aoai_tax import ai_tax_estimate
from services.tax_providers import estimate_fallback  # non-AI fallback

CACHE_GROUP = "tax-estimate"
CACHE_TTL_SEC = 6 * 60 * 60  # 6h

def _normalize_tax(tax: Optional[dict], source: str) -> dict:
    if not isinstance(tax, dict):
        return {}
    return {
        "prior_year":        tax.get("prior_year"),
        "prior_amount":      n(tax.get("prior_amount")),
        "current_year_est":  n(tax.get("current_year_est")),
        "source":            source
    }

def run_tax_estimate(inputs: dict, ai_mode: str = "auto") -> dict:
    """
    Estimate property taxes with optional AI and fallback.

    ai_mode:
      - "auto"     : try AI first; on failure, fall back to non-AI estimate (default)
      - "required" : AI must succeed; if AI fails, return error (no fallback)
      - "off"      : skip AI entirely; use non-AI fallback only
    """
    if not (inputs.get("state") or inputs.get("zip") or inputs.get("county")):
        raise ValueError("Provide at least 'state' or 'zip' or 'county' for tax estimation.")

    ai_mode = (ai_mode or "auto").lower().strip()
    errors: Dict[str, str] = {}

    # Cache key (include ai_mode so you can compare behaviors)
    key_payload = {
        "address": inputs.get("address"),
        "city": inputs.get("city"),
        "state": inputs.get("state"),
        "zip": inputs.get("zip"),
        "county": inputs.get("county"),
        "purchasePrice": inputs.get("purchasePrice") or inputs.get("homeValue"),
        "assessedValue": inputs.get("assessedValue"),
        "millage": inputs.get("millage"),
        "mode": ai_mode,
    }
    cache_key = make_cache_key(key_payload, version="tax-estimate-v2-aimode")
    try:
        cached = blob_cache_get(CACHE_GROUP, cache_key, max_age_sec=CACHE_TTL_SEC)
    except Exception as e:
        logging.warning("[tax-estimate] cache get failed: %s", e)
        cached = None
    if cached:
        return cached

    # Try AI (unless 'off')
    chosen = {}
    if ai_mode != "off":
        try:
            ai_out = ai_tax_estimate(inputs)  # may be None
            if ai_out:
                chosen = _normalize_tax(ai_out, "ai_tax")
        except Exception as e:
            logging.exception("[tax-estimate] ai_tax_estimate failed")
            errors["ai_tax"] = str(e)
            if ai_mode == "required":
                out = {
                    "ok": False,
                    "mode": ai_mode,
                    "error": "ai_tax_estimate failed in required mode",
                    "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                                      inputs.get("state"), inputs.get("zip")] if s]),
                    "debug": {"errors": errors}
                }
                return out

    # Fallback if needed (allowed in auto/off)
    if not chosen or n(chosen.get("current_year_est")) <= 0:
        try:
            fb = estimate_fallback(inputs)
            if isinstance(fb, dict) and n(fb.get("current_year_est")) > 0:
                chosen = _normalize_tax(fb, "fallback")
        except Exception as e:
            logging.exception("[tax-estimate] estimate_fallback failed")
            errors["fallback"] = str(e)

    # If we still don't have anything, return a clear error
    if not chosen or n(chosen.get("current_year_est")) <= 0:
        out = {
            "ok": False,
            "mode": ai_mode,
            "error": "Could not estimate property taxes.",
            "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                              inputs.get("state"), inputs.get("zip")] if s]),
        }
        if errors and ai_mode in ("auto", "off"):
            out["debug"] = {"errors": errors}
        return out

    out = {
        "ok": True,
        "mode": ai_mode,
        "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                          inputs.get("state"), inputs.get("zip")] if s]),
        "tax": chosen
    }

    # Cache and return
    try:
        blob_cache_put(CACHE_GROUP, cache_key, out)
    except Exception as e:
        logging.warning("[tax-estimate] cache put failed: %s", e)

    # Attach non-fatal debug if there were AI errors in auto/off
    if errors and ai_mode in ("auto", "off"):
        out["debug"] = {"errors": errors}

    return out