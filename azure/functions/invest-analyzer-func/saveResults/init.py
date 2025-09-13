try:
    from shared import cosmos
except ImportError:
    cosmos = None

def main(payload: dict):
    """
    Activity to save final analysis results into Cosmos DB.
    Payload is expected to include:
      - id
      - pulls, estimates, metrics, verdict, reasons
    """
    if not payload or "id" not in payload:
        return {"ok": False, "error": "Missing id in payload"}

    if cosmos:
        try:
            # Get existing doc or create new
            doc = cosmos.get_doc(payload["id"]) or {"id": payload["id"]}
            # Update fields
            for k in ("pulls", "estimates", "metrics", "verdict", "reasons"):
                if k in payload:
                    doc[k] = payload[k]
            doc["status"] = "done"
            cosmos.upsert_doc(doc)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # If Cosmos helper not available, just echo payload back
    return {"ok": True, "note": "Cosmos not configured", "data": payload}