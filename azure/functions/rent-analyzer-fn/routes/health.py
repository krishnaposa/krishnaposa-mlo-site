# routes/health.py
from function_app import app
import azure.functions as func
from utils.common import cors_headers

@app.function_name(name="health")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse('{"ok": true}', mimetype="application/json", headers=cors_headers())