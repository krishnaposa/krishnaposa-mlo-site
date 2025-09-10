import azure.functions as func
from shared import blob_client, get_status

def main(req: func.HttpRequest) -> func.HttpResponse:
    job_id = req.route_params.get("job_id")
    if not job_id:
        return func.HttpResponse("Missing job_id", status_code=400)

    st = get_status(blob_client(), job_id)
    if not st:
        return func.HttpResponse('{"state":"unknown"}', mimetype="application/json", status_code=404)
    return func.HttpResponse(
        body=st if isinstance(st, (str, bytes)) else None,
        mimetype="application/json",
        status_code=200
    )