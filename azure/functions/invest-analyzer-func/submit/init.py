import json, uuid
import azure.functions as func
from shared import cosmos

REQUIRED = ["address","city","state","zip"]

def main(req: func.HttpRequest, starter: str) -> func.HttpResponse:
    from azure.durable_functions import DurableOrchestrationClient
    client = DurableOrchestrationClient(starter)
    try:
        body = req.get_json()
        for k in REQUIRED:
            if not body.get(k): return func.HttpResponse(
                json.dumps({"ok": False, "error": f"Missing {k}"}), status_code=400)

        analysis_id = uuid.uuid4().hex
        doc = {
            "id": analysis_id,
            "status": "queued",
            "address": {
                "line1": body["address"], "unit": body.get("unit",""),
                "city": body["city"], "state": body["state"], "zip": body["zip"]
            },
            "assumptions": {
                "dpPct": float(body.get("dpPct",20)),
                "rate": float(body.get("rate",6.75)),
                "term": int(body.get("term",30)),
                "rehab": float(body.get("rehab",0)),
                "vacancyPct": float(body.get("vacancyPct",5)),
                "mgmtPct": float(body.get("mgmtPct",8)),
                "holdYears": int(body.get("holdYears",10)),
                "hoa": float(body.get("hoa",0)),
                "insurance": float(body.get("insurance",0)),
                "taxes": float(body.get("taxes",0)),
                "maintPct": float(body.get("maintPct",5)),
                "closingPct": float(body.get("closingPct",2))
            },
            "pulls": {}, "estimates": {}, "metrics": {},
            "verdict": None, "reasons": None, "error": None
        }
        cosmos.create_doc(doc)

        # Start orchestration (instanceId == analysis_id for easy lookup)
        _ = client.start_new("Orchestrator", instance_id=analysis_id, client_input={"id": analysis_id})
        return func.HttpResponse(json.dumps({"ok": True, "id": analysis_id}),
                                 headers={"Content-Type":"application/json"})
    except Exception as e:
        return func.HttpResponse(json.dumps({"ok": False, "error": str(e)}), status_code=500)