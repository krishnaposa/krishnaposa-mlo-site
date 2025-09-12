import json
import azure.functions as func
from shared import cosmos

def main(req: func.HttpRequest) -> func.HttpResponse:
    i = req.params.get("id")
    if not i:
        return func.HttpResponse(json.dumps({"ok": False, "error": "Missing id"}), status_code=400)
    doc = cosmos.get_doc(i)
    if not doc:
        return func.HttpResponse(json.dumps({"ok": False, "error": "Not found"}), status_code=404)
    return func.HttpResponse(json.dumps({"ok": True, "analysis": doc}),
                             headers={"Content-Type":"application/json"})