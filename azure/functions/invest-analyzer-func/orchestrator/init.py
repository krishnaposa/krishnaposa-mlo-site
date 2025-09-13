# orchestrator/__init__.py
import azure.durable_functions as df

def run(ctx):
    data = ctx.get_input() or {}
    analysis_id = data.get("id")
    if not analysis_id:
        # no id → nothing to do
        return {"status": "error", "error": "missing analysis id"}

    # Retry policy for flaky activities (3 attempts, backoff 5s)
    retry = df.RetryOptions(first_retry_interval_in_milliseconds=5000, max_number_of_attempts=3)

    try:
        # Mark running in Cosmos
        yield ctx.call_activity("markStatus", {"id": analysis_id, "status": "running"})

        # Activities (with retries)
        pulls = yield ctx.call_activity_with_retry("gatherData", retry, analysis_id)
        bundle = yield ctx.call_activity_with_retry("computeMetrics", retry, pulls)
        verdict = yield ctx.call_activity_with_retry("decideVerdict", retry, bundle)

        # Persist final results
        payload = {
            "id": analysis_id,
            "pulls": pulls,
            "estimates": verdict.get("estimates") or bundle.get("estimates"),
            "metrics": verdict.get("metrics"),
            "verdict": verdict.get("verdict"),
            "reasons": verdict.get("reasons"),
        }
        yield ctx.call_activity_with_retry("saveResults", retry, payload)

        # Also set explicit done (belt-and-suspenders)
        payload["status"] = "done"
        yield ctx.call_activity("markStatus", payload)

        return {"id": analysis_id, "status": "done"}

    except Exception as e:
        # Persist the failure so /api/status shows it
        yield ctx.call_activity("markStatus", {"id": analysis_id, "status": "error", "error": str(e)})
        # Re-raise so Durable marks the instance Failed (visible in Portal)
        raise

main = df.Orchestrator.create(run)