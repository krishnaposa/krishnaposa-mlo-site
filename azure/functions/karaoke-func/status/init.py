import json
import azure.functions as func
from shared import get_status

def main(req: func.HttpRequest) -> func.HttpResponse:
    job_id = req.route_params.get("job_id","")
    s = get_status(job_id)
    if not s:
        return func.HttpResponse(status_code=404)
    return func.HttpResponse(json.dumps(s), mimetype="application/json")