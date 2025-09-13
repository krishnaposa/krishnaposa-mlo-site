from shared import cosmos
from datetime import datetime, timezone

def main(payload: dict):
    doc = cosmos.get_doc(payload["id"])
    if not doc:
        return {"ok": False, "error": "doc not found"}

    # update fields if provided
    if "status" in payload:
        doc["status"] = payload["status"]
    if "error" in payload:
        doc["error"] = payload["error"]
    if "pulls" in payload:
        doc["pulls"] = payload["pulls"]
    if "estimates" in payload:
        doc["estimates"] = payload["estimates"]
    if "metrics" in payload:
        doc["metrics"] = payload["metrics"]
    if "verdict" in payload:
        doc["verdict"] = payload["verdict"]
    if "reasons" in payload:
        doc["reasons"] = payload["reasons"]

    doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
    cosmos.upsert_doc(doc)
    return {"ok": True}