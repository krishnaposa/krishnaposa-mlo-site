# routes/rent_analyze.py
from app import app
import azure.functions as func
import json
from utils.common import cors_headers, bad_request, n
from services.analyzer import analyze

@app.function_name(name="rent_analyze")
@app.route(route="rent-analyze", methods=["POST","OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def rent_analyze(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers())

    try:
        body = req.get_json()
    except ValueError:
        return bad_request("Invalid JSON body.")

    inputs = (body or {}).get("inputs") or {}
    prefetch = (body or {}).get("prefetch") or {}
    # Flatten prefetch so analyzer can consume it via inputs["prefetch"]
    if prefetch:
        ai = prefetch.get("ai") or {}
        inputs["prefetch"] = {
            "rent": (ai.get("rent") or {}),
            "expenses": (ai.get("expenses") or {}) | {
                "tax_current_year_est": (prefetch.get("taxes") or {}).get("current_year_est")
            }
        }

    if not n(inputs.get("purchasePrice")):
        return bad_request("'purchasePrice' is required.")
    if not n(inputs.get("rate")) or not n(inputs.get("termYears")):
        return bad_request("'rate' and 'termYears' are required.")

    result = analyze(inputs)
    result["prefetchUsed"] = bool(prefetch)
    return func.HttpResponse(json.dumps(result, ensure_ascii=False),
                             mimetype="application/json", headers=cors_headers())