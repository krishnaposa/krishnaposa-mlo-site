from shared import cosmos
from datetime import datetime, timezone

def main(payload: dict):
  doc = cosmos.get_doc(payload["id"])
  if not doc:
    return {"ok": False, "error": "not found"}

  doc["status"] = payload.get("status", doc.get("status", "queued"))
  if payload.get("error"):
    doc["error"] = payload["error"]
  if payload.get("estimates") is not None:
    doc["estimates"] = payload["estimates"]
  if payload.get("metrics") is not None:
    doc["metrics"] = payload["metrics"]
  if payload.get("verdict") is not None:
    doc["verdict"] = payload["verdict"]
  if payload.get("reasons") is not None:
    doc["reasons"] = payload["reasons"]

  doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
  cosmos.upsert_doc(doc)
  return {"ok": True}