# function_app.py (root, next to host.json)
import azure.functions as func
import json

# Create the Function App instance
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# --- Health check ---
@app.function_name(name="health")
@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"ok": True}),
        mimetype="application/json"
    )

# --- Simple rental prefetch stub ---
@app.function_name(name="rent_prefetch")
@app.route(route="rent-prefetch", methods=["POST"])
def rent_prefetch(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "Invalid JSON"}),
            status_code=400,
            mimetype="application/json"
        )

    # Just echo back for now
    return func.HttpResponse(
        json.dumps({"ok": True, "inputs": body}, ensure_ascii=False),
        mimetype="application/json"
    )