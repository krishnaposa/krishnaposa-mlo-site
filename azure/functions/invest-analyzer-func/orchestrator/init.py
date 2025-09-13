# orchestrator/__init__.py
import azure.durable_functions as df

def run(context):
    data = context.get_input() or {}
    analysis_id = data.get("id")

    # set Cosmos -> running
    yield context.call_activity("markStatus", {"id": analysis_id, "status": "running"})

    pulls = yield context.call_activity("gatherData", analysis_id)
    estimates = yield context.call_activity("computeMetrics", pulls)
    verdict   = yield context.call_activity("decideVerdict", estimates)

    yield context.call_activity("saveResults", {
        "id": analysis_id,
        "pulls": pulls,
        "estimates": estimates,
        "metrics": verdict.get("metrics"),
        "verdict": verdict.get("verdict"),
        "reasons": verdict.get("reasons")
    })

    yield context.call_activity("markStatus", {
        "id": analysis_id,
        "status": "done",
        "pulls": pulls,
        "estimates": estimates,
        "metrics": verdict.get("metrics"),
        "verdict": verdict.get("verdict"),
        "reasons": verdict.get("reasons")
    })

    return {"id": analysis_id, "status": "done"}

main = df.Orchestrator.create(run)