from shared import cosmos

def main(payload: dict):
    doc = cosmos.get_doc(payload["id"])
    if not doc: return False
    doc["pulls"] = payload.get("pulls", doc.get("pulls"))
    doc["estimates"] = payload.get("estimates", {})
    doc["metrics"] = payload.get("metrics", {})
    doc["verdict"] = payload.get("verdict")
    doc["reasons"] = payload.get("reasons")
    doc["status"] = "done"
    cosmos.upsert_doc(doc)
    return True