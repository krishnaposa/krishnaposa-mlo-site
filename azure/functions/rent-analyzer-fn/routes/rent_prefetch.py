# routes/rent_prefetch.py
from app import app
import azure.functions as func
import json
from utils.common import cors_headers, bad_request
from services.tax_providers import fetch_from_county, estimate_fallback
from services.aoai import prefetch_estimate

@app.function_name(name="rent_prefetch")
@app.route(route="rent-prefetch", methods=["POST","OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def rent_prefetch(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers())

    try:
        body = req.get_json()
    except ValueError:
        return bad_request("Invalid JSON body.")

    inputs = (body or {}).get("inputs") or {}
    if not (inputs.get("state") or inputs.get("zip")):
        return bad_request("Provide at least 'state' or 'zip' for better estimates.")

    county = fetch_from_county(inputs) or estimate_fallback(inputs)
    ai = prefetch_estimate(inputs, county)

    out = {
        "ok": True,
        "address": ", ".join([s for s in [inputs.get("address"), inputs.get("city"),
                                          inputs.get("state"), inputs.get("zip")] if s]),
        "taxes": county,
        "ai": ai or None
    }
    return func.HttpResponse(json.dumps(out, ensure_ascii=False),
                             mimetype="application/json", headers=cors_headers())