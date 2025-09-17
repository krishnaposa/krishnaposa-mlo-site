# routes/tax_estimate.py
from app import app
import azure.functions as func
import json
from utils.common import cors_headers, bad_request
from services.aoai_tax import ai_tax_estimate

@app.function_name(name="tax_estimate")
@app.route(route="tax-estimate", methods=["POST","OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def tax_estimate(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers())

    try:
        body = req.get_json()
    except ValueError:
        return bad_request("Invalid JSON body.")

    payload = (body or {}).get("inputs") or {}
    # At minimum we’d like state or zip or county; value helps accuracy
    if not (payload.get("state") or payload.get("zip") or payload.get("county")):
        return bad_request("Provide at least 'state' or 'zip' or 'county' for tax estimation.")

    out = ai_tax_estimate(payload)
    if not out:
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "AI not configured or could not estimate."}),
            status_code=502, mimetype="application/json", headers=cors_headers()
        )

    return func.HttpResponse(
        json.dumps({"ok": True, "tax": out}, ensure_ascii=False),
        mimetype="application/json",
        headers=cors_headers()
    )