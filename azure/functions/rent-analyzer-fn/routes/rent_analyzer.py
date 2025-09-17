# routes/rent_analyze.py
from typing import Dict, Any, List
from utils.common import n
from services.analyzer import analyze

def _merge_prefetch_into_inputs(inputs: Dict[str, Any], prefetch: Dict[str, Any]) -> List[str]:
    """
    Mutates inputs to backfill missing fields from prefetch AI.
    Returns a list of field names we filled so you can display them in the UI.
    """
    filled: List[str] = []
    ai = (prefetch or {}).get("ai") or {}
    exp = (ai.get("expenses") or {})
    taxes = (prefetch.get("taxes") or {})
    appr = ai.get("appreciation")

    # 1) Rent: if user didn't provide, use AI rent estimate
    if inputs.get("rent") in (None, "", 0):
        est_rent = ((ai.get("rent") or {}).get("est"))
        if n(est_rent) > 0:
            inputs["rent"] = n(est_rent)
            filled.append("rent")

    # 2) Taxes (annual): prefer prefetch normalized tax; fall back to AI-expense tax
    if inputs.get("taxAnnual") in (None, "", 0):
        tax_est = n(taxes.get("current_year_est")) or n(exp.get("tax_current_year_est"))
        if tax_est > 0:
            inputs["taxAnnual"] = tax_est
            filled.append("taxAnnual")

    # 3) Insurance (annual)
    if inputs.get("insAnnual") in (None, "", 0):
        v = n(exp.get("insurance_annual_est"))
        if v > 0:
            inputs["insAnnual"] = v
            filled.append("insAnnual")

    # 4) HOA (monthly)
    if inputs.get("hoaMonthly") in (None, "", 0):
        v = n(exp.get("hoa_monthly_est"))
        if v >= 0:  # allow 0 HOA explicitly
            inputs["hoaMonthly"] = v
            filled.append("hoaMonthly")

    # 5) Utilities (monthly, landlord-paid)
    if inputs.get("utilitiesMonthly") in (None, "", 0):
        v = n(exp.get("utilities_monthly_est"))
        if v >= 0:
            inputs["utilitiesMonthly"] = v
            filled.append("utilitiesMonthly")

    # 6) Property management (%) and Maintenance/CapEx (%)
    if inputs.get("pmPct") in (None, "", 0):
        v = n(exp.get("pm_pct_est"))
        if v > 0:
            inputs["pmPct"] = v
            filled.append("pmPct")

    if inputs.get("maintPct") in (None, "", 0):
        v = n(exp.get("maint_pct_est"))
        if v > 0:
            inputs["maintPct"] = v
            filled.append("maintPct")

    # 7) Appreciation assumptions (pass through for projections, if your analyzer uses it)
    if appr is not None:
        # Keep original structure under inputs["prefetch"]["appreciation"] for transparency
        inputs.setdefault("prefetch", {})
        inputs["prefetch"]["appreciation"] = appr
        filled.append("appreciation")

    # Also store full prefetch (rent/expenses) under inputs["prefetch"] for analyzer context
    inputs.setdefault("prefetch", {})
    inputs["prefetch"].update({
        "rent": (ai.get("rent") or {}),
        "expenses": (exp or {}) | {
            "tax_current_year_est": (taxes or {}).get("current_year_est")
        }
    })

    return filled


def run_rent_analyze(inputs: dict, prefetch: dict, ai_mode: str = "auto") -> dict:
    """
    Analyze one rental deal.
      - ai_mode="auto" (default): use prefetch if provided
      - ai_mode="off"           : ignore prefetch entirely
      - ai_mode="required"      : same as auto here (AI is client/server pre-step); validation still applies
    """
    ai_mode = (ai_mode or "auto").lower().strip()

    # If AI is explicitly off, ignore prefetch data
    used_prefetch_fields: List[str] = []
    if prefetch and ai_mode != "off":
        used_prefetch_fields = _merge_prefetch_into_inputs(inputs, prefetch)

    # Validate required numeric inputs for the mortgage math
    if not n(inputs.get("purchasePrice")):
        raise ValueError("'purchasePrice' is required.")
    if not n(inputs.get("rate")) or not n(inputs.get("termYears")):
        raise ValueError("'rate' and 'termYears' are required.")

    # Optional: If user didn’t pass loanAmount/downPct, analyzer should derive from purchasePrice & downPct
    # (Assumes your analyzer handles this; otherwise inject derivations here.)

    result = analyze(inputs)

    # Add some helpful metadata for the UI
    result["prefetchUsed"] = bool(prefetch) and (ai_mode != "off")
    result["usedPrefetchFields"] = used_prefetch_fields
    result["aiMode"] = ai_mode
    # Echo a human-readable address if present
    result["address"] = ", ".join([s for s in [
        inputs.get("address"),
        inputs.get("city"),
        inputs.get("state"),
        inputs.get("zip")
    ] if s])

    return result