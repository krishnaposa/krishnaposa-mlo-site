import json
import azure.functions as func
import azure.durable_functions as df
from shared import cosmos

RUNTIME_TO_DOC = {
    "Pending": "queued",
    "Running": "running",
    "Completed": "done",
    "Failed": "error",
    "Terminated": "error"
}

async def main(req: func.HttpRequest, starter: str) -> func.HttpResponse:
    analysis_id = req.params.get("id")
    if not analysis_id:
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "Missing id"}),
            status_code=400, mimetype="application/json"
        )

    # Read Cosmos (may be stale or not yet written)
    doc = cosmos.get_doc(analysis_id)

    # Ask Durable for live runtime status
    client = df.DurableOrchestrationClient(starter)
    dstat = await client.get_status(analysis_id, show_history=False)
    runtime_status = getattr(dstat, "runtime_status", None) if dstat else None
    runtime_str = str(runtime_status) if runtime_status is not None else None
    runtime_doc_status = RUNTIME_TO_DOC.get(runtime_str, None)

    # Build a friendly merged payload
    merged = {
        "id": analysis_id,
        "status": None,
        "runtimeStatus": runtime_str,
        "estimates": None,
        "metrics": None,
        "verdict": None,
        "reasons": None,
        "error": None
    }

    if doc:
        merged.update({
            "status": doc.get("status"),
            "estimates": doc.get("estimates"),
            "metrics": doc.get("metrics"),
            "verdict": doc.get("verdict"),
            "reasons": doc.get("reasons"),
            "error": doc.get("error")
        })

    # If Cosmos says queued/running or is missing, fall back to Durable runtime
    if not merged["status"] or merged["status"] in ("queued", "running"):
        if runtime_doc_status:
            merged["status"] = runtime_doc_status

    # If still unknown, set a safe default
    if not merged["status"]:
        merged["status"] = "unknown"

    return func.HttpResponse(
        json.dumps({"ok": True, "analysis": merged}),
        mimetype="application/json"
    )