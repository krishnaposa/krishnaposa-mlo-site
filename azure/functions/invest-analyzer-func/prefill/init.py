# prefill/__init__.py  (Azure Functions Python)
import json, re
import azure.functions as func

def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data = req.get_json()
    except:
        data = {}

    addr = (data.get("address") or "").strip()
    if not addr:
        return func.HttpResponse(json.dumps({"ok": False, "error": "missing address"}), status_code=400, mimetype="application/json")

    # naive parse (you likely have better)
    m = re.search(r"^(.*?),\s*(.*?),\s*([A-Z]{2})\s*(\d{5})", addr)
    parts = {"street": None, "city": None, "state": None, "zip": None}
    if m:
        parts = {"street": m.group(1), "city": m.group(2), "state": m.group(3), "zip": m.group(4)}

    # TODO: replace these with real pulls (Redfin/Playwright, RentCast, county tax, etc.)
    estimates = {
        "hoa_monthly": 0,            # from Redfin if available
        "tax_monthly": 300,          # heuristic or county lookup
        "insurance_monthly": 100,    # heuristic baseline
        "suggested_price": None,     # last sale or AVM if you have it
        "rent_monthly": None         # from RentCast/Zillow/etc
    }

    return func.HttpResponse(
        json.dumps({"ok": True, "address_parts": parts, "estimates": estimates, "note": "prefill ready"}),
        mimetype="application/json"
    )