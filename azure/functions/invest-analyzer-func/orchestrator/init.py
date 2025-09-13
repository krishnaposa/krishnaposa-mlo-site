# orchestrator/__init__.py
import azure.durable_functions as df

def run(context):
    context.set_custom_status({"step": "start"})
    data = context.get_input() or {}
    analysis_id = data.get("id")

    # Update Cosmos -> running
    yield context.call_activity("Activities-MarkStatus", {
        "id": analysis_id,
        "status": "running"
    })

    # Fan-out work
    pulls = yield context.call_activity("Activities-GatherData", analysis_id)
    context.set_custom_status({"step": "gather_done", "id": analysis_id})

    estimates = yield context.call_activity("Activities-ComputeMetrics", pulls)
    context.set_custom_status({"step": "metrics_done", "id": analysis_id})

    verdict = yield context.call_activity("Activities-DecideVerdict", estimates)
    context.set_custom_status({"step": "verdict_done", "id": analysis_id})

    # Save results + mark done in Cosmos
    yield context.call_activity("Activities-SaveResults", {
        "id": analysis_id,
        "pulls": pulls,
        "estimates": estimates,
        "metrics": verdict.get("metrics"),
        "verdict": verdict.get("verdict"),
        "reasons": verdict.get("reasons")
    })
    yield context.call_activity("Activities-MarkStatus", {
        "id": analysis_id,
        "status": "done",
        "pulls": pulls,
        "estimates": estimates,
        "metrics": verdict.get("metrics"),
        "verdict": verdict.get("verdict"),
        "reasons": verdict.get("reasons")
    })

    context.set_custom_status({"step": "saved", "id": analysis_id})
    return {"id": analysis_id, "status": "done"}

# IMPORTANT
main = df.Orchestrator.create(run)