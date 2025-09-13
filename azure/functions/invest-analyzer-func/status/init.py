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

    # 1) Read Cosmos safely
    try:
        doc = cosmos.get_doc(analysis_id) or {}
    except Exception as e:
        return func.HttpResponse(
            json.dumps({"ok": False, "error": f"Cosmos error: {e}"}),
            status_code=500, mimetype="application/json"
        )

    # 2) Ask Durable safely (don’t let errors crash the response)
    runtime_str = None
    try:
        client = df.DurableOrchestrationClient(starter)
        dstat = await client.get_status(analysis_id, show_history=False)
        if dstat and getattr(dstat, "runtime_status", None) is not None:
            runtime_str = str(dstat.runtime_status)
    except Exception as e:
        # keep going; just surface the info
        runtime_str = None
        doc.setdefault("debug", {})["durable_error"] = str(e)

    runtime_doc_status = RUNTIME_TO_DOC.get(runtime_str) if runtime_str else None

    merged = {
        "id": analysis_id,
        "status": doc.get("status"),
        "runtimeStatus": runtime_str,
        "estimates": doc.get("estimates"),
        "metrics": doc.get("metrics"),
        "verdict": doc.get("verdict"),
        "reasons": doc.get("reasons"),
        "error": doc.get("error"),
    }

    # Prefer durable runtime when Cosmos is queued/running/empty
    if not merged["status"] or merged["status"] in ("queued", "running"):
        if runtime_doc_status:
            merged["status"] = runtime_doc_status

    if not merged["status"]:
        merged["status"] = "unknown"

    return func.HttpResponse(
        json.dumps({"ok": True, "analysis": merged}),
        mimetype="application/json"
    )