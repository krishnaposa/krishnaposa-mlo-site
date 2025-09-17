# routes/tax_estimate.py
from services.aoai_tax import ai_tax_estimate

def run_tax_estimate(inputs: dict) -> dict:
    if not (inputs.get("state") or inputs.get("zip") or inputs.get("county")):
        raise ValueError("Provide at least 'state' or 'zip' or 'county' for tax estimation.")
    out = ai_tax_estimate(inputs)
    if not out:
        return {"ok": False, "error": "AI not configured or could not estimate."}
    return {"ok": True, "tax": out}