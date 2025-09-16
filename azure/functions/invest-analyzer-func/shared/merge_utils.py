# shared/merge_utils.py
# ---------------------------------------------------------
# Merge helpers for Redfin/Zillow enrichment.
# - Accepts dictionaries returned by your smart scrapers:
#     redfin = {"ok": bool, "url": str, "address_parts": {...}, "estimates": {...}}
#     zillow = {"ok": bool, "url": str, "address_parts": {...}, "estimates": {...}}
# - Produces a consistent prefill payload with provenance for UI badges.
# ---------------------------------------------------------

from __future__ import annotations
from typing import Any, Dict, Optional

def _clean_str(x: Optional[str]) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip()
    return s or None

def _norm_addr(parts: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    parts = parts or {}
    return {
        "street": _clean_str(parts.get("street") or parts.get("address") or parts.get("line")),
        "city":   _clean_str(parts.get("city")),
        "state":  _clean_str(parts.get("state")),
        "zip":    _clean_str(str(parts.get("zip")) if parts.get("zip") is not None else None),
    }

def _first_non_null(*vals):
    for v in vals:
        if v is not None:
            return v
    return None

def _to_float(x) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None

def _derive_tax_monthly(annual: Optional[float]) -> Optional[float]:
    return round(float(annual) / 12.0, 2) if (annual is not None) else None

def choose_address_parts(redfin: Optional[Dict], zillow: Optional[Dict]) -> Dict[str, Optional[str]]:
    """Prefer Redfin address parts; if missing, fall back to Zillow."""
    rf = _norm_addr((redfin or {}).get("address_parts"))
    zf = _norm_addr((zillow or {}).get("address_parts"))
    return {
        "street": _first_non_null(rf.get("street"), zf.get("street")),
        "city":   _first_non_null(rf.get("city"),   zf.get("city")),
        "state":  _first_non_null(rf.get("state"),  zf.get("state")),
        "zip":    _first_non_null(rf.get("zip"),    zf.get("zip")),
    }

def merge_estimates(
    redfin: Optional[Dict[str, Any]],
    zillow: Optional[Dict[str, Any]],
    *,
    prefer: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Merge numeric estimates from Redfin + Zillow with clear precedence.
    `prefer` can override defaults per field with "redfin" or "zillow".
      Defaults:
        - hoa_monthly:       redfin > zillow
        - property_tax_annual: redfin > zillow
        - suggested_price:   explicit price (redfin or zillow) > zestimate
        - rent_monthly:      zillow.rent_zestimate > redfin.rent_monthly
        - insurance_monthly: redfin > 100 baseline
    Returns:
      {
        "address_parts": {...},
        "estimates": {
           "hoa_monthly", "property_tax_annual", "tax_monthly",
           "insurance_monthly", "suggested_price", "rent_monthly",
           "zestimate"  # included if present for transparency
        },
        "sources": { "hoa_monthly": "Redfin", "property_tax_annual": "Zillow", ... },
        "links":   { "redfin": "<url-or-none>", "zillow": "<url-or-none>" }
      }
    """
    prefer = prefer or {}

    rf = (redfin or {})
    zf = (zillow or {})
    rfe = (rf.get("estimates") or {})
    zfe = (zf.get("estimates") or {})

    # ---- Inputs we'll consider ----
    rf_hoa   = _to_float(rfe.get("hoa_monthly"))
    zf_hoa   = _to_float(zfe.get("hoa_monthly"))

    rf_tax_a = _to_float(rfe.get("property_tax_annual"))
    zf_tax_a = _to_float(zfe.get("property_tax_annual"))

    # Price signals
    rf_price = _to_float(rfe.get("suggested_price"))
    zf_price = _to_float(zfe.get("suggested_price"))
    zf_zest  = _to_float(zfe.get("zestimate"))

    # Rent signals
    rf_rent  = _to_float(rfe.get("rent_monthly"))
    zf_rent  = _to_float(zfe.get("rent_zestimate"))  # Zillow-specific key

    # Insurance baseline
    rf_ins   = _to_float(rfe.get("insurance_monthly"))
    baseline_ins = 100.0

    # ---- Decide per-field with precedence + provenance ----
    src = {}

    # HOA
    if prefer.get("hoa_monthly") == "zillow":
        hoa = _first_non_null(zf_hoa, rf_hoa)
        src["hoa_monthly"] = "Zillow" if zf_hoa is not None else ("Redfin" if rf_hoa is not None else None)
    else:
        hoa = _first_non_null(rf_hoa, zf_hoa)
        src["hoa_monthly"] = "Redfin" if rf_hoa is not None else ("Zillow" if zf_hoa is not None else None)

    # Property tax (annual)
    if prefer.get("property_tax_annual") == "zillow":
        tax_a = _first_non_null(zf_tax_a, rf_tax_a)
        src["property_tax_annual"] = "Zillow" if zf_tax_a is not None else ("Redfin" if rf_tax_a is not None else None)
    else:
        tax_a = _first_non_null(rf_tax_a, zf_tax_a)
        src["property_tax_annual"] = "Redfin" if rf_tax_a is not None else ("Zillow" if zf_tax_a is not None else None)

    # Suggested price (prefer explicit price; fall back to Zestimate)
    # You can swap the order with `prefer["suggested_price"]`
    if prefer.get("suggested_price") == "zillow":
        suggested_price = _first_non_null(zf_price, rf_price, zf_zest)
        if zf_price is not None:   src["suggested_price"] = "Zillow"
        elif rf_price is not None: src["suggested_price"] = "Redfin"
        elif zf_zest is not None:  src["suggested_price"] = "Zillow (Zestimate)"
        else:                      src["suggested_price"] = None
    else:
        suggested_price = _first_non_null(rf_price, zf_price, zf_zest)
        if rf_price is not None:   src["suggested_price"] = "Redfin"
        elif zf_price is not None: src["suggested_price"] = "Zillow"
        elif zf_zest is not None:  src["suggested_price"] = "Zillow (Zestimate)"
        else:                      src["suggested_price"] = None

    # Rent (prefer Zillow rentZestimate unless overridden)
    if prefer.get("rent_monthly") == "redfin":
        rent = _first_non_null(rf_rent, zf_rent)
        src["rent_monthly"] = "Redfin" if rf_rent is not None else ("Zillow (Rent Zestimate)" if zf_rent is not None else None)
    else:
        rent = _first_non_null(zf_rent, rf_rent)
        src["rent_monthly"] = "Zillow (Rent Zestimate)" if zf_rent is not None else ("Redfin" if rf_rent is not None else None)

    # Insurance monthly
    if prefer.get("insurance_monthly") == "zillow":
        # Zillow usually doesn't provide insurance; keep structure anyway
        ins = _first_non_null(zfe.get("insurance_monthly"), rf_ins, baseline_ins)
        src["insurance_monthly"] = (
            "Zillow" if zfe.get("insurance_monthly") is not None
            else ("Redfin" if rf_ins is not None else "Baseline")
        )
    else:
        ins = _first_non_null(rf_ins, zfe.get("insurance_monthly"), baseline_ins)
        src["insurance_monthly"] = (
            "Redfin" if rf_ins is not None
            else ("Zillow" if zfe.get("insurance_monthly") is not None else "Baseline")
        )

    # Derived monthly tax
    tax_m = _derive_tax_monthly(tax_a)

    # Address parts
    addr = choose_address_parts(redfin, zillow)

    # Links out (helpful for UI)
    links = {
        "redfin": (redfin or {}).get("url"),
        "zillow": (zillow or {}).get("url")
    }

    estimates = {
        "hoa_monthly": hoa,
        "property_tax_annual": tax_a,
        "tax_monthly": tax_m,
        "insurance_monthly": ins,
        "suggested_price": suggested_price,
        "rent_monthly": rent,
        # optional transparency fields
        "zestimate": zf_zest
    }

    return {
        "address_parts": addr,
        "estimates": estimates,
        "sources": src,
        "links": links
    }

def merge_prefill_result(
    redfin: Optional[Dict[str, Any]],
    zillow: Optional[Dict[str, Any]],
    *,
    prefer: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Convenience wrapper that formats the final prefill payload your frontend expects.
    """
    pref = merge_estimates(redfin, zillow, prefer=prefer)
    # Compose a nice single-line address if possible
    ap = pref["address_parts"]
    address_text = ", ".join([s for s in [ap.get("street"), ap.get("city"), ap.get("state"), ap.get("zip")] if s])

    return {
        "ok": True if any(pref["estimates"].values()) or any(ap.values()) else False,
        "address_parts": ap,
        "address_text": address_text or None,
        "estimates": pref["estimates"],
        "sources": pref["sources"],
        "links": pref["links"]
    }