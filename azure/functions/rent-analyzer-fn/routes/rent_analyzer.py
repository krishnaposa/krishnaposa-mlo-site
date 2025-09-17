# routes/rent_analyze.py
from utils.common import n
from services.analyzer import analyze

def run_rent_analyze(inputs: dict, prefetch: dict) -> dict:
    # Flatten prefetch into inputs["prefetch"] for analyzer
    if prefetch:
        ai = prefetch.get("ai") or {}
        inputs["prefetch"] = {
            "rent": (ai.get("rent") or {}),
            "expenses": (ai.get("expenses") or {}) | {
                "tax_current_year_est": (prefetch.get("taxes") or {}).get("current_year_est")
            },
            "appreciation": ai.get("appreciation")
        }
    if not n(inputs.get("purchasePrice")):
        raise ValueError("'purchasePrice' is required.")
    if not n(inputs.get("rate")) or not n(inputs.get("termYears")):
        raise ValueError("'rate' and 'termYears' are required.")
    result = analyze(inputs)
    result["prefetchUsed"] = bool(prefetch)
    return result