from azure.durable_functions import OrchestratorContext

def main(context: OrchestratorContext):
    data = context.get_input() or {}
    analysis_id = data.get("id")

    # Fan-out activities
    pulls = yield context.call_activity("Activities-GatherData", analysis_id)
    estimates = yield context.call_activity("Activities-ComputeMetrics", pulls)
    verdict = yield context.call_activity("Activities-DecideVerdict", estimates)

    # Save & mark done
    _ = yield context.call_activity("Activities-SaveResults", {
        "id": analysis_id,
        "pulls": pulls,
        "estimates": estimates,
        "metrics": verdict["metrics"],
        "verdict": verdict["verdict"],
        "reasons": verdict["reasons"]
    })

    return {"id": analysis_id, "status": "done"}